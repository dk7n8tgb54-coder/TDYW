#!/usr/bin/env python
"""直接获取Token"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'spug_api'))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User

user = User.objects.filter(username='admin').first()
if user:
    print(f"Token: {user.access_token}")
else:
    print("Error: User 'admin' not found")
