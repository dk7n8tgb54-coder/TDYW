#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from libs import JsonParser, Argument

# 测试各种输入
test_cases = [
    b'{"username":"admin","password":"spug"}',
    '{"username":"admin","password":"spug"}',
]

for i, data in enumerate(test_cases):
    print(f'Test {i+1}: type={type(data).__name__}, data={data}')
    try:
        form, error = JsonParser(
            Argument('username', help='请输入用户名'),
            Argument('password', help='请输入密码'),
            Argument('captcha', required=False),
            Argument('type', required=False)
        ).parse(data)
        print(f'  Result: form={dict(form) if form else None}, error={error}')
    except Exception as e:
        print(f'  Exception: {e}')
        import traceback
        traceback.print_exc()
