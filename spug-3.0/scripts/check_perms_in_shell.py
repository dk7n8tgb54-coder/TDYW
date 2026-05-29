"""
通过Django shell直接检查角色权限
在项目根目录执行: python manage.py shell < check_perms_in_shell.py
"""

from apps.account.models import User, Role
import json

print("=" * 80)
print("运行日志权限检查")
print("=" * 80)

# 查找通信科相关角色
communication_roles = Role.objects.filter(name__icontains='通信')

if communication_roles.exists():
    for role in communication_roles:
        print(f"\n角色名称: {role.name}")
        print(f"角色ID: {role.id}")
        print(f"备注: {role.desc}")
        
        # 检查page_perms
        if role.page_perms:
            perms = json.loads(role.page_perms)
            print(f"\npage_perms (JSON):")
            print(json.dumps(perms, ensure_ascii=False, indent=2))
            
            # 检查运行日志权限
            runlog_perms = perms.get('runlog', {})
            if runlog_perms:
                print(f"\n运行日志模块权限:")
                for page, page_perms in runlog_perms.items():
                    print(f"  - 页面: {page}")
                    print(f"    权限: {page_perms}")
                    
                    # 检查必需的权限
                    required_runlog_perms = ['view', 'add', 'edit', 'del', 'update_view', 'update_add', 'update_edit', 'update_del']
                    print(f"    权限完整性检查:")
                    for perm in required_runlog_perms:
                        has_perm = perm in page_perms
                        status = "✓" if has_perm else "✗"
                        print(f"      {status} {perm}")
            else:
                print(f"\n⚠️  警告: 未配置运行日志权限")
        else:
            print(f"\n⚠️  警告: 该角色未配置page_perms")
        
        print("-" * 80)
else:
    print("❌ 未找到通信科相关角色")

# 查找通信科相关用户
print(f"\n{'=' * 80}")
print("通信科用户检查")
print("=" * 80)

communication_users = User.objects.filter(username__icontains='通信')
if communication_users.exists():
    for user in communication_users:
        print(f"\n用户名: {user.username}")
        print(f"用户ID: {user.id}")
        print(f"租户ID: {user.tenant_id}")
        print(f"是否超级管理员: {user.is_supper}")
        
        # 获取用户角色
        roles = user.roles.all()
        print(f"角色: {[role.name for role in roles]}")
        
        # 检查实际权限
        print(f"\n实际权限检查:")
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
        
        for perm_code in test_perms:
            has_perm = user.has_perms([perm_code])
            status = "✓" if has_perm else "✗"
            print(f"  {status} {perm_code}")
        
        print(f"\npage_perms 属性内容:")
        print(f"  {user.page_perms}")
        
        print("-" * 80)
else:
    print("❌ 未找到通信科相关用户")

print(f"\n{'=' * 80}")
print("检查完成")
print("=" * 80)
