# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""规章管理模块测试

覆盖：
- 权限控制（view/upload/download）
- 附件上传/下载/删除
- 附件归属校验（跨规章下载被拒绝）
- 软删除后列表不返回、下载被拒绝
- 日期格式校验
- category_id 存在性校验
"""
import os
import re
import shutil
import json
import tempfile
import time
from unittest.mock import patch

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.account.models import User
from apps.setting.utils import AppSetting
from apps.regulation.models import Regulation, RegulationCategory, RegulationAttachment
from apps.regulation import storage


def _make_user(username, perms=None, is_supper=False):
    """创建测试用户并设置权限缓存

    access_token 必须为 32 字符，token_expired 必须为未来时间戳。
    """
    # 生成 32 字符的 token
    token = (username * 10)[:32]
    user = User.objects.create(
        username=username,
        nickname=username,
        password_hash='x',
        is_active=True,
        is_supper=is_supper,
        access_token=token,
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01',
        last_ip='127.0.0.1',
        type='default',
    )
    if not is_supper:
        # version 必须与 _get_roles_perms_version() 一致才能命中缓存。
        # 测试用户无角色，_get_roles_perms_version() 返回 0，故 version=0。
        user.set_perms_cache(set(perms or []), version=0)
    return user


def _make_client(user):
    """创建带认证头的测试客户端"""
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


class RegulationBaseTestCase(TestCase):
    """规章管理测试基类"""

    def setUp(self):
        # 隔离文件系统：patch 存储根目录到临时目录，防止 tearDown 删除生产规章文件
        self._tmp_storage_base = tempfile.mkdtemp()
        self._patcher = patch(
            'apps.regulation.storage.get_document_storage_base',
            return_value=self._tmp_storage_base,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self._tmp_storage_base, ignore_errors=True))
        AppSetting.set('bind_ip', False)

        # 不同权限用户
        # uploader 拥有全部规章写权限（add/edit/delete/upload/download/category_manage）
        ALL_REG_PERMS = [
            'document.regulation.view',
            'document.regulation.add',
            'document.regulation.edit',
            'document.regulation.delete',
            'document.regulation.upload',
            'document.regulation.download',
            'document.regulation.category_manage',
        ]
        self.viewer = _make_user('viewer', ['document.regulation.view'])
        self.uploader = _make_user('uploader', ALL_REG_PERMS)
        self.downloader = _make_user('downloader', ['document.regulation.view', 'document.regulation.download'])
        self.no_perm_user = _make_user('noperm', [])

        self.viewer_client = _make_client(self.viewer)
        self.uploader_client = _make_client(self.uploader)
        self.downloader_client = _make_client(self.downloader)
        self.no_perm_client = _make_client(self.no_perm_user)

        # 创建分类
        self.root_cat = RegulationCategory.objects.create(name='根分类', sort_order=0)
        self.leaf_cat = RegulationCategory.objects.create(
            name='叶子分类', parent=self.root_cat, sort_order=0, is_leaf=True
        )
        self.root_cat.is_leaf = False
        self.root_cat.save(update_fields=['is_leaf'])

        # 创建规章
        self.regulation = Regulation.objects.create(
            title='测试规章',
            rule_no='TEST-001',
            category=self.leaf_cat,
            issuing_authority='测试单位',
            status=Regulation.STATUS_ACTIVE,
        )
        self.regulation2 = Regulation.objects.create(
            title='测试规章2',
            rule_no='TEST-002',
            status=Regulation.STATUS_ACTIVE,
        )

    def tearDown(self):
        """清理测试产生的物理文件"""
        reg_base = storage.get_regulation_storage_base()
        if os.path.exists(reg_base):
            for subdir in os.listdir(reg_base):
                path = os.path.join(reg_base, subdir)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)


class RegulationViewPermissionTests(RegulationBaseTestCase):
    """规章查看权限测试"""

    def test_viewer_can_list_regulations(self):
        """有 view 权限可查看规章列表"""
        resp = self.viewer_client.get('/regulation/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['error'], '')
        self.assertGreaterEqual(data['data']['total'], 2)

    def test_viewer_can_view_detail(self):
        """有 view 权限可查看规章详情（含附件列表）"""
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['title'], '测试规章')
        self.assertIn('attachments', data)

    def test_viewer_can_list_attachments(self):
        """有 view 权限可查看附件列表"""
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/attachments/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data'], [])

    def test_no_perm_cannot_view(self):
        """无权限不能查看"""
        resp = self.no_perm_client.get('/regulation/')
        data = resp.json()
        self.assertEqual(data['error'], '权限拒绝')


class RegulationAttachmentUploadTests(RegulationBaseTestCase):
    """附件上传权限测试"""

    def _upload(self, client, regulation_id, filename='test.pdf', content=b'PDF content'):
        """辅助上传方法"""
        file = SimpleUploadedFile(filename, content, content_type='application/pdf')
        return client.post(
            f'/regulation/{regulation_id}/attachments/upload/',
            {'file': file},
        )

    def test_uploader_can_upload(self):
        """有 upload 权限可上传附件"""
        resp = self._upload(self.uploader_client, self.regulation.id)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['file_name'], 'test.pdf')

    def test_viewer_cannot_upload(self):
        """无 upload 权限不能上传"""
        resp = self._upload(self.viewer_client, self.regulation.id)
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_no_perm_cannot_upload(self):
        """无权限不能上传"""
        resp = self._upload(self.no_perm_client, self.regulation.id)
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_upload_creates_physical_file(self):
        """上传后物理文件存在"""
        resp = self._upload(self.uploader_client, self.regulation.id)
        att_id = resp.json()['data']['id']
        att = RegulationAttachment.objects.get(pk=att_id)
        abs_path = storage.resolve_absolute_path(att.file_path)
        self.assertTrue(os.path.exists(abs_path))

    def test_upload_uses_readable_unique_stored_name(self):
        """物理文件名使用原名主体 + 唯一后缀 + 扩展名"""
        filename = '空管 运行规定.PDF'
        resp1 = self._upload(self.uploader_client, self.regulation.id, filename=filename)
        resp2 = self._upload(self.uploader_client, self.regulation.id, filename=filename)

        att1 = RegulationAttachment.objects.get(pk=resp1.json()['data']['id'])
        att2 = RegulationAttachment.objects.get(pk=resp2.json()['data']['id'])

        self.assertEqual(att1.original_name, filename)
        self.assertRegex(att1.stored_name, r'^空管_运行规定_[0-9a-f]{12}\.PDF$')
        self.assertRegex(att2.stored_name, r'^空管_运行规定_[0-9a-f]{12}\.PDF$')
        self.assertNotEqual(att1.stored_name, att2.stored_name)
        self.assertTrue(att1.file_path.endswith(att1.stored_name))

    def test_build_stored_name_sanitizes_unsafe_characters(self):
        """清理路径分隔符和系统非法字符"""
        stored_name = storage.build_stored_name('../a/b\\c:*?"<>|.docx')
        self.assertIsNotNone(re.match(r'^c_[0-9a-f]{12}\.docx$', stored_name))

    def test_upload_rejects_invalid_type(self):
        """不支持的文件类型被拒绝"""
        file = SimpleUploadedFile('test.exe', b'exe content', content_type='application/octet-stream')
        resp = self.uploader_client.post(
            f'/regulation/{self.regulation.id}/attachments/upload/',
            {'file': file},
        )
        self.assertIn('不支持', resp.json()['error'])


class RegulationAttachmentDownloadTests(RegulationBaseTestCase):
    """附件下载测试"""

    def setUp(self):
        super().setUp()
        # 上传一个附件供下载测试使用
        file = SimpleUploadedFile('download_test.pdf', b'PDF download content', content_type='application/pdf')
        resp = self.uploader_client.post(
            f'/regulation/{self.regulation.id}/attachments/upload/',
            {'file': file},
        )
        self.att_id = resp.json()['data']['id']

        # 给 regulation2 也上传一个附件
        file2 = SimpleUploadedFile('other.pdf', b'other content', content_type='application/pdf')
        resp2 = self.uploader_client.post(
            f'/regulation/{self.regulation2.id}/attachments/upload/',
            {'file': file2},
        )
        self.att2_id = resp2.json()['data']['id']

    def test_downloader_can_download(self):
        """有 download 权限可下载附件"""
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/download/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Content-Disposition', resp)
        self.assertIn('attachment', resp['Content-Disposition'])

    def test_viewer_cannot_download(self):
        """无 download 权限不能下载"""
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/download/'
        )
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_cross_regulation_download_rejected(self):
        """下载只能下载当前规章下附件（跨规章被拒绝）"""
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att2_id}/download/'
        )
        self.assertEqual(resp.json()['error'], '附件不存在')

    def test_download_nonexistent_attachment(self):
        """下载不存在的附件返回错误"""
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/99999/download/'
        )
        self.assertEqual(resp.json()['error'], '附件不存在')


class RegulationAttachmentPreviewTests(RegulationBaseTestCase):
    """附件预览鉴权测试"""

    def setUp(self):
        super().setUp()
        file = SimpleUploadedFile('preview_test.pdf', b'PDF preview content', content_type='application/pdf')
        resp = self.uploader_client.post(
            f'/regulation/{self.regulation.id}/attachments/upload/',
            {'file': file},
        )
        self.att_id = resp.json()['data']['id']

    def test_viewer_can_get_native_preview_url(self):
        """有 view 权限可获取 PDF/图片原生预览地址，且地址使用 preview_token"""
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/preview-url/'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['preview_type'], 'native')
        self.assertIn('preview_token=', data['preview_url'])
        self.assertNotIn('x-token=', data['preview_url'])

    def test_preview_file_requires_preview_token(self):
        """预览文件流不能只靠 x-token 访问"""
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/preview-file/'
        )
        self.assertEqual(resp.json()['error'], '缺少 preview_token 参数')

    def test_preview_file_accepts_preview_token(self):
        """kkFileView/原生预览回调可通过短时效 preview_token 读取文件流"""
        url_resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/preview-url/'
        )
        preview_url = url_resp.json()['data']['preview_url']
        preview_token = preview_url.split('preview_token=', 1)[1]
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/preview-file/'
            f'?preview_token={preview_token}'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('inline', resp['Content-Disposition'])


class RegulationAttachmentDeleteTests(RegulationBaseTestCase):
    """删除附件测试"""

    def setUp(self):
        super().setUp()
        file = SimpleUploadedFile('delete_test.pdf', b'delete me', content_type='application/pdf')
        resp = self.uploader_client.post(
            f'/regulation/{self.regulation.id}/attachments/upload/',
            {'file': file},
        )
        self.att_id = resp.json()['data']['id']

    def test_delete_soft_deletes(self):
        """删除附件后列表不再返回"""
        # 删除前列表有该附件
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/attachments/')
        self.assertEqual(len(resp.json()['data']), 1)

        # 删除
        resp = self.uploader_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/'
        )
        self.assertEqual(resp.status_code, 200)

        # 删除后列表为空
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/attachments/')
        self.assertEqual(len(resp.json()['data']), 0)

        # 数据库记录仍存在但 is_deleted=True
        att = RegulationAttachment.objects.get(pk=self.att_id)
        self.assertTrue(att.is_deleted)

    def test_download_after_delete_rejected(self):
        """删除附件后下载被拒绝"""
        self.uploader_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/'
        )
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/download/'
        )
        self.assertEqual(resp.json()['error'], '附件不存在')

    def test_viewer_cannot_delete(self):
        """无 upload 权限不能删除"""
        resp = self.viewer_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/'
        )
        self.assertEqual(resp.json()['error'], '权限拒绝')


class RegulationDateValidationTests(RegulationBaseTestCase):
    """日期格式校验测试"""

    def test_invalid_publish_date(self):
        """非法发布日期返回错误"""
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '测试',
            'rule_no': 'DATE-001',
            'publish_date': '2026/07/16',
        }, content_type='application/json')
        self.assertIn('YYYY-MM-DD', resp.json()['error'])

    def test_invalid_effective_date(self):
        """非法生效日期返回错误"""
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '测试',
            'rule_no': 'DATE-002',
            'effective_date': 'not-a-date',
        }, content_type='application/json')
        self.assertIn('YYYY-MM-DD', resp.json()['error'])

    def test_empty_date_allowed(self):
        """空日期允许创建"""
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '空日期测试',
            'rule_no': 'DATE-003',
            'publish_date': '',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['publish_date'], None)

    def test_valid_date(self):
        """合法日期创建成功"""
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '合法日期测试',
            'rule_no': 'DATE-004',
            'publish_date': '2026-07-16',
            'effective_date': '2026-08-01',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['publish_date'], '2026-07-16')

    def test_invalid_date_on_edit(self):
        """编辑时非法日期返回错误"""
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'effective_date': '2026-13-45'},
            content_type='application/json',
        )
        self.assertIn('YYYY-MM-DD', resp.json()['error'])


class RegulationCategoryValidationTests(RegulationBaseTestCase):
    """分类校验测试"""

    def test_invalid_category_id(self):
        """无效 category_id 返回错误"""
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '测试',
            'rule_no': 'CAT-001',
            'category_id': 99999,
        }, content_type='application/json')
        self.assertEqual(resp.json()['error'], '所选分类不存在')

    def test_non_leaf_category_rejected(self):
        """非叶子分类被拒绝"""
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '测试',
            'rule_no': 'CAT-002',
            'category_id': self.root_cat.id,
        }, content_type='application/json')
        self.assertEqual(resp.json()['error'], '请选择叶子分类')

    def test_valid_leaf_category(self):
        """叶子分类创建成功"""
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '叶子分类测试',
            'rule_no': 'CAT-003',
            'category_id': self.leaf_cat.id,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['category_id'], self.leaf_cat.id)


class CategoryIsLeafMaintenanceTests(RegulationBaseTestCase):
    """分类树 is_leaf 维护测试"""

    def test_delete_last_child_restores_parent_leaf(self):
        """删除最后一个子分类后恢复父节点为叶子"""
        # 创建独立分类树（不关联规章，避免被"该分类下有规章"拦截）
        root = RegulationCategory.objects.create(name='独立根', sort_order=10)
        child = RegulationCategory.objects.create(
            name='独立子', parent=root, sort_order=0, is_leaf=True
        )
        root.is_leaf = False
        root.save(update_fields=['is_leaf'])
        self.assertFalse(root.is_leaf)

        # 删除唯一的子分类
        resp = self.uploader_client.delete(f'/regulation/categories/{child.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('error', ''), '')

        # 父节点恢复为叶子
        root.refresh_from_db()
        self.assertTrue(root.is_leaf)

    def test_create_child_sets_parent_non_leaf(self):
        """新建子分类时父分类设为非叶子"""
        # root_cat 已经有子分类，是非叶子
        self.assertFalse(self.root_cat.is_leaf)

        # 先创建一个新的根分类（叶子）
        resp = self.uploader_client.post('/regulation/categories/', {
            'name': '新根分类',
        }, content_type='application/json')
        new_root_id = resp.json()['data']['id']
        new_root = RegulationCategory.objects.get(pk=new_root_id)
        self.assertTrue(new_root.is_leaf)

        # 在新根分类下创建子分类
        resp = self.uploader_client.post('/regulation/categories/', {
            'name': '子分类',
            'parent_id': new_root_id,
        }, content_type='application/json')

        new_root.refresh_from_db()
        self.assertFalse(new_root.is_leaf)


class RegulationAttachmentSerializationTests(RegulationBaseTestCase):
    """附件序列化字段测试

    验证 _serialize_attachment 加法式增强后：
    - 原有字段 id/file_name/previewable 仍存在
    - 新增字段 file_size/uploaded_by_name/created_at 正确返回
    - created_at 映射模型 uploaded_at
    - uploaded_by_name 使用上传人 nickname
    - 无上传人时 uploaded_by_name 为空字符串
    """

    def setUp(self):
        super().setUp()
        file = SimpleUploadedFile(
            'serialize_test.pdf', b'serialize content', content_type='application/pdf'
        )
        resp = self.uploader_client.post(
            f'/regulation/{self.regulation.id}/attachments/upload/',
            {'file': file},
        )
        self.att_data = resp.json()['data']
        self.att_id = self.att_data['id']
        self.att_obj = RegulationAttachment.objects.get(pk=self.att_id)

    def test_upload_response_has_standard_fields(self):
        """上传响应包含原有字段和新增标准字段"""
        data = self.att_data
        # 原有字段
        self.assertIn('id', data)
        self.assertIn('file_name', data)
        self.assertIn('previewable', data)
        self.assertEqual(data['file_name'], 'serialize_test.pdf')
        self.assertTrue(data['previewable'])
        # 新增字段
        self.assertIn('file_size', data)
        self.assertIn('uploaded_by_name', data)
        self.assertIn('created_at', data)
        self.assertEqual(data['file_size'], len(b'serialize content'))

    def test_uploaded_by_name_uses_nickname(self):
        """uploaded_by_name 为上传人昵称"""
        data = self.att_data
        self.assertEqual(data['uploaded_by_name'], self.uploader.nickname)

    def test_created_at_maps_uploaded_at(self):
        """created_at 映射模型 uploaded_at"""
        data = self.att_data
        self.assertEqual(data['created_at'], self.att_obj.uploaded_at)
        self.assertTrue(data['created_at'])  # 非空

    def test_list_response_has_standard_fields(self):
        """列表响应包含标准字段"""
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/attachments/')
        self.assertEqual(resp.status_code, 200)
        items = resp.json()['data']
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIn('id', item)
        self.assertIn('file_name', item)
        self.assertIn('previewable', item)
        self.assertIn('file_size', item)
        self.assertIn('uploaded_by_name', item)
        self.assertIn('created_at', item)
        self.assertEqual(item['id'], self.att_id)
        self.assertEqual(item['file_size'], self.att_obj.file_size)

    # test_previewable_false_for_unsupported_type 已删除：
    # 规章 ALLOWED_EXTENSIONS 与可预览集合一致，previewable 恒为 True，
    # 无法构造 previewable=False 的场景。如未来扩展允许不可预览类型，需补测试。

    def test_viewer_can_preview_without_download_perm(self):
        """只有 view 权限、没有 download 权限的用户仍能通过 preview-url 预览"""
        # viewer 只有 document.regulation.view
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/preview-url/'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['preview_type'], 'native')
        self.assertIn('preview_token=', data['preview_url'])

    def test_cross_regulation_preview_rejected(self):
        """跨规章附件预览被拒绝"""
        # 给 regulation2 上传附件
        file = SimpleUploadedFile('cross.pdf', b'cross', content_type='application/pdf')
        resp2 = self.uploader_client.post(
            f'/regulation/{self.regulation2.id}/attachments/upload/',
            {'file': file},
        )
        att2_id = resp2.json()['data']['id']
        # 用 regulation1 的上下文访问 regulation2 的附件
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{att2_id}/preview-url/'
        )
        self.assertEqual(resp.json()['error'], '附件不存在')

    def test_soft_delete_hidden_from_list(self):
        """软删除后附件从列表隐藏"""
        # 删除前列表有 1 个
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/attachments/')
        self.assertEqual(len(resp.json()['data']), 1)
        # 软删除
        self.uploader_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att_id}/'
        )
        # 删除后列表为空
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/attachments/')
        self.assertEqual(len(resp.json()['data']), 0)
        # 数据库记录仍存在
        att = RegulationAttachment.objects.get(pk=self.att_id)
        self.assertTrue(att.is_deleted)
