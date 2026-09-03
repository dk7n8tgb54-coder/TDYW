"""规章管理发布门禁测试公共基类。

设计要点（严格遵守"真实代码路径"要求）：
- 所有断言均通过 Django test client 发起真实 HTTP 请求，走完整
  中间件 -> 路由 -> 视图 -> 模型 -> 数据库 链路，不做源码字符串匹配。
- 物理文件系统通过 patch 到进程级临时目录隔离，绝不触碰容器真实 storage。
- 数据库一律使用 Django test runner 创建的 test_spug 隔离库。
"""
import hashlib
import os
import shutil
import tempfile
import time
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase

from apps.account.models import User
from apps.setting.utils import AppSetting
from apps.regulation import storage
from apps.regulation.models import (
    Regulation, RegulationCategory, RegulationAttachment,
)

PERM_VIEW = 'document.regulation.view'
PERM_ADD = 'document.regulation.add'
PERM_EDIT = 'document.regulation.edit'
PERM_DELETE = 'document.regulation.delete'
PERM_UPLOAD = 'document.regulation.upload'
PERM_DOWNLOAD = 'document.regulation.download'
PERM_CATEGORY = 'document.regulation.category_manage'

ALL_PERMS = [
    PERM_VIEW, PERM_ADD, PERM_EDIT, PERM_DELETE,
    PERM_UPLOAD, PERM_DOWNLOAD, PERM_CATEGORY,
]

# 后端允许的全部扩展名（与 storage.ALLOWED_EXTENSIONS 对应）
ALL_ALLOWED_SAMPLES = [
    ('a.pdf', b'%PDF-1.4 a', 'application/pdf'),
    ('a.doc', b'\xd0\xcf\x11\xe0doc', 'application/msword'),
    ('a.docx', b'PK\x03\x04docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('a.xls', b'\xd0\xcf\x11\xe0xls', 'application/vnd.ms-excel'),
    ('a.xlsx', b'PK\x03\x04xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    ('a.ppt', b'\xd0\xcf\x11\xe0ppt', 'application/vnd.ms-powerpoint'),
    ('a.pptx', b'PK\x03\x04pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
    ('a.txt', b'plain text', 'text/plain'),
    ('a.md', b'# md', 'text/markdown'),
    ('a.png', b'\x89PNG\r\n\x1a\n', 'image/png'),
    ('a.jpg', b'\xff\xd8\xff\xe0jpg', 'image/jpeg'),
    ('a.jpeg', b'\xff\xd8\xff\xe0jpeg', 'image/jpeg'),
    ('a.gif', b'GIF89a', 'image/gif'),
    ('a.bmp', b'BMbmp', 'image/bmp'),
    ('a.webp', b'RIFFwebpWEBP', 'image/webp'),
]


def make_token(username):
    """生成稳定且唯一的 32 字符 access_token。"""
    return hashlib.md5(('rg-token-%s' % username).encode('utf-8')).hexdigest()


def make_user(username, perms=None, is_supper=False, tenant_id=None):
    """创建测试用户并写入权限缓存。

    access_token 必须为 32 字符，token_expired 必须为未来时间戳。
    """
    kwargs = dict(
        username=username,
        nickname=username,
        password_hash='x',
        is_active=True,
        is_supper=is_supper,
        access_token=make_token(username),
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01',
        last_ip='127.0.0.1',
        type='default',
    )
    if tenant_id is not None:
        kwargs['tenant_id'] = tenant_id
    user = User.objects.create(**kwargs)
    if not is_supper:
        # version 必须与 _get_roles_perms_version() 一致才能命中缓存。
        # 测试用户无角色，_get_roles_perms_version() 返回 0，故 version=0。
        user.set_perms_cache(set(perms or []), version=0)
    return user


def make_client(user):
    """创建带认证头的测试客户端。"""
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


class StorageIsolationMixin(object):
    """把规章附件存储根目录重定向到进程级临时目录。"""

    def _isolate_storage(self):
        self._tmp_storage = tempfile.mkdtemp(prefix='reg_gate_')
        patcher = patch(
            'apps.regulation.storage.get_document_storage_base',
            return_value=self._tmp_storage,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self._tmp_storage, ignore_errors=True))

    def physical_files(self):
        """列出当前隔离存储根目录下所有物理文件（相对路径）。"""
        result = []
        base = os.path.join(self._tmp_storage, 'regulation')
        if not os.path.exists(base):
            return result
        for root, _dirs, files in os.walk(base):
            for name in files:
                full = os.path.join(root, name)
                result.append(os.path.relpath(full, self._tmp_storage))
        return result

    def physical_file_count(self):
        return len(self.physical_files())


class RegulationGateBaseMixin(StorageIsolationMixin):
    """规章管理发布门禁公共前置：账号矩阵 + 分类树 + 基础规章。"""

    def _build_accounts(self):
        self.admin = make_user('rg_admin', ALL_PERMS)
        self.admin_client = make_client(self.admin)

        self.viewer = make_user('rg_viewer', [PERM_VIEW])
        self.viewer_client = make_client(self.viewer)

        self.uploader = make_user('rg_uploader', [PERM_VIEW, PERM_UPLOAD])
        self.uploader_client = make_client(self.uploader)

        self.downloader = make_user('rg_downloader', [PERM_VIEW, PERM_DOWNLOAD])
        self.downloader_client = make_client(self.downloader)

        self.editor = make_user('rg_editor', [PERM_VIEW, PERM_EDIT])
        self.editor_client = make_client(self.editor)

        self.creator = make_user('rg_creator', [PERM_VIEW, PERM_ADD])
        self.creator_client = make_client(self.creator)

        self.deleter = make_user('rg_deleter', [PERM_VIEW, PERM_DELETE])
        self.deleter_client = make_client(self.deleter)

        self.cat_manager = make_user('rg_catman', [PERM_VIEW, PERM_CATEGORY])
        self.cat_manager_client = make_client(self.cat_manager)

        self.no_perm = make_user('rg_noperm', [])
        self.no_perm_client = make_client(self.no_perm)

        # 不同租户账号（用于验证 Regulation 无 tenant_id 的跨租户可见性）
        self.other_tenant = make_user('rg_other_tenant', [PERM_VIEW], tenant_id='other_tenant')
        self.other_tenant_client = make_client(self.other_tenant)

    def _build_categories(self):
        self.root_cat = RegulationCategory.objects.create(name='根分类', sort_order=0)
        self.leaf_cat = RegulationCategory.objects.create(
            name='叶子分类', parent=self.root_cat, sort_order=0, is_leaf=True)
        self.root_cat.is_leaf = False
        self.root_cat.save(update_fields=['is_leaf'])

    def setUp(self):
        self._isolate_storage()
        AppSetting.set('bind_ip', False)
        self._build_accounts()
        self._build_categories()
        self.regulation = Regulation.objects.create(
            title='基准规章',
            rule_no='RG-0001',
            category=self.leaf_cat,
            issuing_authority='测试发文单位',
            biz_type='空管',
            status=Regulation.STATUS_ACTIVE,
        )
        self.regulation2 = Regulation.objects.create(
            title='基准规章二',
            rule_no='RG-0002',
            status=Regulation.STATUS_ACTIVE,
        )

    # ---------- 常用操作封装 ----------

    def create_regulation(self, client=None, **overrides):
        payload = {'title': '新建规章', 'rule_no': 'RG-NEW'}
        payload.update(overrides)
        client = client or self.admin_client
        return client.post('/regulation/create/', payload, content_type='application/json')

    def upload(self, client, regulation_id, filename='up.pdf',
               content=b'%PDF-1.4 upload', content_type='application/pdf', **extra):
        file_obj = SimpleUploadedFile(filename, content, content_type=content_type)
        data = {'file': file_obj}
        data.update(extra)
        return client.post(f'/regulation/{regulation_id}/attachments/upload/', data)

    def make_attachment_record(self, regulation, name='att.pdf', content=b'%PDF-1.4 rec',
                               file_path=None, uploaded_by=None):
        """直接创建附件记录 + 真实物理文件（用于下载/预览/删除的前置数据）。"""
        rel = file_path or f'regulation/{regulation.id}/2026/09/{name}'
        abs_path = os.path.join(self._tmp_storage, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as fh:
            fh.write(content)
        return RegulationAttachment.objects.create(
            regulation=regulation,
            original_name=name,
            stored_name=name,
            file_path=rel,
            file_size=len(content),
            file_type='pdf',
            uploaded_by=uploaded_by or self.admin,
        )

    def preview_token(self, client, regulation_id, att_id):
        """通过真实 preview-url 接口换取预览令牌。"""
        resp = client.get(f'/regulation/{regulation_id}/attachments/{att_id}/preview-url/')
        url = resp.json()['data']['preview_url']
        return url.split('preview_token=', 1)[1]


class RegulationGateTestCase(RegulationGateBaseMixin, TestCase):
    """默认使用 TestCase（每个用例包裹在事务中，不触发 on_commit）。"""


class RegulationGateTransactionTestCase(RegulationGateBaseMixin, TransactionTestCase):
    """需要验证 on_commit 物理文件清理时使用（事务真实提交）。"""
