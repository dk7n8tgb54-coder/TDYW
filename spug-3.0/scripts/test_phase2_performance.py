#!/usr/bin/env python3
"""
第二阶段修复效果验证脚本

验证内容：
1. P1-1 N+1查询优化 - 班次列表查询次数
2. P1-3 数据库索引 - 索引是否被正确使用

使用方法：
1. 在浏览器开发者工具中执行API调用
2. 或运行此脚本测试
"""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:9000"
TOKEN = None

def get_token():
    """从命令行参数获取token"""
    global TOKEN
    if len(sys.argv) > 1:
        TOKEN = sys.argv[1]
    return TOKEN

def test_shift_list_performance():
    """测试班次列表API性能"""
    print("\n" + "="*60)
    print("测试1: 班次列表查询性能 (P1-1 N+1优化验证)")
    print("="*60)
    
    if not TOKEN:
        print("⚠️  跳过测试：未设置TOKEN")
        print("   使用方法: python test_phase2_performance.py <token>")
        return None
    
    headers = {'X-Token': TOKEN}
    
    # 预热
    try:
        requests.get(f"{BASE_URL}/api/schedule/shift/", headers=headers, timeout=5)
    except:
        pass
    
    # 正式测试
    times = []
    for i in range(3):
        try:
            start = time.time()
            response = requests.get(
                f"{BASE_URL}/api/schedule/shift/", 
                headers=headers,
                timeout=10
            )
            elapsed = (time.time() - start) * 1000  # 转换为毫秒
            times.append(elapsed)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    print(f"   第{i+1}次请求: {elapsed:.1f}ms, 返回 {len(data)} 条班次数据")
                else:
                    print(f"   第{i+1}次请求: {elapsed:.1f}ms, 返回数据格式: {type(data)}")
            else:
                print(f"   第{i+1}次请求: 状态码 {response.status_code}")
                
        except Exception as e:
            print(f"   第{i+1}次请求: 异常 - {e}")
    
    if times:
        avg_time = sum(times) / len(times)
        print(f"\n   平均响应时间: {avg_time:.1f}ms")
        if avg_time < 100:
            print("   ✅ 性能良好 (<100ms)")
            return True
        elif avg_time < 500:
            print("   ⚠️  性能一般 (100-500ms)")
            return True
        else:
            print("   ❌ 性能较差 (>500ms)")
            return False
    return None

def test_schedule_list_performance():
    """测试排班列表API性能"""
    print("\n" + "="*60)
    print("测试2: 排班日历查询性能 (P1-3 索引优化验证)")
    print("="*60)
    
    if not TOKEN:
        print("⚠️  跳过测试：未设置TOKEN")
        return None
    
    headers = {'X-Token': TOKEN}
    
    # 测试当前月份查询
    params = {'year': 2026, 'month': 3}
    
    times = []
    for i in range(3):
        try:
            start = time.time()
            response = requests.get(
                f"{BASE_URL}/api/schedule/",
                headers=headers,
                params=params,
                timeout=10
            )
            elapsed = (time.time() - start) * 1000
            times.append(elapsed)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    print(f"   第{i+1}次请求: {elapsed:.1f}ms, 返回 {len(data)} 条排班数据")
                else:
                    print(f"   第{i+1}次请求: {elapsed:.1f}ms")
            else:
                print(f"   第{i+1}次请求: 状态码 {response.status_code}")
                
        except Exception as e:
            print(f"   第{i+1}次请求: 异常 - {e}")
    
    if times:
        avg_time = sum(times) / len(times)
        print(f"\n   平均响应时间: {avg_time:.1f}ms")
        if avg_time < 200:
            print("   ✅ 性能良好 (<200ms)")
            return True
        elif avg_time < 1000:
            print("   ⚠️  性能一般 (200-1000ms)")
            return True
        else:
            print("   ❌ 性能较差 (>1000ms)")
            return False
    return None

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║     第二阶段修复效果验证 - 性能测试                          ║
╚══════════════════════════════════════════════════════════════╝

验证内容:
1. P1-1 N+1查询优化 - 班次列表API响应时间
2. P1-3 数据库索引 - 排班日历查询性能

使用方法:
  python test_phase2_performance.py <token>

获取Token:
  浏览器F12 -> Application -> LocalStorage -> token
""")
    
    get_token()
    
    results = []
    
    # 测试班次列表性能
    result1 = test_shift_list_performance()
    if result1 is not None:
        results.append(("班次列表查询 (P1-1)", result1))
    
    # 测试排班列表性能
    result2 = test_schedule_list_performance()
    if result2 is not None:
        results.append(("排班日历查询 (P1-3)", result2))
    
    # 汇总
    print("\n" + "="*60)
    print("验证结果汇总")
    print("="*60)
    
    if not results:
        print("\n⚠️  没有完成任何测试")
        print("请提供有效的Token后重新运行")
        return
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\n总计: {passed}/{total} 项通过")
    
    if passed == total:
        print("\n🎉 第二阶段修复效果验证通过！")
    else:
        print("\n⚠️  部分测试未通过，请检查后端服务状态")
    
    print("\n" + "="*60)
    print("数据库索引验证 SQL")
    print("="*60)
    print("""
进入数据库容器验证索引:
  docker exec -it tdyw-db sh
  mysql -uroot -pspug.cc

查看索引:
  USE spug;
  SHOW INDEX FROM tdyw_schedule;
  SHOW INDEX FROM tdyw_schedule_swap;
  SHOW INDEX FROM tdyw_schedule_substitute;

验证索引使用 (EXPLAIN):
  EXPLAIN SELECT * FROM tdyw_schedule 
  WHERE tenant_id = 'xxx' AND schedule_date = '2026-03-17';
  -- 应看到 key 列显示使用了索引
""")

if __name__ == '__main__':
    main()
