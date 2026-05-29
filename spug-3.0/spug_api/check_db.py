import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.db import connection

# 检查 roles 表的 is_global_admin 列
cursor = connection.cursor()
cursor.execute('SELECT id, name, is_global_admin FROM roles')
print('=== roles table ===')
for row in cursor.fetchall():
    print(row)

# 检查 roles 表结构
cursor.execute('DESCRIBE roles')
print('\n=== roles structure ===')
for row in cursor.fetchall():
    print(row)

# 检查 users 表的 tenant_id 列是否已有索引
cursor.execute('SHOW INDEX FROM users WHERE Column_name = %s', ['tenant_id'])
print('\n=== users tenant_id index ===')
for row in cursor.fetchall():
    print(row)

# 检查迁移状态
cursor.execute("SELECT app, name, applied FROM django_migrations WHERE app = 'account' ORDER BY id")
print('\n=== account migrations ===')
for row in cursor.fetchall():
    print(row)
