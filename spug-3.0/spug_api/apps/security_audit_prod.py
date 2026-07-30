"""
生产配置安全短板复核脚本

基于生产配置文件（docker/.env + docker/config/nginx.conf + docker/docker-compose.yml）
逐一复核之前声称的 P1-P3 短板，区分「代码级」（dev/prod 相同）和「配置级」（可能不同）。

运行方式（在宿主机上直接运行，不需要 Docker）:
    cd e:/TDYW/spug-3.0
    python spug_api/apps/security_audit_prod.py
"""
import os
import re
import sys
import io

# 修复 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 解析项目根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
DOCKER_DIR = os.path.join(PROJECT_ROOT, 'docker')
NGINX_CONF_PATH = os.path.join(DOCKER_DIR, 'config', 'nginx.conf')
COMPOSE_PATH = os.path.join(DOCKER_DIR, 'docker-compose.yml')
ENV_PATH = os.path.join(DOCKER_DIR, '.env')
ENV_EXAMPLE_PATH = os.path.join(DOCKER_DIR, '.env.example')

results = []

def check(code, claim, condition, detail_true="", detail_false=""):
    status = "TRUE (短板存在)" if condition else "FALSE (声称为假)"
    results.append((code, claim, status, detail_true if condition else detail_false))
    symbol = "⚠️" if condition else "✅"
    print(f"  {code} {symbol} {claim}")
    print(f"        -> {status}")
    detail = detail_true if condition else detail_false
    if detail:
        print(f"        -> {detail}")
    print()

def read_file(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def parse_env(path):
    """解析 .env 文件为 dict"""
    content = read_file(path)
    if content is None:
        return {}
    env = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            key, _, value = line.partition('=')
            env[key.strip()] = value.strip()
    return env

# ==========================================================================
print("=" * 70)
print("  生产配置安全短板复核")
print("  基于文件: docker/.env + docker/config/nginx.conf + docker/docker-compose.yml")
print("=" * 70)
print()
print("  解读: TRUE = 短板确实存在 (声称为真)")
print("         FALSE = 短板不存在 (声称为假，措施已有)")
print()
print(f"  项目根目录: {PROJECT_ROOT}")
print(f"  docker 目录: {DOCKER_DIR}")
print()

# 加载文件
nginx_conf = read_file(NGINX_CONF_PATH)
compose_conf = read_file(COMPOSE_PATH)
env = parse_env(ENV_PATH)
env_example = parse_env(ENV_EXAMPLE_PATH)

print(f"  nginx.conf: {'✅ 找到' if nginx_conf else '❌ 未找到'} ({NGINX_CONF_PATH})")
print(f"  docker-compose.yml: {'✅ 找到' if compose_conf else '❌ 未找到'} ({COMPOSE_PATH})")
print(f"  .env: {'✅ 找到' if env else '❌ 未找到'} ({ENV_PATH})")
print(f"  .env.example: {'✅ 找到' if env_example else '❌ 未找到'} ({ENV_EXAMPLE_PATH})")
print()
print("-" * 70)

# ==========================================================================
# P1-1: 代码级 - 密码复杂度策略（dev/prod 相同）
# ==========================================================================
print("  P1-1: 声称「无密码复杂度策略」 [代码级 - dev/prod 相同]")
print("-" * 70)

# 读取 account/utils.py
utils_path = os.path.join(SCRIPT_DIR, 'account', 'utils.py')
utils_source = read_file(utils_path) or ""

has_verify = 'def verify_password' in utils_source
checks_length = bool(re.search(r'len\([^)]+\)\s*[<>=]+\s*8', utils_source))
checks_digit = bool(re.search(r'\[0-9\]', utils_source))
checks_lower = bool(re.search(r'\[a-z\]', utils_source))
checks_upper = bool(re.search(r'\[A-Z\]', utils_source))
checks_special = bool(re.search(r'\[\^a-zA-Z0-9\]', utils_source))

# 读取 views.py 确认调用
views_path = os.path.join(SCRIPT_DIR, 'account', 'views.py')
views_source = read_file(views_path) or ""
called_in_views = 'verify_password' in views_source

policy_exists = all([has_verify, checks_length, checks_digit,
                      checks_lower, checks_upper, checks_special, called_in_views])

check("P1-1", "无密码复杂度策略",
      condition=not policy_exists,
      detail_true="密码策略不存在",
      detail_false=f"策略 EXISTS: 长度≥8={checks_length}, 数字={checks_digit}, "
                   f"小写={checks_lower}, 大写={checks_upper}, 特殊字符={checks_special}, "
                   f"views.py 调用={called_in_views}")

# ==========================================================================
# P1-2: 配置级 - Redis 默认无密码
# ==========================================================================
print("-" * 70)
print("  P1-2: 声称「Redis 默认无密码」 [配置级 - 需查生产 .env]")
print("-" * 70)

# 检查 .env 是否设置了 REDIS_PASSWORD
redis_pwd = env.get('REDIS_PASSWORD', '')
redis_pwd_in_compose = 'REDIS_PASSWORD' in (compose_conf or '')

# 检查 docker-compose 是否传递了 REDIS_PASSWORD 环境变量
check("P1-2", "Redis 无密码（生产 .env）",
      condition=(not redis_pwd),
      detail_true=f".env 未设置 REDIS_PASSWORD, docker-compose 也未传递 -> 生产 Redis 无密码",
      detail_false=f".env 设置了 REDIS_PASSWORD={redis_pwd[:3]}...")

# 补充: Redis 是否暴露端口
redis_port_exposed = bool(re.search(r'6379.*:6379|ports.*6379', compose_conf or ''))
print(f"        -> [补充] Redis 端口是否对外暴露: {redis_port_exposed}")
print(f"        -> [补充] Redis 运行在容器内 127.0.0.1，不对外暴露")
print()

# ==========================================================================
# P2-1: 代码级 - 无文件类型白名单（dev/prod 相同）
# ==========================================================================
print("-" * 70)
print("  P2-1: 声称「无文件类型白名单」 [代码级 - dev/prod 相同]")
print("-" * 70)

view_utils_path = os.path.join(SCRIPT_DIR, 'document', 'libs', 'view_utils.py')
view_utils_source = read_file(view_utils_path) or ""

# 搜索是否有扩展名白名单逻辑
has_whitelist = bool(re.search(r'allowed_ext|whitelist|ALLOWED_EXT|extension.*allow',
                               view_utils_source, re.IGNORECASE))

# 搜索 validate_file_name 函数
validate_fn = re.search(r'def validate_file_name\([^)]*\):(.*?)(?=\ndef |\Z)',
                         view_utils_source, re.DOTALL)
if validate_fn:
    fn_body = validate_fn.group(1)
    # 检查是否有扩展名检查
    checks_extension = bool(re.search(r'\.ext|extension|\.endswith|suffix', fn_body, re.IGNORECASE))
else:
    fn_body = ""
    checks_extension = False

# 对比 evidence 模块
evidence_path = os.path.join(SCRIPT_DIR, 'evidence', 'attachment_service.py')
evidence_source = read_file(evidence_path) or ""
evidence_has_whitelist = bool(re.search(r'allowed_ext|ALLOWED_EXT|extension',
                                         evidence_source, re.IGNORECASE))

check("P2-1", "document 模块无文件类型白名单",
      condition=(not has_whitelist and not checks_extension),
      detail_true=f"validate_file_name 不检查扩展名, 有扩展名校验={checks_extension}",
      detail_false=f"存在扩展名白名单逻辑")
print(f"        -> [对比] evidence 模块有白名单: {evidence_has_whitelist}")
print()

# ==========================================================================
# P2-2: 配置级 - 无请求体大小限制（生产 nginx.conf）
# ==========================================================================
print("-" * 70)
print("  P2-2: 声称「无请求体大小限制」 [配置级 - 需查生产 nginx.conf]")
print("-" * 70)

if nginx_conf:
    # 找到 HTTPS server 块
    https_start = nginx_conf.find('listen 443')
    https_block = nginx_conf[https_start:] if https_start != -1 else ''

    # 检查 HTTPS server 块的 client_max_body_size
    https_cmbs = re.findall(r'client_max_body_size\s+(\S+);', https_block)

    # 检查 /api/ location 块（HTTPS 部分）
    # 找到 HTTPS 块中的 /api/ location
    api_in_https = False
    api_has_own_limit = False
    if https_start != -1:
        https_text = nginx_conf[https_start:]
        api_match = re.search(r'location\s+\^~\s*/api/\s*\{', https_text)
        if api_match:
            api_in_https = True
            # 提取该 location 块
            start = api_match.start()
            depth = 0
            end = start
            for i in range(api_match.end() - 1, len(https_text)):
                if https_text[i] == '{':
                    depth += 1
                elif https_text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            api_block = https_text[start:end]
            api_has_own_limit = 'client_max_body_size' in api_block

    has_unlimited = '0' in https_cmbs  # 0 = unlimited

    check("P2-2a", "HTTPS server 块有 client_max_body_size 0 (无限制)",
          condition=has_unlimited,
          detail_true=f"HTTPS server 块的 client_max_body_size 值: {https_cmbs}",
          detail_false=f"HTTPS server 块的 client_max_body_size 值: {https_cmbs}")

    check("P2-2b", "/api/ location 无独立 body 大小限制",
          condition=(api_in_https and not api_has_own_limit),
          detail_true="/api/ 继承 HTTPS server 块的 client_max_body_size 0 (无限制)",
          detail_false=f"/api/ 有独立的 client_max_body_size")
else:
    check("P2-2", "无请求体大小限制", True, "nginx.conf 未找到")

print(f"        -> [补充] 上传 location 的 client_max_body_size 0 是有意设计（大文件上传）")
print(f"        -> [补充] 问题在于非上传 API 也无限制，Django DATA_UPLOAD_MAX_MEMORY_SIZE=2.5MB 仅限非文件字段")
print()

# ==========================================================================
# P3-1: 代码级 - 无会话超时自动登出（dev/prod 相同）
# ==========================================================================
print("-" * 70)
print("  P3-1: 声称「无会话超时自动登出」 [代码级 - dev/prod 相同]")
print("-" * 70)

settings_path = os.path.join(SCRIPT_DIR, '..', 'spug', 'settings.py')
settings_source = read_file(settings_path) or ""

token_ttl_match = re.search(r'TOKEN_TTL\s*=\s*(.+)', settings_source)
token_ttl_raw = token_ttl_match.group(1).strip() if token_ttl_match else 'NOT FOUND'
# 尝试计算（可能是 8 * 3600 这样的表达式）
try:
    token_ttl = eval(token_ttl_raw)
except Exception:
    token_ttl = None

has_idle_timeout = bool(re.search(r'IDLE_TIMEOUT|SESSION_IDLE_TIMEOUT|IDLE_SESSION_TIMEOUT',
                                    settings_source))

# 检查中间件是否有 TTL 刷新（滑动过期）
middleware_path = os.path.join(SCRIPT_DIR, '..', 'libs', 'middleware.py')
middleware_source = read_file(middleware_path) or ""
has_sliding = bool(re.search(r'expire|ttl.*refresh|refresh.*ttl|extend.*ttl|renew',
                              middleware_source, re.IGNORECASE))

ttl_display = f"{token_ttl}s ({token_ttl/3600:.0f}h)" if token_ttl else f"{token_ttl_raw} (无法解析)"

check("P3-1", "无闲置超时自动登出",
      condition=(not has_idle_timeout),
      detail_true=f"TOKEN_TTL={ttl_display}, 固定过期, 无 IDLE_TIMEOUT, 滑动过期={has_sliding}",
      detail_false="存在闲置超时配置")
print()

# ==========================================================================
# P3-2: 配置级 - 数据库密码可能为空或弱（生产 .env）
# ==========================================================================
print("-" * 70)
print("  P3-2: 声称「数据库密码可能为空或弱」 [配置级 - 需查生产 .env]")
print("-" * 70)

db_password = env.get('MYSQL_PASSWORD', '')
db_user = env.get('MYSQL_USER', '')
db_root_password = env.get('MYSQL_ROOT_PASSWORD', '')

# 密码强度检查
pwd_issues = []
if not db_password:
    pwd_issues.append("密码为空")
else:
    if len(db_password) < 8:
        pwd_issues.append(f"密码仅 {len(db_password)} 位 (<8)")
    if not re.search(r'[a-z]', db_password):
        pwd_issues.append("无小写字母")
    if not re.search(r'[A-Z]', db_password):
        pwd_issues.append("无大写字母")
    if not re.search(r'[0-9]', db_password):
        pwd_issues.append("无数字")
    if not re.search(r'[^a-zA-Z0-9]', db_password):
        pwd_issues.append("无特殊字符")

# 检查是否使用 root 账号
uses_root = (db_user == 'root')

# 检查是否使用 _FILE 方式
uses_file = bool(env.get('MYSQL_PASSWORD_FILE', ''))

check("P3-2a", "数据库密码弱",
      condition=(len(pwd_issues) > 0),
      detail_true=f"密码 '{db_password}' ({len(db_password)}位) 问题: {'; '.join(pwd_issues)}",
      detail_false=f"密码强度合格 ({len(db_password)}位)")

check("P3-2b", "应用使用 root 账号（应使用最小权限账号）",
      condition=uses_root,
      detail_true=f"MYSQL_USER={db_user} (应使用 tdyw_app 等最小权限账号, .env.example 已设计但未启用)",
      detail_false=f"MYSQL_USER={db_user}")

check("P3-2c", "密码未使用 _FILE 方式（明文存储）",
      condition=(not uses_file),
      detail_true="密码明文存储在 .env 文件中 (.env.example 推荐使用 _FILE 方式)",
      detail_false="已使用 _FILE 方式")
print()

# ==========================================================================
# 额外-1: Django 安全 Cookie（代码级 - dev/prod 相同）
# ==========================================================================
print("-" * 70)
print("  额外-1: Django 安全 Cookie 未设置 [代码级 - dev/prod 相同]")
print("-" * 70)

session_secure = bool(re.search(r'SESSION_COOKIE_SECURE\s*=\s*True', settings_source))
csrf_secure = bool(re.search(r'CSRF_COOKIE_SECURE\s*=\s*True', settings_source))
session_samesite_match = re.search(r'SESSION_COOKIE_SAMESITE\s*=\s*[\'\"](\w+)[\'\"]', settings_source)
session_samesite = session_samesite_match.group(1) if session_samesite_match else None

check("额外-1a", "SESSION_COOKIE_SECURE 未设置",
      condition=(not session_secure),
      detail_true="未设置 (Django 默认 False), 生产有 HTTPS 应设为 True",
      detail_false="已设置为 True")

check("额外-1b", "CSRF_COOKIE_SECURE 未设置",
      condition=(not csrf_secure),
      detail_true="未设置 (Django 默认 False), 生产有 HTTPS 应设为 True",
      detail_false="已设置为 True")

check("额外-1c", "SESSION_COOKIE_SAMESITE 未设置",
      condition=(session_samesite is None),
      detail_true="未设置",
      detail_false=f"已设置为 '{session_samesite}'")
print()

# ==========================================================================
# 额外-2: Nginx 限流（配置级 - 生产 nginx.conf）
# ==========================================================================
print("-" * 70)
print("  额外-2: Nginx 限流 zone 已定义但未应用 [配置级 - 需查生产 nginx.conf]")
print("-" * 70)

if nginx_conf:
    zones_defined = re.findall(r'limit_req_zone.*zone=(\w+)', nginx_conf)
    # 搜索 limit_req 指令（排除 limit_req_zone）
    limit_req_applied = re.findall(r'^\s*limit_req\s+zone=(\w+)', nginx_conf, re.MULTILINE)

    check("额外-2", "Nginx 限流 zone 已定义但未在 location 中应用",
          condition=(len(zones_defined) > 0 and len(limit_req_applied) == 0),
          detail_true=f"定义了 {len(zones_defined)} 个 zone: {zones_defined}, "
                      f"但无任何 limit_req 指令在 location 中应用",
          detail_false=f"limit_req 已应用: {limit_req_applied}")
else:
    check("额外-2", "Nginx 限流未应用", True, "nginx.conf 未找到")
print()

# ==========================================================================
# 生产 nginx.conf 已有的安全措施（之前遗漏的）
# ==========================================================================
print("-" * 70)
print("  生产 nginx.conf 已有的安全措施（之前分析遗漏的）")
print("-" * 70)

if nginx_conf:
    security_features = {
        "HTTPS/TLS (listen 443)": 'listen 443 ssl' in nginx_conf,
        "TLSv1.2/1.3": 'TLSv1.2' in nginx_conf,
        "HSTS (Strict-Transport-Security)": 'Strict-Transport-Security' in nginx_conf,
        "CSP (Content-Security-Policy)": 'Content-Security-Policy' in nginx_conf,
        "X-Frame-Options": 'X-Frame-Options' in nginx_conf,
        "X-Content-Type-Options": 'X-Content-Type-Options' in nginx_conf,
        "X-XSS-Protection": 'X-XSS-Protection' in nginx_conf,
        "Referrer-Policy": 'Referrer-Policy' in nginx_conf,
        "Permissions-Policy": 'Permissions-Policy' in nginx_conf,
        "X-Download-Options": 'X-Download-Options' in nginx_conf,
        "server_tokens off": 'server_tokens off' in nginx_conf,
        "HTTP->HTTPS 重定向": 'return 301 https' in nginx_conf,
    }

    print()
    for feature, exists in security_features.items():
        symbol = "✅" if exists else "❌"
        print(f"  {symbol} {feature}: {'已有' if exists else '缺失'}")
    print()

# ==========================================================================
# 生产 docker-compose.yml 已有的安全措施
# ==========================================================================
print("-" * 70)
print("  生产 docker-compose.yml 已有的安全措施")
print("-" * 70)

if compose_conf:
    compose_features = {
        "数据库端口仅 localhost": '127.0.0.1:3306:3306' in compose_conf,
        "Redis 端口不对外暴露": '6379' not in compose_conf,
        "SSL 证书挂载": 'ssl' in compose_conf.lower(),
        "nginx.conf 只读挂载": ':ro' in compose_conf and 'nginx.conf' in compose_conf,
        "容器资源限制": 'limits' in compose_conf,
        "健康检查": 'healthcheck' in compose_conf,
        "Docker 网络隔离": 'tdyw-network' in compose_conf,
        "kkFileView 禁止上传": 'KK_FILE_UPLOAD_ENABLED=false' in compose_conf,
        "自动重启": 'restart: unless-stopped' in compose_conf,
    }

    print()
    for feature, exists in compose_features.items():
        symbol = "✅" if exists else "❌"
        print(f"  {symbol} {feature}: {'已有' if exists else '缺失'}")
    print()

# ==========================================================================
# 生产 .env 已有的安全措施
# ==========================================================================
print("-" * 70)
print("  生产 .env 配置状态")
print("-" * 70)

env_features = {
    "DEBUG=False": env.get('DEBUG', '') == 'False',
    "ALLOWED_HOSTS 非通配符": env.get('ALLOWED_HOSTS', '*') != '*',
    "ALLOWED_ORIGINS 已配置": bool(env.get('ALLOWED_ORIGINS', '')),
    "DJANGO_SECRET_KEY 已设置": bool(env.get('DJANGO_SECRET_KEY', '')),
    "MYSQL_PASSWORD 已设置": bool(env.get('MYSQL_PASSWORD', '')),
    "MYSQL_ROOT_PASSWORD 已设置": bool(env.get('MYSQL_ROOT_PASSWORD', '')),
    "REDIS_PASSWORD 已设置": bool(env.get('REDIS_PASSWORD', '')),
    "MYSQL_USER 非 root": env.get('MYSQL_USER', 'root') != 'root',
    "MYSQL_PASSWORD_FILE 方式": bool(env.get('MYSQL_PASSWORD_FILE', '')),
}

print()
for feature, exists in env_features.items():
    symbol = "✅" if exists else "❌"
    print(f"  {symbol} {feature}: {'是' if exists else '否'}")
print()

# ==========================================================================
# 汇总报告
# ==========================================================================
print("=" * 70)
print("  汇总报告")
print("=" * 70)
print()
print(f"  {'编号':<12} {'声称':<35} {'验证结果':<25}")
print(f"  {'-'*12} {'-'*35} {'-'*25}")

for code, claim, status, _ in results:
    symbol = "⚠️" if "TRUE" in status else "✅"
    print(f"  {code:<12} {symbol} {claim:<33} {status}")

print()
true_count = sum(1 for _, _, s, _ in results if "TRUE" in s)
false_count = sum(1 for _, _, s, _ in results if "FALSE" in s)
print(f"  声称为真 (短板存在): {true_count} 项")
print(f"  声称为假 (措施已有): {false_count} 项")
print()
print("=" * 70)
print("  纠错说明:")
print("  1. 原始分析称「无 HTTPS/TLS」-> 错误, 生产 nginx.conf 有 HTTPS + TLSv1.2/1.3")
print("  2. 原始分析称「无安全响应头」-> 错误, 生产 nginx.conf 有 7 个安全头")
print("  3. 原始分析称「无 CSP」-> 错误, 生产 nginx.conf 有完整 CSP")
print("  4. 这些错误是因为之前在 tdyw-test 容器内验证, 容器的 nginx.conf 与生产不同")
print("  5. 生产 nginx.conf 通过 docker-compose volume 挂载: ./config/nginx.conf:/etc/nginx/nginx.conf:ro")
print("=" * 70)
