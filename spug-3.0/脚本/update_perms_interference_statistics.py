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

        # 检查 interference 模块是否存在
        if 'interference' not in perms:
            print(f"角色 {role.name} 没有 interference 模块，跳过")
            continue

        # 检查是否已添加 statistics
        if 'statistics' in perms['interference']:
            print(f"角色 {role.name} 已有 interference.statistics 权限，跳过")
            continue

        # 添加 statistics 到 interference 模块
        perms['interference']['statistics'] = ['view']

        # 保存角色权限
        role.page_perms = json.dumps(perms)
        role.save()

        # 清除权限缓存
        role.clear_perms_cache()

        print(f"角色 {role.name} 已添加 interference.statistics 权限")
    except Exception as e:
        print(f"角色 {role.name} 更新失败: {e}")

print("\n干扰统计权限更新完成")
