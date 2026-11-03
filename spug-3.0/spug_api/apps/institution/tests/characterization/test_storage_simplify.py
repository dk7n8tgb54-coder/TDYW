# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""存储/发布简化后的真实行为测试（2026-11-02 原稿体系移除）

本文件聚焦"原稿体系移除 + 上传直建当前草稿"的结构性不变量；其余同契约
行为已分散在既有套件（不重复造断言，映射如下）：

- 新增文件直建草稿、.doc 转换成功/失败零残留：
  `test_manual_draft.py`（DocConversionTests / DraftSaveTests）、
  `test_manual_multi_files.py`（FileManageTests）。
- 旧草稿替换清理与失败补偿：`test_manual_draft.py`
  （test_save_replaces_old_draft_file_and_cleans_it）。
- 发布失败无副作用、发布保留工作副本、修订轮开关：
  `test_revision_state.py`、`test_manual_multi_files.py`。
- 草稿缺失恢复规则（当前生效版本恢复 / 无可恢复快照提示重新上传 /
  original_id 旧参数拒绝）：`test_manual_draft_recovery.py`。
- 原稿记录/物理文件清理只动 originals/ 根、不碰草稿与版本：
  `tests/test_original_cleanup.py`。

本文件覆盖：
1. 每份上传文件各建独立 ManualFile + 当前 ManualDraft；数据库无原稿表、
   磁盘 originals/ 无原稿文件；响应不再带 originals_count/source_original_id。
2. 移除文件仅退出待发布清单：发布前清单/预检 removed 分组可见，发布后
   新版本不含该文件，旧版本仍含其快照；条目与休眠草稿保留。
3. 发布保留当前草稿（revision/base_version/revision_open）且旧版本快照
   字节不可变；后续草稿修改只产生新版本，不覆写历史快照。
4. 原稿接口全部下线（originals-overview / 文件级 originals 列表与上传 /
   制度级旧 originals 下载预览），旧表已随迁移删除。
"""
import hashlib
import os
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from apps.institution import storage
from apps.institution.models import (ManualDraft, ManualFile, ManualVersion,
                                     ManualVersionFile)
from apps.institution.tests.base import (delete_json, get_data, has_error,
                                         post_json)
from apps.institution.tests.characterization.test_manual_multi_files import (
    DOCX, MultiFileBase,
)

LEGACY_ORIGINAL_TABLE = 'tdyw_institution_original'


class StorageSimplifyBase(MultiFileBase):
    """在 MultiFileBase（所有者/编制者/发布者）之上补本文件专用助手"""

    def _originals_files(self):
        os_root = os.path.join(self._tmp.name, 'originals')
        found = []
        for dirpath, _, filenames in os.walk(os_root):
            found.extend(os.path.join(dirpath, name) for name in filenames)
        return found

    def _assert_no_original_data(self):
        self.assertEqual(self._originals_files(), [])
        self.assertNotIn(
            LEGACY_ORIGINAL_TABLE, connection.introspection.table_names())

    def _publish(self, note):
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/publish/',
            {'change_note': note})
        self.assertFalse(has_error(resp), resp.content)
        return ManualVersion.objects.get(pk=get_data(resp)['id'])

    @staticmethod
    def _read_bytes(rel_path):
        with open(storage.resolve_absolute_path(rel_path), 'rb') as stream:
            return stream.read()

    def _draft_of(self, file_id):
        return ManualDraft.objects.get(file_id=file_id)


class DirectDraftCreationTests(StorageSimplifyBase):
    """上传文件直接建立当前草稿，不再保存任何原稿副本"""

    def test_each_upload_creates_independent_draft_and_no_original_data(self):
        first = self._add_file('规程甲.docx', DOCX + b'-a', owner=self.manager)
        second = self._add_file('规程乙.docx', DOCX + b'-b', owner=self.manager)
        # 每个上传文件各自一条 ManualFile + 一条当前草稿（不是共享草稿）
        self.assertEqual(
            ManualFile.objects.filter(manual=self.manual).count(), 2)
        self.assertEqual(
            ManualDraft.objects.filter(file__manual=self.manual).count(), 2)
        draft_a = self._draft_of(first['id'])
        draft_b = self._draft_of(second['id'])
        self.assertEqual(draft_a.revision, 1)
        self.assertEqual(draft_b.revision, 1)
        self.assertNotEqual(draft_a.file_path, draft_b.file_path)
        # 两份草稿物理文件真实存在且内容即上传字节
        self.assertEqual(self._read_bytes(draft_a.file_path), DOCX + b'-a')
        self.assertEqual(self._read_bytes(draft_b.file_path), DOCX + b'-b')
        # 上传即草稿：无原稿表记录、无 originals/ 物理文件
        self._assert_no_original_data()
        # 响应不再下发原稿字段（前端无 draft_error 警示语义）
        self.assertNotIn('originals_count', first)
        self.assertNotIn('source_original_id', first)
        self.assertNotIn('draft_error', first)


class RemoveFileScopeTests(StorageSimplifyBase):
    """移除文件只退出待发布清单；发布后才影响新版本，旧版本可追溯"""

    def test_remove_only_leaves_pending_list_until_publish(self):
        file_a = self._add_file('甲.docx', DOCX + b'-a', owner=self.manager)
        file_b = self._add_file('乙.docx', DOCX + b'-b', owner=self.manager)
        v1 = self._publish('第一版')
        self.assertEqual(v1.files.count(), 2)
        snapshot_b = ManualVersionFile.objects.get(
            version=v1, manual_file_id=file_b['id'])
        snapshot_b_bytes = self._read_bytes(snapshot_b.file_path)

        # 移除乙：条目软删除、休眠草稿保留，绝不立即删历史快照
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_b["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        entry_b = ManualFile.objects.get(pk=file_b['id'])
        self.assertTrue(entry_b.is_removed)
        self.assertTrue(ManualDraft.objects.filter(file_id=file_b['id']).exists())
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(snapshot_b.file_path)))

        # 发布前：待发布清单只剩甲；预检 removed 分组仍可见乙（供发布者确认）
        self.assertEqual([row['name'] for row in self._files_list()], ['甲.docx'])
        plan = get_data(self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/'))
        self.assertEqual([row['name'] for row in plan['removed']], ['乙.docx'])
        self.assertEqual(plan['removed'][0]['from_version_no'], 1)

        # 发布后：新版本只含甲；旧版本仍含甲+乙且乙快照字节未变
        v2 = self._publish('第二版')
        self.assertEqual(v2.files.count(), 1)
        self.assertFalse(
            v2.files.filter(manual_file_id=file_b['id']).exists())
        self.assertEqual(v1.files.count(), 2)
        snapshot_b.refresh_from_db()
        self.assertEqual(self._read_bytes(snapshot_b.file_path),
                         snapshot_b_bytes)
        # 休眠草稿仍保留（回退可重新纳入），历史版本快照未被清理
        self.assertTrue(ManualDraft.objects.filter(file_id=file_b['id']).exists())


class PublishKeepsDraftTests(StorageSimplifyBase):
    """发布保留当前草稿并产生新的完整快照；旧版本快照不可变"""

    def test_publish_keeps_working_copy_and_history_immutable(self):
        data = self._add_file('正文.docx', DOCX + b'-v1', owner=self.manager)
        v1 = self._publish('第一版')
        draft = self._draft_of(data['id'])
        # 发布不改写草稿修订号；工作副本保留并指向新版本；修订轮关闭
        self.assertEqual(draft.revision, 1)
        self.assertEqual(draft.base_version_id, v1.id)
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(draft.file_path)))
        entry = ManualFile.objects.get(pk=data['id'])
        self.assertFalse(entry.revision_open)
        snapshot = ManualVersionFile.objects.get(
            version=v1, manual_file_id=data['id'])
        snapshot_bytes = self._read_bytes(snapshot.file_path)
        self.assertNotEqual(snapshot.file_path, draft.file_path)

        # 在保留的工作副本上继续修订（真实会话 + multipart 上传）
        self._set_password()
        resp = self._start_session(
            client=self.manager_client, file_id=data['id'])
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/{data["id"]}/'
            f'draft/save/',
            {'file': SimpleUploadedFile('改后.docx', DOCX + b'-v2'),
             'session_key': session_key, 'revision': 1})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 2)
        delete_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/{data["id"]}/'
            f'draft/session/',
            {'session_key': session_key, 'discard': True})

        v2 = self._publish('第二版')
        # 新版本快照=修改后的草稿；旧版本快照文件字节/哈希/归属保持不变
        new_snapshot = ManualVersionFile.objects.get(
            version=v2, manual_file_id=data['id'])
        self.assertEqual(self._read_bytes(new_snapshot.file_path),
                         DOCX + b'-v2')
        self.assertNotEqual(new_snapshot.file_path, snapshot.file_path)
        snapshot.refresh_from_db()
        self.assertEqual(self._read_bytes(snapshot.file_path),
                         snapshot_bytes)
        self.assertEqual(snapshot.file_hash,
                         hashlib.sha256(snapshot_bytes).hexdigest())
        # 发布后草稿工作副本仍在（revision=2、base_version=新版本、修订轮关闭）
        draft = self._draft_of(data['id'])
        self.assertEqual(draft.revision, 2)
        self.assertEqual(draft.base_version_id, v2.id)
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(draft.file_path)))
        entry = ManualFile.objects.get(pk=data['id'])
        self.assertFalse(entry.revision_open)


class OriginalInterfacesRemovedTests(StorageSimplifyBase):
    """原稿接口与旧表已整体删除（前端不再有任何调用入口）"""

    def test_original_endpoints_are_gone_and_legacy_table_absent(self):
        data = self._add_file('规程.docx', DOCX, owner=self.manager)
        base = f'/institution/manuals/{self.manual.id}'
        get_paths = [
            f'{base}/originals-overview/',
            f'{base}/originals/',
            f'{base}/files/{data["id"]}/originals/',
            f'{base}/files/{data["id"]}/originals/upload/',
        ]
        for path in get_paths:
            self.assertEqual(self.manager_client.get(path).status_code, 404)
        self.assertEqual(
            self.manager_client.post(
                f'{base}/files/{data["id"]}/originals/upload/', {}).status_code,
            404)
        # 旧表随迁移 0010 删除，磁盘 originals/ 无任何原稿文件
        self._assert_no_original_data()
