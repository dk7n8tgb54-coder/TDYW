# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 共享测试基础
# 提供用户工厂、权限设置、临时文件目录、断言辅助等公共功能
import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.conf import settings

from apps.account.models import User, Role


def make_access_token():
    """生成 32 字符 access_token"""
    return uuid.uuid4().hex


def make_user(username='testuser', is_supper=False, tenant_id='admin',
              perms=None, password='test123'):
    """创建测试用户

    Args:
        username: 用户名
        is_supper: 是否超管（跳过所有权限检查）
        tenant_id: 租户ID
        perms: 权限列表，如 ['radio_license.license.view', 'radio_license.license.add']
        password: 明文密码
    """
    user = User.objects.create(
        username=username,
        nickname=username,
        password_hash=User.make_password(password),
        access_token=make_access_token(),
        is_supper=is_supper,
        is_active=True,
        tenant_id=tenant_id,
    )
    if perms and not is_supper:
        role = Role.objects.create(
            name=f'{username}_role',
            desc='',
            page_perms='',
            perms_version=1,
            created_by=user,
        )
        # 构造 page_perms JSON: {"radio_license": {"license": {"view", "add"}}}
        perm_tree = {}
        for p in perms:
            parts = p.split('.')
            if len(parts) >= 3:
                module, model, action = parts[0], parts[1], parts[2]
                perm_tree.setdefault(module, {}).setdefault(model, set()).add(action)
        import json
        page_perms_dict = {}
        for module, models in perm_tree.items():
            page_perms_dict[module] = {}
            for model, actions in models.items():
                page_perms_dict[module][model] = {a: True for a in actions}
        role.page_perms = json.dumps(page_perms_dict)
        role.save()
        user.roles.add(role)
        # 清除权限缓存强制重算
        user.set_perms_cache(None)
    return user


def make_role(name, perms_list, created_by):
    """创建带权限的角色

    Args:
        name: 角色名
        perms_list: 权限列表如 ['radio_license.license.view']
        created_by: 创建者 User
    """
    import json
    perm_tree = {}
    for p in perms_list:
        parts = p.split('.')
        if len(parts) >= 3:
            module, model, action = parts[0], parts[1], parts[2]
            perm_tree.setdefault(module, {}).setdefault(model, set()).add(action)
    page_perms_dict = {}
    for module, models in perm_tree.items():
        page_perms_dict[module] = {}
        for model, actions in models.items():
            page_perms_dict[module][model] = {a: True for a in actions}
    role = Role.objects.create(
        name=name,
        desc='',
        page_perms=json.dumps(page_perms_dict),
        perms_version=1,
        created_by=created_by,
    )
    return role


class DocAdminTestBase(TestCase):
    """资料与行政业务测试基类

    - 提供临时文件目录
    - 自动清理测试数据
    - 提供 HTTP client 封装
    """

    @classmethod
    def setUpTestData(cls):
        """创建测试用户集合"""
        cls.admin_user = make_user(
            'admin_test', is_supper=True, tenant_id='admin'
        )
        cls.tenant_a_admin = make_user(
            'tenant_a_admin', is_supper=True, tenant_id='tenant_a'
        )
        cls.tenant_b_admin = make_user(
            'tenant_b_admin', is_supper=True, tenant_id='tenant_b'
        )
        cls.normal_user = make_user(
            'normal_user', is_supper=False, tenant_id='admin',
            perms=['radio_license.license.view',
                   'contract_agreement.agreement.view',
                   'document.document.view',
                   'document.regulation.view']
        )
        cls.no_perm_user = make_user(
            'no_perm_user', is_supper=False, tenant_id='admin'
        )

    def setUp(self):
        """每个测试方法前创建临时目录"""
        self.tmp_dir = tempfile.mkdtemp(prefix='doc_admin_test_')
        # 记录原始 settings
        self._original_base_dir = getattr(settings, 'BASE_DIR', None)

    def tearDown(self):
        """清理临时目录"""
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ===== HTTP Client 封装 =====

    def api_get(self, client, path, user=None, **extra):
        """发起 GET 请求，自动附加 access_token

        Args:
            client: Django test client
            path: API 路径（不含 /api/ 前缀）
            user: 用户对象，None 则不附加 token
        """
        if user:
            extra['HTTP_X_TOKEN'] = user.access_token
        return client.get(path, **extra)

    def api_post(self, client, path, data=None, user=None,
                 content_type='application/json', **extra):
        """发起 POST 请求"""
        import json
        if user:
            extra['HTTP_X_TOKEN'] = user.access_token
        if content_type == 'application/json' and data is not None:
            data = json.dumps(data)
        return client.post(path, data=data, content_type=content_type, **extra)

    def api_delete(self, client, path, user=None, **extra):
        """发起 DELETE 请求"""
        if user:
            extra['HTTP_X_TOKEN'] = user.access_token
        return client.delete(path, **extra)

    # ===== 断言辅助 =====

    def assertApiResponse(self, response, expect_error=None, expect_code=200):
        """断言 API 响应

        Args:
            response: Django HttpResponse
            expect_error: 期望的 error 消息（None 表示期望成功）
            expect_code: 期望 HTTP 状态码
        """
        self.assertEqual(response.status_code, expect_code,
                         f'HTTP status mismatch: got {response.status_code}')
        import json
        body = json.loads(response.content)
        if expect_error is not None:
            self.assertIn('error', body, f'Expected error but got success: {body}')
            if expect_error is not True:
                self.assertIn(expect_error, body['error'],
                              f'Error message mismatch: {body["error"]}')
        else:
            self.assertNotIn('error', body, f'Unexpected error: {body.get("error", "")}')
        return body

    def assertFileExists(self, path):
        """断言物理文件存在"""
        self.assertTrue(os.path.exists(path), f'File should exist: {path}')

    def assertFileNotExists(self, path):
        """断言物理文件不存在"""
        self.assertFalse(os.path.exists(path), f'File should NOT exist: {path}')

    def assertDbRecordExists(self, model, **filters):
        """断言数据库记录存在"""
        qs = model.objects.filter(**filters)
        self.assertTrue(qs.exists(),
                        f'{model.__name__} record should exist with {filters}')

    def assertDbRecordNotExists(self, model, **filters):
        """断言数据库记录不存在"""
        qs = model.objects.filter(**filters)
        self.assertFalse(qs.exists(),
                         f'{model.__name__} record should NOT exist with {filters}')

    # ===== 日期辅助 =====

    @staticmethod
    def today():
        return date.today()

    @staticmethod
    def days_from_now(days):
        return date.today() + timedelta(days=days)

    @staticmethod
    def date_str(d):
        """转字符串格式 YYYY-MM-DD"""
        if isinstance(d, date):
            return d.strftime('%Y-%m-%d')
        return str(d)

    # ===== 文件操作辅助 =====

    def create_temp_file(self, filename='test.txt', content=b'hello world',
                         subdir=None):
        """在临时目录中创建测试文件

        Returns:
            str: 文件绝对路径
        """
        target_dir = self.tmp_dir
        if subdir:
            target_dir = os.path.join(self.tmp_dir, subdir)
            os.makedirs(target_dir, exist_ok=True)
        filepath = os.path.join(target_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
        return filepath

    def create_temp_chunk(self, chunk_dir, chunk_index, content=b'chunk_data'):
        """创建测试分片文件"""
        os.makedirs(chunk_dir, exist_ok=True)
        chunk_path = os.path.join(chunk_dir, str(chunk_index))
        with open(chunk_path, 'wb') as f:
            f.write(content)
        return chunk_path
