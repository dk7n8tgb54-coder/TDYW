#!/usr/bin/env python
"""
测试登录接口响应格式
"""
import requests

API_BASE = "http://localhost/api/account"

# 测试不同的登录凭据
test_cases = [
    {
        'username': 'admin',
        'password': 'Admin888',
        'type': 'local',
        'desc': '管理员账号'
    },
    {
        'username': 'tongxinke',
        'password': 'Dt@6299093',
        'type': 'local',
        'desc': '通信科账号'
    },
    {
        'username': 'zidonghuake',
        'password': 'Aa@123456',
        'type': 'local',
        'desc': '自动化科账号'
    },
    {
        'username': 'daohangke',
        'password': 'Aa@123456',
        'type': 'local',
        'desc': '导航科账号'
    },
    {
        'username': 'dianhuake',
        'password': 'Aa@123456',
        'type': 'local',
        'desc': '电话科账号'
    }
]

print("="*70)
print("  测试登录接口响应格式")
print("="*70)

for i, test_case in enumerate(test_cases, 1):
    print(f"\n【测试 {i}】{test_case['desc']}")
    print(f"  用户名: {test_case['username']}")
    print(f"  密码: {test_case['password']}")
    
    try:
        response = requests.post(
            f"{API_BASE}/login/",
            json={
                'username': test_case['username'],
                'password': test_case['password'],
                'type': 'default'
            },
            headers={'Content-Type': 'application/json'}
        )
        
        print(f"  状态码: {response.status_code}")
        print(f"  响应内容: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"  响应JSON:")
            for key, value in data.items():
                print(f"    {key}: {value if key != 'permissions' else f'[{len(value)}个权限]'}")
            
            if 'access_token' in data:
                print(f"  [OK] 找到 access_token")
            if 'error' in data:
                print(f"  [ERROR] 包含错误信息: {data['error']}")

    except Exception as e:
        print(f"  [ERROR] 请求失败: {e}")

print("\n" + "="*70)
