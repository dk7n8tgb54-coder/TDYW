from django.core.cache import cache
from apps.account.models import User
cache.delete('login_fail:user:admin')
cache.delete('login_fail:ip:127.0.0.1')
cache.delete('login_fail:ip:::1')
u = User.objects.filter(username='admin').first()
print('USER', u, 'ACTIVE', u.is_active if u else None)
print('VERIFY', u.verify_password('spug.dev') if u else None)
