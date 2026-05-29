from apps.account.models import User, Role, Permission

user = User.objects.filter(username='通信科').first()
if user:
    print('用户:', user.username)
    print('Tenant ID:', user.tenant_id)
    print('角色:', [r.name for r in user.roles.all()])

    perms = []
    for role in user.roles.all():
        for perm in role.permissions.all():
            perms.append(f'{perm.module}.{perm.key}')
    print('所有权限:')
    for p in sorted(set(perms)):
        print(f'  {p}')
else:
    print('未找到通信科用户')
