# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""API 分页一致性 + 前端表单校验后端兜底验证测试

验证两个候选发现：
1. API 分页：12 个列表端点无分页，其中 6 个高风险
2. 前端表单校验：3 个表单缺 rules+validateFields，验证后端是否兜底

运行：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test tests.test_pagination_and_form_validation --noinput
"""
import json
import time
import uuid

from django.test import TestCase, Client
from django.contrib.auth.hashers import make_password

from apps.account.models import User, Role, Tenant
from apps.setting.models import Setting
from apps.setting.utils import AppSetting


def _make_user(username, password='Test1234!', **kwargs):
    defaults = dict(
        username=username,
        nickname=username,
        password_hash=make_password(password),
        type='default',
        is_supper=False,
        is_active=True,
        access_token=uuid.uuid4().hex,
        token_expired=int(time.time()) + 8 * 3600,
        last_ip='',
        wx_token='',
        tenant_id='admin',
    )
    defaults.update(kwargs)
    return User.objects.create(**defaults)


# ===========================================================================
# 发现 3：API 分页一致性
# ===========================================================================
class Finding3PaginationTest(TestCase):
    """发现 3：12 个列表端点无分页

    高风险端点：
    - UserView.get - 用户列表
    - RoleView.get - 角色列表
    - TenantView.get - 租户列表
    - UserView.get_tenant_choices - 租户选项
    - AuditLogExportView.get - 审计日志导出
    - FolderView._get_all_folders - 文件夹全量树

    低风险端点（配置/选项类，数据量通常小）：
    - EventTypeConfigView.get - 事件类型配置
    - CategoryTreeView.get - 规章分类树
    - CategoryListCreateView.get - 规章分类列表
    - RegulationAttachmentListView.get - 规章附件列表
    - ResponsibleUserListView.get (×2) - 可选责任人列表
    """

    def setUp(self):
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

        self.super_user = _make_user('super_pag', is_supper=True, tenant_id='admin')
        self.client = Client()

    def test_user_list_has_upper_limit(self):
        """用户列表有上限保护（500 条），防止无界查询"""
        # 创建 5 个用户
        for i in range(5):
            _make_user(f'pag_user_{i}', tenant_id='admin')

        resp = self.client.get(
            '/account/user/',
            HTTP_X_TOKEN=self.super_user.access_token,
        )
        body = resp.json()
        data = body.get('data', [])

        # 验证返回数据
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 6)  # 5 + super

        # 验证后端有上限保护（代码中 queryset[:500]）
        from apps.account.views import UserView
        import inspect
        source = inspect.getsource(UserView.get)
        self.assertIn(
            '[:500]', source,
            "UserView.get 应有 [:500] 上限保护，防止无界查询"
        )

    def test_role_list_has_upper_limit(self):
        """角色列表有上限保护（200 条），防止无界查询"""
        for i in range(5):
            Role.objects.create(
                name=f'pag_role_{i}',
                page_perms='',
                deploy_perms='',
                group_perms='',
                created_by=self.super_user,
            )

        resp = self.client.get(
            '/account/role/',
            HTTP_X_TOKEN=self.super_user.access_token,
        )
        body = resp.json()
        data = body.get('data', [])

        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 5)

        # 验证后端有上限保护
        from apps.account.views import RoleView
        import inspect
        source = inspect.getsource(RoleView.get)
        self.assertIn(
            '[:200]', source,
            "RoleView.get 应有 [:200] 上限保护，防止无界查询"
        )


# ===========================================================================
# 发现 4：前端表单校验缺失 - 后端兜底验证
# ===========================================================================
class Finding4FormValidationBackendCheckTest(TestCase):
    """发现 4：3 个前端表单缺 rules + validateFields

    受影响表单：
    - exec/fault/record/Form.js - 8 个必填字段
    - runlog/Form.js - 7 个必填字段
    - system/account/Form.js - 3 个必填字段

    antd 的 required 属性仅显示星号，不触发验证。
    必须用 rules={[{required: true}]} + form.validateFields() 才能拦截空值。

    此测试验证：前端漏校验时，后端 JsonParser 是否正确拦截空值。
    """

    def setUp(self):
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

        self.super_user = _make_user('super_form', is_supper=True, tenant_id='admin')
        self.client = Client()

    def test_fault_record_empty_fields_blocked_by_backend(self):
        """故障记录表单：空值提交被后端 JsonParser 拦截"""
        # 模拟前端未校验，直接提交空值
        resp = self.client.post(
            '/fault/faultrecord/',
            data=json.dumps({
                'system_name': '',
                'device_code': '',
                'fault_date': '',
                'handler': '',
                'recorder': '',
                'fault_level': '',
                'fault_phenomenon': '',
                'handling_process': '',
            }),
            content_type='application/json',
            HTTP_X_TOKEN=self.super_user.access_token,
        )
        body = resp.json()
        # 后端 JsonParser 的 required=True 字段空值应被拦截
        self.assertTrue(
            body.get('error'),
            "前端缺校验 + 后端未兜底 = 空值被存入数据库。"
            "后端应通过 JsonParser required 拦截空值，但返回了：{}".format(body)
        )

    def test_fault_record_missing_fields_blocked_by_backend(self):
        """故障记录表单：必填字段缺失被后端拦截"""
        resp = self.client.post(
            '/fault/faultrecord/',
            data=json.dumps({}),
            content_type='application/json',
            HTTP_X_TOKEN=self.super_user.access_token,
        )
        body = resp.json()
        self.assertTrue(
            body.get('error'),
            "后端应拦截缺失的必填字段，但返回了：{}".format(body)
        )

    def test_runlog_empty_fields_blocked_by_backend(self):
        """运行日志表单：空值提交被后端拦截"""
        resp = self.client.post(
            '/runlog/',
            data=json.dumps({
                'event_title': '',
                'event_type': '',
                'system_name': '',
                'detail_content': '',
            }),
            content_type='application/json',
            HTTP_X_TOKEN=self.super_user.access_token,
        )
        body = resp.json()
        self.assertTrue(
            body.get('error'),
            "前端缺校验 + 后端未兜底 = 空值被存入数据库。"
            "后端应通过 JsonParser required 拦截空值，但返回了：{}".format(body)
        )

    def test_account_empty_fields_blocked_by_backend(self):
        """用户创建表单：空值提交被后端拦截"""
        resp = self.client.post(
            '/account/user/',
            data=json.dumps({
                'username': '',
                'nickname': '',
                'password': '',
            }),
            content_type='application/json',
            HTTP_X_TOKEN=self.super_user.access_token,
        )
        body = resp.json()
        self.assertTrue(
            body.get('error'),
            "前端缺校验 + 后端未兜底 = 空值被存入数据库。"
            "后端应通过 JsonParser required 拦截空值，但返回了：{}".format(body)
        )

    def test_account_missing_fields_blocked_by_backend(self):
        """用户创建表单：必填字段缺失被后端拦截"""
        resp = self.client.post(
            '/account/user/',
            data=json.dumps({}),
            content_type='application/json',
            HTTP_X_TOKEN=self.super_user.access_token,
        )
        body = resp.json()
        self.assertTrue(
            body.get('error'),
            "后端应拦截缺失的必填字段，但返回了：{}".format(body)
        )
