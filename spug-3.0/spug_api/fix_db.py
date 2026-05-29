import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.db import connection

c = connection.cursor()

# 1. 修复 roles.is_global_admin NULL 值
c.execute('UPDATE roles SET is_global_admin = 0 WHERE is_global_admin IS NULL')
print(f'Updated {c.rowcount} rows in roles.is_global_admin NULL -> 0')

# 2. 验证
c.execute('SELECT id, name, is_global_admin FROM roles WHERE is_global_admin IS NULL')
remaining = c.fetchall()
print(f'Remaining NULLs: {remaining}')

# 3. 也检查 users 表是否有 tenant_id 为 NULL 的
c.execute('SELECT id, username, tenant_id FROM users WHERE tenant_id IS NULL')
null_tenants = c.fetchall()
print(f'Users with NULL tenant_id: {null_tenants}')

if null_tenants:
    c.execute("UPDATE users SET tenant_id = 'admin' WHERE tenant_id IS NULL")
    print(f'Fixed {c.rowcount} users with NULL tenant_id')

print('Done!')
