"""
检查运行日志权限配置的脚本
"""
import os
import sys
import django

# 设置Django环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug_api.settings')
django.setup()

from apps.account.models import User, Role
import json

def check_runlog_permissions():
    """检查运行日志相关权限"""
    print("=" * 60)
    print("运行日志权限检查")
    print("=" * 60)

    # 检查通信科角色
    print("\n1. 检查通信科角色权限配置:")
    print("-" * 60)

    communication_role = Role.objects.filter(name__icontains='通信').first()
    if communication_role:
        print(f"角色名称: {communication_role.name}")
        print(f"角色ID: {communication_role.id}")

        # 解析page_perms
        if communication_role.page_perms:
            perms = json.loads(communication_role.page_perms)
            print(f"\n当前权限配置: {json.dumps(perms, ensure_ascii=False, indent=2)}")

            # 检查运行日志权限
            runlog_perms = perms.get('runlog', {})
            if runlog_perms:
                print(f"\n运行日志模块权限:")
                for page, page_perms in runlog_perms.items():
                    print(f"  - {page}: {page_perms}")
            else:
                print(f"\n⚠️  警告: 未配置运行日志权限")

            # 检查是否包含新权限
            runlog_perms_list = runlog_perms.get('runlog', [])
            required_perms = ['view', 'add', 'edit', 'del', 'update_view', 'update_add', 'update_edit', 'update_del']

            print(f"\n所需权限检查:")
            for perm in required_perms:
                has_perm = perm in runlog_perms_list
                status = "✓" if has_perm else "✗"
                print(f"  {status} {perm}")

        else:
            print(f"\n⚠️  警告: 该角色未配置任何页面权限")
    else:
        print("❌ 未找到通信科角色")

    # 检查通信科账号
    print("\n\n2. 检查通信科账号:")
    print("-" * 60)

    communication_users = User.objects.filter(username__icontains='通信')
    for user in communication_users:
        print(f"用户名: {user.username}")
        print(f"用户ID: {user.id}")
        print(f"租户ID: {user.tenant_id}")
        print(f"是否超级管理员: {user.is_supper}")

        # 获取用户角色
        roles = user.roles.all()
        print(f"角色: {[role.name for role in roles]}")

        # 检查权限缓存
        from django.core.cache import cache
        cached_perms = cache.get(f'perms_{user.id}')
        print(f"权限缓存: {cached_perms if cached_perms else '无'}")

        # 测试权限检查
        test_perms = [
            'runlog.runlog.view',
            'runlog.runlog.add',
            'runlog.runlog.edit',
            'runlog.runlog.del',
            'runlog.runlog.update_view',
            'runlog.runlog.update_add',
            'runlog.runlog.update_edit',
            'runlog.runlog.update_del',
        ]

        print(f"\n权限检查结果:")
        for perm_code in test_perms:
            has_perm = user.has_perms([perm_code])
            status = "✓" if has_perm else "✗"
            print(f"  {status} {perm_code}")
        print()

    print("\n" + "=" * 60)
    print("检查完成")
    print("=" * 60)

if __name__ == '__main__':
    check_runlog_permissions()
