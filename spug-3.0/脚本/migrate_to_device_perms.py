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

        # 检查 exec 模块是否有 device_resume 权限
        if 'exec' in perms and 'device_resume' in perms['exec']:
            old_resume_perms = perms['exec']['device_resume']
            
            # 创建 device 模块
            if 'device' not in perms:
                perms['device'] = {}
            
            # 迁移 device_resume 权限
            if 'device_resume' not in perms['device']:
                perms['device']['device_resume'] = old_resume_perms
            
            # 创建 device_history 权限（如果有增删改权限，则给予全部权限）
            old_history_perms = perms['exec'].get('device_history', [])
            if 'device_history' not in perms['device']:
                # 如果有增删改权限，则给全部
                if len(old_resume_perms) > 1:
                    perms['device']['device_history'] = ['view', 'add', 'edit', 'delete']
                else:
                    perms['device']['device_history'] = old_history_perms
            
            # 删除 exec 模块中的 device 相关权限
            del perms['exec']['device_resume']
            if 'device_history' in perms['exec']:
                del perms['exec']['device_history']
            
            # 保存角色权限
            role.page_perms = json.dumps(perms)
            role.save()
            
            # 清除权限缓存
            role.clear_perms_cache()
            
            print(f"角色 {role.name} 权限已迁移: exec.device_resume -> device.device_resume")
            print(f"  设备履历权限: {perms['device']['device_resume']}")
            print(f"  查看履历权限: {perms['device']['device_history']}")
        elif 'device' not in perms:
            # 没有权限的角色，创建空的 device 模块
            perms['device'] = {
                'device_resume': [],
                'device_history': []
            }
            role.page_perms = json.dumps(perms)
            role.save()
            role.clear_perms_cache()
            print(f"角色 {role.name} 添加了空的 device 模块")
        else:
            print(f"角色 {role.name} 无需迁移")
    except Exception as e:
        print(f"角色 {role.name} 更新失败: {e}")

print("\n设备管理权限迁移完成")
