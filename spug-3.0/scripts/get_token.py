#!/usr/bin/env python
"""
获取用户Token的快捷脚本
"""
import sys
import os

# 添加spug_api到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'spug_api'))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User
from rest_framework.authtoken.models import Token

def get_token(username='admin'):
    """获取指定用户的Token"""
    try:
        user = User.objects.filter(username=username).first()
        if not user:
            print(f'错误：未找到用户 {username}')
            return None
        
        token, created = Token.objects.get_or_create(user=user)
        
        print(f"\n{'='*60}")
        print(f"用户: {username}")
        print(f"Token: {token.key}")
        print(f"{'='*60}\n")
        
        print(f"使用方法1 - 直接修改测试脚本：")
        print(f'  TOKEN = "{token.key}"')
        print(f"\n使用方法2 - 命令行测试：")
        print(f'  curl -H "Authorization: Token {token.key}" http://localhost/api/document/health/')
        
        return token.key
        
    except Exception as e:
        print(f'获取Token失败: {e}')
        return None

if __name__ == '__main__':
    username = sys.argv[1] if len(sys.argv) > 1 else 'admin'
    get_token(username)
