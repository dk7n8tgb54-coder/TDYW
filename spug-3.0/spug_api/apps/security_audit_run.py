"""
安全短板 P1-P3 验证脚本

不依赖 Django 测试数据库，直接在 shell 中运行:
    docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
        python manage.py shell -c "exec(open('apps/security_audit_run.py').read())"

或:
    docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
        python -c "import django; django.setup(); exec(open('apps/security_audit_run.py').read())"
"""
import os
import re
import inspect
import sys

# 由于通过 shell -c 执行，Django 已初始化
from django.conf import settings

# 结果收集
results = []

def check(code, claim, condition, detail_true="", detail_false=""):
    """记录一条验证结果"""
    status = "TRUE (短板存在)" if condition else "FALSE (声称为假)"
    results.append((code, claim, status, detail_true if condition else detail_false))
    symbol = "⚠️" if condition else "✅"
    print(f"  {code} {symbol} {claim}")
    print(f"        -> {status}")
    detail = detail_true if condition else detail_false
    if detail:
        print(f"        -> {detail}")
    print()


print("=" * 70)
print("  安全短板 P1-P3 验证")
print("=" * 70)
print()
print("  解读: TRUE = 短板确实存在 (声称为真)")
print("         FALSE = 短板不存在 (声称为假，措施已有)")
print()
print("-" * 70)
print("  P1-1: 声称「无密码复杂度策略」")
print("-" * 70)

# P1-1: 密码复杂度策略
try:
    from apps.account.utils import verify_password

    weak_rejected = not verify_password('123456')
    short_rejected = not verify_password('Ab1!')
    no_digit_rejected = not verify_password('Abcdefg!')
    no_upper_rejected = not verify_password('abcdef1!')
    no_special_rejected = not verify_password('Abcdef12')
    strong_accepted = verify_password('Test@1234')

    all_checks = all([weak_rejected, short_rejected, no_digit_rejected,
                      no_upper_rejected, no_special_rejected, strong_accepted])

    check("P1-1", "无密码复杂度策略",
          condition=not all_checks,
          detail_true="密码策略不存在或未生效",
          detail_false=f"策略 EXISTS: 弱密码被拒={weak_rejected}, 短密码被拒={short_rejected}, "
                       f"无数字被拒={no_digit_rejected}, 无大写被拒={no_upper_rejected}, "
                       f"无特殊字符被拒={no_special_rejected}, 强密码通过={strong_accepted}")

    # 验证 verify_password 在 views.py 中被调用
    from apps.account import views as account_views
    views_source = inspect.getsource(account_views)
    called_in_views = 'verify_password' in views_source
    if not called_in_views:
        results[-1] = ("P1-1", "无密码复杂度策略", "TRUE (短板存在)",
                       "verify_password 未在 views.py 中调用")
        print(f"        -> ⚠️ verify_password 未在 account/views.py 中调用!")
        print()
except Exception as e:
    check("P1-1", "无密码复杂度策略", True, f"验证异常: {e}")


print("-" * 70)
print("  P1-2: 声称「Redis 默认无密码」")
print("-" * 70)

# P1-2: Redis 默认无密码
try:
    import importlib
    import spug.settings as spug_settings

    # 保存原始环境变量
    original_redis_pwd = os.environ.get('REDIS_PASSWORD', None)

    # 测试 1: 不设置环境变量时的默认值
    os.environ.pop('REDIS_PASSWORD', None)
    importlib.reload(spug_settings)
    default_pwd = spug_settings._REDIS_PASSWORD
    redis_url_no_pwd = spug_settings._REDIS_URL

    # 恢复环境变量
    if original_redis_pwd is not None:
        os.environ['REDIS_PASSWORD'] = original_redis_pwd
    importlib.reload(spug_settings)

    check("P1-2", "Redis 默认无密码",
          condition=(default_pwd == ''),
          detail_true=f"未设置 REDIS_PASSWORD 时默认值为空, URL={redis_url_no_pwd}",
          detail_false=f"默认值非空: '{default_pwd}'")

    # 报告当前运行环境的 Redis 密码状态
    current_redis_url = settings.CACHES['default']['LOCATION']
    current_has_pwd = '@' in current_redis_url
    print(f"        -> [当前环境] Redis URL: {current_redis_url}")
    print(f"        -> [当前环境] Redis 有密码: {'是' if current_has_pwd else '否'}")
    print()
except Exception as e:
    check("P1-2", "Redis 默认无密码", True, f"验证异常: {e}")


print("-" * 70)
print("  P2-1: 声称「无文件类型白名单」(document 模块)")
print("-" * 70)

# P2-1: 文件类型白名单
try:
    from apps.document.libs.view_utils import validate_file_name

    dangerous_files = ['malicious.py', 'shell.sh', 'xss.html', 'backdoor.php',
                       'trojan.exe', 'script.bat', 'webshell.jsp']
    passed = []
    for f in dangerous_files:
        try:
            validate_file_name(f)
            passed.append(f)
        except Exception:
            pass

    check("P2-1", "document 模块无文件类型白名单",
          condition=(len(passed) > 0),
          detail_true=f"危险扩展名通过校验: {passed}",
          detail_false="所有危险扩展名都被拒绝 (可能有白名单)")

    # 对比: evidence 模块
    from apps.evidence import attachment_service
    evidence_source = inspect.getsource(attachment_service)
    evidence_has_whitelist = bool(re.search(r'allowed_ext|ALLOWED_EXT|extension', evidence_source, re.IGNORECASE))
    print(f"        -> [对比] evidence 模块有白名单: {'是' if evidence_has_whitelist else '否'}")
    print()
except Exception as e:
    check("P2-1", "无文件类型白名单", True, f"验证异常: {e}")


print("-" * 70)
print("  P2-2: 声称「无请求体大小限制」")
print("-" * 70)

# P2-2: Nginx 请求体大小限制
try:
    nginx_paths = [
        os.path.join(settings.BASE_DIR, '..', 'docker', 'config', 'nginx.conf'),
        '/data/spug/docker/config/nginx.conf',
    ]
    nginx_conf = None
    for path in nginx_paths:
        path = os.path.normpath(path)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                nginx_conf = f.read()
            break

    if nginx_conf:
        # 检查 HTTPS server 块
        https_start = nginx_conf.find('listen 443')
        https_block = nginx_conf[https_start:] if https_start != -1 else ''
        has_unlimited = 'client_max_body_size 0' in https_block

        check("P2-2a", "Nginx HTTPS 无 body 大小限制",
              condition=has_unlimited,
              detail_true="HTTPS server 块有 client_max_body_size 0 (无限制)",
              detail_false="未找到 client_max_body_size 0")

        # 检查 /api/ location 块
        api_match = re.search(r'location\s+\^~\s*/api/\s*\{', nginx_conf)
        api_has_limit = False
        if api_match:
            start = api_match.start()
            depth = 0
            end = start
            for i in range(api_match.end() - 1, len(nginx_conf)):
                if nginx_conf[i] == '{':
                    depth += 1
                elif nginx_conf[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            api_block = nginx_conf[start:end]
            api_has_limit = 'client_max_body_size' in api_block

        check("P2-2b", "/api/ location 无独立 body 限制",
              condition=not api_has_limit,
              detail_true="/api/ 继承 HTTPS server 的 client_max_body_size 0 (无限制)",
              detail_false="/api/ 有独立的 client_max_body_size")
    else:
        check("P2-2", "Nginx 无 body 大小限制", True, "nginx.conf 未找到，无法验证")

    # Django 层面
    django_limit = getattr(settings, 'DATA_UPLOAD_MAX_MEMORY_SIZE', 2621440)
    print(f"        -> [Django] DATA_UPLOAD_MAX_MEMORY_SIZE = {django_limit} bytes "
          f"({django_limit / 1024 / 1024:.1f} MB, 仅限非文件字段)")
    print()
except Exception as e:
    check("P2-2", "无请求体大小限制", True, f"验证异常: {e}")


print("-" * 70)
print("  P3-1: 声称「无会话超时自动登出」")
print("-" * 70)

# P3-1: 会话超时
try:
    token_ttl = getattr(settings, 'TOKEN_TTL', None)
    has_idle_timeout = (
        hasattr(settings, 'IDLE_TIMEOUT') or
        hasattr(settings, 'SESSION_IDLE_TIMEOUT') or
        hasattr(settings, 'IDLE_SESSION_TIMEOUT')
    )

    # 检查认证中间件是否有 TTL 刷新逻辑（滑动过期）
    from libs import middleware
    middleware_source = inspect.getsource(middleware)
    has_sliding = bool(re.search(r'expire|ttl.*refresh|refresh.*ttl|extend.*ttl|renew',
                                  middleware_source, re.IGNORECASE))

    check("P3-1", "无闲置超时自动登出",
          condition=(not has_idle_timeout),
          detail_true=f"TOKEN_TTL={token_ttl}s ({token_ttl/3600:.0f}h), 无 IDLE_TIMEOUT 配置, "
                      f"滑动过期={has_sliding}",
          detail_false="存在闲置超时配置")

    print(f"        -> TOKEN_TTL = {token_ttl}s ({token_ttl/3600:.0f} 小时)")
    print(f"        -> 有闲置超时配置: {has_idle_timeout}")
    print(f"        -> 有滑动过期(活动刷新TTL): {has_sliding}")
    print()
except Exception as e:
    check("P3-1", "无会话超时自动登出", True, f"验证异常: {e}")


print("-" * 70)
print("  P3-2: 声称「数据库密码可能为空或弱」")
print("-" * 70)

# P3-2: 数据库密码
try:
    db_password = settings.DATABASES['default'].get('PASSWORD')

    is_none = db_password is None
    is_empty = db_password == ''
    is_short = db_password is not None and db_password != '' and len(db_password) < 8

    # 验证密码来源是环境变量
    import spug.settings as spug_settings
    settings_source = inspect.getsource(spug_settings)
    from_env = bool(re.search(r'PASSWORD.*os\.environ|os\.environ.*PASSWORD', settings_source))

    condition = is_none or is_empty or is_short

    details = []
    if is_none:
        details.append("密码为 None (MYSQL_PASSWORD 环境变量未设置)")
    if is_empty:
        details.append("密码为空字符串")
    if is_short:
        details.append(f"密码仅 {len(db_password)} 位 (< 8)")
    if from_env:
        details.append("密码来自环境变量 (部署时可能未设置)")
    if not details:
        details.append(f"密码长度 {len(db_password)} 位, 来自环境变量, 配置正常")

    check("P3-2", "数据库密码可能为空或弱",
          condition=condition,
          detail_true="; ".join(details),
          detail_false="; ".join(details))

    if db_password:
        print(f"        -> 密码长度: {len(db_password)} 位")
    else:
        print(f"        -> 密码: {db_password}")
    print(f"        -> 密码来自环境变量: {from_env}")
    print()
except Exception as e:
    check("P3-2", "数据库密码可能为空或弱", True, f"验证异常: {e}")


print("-" * 70)
print("  额外发现 1: SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE 未设置")
print("-" * 70)

# 额外: 安全 Cookie
try:
    session_secure = getattr(settings, 'SESSION_COOKIE_SECURE', False)
    csrf_secure = getattr(settings, 'CSRF_COOKIE_SECURE', False)
    session_samesite = getattr(settings, 'SESSION_COOKIE_SAMESITE', None)

    check("额外-1a", "SESSION_COOKIE_SECURE 未设置",
          condition=(not session_secure),
          detail_true=f"SESSION_COOKIE_SECURE = {session_secure} (应为 True)",
          detail_false=f"SESSION_COOKIE_SECURE = {session_secure}")

    check("额外-1b", "CSRF_COOKIE_SECURE 未设置",
          condition=(not csrf_secure),
          detail_true=f"CSRF_COOKIE_SECURE = {csrf_secure} (应为 True)",
          detail_false=f"CSRF_COOKIE_SECURE = {csrf_secure}")

    check("额外-1c", "SESSION_COOKIE_SAMESITE 未设置",
          condition=(session_samesite is None),
          detail_true=f"SESSION_COOKIE_SAMESITE = {session_samesite} (应设为 'Lax' 或 'Strict')",
          detail_false=f"SESSION_COOKIE_SAMESITE = {session_samesite}")
    print()
except Exception as e:
    check("额外-1", "安全 Cookie 未设置", True, f"验证异常: {e}")


print("-" * 70)
print("  额外发现 2: Nginx limit_req_zone 已定义但未应用")
print("-" * 70)

# 额外: Nginx 限流
try:
    nginx_paths = [
        os.path.join(settings.BASE_DIR, '..', 'docker', 'config', 'nginx.conf'),
        '/data/spug/docker/config/nginx.conf',
    ]
    nginx_conf = None
    for path in nginx_paths:
        path = os.path.normpath(path)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                nginx_conf = f.read()
            break

    if nginx_conf:
        zones_defined = 'limit_req_zone' in nginx_conf
        # 搜索 limit_req 指令（排除 limit_req_zone 定义）
        limit_req_count = len(re.findall(r'^\s*limit_req\s+zone=', nginx_conf, re.MULTILINE))

        check("额外-2", "Nginx 限流 zone 已定义但未在 location 中应用",
              condition=(zones_defined and limit_req_count == 0),
              detail_true=f"定义了 limit_req_zone 但未找到任何 limit_req 指令 (zone 定义有 {zones_defined}, "
                          f"实际应用 {limit_req_count} 处)",
              detail_false=f"limit_req 已应用 {limit_req_count} 处")
    else:
        check("额外-2", "Nginx 限流未应用", True, "nginx.conf 未找到")
    print()
except Exception as e:
    check("额外-2", "Nginx 限流未应用", True, f"验证异常: {e}")


# ==========================================================================
# 汇总报告
# ==========================================================================
print("=" * 70)
print("  汇总报告")
print("=" * 70)
print()
print(f"  {'编号':<10} {'声称':<30} {'验证结果':<25} {'说明'}")
print(f"  {'-'*10} {'-'*30} {'-'*25} {'-'*40}")

for code, claim, status, detail in results:
    symbol = "⚠️" if "TRUE" in status else "✅"
    short_detail = detail[:40] + "..." if len(detail) > 40 else detail
    print(f"  {code:<10} {symbol} {claim:<28} {status:<25} {short_detail}")

print()
print("=" * 70)
print("  结论:")
true_count = sum(1 for _, _, s, _ in results if "TRUE" in s)
false_count = sum(1 for _, _, s, _ in results if "FALSE" in s)
print(f"  声称为真 (短板存在): {true_count} 项")
print(f"  声称为假 (措施已有): {false_count} 项")
print("=" * 70)
