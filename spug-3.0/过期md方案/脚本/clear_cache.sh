cd /data/spug/spug_api
python -c "
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()
from django.core.cache import cache
from apps.account.models import User, Role
import json

print('=== 清除所有用户的权限缓存 ===')
for user in User.objects.filter(deleted_by_id__isnull=True):
    cache.delete(f'perms_{user.id}')
    user.set_perms_cache()
    print('已清除用户 ' + user.username + ' 的权限缓存')

print('\n=== 检查所有角色的 page_perms ===')
for role in Role.objects.all():
    if role.page_perms:
        perms = json.loads(role.page_perms)
        print('角色: ' + role.name + ', 模块: ' + str(list(perms.keys())))
    else:
        print('角色: ' + role.name + ', page_perms 为空')
"
