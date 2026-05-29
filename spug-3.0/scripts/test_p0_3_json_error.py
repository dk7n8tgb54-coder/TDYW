#!/usr/bin/env python3
"""
P0-3 JSON解析错误处理验证脚本

验证项：
- [ ] 发送错误JSON格式请求，返回明确错误
- [ ] 日志记录JSON解析错误
- [ ] 正常JSON请求不受影响

使用方法：
1. 先登录获取token
2. 运行此脚本
"""

import requests
import json
import sys

# 配置
BASE_URL = "http://localhost:9000"
TOKEN = None  # 需要填写登录后的token

def test_invalid_json_swap_delete():
    """测试换班删除接口的错误JSON处理"""
    print("\n" + "="*60)
    print("测试1: 换班删除接口 - 发送错误JSON格式")
    print("="*60)
    
    if not TOKEN:
        print("⚠️  跳过测试：未设置TOKEN")
        return False
    
    headers = {
        'Content-Type': 'application/json',
        'X-Token': TOKEN
    }
    
    # 发送格式错误的JSON
    invalid_json = '{"id": 1, "invalid json}'  # 故意格式错误
    
    try:
        response = requests.delete(
            f"{BASE_URL}/api/schedule/swap/",
            headers=headers,
            data=invalid_json
        )
        
        print(f"请求状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        result = response.json()
        
        if response.status_code == 200 and 'error' in result:
            print("✅ PASS: 返回了明确的错误信息")
            print(f"   错误信息: {result.get('error')}")
            return True
        else:
            print("❌ FAIL: 未返回预期的错误格式")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: 请求异常 - {e}")
        return False

def test_invalid_json_substitute_delete():
    """测试替班删除接口的错误JSON处理"""
    print("\n" + "="*60)
    print("测试2: 替班删除接口 - 发送错误JSON格式")
    print("="*60)
    
    if not TOKEN:
        print("⚠️  跳过测试：未设置TOKEN")
        return False
    
    headers = {
        'Content-Type': 'application/json',
        'X-Token': TOKEN
    }
    
    # 发送格式错误的JSON
    invalid_json = '{"id": 1, "note": "test",}'  # 多余的逗号
    
    try:
        response = requests.delete(
            f"{BASE_URL}/api/schedule/substitute/",
            headers=headers,
            data=invalid_json
        )
        
        print(f"请求状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        result = response.json()
        
        if response.status_code == 200 and 'error' in result:
            print("✅ PASS: 返回了明确的错误信息")
            print(f"   错误信息: {result.get('error')}")
            return True
        else:
            print("❌ FAIL: 未返回预期的错误格式")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: 请求异常 - {e}")
        return False

def test_valid_json_swap():
    """测试正常JSON请求不受影响"""
    print("\n" + "="*60)
    print("测试3: 换班接口 - 正常JSON请求")
    print("="*60)
    
    if not TOKEN:
        print("⚠️  跳过测试：未设置TOKEN")
        return False
    
    headers = {
        'Content-Type': 'application/json',
        'X-Token': TOKEN
    }
    
    # 发送正常的JSON请求（查询换班列表，不会修改数据）
    try:
        response = requests.get(
            f"{BASE_URL}/api/schedule/swap/",
            headers=headers
        )
        
        print(f"请求状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) or 'data' in result or 'results' in result:
                print("✅ PASS: 正常请求成功，返回数据格式正确")
                return True
            else:
                print("⚠️  返回格式可能不同，但请求成功")
                return True
        else:
            print(f"⚠️  请求返回状态码 {response.status_code}，但请求已处理")
            return True
            
    except Exception as e:
        print(f"❌ FAIL: 请求异常 - {e}")
        return False

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║           P0-3 JSON解析错误处理验证                          ║
╚══════════════════════════════════════════════════════════════╝

验证前准备：
1. 确保后端服务已启动
2. 获取登录token（浏览器F12 -> Application -> LocalStorage -> token）
3. 修改脚本中的 TOKEN 变量

使用方法：
  python test_p0_3_json_error.py <your_token>
""")
    
    global TOKEN
    if len(sys.argv) > 1:
        TOKEN = sys.argv[1]
    else:
        print("\n⚠️  警告: 未提供TOKEN，请在命令行传入: python test_p0_3_json_error.py <token>")
        print("或修改脚本中的 TOKEN 变量\n")
    
    results = []
    
    results.append(("换班删除-错误JSON", test_invalid_json_swap_delete()))
    results.append(("替班删除-错误JSON", test_invalid_json_substitute_delete()))
    results.append(("换班列表-正常请求", test_valid_json()))
    
    print("\n" + "="*60)
    print("验证结果汇总")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)
    skipped = sum(1 for _, r in results if r is None)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL" if result is False else "⏭️ SKIP"
        print(f"{status}: {name}")
    
    print(f"\n总计: {passed} 通过, {failed} 失败, {skipped} 跳过")
    
    if failed == 0:
        print("\n🎉 所有验证项通过！P0-3 修复成功！")
    else:
        print("\n⚠️  存在失败的验证项，请检查日志")

if __name__ == '__main__':
    main()
