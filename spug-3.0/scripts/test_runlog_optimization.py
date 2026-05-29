#!/usr/bin/env python
"""运行日志统计接口优化测试脚本"""

import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from django.test import RequestFactory
from apps.runlog.models import RunLog
from apps.account.models import User
from spug_api.apps.runlog.views import RunLogStatisticsView

def print_section(title):
    """打印分节标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def test_query_count():
    """测试1：验证查询次数为2次（替代12次）"""
    print_section("测试1：验证查询次数为2次")
    
    # 创建测试用户
    user = User.objects.filter(username='test_user').first()
    if not user:
        user = User.objects.create_user(username='test_user', password='test123', tenant_id=1)
        print(f"✓ 创建测试用户: {user.username}")
    
    # 创建测试请求
    factory = RequestFactory()
    request = factory.get('/api/runlog/statistics/')
    request.user = user
    
    # 监控查询次数
    from django.test.utils import override_settings
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    
    with CaptureQueriesContext(connection) as queries:
        view = RunLogStatisticsView()
        response = view.get(request)
    
    query_count = len(queries)
    print(f"  查询次数: {query_count}")
    
    if query_count <= 2:
        print(f"  ✅ 测试通过：查询次数为{query_count}次（预期≤2次）")
        return True
    else:
        print(f"  ❌ 测试失败：查询次数为{query_count}次（预期≤2次）")
        print(f"  查询详情:")
        for i, q in enumerate(queries):
            print(f"    {i+1}. {q['sql'][:100]}...")
        return False

def test_empty_data():
    """测试2：验证7天内无数据时返回默认值"""
    print_section("测试2：验证7天内无数据时返回默认值")
    
    user = User.objects.filter(username='test_user').first()
    if not user:
        user = User.objects.create_user(username='test_user', password='test123', tenant_id=1)
    
    factory = RequestFactory()
    request = factory.get('/api/runlog/statistics/')
    request.user = user
    
    view = RunLogStatisticsView()
    response = view.get(request)
    
    if hasattr(response, 'data'):
        data = response.data
    elif hasattr(response, 'json'):
        data = response.json()
    else:
        import json
        data = json.loads(response.content.decode())
    
    # 验证默认值
    status_count = data.get('status_stats', {})
    severity_count = data.get('severity_stats', {})
    trend_data = data.get('trend_data', [])
    
    checks = [
        (status_count.get('in_progress', {}).get('count', -1) == 0, 
         f"in_progress默认值: {status_count.get('in_progress', {}).get('count', 'N/A')}"),
        (status_count.get('resolved', {}).get('count', -1) == 0, 
         f"resolved默认值: {status_count.get('resolved', {}).get('count', 'N/A')}"),
        (severity_count.get('P0', {}).get('count', -1) == 0, 
         f"P0默认值: {severity_count.get('P0', {}).get('count', 'N/A')}"),
        (severity_count.get('P1', {}).get('count', -1) == 0, 
         f"P1默认值: {severity_count.get('P1', {}).get('count', 'N/A')}"),
        (severity_count.get('P2', {}).get('count', -1) == 0, 
         f"P2默认值: {severity_count.get('P2', {}).get('count', 'N/A')}"),
        (len(trend_data) == 7, 
         f"趋势数据条数: {len(trend_data)}"),
    ]
    
    all_passed = True
    for check, msg in checks:
        if check:
            print(f"  ✅ {msg}")
        else:
            print(f"  ❌ {msg}")
            all_passed = False
    
    if all_passed:
        print(f"\n  ✅ 测试通过：7天内无数据时返回正确的默认值")
    else:
        print(f"\n  ❌ 测试失败：7天内无数据时默认值不正确")
    
    return all_passed

def test_response_format():
    """测试3：验证响应格式正确"""
    print_section("测试3：验证响应格式正确")
    
    user = User.objects.filter(username='test_user').first()
    if not user:
        user = User.objects.create_user(username='test_user', password='test123', tenant_id=1)
    
    factory = RequestFactory()
    request = factory.get('/api/runlog/statistics/')
    request.user = user
    
    view = RunLogStatisticsView()
    response = view.get(request)
    
    if hasattr(response, 'data'):
        data = response.data
    elif hasattr(response, 'json'):
        data = response.json()
    else:
        import json
        data = json.loads(response.content.decode())
    
    required_fields = ['status_stats', 'severity_stats', 'trend_data']
    all_present = all(field in data for field in required_fields)
    
    if all_present:
        print(f"  ✅ 响应包含所有必需字段: {required_fields}")
        
        # 验证嵌套结构
        status_keys = data['status_stats'].keys()
        severity_keys = data['severity_stats'].keys()
        
        print(f"  ✅ status_stats包含字段: {list(status_keys)}")
        print(f"  ✅ severity_stats包含字段: {list(severity_keys)}")
        print(f"  ✅ trend_data包含{len(data['trend_data'])}条记录")
        
        print(f"\n  ✅ 测试通过：响应格式正确")
        return True
    else:
        missing = [f for f in required_fields if f not in data]
        print(f"  ❌ 响应缺少字段: {missing}")
        print(f"\n  ❌ 测试失败：响应格式不正确")
        return False

def test_exception_handling():
    """测试4：验证异常处理"""
    print_section("测试4：验证异常处理")
    
    user = User.objects.filter(username='test_user').first()
    if not user:
        user = User.objects.create_user(username='test_user', password='test123', tenant_id=1)
    
    factory = RequestFactory()
    
    # 测试1：无效租户ID（移除tenant_id）
    request1 = factory.get('/api/runlog/statistics/')
    request1.user = user
    delattr(request1.user, 'tenant_id')
    
    view = RunLogStatisticsView()
    response1 = view.get(request1)
    
    if hasattr(response1, 'status_code') and response1.status_code == 400:
        print(f"  ✅ 无效租户ID返回400错误")
    else:
        print(f"  ❌ 无效租户ID未返回400错误")
        return False
    
    print(f"\n  ✅ 测试通过：异常处理正确")
    return True

def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("  运行日志统计接口优化测试")
    print("="*60)
    
    tests = [
        ("查询次数优化", test_query_count),
        ("空数据边界处理", test_empty_data),
        ("响应格式验证", test_response_format),
        ("异常处理验证", test_exception_handling),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed, None))
        except Exception as e:
            print(f"\n  ❌ 测试异常: {str(e)}")
            import traceback
            traceback.print_exc()
            results.append((name, False, str(e)))
    
    # 打印汇总
    print_section("测试结果汇总")
    passed_count = sum(1 for _, passed, _ in results if passed)
    total_count = len(results)
    
    for name, passed, error in results:
        status = "✅ 通过" if passed else f"❌ 失败 ({error})"
        print(f"  {status} - {name}")
    
    print(f"\n  总计: {passed_count}/{total_count} 通过")
    
    if passed_count == total_count:
        print(f"\n  🎉 所有测试通过！")
        return 0
    else:
        print(f"\n  ⚠️  部分测试失败")
        return 1

if __name__ == '__main__':
    sys.exit(main())
