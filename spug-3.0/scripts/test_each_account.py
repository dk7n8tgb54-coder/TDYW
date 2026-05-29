#!/usr/bin/env python
"""
单独测试每个账号，避免批量操作导致禁用
"""
import requests
import time

API_BASE = "http://localhost/api/account"

ACCOUNTS = [
    {'username': 'admin', 'password': 'Admin888', 'name': '管理员'},
    {'username': 'tongxinke', 'password': 'Dt@6299093', 'name': '通信科'},
    {'username': 'zidonghuake', 'password': 'Aa@123456', 'name': '自动化科'},
    {'username': 'daohangke', 'password': 'Aa@123456', 'name': '导航科'},
    {'username': 'dianhuake', 'password': 'Aa@123456', 'name': '电话科'},
]

print("="*70)
print("  单独测试每个账号")
print("="*70)

success_count = 0
fail_count = 0

for i, account in enumerate(ACCOUNTS, 1):
    print(f"\n测试 {i}/{len(ACCOUNTS)}")
    print(f"【{account['name']}】{account['username']}")

    response = requests.post(
        f"{API_BASE}/login/",
        json={
            'username': account['username'],
            'password': account['password'],
            'type': 'default'
        },
        headers={'Content-Type': 'application/json'}
    )

    if response.status_code == 200:
        data = response.json()
        if 'error' in data and data['error']:
            print(f"  [X] 失败: {data['error']}")
            fail_count += 1
        elif 'access_token' in data:
            print(f"  [OK] 成功！Token: {data['access_token'][:16]}...")
            success_count += 1
    else:
        print(f"  [X] HTTP {response.status_code}: {response.text}")
        fail_count += 1

    time.sleep(0.5)  # 避免触发禁用机制

print("\n" + "="*70)
print(f"  测试结果: 成功 {success_count}/{len(ACCOUNTS)}")
print("="*70)
