"""公共资料库基础功能发布门禁测试（stable_contract）。

覆盖：目录列表/创建/幂等/重命名/删除、文件上传/列表/重命名/下载/删除、
      搜索、文件夹属性统计、递归复制/移动/删除后的数据库与物理文件状态。
"""
import os

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.document.libs.document_utils import get_document_storage_base_path, is_safe_path
from apps.document.models import DocumentFilePublic, DocumentFolderPublic
from tests.helpers.test_base import (
    get_response_data, has_error, make_client, make_user, post_json, setup_test_env)

from .helpers import StorageCleanupMixin, make_file, make_folder, unique

FOLDER_URL = '/document/folder/'
FOLDER_RENAME_URL = '/document/folder/rename/'
FOLDER_COPY_URL = '/document/folder/copy/'
FOLDER_MOVE_URL = '/document/folder/move/'
FOLDER_PROPERTIES_URL = '/document/folder/properties/'
SEARCH_URL = '/document/folder/search/'
UPLOAD_URL = '/document/upload/'
FILE_RENAME_URL = '/document/file/rename/'
FILE_DELETE_URL = '/document/file/'


class PublicBasicsTest(StorageCleanupMixin, TestCase):
    """公共资料库基础功能"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('gate_admin', is_supper=True)

    def setUp(self):
        super().setUp()
        setup_test_env()
        self.client = make_client(self.admin)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'

    # ---------- helpers ----------

    def _create_folder(self, name, parent_id=None):
        resp = post_json(self.client, FOLDER_URL, {
            'name': name, 'parent_id': parent_id, 'is_public': True,
        })
        return resp

    def _list(self, folder_id=None, **extra):
        params = {'is_public': 'true'}
        if folder_id is not None:
            params['id'] = folder_id
        params.update(extra)
        return self.client.get(FOLDER_URL, params)

    def _upload(self, filename, content=b'gate-upload', folder_id=None, **extra):
        data = {'file': SimpleUploadedFile(filename, content, content_type='text/plain'),
                'is_public': 'true'}
        if folder_id is not None:
            data['folder_id'] = folder_id
        data.update(extra)
        return self.client.post(UPLOAD_URL, data=data)

    # ---------- 1. 目录列表 ----------

    def test_01_root_list_ok(self):
        """列表: 根目录返回 folders/files 结构"""
        resp = self._list()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertIsInstance(data, dict)
        self.assertIn('folders', data)
        self.assertIn('files', data)

    def test_02_sub_folder_list_sees_children(self):
        """列表: 子目录能看到自己的子文件夹和文件"""
        parent = make_folder(created_by=self.admin)
        child = make_folder(parent=parent, created_by=self.admin)
        file_obj = make_file(folder=parent, created_by=self.admin)
        self.track_path(file_obj.file_path)

        resp = self._list(parent.id)
        data = get_response_data(resp)
        folder_ids = [f['id'] for f in data['folders']]
        file_ids = [f['id'] for f in data['files']]
        self.assertIn(child.id, folder_ids)
        self.assertIn(file_obj.id, file_ids)

    def test_03_list_does_not_leak_other_folder_children(self):
        """列表: 目录 A 不返回目录 B 的子元素"""
        a = make_folder(created_by=self.admin)
        b = make_folder(created_by=self.admin)
        file_in_b = make_file(folder=b, created_by=self.admin)
        self.track_path(file_in_b.file_path)

        data = get_response_data(self._list(a.id))
        self.assertNotIn(file_in_b.id, [f['id'] for f in data['files']])

    # ---------- 2. 文件夹 CRUD 与幂等 ----------

    def test_04_create_folder(self):
        """创建文件夹: 落库且 created=True"""
        name = unique('新建目录')
        resp = self._create_folder(name)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertTrue(data['created'])
        self.assertTrue(DocumentFolderPublic.objects.filter(id=data['id'], name=name).exists())

    def test_05_create_same_name_folder_is_idempotent(self):
        """创建同名文件夹: 幂等返回同一 id 且 created=False"""
        name = unique('幂等目录')
        first = self._create_folder(name)
        second = self._create_folder(name)
        self.assertFalse(has_error(second), second.json())
        d1, d2 = get_response_data(first), get_response_data(second)
        self.assertTrue(d1['created'])
        self.assertFalse(d2['created'])
        self.assertEqual(d1['id'], d2['id'])
        self.assertEqual(DocumentFolderPublic.objects.filter(name=name).count(), 1)

    def test_06_create_same_name_in_different_parent_allowed(self):
        """不同父目录下允许同名"""
        name = unique('同名')
        p1, p2 = make_folder(created_by=self.admin), make_folder(created_by=self.admin)
        r1 = self._create_folder(name, parent_id=p1.id)
        r2 = self._create_folder(name, parent_id=p2.id)
        self.assertTrue(get_response_data(r1)['created'])
        self.assertTrue(get_response_data(r2)['created'])
        self.assertNotEqual(get_response_data(r1)['id'], get_response_data(r2)['id'])

    def test_07_create_folder_empty_name_rejected(self):
        """空文件夹名被拒绝且不落库"""
        before = DocumentFolderPublic.objects.count()
        resp = self._create_folder('')
        self.assertTrue(has_error(resp), resp.json())
        self.assertEqual(DocumentFolderPublic.objects.count(), before)

    def test_08_create_folder_illegal_name_rejected(self):
        """非法字符文件夹名被拒绝"""
        before = DocumentFolderPublic.objects.count()
        resp = self._create_folder('bad/name')
        self.assertTrue(has_error(resp), resp.json())
        self.assertEqual(DocumentFolderPublic.objects.count(), before)

    def test_09_rename_folder(self):
        """重命名文件夹: 数据库生效"""
        folder = make_folder(created_by=self.admin)
        new_name = unique('改名后')
        resp = post_json(self.client, FOLDER_RENAME_URL,
                         {'id': folder.id, 'name': new_name, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        folder.refresh_from_db()
        self.assertEqual(folder.name, new_name)

    def test_10_rename_folder_duplicate_rejected(self):
        """重命名成已存在名称被拒绝，原名保持不变"""
        p = make_folder(created_by=self.admin)
        a = make_folder(name=unique('A'), parent=p, created_by=self.admin)
        b = make_folder(name=unique('B'), parent=p, created_by=self.admin)
        resp = post_json(self.client, FOLDER_RENAME_URL,
                         {'id': b.id, 'name': a.name, 'is_public': True})
        self.assertTrue(has_error(resp), resp.json())
        b.refresh_from_db()
        self.assertNotEqual(b.name, a.name)

    def test_11_delete_folder(self):
        """删除文件夹: 数据库记录移除"""
        folder = make_folder(created_by=self.admin)
        resp = self.client.delete(f'{FOLDER_URL}?id={folder.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        self.assertFalse(DocumentFolderPublic.objects.filter(id=folder.id).exists())

    def test_12_delete_folder_recursive_removes_db_and_physical(self):
        """递归删除: 子文件夹、文件记录与物理文件全部清除"""
        root = make_folder(created_by=self.admin)
        sub = make_folder(parent=root, created_by=self.admin)
        f_in_sub = make_file(folder=sub, created_by=self.admin)
        f_in_root = make_file(folder=root, created_by=self.admin)
        paths = [f_in_sub.file_path, f_in_root.file_path]
        for p in paths:
            self.assertTrue(os.path.exists(p), '前置条件：物理文件应存在')

        resp = self.client.delete(f'{FOLDER_URL}?id={root.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())

        self.assertFalse(DocumentFolderPublic.objects.filter(id=root.id).exists())
        self.assertFalse(DocumentFolderPublic.objects.filter(id=sub.id).exists())
        self.assertFalse(DocumentFilePublic.objects.filter(
            id__in=[f_in_sub.id, f_in_root.id]).exists())
        for p in paths:
            self.assertFalse(os.path.exists(p), f'物理文件应被删除: {p}')

    def test_13_delete_folder_does_not_touch_siblings(self):
        """递归删除不会误删兄弟目录"""
        root = make_folder(created_by=self.admin)
        sibling = make_folder(created_by=self.admin)
        f_sibling = make_file(folder=sibling, created_by=self.admin)
        self.track_path(f_sibling.file_path)

        self.client.delete(f'{FOLDER_URL}?id={root.id}&is_public=true')

        self.assertTrue(DocumentFolderPublic.objects.filter(id=sibling.id).exists())
        self.assertTrue(DocumentFilePublic.objects.filter(id=f_sibling.id).exists())
        self.assertTrue(os.path.exists(f_sibling.file_path))

    # ---------- 3. 文件上传 ----------

    def test_14_upload_small_file(self):
        """小文件上传: 数据库记录 + 物理文件都存在"""
        folder = make_folder(created_by=self.admin)
        fname = unique('upload') + '.txt'
        resp = self._upload(fname, b'hello-gate', folder_id=folder.id)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data.get('status'), 'success')

        obj = DocumentFilePublic.objects.filter(display_name=fname).first()
        self.assertIsNotNone(obj, '上传后应生成文件记录')
        self.assertEqual(obj.folder_id, folder.id)
        self.assertTrue(os.path.exists(obj.file_path), '物理文件应存在')
        self.assertEqual(obj.file_size, len(b'hello-gate'))
        self.track_path(obj.file_path)

    def test_15_upload_to_root(self):
        """上传到根目录成功"""
        fname = unique('root_upload') + '.txt'
        resp = self._upload(fname, b'root')
        self.assertFalse(has_error(resp), resp.json())
        obj = DocumentFilePublic.objects.filter(display_name=fname).first()
        self.assertIsNotNone(obj)
        self.assertIsNone(obj.folder_id)
        self.track_path(obj.file_path)

    def test_16_upload_conflict_detected(self):
        """同名冲突: 无 conflict_action 时返回 conflict"""
        folder = make_folder(created_by=self.admin)
        fname = unique('conflict') + '.txt'
        self._upload(fname, b'aaa', folder_id=folder.id)
        first = DocumentFilePublic.objects.filter(display_name=fname).first()
        self.track_path(first.file_path)

        resp = self._upload(fname, b'bbb', folder_id=folder.id)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data.get('status'), 'conflict')
        self.assertEqual(DocumentFilePublic.objects.filter(display_name=fname).count(), 1)

    def test_17_upload_conflict_keep_renames(self):
        """冲突 keep: 生成新名称，保留原文件"""
        folder = make_folder(created_by=self.admin)
        fname = unique('keep') + '.txt'
        self._upload(fname, b'aaa', folder_id=folder.id)
        first = DocumentFilePublic.objects.filter(display_name=fname).first()
        self.track_path(first.file_path)

        resp = self._upload(fname, b'bbb', folder_id=folder.id, conflict_action='keep')
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(get_response_data(resp).get('status'), 'success')
        self.assertEqual(DocumentFilePublic.objects.filter(display_name=fname).count(), 1)
        self.assertTrue(DocumentFilePublic.objects.filter(folder=folder).count() >= 2)
        for obj in DocumentFilePublic.objects.filter(folder=folder):
            self.track_path(obj.file_path)
        first.refresh_from_db()
        self.assertEqual(first.display_name, fname)

    def test_18_upload_conflict_skip(self):
        """冲突 skip: 不新增记录"""
        folder = make_folder(created_by=self.admin)
        fname = unique('skip') + '.txt'
        self._upload(fname, b'aaa', folder_id=folder.id)
        first = DocumentFilePublic.objects.filter(display_name=fname).first()
        self.track_path(first.file_path)

        resp = self._upload(fname, b'bbb', folder_id=folder.id, conflict_action='skip')
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(get_response_data(resp).get('status'), 'skipped')
        self.assertEqual(DocumentFilePublic.objects.filter(display_name=fname).count(), 1)

    def test_19_upload_conflict_replace(self):
        """冲突 replace: 替换旧记录"""
        folder = make_folder(created_by=self.admin)
        fname = unique('replace') + '.txt'
        self._upload(fname, b'aaa', folder_id=folder.id)
        old = DocumentFilePublic.objects.filter(display_name=fname).first()

        resp = self._upload(fname, b'bbb', folder_id=folder.id, conflict_action='replace')
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(DocumentFilePublic.objects.filter(display_name=fname).count(), 1)
        new = DocumentFilePublic.objects.filter(display_name=fname).first()
        self.assertNotEqual(old.id, new.id)
        self.assertEqual(new.file_size, 3)
        self.track_path(new.file_path)

    def test_20_oversize_validator_rejects(self):
        """超过 DEFAULT_MAX_FILE_SIZE(100MB)：校验函数拒绝

        HTTP 层上传 100MB+ 实体代价过高，此处对真实校验函数做行为断言，
        并在 test_upload_merge 中用分片接口的 file_size 参数做 HTTP 层验证。
        """
        from apps.document.constants import DEFAULT_MAX_FILE_SIZE
        from apps.document.views.base import validate_file_upload

        ok, msg = validate_file_upload('ok.txt', DEFAULT_MAX_FILE_SIZE + 1,
                                       max_file_size=DEFAULT_MAX_FILE_SIZE)
        self.assertFalse(ok)
        self.assertEqual(msg, '文件大小超过限制（最大100MB）')

        ok2, _ = validate_file_upload('ok.txt', DEFAULT_MAX_FILE_SIZE,
                                      max_file_size=DEFAULT_MAX_FILE_SIZE)
        self.assertTrue(ok2, '边界值 100MB 应允许')

        ok3, msg3 = validate_file_upload('ok.txt', 0, max_file_size=DEFAULT_MAX_FILE_SIZE)
        self.assertFalse(ok3)
        self.assertEqual(msg3, '文件大小必须为正数')

    def test_21_upload_path_traversal_name_cannot_escape_storage_root(self):
        """含 .. 的文件名不得逃出文档存储根目录"""
        resp = self._upload('../../evil.txt', b'x')
        self.assertFalse(has_error(resp), resp.json())

        obj = DocumentFilePublic.objects.filter(display_name='evil.txt').first()
        self.assertIsNotNone(obj, 'Django multipart 会 basename 化后接受该文件')
        self.track_path(obj.file_path)
        # 核心不变量：物理文件必须落在存储根目录内
        self.assertTrue(os.path.isabs(obj.file_path))
        self.assertTrue(
            is_safe_path(get_document_storage_base_path(), obj.file_path),
            f'物理文件必须在存储根目录内: {obj.file_path}')
        self.assertFalse(os.path.exists(
            os.path.join(settings.BASE_DIR, 'storage', 'evil.txt')),
            '不得在存储根目录之外落盘')

    def test_22_upload_separator_name_stripped(self):
        """含路径分隔符的文件名被剥离为 basename，不产生子目录"""
        resp = self._upload('a/b.txt', b'x')
        self.assertFalse(has_error(resp), resp.json())
        obj = DocumentFilePublic.objects.filter(display_name='b.txt').first()
        self.assertIsNotNone(obj)
        self.track_path(obj.file_path)
        self.assertFalse(os.path.exists(
            os.path.join(settings.BASE_DIR, 'storage', 'documents', 'public', 'a')),
            '不得创建子目录')

    def test_23_upload_to_missing_folder_rejected(self):
        """上传到不存在的文件夹被拒绝"""
        resp = self._upload(unique('nofolder') + '.txt', b'x', folder_id=99999999)
        self.assertTrue(has_error(resp), resp.json())

    # ---------- 4. 文件重命名 / 删除 ----------

    def test_24_rename_file(self):
        """文件重命名: 数据库生效，物理路径不变"""
        obj = make_file(created_by=self.admin, name=unique('old') + '.txt')
        self.track_path(obj.file_path)
        old_path = obj.file_path
        new_name = unique('new') + '.txt'

        resp = post_json(self.client, FILE_RENAME_URL,
                         {'id': obj.id, 'name': new_name, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        obj.refresh_from_db()
        self.assertEqual(obj.display_name, new_name)
        self.assertEqual(obj.file_path, old_path, '重命名不应移动物理文件')

    def test_25_delete_file_removes_db_and_physical(self):
        """文件删除: 先删物理文件再删数据库记录"""
        obj = make_file(created_by=self.admin)
        self.assertTrue(os.path.exists(obj.file_path))
        resp = self.client.delete(f'{FILE_DELETE_URL}?id={obj.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        self.assertFalse(DocumentFilePublic.objects.filter(id=obj.id).exists())
        self.assertFalse(os.path.exists(obj.file_path), '物理文件应被删除')

    def test_26_delete_missing_file_returns_error(self):
        """删除不存在的文件返回业务错误（HTTP 200 + error）"""
        resp = self.client.delete(f'{FILE_DELETE_URL}?id=99999999&is_public=true')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(has_error(resp), '缺失文件应返回业务错误')

    # ---------- 5. 搜索 ----------

    def test_27_search_global(self):
        """全局搜索: 命中文件名"""
        folder = make_folder(name=unique('搜索目录'), created_by=self.admin)
        obj = make_file(folder=folder, created_by=self.admin,
                        name=unique('搜索文件') + '.txt')
        self.track_path(obj.file_path)

        resp = self.client.get(SEARCH_URL, {'keyword': obj.display_name, 'is_public': 'true'})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertIn(obj.id, [f['id'] for f in data['files']])

    def test_28_search_scoped_to_folder(self):
        """当前目录搜索: 不返回其他目录的结果"""
        a = make_folder(created_by=self.admin)
        b = make_folder(created_by=self.admin)
        target = unique('目录内') + '.txt'
        in_a = make_file(folder=a, created_by=self.admin, name=target)
        out = make_file(folder=b, created_by=self.admin, name=target)
        self.track_path(in_a.file_path)
        self.track_path(out.file_path)

        resp = self.client.get(SEARCH_URL,
                               {'keyword': target, 'folder_id': a.id, 'is_public': 'true'})
        data = get_response_data(resp)
        ids = [f['id'] for f in data['files']]
        self.assertIn(in_a.id, ids)
        self.assertNotIn(out.id, ids)

    def test_29_search_empty_keyword_returns_empty(self):
        """空关键字返回空结果"""
        resp = self.client.get(SEARCH_URL, {'keyword': '   ', 'is_public': 'true'})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['files'], [])
        self.assertEqual(data['folders'], [])

    # ---------- 6. 文件夹属性统计 ----------

    def test_30_folder_properties_recursive_stats(self):
        """文件夹属性: 递归统计子目录数、文件数、总大小"""
        root = make_folder(created_by=self.admin)
        sub = make_folder(parent=root, created_by=self.admin)
        f1 = make_file(folder=root, created_by=self.admin, content=b'a' * 10)
        f2 = make_file(folder=sub, created_by=self.admin, content=b'b' * 20)
        self.track_path(f1.file_path)
        self.track_path(f2.file_path)

        resp = self.client.get(FOLDER_PROPERTIES_URL,
                               {'id': root.id, 'is_public': 'true', 'type': 'folder'})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['sub_folder_count'], 1)
        self.assertEqual(data['file_count'], 2)
        self.assertEqual(data['total_size'], 30)

    # ---------- 7. 复制 / 移动 ----------

    def test_31_copy_folder_keeps_source(self):
        """复制文件夹: 源文件仍在，目标产生新记录"""
        src = make_folder(created_by=self.admin)
        dst = make_folder(created_by=self.admin)
        f = make_file(folder=src, created_by=self.admin)
        self.track_path(f.file_path)

        resp = post_json(self.client, FOLDER_COPY_URL,
                         {'id': src.id, 'target_id': dst.id, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())

        self.assertTrue(DocumentFilePublic.objects.filter(id=f.id).exists(), '源文件应保留')
        self.assertTrue(os.path.exists(f.file_path), '源物理文件应保留')
        copies = DocumentFilePublic.objects.filter(folder__parent=dst)
        self.assertTrue(copies.exists(), '目标目录应产生副本')
        for c in copies:
            self.track_path(c.file_path)
            self.assertTrue(os.path.exists(c.file_path), f'副本物理文件应存在: {c.file_path}')

    def test_32_move_folder(self):
        """移动文件夹: 父子关系更新"""
        src = make_folder(created_by=self.admin)
        dst = make_folder(created_by=self.admin)
        child = make_folder(parent=src, created_by=self.admin)

        resp = post_json(self.client, FOLDER_MOVE_URL,
                         {'id': src.id, 'target_id': dst.id, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        src.refresh_from_db()
        self.assertEqual(src.parent_id, dst.id)
        child.refresh_from_db()
        self.assertEqual(child.parent_id, src.id)

    def test_33_move_folder_into_itself_rejected(self):
        """移动文件夹到自身/子目录被拒绝（循环引用防护）"""
        parent = make_folder(created_by=self.admin)
        child = make_folder(parent=parent, created_by=self.admin)

        resp = post_json(self.client, FOLDER_MOVE_URL,
                         {'id': parent.id, 'target_id': child.id, 'is_public': True})
        self.assertTrue(has_error(resp), '移动到子目录应被拒绝')
        parent.refresh_from_db()
        self.assertIsNone(parent.parent_id)

        resp2 = post_json(self.client, FOLDER_MOVE_URL,
                          {'id': parent.id, 'target_id': parent.id, 'is_public': True})
        self.assertTrue(has_error(resp2), '移动到自身应被拒绝')
        parent.refresh_from_db()
        self.assertIsNone(parent.parent_id)

    def test_34_move_folder_to_root(self):
        """移动文件夹到根目录"""
        parent = make_folder(created_by=self.admin)
        child = make_folder(parent=parent, created_by=self.admin)
        resp = post_json(self.client, FOLDER_MOVE_URL,
                         {'id': child.id, 'target_id': None, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        child.refresh_from_db()
        self.assertIsNone(child.parent_id)
