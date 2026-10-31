# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""kkFileView 预览缓存键（fullfilename）契约：显示名不得作为缓存键

kkFileView 以 fullfilename 作为回源下载文件名与转换缓存键（缓存目录按该名
存放下载源与转换产物，同名即命中同一条目）：两份显示名相同、内容不同的
文件若都以显示名作为 fullfilename，第二份预览会直接命中第一份的转换缓存
（串版）。dev 环境实测复现：先预览草稿，再预览同显示名的生效版快照，
看到的是草稿内容（快照物理文件与其哈希本身完好，串版只发生在缓存层）。

契约（originals / drafts / versions / version files 四类预览同一口径）：
- fullfilename = basename(file_path)（build_stored_name 生成的含 UUID 存储
  名，与物理文件唯一对应）；显示名只作为 file_name 下发，不参与缓存键；
- 同显示名、不同内容的两个文件，fullfilename 必须互不相同；
- preview_token 回源字节流与各自物理文件一致（回源不串用）。
"""
import base64
import os
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings

from apps.institution import storage
from apps.institution.models import (
    Manual, ManualDraft, ManualFile, ManualOriginal, ManualVersion,
    ManualVersionFile)
from apps.institution.tests.base import (
    PERM_DRAFT, PERM_VIEW, get_data, has_error, make_client, make_grant,
    make_user, setup_test_env)

DISPLAY_NAME = '同名文件.docx'
CONTENT_A = b'PK\x03\x04 preview cache key content A'
CONTENT_B = b'PK\x03\x04 preview cache key content B'


def parse_preview(preview_url):
    """从 kkFileView URL 还原回源 file_url 与 query（preview_url=base64(url)）"""
    file_url = base64.b64decode(preview_url.split('url=')[1]).decode()
    query = parse_qs(urlparse(file_url).query)
    return file_url, query


class PreviewCacheKeyMixin:
    """公共环境：隔离存储目录 + 手册 + 持编制/查看角色的用户

    （override_settings 钉住 KKFILEVIEW 配置，不依赖运行环境变量，
    装饰在各 TestCase 子类上——SimpleTestCase 才能被该装饰器修饰。）
    """

    def setUp(self):
        setup_test_env()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.manual = Manual.objects.create(
            name='预览缓存键手册', code='YL-001',
            org_type=Manual.OWNER_SECTION, org_name='甲科室',
            tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptA',
                                perms=[PERM_DRAFT])
        make_grant(self.manual, self.editor, can_edit=True)
        self.viewer = make_user('viewer', tenant_id='deptB',
                                perms=[PERM_VIEW])
        make_grant(self.manual, self.viewer, can_view=True)

    def _write_physical(self, kind, content):
        """按存储约定生成一份真实物理文件，返回相对路径"""
        rel = storage.build_relative_path(
            kind, self.manual.id, storage.build_stored_name(DISPLAY_NAME))
        abs_path = storage.resolve_absolute_path(rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(content)
        return rel


@override_settings(KKFILEVIEW_API_URL='/kkfileview',
                   KKFILEVIEW_SERVER_URL='http://tdyw-test')
class DraftPreviewCacheKeyTests(PreviewCacheKeyMixin, TestCase):
    """草稿预览：同显示名不同内容的两份草稿，缓存键必须分离"""

    def _make_file_with_draft(self, content):
        entry = ManualFile.objects.create(
            manual=self.manual, display_name=DISPLAY_NAME, sort_order=0)
        rel = self._write_physical('draft', content)
        draft = ManualDraft.objects.create(
            manual=self.manual, file=entry, file_path=rel,
            original_name=DISPLAY_NAME, file_size=len(content), revision=1)
        return entry, draft

    def _get_preview(self, entry):
        resp = self.editor_client = make_client(self.editor).get(
            f'/institution/manuals/{self.manual.id}/files/{entry.id}/draft/preview-url/')
        self.assertFalse(has_error(resp))
        return get_data(resp)

    def test_fullfilename_is_unique_stored_name_not_display_name(self):
        entry_a, draft_a = self._make_file_with_draft(CONTENT_A)
        entry_b, draft_b = self._make_file_with_draft(CONTENT_B)
        data_a = self._get_preview(entry_a)
        data_b = self._get_preview(entry_b)
        _, query_a = parse_preview(data_a['preview_url'])
        _, query_b = parse_preview(data_b['preview_url'])
        key_a = query_a['fullfilename'][0]
        key_b = query_b['fullfilename'][0]
        # 缓存键 = 唯一存储名（basename(file_path)），绝不是显示名
        self.assertEqual(key_a, os.path.basename(draft_a.file_path.replace('\\', '/')))
        self.assertEqual(key_b, os.path.basename(draft_b.file_path.replace('\\', '/')))
        self.assertNotEqual(key_a, DISPLAY_NAME)
        self.assertNotEqual(key_b, DISPLAY_NAME)
        # 同显示名、不同内容：缓存键互不相同（串版的直接判据）
        self.assertNotEqual(key_a, key_b)

    def test_file_name_response_keeps_display_name(self):
        """显示名仍作为 file_name 下发（用户可见名不受缓存键修复影响）"""
        entry, _ = self._make_file_with_draft(CONTENT_A)
        data = self._get_preview(entry)
        self.assertEqual(data['file_name'], DISPLAY_NAME)
        self.assertEqual(data['preview_type'], 'kkfileview')

    def test_backsource_stream_serves_own_bytes(self):
        """回源内容不串用：各自 preview_token 取回各自物理文件的字节"""
        entry_a, _ = self._make_file_with_draft(CONTENT_A)
        entry_b, _ = self._make_file_with_draft(CONTENT_B)
        streams = {}
        client = make_client(self.editor)
        for entry, content in ((entry_a, CONTENT_A), (entry_b, CONTENT_B)):
            data = self._get_preview(entry)
            file_url, query = parse_preview(data['preview_url'])
            # 测试直连 Django URLconf；生产由 nginx 剥离 /api 前缀
            stream_path = urlparse(file_url).path.replace('/api', '', 1)
            resp = client.get(
                f'{stream_path}?preview_token={query["preview_token"][0]}')
            self.assertEqual(resp.status_code, 200)
            body = (b''.join(resp.streaming_content) if resp.streaming
                    else resp.content)
            streams[entry.id] = body
        self.assertEqual(streams[entry_a.id], CONTENT_A)
        self.assertEqual(streams[entry_b.id], CONTENT_B)


@override_settings(KKFILEVIEW_API_URL='/kkfileview',
                   KKFILEVIEW_SERVER_URL='http://tdyw-test')
class OriginalPreviewCacheKeyTests(PreviewCacheKeyMixin, TestCase):
    """原稿预览：fullfilename 用存储名，显示名只进 file_name"""

    def _make_original(self, content):
        entry = ManualFile.objects.create(
            manual=self.manual, display_name=DISPLAY_NAME, sort_order=0)
        rel = self._write_physical('original', content)
        return ManualOriginal.objects.create(
            manual=self.manual, file=entry, file_path=rel,
            original_name=DISPLAY_NAME, ext='.docx', file_size=len(content),
            uploaded_by=self.editor)

    def test_fullfilename_is_stored_name_and_display_name_in_file_name(self):
        original = self._make_original(CONTENT_A)
        resp = make_client(self.viewer).get(
            f'/institution/manuals/{self.manual.id}/originals/{original.id}/preview-url/')
        self.assertFalse(has_error(resp))
        data = get_data(resp)
        _, query = parse_preview(data['preview_url'])
        key = query['fullfilename'][0]
        self.assertEqual(key, os.path.basename(original.file_path.replace('\\', '/')))
        self.assertNotEqual(key, DISPLAY_NAME)
        self.assertEqual(data['file_name'], DISPLAY_NAME)

    def test_same_display_name_originals_have_distinct_keys(self):
        original_a = self._make_original(CONTENT_A)
        original_b = self._make_original(CONTENT_B)
        keys = []
        for original in (original_a, original_b):
            resp = make_client(self.viewer).get(
                f'/institution/manuals/{self.manual.id}/originals/{original.id}/preview-url/')
            self.assertFalse(has_error(resp))
            _, query = parse_preview(get_data(resp)['preview_url'])
            keys.append(query['fullfilename'][0])
        self.assertNotEqual(keys[0], keys[1])


@override_settings(KKFILEVIEW_API_URL='/kkfileview',
                   KKFILEVIEW_SERVER_URL='http://tdyw-test')
class VersionPreviewCacheKeyTests(PreviewCacheKeyMixin, TestCase):
    """版本快照预览（version files 与旧单文件 versions 接口）同一契约"""

    def _make_published_version(self, content):
        entry = ManualFile.objects.create(
            manual=self.manual, display_name=DISPLAY_NAME, sort_order=0)
        rel = self._write_physical('version', content)
        version = ManualVersion.objects.create(
            manual=self.manual, version_no=1, file_path=rel,
            original_name=DISPLAY_NAME, published_by=self.editor)
        snapshot = ManualVersionFile.objects.create(
            version=version, manual_file=entry, display_name=DISPLAY_NAME,
            file_path=rel, file_size=len(content))
        self.manual.current_version = version
        self.manual.save(update_fields=['current_version'])
        return version, snapshot

    def _get_version_file_preview(self, version, snapshot):
        resp = make_client(self.viewer).get(
            f'/institution/manuals/{self.manual.id}/versions/{version.id}/'
            f'files/{snapshot.id}/preview-url/')
        self.assertFalse(has_error(resp))
        return get_data(resp)

    def test_version_file_preview_fullfilename_is_stored_name(self):
        version, snapshot = self._make_published_version(CONTENT_A)
        data = self._get_version_file_preview(version, snapshot)
        _, query = parse_preview(data['preview_url'])
        key = query['fullfilename'][0]
        self.assertEqual(key, os.path.basename(snapshot.file_path.replace('\\', '/')))
        self.assertNotEqual(key, DISPLAY_NAME)
        self.assertEqual(data['file_name'], DISPLAY_NAME)

    def test_legacy_single_version_preview_fullfilename_is_stored_name(self):
        """旧单文件 versions/<vid>/preview-url/ 委托唯一快照，同一缓存键契约"""
        version, snapshot = self._make_published_version(CONTENT_A)
        resp = make_client(self.viewer).get(
            f'/institution/manuals/{self.manual.id}/versions/{version.id}/preview-url/')
        self.assertFalse(has_error(resp))
        data = get_data(resp)
        _, query = parse_preview(data['preview_url'])
        key = query['fullfilename'][0]
        self.assertEqual(key, os.path.basename(snapshot.file_path.replace('\\', '/')))
        self.assertNotEqual(key, DISPLAY_NAME)

    def test_draft_and_snapshot_same_display_name_distinct_keys(self):
        """实测串版场景钉死：同显示名的草稿与生效快照缓存键必须互不相同"""
        entry = ManualFile.objects.create(
            manual=self.manual, display_name=DISPLAY_NAME, sort_order=0)
        draft_rel = self._write_physical('draft', CONTENT_A)
        ManualDraft.objects.create(
            manual=self.manual, file=entry, file_path=draft_rel,
            original_name=DISPLAY_NAME, file_size=len(CONTENT_A), revision=2)
        version, snapshot = self._make_published_version(CONTENT_B)
        self.assertNotEqual(CONTENT_A, CONTENT_B)
        draft_data = self._get_preview_via_editor(entry)
        snap_data = self._get_version_file_preview(version, snapshot)
        _, draft_query = parse_preview(draft_data['preview_url'])
        _, snap_query = parse_preview(snap_data['preview_url'])
        self.assertNotEqual(
            draft_query['fullfilename'][0], snap_query['fullfilename'][0])
        # 两侧都绝不是显示名
        self.assertNotEqual(draft_query['fullfilename'][0], DISPLAY_NAME)
        self.assertNotEqual(snap_query['fullfilename'][0], DISPLAY_NAME)

    def _get_preview_via_editor(self, entry):
        resp = make_client(self.editor).get(
            f'/institution/manuals/{self.manual.id}/files/{entry.id}/draft/preview-url/')
        self.assertFalse(has_error(resp))
        return get_data(resp)
