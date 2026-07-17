from apps.account.models import User
u = User.objects.get(username='admin')
u.password_hash = User.make_password('spug.dev')
u.save()
print('RESET_OK', u.username)
