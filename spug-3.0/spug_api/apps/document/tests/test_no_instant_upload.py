#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""移除秒传/跨 transfer 哈希复用 - 后端验证测试

验证：
1. 同一 transfer 重复 merge 请求保持幂等
2. 不存在的 transfer_id 不命中
3. transfer A 已 COMPLETED，transfer B 与其 hash/文件名/目录相同：B 不得复用 A.file_path
4. 两个相同哈希但不同文件名的任务互不复用
5a-d. 相同哈希但不同目录/用户/租户/system_folder 的任务互不影响
6. check_uploaded_chunks 只读取当前 transfer_id 的分片目录
7. 新 transfer 没有分片时返回从头上传
8. direct_merge 对同一 transfer 的完整分片仍可工作
9. 抽样哈希不能触发跨 transfer COMPLETED 复用
10. 两个同哈希 transfer 各自完成合并后 file_path 独立
11. check_idempotency 函数签名不含 file_hash 参数
12. transfer_completion.py 不含 sibling 查找
13. merge.py 不含 _lookup_by_file_hash 函数
14. IDOR 防护 - 用户不能查到其他用户的 transfer
15. COMPLETED transfer 无对应文件记录时返回 None（安全降级）

运行方式：
  docker exec -e PYTHONIOENCODING=utf-8 -e PYTHONPATH=/data/spug/spug_api \
    -w /data/spug/spug_api tdyw-test python manage.py test \
    apps.document.tests.test_no_instant_upload --noinput -v2
"""
import os, sys, inspect, uuid

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django; django.setup()

from django.test import TestCase
from apps.account.models import User
from apps.document.models import DocumentTransfer, DocumentFilePrivate
from apps.document.constants import TransferStatus
from apps.document.views.upload.merge import check_idempotency


def make_user(username='testuser', tenant_id='test_tenant'):
    return User.objects.create(
        username=username, nickname=username,
        password_hash=User.make_password('test123!'),
        access_token=uuid.uuid4().hex,
        tenant_id=tenant_id, type='default',
        last_ip='127.0.0.1',
    )


def make_transfer(user, **kw):
    d = dict(
        tenant_id='test_tenant', user=user, transfer_type='UPLOAD',
        status=TransferStatus.PENDING.value, file_name='test.pdf', file_size=1024,
        file_path='/data/documents/test.pdf', file_hash='', folder_id=None,
        is_public=False, system_folder='', total_chunks=5, uploaded_chunks=0,
    )
    d.update(kw)
    return DocumentTransfer.objects.create(**d)


class TestNoInstantUpload(TestCase):
    """验证秒传/跨 transfer 哈希复用已移除，断点续传保留"""

    def setUp(self):
        self.user_a = make_user('user_a', 't_a')
        self.user_b = make_user('user_b', 't_b')

    # ============================================================
    # 测试 1: 同一 transfer 重复 merge 请求保持幂等
    # ============================================================
    def test_01_same_transfer_idempotent(self):
        """同一 transfer_id 两次 check_idempotency 应返回相同结果"""
        transfer = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.MERGING.value,
            file_hash='hash_001', celery_task_id='celery_001',
        )
        r1, err1 = check_idempotency(transfer_id=transfer.id, user=self.user_a)
        r2, err2 = check_idempotency(transfer_id=transfer.id, user=self.user_a)

        self.assertIsNotNone(r1, '第一次查询应命中')
        self.assertIsNotNone(r2, '第二次查询应命中')
        self.assertEqual(r1.get('status'), r2.get('status'), '两次结果应一致')
        self.assertEqual(r1.get('status'), 'merging', '状态应为 merging')

    # ============================================================
    # 测试 2: 不存在的 transfer_id 不命中
    # ============================================================
    def test_02_nonexistent_transfer_no_hit(self):
        """不存在的 transfer_id 应返回 (None, None)"""
        r, err = check_idempotency(transfer_id=999999, user=self.user_a)
        self.assertIsNone(r, '不存在的 transfer_id 应返回 None')
        self.assertIsNone(err, '不应有错误')

    # ============================================================
    # 测试 3: transfer A 已 COMPLETED，transfer B 与其完全相同，B 不得复用 A.file_path
    # ============================================================
    def test_03_completed_a_no_reuse_for_b(self):
        """A 已 COMPLETED，B 同 hash/文件名/目录，check_idempotency(B) 不应命中 A"""
        transfer_a = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.COMPLETED.value,
            file_hash='same_hash', file_name='report.pdf',
            folder_id=100, file_path='/data/documents/report.pdf',
            celery_task_id='celery_a',
        )
        transfer_b = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.PENDING.value,
            file_hash='same_hash', file_name='report.pdf',
            folder_id=100, file_path='/data/documents/report_b.pdf',
        )
        r, err = check_idempotency(transfer_id=transfer_b.id, user=self.user_a)
        self.assertIsNone(r, 'B 的 check_idempotency 不应命中 A 的记录')

    # ============================================================
    # 测试 4: 相同哈希但不同文件名的任务互不复用
    # ============================================================
    def test_04_same_hash_diff_name_no_reuse(self):
        """A 和 B 同 hash 但不同文件名，B 不应命中 A"""
        transfer_a = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.COMPLETED.value,
            file_hash='shared_hash', file_name='file_a.pdf',
            folder_id=100, file_path='/data/documents/file_a.pdf',
        )
        transfer_b = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.PENDING.value,
            file_hash='shared_hash', file_name='file_b.pdf',
            folder_id=100, file_path='/data/documents/file_b.pdf',
        )
        r, err = check_idempotency(transfer_id=transfer_b.id, user=self.user_a)
        self.assertIsNone(r, '不同文件名的同 hash transfer 不应命中')

    # ============================================================
    # 测试 5a: 相同哈希但不同目录互不影响
    # ============================================================
    def test_05a_same_hash_diff_folder_no_reuse(self):
        """A 和 B 同 hash 同文件名但不同 folder_id，B 不应命中 A"""
        transfer_a = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.COMPLETED.value,
            file_hash='dir_hash', file_name='doc.pdf',
            folder_id=100, file_path='/data/documents/dir1/doc.pdf',
        )
        transfer_b = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.PENDING.value,
            file_hash='dir_hash', file_name='doc.pdf',
            folder_id=200, file_path='/data/documents/dir2/doc.pdf',
        )
        r, err = check_idempotency(transfer_id=transfer_b.id, user=self.user_a)
        self.assertIsNone(r, '不同目录的同 hash transfer 不应命中')

    # ============================================================
    # 测试 5b: 相同哈希但不同用户互不影响
    # ============================================================
    def test_05b_same_hash_diff_user_no_reuse(self):
        """A 和 B 同 hash 同文件名但不同用户，B 不应命中 A"""
        transfer_a = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.COMPLETED.value,
            file_hash='user_hash', file_name='doc.pdf',
            folder_id=100, file_path='/data/documents/user_a/doc.pdf',
        )
        transfer_b = make_transfer(
            self.user_b, tenant_id='t_b',
            status=TransferStatus.PENDING.value,
            file_hash='user_hash', file_name='doc.pdf',
            folder_id=100, file_path='/data/documents/user_b/doc.pdf',
        )
        r, err = check_idempotency(transfer_id=transfer_b.id, user=self.user_b)
        self.assertIsNone(r, '不同用户的同 hash transfer 不应命中')

    # ============================================================
    # 测试 5c: 相同哈希但不同租户互不影响
    # ============================================================
    def test_05c_same_hash_diff_tenant_no_reuse(self):
        """A 和 B 同 hash 但不同租户，B 不应命中 A"""
        transfer_a = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.COMPLETED.value,
            file_hash='tenant_hash', file_name='doc.pdf',
            folder_id=100, file_path='/data/documents/t_a/doc.pdf',
        )
        transfer_b = make_transfer(
            self.user_b, tenant_id='t_b',
            status=TransferStatus.PENDING.value,
            file_hash='tenant_hash', file_name='doc.pdf',
            folder_id=100, file_path='/data/documents/t_b/doc.pdf',
        )
        r, err = check_idempotency(transfer_id=transfer_b.id, user=self.user_b)
        self.assertIsNone(r, '不同租户的同 hash transfer 不应命中')

    # ============================================================
    # 测试 5d: 相同哈希但不同 system_folder 互不影响
    # ============================================================
    def test_05d_same_hash_diff_system_folder_no_reuse(self):
        """A 和 B 同 hash 但不同 system_folder，B 不应命中 A"""
        transfer_a = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.COMPLETED.value,
            file_hash='sys_hash', file_name='doc.pdf',
            folder_id=None, system_folder='party_building_documents',
            file_path='/data/documents/pb/doc.pdf',
        )
        transfer_b = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.PENDING.value,
            file_hash='sys_hash', file_name='doc.pdf',
            folder_id=None, system_folder='',
            file_path='/data/documents/normal/doc.pdf',
        )
        r, err = check_idempotency(transfer_id=transfer_b.id, user=self.user_a)
        self.assertIsNone(r, '不同 system_folder 的同 hash transfer 不应命中')

    # ============================================================
    # 测试 6: check_uploaded_chunks 只读取当前 transfer_id 的分片目录
    # ============================================================
    def test_06_resume_reads_only_own_chunks(self):
        """resume.py _get_chunk_dir 使用 transfer_id 定位分片目录，不跨 transfer"""
        from apps.document.views.upload.resume import CheckUploadedChunksView
        from apps.document.libs.document_utils import get_chunk_dir_path

        # 验证 get_chunk_dir_path 包含 transfer_id 参数
        sig = inspect.signature(get_chunk_dir_path)
        params = set(sig.parameters.keys())
        self.assertIn('transfer_id', params, 'get_chunk_dir_path 应接受 transfer_id 参数')

        # 验证 _get_chunk_dir 方法中先校验归属再使用 transfer_id
        src = inspect.getsource(CheckUploadedChunksView._get_chunk_dir)
        self.assertIn('TransferOwnershipValidator', src,
                      '_get_chunk_dir 应包含归属校验')
        self.assertIn('transfer_id', src,
                      '_get_chunk_dir 应使用 transfer_id')

    # ============================================================
    # 测试 7: 新 transfer 没有分片时返回从头上传
    # ============================================================
    def test_07_new_transfer_no_chunks(self):
        """新 transfer_id 的分片目录不存在时，_get_chunk_dir 返回 None"""
        from apps.document.views.upload.resume import CheckUploadedChunksView
        src = inspect.getsource(CheckUploadedChunksView._get_chunk_dir)
        self.assertIn('return None', src,
                      '_get_chunk_dir 应在目录不存在时返回 None')
        self.assertIn('os.path.exists', src,
                      '_get_chunk_dir 应检查目录是否存在')

    # ============================================================
    # 测试 8: direct_merge 对同一 transfer 的完整分片仍可工作
    # ============================================================
    def test_08_direct_merge_same_transfer(self):
        """direct_merge.py 的 _check_idempotent 只检查当前 transfer 状态"""
        from apps.document.views.upload.direct_merge import DirectMergeView
        src = inspect.getsource(DirectMergeView._check_idempotent)
        self.assertNotIn('_lookup_by_file_hash', src,
                         '_check_idempotent 不应调用 _lookup_by_file_hash')

    # ============================================================
    # 测试 9: 抽样哈希（sv1_...）不能触发跨 transfer COMPLETED 复用
    # ============================================================
    def test_09_sample_hash_no_cross_reuse(self):
        """抽样哈希 file_hash='sv1_abc123' 不应触发跨 transfer 复用"""
        transfer_a = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.COMPLETED.value,
            file_hash='sv1_abc123', file_name='sample.pdf',
            folder_id=100, file_path='/data/documents/sample.pdf',
        )
        transfer_b = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.PENDING.value,
            file_hash='sv1_abc123', file_name='sample.pdf',
            folder_id=100, file_path='/data/documents/sample_b.pdf',
        )
        r, err = check_idempotency(transfer_id=transfer_b.id, user=self.user_a)
        self.assertIsNone(r, '抽样哈希不应触发跨 transfer 复用')

    # ============================================================
    # 测试 10: 两个同哈希 transfer 各自完成合并后 file_path 独立
    #
    # 通过 generate_file_names 模拟真实文件创建流程：
    # 两个同 hash、同名的文件各自调用 generate_file_names，
    # 验证第二次调用生成带后缀的独立名称，file_path 不同。
    # ============================================================
    def test_10_independent_file_paths_via_naming(self):
        """两个同哈希同名的文件通过 generate_file_names 生成独立路径"""
        from apps.document.models import DocumentFilePrivate, DocumentFolderPrivate
        from apps.document.libs.naming_utils import generate_file_names

        # 创建测试文件夹
        folder = DocumentFolderPrivate.objects.create(
            tenant_id='t_a', created_by=self.user_a,
            name='test_folder_10', parent=None,
        )

        try:
            # 第一个文件 - 正常创建
            names_1 = generate_file_names(
                DocumentFilePrivate, 'report.pdf', folder, self.user_a
            )
            f1 = DocumentFilePrivate.objects.create(
                tenant_id='t_a', created_by=self.user_a,
                name=names_1['logical_name'],
                display_name=names_1['display_name'],
                physical_name=names_1['physical_name'],
                file_path=f"/data/documents/{names_1['physical_name']}",
                file_size=1024, file_type='application/pdf', folder=folder,
            )

            # 第二个文件 - 同名同目录，应生成带后缀的独立名称
            names_2 = generate_file_names(
                DocumentFilePrivate, 'report.pdf', folder, self.user_a
            )
            f2 = DocumentFilePrivate.objects.create(
                tenant_id='t_a', created_by=self.user_a,
                name=names_2['logical_name'],
                display_name=names_2['display_name'],
                physical_name=names_2['physical_name'],
                file_path=f"/data/documents/{names_2['physical_name']}",
                file_size=1024, file_type='application/pdf', folder=folder,
            )

            # 断言：两个文件有独立的物理名称和路径
            self.assertNotEqual(f1.physical_name, f2.physical_name,
                                '两个文件的 physical_name 必须不同')
            self.assertNotEqual(f1.file_path, f2.file_path,
                                '两个文件的 file_path 必须不同')
            # 第二个文件的 logical_name 应有后缀（如 report_001.pdf）
            self.assertNotEqual(f1.name, f2.name,
                                '两个文件的 name 必须不同')
            self.assertIn('_', f2.name,
                          '第二个文件的 name 应有后缀分隔符')

            # 验证数据库中不存在两条记录共享同一 file_path
            paths = list(DocumentFilePrivate.objects.filter(
                tenant_id='t_a', folder=folder
            ).values_list('file_path', flat=True))
            self.assertEqual(len(paths), len(set(paths)),
                             '数据库中不应有两条记录共享同一 file_path')
        finally:
            # 清理
            DocumentFilePrivate.objects.filter(folder=folder).delete()
            DocumentFolderPrivate.objects.filter(id=folder.id).delete()

    # ============================================================
    # 测试 11: check_idempotency 函数签名不含 file_hash 参数
    # ============================================================
    def test_11_check_idempotency_signature(self):
        """check_idempotency 不接受 file_hash/is_public/folder_id/system_folder/file_name 参数"""
        sig = inspect.signature(check_idempotency)
        params = set(sig.parameters.keys())
        forbidden = {'file_hash', 'is_public', 'folder_id', 'system_folder', 'file_name'}
        has_forbidden = params & forbidden
        self.assertFalse(has_forbidden,
                         f'check_idempotency 不应接受参数: {has_forbidden}')
        self.assertIn('transfer_id', params,
                      'check_idempotency 应接受 transfer_id 参数')

    # ============================================================
    # 测试 12: transfer_completion.py 不含 sibling 查找
    # ============================================================
    def test_12_no_sibling_lookup(self):
        """TransferCompletionService.complete 不含跨 transfer sibling 查找"""
        from apps.document.services.transfer_completion import TransferCompletionService
        src = inspect.getsource(TransferCompletionService.complete)
        self.assertNotIn('sibling', src.lower(),
                         'complete 方法不应包含 sibling 查找')
        # 不应包含跨 transfer 的 DocumentTransfer.objects.filter 查询
        self.assertFalse(
            'DocumentTransfer.objects.filter' in src and 'file_hash' in src,
            'complete 方法不应通过 file_hash 查询其他 transfer'
        )

    # ============================================================
    # 测试 13: merge.py 不含 _lookup_by_file_hash 函数
    # ============================================================
    def test_13_no_lookup_by_file_hash(self):
        """merge.py 模块不含 _lookup_by_file_hash 函数"""
        from apps.document.views.upload import merge as merge_module
        self.assertFalse(hasattr(merge_module, '_lookup_by_file_hash'),
                         'merge 模块不应包含 _lookup_by_file_hash 函数')

    # ============================================================
    # 测试 14: IDOR 防护 - 用户不能查到其他用户的 transfer
    # ============================================================
    def test_14_idor_protection(self):
        """用户 B 查用户 A 的 transfer 应返回 None"""
        transfer_a = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.MERGING.value,
            file_hash='idor_hash', celery_task_id='celery_idor',
        )
        # 用户 B 尝试查用户 A 的 transfer
        r, err = check_idempotency(transfer_id=transfer_a.id, user=self.user_b)
        self.assertIsNone(r, '用户 B 不应能查到用户 A 的 transfer')

    # ============================================================
    # 测试 15: COMPLETED transfer 无对应文件记录时返回 None（安全降级）
    # ============================================================
    def test_15_completed_transfer_no_file_record(self):
        """COMPLETED transfer 但无对应文件记录时，check_idempotency 返回 None

        这是 2026-08-05 修复的安全检查：不信任 COMPLETED 状态，必须验证文件记录存在。
        """
        transfer = make_transfer(
            self.user_a, tenant_id='t_a',
            status=TransferStatus.COMPLETED.value,
            file_hash='comp_hash', file_path='/data/documents/comp.pdf',
            celery_task_id='celery_comp',
        )
        r, err = check_idempotency(transfer_id=transfer.id, user=self.user_a)
        # 因为没有对应的文件记录，应返回 None（安全降级）
        self.assertIsNone(r, 'COMPLETED 无文件记录应返回 None（安全降级）')


if __name__ == '__main__':
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestNoInstantUpload)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
