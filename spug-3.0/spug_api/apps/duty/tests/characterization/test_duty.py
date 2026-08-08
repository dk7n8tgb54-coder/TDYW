# -*- coding: utf-8 -*-
"""值班日志模块特征测试

覆盖：
- CRUD 全生命周期
- 权限检查（view/add/edit/del）
- 租户隔离
- 软删除行为
- 幂等性检查
- reporter 自动填充
- 字段校验和边界
- 列表分页、排序
- 跨用户/跨租户访问
- 审计字段
- HTTP 200 + error 业务错误协议

已知缺陷（不修复生产代码，仅记录）：
- DUTY-001: edit 接口 UnboundLocalError: 'timezone' (views.py L134)
"""
import json
import time
import unittest
from datetime import timedelta
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.account.models import User, Role
from apps.duty.models import DutyRecord
from apps.utils.test_helpers import setup_test_env


# ============================================================
# 测试辅助
# ============================================================

def _make_user(username, is_supper=False, tenant_id='default', is_active=True):
    token = (username * 10)[:32]
    user = User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=is_active, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )
    return user


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


def _make_record(user, **kwargs):
    defaults = {
        'duty_person': '张三',
        'reporter': user.nickname or user.username,
        'department': '测试部门',
        'duty_date': timezone.now(),
        'duty_situation': '值班正常',
        'created_by': user,
        'tenant_id': user.tenant_id,
    }
    defaults.update(kwargs)
    return DutyRecord.objects.create(**defaults)


# ============================================================
# CRUD 基础测试
# ============================================================

@override_settings(MEDIA_ROOT='/tmp/test_media_duty')
class DutyCRUDTests(TestCase):
    """值班日志 CRUD 基础测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, [('duty', 'duty', ['view', 'add', 'edit', 'del'])])
        self.client = _make_client(self.user)
        self.url = '/duty/duty/'

    def _post(self, data):
        return self.client.post(self.url, data=json.dumps(data), content_type='application/json')

    def test_create_success(self):
        """创建值班日志成功"""
        resp = self._post({
            'duty_person': '张三',
            'department': '运维部',
            'duty_date': '2026-08-08 09:00',
            'duty_situation': '值班正常',
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        record = DutyRecord.objects.get(duty_person='张三', department='运维部')
        self.assertEqual(record.duty_situation, '值班正常')
        self.assertEqual(record.created_by, self.user)
        self.assertEqual(record.reporter, self.user.nickname)
        self.assertFalse(record.is_deleted)
        self.assertIsNone(record.deleted_at)

    def test_create_minimal_fields(self):
        """仅必填字段创建"""
        resp = self._post({
            'duty_person': '李四',
            'department': '安全部',
            'duty_date': '2026-08-08 10:00',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))
        record = DutyRecord.objects.get(duty_person='李四', department='安全部')
        self.assertEqual(record.duty_situation, '')

    def test_create_missing_duty_person(self):
        """缺少 duty_person"""
        resp = self._post({'department': '安全部', 'duty_date': '2026-08-08 10:00'})
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_department(self):
        """缺少 department"""
        resp = self._post({'duty_person': '李四', 'duty_date': '2026-08-08 10:00'})
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_duty_date(self):
        """缺少 duty_date"""
        resp = self._post({'duty_person': '李四', 'department': '安全部'})
        self.assertTrue(resp.json().get('error'))

    def test_create_reporter_not_from_client(self):
        """客户端传入 reporter 被忽略，自动填充当前用户"""
        resp = self._post({
            'duty_person': '赵六',
            'department': '运维部',
            'duty_date': '2026-08-08 09:00',
            'reporter': '假冒用户',
        })
        self.assertEqual(resp.status_code, 200)
        record = DutyRecord.objects.get(duty_person='赵六', department='运维部')
        self.assertEqual(record.reporter, self.user.nickname)

    @unittest.expectedFailure
    def test_edit_success(self):
        """编辑值班日志成功（DUTY-001: views.py L134 timezone UnboundLocalError）"""
        record = _make_record(self.user)
        resp = self._post({'id': record.id, 'duty_person': '王五', 'duty_situation': '更新后内容'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))
        record.refresh_from_db()
        self.assertEqual(record.duty_person, '王五')

    @unittest.expectedFailure
    def test_edit_partial_update(self):
        """部分更新（DUTY-001: 同上）"""
        record = _make_record(self.user, duty_person='原始人', duty_situation='原始内容')
        resp = self._post({'id': record.id, 'duty_situation': '新内容'})
        self.assertEqual(resp.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.duty_person, '原始人')
        self.assertEqual(record.duty_situation, '新内容')

    def test_edit_nonexistent_record(self):
        """编辑不存在的记录"""
        resp = self._post({'id': 99999, 'duty_person': '测试'})
        self.assertTrue(resp.json().get('error'))

    def test_delete_via_post_action(self):
        """POST action=delete 删除"""
        record = _make_record(self.user)
        resp = self._post({'id': record.id, 'action': 'delete'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))
        record = DutyRecord.objects.all_with_deleted().get(pk=record.pk)
        self.assertTrue(record.is_deleted)
        self.assertIsNotNone(record.deleted_at)

    def test_delete_via_delete_method(self):
        """DELETE 方法删除"""
        record = _make_record(self.user)
        resp = self.client.delete(f'{self.url}?id={record.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))
        record = DutyRecord.objects.all_with_deleted().get(pk=record.pk)
        self.assertTrue(record.is_deleted)

    def test_delete_nonexistent(self):
        """删除不存在的记录"""
        resp = self.client.delete(f'{self.url}?id=99999')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 权限测试
# ============================================================

class DutyPermissionTests(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.viewer = _make_user('viewer', tenant_id='t1')
        _grant_perms(self.viewer, [('duty', 'duty', ['view'])])
        self.c_viewer = _make_client(self.viewer)

        self.editor = _make_user('editor', tenant_id='t1')
        _grant_perms(self.editor, [('duty', 'duty', ['view', 'add'])])
        self.c_editor = _make_client(self.editor)

        self.noperm = _make_user('noperm', tenant_id='t1')
        self.c_noperm = _make_client(self.noperm)

        self.supper = _make_user('supper', is_supper=True, tenant_id='t1')
        self.c_supper = _make_client(self.supper)

    def test_view_with_permission(self):
        resp = self.c_viewer.get('/duty/duty/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))

    def test_view_without_permission(self):
        resp = self.c_noperm.get('/duty/duty/')
        self.assertTrue(resp.json().get('error'))

    def test_add_without_permission(self):
        resp = self.c_viewer.post('/duty/duty/', data=json.dumps({
            'duty_person': '张三', 'department': '运维部', 'duty_date': '2026-08-08 09:00',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_add_with_permission(self):
        resp = self.c_editor.post('/duty/duty/', data=json.dumps({
            'duty_person': '张三', 'department': '运维部', 'duty_date': '2026-08-08 09:00',
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))

    def test_supper_bypasses_permission(self):
        resp = self.c_supper.get('/duty/duty/')
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 租户隔离测试
# ============================================================

class DutyTenantIsolationTests(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.user_a = _make_user('user_a', tenant_id='tenant_a')
        _grant_perms(self.user_a, [('duty', 'duty', ['view', 'add', 'edit', 'del'])])
        self.c_a = _make_client(self.user_a)

        self.user_b = _make_user('user_b', tenant_id='tenant_b')
        _grant_perms(self.user_b, [('duty', 'duty', ['view', 'add', 'edit', 'del'])])
        self.c_b = _make_client(self.user_b)

        self.supper = _make_user('supper', is_supper=True, tenant_id='tenant_a')
        self.c_supper = _make_client(self.supper)

    def test_cross_tenant_list_isolation(self):
        record_a = _make_record(self.user_a, duty_person='A的人')
        record_b = _make_record(self.user_b, duty_person='B的人')
        resp = self.c_a.get('/duty/duty/')
        ids = [r['id'] for r in resp.json()['data']['records']]
        self.assertIn(record_a.id, ids)
        self.assertNotIn(record_b.id, ids)

    def test_cross_tenant_delete_blocked(self):
        record_b = _make_record(self.user_b, duty_person='B的人')
        resp = self.c_a.delete(f'/duty/duty/?id={record_b.id}')
        self.assertTrue(resp.json().get('error'))
        record_b = DutyRecord.objects.all_with_deleted().get(pk=record_b.pk)
        self.assertFalse(record_b.is_deleted)

    def test_supper_sees_all_tenants(self):
        record_a = _make_record(self.user_a, duty_person='A的人')
        record_b = _make_record(self.user_b, duty_person='B的人')
        resp = self.c_supper.get('/duty/duty/')
        ids = [r['id'] for r in resp.json()['data']['records']]
        self.assertIn(record_a.id, ids)
        self.assertIn(record_b.id, ids)

    def test_tenant_id_not_from_client(self):
        resp = self.c_a.post('/duty/duty/', data=json.dumps({
            'duty_person': '测试人', 'department': '运维部', 'duty_date': '2026-08-08 09:00',
            'tenant_id': 'tenant_b',
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        record = DutyRecord.objects.get(duty_person='测试人', department='运维部')
        self.assertEqual(record.tenant_id, 'tenant_a')


# ============================================================
# 软删除行为测试
# ============================================================

class DutySoftDeleteTests(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, [('duty', 'duty', ['view', 'add', 'edit', 'del'])])
        self.client = _make_client(self.user)

    def test_soft_delete_excludes_from_list(self):
        record = _make_record(self.user, duty_person='测试人')
        resp = self.client.get('/duty/duty/')
        self.assertIn(record.id, [r['id'] for r in resp.json()['data']['records']])
        self.client.delete(f'/duty/duty/?id={record.id}')
        resp = self.client.get('/duty/duty/')
        self.assertNotIn(record.id, [r['id'] for r in resp.json()['data']['records']])

    def test_soft_delete_preserves_db_record(self):
        record = _make_record(self.user)
        self.client.delete(f'/duty/duty/?id={record.id}')
        self.assertTrue(DutyRecord.objects.all_with_deleted().filter(pk=record.pk).exists())
        record = DutyRecord.objects.all_with_deleted().get(pk=record.pk)
        self.assertTrue(record.is_deleted)

    def test_double_delete(self):
        record = _make_record(self.user)
        self.client.delete(f'/duty/duty/?id={record.id}')
        resp = self.client.delete(f'/duty/duty/?id={record.id}')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 幂等性测试
# ============================================================

class DutyIdempotencyTests(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, [('duty', 'duty', ['view', 'add'])])
        self.client = _make_client(self.user)

    def test_duplicate_within_window_blocked(self):
        data = {'duty_person': '张三', 'department': '运维部', 'duty_date': '2026-08-08 09:00'}
        resp1 = self.client.post('/duty/duty/', data=json.dumps(data), content_type='application/json')
        self.assertFalse(resp1.json().get('error'))
        resp2 = self.client.post('/duty/duty/', data=json.dumps(data), content_type='application/json')
        self.assertTrue(resp2.json().get('error'))

    def test_different_person_allows(self):
        self.client.post('/duty/duty/', data=json.dumps({
            'duty_person': '张三', 'department': '运维部', 'duty_date': '2026-08-08 09:00',
        }), content_type='application/json')
        resp = self.client.post('/duty/duty/', data=json.dumps({
            'duty_person': '李四', 'department': '运维部', 'duty_date': '2026-08-08 09:00',
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 列表查询测试
# ============================================================

class DutyListQueryTests(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, [('duty', 'duty', ['view', 'add'])])
        self.client = _make_client(self.user)
        now = timezone.now()
        self.r1 = _make_record(self.user, duty_person='张三', department='运维部',
                                duty_situation='情况1', duty_date=now - timedelta(days=2))
        self.r2 = _make_record(self.user, duty_person='李四', department='安全部',
                                duty_situation='情况2', duty_date=now - timedelta(days=1))
        self.r3 = _make_record(self.user, duty_person='王五', department='运维部',
                                duty_situation='情况3', duty_date=now)

    def test_list_default_order(self):
        """默认按 duty_date 倒序"""
        resp = self.client.get('/duty/duty/')
        ids = [r['id'] for r in resp.json()['data']['records']]
        self.assertEqual(ids[0], self.r3.id)

    def test_list_pagination(self):
        """分页"""
        resp = self.client.get('/duty/duty/?page=1&page_size=2')
        body = resp.json()['data']
        self.assertEqual(len(body['records']), 2)
        self.assertEqual(body['total'], 3)

    def test_list_returns_duty_persons(self):
        """返回去重 duty_persons"""
        resp = self.client.get('/duty/duty/')
        persons = resp.json()['data']['duty_persons']
        self.assertIn('张三', persons)
        self.assertIn('李四', persons)

    def test_list_returns_departments(self):
        """返回去重 departments"""
        resp = self.client.get('/duty/duty/')
        depts = resp.json()['data']['departments']
        self.assertIn('运维部', depts)
        self.assertIn('安全部', depts)

    def test_list_no_keyword_search(self):
        """列表 API 无 keyword 搜索功能（返回全部记录）"""
        resp = self.client.get('/duty/duty/?keyword=张三')
        body = resp.json()['data']
        # keyword 参数被忽略，返回所有记录
        self.assertEqual(body['total'], 3)


# ============================================================
# 跨用户访问测试
# ============================================================

class DutyCrossUserTests(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.user1 = _make_user('user1', tenant_id='t1')
        _grant_perms(self.user1, [('duty', 'duty', ['view', 'add', 'edit', 'del'])])
        self.c1 = _make_client(self.user1)

        self.user2 = _make_user('user2', tenant_id='t1')
        _grant_perms(self.user2, [('duty', 'duty', ['view', 'add', 'edit', 'del'])])
        self.c2 = _make_client(self.user2)

    def test_same_tenant_user_can_view_others(self):
        record = _make_record(self.user1, duty_person='user1的记录')
        resp = self.c2.get('/duty/duty/')
        self.assertIn(record.id, [r['id'] for r in resp.json()['data']['records']])

    def test_same_tenant_user_can_delete_others(self):
        record = _make_record(self.user1, duty_person='原始')
        resp = self.c2.delete(f'/duty/duty/?id={record.id}')
        self.assertFalse(resp.json().get('error'))
        record = DutyRecord.objects.all_with_deleted().get(pk=record.pk)
        self.assertTrue(record.is_deleted)


# ============================================================
# 字段边界测试
# ============================================================

class DutyFieldBoundaryTests(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, [('duty', 'duty', ['view', 'add'])])
        self.client = _make_client(self.user)

    def _post(self, data):
        return self.client.post('/duty/duty/', data=json.dumps(data), content_type='application/json')

    def test_empty_duty_situation(self):
        resp = self._post({
            'duty_person': '张三', 'department': '运维部',
            'duty_date': '2026-08-08 09:00', 'duty_situation': '',
        })
        self.assertFalse(resp.json().get('error'))
        record = DutyRecord.objects.get(duty_person='张三', department='运维部')
        self.assertEqual(record.duty_situation, '')

    def test_past_date_allowed(self):
        """允许补录历史日志"""
        resp = self._post({
            'duty_person': '张三', 'department': '运维部', 'duty_date': '2020-01-01 09:00',
        })
        self.assertFalse(resp.json().get('error'))

    def test_future_date_allowed(self):
        """允许创建未来日期的日志"""
        resp = self._post({
            'duty_person': '张三', 'department': '运维部', 'duty_date': '2030-01-01 09:00',
        })
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 审计字段测试
# ============================================================

class DutyAuditFieldTests(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, [('duty', 'duty', ['view', 'add', 'del'])])
        self.client = _make_client(self.user)

    def test_created_by_set_on_create(self):
        self.client.post('/duty/duty/', data=json.dumps({
            'duty_person': '张三', 'department': '运维部', 'duty_date': '2026-08-08 09:00',
        }), content_type='application/json')
        record = DutyRecord.objects.get(duty_person='张三', department='运维部')
        self.assertEqual(record.created_by, self.user)

    def test_created_at_set_on_create(self):
        self.client.post('/duty/duty/', data=json.dumps({
            'duty_person': '李四', 'department': '运维部', 'duty_date': '2026-08-08 09:00',
        }), content_type='application/json')
        record = DutyRecord.objects.get(duty_person='李四', department='运维部')
        self.assertIsNotNone(record.created_at)

    @unittest.expectedFailure
    def test_updated_at_set_on_edit(self):
        """DUTY-001: edit 接口 timezone UnboundLocalError"""
        record = _make_record(self.user)
        self.client.post('/duty/duty/', data=json.dumps({
            'id': record.id, 'duty_situation': '更新',
        }), content_type='application/json')
        record.refresh_from_db()
        self.assertIsNotNone(record.updated_at)
