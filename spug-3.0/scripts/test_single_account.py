#!/usr/bin/env python
"""
谨慎测试单个账号登录
"""
import requests

API_BASE = "http://localhost/api/account"

print("="*70)
print("  谨慎测试：admin 账号")
print("="*70)

username = 'admin'
password = 'Admin888'

print(f"\n用户名: {username}")
print(f"密码: {password}")

response = requests.post(
    f"{API_BASE}/login/",
    json={
        'username': username,
        'password': password,
        'type': 'local'
    },
    headers={
        'Content-Type': 'application/json'
    }
)

print(f"\n状态码: {response.status_code}")
print(f"响应: {response.text}")

if response.status_code == 200:
    data = response.json()
    if 'error' in data:
        print(f"[X] 失败: {data['error']}")
    elif 'access_token' in data:
        print(f"[OK] 成功！Token: {data['access_token'][:16]}...")

print("\n" + "="*70)
