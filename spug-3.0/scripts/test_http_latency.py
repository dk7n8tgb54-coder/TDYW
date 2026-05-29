#!/usr/bin/env python
"""测试HTTP请求延迟"""
import requests
import time
import statistics

# 测试配置
BASE_URL = "http://localhost:80"
TOKEN = None  # 登录后会设置

def login():
    """登录获取token"""
    global TOKEN
    url = f"{BASE_URL}/api/account/login/"
    data = {
        "username": "tongxinke",
        "password": "Dt@6299093",
        "type": "default"
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        result = response.json()
        TOKEN = result['data']['access_token']
        print(f"登录成功，获取到token")
        return True
    else:
        print(f"登录失败: {response.status_code}")
        return False

def test_endpoint(name, url, method='GET', params=None, json_data=None):
    """测试单个端点"""
    headers = {
        "X-Token": TOKEN,
        "Content-Type": "application/json"
    }

    times = []
    for i in range(20):
        start = time.time()
        if method == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=10)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=json_data, timeout=10)
        elapsed = (time.time() - start) * 1000
        times.append(elapsed)

    times.sort()
    p50 = statistics.median(times)
    p95 = times[int(len(times) * 0.95)]
    p99 = times[int(len(times) * 0.99)]
    avg = sum(times) / len(times)

    print(f"\n{name}:")
    print(f"  平均: {avg:.2f}ms")
    print(f"  P50:  {p50:.2f}ms")
    print(f"  P95:  {p95:.2f}ms")
    print(f"  P99:  {p99:.2f}ms")
    print(f"  最快: {min(times):.2f}ms")
    print(f"  最慢: {max(times):.2f}ms")

    return avg, p95

if __name__ == '__main__':
    print("="*70)
    print("  HTTP请求延迟测试")
    print("="*70)

    if not login():
        exit(1)

    print("\n开始测试各端点...")

    # 测试列表查询
    test_endpoint("列表查询", f"{BASE_URL}/api/runlog/", 'GET')

    # 测试统计接口
    test_endpoint("统计接口", f"{BASE_URL}/api/runlog/statistics/", 'GET')

    # 测试获取详情
    test_endpoint("获取详情", f"{BASE_URL}/api/runlog/detail/", 'GET', params={"id": 1})

    print("\n" + "="*70)
    print("测试完成")
    print("="*70)
    print("\n如果:")
    print("  - P95 < 100ms: 网络良好，Django响应快")
    print("  - P95 100-500ms: 正常范围")
    print("  - P95 500-1000ms: 需要优化")
    print("  - P95 > 1000ms: 有严重问题")
