import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')
django.setup()

from apps.account.models import Role
import json

# 获取所有角色
roles = Role.objects.all()

for role in roles:
    if not role.page_perms:
        continue

    try:
        perms = json.loads(role.page_perms)

        # 检查 exec 模块是否存在
        if 'exec' not in perms:
            print(f"角色 {role.name} 没有 exec 模块，跳过")
            continue

        # 检查是否已添加 device_event
        if 'device_event' in perms['exec']:
            print(f"角色 {role.name} 已有 device_event 权限，跳过")
            continue

        # 添加 device_event 到 exec 模块，默认赋予所有权限
        perms['exec']['device_event'] = ['view', 'add', 'edit', 'delete']

        # 保存角色权限
        role.page_perms = json.dumps(perms)
        role.save()

        # 清除权限缓存
        role.clear_perms_cache()

        print(f"角色 {role.name} 已添加 device_event 权限")
    except Exception as e:
        print(f"角色 {role.name} 更新失败: {e}")

print("\n设备履历权限更新完成")
