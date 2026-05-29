#!/usr/bin/env python
"""测试运行日志API"""
import os
import sys
import django

# 设置Django环境
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.test import RequestFactory
from apps.runlog.models import RunLog
from apps.runlog.views import RunLogStatisticsView
from apps.account.models import User
from datetime import datetime, timedelta

def test_statistics_api():
    """测试统计API"""
    print("="*60)
    print("  测试运行日志统计API")
    print("="*60)

    # 创建或获取测试用户
    user = User.objects.filter(username='test_user').first()
    if not user:
        from libs import human_datetime
        import string
        import random

        access_token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        user = User.objects.create(
            username='test_user',
            nickname='测试用户',
            password_hash=User.make_password('test123'),
            type='default',
            is_supper=False,
            is_active=True,
            access_token=access_token,
            token_expired=None,
            last_login=human_datetime(),
            last_ip='127.0.0.1',
            tenant_id='admin'
        )
        print(f"✅ 创建测试用户: {user.username}")

    # 创建测试请求
    factory = RequestFactory()
    request = factory.get('/api/runlog/statistics/')
    request.user = user

    print(f"\n测试用户: {user.username}")
    print(f"租户ID: {getattr(user, 'tenant_id', 'None')}")

    try:
        # 调用视图
        view = RunLogStatisticsView()
        response = view.get(request)

        # 检查响应
        if hasattr(response, 'data'):
            data = response.data
        elif hasattr(response, 'json'):
            data = response.json()
        else:
            import json
            response_str = response.content.decode()
            print(f"原始响应: {response_str}")
            data = json.loads(response_str)

        print(f"\n✅ API调用成功")
        print(f"响应状态码: {getattr(response, 'status_code', 'Unknown')}")

        # 检查响应结构
        if isinstance(data, dict) and 'data' in data:
            print(f"响应包含'data'字段，提取内部数据")
            data = data['data']

        print(f"\n统计数据:")
        print(f"  status_stats: {data.get('status_stats', {})}")
        print(f"  severity_stats: {data.get('severity_stats', {})}")
        print(f"  trend_data条数: {len(data.get('trend_data', []))}")

        return 0

    except Exception as e:
        print(f"\n❌ API调用失败")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        import traceback
        print(f"\n错误堆栈:")
        traceback.print_exc()
        return 1

def test_list_api():
    """测试列表API"""
    print("\n" + "="*60)
    print("  测试运行日志列表API")
    print("="*60)

    # 创建或获取测试用户
    user = User.objects.filter(username='test_user').first()
    if not user:
        from libs import human_datetime
        import string
        import random

        access_token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        user = User.objects.create(
            username='test_user',
            nickname='测试用户',
            password_hash=User.make_password('test123'),
            type='default',
            is_supper=False,
            is_active=True,
            access_token=access_token,
            token_expired=None,
            last_login=human_datetime(),
            last_ip='127.0.0.1',
            tenant_id='admin'
        )

    # 创建测试请求
    factory = RequestFactory()
    request = factory.get('/api/runlog/')
    request.user = user

    try:
        # 导入视图
        from apps.runlog.views import RunLogView

        # 调用视图
        view = RunLogView()
        response = view.get(request)

        # 检查响应
        if hasattr(response, 'data'):
            data = response.data
        elif hasattr(response, 'json'):
            data = response.json()
        else:
            import json
            data = json.loads(response.content.decode())

        print(f"\n✅ API调用成功")
        print(f"响应状态码: {getattr(response, 'status_code', 'Unknown')}")
        print(f"系统名称数量: {len(data.get('system_names', []))}")
        print(f"日志数量: {len(data.get('logs', []))}")

        return 0

    except Exception as e:
        print(f"\n❌ API调用失败")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        import traceback
        print(f"\n错误堆栈:")
        traceback.print_exc()
        return 1

def main():
    """运行所有测试"""
    print("\n运行日志API测试")
    print("="*60 + "\n")

    results = []

    # 测试统计API
    result1 = test_statistics_api()
    results.append(("统计API", result1 == 0))

    # 测试列表API
    result2 = test_list_api()
    results.append(("列表API", result2 == 0))

    # 打印汇总
    print("\n" + "="*60)
    print("  测试结果汇总")
    print("="*60)

    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status} - {name}")

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    print(f"\n总计: {passed_count}/{total_count} 通过")

    if passed_count == total_count:
        print(f"\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️  部分测试失败")
        return 1

if __name__ == '__main__':
    sys.exit(main())
