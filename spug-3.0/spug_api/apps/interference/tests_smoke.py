# -*- coding: utf-8 -*-
"""
干扰记录模块测试
覆盖：列表查询/权限校验/创建/编辑/删除/数据校验
（统计能力已迁移至数据分析-干扰分析，见 apps/data_analysis/tests.py）
"""
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.core.cache import cache

from apps.interference.models import Interference


def _make_user(username, perms=None, is_supper=False):
    """创建测试用户并设置权限缓存（version=0 匹配无角色用户的版本校验）"""
    import time
    from apps.account.models import User
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
        user.set_perms_cache(set(perms or []), version=0)
    return user


def _make_client(user):
    """创建带认证头的测试客户端"""
    from django.test import Client
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


VIEW_PERMS = ['interference.interference.view']
# 注意：interference.statistics.view 不再列入本模块的编辑权限集合。
# 旧的 /interference/statistics/ 统计接口已删除，统计能力由
# 数据分析 - 干扰分析（/api/data-analysis/interference/）提供。
EDIT_PERMS = ['interference.interference.view', 'interference.interference.add',
              'interference.interference.edit', 'interference.interference.del']

VALID_DATA = {
    'frequency': '108.5 MHz',
    'report_dept': '技术部',
    'datetime': '2026-07-19 10:00:00',
    'coordinates': 'N39.9,E116.4',
    'interference_type': '信号干扰',
    'phenomenon': '测试现象描述',
    'is_reported': '否',
}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class InterferenceViewTest(TestCase):
    """干扰记录 CRUD 测试"""

    def setUp(self):
        cache.clear()
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.viewer = _make_user('viewer', VIEW_PERMS)
        self.editor = _make_user('editor', EDIT_PERMS)
        self.noperm = _make_user('noperm', [])
        self.viewer_client = _make_client(self.viewer)
        self.editor_client = _make_client(self.editor)
        self.noperm_client = _make_client(self.noperm)

    def tearDown(self):
        cache.clear()

    # ---- 列表查询 ----

    def test_viewer_can_list(self):
        """有 view 权限的用户能查列表"""
        resp = self.viewer_client.get('/interference/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertIn('records', body['data'])
        self.assertIn('total', body['data'])

    def test_no_perm_denied(self):
        """无权限用户被拒"""
        resp = self.noperm_client.get('/interference/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_list_with_filter(self):
        """列表筛选（frequency 模糊匹配）"""
        # 先创建一条记录
        self.editor_client.post('/interference/', data=VALID_DATA, content_type='application/json')
        resp = self.viewer_client.get('/interference/?frequency=108.5')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['data']['total'], 1)

    # ---- 创建 ----

    def test_create_success(self):
        """有 add 权限的用户能创建"""
        resp = self.editor_client.post('/interference/', data=VALID_DATA, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'), body.get('error', ''))
        self.assertEqual(Interference.objects.count(), 1)
        record = Interference.objects.first()
        self.assertEqual(record.frequency, '108.5 MHz')
        self.assertEqual(record.status, 'draft')

    def test_viewer_cannot_create(self):
        """只有 view 权限的用户不能创建"""
        resp = self.viewer_client.post('/interference/', data=VALID_DATA, content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_create_missing_required_field(self):
        """缺必填字段返回错误"""
        data = VALID_DATA.copy()
        del data['frequency']
        resp = self.editor_client.post('/interference/', data=data, content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'))
        self.assertIn('频率', body['error'])

    def test_create_invalid_datetime(self):
        """日期格式校验"""
        data = VALID_DATA.copy()
        data['datetime'] = '2026/07/19'
        resp = self.editor_client.post('/interference/', data=data, content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'))
        self.assertIn('YYYY-MM-DD', body['error'])

    # ---- 编辑 ----

    def test_edit_success(self):
        """编辑已存在记录（只传部分字段，验证部分更新不被全覆盖）"""
        # 先创建
        self.editor_client.post('/interference/', data=VALID_DATA, content_type='application/json')
        record = Interference.objects.first()
        # 编辑：只传 id + frequency，不传其他字段
        resp = self.editor_client.post(
            '/interference/',
            data={'id': record.id, 'frequency': '99.9 MHz'},
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body.get('error', ''))
        record.refresh_from_db()
        self.assertEqual(record.frequency, '99.9 MHz')
        # 其他字段不应被覆盖为 None
        self.assertEqual(record.report_dept, '技术部')
        self.assertEqual(record.interference_type, '信号干扰')
        self.assertEqual(record.phenomenon, '测试现象描述')

    # ---- 删除 ----

    def test_delete_draft_success(self):
        """删除 draft 状态记录"""
        self.editor_client.post('/interference/', data=VALID_DATA, content_type='application/json')
        record = Interference.objects.first()
        resp = self.editor_client.delete(f'/interference/?id={record.id}')
        body = resp.json()
        self.assertFalse(body.get('error'), body.get('error', ''))
        self.assertEqual(Interference.objects.count(), 0)

    def test_delete_missing_id(self):
        """删除缺 id 参数"""
        resp = self.editor_client.delete('/interference/')
        body = resp.json()
        self.assertTrue(body.get('error'))

    # ---- 统计 ----
    # 干扰统计 API 已移除（由 数据分析-干扰分析 /api/data-analysis/interference/ 取代）


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class InterferenceTenantIsolationTest(TestCase):
    """租户隔离测试"""

    def setUp(self):
        cache.clear()
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        from apps.account.models import Tenant
        self.tenant_a = Tenant.objects.create(name='租户A', id='tenant-a')
        self.tenant_b = Tenant.objects.create(name='租户B', id='tenant-b')
        self.user_a = _make_user('userA', EDIT_PERMS)
        self.user_a.tenant_id = 'tenant-a'
        self.user_a.save()
        self.user_b = _make_user('userB', EDIT_PERMS)
        self.user_b.tenant_id = 'tenant-b'
        self.user_b.save()
        self.client_a = _make_client(self.user_a)
        self.client_b = _make_client(self.user_b)

    def tearDown(self):
        cache.clear()

    def test_tenant_isolation(self):
        """租户 A 的数据租户 B 看不到"""
        # 租户 A 创建记录
        resp = self.client_a.post('/interference/', data=VALID_DATA, content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.assertEqual(Interference.objects.count(), 1)

        # 租户 B 查列表看不到
        resp = self.client_b.get('/interference/')
        body = resp.json()
        self.assertEqual(body['data']['total'], 0)

    def test_cross_tenant_edit_rejected(self):
        """租户 B 不能编辑租户 A 的记录"""
        self.client_a.post('/interference/', data=VALID_DATA, content_type='application/json')
        record = Interference.objects.first()
        resp = self.client_b.post(
            '/interference/',
            data={'id': record.id, 'frequency': '999 MHz'},
            content_type='application/json',
        )
        self.assertTrue(resp.json().get('error'))
        # 记录未被修改
        record.refresh_from_db()
        self.assertEqual(record.frequency, '108.5 MHz')

    def test_cross_tenant_delete_rejected(self):
        """租户 B 不能删除租户 A 的记录"""
        self.client_a.post('/interference/', data=VALID_DATA, content_type='application/json')
        record = Interference.objects.first()
        resp = self.client_b.delete(f'/interference/?id={record.id}')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(Interference.objects.count(), 1)
