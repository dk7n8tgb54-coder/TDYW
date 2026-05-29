#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
传输列表恢复功能测试脚本

测试场景：
1. 创建传输记录（PENDING/UPLOADING/PAUSED）
2. 模拟前端调用 GET /api/document/transfers/
3. 验证返回数据包含 file_hash 字段
4. 验证租户过滤正确
"""

import os
import sys
import django

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data/backend'))

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.document.models import DocumentTransfer, Document
from apps.account.models import User
from apps.libs.tenant_utils import apply_tenant_filter
from django.test import Client, TestCase
from django.utils import timezone
import json
import time


def test_transfer_list_api():
    """测试传输列表 API"""
    print("=" * 60)
    print("测试 1: 传输列表 API 返回 file_hash 字段")
    print("=" * 60)

    # 创建测试用户
    user, _ = User.objects.get_or_create(
        username='test_restore_user',
        defaults={
            'email': 'test_restore@example.com',
            'is_supper': False,
            'tenant_id': 'test_tenant_001'
        }
    )

    # 创建测试传输记录（不同状态）
    now = timezone.now()
    transfers = []

    # 创建 PENDING 状态的记录
    t1 = DocumentTransfer.objects.create(
        tenant_id='test_tenant_001',
        user=user,
        transfer_type='upload',
        status='PENDING',
        file_name='test_file_1.txt',
        file_size=1024 * 1024,
        file_hash='md5_hash_001',
        folder_id=None,
        is_public=False,
        total_chunks=10,
        uploaded_chunks=0,
        progress=0,
        transferred_size=0,
        speed=0,
        created_at=now
    )
    transfers.append(t1)

    # 创建 UPLOADING 状态的记录
    t2 = DocumentTransfer.objects.create(
        tenant_id='test_tenant_001',
        user=user,
        transfer_type='upload',
        status='UPLOADING',
        file_name='test_file_2.txt',
        file_size=5 * 1024 * 1024,
        file_hash='md5_hash_002',
        folder_id=None,
        is_public=False,
        total_chunks=50,
        uploaded_chunks=25,
        progress=50,
        transferred_size=2.5 * 1024 * 1024,
        speed=1024 * 1024,
        created_at=now
    )
    transfers.append(t2)

    # 创建 PAUSED 状态的记录
    t3 = DocumentTransfer.objects.create(
        tenant_id='test_tenant_001',
        user=user,
        transfer_type='upload',
        status='PAUSED',
        file_name='test_file_3.txt',
        file_size=10 * 1024 * 1024,
        file_hash='md5_hash_003',
        folder_id=None,
        is_public=False,
        total_chunks=100,
        uploaded_chunks=60,
        progress=60,
        transferred_size=6 * 1024 * 1024,
        speed=0,
        created_at=now
    )
    transfers.append(t3)

    print(f"✓ 创建了 {len(transfers)} 条测试传输记录")

    # 使用测试客户端调用 API
    client = Client()
    # 模拟用户登录（简化处理，实际需要完整的登录流程）
    client.force_login(user)

    # 调用传输列表 API
    response = client.get('/api/document/transfers/')
    response_data = json.loads(response.content)

    print(f"API 响应状态码: {response.status_code}")

    if response.status_code == 200:
        transfers_data = response_data.get('data', [])
        print(f"API 返回传输记录数: {len(transfers_data)}")

        # 验证每条记录包含 file_hash 字段
        all_have_hash = True
        for idx, t in enumerate(transfers_data):
            has_hash = 'file_hash' in t
            print(f"  记录 {idx+1}: file_name={t.get('file_name')}, file_hash={t.get('file_hash')}, has_hash={has_hash}")
            if not has_hash:
                all_have_hash = False
                print(f"  ✗ 缺少 file_hash 字段!")

        if all_have_hash:
            print("✓ 所有记录都包含 file_hash 字段")
        else:
            print("✗ 部分记录缺少 file_hash 字段")
            return False

        # 验证返回的记录包含 file_hash 值
        hash_count = sum(1 for t in transfers_data if t.get('file_hash'))
        print(f"✓ 共有 {hash_count} 条记录有 file_hash 值")

    else:
        print(f"✗ API 调用失败: {response_data.get('error', '未知错误')}")
        return False

    # 清理测试数据
    DocumentTransfer.objects.filter(user=user).delete()
    print("✓ 清理测试数据完成")
    print()

    return True


def test_tenant_filter():
    """测试租户过滤"""
    print("=" * 60)
    print("测试 2: 租户过滤正确性")
    print("=" * 60)

    # 创建两个租户的用户
    user1, _ = User.objects.get_or_create(
        username='test_tenant_user_1',
        defaults={
            'email': 'user1@example.com',
            'is_supper': False,
            'tenant_id': 'tenant_a'
        }
    )

    user2, _ = User.objects.get_or_create(
        username='test_tenant_user_2',
        defaults={
            'email': 'user2@example.com',
            'is_supper': False,
            'tenant_id': 'tenant_b'
        }
    )

    now = timezone.now()

    # 创建 user1 的传输记录
    t1 = DocumentTransfer.objects.create(
        tenant_id='tenant_a',
        user=user1,
        transfer_type='upload',
        status='UPLOADING',
        file_name='user1_file.txt',
        file_size=1024 * 1024,
        file_hash='hash_a',
        folder_id=None,
        is_public=False,
        total_chunks=10,
        uploaded_chunks=5,
        progress=50,
        created_at=now
    )

    # 创建 user2 的传输记录
    t2 = DocumentTransfer.objects.create(
        tenant_id='tenant_b',
        user=user2,
        transfer_type='upload',
        status='UPLOADING',
        file_name='user2_file.txt',
        file_size=1024 * 1024,
        file_hash='hash_b',
        folder_id=None,
        is_public=False,
        total_chunks=10,
        uploaded_chunks=5,
        progress=50,
        created_at=now
    )

    print(f"✓ 创建了 2 条不同租户的传输记录")

    # 验证租户过滤
    queryset = DocumentTransfer.objects.filter(user=user1)
    queryset = apply_tenant_filter(queryset, user1)
    user1_transfers = queryset

    print(f"✓ User1 (tenant_a) 的传输记录数: {user1_transfers.count()}")
    print(f"  记录: {[t.file_name for t in user1_transfers]}")

    if user1_transfers.count() == 1 and user1_transfers.first().tenant_id == 'tenant_a':
        print("✓ 租户过滤正确")
    else:
        print("✗ 租户过滤失败")
        return False

    # 清理测试数据
    DocumentTransfer.objects.filter(user__in=[user1, user2]).delete()
    print("✓ 清理测试数据完成")
    print()

    return True


def test_time_filter():
    """测试时间过滤（30分钟内的记录）"""
    print("=" * 60)
    print("测试 3: 时间过滤（30分钟内的未完成记录）")
    print("=" * 60)

    user, _ = User.objects.get_or_create(
        username='test_time_filter_user',
        defaults={
            'email': 'timefilter@example.com',
            'is_supper': False,
            'tenant_id': 'tenant_time'
        }
    )

    now = timezone.now()

    # 创建 29 分钟前的记录（应该被恢复）
    recent_record = DocumentTransfer.objects.create(
        tenant_id='tenant_time',
        user=user,
        transfer_type='upload',
        status='UPLOADING',
        file_name='recent_file.txt',
        file_size=1024 * 1024,
        file_hash='hash_recent',
        folder_id=None,
        is_public=False,
        total_chunks=10,
        uploaded_chunks=5,
        progress=50,
        created_at=now - timezone.timedelta(minutes=29)
    )

    # 创建 31 分钟前的记录（不应被恢复）
    old_record = DocumentTransfer.objects.create(
        tenant_id='tenant_time',
        user=user,
        transfer_type='upload',
        status='UPLOADING',
        file_name='old_file.txt',
        file_size=1024 * 1024,
        file_hash='hash_old',
        folder_id=None,
        is_public=False,
        total_chunks=10,
        uploaded_chunks=5,
        progress=50,
        created_at=now - timezone.timedelta(minutes=31)
    )

    print(f"✓ 创建了 2 条不同时间的传输记录（29分钟前、31分钟前）")

    # 模拟前端过滤逻辑
    THIRTY_MINUTES = 30 * 60 * 1000
    transfers = list(DocumentTransfer.objects.filter(user=user).order_by('-created_at')[:100])

    pending_transfers = []
    for t in transfers:
        created_time = t.created_at
        is_recent = (now - created_time).total_seconds() * 1000 < THIRTY_MINUTES
        is_unfinished = ['PENDING', 'UPLOADING', 'PAUSED'].includes(t.status)

        if is_recent and is_unfinished:
            pending_transfers.append(t)

    print(f"✓ 符合恢复条件的记录数: {len(pending_transfers)}")
    print(f"  记录: {[t.file_name for t in pending_transfers]}")

    if len(pending_transfers) == 1 and pending_transfers[0].file_name == 'recent_file.txt':
        print("✓ 时间过滤正确")
    else:
        print("✗ 时间过滤失败")
        return False

    # 清理测试数据
    DocumentTransfer.objects.filter(user=user).delete()
    print("✓ 清理测试数据完成")
    print()

    return True


def main():
    """主测试函数"""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "传输列表恢复功能测试" + " " * 24 + "║")
    print("╚" + "═" * 58 + "╝")
    print()

    results = []

    # 运行测试
    results.append(("传输列表 API 返回 file_hash", test_transfer_list_api()))
    results.append(("租户过滤正确性", test_tenant_filter()))
    results.append(("时间过滤（30分钟内）", test_time_filter()))

    # 输出测试结果汇总
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status}  {name}")

    print()
    print(f"总计: {passed}/{total} 测试通过")

    if passed == total:
        print("✓ 所有测试通过!")
        return 0
    else:
        print("✗ 部分测试失败，请检查")
        return 1


if __name__ == '__main__':
    exit(main())
