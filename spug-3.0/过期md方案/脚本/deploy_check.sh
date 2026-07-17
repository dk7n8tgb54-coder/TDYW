#!/bin/sh
cd /data/spug/spug_api
export DJANGO_SETTINGS_MODULE=spug.settings
python -c "
import django
django.setup()
from apps.account.models import Role
print('Checking for deploy in role permissions...')
for role in Role.objects.all():
    print(f'Role: {role.name}')
    if role.page_perms and 'deploy' in role.page_perms:
        print(f'  HAS deploy!')
        print(f'  {role.page_perms[:200]}')
" 2>&1
