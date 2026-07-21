#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spug 发布前配置审计脚本（阶段 1：环境与配置审计）

用法（推荐，通过 stdin 注入容器，不污染容器文件系统）:
    wsl bash -c "docker exec -i tdyw python - < scripts/pre_release/audit_config.py"

或在容器内直接执行（需先将文件复制进容器）:
    docker cp scripts/pre_release/audit_config.py tdyw:/tmp/audit_config.py
    docker exec tdyw python /tmp/audit_config.py

退出码: 0=无 FAIL, 1=存在 FAIL
"""
import os
import sys
import subprocess
from pathlib import Path
from collections import defaultdict

# ===== Django 环境初始化 =====
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')

import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402

# ===== 结果收集 =====
results = []  # (level, category, item, status, detail)

def check(level, category, item, detail=''):
    status = {'PASS': '[PASS]', 'WARN': '[WARN]', 'FAIL': '[FAIL]', 'INFO': '[INFO]'}[level]
    results.append((level, category, item, status, detail))

# ====================================================================
# 1. Django 核心安全配置
# ====================================================================
cat = '1. Django 安全配置'

# DEBUG
check('FAIL' if settings.DEBUG else 'PASS', cat, 'DEBUG',
      'DEBUG=True 不应在生产环境' if settings.DEBUG else 'DEBUG=False')

# SECRET_KEY
sk = settings.SECRET_KEY or ''
if not sk:
    check('FAIL', cat, 'SECRET_KEY', 'SECRET_KEY 为空')
elif sk == 'dev-only-insecure-key-do-not-use-in-production':
    check('FAIL', cat, 'SECRET_KEY', '使用了开发默认密钥')
elif len(sk) < 32:
    check('WARN', cat, 'SECRET_KEY', f'密钥长度不足 ({len(sk)} < 32)')
else:
    check('PASS', cat, 'SECRET_KEY', f'已设置 (长度 {len(sk)})')

# ALLOWED_HOSTS
if '*' in settings.ALLOWED_HOSTS:
    check('WARN', cat, 'ALLOWED_HOSTS', 'ALLOWED_HOSTS=* 过于宽松，建议改为具体域名/IP')
elif not settings.ALLOWED_HOSTS:
    check('FAIL', cat, 'ALLOWED_HOSTS', 'ALLOWED_HOSTS 为空')
else:
    check('PASS', cat, 'ALLOWED_HOSTS', str(settings.ALLOWED_HOSTS))

# ALLOWED_ORIGINS（Origin/Referer 校验）
ao = getattr(settings, 'ALLOWED_ORIGINS', [])
if not ao:
    check('WARN', cat, 'ALLOWED_ORIGINS', '未设置，Origin 校验可能放行所有来源')
else:
    check('PASS', cat, 'ALLOWED_ORIGINS', f'{len(ao)} 个来源')

# USE_TZ（项目约定 False）
if settings.USE_TZ:
    check('WARN', cat, 'USE_TZ', 'USE_TZ=True，项目约定 USE_TZ=False（timezone.localdate 会抛错）')
else:
    check('PASS', cat, 'USE_TZ', 'False (项目约定)')

# TIME_ZONE
check('PASS' if settings.TIME_ZONE == 'Asia/Shanghai' else 'WARN',
      cat, 'TIME_ZONE', f'TIME_ZONE={settings.TIME_ZONE}')

# Celery 时区一致性
if settings.CELERY_ENABLE_UTC and not settings.USE_TZ:
    check('WARN', cat, 'Celery 时区',
          f'CELERY_ENABLE_UTC=True 但 USE_TZ=False，beat 调度可能有时区偏差')
else:
    tz_aware = getattr(settings, 'DJANGO_CELERY_BEAT_TZ_AWARE', 'N/A')
    check('PASS', cat, 'Celery 时区',
          f'ENABLE_UTC={settings.CELERY_ENABLE_UTC}, TZ_AWARE={tz_aware}')

# ====================================================================
# 2. 数据库
# ====================================================================
cat = '2. 数据库'
db = settings.DATABASES['default']

if not db.get('NAME'):
    check('FAIL', cat, 'DB NAME', 'MYSQL_DATABASE 未设置')
else:
    check('PASS', cat, 'DB NAME', db['NAME'])

if not db.get('USER'):
    check('FAIL', cat, 'DB USER', 'MYSQL_USER 未设置')
else:
    check('PASS', cat, 'DB USER', db['USER'])

if db.get('CONN_MAX_AGE', 0) != 0:
    check('WARN', cat, 'CONN_MAX_AGE',
          f'CONN_MAX_AGE={db["CONN_MAX_AGE"]}，项目用 gevent 应为 0')
else:
    check('PASS', cat, 'CONN_MAX_AGE', '0 (gevent 兼容)')

# 实际连通性
try:
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        cursor.fetchone()
    check('PASS', cat, 'DB 连通性', 'SELECT 1 成功')
except Exception as e:
    check('FAIL', cat, 'DB 连通性', str(e))

# MySQL 版本与关键参数
try:
    with connection.cursor() as cursor:
        cursor.execute('SELECT VERSION()')
        version = cursor.fetchone()[0]
        check('INFO', cat, 'MySQL 版本', version)

        cursor.execute("SHOW VARIABLES LIKE 'max_connections'")
        mc = cursor.fetchone()
        if mc:
            v = int(mc[1])
            if v > 300:
                check('WARN', cat, 'max_connections', f'{v}（8G 服务器建议 300）')
            else:
                check('PASS', cat, 'max_connections', f'{v}')

        cursor.execute("SHOW VARIABLES LIKE 'innodb_buffer_pool_size'")
        bp = cursor.fetchone()
        if bp:
            v = int(bp[1]) // (1024*1024)
            check('INFO', cat, 'innodb_buffer_pool_size', f'{v} MB')

        cursor.execute("SHOW VARIABLES LIKE 'character_set_server'")
        cs = cursor.fetchone()
        if cs:
            check('PASS' if cs[1] == 'utf8mb4' else 'WARN',
                  cat, 'character_set_server', cs[1])

        cursor.execute("SHOW VARIABLES LIKE 'sql_mode'")
        sm = cursor.fetchone()
        if sm:
            if 'STRICT_TRANS_TABLES' in sm[1]:
                check('PASS', cat, 'sql_mode', 'STRICT_TRANS_TABLES 已启用')
            else:
                check('WARN', cat, 'sql_mode', '未启用 STRICT_TRANS_TABLES')

        cursor.execute("SHOW VARIABLES LIKE 'slow_query_log'")
        sq = cursor.fetchone()
        if sq:
            check('PASS' if sq[1] == 'ON' else 'WARN',
                  cat, 'slow_query_log', sq[1])
except Exception as e:
    check('WARN', cat, 'MySQL 参数查询', str(e))

# ====================================================================
# 3. Redis（4 个 DB）
# ====================================================================
cat = '3. Redis'
try:
    import redis
except ImportError:
    check('WARN', cat, 'redis 库', 'redis-py 未安装，跳过连通性检查')
    redis = None

if redis:
    rhost = os.environ.get('REDIS_HOST', '127.0.0.1')
    rport = int(os.environ.get('REDIS_PORT', '6379'))
    rpwd = os.environ.get('REDIS_PASSWORD', '')

    for db_num, name in [(0, 'channels'), (1, 'cache'), (2, 'broker'), (3, 'result')]:
        try:
            r = redis.Redis(host=rhost, port=rport, db=db_num, password=rpwd,
                            socket_connect_timeout=3)
            r.ping()
            check('PASS', cat, f'DB{db_num} ({name})', 'PONG')
        except Exception as e:
            check('FAIL', cat, f'DB{db_num} ({name})', str(e))

    # 权限缓存键数量
    try:
        r = redis.Redis(host=rhost, port=rport, db=1, password=rpwd)
        perms_keys = r.keys('perms_*')
        check('INFO', cat, '权限缓存',
              f'当前有 {len(perms_keys)} 个 perms_* 缓存键')
    except Exception as e:
        check('WARN', cat, '权限缓存', str(e))

# ====================================================================
# 4. Celery
# ====================================================================
cat = '4. Celery'
try:
    from celery import current_app
    i = current_app.control.inspect(timeout=3)
    ping = i.ping()
    if ping:
        check('PASS', cat, 'Worker ping', f'{len(ping)} 个 worker 响应')
        for name in sorted(ping.keys()):
            check('INFO', cat, f'  worker', name)
    else:
        check('FAIL', cat, 'Worker ping', '无 worker 响应')
except Exception as e:
    check('WARN', cat, 'Worker ping', str(e))

# Beat schedule
try:
    sched = settings.CELERY_BEAT_SCHEDULE
    check('INFO', cat, 'Beat schedule', f'{len(sched)} 个定时任务')
    for name in sorted(sched.keys()):
        task = sched[name].get('task', '?')
        check('INFO', cat, f'  - {name}', task)
except Exception as e:
    check('WARN', cat, 'Beat schedule', str(e))

# ====================================================================
# 5. 文件系统与目录权限
# ====================================================================
cat = '5. 文件系统'
for path_name, path in [
    ('MEDIA_ROOT', settings.MEDIA_ROOT),
    ('STATIC_ROOT', settings.STATIC_ROOT),
    ('TRANSFER_DIR', getattr(settings, 'TRANSFER_DIR', '')),
    ('logs', os.path.join(settings.BASE_DIR, 'logs')),
]:
    if not path:
        continue
    p = Path(path)
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
            check('WARN', cat, path_name, f'{path} 不存在，已创建')
        except Exception as e:
            check('FAIL', cat, path_name, f'{path} 不存在且无法创建: {e}')
    elif not os.access(path, os.W_OK):
        check('FAIL', cat, path_name, f'{path} 不可写')
    else:
        check('PASS', cat, path_name, f'可写')

# 关键存储目录
storage_dir = os.path.join(settings.BASE_DIR, 'storage')
for sub in ['documents', 'document_chunks', 'transfer']:
    d = os.path.join(storage_dir, sub)
    if os.path.exists(d):
        if os.access(d, os.W_OK):
            check('PASS', cat, f'storage/{sub}', '可写')
        else:
            check('FAIL', cat, f'storage/{sub}', '不可写')
    else:
        check('WARN', cat, f'storage/{sub}', '不存在（首次使用时会创建）')

# ====================================================================
# 6. 迁移状态
# ====================================================================
cat = '6. 数据库迁移'
try:
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if plan:
        check('FAIL', cat, '未应用迁移', f'{len(plan)} 个迁移未应用')
        for m in plan[:10]:
            check('INFO', cat, f'  - {m}', '')
    else:
        check('PASS', cat, '迁移状态', '全部已应用')
except Exception as e:
    check('WARN', cat, '迁移状态', str(e))

# 模型与迁移一致性
try:
    output = subprocess.check_output(
        ['python', 'manage.py', 'makemigrations', '--check', '--dry-run'],
        stderr=subprocess.STDOUT, text=True, timeout=30,
        cwd=settings.BASE_DIR)
    if 'No changes detected' in output:
        check('PASS', cat, '模型-迁移一致性', 'No changes detected')
    else:
        check('WARN', cat, '模型-迁移一致性', '有未生成的迁移')
except subprocess.CalledProcessError:
    check('WARN', cat, '模型-迁移一致性', 'makemigrations --check 返回非零')
except Exception as e:
    check('WARN', cat, '模型-迁移一致性', str(e))

# ====================================================================
# 7. INSTALLED_APPS 完整性
# ====================================================================
cat = '7. 业务模块'
expected_apps = [
    'apps.account', 'apps.setting', 'apps.exec', 'apps.fault', 'apps.duty',
    'apps.device', 'apps.interference', 'apps.home', 'apps.runlog',
    'apps.document', 'apps.upgrade', 'apps.checksheet', 'apps.logs',
    'apps.radio_license', 'apps.contract_agreement', 'apps.evidence',
    'apps.regulation', 'apps.signature', 'apps.department_duty_log',
]
missing = [a for a in expected_apps if a not in settings.INSTALLED_APPS]
if missing:
    check('FAIL', cat, '缺失模块', str(missing))
else:
    check('PASS', cat, '全部模块', f'{len(expected_apps)} 个业务 app 已注册')

# ====================================================================
# 8. 关键文件存在性
# ====================================================================
cat = '8. 关键文件'
critical_files = [
    '/etc/nginx/nginx.conf',
    '/etc/nginx/ssl/spug.crt',
    '/etc/nginx/ssl/spug.key',
    '/etc/supervisor/conf.d/supervisord.conf',
    '/data/spug/spug_api/tools/start-api.sh',
    '/data/spug/spug_api/tools/start-api-upload.sh',
    '/data/spug/spug_api/tools/start-celery.sh',
    '/data/spug/spug_api/tools/start-celery-beat.sh',
    '/data/spug/spug_api/tools/start-celery-merge.sh',
    '/data/spug/spug_api/tools/start-celery-cleanup.sh',
    '/data/spug/spug_api/tools/start-ws.sh',
    '/data/spug/spug_web/build/index.html',
]
for f in critical_files:
    check('PASS' if os.path.exists(f) else 'FAIL', cat, f,
          '' if os.path.exists(f) else '不存在')

# SSL 证书有效期
try:
    output = subprocess.check_output(
        ['openssl', 'x509', '-in', '/etc/nginx/ssl/spug.crt',
         '-noout', '-enddate'],
        stderr=subprocess.STDOUT, text=True, timeout=5)
    # notAfter=Mar 28 16:10:00 2027 GMT
    end_str = output.strip().split('=', 1)[-1]
    check('INFO', cat, 'SSL 证书有效期', f'到期: {end_str}')
except Exception as e:
    check('WARN', cat, 'SSL 证书', str(e))

# ====================================================================
# 9. Supervisor 进程状态
# ====================================================================
cat = '9. Supervisor 进程'
expected_programs = [
    'nginx', 'redis', 'spug-api', 'spug-api-upload', 'spug-ws',
    'spug-worker', 'spug-celery', 'spug-celery-beat',
    'spug-celery-cleanup', 'spug-celery-merge', 'spug-celery-batch',
    'spug-celery-thumbnail', 'spug-celery-radio-license',
]
try:
    output = subprocess.check_output(
        ['supervisorctl', 'status'],
        stderr=subprocess.STDOUT, text=True, timeout=5)
    statuses = {}
    for line in output.strip().split('\n'):
        parts = line.split()
        if len(parts) >= 2:
            statuses[parts[0]] = parts[1]
    for prog in expected_programs:
        if prog not in statuses:
            check('FAIL', cat, prog, '未在 supervisor 管理')
        elif statuses[prog] != 'RUNNING':
            check('FAIL', cat, prog, f'状态: {statuses[prog]}')
        else:
            check('PASS', cat, prog, 'RUNNING')
    # 意外的额外进程
    extra = set(statuses.keys()) - set(expected_programs)
    for e in extra:
        check('WARN', cat, e, f'未在预期清单 (状态 {statuses[e]})')
except Exception as e:
    check('WARN', cat, 'supervisorctl', str(e))

# ====================================================================
# 10. 环境变量
# ====================================================================
cat = '10. 环境变量'
required_env = [
    'MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DATABASE',
    'DJANGO_SECRET_KEY', 'DEBUG', 'ALLOWED_HOSTS',
    'REDIS_HOST', 'REDIS_PORT', 'TZ',
]
for var in required_env:
    val = os.environ.get(var)
    if val is None:
        check('WARN', cat, var, '未设置（使用 settings 默认值）')
    elif var in ('MYSQL_PASSWORD', 'DJANGO_SECRET_KEY') and not val:
        check('FAIL', cat, var, '为空')
    elif var in ('MYSQL_PASSWORD', 'DJANGO_SECRET_KEY'):
        check('PASS', cat, var, '已设置 (值已隐藏)')
    else:
        check('PASS', cat, var, val)

# ====================================================================
# 11. named volume 陷阱（docker-compose 检查）
# ====================================================================
cat = '11. Docker Volume 陷阱'
compose_files = [
    '/data/spug/spug_api/../docker/docker-compose.yml',
    '/data/spug/docker-compose.yml',
]
# 在容器内通常看不到 compose 文件（构建时已固化），跳过文件读取
# 改为检查实际挂载情况
try:
    output = subprocess.check_output(
        ['mount'], stderr=subprocess.STDOUT, text=True, timeout=5)
    # 检查 media/documents 是否是 named volume（非 bind mount）
    media_is_bind = '/data/spug/spug_api/media' in output and '/mnt/' in output.split('/data/spug/spug_api/media')[0][-50:]
    check('INFO', cat, '挂载类型',
          '详见 docker-compose.yml 的 volumes 配置')
except Exception:
    pass

# 检查 media 目录的实际数据位置
media_path = settings.MEDIA_ROOT
try:
    # 写一个测试文件看是否在 named volume 里
    test_file = os.path.join(media_path, '.audit_test')
    with open(test_file, 'w') as f:
        f.write('audit')
    os.remove(test_file)
    check('PASS', cat, 'MEDIA_ROOT 可写', media_path)
    check('INFO', cat, 'Volume 提醒',
          '请人工确认 docker-compose.yml 中 tdyw-media/tdyw-documents 是 named volume '
          '还是 bind mount（named volume 切换项目名会丢数据）')
except Exception as e:
    check('FAIL', cat, 'MEDIA_ROOT 可写', str(e))

# ====================================================================
# 输出报告
# ====================================================================
print('\n' + '=' * 72)
print('  Spug 发布前配置审计报告 (阶段 1)')
print('=' * 72)

by_cat = defaultdict(list)
for level, category, item, status, detail in results:
    by_cat[category].append((level, item, status, detail))

counts = {'PASS': 0, 'WARN': 0, 'FAIL': 0, 'INFO': 0}
for level, _, _, _, _ in results:
    counts[level] = counts.get(level, 0) + 1

for cat, items in by_cat.items():
    print(f'\n【{cat}】')
    for level, item, status, detail in items:
        line = f'  {status:8s} {item}'
        if detail:
            line += f'  ->  {detail}'
        print(line)

print('\n' + '=' * 72)
print(f'  合计: [PASS] {counts["PASS"]:3d}   '
      f'[WARN] {counts["WARN"]:3d}   '
      f'[FAIL] {counts["FAIL"]:3d}   '
      f'[INFO] {counts["INFO"]:3d}')
print('=' * 72)

# 列出所有 FAIL 和 WARN 供快速定位
issues = [(l, c, i, d) for l, c, i, _, d in results if l in ('FAIL', 'WARN')]
if issues:
    print('\n[需要处理的问题清单]')
    for level, cat, item, detail in issues:
        marker = '!' if level == 'FAIL' else '?'
        print(f'  {marker} [{cat}] {item}: {detail}')
    print()

sys.exit(0 if counts['FAIL'] == 0 else 1)
