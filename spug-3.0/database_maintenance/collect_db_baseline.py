#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库基线采集脚本（Phase 0 / 修改前基线）

用途：在任何数据库配置修改前，采集并归档当前运行态基线，
作为变更对照与回滚依据。输出严格不含任何密码/密钥。

输出内容：
  1. 数据库版本
  2. 镜像与 digest（容器内无 docker CLI，打印宿主机命令）
  3. 持久性与复制相关运行参数
  4. 全部业务表引擎分布 + 非 InnoDB 明细
  5. 数据/索引大小（汇总 + Top 10 大表）
  6. 当前 migration 状态（叶子节点 + 未应用数量）
  7. 当前账号授权摘要（仅 user/host/权限类型，不含密码列）

用法（通过 stdin 注入 tdyw 容器，不污染容器文件系统）：
    wsl bash -c "docker exec -i tdyw python - < database_maintenance/collect_db_baseline.py"
    
    docker exec -i tdyw python -
< database_maintenance/collect_db_baseline.py

或在容器内直接执行：
    docker cp database_maintenance/collect_db_baseline.py tdyw:/tmp/collect_db_baseline.py
    docker exec tdyw python /tmp/collect_db_baseline.py

建议将输出重定向到文件归档：
    wsl bash -c "docker exec -i tdyw python - < database_maintenance/collect_db_baseline.py" \
        > /data/backups/tdyw/db_baseline_$(date +%Y%m%d_%H%M%S).txt

退出码: 0=采集成功, 2=部分采集失败（见末尾汇总）
"""
import os
import sys
from datetime import datetime

# ===== Django 环境初始化 =====
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')

import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402

errors = []


def section(title):
    print('\n' + '=' * 72)
    print('  ' + title)
    print('=' * 72)


def kv(key, value):
    print('  %-40s : %s' % (key, value))


def safe(fn, label):
    try:
        fn()
    except Exception as e:
        errors.append('%s: %s' % (label, e))
        print('  [采集失败] %s: %s' % (label, e))


print('=' * 72)
print('  数据库基线采集报告')
print('  采集时间: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
print('=' * 72)

# ------------------------------------------------------------------
# 1. 镜像与 digest（容器内无 docker CLI，打印宿主机命令）
# ------------------------------------------------------------------
section('1. 镜像与 digest（需在宿主机执行以下命令并归档到本报告）')
print('  # 数据库容器镜像 ID')
print("  docker inspect --format='{{.Image}}' tdyw-db")
print('  # 数据库容器镜像 repo digest（若有）')
print("  docker inspect --format='{{json .RepoDigests}}' tdyw-db")
print('  # 应用容器镜像 ID / digest')
print("  docker inspect --format='{{.Image}}' tdyw")
print("  docker inspect --format='{{json .RepoDigests}}' tdyw")

# ------------------------------------------------------------------
# 2. 数据库版本
# ------------------------------------------------------------------
section('2. 数据库版本')


def get_version():
    with connection.cursor() as cursor:
        cursor.execute('SELECT VERSION()')
        kv('VERSION()', cursor.fetchone()[0])
        cursor.execute('SELECT @@version_comment')
        row = cursor.fetchone()
        if row:
            kv('version_comment', row[0])


safe(get_version, '数据库版本')

# ------------------------------------------------------------------
# 3. 持久性与复制相关运行参数
# ------------------------------------------------------------------
section('3. 持久性与复制相关运行参数')

DURABILITY_PARAMS = [
    'innodb_flush_log_at_trx_commit', 'sync_binlog', 'log_bin',
    'binlog_format', 'binlog_expire_logs_seconds', 'innodb_doublewrite',
    'server_id', 'gtid_strict_mode', 'log_slave_updates', 'read_only',
    'default_storage_engine', 'innodb_buffer_pool_size',
    'max_connections', 'character_set_server', 'sql_mode',
]


def get_params():
    in_list = ','.join("'%s'" % p for p in DURABILITY_PARAMS)
    with connection.cursor() as cursor:
        cursor.execute(
            "SHOW VARIABLES WHERE Variable_name IN (%s)" % in_list)
        rows = {r[0]: r[1] for r in cursor.fetchall()}
    for p in DURABILITY_PARAMS:
        kv(p, rows.get(p, '(未返回)'))


safe(get_params, '运行参数')

# ------------------------------------------------------------------
# 4. 全部业务表引擎分布
# ------------------------------------------------------------------
section('4. 表引擎分布')


def get_engines():
    db_name = settings.DATABASES['default']['NAME']
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ENGINE, COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "GROUP BY ENGINE ORDER BY COUNT(*) DESC", [db_name])
        for engine, cnt in cursor.fetchall():
            kv('引擎 %s' % (engine or 'NULL'), '%s 张表' % cnt)
        # 非 InnoDB 明细
        cursor.execute(
            "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "AND (ENGINE IS NULL OR ENGINE <> 'InnoDB')", [db_name])
        non_innodb = cursor.fetchall()
    if non_innodb:
        print('  --- 非 InnoDB 表明细 ---')
        for t, e in non_innodb:
            kv(t, e or 'NULL')
    else:
        print('  (全部业务表均为 InnoDB)')


safe(get_engines, '表引擎')

# ------------------------------------------------------------------
# 5. 数据/索引大小
# ------------------------------------------------------------------
section('5. 数据/索引大小')


def human(n):
    n = n or 0
    for unit in ['B', 'KB', 'MB', 'GB']:
        if n < 1024:
            return '%.2f %s' % (n, unit)
        n /= 1024
    return '%.2f TB' % n


def get_sizes():
    db_name = settings.DATABASES['default']['NAME']
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*), SUM(DATA_LENGTH), SUM(INDEX_LENGTH), "
            "SUM(DATA_LENGTH+INDEX_LENGTH) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'", [db_name])
        t_cnt, data_b, idx_b, total_b = cursor.fetchone()
    kv('表数量', t_cnt or 0)
    kv('数据总大小', '%s (%s bytes)' % (human(data_b), data_b or 0))
    kv('索引总大小', '%s (%s bytes)' % (human(idx_b), idx_b or 0))
    kv('合计', '%s (%s bytes)' % (human(total_b), total_b or 0))
    print('  --- Top 10 大表（按 数据+索引） ---')
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME, DATA_LENGTH, INDEX_LENGTH, "
            "(DATA_LENGTH+INDEX_LENGTH) AS total "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY total DESC LIMIT 10", [db_name])
        for name, d, i, tot in cursor.fetchall():
            kv(name, '数据 %s / 索引 %s / 合计 %s' % (human(d), human(i), human(tot)))


safe(get_sizes, '数据/索引大小')

# ------------------------------------------------------------------
# 6. 当前 migration 状态
# ------------------------------------------------------------------
section('6. Migration 状态')


def get_migrations():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    applied = executor.recorder.applied_migrations()
    kv('已应用迁移数', len(applied))
    kv('叶子节点数', len(leaves))
    print('  --- 叶子节点（migration 最新版本） ---')
    for app, name in sorted(leaves):
        kv(app, name)
    plan = executor.migration_plan(leaves)
    if plan:
        print('  [警告] 有 %d 个迁移未应用' % len(plan))
        for m in plan[:20]:
            kv('  未应用', str(m))
    else:
        print('  (无未应用迁移，迁移状态为最新)')


safe(get_migrations, 'Migration 状态')

# ------------------------------------------------------------------
# 7. 当前账号授权摘要（不含密码）
# ------------------------------------------------------------------
section('7. 账号授权摘要（不含密码）')


def get_grants():
    with connection.cursor() as cursor:
        # 账号列表（不查询 password/authentication_string 列）
        cursor.execute("SELECT user, host FROM mysql.user ORDER BY user, host")
        users = cursor.fetchall()
    print('  数据库账号共 %d 个：' % len(users))
    for u, h in users:
        kv(u or '(空)', '@%s' % h)
    # 全局权限
    print('  --- 全局权限 (information_schema.USER_PRIVILEGES) ---')
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT GRANTEE, PRIVILEGE_TYPE, IS_GRANTABLE "
            "FROM information_schema.USER_PRIVILEGES "
            "ORDER BY GRANTEE, PRIVILEGE_TYPE")
        rows = cursor.fetchall()
    if rows:
        for grantee, priv, grantable in rows:
            kv(grantee, '%s (GRANT: %s)' % (priv, grantable))
    else:
        print('  (无全局权限记录)')
    # 目标库 schema 权限
    db_name = settings.DATABASES['default']['NAME']
    print('  --- 目标库 %s 的 SCHEMA 权限 ---' % db_name)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT GRANTEE, PRIVILEGE_TYPE, IS_GRANTABLE "
            "FROM information_schema.SCHEMA_PRIVILEGES "
            "WHERE TABLE_SCHEMA = %s ORDER BY GRANTEE, PRIVILEGE_TYPE",
            [db_name])
        rows = cursor.fetchall()
    if rows:
        for grantee, priv, grantable in rows:
            kv(grantee, '%s (GRANT: %s)' % (priv, grantable))
    else:
        print('  (无该库的 schema 权限记录)')
    # 应用当前连接账号（不打印密码）
    kv('应用连接账号', settings.DATABASES['default'].get('USER', '(未知)'))


safe(get_grants, '账号授权')

# ------------------------------------------------------------------
# 汇总
# ------------------------------------------------------------------
print('\n' + '=' * 72)
if errors:
    print('  采集完成，但有 %d 项失败：' % len(errors))
    for e in errors:
        print('    - ' + e)
    print('=' * 72)
    sys.exit(2)
print('  采集完成，全部成功。请将本输出归档到备份目录。')
print('=' * 72)
sys.exit(0)
