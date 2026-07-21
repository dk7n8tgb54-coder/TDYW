from apps.account.models import User
for u in User.objects.filter(username__startswith="st_press"):
    print(f"{u.username} | tenant={u.tenant_id} | active={u.is_active} | super={u.is_supper} | type={u.type}")
