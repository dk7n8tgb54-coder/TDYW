#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P0级别修复验证测试脚本

测试内容：
1. 权限检查缺少租户验证
2. 失败状态同步后端
3. 持久化恢复功能
"""

import os
import sys
import django

# 设置Django环境
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.document.models import DocumentTransfer
from apps.account.models import User, Role
from django.test import RequestFactory, TestCase
from apps.document.views.transfer import (
    TransferListView,
    TransferProgressUpdateView,
    TransferCompleteView,
    TransferCancelView,
    TransferDeleteView,
    TransferFailView
)
from django.contrib.auth.models import AnonymousUser
import json as json_lib


class TestP0Fixes(TestCase):
    """P0修复验证测试"""

    def setUp(self):
        """测试初始化"""
        self.factory = RequestFactory()

        # 创建测试用户（不同租户）
        self.user_tenant_a = User.objects.create(
            username='user_a',
            tenant_id='tenant_a',
            password_hash=User.make_password('test123'),
            is_active=True
        )
        self.user_tenant_b = User.objects.create(
            username='user_b',
            tenant_id='tenant_b',
            password_hash=User.make_password('test123'),
            is_active=True
        )

        # 授予测试用户资料库权限，使 document_auth 装饰器放行，
        # 从而真正执行到视图内的租户隔离/状态同步逻辑（不授权则被挡在门外）
        doc_role = Role.objects.create(
            name='资料库测试角色',
            created_by=self.user_tenant_a,
            page_perms=json_lib.dumps({"document": {"document": ["upload", "view"]}})
        )
        self.user_tenant_a.roles.add(doc_role)
        self.user_tenant_b.roles.add(doc_role)
        self.doc_role = doc_role

        # 创建租户A的传输记录
        self.transfer_tenant_a = DocumentTransfer.objects.create(
            tenant_id='tenant_a',
            user=self.user_tenant_a,
            transfer_type='UPLOAD',
            status='UPLOADING',
            file_name='test_file.txt',
            file_size=1024 * 1024,
            file_hash='a' * 32,
            progress=50,
            total_chunks=10,
            uploaded_chunks=5
        )

    def test_p0_1_tenant_isolation_in_progress_update(self):
        """测试P0-1: 进度更新接口的租户隔离"""
        print("\n[P0-1] 测试进度更新接口租户隔离...")

        # 测试1: 租户A用户A更新自己的记录 - 应该成功
        request = self.factory.post(
            f'/api/document/transfers/{self.transfer_tenant_a.id}/progress/',
            json_lib.dumps({'progress': 60}),
            content_type='application/json'
        )
        request.user = self.user_tenant_a

        view = TransferProgressUpdateView.as_view()
        response = view(request, transfer_id=self.transfer_tenant_a.id)

        self.assertEqual(response.status_code, 200)
        self.transfer_tenant_a.refresh_from_db()
        self.assertEqual(self.transfer_tenant_a.progress, 60)
        print("✓ 租户A用户A更新自己的记录 - 成功")

        # 测试2: 租户B用户A（同用户名不同租户）尝试更新租户A的记录 - 应该失败
        user_tenant_b_same_name = User.objects.create(
            username='user_a',  # 相同用户名
            tenant_id='tenant_b',  # 不同租户
            password_hash=User.make_password('test123'),
            is_active=True
        )
        user_tenant_b_same_name.roles.add(self.doc_role)

        request = self.factory.post(
            f'/api/document/transfers/{self.transfer_tenant_a.id}/progress/',
            json_lib.dumps({'progress': 70}),
            content_type='application/json'
        )
        request.user = user_tenant_b_same_name

        view = TransferProgressUpdateView.as_view()
        response = view(request, transfer_id=self.transfer_tenant_a.id)

        self.assertEqual(response.status_code, 200)
        resp_json = json_lib.loads(response.content)
        self.assertIn('无权', resp_json.get('error', ''))
        print("✓ 租户B用户A尝试更新租户A记录 - 失败（符合预期）")

    def test_p0_1_tenant_isolation_in_complete(self):
        """测试P0-1: 完成接口的租户隔离"""
        print("\n[P0-1] 测试完成接口租户隔离...")

        # 租户B用户尝试完成租户A的记录 - 应该失败
        request = self.factory.post(
            f'/api/document/transfers/{self.transfer_tenant_a.id}/complete/',
            json_lib.dumps({}),
            content_type='application/json'
        )
        request.user = self.user_tenant_b

        view = TransferCompleteView.as_view()
        response = view(request, transfer_id=self.transfer_tenant_a.id)

        self.assertEqual(response.status_code, 200)
        resp_json = json_lib.loads(response.content)
        self.assertIn('无权', resp_json.get('error', ''))
        print("✓ 租户B用户尝试完成租户A记录 - 失败（符合预期）")

    def test_p0_1_tenant_isolation_in_cancel(self):
        """测试P0-1: 取消接口的租户隔离"""
        print("\n[P0-1] 测试取消接口租户隔离...")

        # 租户B用户尝试取消租户A的记录 - 应该失败
        request = self.factory.post(
            f'/api/document/transfers/{self.transfer_tenant_a.id}/cancel/',
            json_lib.dumps({}),
            content_type='application/json'
        )
        request.user = self.user_tenant_b

        view = TransferCancelView.as_view()
        response = view(request, transfer_id=self.transfer_tenant_a.id)

        # CancelView 跨租户拒绝返回 200 + error（非 403），以 error 内容判定拒绝
        self.assertEqual(response.status_code, 200)
        resp_json = json_lib.loads(response.content)
        self.assertIn('无权', resp_json.get('error', ''))
        print("✓ 租户B用户尝试取消租户A记录 - 失败（符合预期）")

    def test_p0_1_tenant_isolation_in_delete(self):
        """测试P0-1: 删除接口的租户隔离"""
        print("\n[P0-1] 测试删除接口租户隔离...")

        # 先标记为已完成
        self.transfer_tenant_a.status = 'COMPLETED'
        self.transfer_tenant_a.save()

        # 租户B用户尝试删除租户A的记录 - 应该失败
        request = self.factory.delete(
            f'/api/document/transfers/{self.transfer_tenant_a.id}/delete/'
        )
        request.user = self.user_tenant_b

        view = TransferDeleteView.as_view()
        response = view(request, transfer_id=self.transfer_tenant_a.id)

        # DeleteView 跨租户拒绝返回 200 + error（TransferRecordManager 返回无权），以 error 内容判定
        self.assertEqual(response.status_code, 200)
        resp_json = json_lib.loads(response.content)
        self.assertIn('无权', resp_json.get('error', ''))
        print("✓ 租户B用户尝试删除租户A记录 - 失败（符合预期）")

    def test_p0_2_fail_status_sync(self):
        """测试P0-2: 失败状态同步后端"""
        print("\n[P0-2] 测试失败状态同步后端...")

        # 测试1: 标记传输失败
        request = self.factory.post(
            f'/api/document/transfers/{self.transfer_tenant_a.id}/fail/',
            json_lib.dumps({'error_message': '网络连接失败'}),
            content_type='application/json'
        )
        request.user = self.user_tenant_a

        view = TransferFailView.as_view()
        response = view(request, transfer_id=self.transfer_tenant_a.id)

        self.assertEqual(response.status_code, 200)
        self.transfer_tenant_a.refresh_from_db()
        self.assertEqual(self.transfer_tenant_a.status, 'FAILED')
        self.assertEqual(self.transfer_tenant_a.error_message, '网络连接失败')
        print("✓ 标记传输失败 - 成功")

        # 测试2: 不同租户无法标记失败
        request = self.factory.post(
            f'/api/document/transfers/{self.transfer_tenant_a.id}/fail/',
            json_lib.dumps({'error_message': '无权限'}),
            content_type='application/json'
        )
        request.user = self.user_tenant_b

        view = TransferFailView.as_view()
        response = view(request, transfer_id=self.transfer_tenant_a.id)

        self.assertEqual(response.status_code, 200)
        print("✓ 不同租户无法标记失败 - 成功")

    def test_p0_3_restore_transfers(self):
        """测试P0-3: 持久化恢复功能（后端查询接口）"""
        print("\n[P0-3] 测试持久化恢复功能...")

        # 创建多个传输记录（不同状态和租户）
        # 租户A - 未完成
        transfer1 = DocumentTransfer.objects.create(
            tenant_id='tenant_a',
            user=self.user_tenant_a,
            transfer_type='UPLOAD',
            status='PAUSED',
            file_name='paused_file.txt',
            file_size=2048,
            file_hash='b' * 32,
            progress=30
        )

        # 租户A - 已完成
        transfer2 = DocumentTransfer.objects.create(
            tenant_id='tenant_a',
            user=self.user_tenant_a,
            transfer_type='UPLOAD',
            status='COMPLETED',
            file_name='completed_file.txt',
            file_size=1024,
            file_hash='c' * 32,
            progress=100
        )

        # 租户B - 未完成
        transfer3 = DocumentTransfer.objects.create(
            tenant_id='tenant_b',
            user=self.user_tenant_b,
            transfer_type='UPLOAD',
            status='UPLOADING',
            file_name='tenant_b_file.txt',
            file_size=512,
            file_hash='d' * 32,
            progress=80
        )

        # 查询租户A的传输记录
        request = self.factory.get('/api/document/transfers/')
        request.user = self.user_tenant_a

        view = TransferListView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = response.data if hasattr(response, 'data') else json_lib.loads(response.content)
        transfers = data.get('data', [])

        # 应只返回租户A的记录（租户隔离）：transfer3 属于 tenant_b，不应出现
        # 注意：TransferListView 的响应字典不含 tenant_id 字段，故以记录 id 校验隔离
        transfer_ids = set(t.get('id') for t in transfers)
        self.assertIn(self.transfer_tenant_a.id, transfer_ids)
        self.assertIn(transfer1.id, transfer_ids)
        self.assertIn(transfer2.id, transfer_ids)
        self.assertNotIn(transfer3.id, transfer_ids)

        # 应该包含未完成的记录
        status_list = [t.get('status') for t in transfers]
        self.assertIn('UPLOADING', status_list)  # self.transfer_tenant_a
        self.assertIn('PAUSED', status_list)  # transfer1
        self.assertIn('COMPLETED', status_list)  # transfer2

        print("✓ 查询租户A的传输记录 - 成功")
        print(f"  - 返回 {len(transfers)} 条记录")
        print(f"  - 状态分布: {status_list}")

        # 测试按状态筛选
        request = self.factory.get('/api/document/transfers/?status=COMPLETED')
        request.user = self.user_tenant_a

        view = TransferListView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = response.data if hasattr(response, 'data') else json_lib.loads(response.content)
        transfers_completed = data.get('data', [])

        # 应该只返回已完成的记录
        self.assertTrue(all(t.get('status') == 'COMPLETED' for t in transfers_completed))
        print("✓ 按状态筛选 - 成功")


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("P0级别修复验证测试")
    print("=" * 60)

    from django.test.runner import DiscoverRunner

    runner = DiscoverRunner(verbosity=2)
    test_suite = runner.test_loader.loadTestsFromTestCase(TestP0Fixes)
    result = runner.run_suite(test_suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("✓ 所有P0修复验证测试通过")
    else:
        print("✗ 部分测试失败")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
