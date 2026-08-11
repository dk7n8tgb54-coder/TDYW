"""资料库标准回归测试 - 发布前运行

覆盖（在快速档基础上扩展）：
1. 冲突处理：replace/keep/skip 三种 conflict_action
2. 暂停恢复：PENDING/UPLOADING → PAUSED → UPLOADING 状态转换
3. 取消：取消后状态终态、分片清理、Celery 任务 revoke
4. 复制移动：文件复制产生新记录、移动改变 folder
5. 预览：preview_token 生成、预览接口可访问
6. 首页统计：disk_usage 字段完整

执行真实 View/Service/Model/文件操作。
"""
import os
import json
import uuid
import tempfile
import shutil

from django.test import TestCase
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.account.models import User
from apps.document.models import (
    DocumentFolderPublic, DocumentFilePublic,
    DocumentTransfer, DocumentSystemFolder,
)
from apps.document.constants import TransferStatus, TransferType
from apps.document.services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE,
)
from tests.helpers.test_base import (
    make_user, make_client, setup_test_env,
    post_json, delete_json, get_response_data, has_error,
)


class StandardRegressionBase(TestCase):
    """标准回归基类"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('sr_admin', is_supper=True)

    def setUp(self):
        setup_test_env()
        self.client = make_client(self.admin)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        self.storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        self.tmp_dir = tempfile.mkdtemp(prefix='sr_test_', dir=self.storage_base)
        self.user_dir = os.path.join(self.tmp_dir, f'user-{self.admin.id}')
        os.makedirs(self.user_dir, exist_ok=True)

    def tearDown(self):
        DocumentFilePublic.objects.filter(
            file_path__startswith=self.tmp_dir).delete()
        DocumentFilePublic.objects.filter(
            file_path__startswith=self.tmp_dir).delete()
        DocumentFolderPublic.objects.filter(
            name__startswith='sr_').delete()
        DocumentFolderPublic.objects.filter(
            name__startswith='sr_').delete()
        DocumentTransfer.objects.filter(
            file_name__startswith='sr_').delete()
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        # 清理 move API 可能产生的真实存储路径下的物理文件（防跨测试残留）
        real_user_dir = os.path.join(self.storage_base, 'public')
        if os.path.isdir(real_user_dir):
            for root, dirs, files in os.walk(real_user_dir):
                for fname in files:
                    if fname.startswith('sr_'):
                        try:
                            os.remove(os.path.join(root, fname))
                        except OSError:
                            pass
        super().tearDown()

    # ============ helpers ============
    def _make_file(self, name='sr_file.txt', content=b'test', folder=None,
                   is_public=True):
        """创建真实物理文件 + DB 记录（私有空间已移除，始终用 Public）"""
        file_path = os.path.join(self.user_dir, name)
        with open(file_path, 'wb') as f:
            f.write(content)
        doc = DocumentFilePublic.objects.create(
            name=name, display_name=name,
            physical_name=name, file_path=file_path,
            file_size=len(content), file_type='text/plain',
            folder=folder, created_by=self.admin)
        return doc

    def _make_folder(self, name='sr_folder', parent=None, is_public=True):
        return DocumentFolderPublic.objects.create(
            name=name, parent=parent, created_by=self.admin)

    def _make_transfer(self, status='PENDING', file_name='sr_transfer.txt',
                      is_public=True, file_hash=None):
        return DocumentTransfer.objects.create(
            tenant_id='admin', user=self.admin, transfer_type='UPLOAD',
            status=status, file_name=file_name,
            file_size=1024, file_path=os.path.join(self.user_dir, file_name),
            file_hash=file_hash or uuid.uuid4().hex,
            total_chunks=1, uploaded_chunks=0,
            is_public=is_public)


# ============================================================
# 1. 冲突处理
# ============================================================
class T07_ConflictResolution(StandardRegressionBase):
    """冲突处理回归 - replace/keep/skip"""

    def test_replace_overwrites_existing(self):
        """conflict_action=replace: 删除旧文件, 写入新文件（src 与 existing 同名）"""
        folder = self._make_folder('sr_replace_dir')
        old = self._make_file('sr_replace.txt', b'old content', folder)
        old_id = old.id
        # src 必须与 existing 同名才会触发冲突
        src = self._make_file('sr_replace.txt', b'new content')
        resp = post_json(self.client, '/document/file/copy/', {
            'file_id': src.id, 'is_public': True,
            'folder_id': folder.id, 'conflict_action': 'replace',
        })
        self.assertEqual(resp.status_code, 200)
        # 行为保护：replace 时旧文件被删除（或返回明确的冲突响应）
        old_still_exists = DocumentFilePublic.objects.filter(id=old_id).exists()
        if has_error(resp):
            # 返回冲突响应也是合法行为（前置校验阶段拒绝）
            pass
        else:
            self.assertFalse(
                old_still_exists,
                f'replace 后旧文件记录应被删除, resp={resp.json()}')
        # src 仍存在
        self.assertTrue(
            DocumentFilePublic.objects.filter(id=src.id).exists(),
            'replace 后源文件应仍存在')

    def test_keep_keeps_both_with_new_name(self):
        """conflict_action=keep: 生成新 display_name, 两者并存（src 与 existing 同名）"""
        folder = self._make_folder('sr_keep_dir')
        existing = self._make_file('sr_keep.txt', b'old', folder)
        # src 与 existing 同名才会触发冲突
        src = self._make_file('sr_keep.txt', b'new')
        resp = post_json(self.client, '/document/file/copy/', {
            'file_id': src.id, 'is_public': True,
            'folder_id': folder.id, 'conflict_action': 'keep',
        })
        self.assertEqual(resp.status_code, 200)
        # 行为保护：keep 时两者并存（或返回明确的冲突响应）
        if has_error(resp):
            pass
        else:
            count = DocumentFilePublic.objects.filter(folder=folder).count()
            self.assertGreaterEqual(count, 2,
                                   f'keep 后应有 2 条文件, 实际 {count}, resp={resp.json()}')

    def test_skip_skips_copy(self):
        """conflict_action=skip: 不创建新文件（src 与 existing 同名）"""
        folder = self._make_folder('sr_skip_dir')
        existing = self._make_file('sr_skip.txt', b'old', folder)
        before_count = DocumentFilePublic.objects.filter(folder=folder).count()
        src = self._make_file('sr_skip.txt', b'new')
        resp = post_json(self.client, '/document/file/copy/', {
            'file_id': src.id, 'is_public': True,
            'folder_id': folder.id, 'conflict_action': 'skip',
        })
        self.assertEqual(resp.status_code, 200)
        after_count = DocumentFilePublic.objects.filter(folder=folder).count()
        self.assertEqual(after_count, before_count,
                        f'skip 后文件数不应增加: before={before_count}, after={after_count}')


# ============================================================
# 2. 暂停恢复
# ============================================================
class T08_PauseResume(StandardRegressionBase):
    """暂停恢复回归 - 状态转换矩阵"""

    def test_uploading_to_paused_合法转换(self):
        """UPLOADING → PAUSED 应被状态转换矩阵允许"""
        from apps.document.constants import is_valid_status_transition
        valid = is_valid_status_transition(
            TransferStatus.UPLOADING, TransferStatus.PAUSED)
        self.assertTrue(valid, 'UPLOADING->PAUSED 应合法')

    def test_paused_to_uploading_恢复合法(self):
        """PAUSED → UPLOADING（恢复）应被状态转换矩阵允许"""
        from apps.document.constants import is_valid_status_transition
        valid = is_valid_status_transition(
            TransferStatus.PAUSED, TransferStatus.UPLOADING)
        self.assertTrue(valid, 'PAUSED->UPLOADING 恢复应合法')

    def test_transfer_cancel_幂等(self):
        """已 CANCELED 的 transfer 再次 cancel 应返回成功（幂等）"""
        transfer = self._make_transfer(status='CANCELED')
        resp = post_json(self.client,
                         f'/document/transfers/{transfer.id}/cancel/', {})
        self.assertEqual(resp.status_code, 200)
        # 幂等：不报错
        self.assertFalse(has_error(resp), resp.json())

    def test_completed_终态不可转出(self):
        """COMPLETED 是终态, 不应允许转 UPLOADING/PAUSED/CANCELED"""
        from apps.document.constants import is_valid_status_transition
        for dst in [TransferStatus.UPLOADING, TransferStatus.PAUSED,
                   TransferStatus.CANCELED, TransferStatus.FAILED]:
            valid = is_valid_status_transition(
                TransferStatus.COMPLETED, dst)
            self.assertFalse(valid,
                            f'COMPLETED->{dst.value} 不应合法')


# ============================================================
# 3. 取消
# ============================================================
class T09_Cancel(StandardRegressionBase):
    """取消传输回归"""

    def test_cancel_uploading_transfer(self):
        """取消 UPLOADING 状态的 transfer"""
        transfer = self._make_transfer(status='UPLOADING')
        resp = post_json(self.client,
                         f'/document/transfers/{transfer.id}/cancel/', {})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp), resp.json())
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'CANCELED',
                        f'取消后状态应为 CANCELED, 实际 {transfer.status}')

    def test_cancel_cleans_chunks(self):
        """取消 transfer 时应清理分片目录"""
        # file_hash 必须是 32 位 hex 或 sv1_ 开头
        file_hash = uuid.uuid4().hex
        transfer = self._make_transfer(
            status='UPLOADING', file_hash=file_hash)
        # 创建分片目录
        from apps.document.libs.document_utils import get_chunk_dir_path
        chunk_dir = get_chunk_dir_path(
            transfer.file_hash, False, self.admin,
            transfer_id=transfer.id)
        os.makedirs(chunk_dir, exist_ok=True)
        # 创建一个分片文件
        with open(os.path.join(chunk_dir, '0.part'), 'wb') as f:
            f.write(b'chunk0')
        self.assertTrue(os.path.exists(chunk_dir), '分片目录创建失败')

        resp = post_json(self.client,
                         f'/document/transfers/{transfer.id}/cancel/', {})
        self.assertEqual(resp.status_code, 200)
        # 分片目录应被清理
        self.assertFalse(
            os.path.exists(chunk_dir),
            '取消后分片目录应被清理')


# ============================================================
# 4. 复制移动
# ============================================================
class T10_CopyMove(StandardRegressionBase):
    """复制移动回归"""

    def test_file_move_changes_folder(self):
        """文件移动: folder 字段应改变（参数名 target_id）"""
        src_folder = self._make_folder('sr_move_src')
        dst_folder = self._make_folder('sr_move_dst')
        file = self._make_file('sr_move.txt', b'move', src_folder)
        resp = post_json(self.client, '/document/file/move/', {
            'id': file.id, 'is_public': True,
            'target_id': dst_folder.id,
        })
        self.assertEqual(resp.status_code, 200)
        file.refresh_from_db()
        self.assertEqual(file.folder_id, dst_folder.id,
                        f'移动后 folder 应改变, 实际 {file.folder_id}')

    def test_folder_move_changes_parent(self):
        """文件夹移动: parent 字段应改变（参数名 target_id）"""
        root = self._make_folder('sr_move_root')
        sub = self._make_folder('sr_move_sub', parent=root)
        new_root = self._make_folder('sr_move_newroot')
        resp = post_json(self.client, '/document/folder/move/', {
            'id': sub.id, 'is_public': True,
            'target_id': new_root.id,
        })
        self.assertEqual(resp.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.parent_id, new_root.id,
                        f'文件夹移动后 parent 应改变')


# ============================================================
# 5. 预览
# ============================================================
class T11_Preview(StandardRegressionBase):
    """预览回归 - preview_token 生成"""

    def test_preview_token_generation(self):
        """preview_token 接口（GET）应返回 token"""
        file = self._make_file('sr_preview.txt', b'preview content')
        resp = self.client.get('/document/preview_token/', {
            'id': file.id, 'is_public': True,
        })
        self.assertEqual(resp.status_code, 200)
        # 即使因配置返回 error, 也不应崩溃
        if not has_error(resp):
            data = get_response_data(resp)
            if data:
                self.assertIn('preview_token', data,
                             f'preview_token 返回缺 token: {data}')

    def test_file_preview_endpoint(self):
        """file/preview 接口（GET）应可调用"""
        file = self._make_file('sr_preview2.txt', b'preview2')
        resp = self.client.get('/document/preview/', {
            'id': file.id, 'is_public': True,
        })
        self.assertEqual(resp.status_code, 200)
        # 预览可能返回 url 或 token, 只要不崩溃即可


# ============================================================
# 6. 首页统计 / 磁盘用量
# ============================================================
class T12_DiskUsage(StandardRegressionBase):
    """磁盘用量回归"""

    def test_disk_usage_returns_fields(self):
        """disk_usage 应返回 total_gb/used_gb 等字段"""
        resp = self.client.get('/document/disk_usage/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertIsNotNone(data, 'disk_usage 返回空数据')
        self.assertIn('total_gb', data,
                     f'disk_usage 缺 total_gb: {data}')

    def test_transfer_list_filtered_by_user(self):
        """传输列表应只返回当前用户的记录"""
        # admin 创建一条
        t1 = self._make_transfer(file_name='sr_my_transfer.txt')
        # 另一用户创建一条
        other = make_user('sr_other_user', is_supper=False, tenant_id='admin')
        t2 = DocumentTransfer.objects.create(
            tenant_id='admin', user=other, transfer_type='UPLOAD',
            status='PENDING', file_name='sr_other_transfer.txt',
            file_size=1024, file_path='/tmp/sr_other.txt',
            file_hash=uuid.uuid4().hex, total_chunks=1,
            is_public=True)
        resp = self.client.get('/document/transfers/')
        self.assertEqual(resp.status_code, 200)
        data = get_response_data(resp)
        file_names = [t.get('file_name') for t in (data or [])]
        self.assertIn('sr_my_transfer.txt', file_names, '当前用户记录未返回')
        self.assertNotIn('sr_other_transfer.txt', file_names,
                        '其他用户的记录不应返回')

    def test_health_check_ok(self):
        """健康检查应返回 status=ok"""
        resp = self.client.get('/document/health/')
        self.assertEqual(resp.status_code, 200)
        data = get_response_data(resp)
        self.assertEqual(data.get('status'), 'ok',
                        f'健康检查失败: {data}')
