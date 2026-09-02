"""分片上传、合并与传输状态机发布门禁测试（stable_contract）。

覆盖：小文件直传、分片上传、断点续传检查、缺失/重复/乱序分片、合并幂等、
      状态转换矩阵、终态不可变、重试、取消、传输记录归属、文件名与大小校验。
"""
import os
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.document.constants import (
    ALLOWED_STATUS_TRANSITIONS, DEFAULT_MAX_FILE_SIZE, TransferStatus,
    is_valid_status_transition)
from apps.document.libs.document_utils import get_chunk_storage_base_path
from apps.document.models import DocumentFilePublic, DocumentTransfer
from tests.helpers.test_base import (
    get_response_data, has_error, make_client, make_user, post_json, setup_test_env)

from .helpers import (
    PERM_UPLOAD, PERM_VIEW, StorageCleanupMixin, make_folder, make_transfer, unique)

CHUNK_URL = '/document/upload_chunk/'
RESUME_URL = '/document/check_uploaded_chunks/'
DIRECT_MERGE_URL = '/document/direct_merge/'
MERGE_URL = '/document/merge_chunks/'
MERGE_STATUS_URL = '/document/merge_status/'
TRANSFER_CREATE_URL = '/document/transfers/create/'


class UploadMergeStateMachineTest(StorageCleanupMixin, TestCase):
    """分片上传 / 合并 / 传输状态机"""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('gate_upload', perms=[PERM_VIEW, PERM_UPLOAD])
        cls.other = make_user('gate_upload_other', perms=[PERM_VIEW, PERM_UPLOAD])
        cls.admin = make_user('gate_upload_admin', is_supper=True)

    def setUp(self):
        super().setUp()
        setup_test_env()
        self.client = make_client(self.user)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        self.other_client = make_client(self.other)
        self.other_client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        self.folder = make_folder(name=unique('上传目录'), created_by=self.user)
        # 文件哈希必须是 32 位 MD5 或 sv1_ 前缀的抽样哈希
        self.file_hash = uuid.uuid4().hex
        self.chunk_dir = os.path.join(
            get_chunk_storage_base_path(), 'public', self.file_hash)
        self.track_path(self.chunk_dir)

    # ---------- helpers ----------

    def _create_transfer(self, total_chunks=3, file_size=300, file_name=None,
                         client=None, status='PENDING', folder_id=None):
        payload = {
            'transfer_type': 'UPLOAD',
            'file_name': file_name or (unique('chunked') + '.bin'),
            'file_size': file_size,
            'file_hash': self.file_hash,
            'total_chunks': total_chunks,
            'is_public': True,
            'folder_id': self.folder.id if folder_id is None else folder_id,
        }
        resp = post_json(client or self.client, TRANSFER_CREATE_URL, payload)
        self.assertFalse(has_error(resp), resp.json())
        transfer_id = get_response_data(resp)['id']
        if status != 'PENDING':
            DocumentTransfer.objects.filter(id=transfer_id).update(status=status)
        return transfer_id

    def _upload_chunk(self, index, content=b'0123456789', total_chunks=3,
                      transfer_id=None, file_name=None, file_size=None,
                      client=None, **extra):
        data = {
            'file_name': file_name or 'chunked.bin',
            'file_size': file_size if file_size is not None else 300,
            'chunk_index': index,
            'total_chunks': total_chunks,
            'file_hash': self.file_hash,
            'is_public': 'true',
            'folder_id': self.folder.id,
        }
        if transfer_id is not None:
            data['transfer_id'] = transfer_id
        data.update(extra)
        data['file'] = SimpleUploadedFile('blob', content,
                                          content_type='application/octet-stream')
        return (client or self.client).post(CHUNK_URL, data=data)

    # ---------- 1. 传输记录创建与状态机矩阵 ----------

    def test_01_create_transfer(self):
        """创建传输记录返回 id 且初始状态 PENDING"""
        tid = self._create_transfer()
        t = DocumentTransfer.objects.get(id=tid)
        self.assertEqual(t.status, 'PENDING')
        self.assertEqual(t.user_id, self.user.id)
        self.assertEqual(t.total_chunks, 3)

    def test_02_state_transition_matrix_matches_spec(self):
        """状态转换矩阵与 AGENTS.md 规范完全一致"""
        from apps.document.constants import TransferStatus as S
        expected = {
            S.PENDING: {S.UPLOADING, S.DOWNLOADING, S.COPYING, S.PAUSED,
                        S.CANCELED, S.COMPLETED, S.FAILED},
            S.UPLOADING: {S.PAUSED, S.MERGING, S.COMPLETED, S.FAILED, S.CANCELED},
            S.DOWNLOADING: {S.PAUSED, S.COMPLETED, S.FAILED, S.CANCELED},
            S.PAUSED: {S.UPLOADING, S.DOWNLOADING, S.COPYING, S.FAILED, S.CANCELED},
            S.MERGING: {S.COMPLETED, S.FAILED, S.CANCELED},
            S.COPYING: {S.PAUSED, S.COMPLETED, S.FAILED, S.CANCELED},
            S.FAILED: {S.UPLOADING, S.DOWNLOADING, S.COPYING, S.CANCELED},
            S.COMPLETED: set(),
            S.CANCELED: set(),
        }
        self.assertEqual(set(ALLOWED_STATUS_TRANSITIONS.keys()), set(expected.keys()))
        for src, targets in expected.items():
            self.assertEqual(set(ALLOWED_STATUS_TRANSITIONS[src]), targets,
                             f'{src} 允许目标集合不匹配')

    def test_03_terminal_states_are_terminal(self):
        """COMPLETED / CANCELED 为终态，任何出边都被拒绝"""
        for terminal in (TransferStatus.COMPLETED, TransferStatus.CANCELED):
            for target in TransferStatus:
                self.assertFalse(
                    is_valid_status_transition(terminal, target),
                    f'{terminal.value} -> {target.value} 不应被允许')

    def test_04_retry_from_failed_allowed(self):
        """FAILED 允许重试回到 UPLOADING / DOWNLOADING / COPYING"""
        for target in (TransferStatus.UPLOADING, TransferStatus.DOWNLOADING,
                       TransferStatus.COPYING, TransferStatus.CANCELED):
            self.assertTrue(is_valid_status_transition(TransferStatus.FAILED, target))
        self.assertFalse(
            is_valid_status_transition(TransferStatus.FAILED, TransferStatus.COMPLETED),
            'FAILED 不能直接跳到 COMPLETED')

    def test_05_uploading_to_completed_allowed(self):
        """UPLOADING -> COMPLETED 必须允许（普通上传无分片合并）"""
        self.assertTrue(
            is_valid_status_transition(TransferStatus.UPLOADING, TransferStatus.COMPLETED))

    # ---------- 2. 状态更新接口 ----------

    def test_06_status_update_valid_transition(self):
        """合法状态转换通过接口生效"""
        tid = self._create_transfer()
        resp = post_json(self.client, f'/document/transfers/{tid}/status/',
                         {'status': 'UPLOADING'})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=tid).status, 'UPLOADING')

    def test_07_status_update_invalid_transition_rejected(self):
        """非法状态转换被拒（COMPLETED -> UPLOADING）"""
        tid = self._create_transfer(status='COMPLETED')
        resp = post_json(self.client, f'/document/transfers/{tid}/status/',
                         {'status': 'UPLOADING'})
        self.assertTrue(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=tid).status, 'COMPLETED')

    def test_08_status_update_unknown_status_rejected(self):
        """未知状态值被拒"""
        tid = self._create_transfer()
        resp = post_json(self.client, f'/document/transfers/{tid}/status/',
                         {'status': 'NOT_A_STATUS'})
        self.assertTrue(has_error(resp), resp.json())

    def test_09_status_update_same_value_is_idempotent(self):
        """同值状态更新幂等成功"""
        tid = self._create_transfer(status='UPLOADING')
        resp = post_json(self.client, f'/document/transfers/{tid}/status/',
                         {'status': 'UPLOADING'})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=tid).status, 'UPLOADING')

    def test_10_cancel_from_uploading(self):
        """UPLOADING -> CANCELED 成功"""
        tid = self._create_transfer(status='UPLOADING')
        resp = post_json(self.client, f'/document/transfers/{tid}/cancel/', {})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=tid).status, 'CANCELED')

    def test_11_cancel_from_completed_rejected(self):
        """终态 COMPLETED 不允许取消"""
        tid = self._create_transfer(status='COMPLETED')
        resp = post_json(self.client, f'/document/transfers/{tid}/cancel/', {})
        self.assertTrue(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=tid).status, 'COMPLETED')

    def test_12_cancel_from_merging_allowed(self):
        """MERGING 保留取消能力"""
        tid = self._create_transfer(status='MERGING')
        resp = post_json(self.client, f'/document/transfers/{tid}/cancel/', {})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=tid).status, 'CANCELED')

    def test_13_fail_writes_error_message(self):
        """标记失败写入可诊断的 error_message"""
        tid = self._create_transfer(status='UPLOADING')
        resp = post_json(self.client, f'/document/transfers/{tid}/fail/',
                         {'error_message': '网络中断'})
        self.assertFalse(has_error(resp), resp.json())
        t = DocumentTransfer.objects.get(id=tid)
        self.assertEqual(t.status, 'FAILED')
        self.assertEqual(t.error_message, '网络中断')

    def test_14_fail_default_message(self):
        """标记失败不传参也有默认可诊断信息"""
        tid = self._create_transfer(status='UPLOADING')
        post_json(self.client, f'/document/transfers/{tid}/fail/', {})
        t = DocumentTransfer.objects.get(id=tid)
        self.assertEqual(t.status, 'FAILED')
        self.assertTrue(t.error_message, '失败状态必须提供可诊断 error')

    def test_15_failed_can_retry_to_uploading(self):
        """FAILED 可重试回到 UPLOADING"""
        tid = self._create_transfer(status='FAILED')
        resp = post_json(self.client, f'/document/transfers/{tid}/status/',
                         {'status': 'UPLOADING'})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=tid).status, 'UPLOADING')

    def test_16_progress_update(self):
        """进度更新写库"""
        tid = self._create_transfer(status='UPLOADING')
        resp = post_json(self.client, f'/document/transfers/{tid}/progress/',
                         {'progress': 55, 'uploaded_chunks': 2, 'transferred_size': 165})
        self.assertFalse(has_error(resp), resp.json())
        t = DocumentTransfer.objects.get(id=tid)
        self.assertEqual(t.progress, 55)
        self.assertEqual(t.uploaded_chunks, 2)

    def test_17_progress_cannot_be_updated_by_other_user(self):
        """他人不能更新进度"""
        tid = self._create_transfer(status='UPLOADING')
        resp = post_json(self.other_client, f'/document/transfers/{tid}/progress/',
                         {'progress': 99})
        self.assertTrue(has_error(resp), resp.json())
        self.assertNotEqual(DocumentTransfer.objects.get(id=tid).progress, 99)

    def test_18_transfer_delete(self):
        """删除自己的传输记录"""
        tid = self._create_transfer()
        resp = self.client.delete(f'/document/transfers/{tid}/delete/')
        self.assertFalse(has_error(resp), resp.json())
        self.assertFalse(DocumentTransfer.objects.filter(id=tid).exists())

    def test_19_transfer_delete_by_other_user_rejected(self):
        """他人不能删除传输记录"""
        tid = self._create_transfer()
        resp = self.other_client.delete(f'/document/transfers/{tid}/delete/')
        self.assertTrue(has_error(resp), resp.json())
        self.assertTrue(DocumentTransfer.objects.filter(id=tid).exists())

    # ---------- 3. 分片上传 ----------

    def test_20_chunk_upload_success(self):
        """分片上传成功，物理分片落盘"""
        tid = self._create_transfer()
        resp = self._upload_chunk(0, b'0123456789', transfer_id=tid)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['status'], 'uploaded')
        self.assertEqual(data['chunk_index'], 0)

        chunk_file = os.path.join(self.chunk_dir, str(tid), '0.part')
        self.assertTrue(os.path.exists(chunk_file), f'分片文件应落盘: {chunk_file}')

    def test_21_chunk_upload_out_of_order(self):
        """乱序分片上传被接受"""
        tid = self._create_transfer()
        for idx in (2, 0, 1):
            resp = self._upload_chunk(idx, b'0123456789', transfer_id=tid)
            self.assertFalse(has_error(resp), f'分片 {idx} 上传失败: {resp.json()}')
        for idx in range(3):
            self.assertTrue(os.path.exists(
                os.path.join(self.chunk_dir, str(tid), f'{idx}.part')))

    def test_22_chunk_upload_duplicate_is_idempotent(self):
        """重复上传同一分片幂等，不产生额外文件"""
        tid = self._create_transfer()
        self._upload_chunk(0, b'0123456789', transfer_id=tid)
        resp = self._upload_chunk(0, b'0123456789', transfer_id=tid)
        self.assertFalse(has_error(resp), resp.json())
        part_dir = os.path.join(self.chunk_dir, str(tid))
        self.assertEqual(len(os.listdir(part_dir)), 1, '重复分片不应产生额外文件')

    def test_23_resume_reports_missing_chunks(self):
        """断点续传检查返回缺失分片"""
        tid = self._create_transfer()
        self._upload_chunk(0, b'0123456789', transfer_id=tid)
        resp = post_json(self.client, RESUME_URL, {
            'file_hash': self.file_hash, 'total_chunks': 3,
            'transfer_id': tid, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['exists'], True)
        self.assertIn(0, data['uploaded_chunks'])
        self.assertNotIn(1, data['uploaded_chunks'])
        self.assertFalse(data['all_chunks_ready'])

    def test_24_resume_all_chunks_ready(self):
        """全部分片就绪后 all_chunks_ready 为 True"""
        tid = self._create_transfer(status='UPLOADING')
        for idx in range(3):
            self._upload_chunk(idx, b'0123456789', transfer_id=tid)
        resp = post_json(self.client, RESUME_URL, {
            'file_hash': self.file_hash, 'total_chunks': 3,
            'transfer_id': tid, 'is_public': True})
        data = get_response_data(resp)
        self.assertFalse(has_error(resp), resp.json())
        self.assertTrue(data['all_chunks_ready'], data)

    def test_25_resume_unknown_hash_returns_exists_false(self):
        """未知哈希返回 exists=False 且不报错"""
        resp = post_json(self.client, RESUME_URL, {
            'file_hash': unique('nohash'), 'total_chunks': 3, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        self.assertFalse(get_response_data(resp)['exists'])

    # ---------- 4. 分片上传安全校验 ----------

    def test_26_chunk_oversize_rejected(self):
        """分片接口按 file_size 参数拒绝超大文件（无需真实传输 100MB）"""
        resp = self._upload_chunk(0, b'x', file_size=DEFAULT_MAX_FILE_SIZE + 1)
        self.assertTrue(has_error(resp), resp.json())
        self.assertIn('超出限制', resp.json()['error'])

    def test_27_chunk_path_traversal_filename_rejected(self):
        """分片接口拒绝含 .. 的 file_name（净化而非拒绝会绕过校验函数）"""
        resp = self._upload_chunk(0, b'x', file_name='../../evil.bin')
        self.assertTrue(has_error(resp), resp.json())
        self.assertIn('非法字符', resp.json()['error'])

    def test_28_chunk_separator_filename_rejected(self):
        """分片接口拒绝含路径分隔符的 file_name"""
        resp = self._upload_chunk(0, b'x', file_name='a/b.bin')
        self.assertTrue(has_error(resp), resp.json())

    def test_29_chunk_overlong_filename_rejected(self):
        """分片接口拒绝超长 file_name"""
        resp = self._upload_chunk(0, b'x', file_name='x' * 300 + '.bin')
        self.assertTrue(has_error(resp), resp.json())

    def test_30_chunk_invalid_transfer_id_rejected(self):
        """非法 transfer_id 格式直接拒绝，不降级处理"""
        resp = self._upload_chunk(0, b'x', transfer_id='not-a-number')
        self.assertTrue(has_error(resp), resp.json())

    def test_31_chunk_cannot_use_other_users_transfer(self):
        """不能使用他人 transfer_id 上传分片"""
        tid = self._create_transfer()
        resp = self._upload_chunk(0, b'x', transfer_id=tid, client=self.other_client)
        self.assertTrue(has_error(resp), resp.json())

    def test_32_chunk_missing_file_rejected(self):
        """缺少文件分片被拒绝"""
        resp = post_json(self.client, CHUNK_URL, {
            'file_name': 'x.bin', 'file_size': 10, 'chunk_index': 0,
            'total_chunks': 1, 'file_hash': self.file_hash, 'is_public': True})
        self.assertTrue(has_error(resp), resp.json())

    def test_33_chunk_total_mismatch_rejected(self):
        """分片总数与传输记录不一致被拒"""
        tid = self._create_transfer(total_chunks=3)
        resp = self._upload_chunk(0, b'x', total_chunks=9, transfer_id=tid)
        self.assertTrue(has_error(resp), resp.json())

    def test_34_chunk_size_mismatch_rejected(self):
        """声明 chunk_size 与实际大小不符被拒"""
        tid = self._create_transfer()
        resp = self._upload_chunk(0, b'0123456789', transfer_id=tid, chunk_size=999)
        self.assertTrue(has_error(resp), resp.json())

    # ---------- 5. 合并幂等 ----------

    def test_35_direct_merge_submit(self):
        """提交合并任务返回 task_id 与 pending 状态"""
        tid = self._create_transfer(status='UPLOADING')
        for idx in range(3):
            self._upload_chunk(idx, b'0123456789', transfer_id=tid)
        resp = post_json(self.client, DIRECT_MERGE_URL, {
            'transfer_id': tid, 'folder_id': self.folder.id,
            'file_name': unique('merged') + '.bin', 'file_hash': self.file_hash,
            'total_chunks': 3, 'file_size': 30, 'is_public': True,
        })
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['status'], 'pending')
        self.assertTrue(data['task_id'])
        self.assertFalse(data['is_idempotent'])

    def test_36_direct_merge_repeat_is_idempotent(self):
        """重复提交同一合并请求返回 is_idempotent=True，不重复投递"""
        tid = self._create_transfer(status='UPLOADING')
        for idx in range(3):
            self._upload_chunk(idx, b'0123456789', transfer_id=tid)
        payload = {
            'transfer_id': tid, 'folder_id': self.folder.id,
            'file_name': unique('merged2') + '.bin', 'file_hash': self.file_hash,
            'total_chunks': 3, 'file_size': 30, 'is_public': True,
        }
        first = post_json(self.client, DIRECT_MERGE_URL, payload)
        self.assertFalse(has_error(first), first.json())
        first_task = get_response_data(first)['task_id']

        second = post_json(self.client, DIRECT_MERGE_URL, payload)
        self.assertFalse(has_error(second), second.json())
        data = get_response_data(second)
        self.assertTrue(data['is_idempotent'], data)
        self.assertEqual(data['task_id'], first_task, '重复提交不得产生新任务')

    def test_37_direct_merge_completed_with_file_record_is_idempotent(self):
        """COMPLETED 且文件记录存在 -> 幂等返回 completed"""
        tid = self._create_transfer(status='COMPLETED')
        DocumentTransfer.objects.filter(id=tid).update(
            file_path='/tmp/whatever.bin', celery_task_id='fake-task-id')
        resp = post_json(self.client, DIRECT_MERGE_URL, {
            'transfer_id': tid, 'folder_id': self.folder.id,
            'file_name': 'done.bin', 'file_hash': self.file_hash,
            'total_chunks': 3, 'file_size': 30, 'is_public': True,
        })
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['status'], 'completed')
        self.assertTrue(data['is_idempotent'])

    def test_38_direct_merge_completed_without_file_record_resets(self):
        """COMPLETED 但文件记录缺失 -> 重置为可重新合并，不产生幽灵完成态"""
        tid = self._create_transfer(status='COMPLETED')
        DocumentTransfer.objects.filter(id=tid).update(
            file_path='', celery_task_id=None)
        resp = post_json(self.client, DIRECT_MERGE_URL, {
            'transfer_id': tid, 'folder_id': self.folder.id,
            'file_name': unique('recover') + '.bin', 'file_hash': self.file_hash,
            'total_chunks': 3, 'file_size': 30, 'is_public': True,
        })
        self.assertFalse(has_error(resp), resp.json())
        t = DocumentTransfer.objects.get(id=tid)
        self.assertNotEqual(t.status, 'COMPLETED',
                            '文件记录缺失时不得停留在 COMPLETED')
        self.assertEqual(
            DocumentFilePublic.objects.filter(folder=self.folder).count(), 0,
            '重置重合并阶段不应立即产生重复文件记录')

    def test_39_merge_status_unknown_task_reports_pending(self):
        """查询不存在的合并任务：Celery 无结果后端，返回 pending（已知限制）

        行为记录：AsyncResult 对未知 task_id 返回 PENDING，接口如实透传。
        前端依赖 DEFAULT_MERGE_STATUS_TIMEOUT=300s 轮询超时兜底。
        """
        resp = self.client.get(MERGE_STATUS_URL, {'task_id': 'not-exist-task'})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(get_response_data(resp)['status'], 'pending')

    def test_40_merge_status_missing_param(self):
        """缺少 task_id 参数返回可识别错误"""
        resp = self.client.get(MERGE_STATUS_URL, {})
        self.assertTrue(has_error(resp), resp.json())

    # ---------- 6. 传输完成校验 ----------

    def test_41_complete_without_file_record_rejected(self):
        """文件记录未创建时不得标记完成"""
        tid = self._create_transfer(status='UPLOADING')
        resp = post_json(self.client, f'/document/transfers/{tid}/complete/', {})
        self.assertTrue(has_error(resp), resp.json())
        self.assertNotEqual(DocumentTransfer.objects.get(id=tid).status, 'COMPLETED')

    def test_42_complete_with_file_path_succeeds(self):
        """存在文件记录时可标记完成"""
        tid = self._create_transfer(status='UPLOADING')
        DocumentTransfer.objects.filter(id=tid).update(file_path='/tmp/x.bin')
        resp = post_json(self.client, f'/document/transfers/{tid}/complete/', {})
        self.assertFalse(has_error(resp), resp.json())
        t = DocumentTransfer.objects.get(id=tid)
        self.assertEqual(t.status, 'COMPLETED')
        self.assertIsNotNone(t.completed_at)

    def test_43_complete_on_terminal_is_idempotent(self):
        """重复的完成请求幂等成功，状态保持 COMPLETED 且无副作用"""
        tid = self._create_transfer(status='COMPLETED')
        DocumentTransfer.objects.filter(id=tid).update(file_path='/tmp/x.bin')
        before = DocumentTransfer.objects.get(id=tid).updated_at
        resp = post_json(self.client, f'/document/transfers/{tid}/complete/', {})
        self.assertFalse(has_error(resp), resp.json())
        t = DocumentTransfer.objects.get(id=tid)
        self.assertEqual(t.status, 'COMPLETED')

    # ---------- 7. 批量操作 ----------

    def test_44_batch_pause(self):
        """批量暂停只影响可暂停的记录"""
        t1 = self._create_transfer(status='UPLOADING')
        t2 = self._create_transfer(status='COMPLETED')
        resp = post_json(self.client, '/document/transfers/batch/pause/',
                         {'transfer_ids': [t1, t2]})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertIn(t1, data['updated_ids'])
        self.assertEqual(DocumentTransfer.objects.get(id=t1).status, 'PAUSED')
        self.assertEqual(DocumentTransfer.objects.get(id=t2).status, 'COMPLETED')

    def test_45_batch_resume(self):
        """批量恢复把 PAUSED 恢复到 UPLOADING"""
        t1 = self._create_transfer(status='PAUSED')
        resp = post_json(self.client, '/document/transfers/batch/resume/',
                         {'transfer_ids': [t1]})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=t1).status, 'UPLOADING')

    def test_46_batch_cancel(self):
        """批量取消提交任务"""
        t1 = self._create_transfer(status='UPLOADING')
        resp = post_json(self.client, '/document/transfers/batch/cancel/',
                         {'transfer_ids': [t1]})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(get_response_data(resp)['status'], 'pending')

    def test_47_batch_delete(self):
        """批量删除提交任务"""
        t1 = self._create_transfer(status='COMPLETED')
        resp = post_json(self.client, '/document/transfers/batch/delete/',
                         {'transfer_ids': [t1]})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(get_response_data(resp)['status'], 'pending')

    def test_48_batch_ops_ignore_other_users_transfers(self):
        """批量操作不得影响他人传输记录"""
        t_other = self._create_transfer(status='UPLOADING')
        DocumentTransfer.objects.filter(id=t_other).update(user=self.other)
        resp = post_json(self.client, '/document/transfers/batch/pause/',
                         {'transfer_ids': [t_other]})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(DocumentTransfer.objects.get(id=t_other).status, 'UPLOADING')

    # ---------- 8. 未知/不存在的 transfer ----------

    def test_49_operation_on_missing_transfer_returns_error(self):
        """操作不存在的传输记录返回可识别错误"""
        resp = post_json(self.client, '/document/transfers/99999999/status/',
                         {'status': 'UPLOADING'})
        self.assertTrue(has_error(resp), resp.json())
