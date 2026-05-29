#!/usr/bin/env python
"""
测试全局管理员角色功能
"""

import os
import sys
import django

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User, Role

def test_global_admin():
    print("=" * 60)
    print("测试全局管理员角色功能")
    print("=" * 60)

    # 1. 检查是否有全局管理员角色
    print("\n1. 检查全局管理员角色...")
    global_admin_roles = Role.objects.filter(is_global_admin=True)
    print(f"   全局管理员角色数量: {global_admin_roles.count()}")
    for role in global_admin_roles:
        print(f"   - {role.name} (ID: {role.id})")

    # 2. 创建一个测试的全局管理员角色
    print("\n2. 创建测试全局管理员角色...")
    test_role, created = Role.objects.get_or_create(
        name='测试全局管理员',
        defaults={
            'desc': '用于测试的全局管理员角色',
            'is_global_admin': True,
            'created_by': User.objects.first()
        }
    )
    print(f"   {'创建' if created else '已存在'}: {test_role.name} (is_global_admin={test_role.is_global_admin})")

    # 3. 创建一个普通角色
    print("\n3. 创建测试普通角色...")
    normal_role, created = Role.objects.get_or_create(
        name='测试普通角色',
        defaults={
            'desc': '用于测试的普通角色',
            'is_global_admin': False,
            'created_by': User.objects.first()
        }
    )
    print(f"   {'创建' if created else '已存在'}: {normal_role.name} (is_global_admin={normal_role.is_global_admin})")

    # 4. 测试User.is_global_admin属性
    print("\n4. 测试用户is_global_admin属性...")
    test_user = User.objects.filter(is_supper=False).first()
    if test_user:
        print(f"   测试用户: {test_user.username}")

        # 清除现有角色
        test_user.roles.clear()

        # 测试没有全局管理员角色的情况
        test_user.roles.add(normal_role)
        print(f"   拥有普通角色 '{normal_role.name}' 时的 is_global_admin: {test_user.is_global_admin}")

        # 测试有全局管理员角色的情况
        test_user.roles.clear()
        test_user.roles.add(test_role)
        print(f"   拥有全局管理员角色 '{test_role.name}' 时的 is_global_admin: {test_user.is_global_admin}")

        # 测试同时拥有两种角色的情况
        test_user.roles.add(normal_role)
        print(f"   同时拥有两种角色时的 is_global_admin: {test_user.is_global_admin}")
    else:
        print("   警告: 没有找到测试用户")

    # 5. 测试超级管理员
    print("\n5. 测试超级用户...")
    supper_users = User.objects.filter(is_supper=True)
    if supper_users.exists():
        for user in supper_users:
            print(f"   {user.username} (is_super={user.is_supper}, is_global_admin={user.is_global_admin})")
    else:
        print("   没有找到超级用户")

    # 6. 测试to_dict方法是否包含is_global_admin
    print("\n6. 测试Role.to_dict()方法...")
    role_dict = test_role.to_dict()
    print(f"   to_dict()中包含的字段: {list(role_dict.keys())}")
    print(f"   is_global_admin值: {role_dict.get('is_global_admin')}")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)

if __name__ == '__main__':
    test_global_admin()
