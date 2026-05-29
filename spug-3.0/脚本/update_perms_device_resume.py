import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')
django.setup()

from apps.account.models import Role
import json

# 定义 device_resume 模块的权限
device_resume_perms = {
  "view": "查看设备",
  "add": "新建设备",
  "edit": "编辑设备",
  "delete": "删除设备"
}

# 获取所有角色
roles = Role.objects.all()

for role in roles:
    if not role.page_perms:
        continue

    try:
        perms = json.loads(role.page_perms)

        # 检查是否已添加 device_resume
        if 'exec' in perms and 'device_resume' in perms['exec']:
            print(f"角色 {role.name} 已有 device_resume 权限，跳过")
            continue

        # 添加 device_resume 到 exec 模块
        if 'exec' not in perms:
            perms['exec'] = {}

        perms['exec']['device_resume'] = ['view', 'add', 'edit', 'delete']

        # 保存角色权限
        role.page_perms = json.dumps(perms)
        role.save()

        # 清除权限缓存
        role.clear_perms_cache()

        print(f"角色 {role.name} 已添加 device_resume 权限")
    except Exception as e:
        print(f"角色 {role.name} 更新失败: {e}")

print("\n设备管理权限更新完成")
