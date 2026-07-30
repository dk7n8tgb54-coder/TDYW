"""
安全短板修复验证测试

验证 4 项修复是否成功：
1. Redis 密码已设置（.env + docker-compose.yml + supervisord.conf）
2. MYSQL_USER 非 root（.env + docker-compose.yml + SQL 脚本）
3. SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE 已设置（settings.py）
4. Nginx limit_req 已应用（nginx.conf）

运行方式（宿主机直接运行）:
    cd e:/TDYW/spug-3.0
    python spug_api/apps/security_fix_verify.py

或通过 Docker（Django 运行时验证）:
    docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
        python apps/security_fix_verify.py
"""
import os
import re
import sys
import io

# 修复 Windows GBK 编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Django 运行时检查（如果可用）
try:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
    import django
    django.setup()
    from django.conf import settings as django_settings
    DJANGO_AVAILABLE = True
except Exception:
    DJANGO_AVAILABLE = False

# 路径解析
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
DOCKER_DIR = os.path.join(PROJECT_ROOT, 'docker')

passed = 0
failed = 0
errors = []

def assert_true(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
        if detail:
            print(f"         {detail}")
    else:
        failed += 1
        errors.append(name)
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         {detail}")
    print()

def read_file(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def parse_env(path):
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


print("=" * 70)
print("  安全短板修复验证测试")
print("=" * 70)
print()
print(f"  Django 运行时: {'可用' if DJANGO_AVAILABLE else '不可用（跳过运行时检查）'}")
print(f"  项目根目录: {PROJECT_ROOT}")
print()

# ==========================================================================
# 修复 1: Redis 密码
# ==========================================================================
print("-" * 70)
print("  修复 1: Redis 密码")
print("-" * 70)
print()

env = parse_env(os.path.join(DOCKER_DIR, '.env'))
compose = read_file(os.path.join(DOCKER_DIR, 'docker-compose.yml'))
supervisord = read_file(os.path.join(DOCKER_DIR, 'config', 'supervisord.conf'))

# 1.1 .env 设置了 REDIS_PASSWORD
redis_pwd = env.get('REDIS_PASSWORD', '')
assert_true(
    "1.1 .env 设置了 REDIS_PASSWORD",
    bool(redis_pwd),
    f"REDIS_PASSWORD={'*' * len(redis_pwd) + '...' if redis_pwd else '(空)'}"
)

# 1.2 REDIS_PASSWORD 非空且足够长（>=8）
assert_true(
    "1.2 REDIS_PASSWORD 长度 >= 8",
    len(redis_pwd) >= 8,
    f"长度: {len(redis_pwd)}"
)

# 1.3 docker-compose.yml 传递了 REDIS_PASSWORD 环境变量
assert_true(
    "1.3 docker-compose.yml 传递 REDIS_PASSWORD",
    'REDIS_PASSWORD' in (compose or ''),
    "docker-compose.yml 的 tdyw 服务 environment 中包含 REDIS_PASSWORD"
)

# 1.4 supervisord.conf 使用 bash -c 条件设置 requirepass
assert_true(
    "1.4 supervisord.conf 支持 REDIS_PASSWORD 条件设置",
    'REDIS_PASSWORD' in (supervisord or '') and 'requirepass' in (supervisord or ''),
    "Redis 启动命令包含 ${REDIS_PASSWORD:+--requirepass} 条件逻辑"
)

# 1.5 settings.py 读取 REDIS_PASSWORD 环境变量
settings_py = read_file(os.path.join(SCRIPT_DIR, '..', 'spug', 'settings.py'))
assert_true(
    "1.5 settings.py 读取 REDIS_PASSWORD 环境变量",
    'REDIS_PASSWORD' in (settings_py or ''),
    "settings.py 中存在 os.environ.get('REDIS_PASSWORD', '') 逻辑"
)

# 1.6 Django 运行时验证 Redis URL 包含密码
if DJANGO_AVAILABLE:
    redis_url = django_settings.CACHES['default']['LOCATION']
    assert_true(
        "1.6 [运行时] Redis URL 包含密码",
        '@' in redis_url,
        f"Redis URL: {redis_url}"
    )
else:
    print("  [SKIP] 1.6 [运行时] Redis URL 包含密码 (Django 不可用)")
    print()

# ==========================================================================
# 修复 2: MYSQL_USER 非 root
# ==========================================================================
print("-" * 70)
print("  修复 2: MYSQL_USER 非 root")
print("-" * 70)
print()

# 2.1 .env 中 MYSQL_USER 非 root
mysql_user = env.get('MYSQL_USER', '')
assert_true(
    "2.1 .env MYSQL_USER 非 root",
    mysql_user != 'root' and mysql_user != '',
    f"MYSQL_USER={mysql_user}"
)

# 2.2 .env 中 MYSQL_USER 为 tdyw
assert_true(
    "2.2 .env MYSQL_USER 为 tdyw",
    mysql_user == 'tdyw',
    f"MYSQL_USER={mysql_user}"
)

# 2.3 docker-compose.yml 使用 ${MYSQL_USER} 而非硬编码 root
assert_true(
    "2.3 docker-compose.yml 使用 ${MYSQL_USER} 而非硬编码 root",
    '${MYSQL_USER' in (compose or '') and 'MYSQL_USER=root' not in (compose or ''),
    "docker-compose.yml 使用 ${MYSQL_USER:-tdyw} 读取环境变量"
)

# 2.4 SQL 脚本存在
sql_script = read_file(os.path.join(DOCKER_DIR, 'scripts', 'init_tdyw_account.sql'))
assert_true(
    "2.4 SQL 脚本存在（init_tdyw_account.sql）",
    sql_script is not None,
    f"路径: docker/scripts/init_tdyw_account.sql"
)

# 2.5 SQL 脚本创建 tdyw 用户
assert_true(
    "2.5 SQL 脚本创建 tdyw 用户",
    sql_script is not None and "CREATE USER" in sql_script and "'tdyw'" in sql_script,
    "SQL 脚本包含 CREATE USER 'tdyw' 语句"
)

# 2.6 SQL 脚本不授予 GRANT OPTION / SUPER / FILE
assert_true(
    "2.6 SQL 脚本不授予 GRANT OPTION / SUPER / FILE",
    sql_script is not None and
    'GRANT OPTION' not in sql_script and
    'SUPER' not in sql_script and
    'FILE' not in sql_script,
    "SQL 脚本仅授予 DML + DDL，无 GRANT OPTION/SUPER/FILE"
)

# 2.7 Django 运行时验证数据库连接用户
if DJANGO_AVAILABLE:
    db_user = django_settings.DATABASES['default'].get('USER', '')
    assert_true(
        "2.7 [运行时] Django 数据库连接用户非 root",
        db_user != 'root' and db_user != '',
        f"DB USER={db_user}"
    )
else:
    print("  [SKIP] 2.7 [运行时] Django 数据库连接用户非 root (Django 不可用)")
    print()

# ==========================================================================
# 修复 3: SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE
# ==========================================================================
print("-" * 70)
print("  修复 3: SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE")
print("-" * 70)
print()

# 3.1 settings.py 包含 SESSION_COOKIE_SECURE 设置
assert_true(
    "3.1 settings.py 设置了 SESSION_COOKIE_SECURE",
    'SESSION_COOKIE_SECURE' in (settings_py or ''),
    "settings.py 中存在 SESSION_COOKIE_SECURE 配置"
)

# 3.2 settings.py 包含 CSRF_COOKIE_SECURE 设置
assert_true(
    "3.2 settings.py 设置了 CSRF_COOKIE_SECURE",
    'CSRF_COOKIE_SECURE' in (settings_py or ''),
    "settings.py 中存在 CSRF_COOKIE_SECURE 配置"
)

# 3.3 设置条件为 not DEBUG
assert_true(
    "3.3 安全 Cookie 设置条件为 not DEBUG",
    bool(settings_py and re.search(r'if\s+not\s+DEBUG', settings_py)),
    "安全 Cookie 在 DEBUG=False 时自动启用"
)

# 3.4 Django 运行时验证（DEBUG=False 时）
if DJANGO_AVAILABLE:
    debug = django_settings.DEBUG
    if not debug:
        assert_true(
            "3.4 [运行时] DEBUG=False 时 SESSION_COOKIE_SECURE=True",
            getattr(django_settings, 'SESSION_COOKIE_SECURE', False) == True,
            f"SESSION_COOKIE_SECURE={getattr(django_settings, 'SESSION_COOKIE_SECURE', False)}"
        )
        assert_true(
            "3.5 [运行时] DEBUG=False 时 CSRF_COOKIE_SECURE=True",
            getattr(django_settings, 'CSRF_COOKIE_SECURE', False) == True,
            f"CSRF_COOKIE_SECURE={getattr(django_settings, 'CSRF_COOKIE_SECURE', False)}"
        )
    else:
        print(f"  [SKIP] 3.4-3.5 [运行时] 当前 DEBUG=True，安全 Cookie 未启用（符合预期）")
        print()
else:
    print("  [SKIP] 3.4-3.5 [运行时] (Django 不可用)")
    print()

# ==========================================================================
# 修复 4: Nginx limit_req
# ==========================================================================
print("-" * 70)
print("  修复 4: Nginx limit_req")
print("-" * 70)
print()

nginx_conf = read_file(os.path.join(DOCKER_DIR, 'config', 'nginx.conf'))

# 4.1 nginx.conf 定义了 limit_req_zone
zones = re.findall(r'limit_req_zone.*zone=(\w+)', nginx_conf or '')
assert_true(
    "4.1 nginx.conf 定义了 limit_req_zone",
    len(zones) >= 3,
    f"zones: {zones}"
)

# 4.2 nginx.conf 包含 limit_req 指令
limit_reqs = re.findall(r'^\s*limit_req\s+zone=(\w+)', nginx_conf or '', re.MULTILINE)
assert_true(
    "4.2 nginx.conf 包含 limit_req 指令",
    len(limit_reqs) > 0,
    f"已应用的 zones: {limit_reqs}"
)

# 4.3 login_limit 已应用到登录接口
assert_true(
    "4.3 login_limit 已应用到登录接口",
    'login_limit' in limit_reqs,
    "登录接口 /api/account/login/ 已应用 login_limit 限流"
)

# 4.4 api_limit 已应用到 /api/ 通用接口
assert_true(
    "4.4 api_limit 已应用到 /api/ 通用接口",
    'api_limit' in limit_reqs,
    "/api/ location 已应用 api_limit 限流"
)

# 4.5 登录接口有独立的 location 块
assert_true(
    "4.5 登录接口有独立 location 块",
    bool(nginx_conf and re.search(r'location\s*=\s*/api/account/login/', nginx_conf)),
    "存在 location = /api/account/login/ 独立块"
)

# ==========================================================================
# 汇总
# ==========================================================================
print("=" * 70)
print("  测试汇总")
print("=" * 70)
print()
print(f"  通过: {passed}")
print(f"  失败: {failed}")
print(f"  总计: {passed + failed}")
print()

if failed > 0:
    print("  失败项:")
    for e in errors:
        print(f"    - {e}")
    print()
    sys.exit(1)
else:
    print("  全部通过！所有修复已验证成功。")
    print()
    sys.exit(0)
