# -*- coding: utf-8 -*-
"""跨日事项跟踪（RunLog）特征测试

覆盖：
- CRUD 全生命周期（事件 + 动态）
- 状态流转（in_progress -> resolved -> verified -> closed -> voided）
- 非法状态跳转
- 权限检查
- 租户隔离
- 软删除 + 级联删除
- 幂等性检查
- 动态编辑 24h 窗口
- 列表筛选、分页、排序
- 日期区间过滤
- 审计字段
- 统计接口
"""
import json
import time
import unittest
from datetime import date, timedelta
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.account.models import User, Role
from apps.setting.utils import AppSetting
from apps.runlog.models import RunLog, RunLogUpdate, EventTypeConfig
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


def _make_event(user, **kwargs):
    """直接创建 RunLog 事件"""
    defaults = {
        'event_title': '测试事件',
        'event_type': '运行异常',
        'system_name': '测试系统',
        'severity': 'P2',
        'status': 'in_progress',
        'responsible_user_name': '',
        'created_by': user,
        'tenant_id': user.tenant_id,
    }
    defaults.update(kwargs)
    return RunLog.objects.create(**defaults)


def _make_update(event, user, **kwargs):
    """直接创建 RunLogUpdate 动态"""
    defaults = {
        'runlog_id': event.id,
        'event_title': event.event_title,
        'update_date': date.today(),
        'sequence': 1,
        'recorder': user.nickname,
        'detail_content': '测试动态内容',
        'editable_until': timezone.now() + timedelta(hours=24),
        'created_by': user,
        'tenant_id': user.tenant_id,
    }
    defaults.update(kwargs)
    return RunLogUpdate.objects.create(**defaults)


ALL_RUNLOG_PERMS = [('runlog', 'runlog', [
    'view', 'add', 'edit', 'del',
    'update_view', 'update_add', 'update_edit', 'update_del',
])]


# ============================================================
# 事件 CRUD 测试
# ============================================================

@override_settings(MEDIA_ROOT='/tmp/test_media_runlog')
class RunLogCRUDTests(TestCase):
    """跨日事项 CRUD 测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_RUNLOG_PERMS)
        self.client = _make_client(self.user)
        self.url = '/runlog/'

    def _post(self, data):
        return self.client.post(self.url, data=json.dumps(data), content_type='application/json')

    def _put(self, data):
        return self.client.put(self.url, data=json.dumps(data), content_type='application/json')

    def test_create_event_success(self):
        """创建事件成功（含首次动态）"""
        resp = self._post({
            'event_title': '网络中断',
            'event_type': '运行异常',
            'system_name': '核心网络',
            'severity': 'P1',
            'responsible_user_name': '',
            'first_update': {
                'update_date': '2026-08-08',
                'detail_content': '核心交换机故障导致网络中断',
                'duty_person': '测试人',
            },
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        event = RunLog.objects.get(event_title='网络中断')
        self.assertEqual(event.status, 'in_progress')
        self.assertEqual(event.severity, 'P1')
        self.assertEqual(event.created_by, self.user)
        self.assertEqual(event.update_count, 1)
        self.assertEqual(event.first_update_date, date(2026, 8, 8))
        self.assertEqual(event.last_update_date, date(2026, 8, 8))
        update = RunLogUpdate.objects.get(runlog_id=event.id)
        self.assertEqual(update.detail_content, '核心交换机故障导致网络中断')

    def test_create_missing_title(self):
        """缺少 event_title"""
        resp = self._post({
            'event_type': '运行异常',
            'system_name': '测试系统',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_event_type(self):
        """缺少 event_type"""
        resp = self._post({
            'event_title': '测试',
            'system_name': '测试系统',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_system_name(self):
        """缺少 system_name"""
        resp = self._post({
            'event_title': '测试',
            'event_type': '运行异常',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_invalid_severity(self):
        """非法 severity"""
        resp = self._post({
            'event_title': '测试',
            'event_type': '运行异常',
            'system_name': '测试系统',
            'severity': 'P5',
            'first_update': {'update_date': '2026-08-08', 'duty_person': '测试人'},
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_without_first_update(self):
        """缺少首次动态"""
        resp = self._post({
            'event_title': '测试',
            'event_type': '运行异常',
            'system_name': '测试系统',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_default_severity(self):
        """默认 severity 为 P2"""
        resp = self._post({
            'event_title': '测试',
            'event_type': '运行异常',
            'system_name': '测试系统',
            'responsible_user_name': '',
            'first_update': {'update_date': '2026-08-08', 'duty_person': '测试人'},
        })
        self.assertFalse(resp.json().get('error'))
        event = RunLog.objects.get(event_title='测试')
        self.assertEqual(event.severity, 'P2')

    def test_edit_event_fields(self):
        """编辑事件字段"""
        event = _make_event(self.user)
        resp = self._put({
            'id': event.id,
            'severity': 'P0',
            'responsible_user_name': '张三',
        })
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertEqual(event.severity, 'P0')
        self.assertEqual(event.responsible_user_name, '张三')

    def test_edit_nonexistent_event(self):
        """编辑不存在的事件"""
        resp = self._put({'id': 99999, 'severity': 'P0'})
        self.assertTrue(resp.json().get('error'))

    def test_delete_event_soft_delete(self):
        """删除事件是软删除"""
        event = _make_event(self.user)
        resp = self.client.delete(f'{self.url}?id={event.id}')
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertTrue(event.is_deleted)
        self.assertIsNotNone(event.deleted_at)

    def test_delete_event_cascade_updates(self):
        """删除事件级联删除动态"""
        event = _make_event(self.user)
        update = _make_update(event, self.user)
        self.client.delete(f'{self.url}?id={event.id}')
        self.assertFalse(RunLogUpdate.objects.filter(pk=update.pk).exists())

    def test_delete_nonexistent(self):
        """删除不存在的事件"""
        resp = self.client.delete(f'{self.url}?id=99999')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 状态流转测试
# ============================================================

class RunLogStatusTransitionTests(TestCase):
    """跨日事项状态流转测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_RUNLOG_PERMS)
        self.client = _make_client(self.user)
        self.url = '/runlog/'

    def _put(self, data):
        return self.client.put(self.url, data=json.dumps(data), content_type='application/json')

    def test_in_progress_to_resolved(self):
        """in_progress -> resolved"""
        event = _make_event(self.user)
        resp = self._put({'id': event.id, 'status': 'resolved'})
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertEqual(event.status, 'resolved')

    def test_resolved_to_verified(self):
        """resolved -> verified"""
        event = _make_event(self.user, status='resolved')
        resp = self._put({'id': event.id, 'status': 'verified'})
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertEqual(event.status, 'verified')

    @unittest.expectedFailure
    def test_verified_to_closed(self):
        """verified -> closed（RUNLOG-001: views.py closed 分支 datetime JSON 序列化失败）"""
        event = _make_event(self.user, status='verified')
        resp = self._put({'id': event.id, 'status': 'closed'})
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertEqual(event.status, 'closed')

    def test_closed_to_voided(self):
        """closed -> voided"""
        event = _make_event(self.user, status='closed')
        resp = self._put({'id': event.id, 'status': 'voided'})
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertEqual(event.status, 'voided')

    def test_illegal_in_progress_to_verified(self):
        """非法：in_progress -> verified"""
        event = _make_event(self.user)
        resp = self._put({'id': event.id, 'status': 'verified'})
        self.assertTrue(resp.json().get('error'))

    def test_illegal_in_progress_to_closed(self):
        """非法：in_progress -> closed"""
        event = _make_event(self.user)
        resp = self._put({'id': event.id, 'status': 'closed'})
        self.assertTrue(resp.json().get('error'))

    def test_illegal_resolved_to_voided(self):
        """非法：resolved -> voided"""
        event = _make_event(self.user, status='resolved')
        resp = self._put({'id': event.id, 'status': 'voided'})
        self.assertTrue(resp.json().get('error'))

    def test_illegal_voided_to_anything(self):
        """作废后不能流转"""
        event = _make_event(self.user, status='voided')
        for target in ['in_progress', 'resolved', 'verified', 'closed']:
            resp = self._put({'id': event.id, 'status': target})
            self.assertTrue(resp.json().get('error'), f'voided -> {target} should be blocked')

    def test_resolved_back_to_in_progress(self):
        """resolved -> in_progress（回退）"""
        event = _make_event(self.user, status='resolved')
        resp = self._put({'id': event.id, 'status': 'in_progress'})
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertEqual(event.status, 'in_progress')

    def test_verified_back_to_in_progress(self):
        """verified -> in_progress（回退）"""
        event = _make_event(self.user, status='verified')
        resp = self._put({'id': event.id, 'status': 'in_progress'})
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertEqual(event.status, 'in_progress')

    @unittest.expectedFailure
    def test_closed_with_resolution(self):
        """关闭时填写处理措施（RUNLOG-001: closed 分支 datetime 序列化失败）"""
        event = _make_event(self.user, status='verified')
        resp = self._put({
            'id': event.id,
            'status': 'closed',
            'resolution': '问题已修复',
        })
        self.assertFalse(resp.json().get('error'))
        event.refresh_from_db()
        self.assertEqual(event.status, 'closed')
        self.assertEqual(event.resolution, '问题已修复')
        self.assertIsNotNone(event.verified_at)
        self.assertIsNotNone(event.closed_at)

    @unittest.expectedFailure
    def test_closed_sets_snapshot_hash(self):
        """关闭时设置快照哈希（RUNLOG-001: closed 分支 datetime 序列化失败）"""
        event = _make_event(self.user, status='verified')
        _make_update(event, self.user)
        self._put({'id': event.id, 'status': 'closed'})
        event.refresh_from_db()
        self.assertTrue(event.snapshot_hash)
        self.assertEqual(len(event.snapshot_hash), 64)


# ============================================================
# 动态（Update）测试
# ============================================================

class RunLogUpdateTests(TestCase):
    """运行动态测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_RUNLOG_PERMS)
        self.client = _make_client(self.user)
        self.event = _make_event(self.user)
        self.url = '/runlog/update/'

    def _post(self, data):
        return self.client.post(self.url, data=json.dumps(data), content_type='application/json')

    def _put(self, data):
        return self.client.put(self.url, data=json.dumps(data), content_type='application/json')

    def test_add_update_success(self):
        """添加动态成功"""
        resp = self._post({
            'runlog_id': self.event.id,
            'update_date': '2026-08-08',
            'detail_content': '新动态内容',
            'duty_person': '测试人',
        })
        self.assertFalse(resp.json().get('error'))
        update = RunLogUpdate.objects.get(runlog_id=self.event.id, detail_content='新动态内容')
        self.assertEqual(update.sequence, 1)
        self.event.refresh_from_db()
        self.assertEqual(self.event.update_count, 1)

    def test_add_update_missing_content(self):
        """缺少 detail_content"""
        resp = self._post({
            'runlog_id': self.event.id,
            'update_date': '2026-08-08',
        })
        self.assertTrue(resp.json().get('error'))

    def test_add_update_nonexistent_event(self):
        """添加动态到不存在的事件"""
        resp = self._post({
            'runlog_id': 99999,
            'update_date': '2026-08-08',
            'detail_content': '测试',
        })
        self.assertTrue(resp.json().get('error'))

    def test_add_multiple_updates_sequence(self):
        """同一天多次动态序号递增"""
        for i in range(3):
            self._post({
                'runlog_id': self.event.id,
                'update_date': '2026-08-08',
                'detail_content': f'动态{i}',
                'duty_person': '测试人',
            })
        updates = RunLogUpdate.objects.filter(runlog_id=self.event.id).order_by('sequence')
        self.assertEqual(len(updates), 3)
        self.assertEqual(updates[0].sequence, 1)
        self.assertEqual(updates[1].sequence, 2)
        self.assertEqual(updates[2].sequence, 3)

    @unittest.expectedFailure
    def test_edit_update_within_24h(self):
        """24小时内编辑动态（RUNLOG-002: views.py L424 duty_person or None -> NOT NULL约束失败）"""
        update = _make_update(self.event, self.user)
        resp = self._put({
            'id': update.id,
            'detail_content': '修改后内容',
        })
        self.assertFalse(resp.json().get('error'))
        update.refresh_from_db()
        self.assertEqual(update.detail_content, '修改后内容')

    def test_edit_update_expired(self):
        """超过24小时不能编辑"""
        update = _make_update(self.event, self.user,
                               editable_until=timezone.now() - timedelta(hours=1))
        resp = self._put({
            'id': update.id,
            'detail_content': '修改后内容',
        })
        self.assertTrue(resp.json().get('error'))

    def test_edit_update_by_non_creator(self):
        """非创建者不能编辑动态"""
        other_user = _make_user('other', tenant_id='t1')
        _grant_perms(other_user, ALL_RUNLOG_PERMS)
        other_client = _make_client(other_user)
        update = _make_update(self.event, self.user)
        resp = other_client.put(self.url, data=json.dumps({
            'id': update.id,
            'detail_content': '修改',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_delete_update(self):
        """删除动态"""
        update = _make_update(self.event, self.user)
        resp = self.client.delete(f'{self.url}?id={update.id}')
        self.assertFalse(resp.json().get('error'))
        self.assertFalse(RunLogUpdate.objects.filter(pk=update.pk).exists())
        self.event.refresh_from_db()
        self.assertEqual(self.event.update_count, 0)

    def test_delete_update_updates_dates(self):
        """删除动态后更新日期统计"""
        update1 = _make_update(self.event, self.user, update_date=date(2026, 8, 1))
        update2 = _make_update(self.event, self.user, update_date=date(2026, 8, 5), sequence=2)
        self.client.delete(f'{self.url}?id={update1.id}')
        self.event.refresh_from_db()
        self.assertEqual(self.event.update_count, 1)
        self.assertEqual(self.event.first_update_date, date(2026, 8, 5))
        self.assertEqual(self.event.last_update_date, date(2026, 8, 5))


# ============================================================
# 权限测试
# ============================================================

class RunLogPermissionTests(TestCase):
    """跨日事项权限测试"""

    def setUp(self):
        setup_test_env(self)
        self.viewer = _make_user('viewer', tenant_id='t1')
        _grant_perms(self.viewer, [('runlog', 'runlog', ['view'])])
        self.c_viewer = _make_client(self.viewer)

        self.editor = _make_user('editor', tenant_id='t1')
        _grant_perms(self.editor, [('runlog', 'runlog', ['view', 'add', 'edit'])])
        self.c_editor = _make_client(self.editor)

        self.noperm = _make_user('noperm', tenant_id='t1')
        self.c_noperm = _make_client(self.noperm)

        self.supper = _make_user('supper', is_supper=True, tenant_id='t1')
        self.c_supper = _make_client(self.supper)

    def test_view_with_permission(self):
        """有 view 权限可以列表"""
        resp = self.c_viewer.get('/runlog/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))

    def test_view_without_permission(self):
        """无权限不能列表"""
        resp = self.c_noperm.get('/runlog/')
        self.assertTrue(resp.json().get('error'))

    def test_add_without_permission(self):
        """无 add 权限不能创建"""
        resp = self.c_viewer.post('/runlog/', data=json.dumps({
            'event_title': '测试',
            'event_type': '运行异常',
            'system_name': '测试系统',
            'first_update': {'update_date': '2026-08-08', 'duty_person': '测试人'},
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_supper_bypasses_permission(self):
        """超级管理员绕过权限"""
        resp = self.c_supper.get('/runlog/')
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 租户隔离测试
# ============================================================

class RunLogTenantIsolationTests(TestCase):
    """跨日事项租户隔离测试"""

    def setUp(self):
        setup_test_env(self)
        self.user_a = _make_user('user_a', tenant_id='tenant_a')
        _grant_perms(self.user_a, ALL_RUNLOG_PERMS)
        self.c_a = _make_client(self.user_a)

        self.user_b = _make_user('user_b', tenant_id='tenant_b')
        _grant_perms(self.user_b, ALL_RUNLOG_PERMS)
        self.c_b = _make_client(self.user_b)

        self.supper = _make_user('supper', is_supper=True, tenant_id='tenant_a')
        self.c_supper = _make_client(self.supper)

    def test_cross_tenant_list_isolation(self):
        """租户隔离：列表"""
        event_a = _make_event(self.user_a, event_title='A的事件')
        event_b = _make_event(self.user_b, event_title='B的事件')
        resp = self.c_a.get('/runlog/')
        body = resp.json()
        titles = [l['event_title'] for l in body['data']['logs']]
        self.assertIn('A的事件', titles)
        self.assertNotIn('B的事件', titles)

    def test_cross_tenant_edit_blocked(self):
        """跨租户编辑被拒"""
        event_b = _make_event(self.user_b)
        resp = self.c_a.put('/runlog/', data=json.dumps({
            'id': event_b.id,
            'severity': 'P0',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_cross_tenant_delete_blocked(self):
        """跨租户删除被拒"""
        event_b = _make_event(self.user_b)
        resp = self.c_a.delete(f'/runlog/?id={event_b.id}')
        self.assertTrue(resp.json().get('error'))

    def test_cross_tenant_detail_blocked(self):
        """跨租户查看详情被拒"""
        event_b = _make_event(self.user_b)
        resp = self.c_a.get(f'/runlog/detail/?id={event_b.id}')
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_cross_tenant_add_update_blocked(self):
        """跨租户添加动态被拒"""
        event_b = _make_event(self.user_b)
        resp = self.c_a.post('/runlog/update/', data=json.dumps({
            'runlog_id': event_b.id,
            'update_date': '2026-08-08',
            'detail_content': '测试',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_supper_sees_all_tenants(self):
        """超级管理员看到所有租户"""
        event_a = _make_event(self.user_a, event_title='A的事件')
        event_b = _make_event(self.user_b, event_title='B的事件')
        resp = self.c_supper.get('/runlog/')
        body = resp.json()
        titles = [l['event_title'] for l in body['data']['logs']]
        self.assertIn('A的事件', titles)
        self.assertIn('B的事件', titles)


# ============================================================
# 幂等性测试
# ============================================================

class RunLogIdempotencyTests(TestCase):
    """跨日事项幂等性测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_RUNLOG_PERMS)
        self.client = _make_client(self.user)
        self.url = '/runlog/'

    def test_duplicate_event_blocked(self):
        """30秒内重复提交相同事件被拦截"""
        data = {
            'event_title': '重复事件',
            'event_type': '运行异常',
            'system_name': '测试系统',
            'responsible_user_name': '',
            'first_update': {'update_date': '2026-08-08', 'duty_person': '测试人'},
        }
        resp1 = self.client.post(self.url, data=json.dumps(data), content_type='application/json')
        self.assertFalse(resp1.json().get('error'))

        resp2 = self.client.post(self.url, data=json.dumps(data), content_type='application/json')
        self.assertTrue(resp2.json().get('error'))

    def test_different_title_allows(self):
        """不同标题可以创建"""
        self.client.post(self.url, data=json.dumps({
            'event_title': '事件A',
            'event_type': '运行异常',
            'system_name': '测试系统',
            'responsible_user_name': '',
            'first_update': {'update_date': '2026-08-08', 'duty_person': '测试人'},
        }), content_type='application/json')
        resp = self.client.post(self.url, data=json.dumps({
            'event_title': '事件B',
            'event_type': '运行异常',
            'system_name': '测试系统',
            'responsible_user_name': '',
            'first_update': {'update_date': '2026-08-08', 'duty_person': '测试人'},
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 列表查询测试
# ============================================================

class RunLogListQueryTests(TestCase):
    """跨日事项列表查询测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_RUNLOG_PERMS)
        self.client = _make_client(self.user)
        self.url = '/runlog/'

        now = timezone.now()
        self.event1 = _make_event(self.user, event_title='事件1', severity='P0',
                                   system_name='系统A', status='in_progress')
        self.event1.created_at = now - timedelta(days=2)
        self.event1.save()

        self.event2 = _make_event(self.user, event_title='事件2', severity='P1',
                                   system_name='系统B', status='resolved')
        self.event2.created_at = now - timedelta(days=1)
        self.event2.save()

        self.event3 = _make_event(self.user, event_title='事件3', severity='P2',
                                   system_name='系统A', status='in_progress')
        self.event3.created_at = now
        self.event3.save()

    def test_list_default_order(self):
        """默认按 created_at 倒序"""
        resp = self.client.get(self.url)
        body = resp.json()
        ids = [l['id'] for l in body['data']['logs']]
        self.assertEqual(ids[0], self.event3.id)

    def test_filter_by_status(self):
        """按状态筛选"""
        resp = self.client.get(f'{self.url}?status=resolved')
        body = resp.json()
        ids = [l['id'] for l in body['data']['logs']]
        self.assertIn(self.event2.id, ids)
        self.assertNotIn(self.event1.id, ids)
        self.assertNotIn(self.event3.id, ids)

    def test_filter_by_severity(self):
        """按级别筛选"""
        resp = self.client.get(f'{self.url}?severity=P0')
        body = resp.json()
        ids = [l['id'] for l in body['data']['logs']]
        self.assertIn(self.event1.id, ids)
        self.assertNotIn(self.event2.id, ids)

    def test_filter_by_system_name(self):
        """按系统名称筛选"""
        resp = self.client.get(f'{self.url}?system_name=系统A')
        body = resp.json()
        ids = [l['id'] for l in body['data']['logs']]
        self.assertIn(self.event1.id, ids)
        self.assertIn(self.event3.id, ids)
        self.assertNotIn(self.event2.id, ids)

    def test_pagination(self):
        """分页"""
        resp = self.client.get(f'{self.url}?page=1&page_size=2')
        body = resp.json()
        self.assertEqual(len(body['data']['logs']), 2)
        self.assertEqual(body['data']['pagination']['total_count'], 3)

    def test_empty_result(self):
        """空结果"""
        resp = self.client.get(f'{self.url}?status=voided')
        body = resp.json()
        self.assertEqual(len(body['data']['logs']), 0)

    def test_returns_system_names(self):
        """返回系统名称列表"""
        resp = self.client.get(self.url)
        body = resp.json()
        names = body['data']['system_names']
        self.assertIn('系统A', names)
        self.assertIn('系统B', names)


# ============================================================
# 软删除行为测试
# ============================================================

class RunLogSoftDeleteTests(TestCase):
    """跨日事项软删除测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_RUNLOG_PERMS)
        self.client = _make_client(self.user)
        self.url = '/runlog/'

    def test_soft_delete_excludes_from_list(self):
        """软删除后不出现在列表中"""
        event = _make_event(self.user)
        self.client.delete(f'{self.url}?id={event.id}')
        resp = self.client.get(self.url)
        body = resp.json()
        ids = [l['id'] for l in body['data']['logs']]
        self.assertNotIn(event.id, ids)

    def test_deleted_event_edit_blocked(self):
        """已删除事件不能编辑"""
        event = _make_event(self.user)
        self.client.delete(f'{self.url}?id={event.id}')
        resp = self.client.put(self.url, data=json.dumps({
            'id': event.id,
            'severity': 'P0',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 统计接口测试
# ============================================================

class RunLogStatisticsTests(TestCase):
    """跨日事项统计接口测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_RUNLOG_PERMS)
        self.client = _make_client(self.user)

    def test_statistics_returns_data(self):
        """统计接口返回数据"""
        _make_event(self.user, status='in_progress', severity='P0')
        _make_event(self.user, status='resolved', severity='P1')
        resp = self.client.get('/runlog/statistics/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertIn('status_stats', body['data'])
        self.assertIn('severity_stats', body['data'])
        self.assertIn('trend_data', body['data'])

    def test_statistics_empty_data(self):
        """空数据统计"""
        resp = self.client.get('/runlog/statistics/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['status_stats']['in_progress']['count'], 0)
        self.assertEqual(body['data']['status_stats']['resolved']['count'], 0)


# ============================================================
# 详情接口测试
# ============================================================

class RunLogDetailTests(TestCase):
    """跨日事项详情接口测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ALL_RUNLOG_PERMS)
        self.client = _make_client(self.user)

    def test_detail_returns_updates(self):
        """详情返回动态列表"""
        event = _make_event(self.user)
        update1 = _make_update(event, self.user, detail_content='动态1')
        update2 = _make_update(event, self.user, detail_content='动态2', sequence=2)
        resp = self.client.get(f'/runlog/detail/?id={event.id}')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(len(body['data']['updates']), 2)

    def test_detail_nonexistent(self):
        """不存在的事件详情"""
        resp = self.client.get('/runlog/detail/?id=99999')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 事件类型配置测试
# ============================================================

class EventTypeConfigTests(TestCase):
    """事件类型配置测试"""

    def setUp(self):
        setup_test_env(self)
        self.supper = _make_user('supper', is_supper=True, tenant_id='t1')
        self.c_supper = _make_client(self.supper)
        self.normal = _make_user('normal', tenant_id='t1')
        self.c_normal = _make_client(self.normal)

    def test_get_event_types(self):
        """获取事件类型列表"""
        EventTypeConfig.objects.create(name='运行异常', created_by=self.supper)
        EventTypeConfig.objects.create(name='设备故障', created_by=self.supper)
        resp = self.c_supper.get('/runlog/event_types/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(len(body['data']), 2)

    def test_create_event_type_supper(self):
        """超级管理员创建事件类型"""
        resp = self.c_supper.post('/runlog/event_types/', data=json.dumps({
            'name': '安全事件',
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))

    def test_create_event_type_normal_blocked(self):
        """普通用户不能创建事件类型"""
        resp = self.c_normal.post('/runlog/event_types/', data=json.dumps({
            'name': '安全事件',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_create_duplicate_name(self):
        """重复名称"""
        EventTypeConfig.objects.create(name='运行异常', created_by=self.supper)
        resp = self.c_supper.post('/runlog/event_types/', data=json.dumps({
            'name': '运行异常',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
