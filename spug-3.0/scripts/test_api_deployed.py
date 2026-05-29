#!/usr/bin/env python3
"""
简单测试：检查API接口是否部署成功（不需要Token）
"""
import requests
import sys

BASE_URL = "http://localhost/api"

def test_api(url, name):
    """测试单个API"""
    full_url = f"{BASE_URL}{url}"
    print(f"\n测试: {name}")
    print(f"URL: {full_url}")
    
    try:
        # 不带Token请求，期望返回401（认证失败）
        resp = requests.post(full_url, json={}, timeout=5)
        
        if resp.status_code == 401 or resp.status_code == 403:
            print(f"✅ 接口已部署 (返回{resp.status_code}，认证失败是正常行为)")
            return True
        elif resp.status_code == 400:
            print(f"✅ 接口已部署 (返回400，参数验证工作正常)")
            return True
        elif resp.status_code == 404:
            print(f"❌ 接口不存在 (404)")
            return False
        else:
            print(f"ℹ️  返回状态码: {resp.status_code}")
            return True
            
    except requests.exceptions.ConnectionError:
        print(f"❌ 连接失败 - 请检查服务是否启动: {BASE_URL}")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def main():
    print("="*60)
    print("API部署检查 (无需Token)")
    print("="*60)
    print(f"\n目标地址: {BASE_URL}")
    
    tests = [
        ("/document/upload/check/", "分片检测接口"),
        ("/document/direct_merge/", "直接合并接口"),
        ("/document/health/", "健康检查接口"),
    ]
    
    results = []
    for url, name in tests:
        results.append(test_api(url, name))
    
    print("\n" + "="*60)
    passed = sum(results)
    total = len(results)
    
    if all(results):
        print(f"✅ 所有接口已部署 ({passed}/{total})")
        print("\n下一步：")
        print("1. 启动后端服务")
        print("2. 登录系统获取Token")
        print("3. 运行完整测试: python scripts/test_merge_retry.py")
    else:
        print(f"⚠️  部分接口检查失败 ({passed}/{total})")
        print("\n可能原因：")
        print("1. 服务未启动 - 运行: docker-compose up -d")
        print("2. 地址错误 - 修改BASE_URL")
        print("3. Django未迁移 - 运行: python manage.py migrate")
    
    return all(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
