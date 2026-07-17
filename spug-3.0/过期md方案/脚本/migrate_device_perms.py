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

        # 检查是否有旧的 device_resume 权限
        if 'device_resume' in perms['exec']:
            old_perms = perms['exec']['device_resume']
            
            # 检查是否已经迁移
            if 'device_info' in perms['exec'] and 'device_history' in perms['exec']:
                print(f"角色 {role.name} 已迁移过，跳过")
                continue
            
            # 创建新的权限结构
            perms['exec']['device_info'] = old_perms
            perms['exec']['device_history'] = old_perms
            
            # 删除旧的 device_resume 权限
            del perms['exec']['device_resume']
            
            # 保存角色权限
            role.page_perms = json.dumps(perms)
            role.save()
            
            # 清除权限缓存
            role.clear_perms_cache()
            
            print(f"角色 {role.name} 权限已迁移: device_resume -> device_info, device_history")
            print(f"  旧权限: {old_perms}")
        else:
            print(f"角色 {role.name} 没有 device_resume 权限，跳过")
    except Exception as e:
        print(f"角色 {role.name} 更新失败: {e}")

print("\n设备管理权限迁移完成")
