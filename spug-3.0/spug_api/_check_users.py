from apps.account.models import User
u = User.objects.get(username='admin')
u.password_hash = User.make_password('Spug@admin')
u.save()
print('password reset, verify:', u.verify_password('Spug@admin'))
