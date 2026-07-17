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

        # 清理错误的 device_info 和 device_history 权限
        if 'device_info' in perms['exec']:
            del perms['exec']['device_info']
            print(f"角色 {role.name} 删除了错误的 device_info 权限")
        
        # 检查是否有 device_history 权限，如果没有则添加
        if 'device_history' not in perms['exec']:
            perms['exec']['device_history'] = []
            print(f"角色 {role.name} 添加了 device_history 权限")
        
        # 保存角色权限
        role.page_perms = json.dumps(perms)
        role.save()
        
        # 清除权限缓存
        role.clear_perms_cache()
        
        print(f"角色 {role.name} 权限已更新")
    except Exception as e:
        print(f"角色 {role.name} 更新失败: {e}")

print("\n设备管理权限修复完成")
