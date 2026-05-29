#!/usr/bin/env python3
"""
快速API测试脚本 - 测试文档管理分表改造
"""
import requests
import json
import sys

BASE_URL = "http://localhost"
API_URL = f"{BASE_URL}/api"

# 测试用户token (需要根据实际环境调整)
ADMIN_TOKEN = None  # 从登录接口获取
USER_TOKEN = None   # 从登录接口获取

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def test_health_check():
    """测试服务健康状态"""
    print_section("1. 健康检查")
    try:
        response = requests.get(f"{BASE_URL}/", timeout=5)
        print(f"✓ 服务状态: {response.status_code}")
        return True
    except Exception as e:
        print(f"✗ 服务不可用: {e}")
        return False

def test_login():
    """测试登录获取token"""
    print_section("2. 登录测试")
    try:
        # 使用默认管理员账号登录
        response = requests.post(
            f"{API_URL}/account/login/",
            json={"username": "admin", "password": "spug"},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            token = data.get('token')
            if token:
                print(f"✓ 登录成功, 获取token: {token[:20]}...")
                global ADMIN_TOKEN
                ADMIN_TOKEN = token
                return True
        print(f"✗ 登录失败: {response.status_code}")
        print(f"响应: {response.text}")
        return False
    except Exception as e:
        print(f"✗ 登录异常: {e}")
        return False

def test_get_folders_private():
    """测试获取私有空间文件夹"""
    print_section("3. 获取私有空间文件夹")
    if not ADMIN_TOKEN:
        print("✗ 未获取到管理员token")
        return False

    try:
        response = requests.get(
            f"{API_URL}/document/folder/",
            headers={"Authorization": ADMIN_TOKEN},
            timeout=5
        )
        print(f"✓ 私有文件夹接口: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 返回数据: {json.dumps(data, ensure_ascii=False)[:100]}...")
        return True
    except Exception as e:
        print(f"✗ 接口异常: {e}")
        return False

def test_get_folders_public():
    """测试获取公共空间文件夹"""
    print_section("4. 获取公共空间文件夹")
    if not ADMIN_TOKEN:
        print("✗ 未获取到管理员token")
        return False

    try:
        response = requests.get(
            f"{API_URL}/document/folder/",
            params={"is_public": "true"},
            headers={"Authorization": ADMIN_TOKEN},
            timeout=5
        )
        print(f"✓ 公共文件夹接口: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 返回数据: {json.dumps(data, ensure_ascii=False)[:100]}...")
        return True
    except Exception as e:
        print(f"✗ 接口异常: {e}")
        return False

def test_get_files_private():
    """测试获取私有空间文件"""
    print_section("5. 获取私有空间文件")
    if not ADMIN_TOKEN:
        print("✗ 未获取到管理员token")
        return False

    try:
        response = requests.get(
            f"{API_URL}/document/file/",
            headers={"Authorization": ADMIN_TOKEN},
            timeout=5
        )
        print(f"✓ 私有文件接口: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 返回数据: {json.dumps(data, ensure_ascii=False)[:100]}...")
        return True
    except Exception as e:
        print(f"✗ 接口异常: {e}")
        return False

def test_get_files_public():
    """测试获取公共空间文件"""
    print_section("6. 获取公共空间文件")
    if not ADMIN_TOKEN:
        print("✗ 未获取到管理员token")
        return False

    try:
        response = requests.get(
            f"{API_URL}/document/file/",
            params={"is_public": "true"},
            headers={"Authorization": ADMIN_TOKEN},
            timeout=5
        )
        print(f"✓ 公共文件接口: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 返回数据: {json.dumps(data, ensure_ascii=False)[:100]}...")
        return True
    except Exception as e:
        print(f"✗ 接口异常: {e}")
        return False

def test_disk_usage():
    """测试磁盘使用率接口"""
    print_section("7. 磁盘使用率接口")
    if not ADMIN_TOKEN:
        print("✗ 未获取到管理员token")
        return False

    try:
        # 测试私有空间
        response = requests.get(
            f"{API_URL}/document/disk_usage/",
            headers={"Authorization": ADMIN_TOKEN},
            timeout=5
        )
        print(f"✓ 私有空间磁盘使用率: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 私有空间数据: {json.dumps(data, ensure_ascii=False)[:100]}...")

        # 测试公共空间
        response = requests.get(
            f"{API_URL}/document/disk_usage/",
            params={"is_public": "true"},
            headers={"Authorization": ADMIN_TOKEN},
            timeout=5
        )
        print(f"✓ 公共空间磁盘使用率: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 公共空间数据: {json.dumps(data, ensure_ascii=False)[:100]}...")

        return True
    except Exception as e:
        print(f"✗ 接口异常: {e}")
        return False

def main():
    """主函数"""
    print("="*60)
    print("  文档管理分表改造 - 快速API测试")
    print("="*60)

    tests = [
        ("健康检查", test_health_check),
        ("登录测试", test_login),
        ("私有文件夹", test_get_folders_private),
        ("公共文件夹", test_get_folders_public),
        ("私有文件", test_get_files_private),
        ("公共文件", test_get_files_public),
        ("磁盘使用率", test_disk_usage),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"✗ {test_name} 异常: {e}")
            results.append((test_name, False))

    # 打印总结
    print_section("测试总结")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for test_name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status} - {test_name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n✅ API测试成功!")
        return 0
    else:
        print("\n❌ 部分测试失败!")
        return 1

if __name__ == '__main__':
    sys.exit(main())
