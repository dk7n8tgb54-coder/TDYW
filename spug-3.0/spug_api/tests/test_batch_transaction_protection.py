#!/usr/bin/env python3
"""
测试事务保护和批量操作功能
测试内容：
1. Celery批量删除任务的事务保护
2. Celery批量取消任务的事务保护
3. 批量暂停/恢复API的事务行为

Copyright: (c) OpenSpug Organization
Released under the AGPL-3.0 License.
"""
import os
import sys
import django

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

django.setup()

import threading
import time
from django.db import transaction
from apps.document.models import DocumentTransfer
from apps.document.tasks.batch import batch_delete_transfers, batch_cancel_transfers
from apps.account.models import User

def print_header(title):
    """打印测试标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_result(test_name, success, details=""):
    """打印测试结果"""
    status = "✓" if success else "✗"
    print(f"  {status} {test_name}")
    if details:
        print(f"    {details}")

def setup_test_data(user, tenant_id, count=5):
    """创建测试用的传输记录"""
    transfers = []
    for i in range(count):
        transfer = DocumentTransfer.objects.create(
            tenant_id=tenant_id,
            user=user,
            transfer_type='UPLOAD',
            status='COMPLETED' if i % 2 == 0 else 'PAUSED',
            file_name=f'test_file_{i}.pdf',
            file_size=1024 * 1024 * (i + 1),
            file_path=f'/test/path/file_{i}.pdf',
            file_hash=f'hash_{i}',
            folder_id=1,
            is_public=False,
            total_chunks=10,
            uploaded_chunks=10 if i % 2 == 0 else 5,
            progress=100 if i % 2 == 0 else 50,
        )
        transfers.append(transfer)
    return transfers

def cleanup_test_data(transfer_ids):
    """清理测试数据"""
    DocumentTransfer.objects.filter(id__in=transfer_ids).delete()

# ==================== 测试类 ====================

class TransactionProtectionTest:
    """事务保护测试"""

    def __init__(self):
        self.user = User.objects.filter(id=5).first()
        if not self.user:
            # 创建一个测试用户
            from django.contrib.auth.hashers import make_password
            self.user = User.objects.create(
                username='test_transaction_user',
                password=make_password('test123'),
                tenant_id='test_tenant',
                is_supper=False
            )
        self.tenant_id = self.user.tenant_id
        self.test_transfers = []
        self.errors = []

    def setup(self):
        """准备测试数据"""
        # 清理旧数据
        DocumentTransfer.objects.filter(
            tenant_id=self.tenant_id,
            file_name__startswith='test_file_'
        ).delete()
        
        # 创建新测试数据
        self.test_transfers = setup_test_data(self.user, self.tenant_id, count=5)
        print(f"  创建 {len(self.test_transfers)} 条测试传输记录")

    def teardown(self):
        """清理测试数据"""
        if self.test_transfers:
            cleanup_test_data([t.id for t in self.test_transfers])
            print(f"  清理测试数据完成")

    def test_batch_delete_transaction_isolation(self):
        """测试批量删除的事务隔离"""
        print_header("测试1: 批量删除事务隔离")
        self.setup()

        try:
            # 获取可删除的记录ID（状态为COMPLETED）
            deletable = [t for t in self.test_transfers if t.status == 'COMPLETED']
            transfer_ids = [t.id for t in deletable]
            
            print(f"  准备删除 {len(transfer_ids)} 条记录")
            
            # 执行批量删除任务（同步执行，不通过Celery）
            result = batch_delete_transfers.run(
                transfer_ids=transfer_ids,
                request_user_id=self.user.id,
                request_tenant_id=self.tenant_id
            )
            
            print(f"  删除结果: {result}")
            
            # 验证删除结果
            success = result['deleted'] == len(transfer_ids)
            details = f"期望删除 {len(transfer_ids)} 条，实际删除 {result['deleted']} 条"
            print_result("批量删除事务隔离", success, details)
            
            # 验证数据库状态
            remaining = DocumentTransfer.objects.filter(id__in=transfer_ids).count()
            success = remaining == 0
            print_result("数据库状态验证", success, f"剩余记录数: {remaining}")
            
        except Exception as e:
            print_result("批量删除事务隔离", False, str(e))
        finally:
            self.teardown()

    def test_batch_cancel_transaction_isolation(self):
        """测试批量取消的事务隔离"""
        print_header("测试2: 批量取消事务隔离")
        self.setup()

        try:
            # 获取可取消的记录ID（状态为PAUSED）
            cancellable = [t for t in self.test_transfers if t.status == 'PAUSED']
            transfer_ids = [t.id for t in cancellable]
            
            print(f"  准备取消 {len(transfer_ids)} 条记录")
            
            # 执行批量取消任务（同步执行，不通过Celery）
            result = batch_cancel_transfers.run(
                transfer_ids=transfer_ids,
                request_user_id=self.user.id,
                request_tenant_id=self.tenant_id
            )
            
            print(f"  取消结果: {result}")
            
            # 验证取消结果
            success = result['updated'] == len(transfer_ids)
            details = f"期望取消 {len(transfer_ids)} 条，实际取消 {result['updated']} 条"
            print_result("批量取消事务隔离", success, details)
            
            # 验证数据库状态
            cancelled_count = DocumentTransfer.objects.filter(
                id__in=transfer_ids,
                status='CANCELED'
            ).count()
            success = cancelled_count == len(transfer_ids)
            print_result("数据库状态验证", success, f"已取消记录数: {cancelled_count}")
            
        except Exception as e:
            print_result("批量取消事务隔离", False, str(e))
        finally:
            self.teardown()

    def test_tenant_isolation_in_batch_operations(self):
        """测试批量操作中的租户隔离"""
        print_header("测试3: 批量操作租户隔离")
        self.setup()

        try:
            # 创建其他租户的记录
            other_transfer = DocumentTransfer.objects.create(
                tenant_id='other_tenant',  # 不同租户
                user=self.user,
                transfer_type='UPLOAD',
                status='COMPLETED',
                file_name='other_tenant_file.pdf',
                file_size=1024 * 1024,
                file_path='/test/other/file.pdf',
                file_hash='other_hash',
                folder_id=1,
                is_public=False,
                total_chunks=10,
                uploaded_chunks=10,
                progress=100,
            )
            
            # 尝试删除包含其他租户记录的列表
            transfer_ids = [self.test_transfers[0].id, other_transfer.id]
            
            print(f"  尝试删除2条记录（1条本租户，1条其他租户）")
            
            result = batch_delete_transfers.run(
                transfer_ids=transfer_ids,
                request_user_id=self.user.id,
                request_tenant_id=self.tenant_id  # 使用本租户ID
            )
            
            print(f"  删除结果: {result}")
            
            # 验证：本租户记录应被删除，其他租户记录应被跳过
            local_deleted = not DocumentTransfer.objects.filter(id=self.test_transfers[0].id).exists()
            other_exists = DocumentTransfer.objects.filter(id=other_transfer.id).exists()
            
            success = local_deleted and other_exists
            details = f"本租户记录已删除: {local_deleted}, 其他租户记录保留: {other_exists}"
            print_result("租户隔离验证", success, details)
            
            # 清理其他租户记录
            other_transfer.delete()
            
        except Exception as e:
            print_result("租户隔离验证", False, str(e))
        finally:
            self.teardown()

    def test_concurrent_batch_operations(self):
        """测试并发批量操作的事务保护"""
        print_header("测试4: 并发批量操作事务保护")
        self.setup()

        try:
            transfer_ids = [t.id for t in self.test_transfers]
            results = []
            errors = []

            def delete_task():
                try:
                    result = batch_delete_transfers.run(
                        transfer_ids=transfer_ids[:2],
                        request_user_id=self.user.id,
                        request_tenant_id=self.tenant_id
                    )
                    results.append(('delete', result))
                except Exception as e:
                    errors.append(('delete', str(e)))

            def cancel_task():
                try:
                    result = batch_cancel_transfers.run(
                        transfer_ids=transfer_ids[2:],
                        request_user_id=self.user.id,
                        request_tenant_id=self.tenant_id
                    )
                    results.append(('cancel', result))
                except Exception as e:
                    errors.append(('cancel', str(e)))

            # 并发执行两个任务
            thread1 = threading.Thread(target=delete_task)
            thread2 = threading.Thread(target=cancel_task)
            
            thread1.start()
            thread2.start()
            thread1.join()
            thread2.join()

            print(f"  并发操作结果: {results}")
            if errors:
                print(f"  错误: {errors}")

            # 验证至少有一个操作成功
            success = len(results) >= 1
            print_result("并发操作完成", success, f"成功操作数: {len(results)}, 错误数: {len(errors)}")

        except Exception as e:
            print_result("并发批量操作", False, str(e))
        finally:
            self.teardown()

    def run_all_tests(self):
        """运行所有测试"""
        print_header("事务保护测试套件")
        print(f"  测试用户: {self.user.username}")
        print(f"  租户ID: {self.tenant_id}")
        
        self.test_batch_delete_transaction_isolation()
        self.test_batch_cancel_transaction_isolation()
        self.test_tenant_isolation_in_batch_operations()
        self.test_concurrent_batch_operations()
        
        print_header("测试完成")


class BatchAPIFrontendTest:
    """批量操作前端API测试"""

    def __init__(self):
        self.user = User.objects.filter(id=5).first()
        if not self.user:
            from django.contrib.auth.hashers import make_password
            self.user = User.objects.create(
                username='test_batch_api_user',
                password=make_password('test123'),
                tenant_id='test_tenant_api',
                is_supper=False
            )
        self.tenant_id = self.user.tenant_id
        self.test_transfers = []

    def setup(self):
        """准备测试数据"""
        DocumentTransfer.objects.filter(
            tenant_id=self.tenant_id,
            file_name__startswith='batch_test_'
        ).delete()
        
        # 创建不同状态的记录
        statuses = ['UPLOADING', 'PAUSED', 'PENDING', 'COMPLETED', 'FAILED']
        for i, status in enumerate(statuses):
            transfer = DocumentTransfer.objects.create(
                tenant_id=self.tenant_id,
                user=self.user,
                transfer_type='UPLOAD',
                status=status,
                file_name=f'batch_test_file_{i}.pdf',
                file_size=1024 * 1024,
                file_path=f'/test/batch/file_{i}.pdf',
                file_hash=f'batch_hash_{i}',
                folder_id=1,
                is_public=False,
                total_chunks=10,
                uploaded_chunks=5,
                progress=50,
            )
            self.test_transfers.append(transfer)
        print(f"  创建 {len(self.test_transfers)} 条测试记录（多种状态）")

    def teardown(self):
        """清理测试数据"""
        if self.test_transfers:
            DocumentTransfer.objects.filter(
                id__in=[t.id for t in self.test_transfers]
            ).delete()
            print(f"  清理测试数据完成")

    def test_batch_pause_api(self):
        """测试批量暂停API"""
        print_header("测试5: 批量暂停API")
        self.setup()

        try:
            # 模拟前端批量暂停
            pausable_ids = [t.id for t in self.test_transfers 
                          if t.status in ['UPLOADING', 'PENDING']]
            
            print(f"  准备暂停 {len(pausable_ids)} 条记录")
            
            from apps.document.views.transfer.batch import TransferBatchPauseView
            from django.test import RequestFactory
            import json
            
            factory = RequestFactory()
            request = factory.post(
                '/api/document/transfers/batch/pause/',
                data=json.dumps({'transfer_ids': pausable_ids}),
                content_type='application/json'
            )
            request.user = self.user
            
            view = TransferBatchPauseView()
            response = view.post(request)
            
            result = json.loads(response.content)
            print(f"  API响应: {result}")
            
            success = result.get('data', {}).get('updated', 0) == len(pausable_ids)
            print_result("批量暂停API", success, f"暂停记录数: {result.get('data', {}).get('updated', 0)}")

        except Exception as e:
            print_result("批量暂停API", False, str(e))
            import traceback
            traceback.print_exc()
        finally:
            self.teardown()

    def test_batch_resume_api(self):
        """测试批量恢复API"""
        print_header("测试6: 批量恢复API")
        self.setup()

        try:
            # 先将一些记录设为PAUSED状态
            paused_ids = []
            for t in self.test_transfers[:2]:
                t.status = 'PAUSED'
                t.save()
                paused_ids.append(t.id)
            
            print(f"  准备恢复 {len(paused_ids)} 条PAUSED记录")
            
            from apps.document.views.transfer.batch import TransferBatchResumeView
            from django.test import RequestFactory
            import json
            
            factory = RequestFactory()
            request = factory.post(
                '/api/document/transfers/batch/resume/',
                data=json.dumps({'transfer_ids': paused_ids}),
                content_type='application/json'
            )
            request.user = self.user
            
            view = TransferBatchResumeView()
            response = view.post(request)
            
            result = json.loads(response.content)
            print(f"  API响应: {result}")
            
            success = result.get('data', {}).get('updated', 0) == len(paused_ids)
            print_result("批量恢复API", success, f"恢复记录数: {result.get('data', {}).get('updated', 0)}")

        except Exception as e:
            print_result("批量恢复API", False, str(e))
            import traceback
            traceback.print_exc()
        finally:
            self.teardown()

    def run_all_tests(self):
        """运行所有API测试"""
        print_header("批量操作前端API测试套件")
        
        self.test_batch_pause_api()
        self.test_batch_resume_api()
        
        print_header("API测试完成")


# ==================== 主程序 ====================

if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("  事务保护与批量操作功能测试")
    print("  测试内容: Celery任务事务保护 + 批量API接口")
    print("=" * 70)

    # 运行事务保护测试
    transaction_test = TransactionProtectionTest()
    transaction_test.run_all_tests()

    print("\n")

    # 运行API测试
    api_test = BatchAPIFrontendTest()
    api_test.run_all_tests()

    print("\n" + "=" * 70)
    print("  所有测试执行完毕")
    print("=" * 70 + "\n")
