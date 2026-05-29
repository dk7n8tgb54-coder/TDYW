"""
测试权限生成和检查逻辑
"""
import json

# 模拟codes.js中的权限定义
codes = {
    'runlog': {
        'runlog': ['view', 'add', 'edit', 'del', 'update_view', 'update_add', 'update_edit', 'update_del']
    }
}

# 模拟数据库中保存的page_perms (角色重新勾选后的JSON)
role_page_perms = {
    'runlog': {
        'runlog': ['view', 'add', 'edit', 'del', 'update_view', 'update_add', 'update_edit', 'update_del']
    }
}

# 模拟User.page_perms属性的生成逻辑
def generate_user_page_perms(page_perms):
    """模拟User模型的page_perms属性生成"""
    data = set()
    for m, v in page_perms.items():
        for p, d in v.items():
            data.update(f'{m}.{p}.{x}' for x in d)
    return data

# 测试
print("=" * 60)
print("权限生成测试")
print("=" * 60)

user_perms = generate_user_page_perms(role_page_perms)
print(f"\n生成的用户权限:")
for perm in sorted(user_perms):
    print(f"  - {perm}")

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

print(f"\n权限检查测试:")
for perm in test_perms:
    has_perm = perm in user_perms
    status = "✓" if has_perm else "✗"
    print(f"  {status} {perm}")

# 测试intersection
print(f"\n使用intersection测试:")
codes_to_check = {'runlog.runlog.update_view'}
intersection = user_perms.intersection(codes_to_check)
print(f"  用户权限: {user_perms}")
print(f"  检查权限: {codes_to_check}")
print(f"  交集: {intersection}")
print(f"  有权限: {len(intersection) > 0}")
