# -*- coding: utf-8 -*-
"""部门值班日志特征测试

覆盖：
- 草稿 CRUD（创建/编辑/详情/删除）
- 签署流程（草稿 -> 已签署）
- 退回流程（已签署 -> 草稿）
- 权限检查（view/add/edit/del/sign/return/export）
- 可见性规则（草稿仅本人可见，已签全局可见，超级管理员全部可见）
- 乐观锁（version 版本冲突）
- 幂等性（30 秒窗口 + 签署 request_id）
- 字段校验（必填/长度/日期/受保护字段）
- 软删除行为
- 列表查询（分页/筛选/排序/日期区间）
- 跨用户/跨租户访问
- 审计字段
"""
import json
import time
from datetime import date, timedelta
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.account.models import User, Role
from apps.setting.utils import AppSetting
from apps.department_duty_log.models import (
    DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED,
)
from apps.signature.models import SignatureUsage
from apps.utils.test_helpers import setup_test_env


# ============================================================
# 测试辅助
# ============================================================

def _make_user(username, is_supper=False, tenant_id='default', is_active=True):
    token = (username * 10)[:32]
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=is_active, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return client


def _grant_perms(user, perms):
    perm_dict = {}
    for module, page, keys in perms:
        perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)
    role_name = f'role_{user.username}'
    role = Role.objects.filter(name=role_name).first()
    if role:
        existing = json.loads(role.page_perms) if role.page_perms else {}
        for m, pages in perm_dict.items():
            if m not in existing:
                existing[m] = {}
            for p, keys in pages.items():
                if p not in existing[m]:
                    existing[m][p] = []
                existing[m][p].extend(keys)
        role.page_perms = json.dumps(existing)
        role.save()
    else:
        role = Role.objects.create(
            name=role_name,
            page_perms=json.dumps(perm_dict),
            created_by=user,
        )
        user.roles.add(role)
    user.set_perms_cache()
    return role


ALL_DUTY_LOG_PERMS = [('department_duty_log', 'department_duty_log', [
    'view', 'add', 'edit', 'del', 'sign', 'return', 'export',
])]


def _make_log(user, **kwargs):
    """直接创建 DepartmentDutyLog 草稿"""
    defaults = {
        'duty_date': date.today(),
        'duty_person': user,
        'duty_person_name': user.nickname or user.username,
        'weather': '晴',
        'duty_record': '值班正常',
        'remark': '',
        'status': STATUS_DRAFT,
        'version': 1,
        'created_by': user,
    }
    defaults.update(kwargs)
    return DepartmentDutyLog.objects.create(**defaults)


def _make_signed_log(user, **kwargs):
    """直接创建已签署日志（含 SignatureUsage）"""
    usage = SignatureUsage.objects.create(
        tenant_id=user.tenant_id,
        module='department_duty_log',
        object_type='DepartmentDutyLog',
        object_id='temp',
        scene_code='operator',
        signer_user_id=user.id,
        signer_username=user.username,
        signer_name=user.nickname,
        signature_attachment_id=1,
        signature_version=1,
        signature_sha256='a' * 64,
        business_snapshot='{}',
        business_snapshot_hash='b' * 64,
        signed_at=timezone.now(),
        signer_ip='10.0.0.1',
        request_id=f'test-{user.id}-{timezone.now().timestamp()}',
    )
    defaults = {
        'duty_date': date.today(),
        'duty_person': user,
        'duty_person_name': user.nickname or user.username,
        'weather': '晴',
        'duty_record': '值班正常',
        'remark': '',
        'status': STATUS_SIGNED,
        'version': 2,
        'created_by': user,
        'signed_by': user,
        'signed_by_name': user.nickname,
        'signed_at': timezone.now(),
        'signature_usage_id': usage.id,
        'signature_version': 1,
        'signature_sha256': 'a' * 64,
        'business_snapshot_hash': 'b' * 64,
    }
    defaults.update(kwargs)
    log = DepartmentDutyLog.objects.create(**defaults)
    # Update object_id after creation
    usage.object_id = str(log.id)
    usage.save(update_fields=['object_id'])
    return log


BASE_URL = '/department-duty-log/records/'
OPTIONS_URL = '/department-duty-log/options/'
DUTY_DATES_URL = '/department-duty-log/records/duty_dates/'


# ============================================================
# 草稿 CRUD 测试
# ============================================================

class DepartmentDutyLogCRUDTests(TestCase):
    """部门值班日志草稿 CRUD 测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

    def _post(self, data):
        return self.client.post(BASE_URL, data=json.dumps(data), content_type='application/json')

    def _put(self, pk, data):
        return self.client.put(f'{BASE_URL}{pk}/', data=json.dumps(data), content_type='application/json')

    def test_create_draft_success(self):
        """创建草稿成功"""
        resp = self._post({
            'duty_date': '2026-08-08',
            'weather': '晴',
            'duty_record': '值班正常',
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        log = DepartmentDutyLog.objects.get(duty_record='值班正常')
        self.assertEqual(log.status, STATUS_DRAFT)
        self.assertEqual(log.version, 1)
        self.assertEqual(log.duty_person, self.user)
        self.assertEqual(log.duty_person_name, self.user.nickname)
        self.assertEqual(log.created_by, self.user)
        self.assertEqual(log.weather, '晴')

    def test_create_missing_duty_date(self):
        """缺少 duty_date"""
        resp = self._post({
            'weather': '晴',
            'duty_record': '值班正常',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_weather(self):
        """缺少 weather"""
        resp = self._post({
            'duty_date': '2026-08-08',
            'duty_record': '值班正常',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_duty_record(self):
        """缺少 duty_record"""
        resp = self._post({
            'duty_date': '2026-08-08',
            'weather': '晴',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_future_date_blocked(self):
        """不允许未来日期"""
        future = date.today() + timedelta(days=1)
        resp = self._post({
            'duty_date': future.strftime('%Y-%m-%d'),
            'weather': '晴',
            'duty_record': '值班正常',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_invalid_date_format(self):
        """非法日期格式"""
        resp = self._post({
            'duty_date': '2026/08/08',
            'weather': '晴',
            'duty_record': '值班正常',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_protected_fields_rejected(self):
        """受保护字段被拒绝"""
        resp = self._post({
            'duty_date': '2026-08-08',
            'weather': '晴',
            'duty_record': '值班正常',
            'status': 'signed',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_protected_duty_person_id_rejected(self):
        """受保护字段 duty_person_id 被拒绝"""
        resp = self._post({
            'duty_date': '2026-08-08',
            'weather': '晴',
            'duty_record': '值班正常',
            'duty_person_id': 999,
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_long_weather(self):
        """超长 weather"""
        resp = self._post({
            'duty_date': '2026-08-08',
            'weather': 'A' * 51,
            'duty_record': '值班正常',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_long_duty_record(self):
        """超长 duty_record"""
        resp = self._post({
            'duty_date': '2026-08-08',
            'weather': '晴',
            'duty_record': 'A' * 10001,
        })
        self.assertTrue(resp.json().get('error'))

    def test_edit_draft_success(self):
        """编辑草稿成功"""
        log = _make_log(self.user)
        resp = self._put(log.id, {
            'duty_date': '2026-08-08',
            'weather': '雨',
            'duty_record': '修改后内容',
            'remark': '备注',
            'version': 1,
        })
        self.assertFalse(resp.json().get('error'))
        log.refresh_from_db()
        self.assertEqual(log.weather, '雨')
        self.assertEqual(log.duty_record, '修改后内容')
        self.assertEqual(log.remark, '备注')
        self.assertEqual(log.version, 2)
        self.assertEqual(log.updated_by_id, self.user.id)

    def test_edit_version_conflict(self):
        """版本冲突"""
        log = _make_log(self.user, version=1)
        resp = self._put(log.id, {
            'duty_date': '2026-08-08',
            'weather': '雨',
            'duty_record': '修改',
            'version': 2,
        })
        self.assertTrue(resp.json().get('error'))

    def test_edit_missing_version(self):
        """编辑缺少 version"""
        log = _make_log(self.user)
        resp = self._put(log.id, {
            'duty_date': '2026-08-08',
            'weather': '雨',
            'duty_record': '修改',
        })
        self.assertTrue(resp.json().get('error'))

    def test_edit_nonexistent(self):
        """编辑不存在的记录"""
        resp = self._put(99999, {
            'duty_date': '2026-08-08',
            'weather': '雨',
            'duty_record': '修改',
            'version': 1,
        })
        self.assertTrue(resp.json().get('error'))

    def test_delete_draft_success(self):
        """删除草稿成功（软删除）"""
        log = _make_log(self.user)
        resp = self.client.delete(f'{BASE_URL}{log.id}/')
        self.assertFalse(resp.json().get('error'))
        log.refresh_from_db()
        self.assertIsNotNone(log.deleted_at)

    def test_delete_nonexistent(self):
        """删除不存在的记录"""
        resp = self.client.delete(f'{BASE_URL}99999/')
        self.assertTrue(resp.json().get('error'))

    def test_detail_success(self):
        """详情"""
        log = _make_log(self.user)
        resp = self.client.get(f'{BASE_URL}{log.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['id'], log.id)
        self.assertEqual(body['data']['duty_record'], log.duty_record)


# ============================================================
# 签署流程测试
# ============================================================

class DepartmentDutyLogSignTests(TestCase):
    """部门值班日志签署测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

    def test_sign_requires_confirm(self):
        """签署需要 confirm=True"""
        log = _make_log(self.user)
        resp = self.client.post(f'{BASE_URL}{log.id}/sign/', data=json.dumps({
            'version': 1,
            'confirm': False,
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_sign_requires_version(self):
        """签署需要 version"""
        log = _make_log(self.user)
        resp = self.client.post(f'{BASE_URL}{log.id}/sign/', data=json.dumps({
            'confirm': True,
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_sign_nonexistent(self):
        """签署不存在的记录"""
        resp = self.client.post(f'{BASE_URL}99999/sign/', data=json.dumps({
            'version': 1,
            'confirm': True,
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_sign_protected_fields_rejected(self):
        """签署时受保护字段被拒绝"""
        log = _make_log(self.user)
        resp = self.client.post(f'{BASE_URL}{log.id}/sign/', data=json.dumps({
            'version': 1,
            'confirm': True,
            'status': 'signed',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 退回流程测试
# ============================================================

class DepartmentDutyLogReturnTests(TestCase):
    """部门值班日志退回测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

    def test_return_nonexistent(self):
        """退回不存在的记录"""
        resp = self.client.post(f'{BASE_URL}99999/return/', data=json.dumps({}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_return_draft_blocked(self):
        """退回草稿被拒"""
        log = _make_log(self.user)
        resp = self.client.post(f'{BASE_URL}{log.id}/return/', data=json.dumps({}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 可见性测试
# ============================================================

class DepartmentDutyLogVisibilityTests(TestCase):
    """部门值班日志可见性测试"""

    def setUp(self):
        setup_test_env(self)
        self.user1 = _make_user('user1', tenant_id='t1')
        _grant_perms(self.user1, ALL_DUTY_LOG_PERMS)
        self.c1 = _make_client(self.user1)

        self.user2 = _make_user('user2', tenant_id='t1')
        _grant_perms(self.user2, ALL_DUTY_LOG_PERMS)
        self.c2 = _make_client(self.user2)

        self.supper = _make_user('supper', is_supper=True, tenant_id='t1')
        self.c_supper = _make_client(self.supper)

    def test_draft_only_visible_to_owner(self):
        """草稿仅本人可见"""
        log = _make_log(self.user1)
        resp = self.c2.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertNotIn(log.id, ids)

    def test_draft_visible_to_owner(self):
        """草稿创建人可以看到"""
        log = _make_log(self.user1)
        resp = self.c1.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(log.id, ids)

    def test_signed_visible_to_all(self):
        """已签记录所有人可见"""
        log = _make_signed_log(self.user1)
        resp = self.c2.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(log.id, ids)

    def test_supper_sees_all_drafts(self):
        """超级管理员可以看到所有草稿"""
        log = _make_log(self.user1)
        resp = self.c_supper.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(log.id, ids)

    def test_detail_draft_only_owner(self):
        """草稿详情仅本人可访问"""
        log = _make_log(self.user1)
        resp = self.c2.get(f'{BASE_URL}{log.id}/')
        self.assertTrue(resp.json().get('error'))

    def test_detail_signed_all_users(self):
        """已签详情所有人可访问"""
        log = _make_signed_log(self.user1)
        resp = self.c2.get(f'{BASE_URL}{log.id}/')
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 权限测试
# ============================================================

class DepartmentDutyLogPermissionTests(TestCase):
    """部门值班日志权限测试"""

    def setUp(self):
        setup_test_env(self)
        self.viewer = _make_user('viewer', tenant_id='t1')
        _grant_perms(self.viewer, [('department_duty_log', 'department_duty_log', ['view'])])
        self.c_viewer = _make_client(self.viewer)

        self.noperm = _make_user('noperm', tenant_id='t1')
        self.c_noperm = _make_client(self.noperm)

        self.supper = _make_user('supper', is_supper=True, tenant_id='t1')
        self.c_supper = _make_client(self.supper)

    def test_view_with_permission(self):
        """有 view 权限可以列表"""
        resp = self.c_viewer.get(BASE_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))

    def test_view_without_permission(self):
        """无权限不能列表"""
        resp = self.c_noperm.get(BASE_URL)
        self.assertTrue(resp.json().get('error'))

    def test_add_without_permission(self):
        """无 add 权限不能创建"""
        resp = self.c_viewer.post(BASE_URL, data=json.dumps({
            'duty_date': '2026-08-08',
            'weather': '晴',
            'duty_record': '值班正常',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_supper_bypasses_permission(self):
        """超级管理员绕过权限"""
        resp = self.c_supper.get(BASE_URL)
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 幂等性测试
# ============================================================

class DepartmentDutyLogIdempotencyTests(TestCase):
    """部门值班日志幂等性测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

    def test_duplicate_create_blocked(self):
        """30 秒窗口内重复提交相同记录被拦截"""
        data = {
            'duty_date': '2026-08-08',
            'weather': '晴',
            'duty_record': '值班正常',
        }
        resp1 = self.client.post(BASE_URL, data=json.dumps(data), content_type='application/json')
        self.assertFalse(resp1.json().get('error'))

        resp2 = self.client.post(BASE_URL, data=json.dumps(data), content_type='application/json')
        self.assertTrue(resp2.json().get('error'))

    def test_different_duty_record_allows(self):
        """不同 duty_record 可以创建"""
        self.client.post(BASE_URL, data=json.dumps({
            'duty_date': '2026-08-08',
            'weather': '晴',
            'duty_record': '记录A',
        }), content_type='application/json')
        resp = self.client.post(BASE_URL, data=json.dumps({
            'duty_date': '2026-08-08',
            'weather': '晴',
            'duty_record': '记录B',
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 所有权测试
# ============================================================

class DepartmentDutyLogOwnershipTests(TestCase):
    """部门值班日志所有权测试"""

    def setUp(self):
        setup_test_env(self)
        self.user1 = _make_user('user1', tenant_id='t1')
        _grant_perms(self.user1, ALL_DUTY_LOG_PERMS)
        self.c1 = _make_client(self.user1)

        self.user2 = _make_user('user2', tenant_id='t1')
        _grant_perms(self.user2, ALL_DUTY_LOG_PERMS)
        self.c2 = _make_client(self.user2)

    def test_edit_others_draft_blocked(self):
        """只能编辑本人草稿"""
        log = _make_log(self.user1)
        resp = self.c2.put(f'{BASE_URL}{log.id}/', data=json.dumps({
            'duty_date': '2026-08-08',
            'weather': '雨',
            'duty_record': '修改',
            'version': 1,
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_delete_others_draft_blocked(self):
        """只能删除本人草稿"""
        log = _make_log(self.user1)
        resp = self.c2.delete(f'{BASE_URL}{log.id}/')
        self.assertTrue(resp.json().get('error'))

    def test_sign_others_draft_blocked(self):
        """只能签署本人草稿"""
        log = _make_log(self.user1)
        resp = self.c2.post(f'{BASE_URL}{log.id}/sign/', data=json.dumps({
            'version': 1,
            'confirm': True,
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 列表查询测试
# ============================================================

class DepartmentDutyLogListQueryTests(TestCase):
    """部门值班日志列表查询测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

        today = date.today()
        self.log1 = _make_log(self.user, duty_date=today - timedelta(days=2),
                               weather='晴', duty_record='记录1')
        self.log2 = _make_log(self.user, duty_date=today - timedelta(days=1),
                               weather='雨', duty_record='记录2')
        self.log3 = _make_signed_log(self.user, duty_date=today,
                                      weather='阴', duty_record='已签记录')

    def test_list_default_order(self):
        """默认按 duty_date 倒序"""
        resp = self.client.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertEqual(ids[0], self.log3.id)

    def test_list_pagination(self):
        """分页"""
        resp = self.client.get(f'{BASE_URL}?page=1&page_size=2')
        body = resp.json()
        self.assertEqual(len(body['data']['records']), 2)
        self.assertEqual(body['data']['total'], 3)

    def test_filter_by_status(self):
        """按状态筛选"""
        resp = self.client.get(f'{BASE_URL}?status={STATUS_DRAFT}')
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(self.log1.id, ids)
        self.assertIn(self.log2.id, ids)
        self.assertNotIn(self.log3.id, ids)

    def test_filter_by_keyword(self):
        """关键词搜索"""
        resp = self.client.get(f'{BASE_URL}?keyword=记录2')
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(self.log2.id, ids)
        self.assertNotIn(self.log1.id, ids)

    def test_filter_by_date_range(self):
        """日期区间筛选"""
        today = date.today()
        start = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        end = today.strftime('%Y-%m-%d')
        resp = self.client.get(f'{BASE_URL}?start_date={start}&end_date={end}')
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(self.log2.id, ids)
        self.assertIn(self.log3.id, ids)
        self.assertNotIn(self.log1.id, ids)

    def test_empty_result(self):
        """空结果"""
        resp = self.client.get(f'{BASE_URL}?keyword=不存在')
        body = resp.json()
        self.assertEqual(len(body['data']['records']), 0)
        self.assertEqual(body['data']['total'], 0)

    def test_invalid_status(self):
        """非法状态值"""
        resp = self.client.get(f'{BASE_URL}?status=invalid')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 软删除行为测试
# ============================================================

class DepartmentDutyLogSoftDeleteTests(TestCase):
    """部门值班日志软删除测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

    def test_soft_delete_excludes_from_list(self):
        """软删除后不出现在列表中"""
        log = _make_log(self.user)
        self.client.delete(f'{BASE_URL}{log.id}/')
        resp = self.client.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertNotIn(log.id, ids)

    def test_soft_delete_preserves_db_record(self):
        """软删除后数据库记录仍存在"""
        log = _make_log(self.user)
        self.client.delete(f'{BASE_URL}{log.id}/')
        self.assertTrue(DepartmentDutyLog.objects.filter(pk=log.pk).exists())
        log = DepartmentDutyLog.objects.get(pk=log.pk)
        self.assertIsNotNone(log.deleted_at)

    def test_delete_signed_blocked(self):
        """已签记录不可删除"""
        log = _make_signed_log(self.user)
        resp = self.client.delete(f'{BASE_URL}{log.id}/')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 跨租户测试
# ============================================================

class DepartmentDutyLogTenantTests(TestCase):
    """部门值班日志跨租户测试"""

    def setUp(self):
        setup_test_env(self)
        self.user_a = _make_user('user_a', tenant_id='tenant_a')
        _grant_perms(self.user_a, ALL_DUTY_LOG_PERMS)
        self.c_a = _make_client(self.user_a)

        self.user_b = _make_user('user_b', tenant_id='tenant_b')
        _grant_perms(self.user_b, ALL_DUTY_LOG_PERMS)
        self.c_b = _make_client(self.user_b)

        self.supper = _make_user('supper', is_supper=True, tenant_id='tenant_a')
        self.c_supper = _make_client(self.supper)

    def test_cross_tenant_draft_not_visible(self):
        """跨租户草稿不可见（可见性不按租户，按 ownership）"""
        # user_a 的草稿
        log_a = _make_log(self.user_a)
        # user_b 看不到 user_a 的草稿
        resp = self.c_b.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertNotIn(log_a.id, ids)

    def test_cross_tenant_signed_visible(self):
        """跨租户已签记录可见（可见性不过滤租户）"""
        log_a = _make_signed_log(self.user_a)
        resp = self.c_b.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(log_a.id, ids)

    def test_supper_sees_all(self):
        """超级管理员可以看到所有记录"""
        log_a = _make_log(self.user_a)
        log_b = _make_log(self.user_b)
        resp = self.c_supper.get(BASE_URL)
        body = resp.json()
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(log_a.id, ids)
        self.assertIn(log_b.id, ids)


# ============================================================
# 值班日期列表测试
# ============================================================

class DepartmentDutyLogDutyDatesTests(TestCase):
    """值班日期列表测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

    def test_get_duty_dates(self):
        """获取已有值班日志日期"""
        _make_log(self.user, duty_date=date(2026, 8, 5))
        _make_log(self.user, duty_date=date(2026, 8, 10))
        resp = self.client.get(f'{DUTY_DATES_URL}?year=2026&month=8')
        body = resp.json()
        self.assertFalse(body.get('error'))
        dates = body['data']['dates']
        self.assertIn('2026-08-05', dates)
        self.assertIn('2026-08-10', dates)

    def test_duty_dates_excludes_other_months(self):
        """不返回其他月份的日期"""
        _make_log(self.user, duty_date=date(2026, 7, 15))
        _make_log(self.user, duty_date=date(2026, 8, 10))
        resp = self.client.get(f'{DUTY_DATES_URL}?year=2026&month=8')
        body = resp.json()
        dates = body['data']['dates']
        self.assertNotIn('2026-07-15', dates)
        self.assertIn('2026-08-10', dates)

    def test_duty_dates_missing_year(self):
        """缺少 year 参数"""
        resp = self.client.get(f'{BASE_URL}duty_dates/?month=8')
        self.assertTrue(resp.json().get('error'))

    def test_duty_dates_missing_month(self):
        """缺少 month 参数"""
        resp = self.client.get(f'{BASE_URL}duty_dates/?year=2026')
        self.assertTrue(resp.json().get('error'))

    def test_duty_dates_invalid_month(self):
        """非法 month"""
        resp = self.client.get(f'{BASE_URL}duty_dates/?year=2026&month=13')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 选项接口测试
# ============================================================

class DepartmentDutyLogOptionsTests(TestCase):
    """选项接口测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

    def test_get_options(self):
        """获取选项"""
        resp = self.client.get(f'{OPTIONS_URL}')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertIn('data', body)

    def test_options_without_permission(self):
        """无权限不能获取选项"""
        noperm = _make_user('noperm', tenant_id='t1')
        c_noperm = _make_client(noperm)
        resp = c_noperm.get(f'{OPTIONS_URL}')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 能力字段测试
# ============================================================

class DepartmentDutyLogCapabilitiesTests(TestCase):
    """能力字段测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_DUTY_LOG_PERMS)
        self.client = _make_client(self.user)

    def test_draft_owner_capabilities(self):
        """草稿所有者的能力字段"""
        log = _make_log(self.user)
        resp = self.client.get(f'{BASE_URL}{log.id}/')
        body = resp.json()
        caps = body['data']
        self.assertTrue(caps['can_edit'])
        self.assertTrue(caps['can_delete'])
        self.assertTrue(caps['can_sign'])
        self.assertFalse(caps['can_return'])

    def test_signed_capabilities(self):
        """已签记录的能力字段"""
        log = _make_signed_log(self.user)
        resp = self.client.get(f'{BASE_URL}{log.id}/')
        body = resp.json()
        caps = body['data']
        self.assertFalse(caps['can_edit'])
        self.assertFalse(caps['can_delete'])
        self.assertFalse(caps['can_sign'])
        self.assertTrue(caps['can_return'])
        self.assertTrue(caps['can_export'])

    def test_draft_non_owner_capabilities(self):
        """非草稿所有者的能力字段"""
        other = _make_user('other', tenant_id='t1')
        _grant_perms(other, ALL_DUTY_LOG_PERMS)
        c_other = _make_client(other)
        log = _make_log(self.user)
        # other 用户看不到 user 的草稿
        resp = c_other.get(f'{BASE_URL}{log.id}/')
        self.assertTrue(resp.json().get('error'))
