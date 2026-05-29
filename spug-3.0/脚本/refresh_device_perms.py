"""
刷新通信科角色的设备管理权限到用户
"""
import os
import sys
import django

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'data', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

django.setup()

from apps.account.models import User, Role

def refresh_device_permissions():
    # 获取通信科角色
    role = Role.objects.filter(name='通信科').first()
    if not role:
        print("未找到通信科角色")
        return

    print(f"通信科角色的权限:")
    print(role.page_perms)

    # 获取所有通信科的用户
    users = User.objects.filter(roles__name='通信科')
    print(f"\n找到 {users.count()} 个通信科用户")

    for user in users:
        print(f"\n刷新用户: {user.username}")
        # 刷新用户权限
        user.page_perms = user.get_page_perms()
        user.save()
        print(f"  更新后的权限数量: {len(user.page_perms)}")

        # 检查是否有设备管理权限
        device_perms = [p for p in user.page_perms if p.startswith('device.')]
        print(f"  设备管理权限: {device_perms}")

    print("\n权限刷新完成!")

if __name__ == '__main__':
    refresh_device_permissions()
