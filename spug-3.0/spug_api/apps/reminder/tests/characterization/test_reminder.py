# -*- coding: utf-8 -*-
"""提醒事项模块特征测试

覆盖：
- CRUD 全生命周期
- 权限检查（view/add/edit/delete）
- 租户隔离
- 软删除
- 表单校验（target_date/repeat_type/repeat_interval/recipient_users）
- matches_today 逻辑（none/daily/weekly/monthly/yearly）
- Pending 懒创建 ReminderLog
- Ack 确认
- Status 看板
- Users 列表
- 幂等性（ReminderLog get_or_create）
- 审计事件
- 已禁用/已删除提醒不触发 pending
"""
import json
import time
from datetime import date, timedelta
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.account.models import User, Role
from apps.setting.utils import AppSetting
from apps.reminder.models import Reminder, ReminderLog
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


REMINDER_PERMS = [('home', 'reminder', ['view', 'add', 'edit', 'delete'])]


def _make_reminder(user, **kwargs):
    """直接创建 Reminder"""
    defaults = {
        'name': '测试提醒',
        'enabled': True,
        'target_date': date.today(),
        'repeat_type': 'none',
        'repeat_interval': 1,
        'content': '请填写日志',
        'recipient_users': json.dumps([{'id': user.id, 'nickname': user.nickname}]),
        'created_by_id': user.id,
        'created_by_name': user.nickname,
        'tenant_id': user.tenant_id,
    }
    defaults.update(kwargs)
    return Reminder.objects.create(**defaults)


# ============================================================
# CRUD 测试
# ============================================================

class ReminderCRUDTests(TestCase):
    """提醒事项 CRUD 测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, REMINDER_PERMS)
        self.client = _make_client(self.user)
        self.url = '/reminder/'

    def _post(self, data, pk=None):
        url = f'{self.url}{pk}/' if pk else self.url
        return self.client.post(url, data=json.dumps(data), content_type='application/json')

    def test_create_success(self):
        """创建提醒成功"""
        resp = self._post({
            'name': '每日值班提醒',
            'target_date': '2026-08-08',
            'repeat_type': 'daily',
            'repeat_interval': 1,
            'content': '请填写值班日志',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': self.user.nickname}]),
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        obj = Reminder.objects.get(name='每日值班提醒')
        self.assertEqual(obj.repeat_type, 'daily')
        self.assertEqual(obj.target_date, date(2026, 8, 8))
        self.assertEqual(obj.created_by_id, self.user.id)
        self.assertEqual(obj.tenant_id, 't1')

    def test_create_missing_name(self):
        """缺少 name"""
        resp = self._post({
            'target_date': '2026-08-08',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_target_date(self):
        """缺少 target_date"""
        resp = self._post({
            'name': '测试',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_recipient_users(self):
        """缺少 recipient_users"""
        resp = self._post({
            'name': '测试',
            'target_date': '2026-08-08',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_empty_recipient_users(self):
        """空接收人列表"""
        resp = self._post({
            'name': '测试',
            'target_date': '2026-08-08',
            'recipient_users': '[]',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_invalid_target_date_format(self):
        """目标日格式错误"""
        resp = self._post({
            'name': '测试',
            'target_date': '2026/08/08',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_invalid_repeat_type(self):
        """非法重复类型"""
        resp = self._post({
            'name': '测试',
            'target_date': '2026-08-08',
            'repeat_type': 'hourly',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_invalid_repeat_interval(self):
        """重复间隔 < 1"""
        resp = self._post({
            'name': '测试',
            'target_date': '2026-08-08',
            'repeat_type': 'daily',
            'repeat_interval': 0,
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_default_repeat_type(self):
        """默认 repeat_type 为 none"""
        resp = self._post({
            'name': '测试',
            'target_date': '2026-08-08',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
        })
        self.assertFalse(resp.json().get('error'))
        obj = Reminder.objects.get(name='测试')
        self.assertEqual(obj.repeat_type, 'none')
        self.assertEqual(obj.repeat_interval, 1)

    def test_edit_success(self):
        """编辑提醒成功"""
        obj = _make_reminder(self.user)
        resp = self._post({
            'name': '修改后名称',
            'target_date': '2026-08-10',
            'repeat_type': 'weekly',
            'repeat_interval': 2,
            'content': '新内容',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
            'enabled': False,
        }, pk=obj.id)
        self.assertFalse(resp.json().get('error'))
        obj.refresh_from_db()
        self.assertEqual(obj.name, '修改后名称')
        self.assertEqual(obj.repeat_type, 'weekly')
        self.assertEqual(obj.repeat_interval, 2)
        self.assertFalse(obj.enabled)
        self.assertEqual(obj.updated_by_id, self.user.id)

    def test_edit_nonexistent(self):
        """编辑不存在的提醒"""
        resp = self._post({
            'name': '测试',
            'target_date': '2026-08-08',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
        }, pk=99999)
        self.assertTrue(resp.json().get('error'))

    def test_delete_success(self):
        """删除提醒（软删除）"""
        obj = _make_reminder(self.user)
        resp = self.client.delete(f'{self.url}{obj.id}/')
        self.assertFalse(resp.json().get('error'))
        obj.refresh_from_db()
        self.assertTrue(obj.is_deleted)
        self.assertIsNotNone(obj.deleted_at)
        self.assertEqual(obj.deleted_by_id, self.user.id)

    def test_delete_nonexistent(self):
        """删除不存在的提醒"""
        resp = self.client.delete(f'{self.url}99999/')
        self.assertTrue(resp.json().get('error'))

    def test_list_returns_all(self):
        """列表返回所有未删除的提醒"""
        obj1 = _make_reminder(self.user, name='提醒1')
        obj2 = _make_reminder(self.user, name='提醒2')
        resp = self.client.get(self.url)
        body = resp.json()
        self.assertEqual(len(body['data']), 2)
        names = [r['name'] for r in body['data']]
        self.assertIn('提醒1', names)
        self.assertIn('提醒2', names)

    def test_list_excludes_deleted(self):
        """列表不包含已删除的提醒"""
        obj1 = _make_reminder(self.user, name='提醒1')
        obj2 = _make_reminder(self.user, name='提醒2')
        obj2.is_deleted = True
        obj2.save()
        resp = self.client.get(self.url)
        body = resp.json()
        self.assertEqual(len(body['data']), 1)
        self.assertEqual(body['data'][0]['name'], '提醒1')

    def test_detail_success(self):
        """详情"""
        obj = _make_reminder(self.user)
        resp = self.client.get(f'{self.url}{obj.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['name'], obj.name)

    def test_detail_nonexistent(self):
        """详情不存在"""
        resp = self.client.get(f'{self.url}99999/')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 权限测试
# ============================================================

class ReminderPermissionTests(TestCase):
    """提醒事项权限测试"""

    def setUp(self):
        setup_test_env(self)
        self.viewer = _make_user('viewer', tenant_id='t1')
        _grant_perms(self.viewer, [('home', 'reminder', ['view'])])
        self.c_viewer = _make_client(self.viewer)

        self.editor = _make_user('editor', tenant_id='t1')
        _grant_perms(self.editor, REMINDER_PERMS)
        self.c_editor = _make_client(self.editor)

        self.noperm = _make_user('noperm', tenant_id='t1')
        self.c_noperm = _make_client(self.noperm)

        self.supper = _make_user('supper', is_supper=True, tenant_id='t1')
        self.c_supper = _make_client(self.supper)

    def test_view_with_permission(self):
        """有 view 权限可以列表"""
        resp = self.c_viewer.get('/reminder/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))

    def test_view_without_permission(self):
        """无权限不能列表"""
        resp = self.c_noperm.get('/reminder/')
        self.assertTrue(resp.json().get('error'))

    def test_add_without_permission(self):
        """无 add 权限不能创建"""
        resp = self.c_viewer.post('/reminder/', data=json.dumps({
            'name': '测试',
            'target_date': '2026-08-08',
            'recipient_users': json.dumps([{'id': self.viewer.id, 'nickname': 'viewer'}]),
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_delete_without_permission(self):
        """无 delete 权限不能删除"""
        obj = _make_reminder(self.editor)
        resp = self.c_viewer.delete(f'/reminder/{obj.id}/')
        self.assertTrue(resp.json().get('error'))

    def test_supper_bypasses_permission(self):
        """超级管理员绕过权限"""
        resp = self.c_supper.get('/reminder/')
        self.assertFalse(resp.json().get('error'))

    def test_pending_no_permission_required(self):
        """pending 接口不需要管理权限"""
        obj = _make_reminder(self.noperm, target_date=date.today(),
                              recipient_users=json.dumps([{'id': self.noperm.id, 'nickname': self.noperm.nickname}]))
        resp = self.c_noperm.get('/reminder/pending/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))

    def test_ack_no_permission_required(self):
        """ack 接口不需要管理权限"""
        obj = _make_reminder(self.editor, target_date=date.today(),
                              recipient_users=json.dumps([{'id': self.noperm.id, 'nickname': self.noperm.nickname}]))
        log = ReminderLog.objects.create(
            reminder=obj, user_id=self.noperm.id, user_name=self.noperm.nickname,
            date_key=date.today().strftime('%Y-%m-%d'),
        )
        resp = self.c_noperm.post('/reminder/ack/', data=json.dumps({
            'log_id': log.id,
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 租户隔离测试
# ============================================================

class ReminderTenantIsolationTests(TestCase):
    """提醒事项租户隔离测试"""

    def setUp(self):
        setup_test_env(self)
        self.user_a = _make_user('user_a', tenant_id='tenant_a')
        _grant_perms(self.user_a, REMINDER_PERMS)
        self.c_a = _make_client(self.user_a)

        self.user_b = _make_user('user_b', tenant_id='tenant_b')
        _grant_perms(self.user_b, REMINDER_PERMS)
        self.c_b = _make_client(self.user_b)

        self.supper = _make_user('supper', is_supper=True, tenant_id='tenant_a')
        self.c_supper = _make_client(self.supper)

    def test_cross_tenant_list_isolation(self):
        """租户隔离：列表"""
        obj_a = _make_reminder(self.user_a, name='A的提醒')
        obj_b = _make_reminder(self.user_b, name='B的提醒')
        resp = self.c_a.get('/reminder/')
        body = resp.json()
        names = [r['name'] for r in body['data']]
        self.assertIn('A的提醒', names)
        self.assertNotIn('B的提醒', names)

    def test_cross_tenant_edit_blocked(self):
        """跨租户编辑被拒"""
        obj_b = _make_reminder(self.user_b)
        resp = self.c_a.post(f'/reminder/{obj_b.id}/', data=json.dumps({
            'name': '修改',
            'target_date': '2026-08-08',
            'recipient_users': json.dumps([{'id': self.user_a.id, 'nickname': 'a'}]),
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_cross_tenant_delete_blocked(self):
        """跨租户删除被拒"""
        obj_b = _make_reminder(self.user_b)
        resp = self.c_a.delete(f'/reminder/{obj_b.id}/')
        self.assertTrue(resp.json().get('error'))

    def test_cross_tenant_detail_blocked(self):
        """跨租户详情被拒"""
        obj_b = _make_reminder(self.user_b)
        resp = self.c_a.get(f'/reminder/{obj_b.id}/')
        self.assertTrue(resp.json().get('error'))

    def test_supper_sees_all_tenants(self):
        """超级管理员看到所有租户"""
        obj_a = _make_reminder(self.user_a, name='A的提醒')
        obj_b = _make_reminder(self.user_b, name='B的提醒')
        resp = self.c_supper.get('/reminder/')
        body = resp.json()
        names = [r['name'] for r in body['data']]
        self.assertIn('A的提醒', names)
        self.assertIn('B的提醒', names)


# ============================================================
# matches_today 逻辑测试
# ============================================================

class ReminderMatchesTodayTests(TestCase):
    """matches_today 重复匹配逻辑测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')

    def test_none_matches_on_target_date(self):
        """none: 仅 target_date 当天匹配"""
        today = date(2026, 8, 8)
        obj = _make_reminder(self.user, target_date=today, repeat_type='none')
        self.assertTrue(obj.matches_today(today))
        self.assertFalse(obj.matches_today(today + timedelta(days=1)))

    def test_none_before_target_date(self):
        """none: target_date 之前不匹配"""
        obj = _make_reminder(self.user, target_date=date(2026, 8, 10), repeat_type='none')
        self.assertFalse(obj.matches_today(date(2026, 8, 8)))

    def test_daily_interval_1(self):
        """daily interval=1: 每天匹配"""
        td = date(2026, 8, 1)
        obj = _make_reminder(self.user, target_date=td, repeat_type='daily', repeat_interval=1)
        for delta in range(0, 10):
            self.assertTrue(obj.matches_today(td + timedelta(days=delta)))

    def test_daily_interval_3(self):
        """daily interval=3: 每3天匹配"""
        td = date(2026, 8, 1)
        obj = _make_reminder(self.user, target_date=td, repeat_type='daily', repeat_interval=3)
        self.assertTrue(obj.matches_today(td))
        self.assertFalse(obj.matches_today(td + timedelta(days=1)))
        self.assertFalse(obj.matches_today(td + timedelta(days=2)))
        self.assertTrue(obj.matches_today(td + timedelta(days=3)))

    def test_weekly_interval_1(self):
        """weekly interval=1: 每7天匹配"""
        td = date(2026, 8, 1)
        obj = _make_reminder(self.user, target_date=td, repeat_type='weekly', repeat_interval=1)
        self.assertTrue(obj.matches_today(td))
        self.assertFalse(obj.matches_today(td + timedelta(days=6)))
        self.assertTrue(obj.matches_today(td + timedelta(days=7)))

    def test_monthly_interval_1(self):
        """monthly interval=1: 每月同日匹配"""
        td = date(2026, 1, 15)
        obj = _make_reminder(self.user, target_date=td, repeat_type='monthly', repeat_interval=1)
        self.assertTrue(obj.matches_today(date(2026, 2, 15)))
        self.assertFalse(obj.matches_today(date(2026, 2, 16)))
        self.assertTrue(obj.matches_today(date(2026, 3, 15)))

    def test_yearly_interval_1(self):
        """yearly interval=1: 每年同月同日匹配"""
        td = date(2026, 3, 15)
        obj = _make_reminder(self.user, target_date=td, repeat_type='yearly', repeat_interval=1)
        self.assertTrue(obj.matches_today(date(2027, 3, 15)))
        self.assertFalse(obj.matches_today(date(2027, 3, 16)))
        self.assertFalse(obj.matches_today(date(2027, 4, 15)))


# ============================================================
# Pending 测试
# ============================================================

class ReminderPendingTests(TestCase):
    """Pending 懒创建测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = _make_user('admin', tenant_id='t1')
        _grant_perms(self.admin, REMINDER_PERMS)
        self.c_admin = _make_client(self.admin)

        self.recipient = _make_user('recipient', tenant_id='t1')
        self.c_recipient = _make_client(self.recipient)

    def test_pending_creates_log(self):
        """pending 懒创建 ReminderLog"""
        _make_reminder(self.admin, target_date=date.today(),
                        recipient_users=json.dumps([
                            {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                        ]))
        resp = self.c_recipient.get('/reminder/pending/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['data']), 1)
        log = ReminderLog.objects.get(user_id=self.recipient.id)
        self.assertFalse(log.is_acked)

    def test_pending_idempotent(self):
        """重复调用 pending 不创建重复 log"""
        _make_reminder(self.admin, target_date=date.today(),
                        recipient_users=json.dumps([
                            {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                        ]))
        self.c_recipient.get('/reminder/pending/')
        self.c_recipient.get('/reminder/pending/')
        count = ReminderLog.objects.filter(user_id=self.recipient.id).count()
        self.assertEqual(count, 1)

    def test_pending_excludes_disabled(self):
        """已禁用提醒不出现在 pending"""
        _make_reminder(self.admin, target_date=date.today(), enabled=False,
                        recipient_users=json.dumps([
                            {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                        ]))
        resp = self.c_recipient.get('/reminder/pending/')
        body = resp.json()
        self.assertEqual(len(body['data']), 0)

    def test_pending_excludes_deleted(self):
        """已删除提醒不出现在 pending"""
        obj = _make_reminder(self.admin, target_date=date.today(),
                              recipient_users=json.dumps([
                                  {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                              ]))
        obj.is_deleted = True
        obj.save()
        resp = self.c_recipient.get('/reminder/pending/')
        body = resp.json()
        self.assertEqual(len(body['data']), 0)

    def test_pending_excludes_not_recipient(self):
        """非接收人不出现在 pending"""
        other = _make_user('other', tenant_id='t1')
        c_other = _make_client(other)
        _make_reminder(self.admin, target_date=date.today(),
                        recipient_users=json.dumps([
                            {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                        ]))
        resp = c_other.get('/reminder/pending/')
        body = resp.json()
        self.assertEqual(len(body['data']), 0)

    def test_pending_excludes_non_matching_date(self):
        """非匹配日期不出现在 pending"""
        _make_reminder(self.admin, target_date=date.today() + timedelta(days=1),
                        repeat_type='none',
                        recipient_users=json.dumps([
                            {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                        ]))
        resp = self.c_recipient.get('/reminder/pending/')
        body = resp.json()
        self.assertEqual(len(body['data']), 0)

    def test_pending_excludes_acked(self):
        """已确认的 log 不出现在 pending"""
        obj = _make_reminder(self.admin, target_date=date.today(),
                              recipient_users=json.dumps([
                                  {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                              ]))
        log = ReminderLog.objects.create(
            reminder=obj, user_id=self.recipient.id, user_name=self.recipient.nickname,
            date_key=date.today().strftime('%Y-%m-%d'), is_acked=True,
            acked_at=timezone.now(),
        )
        resp = self.c_recipient.get('/reminder/pending/')
        body = resp.json()
        self.assertEqual(len(body['data']), 0)


# ============================================================
# Ack 确认测试
# ============================================================

class ReminderAckTests(TestCase):
    """Ack 确认测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = _make_user('admin', tenant_id='t1')
        _grant_perms(self.admin, REMINDER_PERMS)

        self.recipient = _make_user('recipient', tenant_id='t1')
        self.c_recipient = _make_client(self.recipient)

        self.other = _make_user('other', tenant_id='t1')
        self.c_other = _make_client(self.other)

        self.reminder = _make_reminder(self.admin, target_date=date.today(),
                                        recipient_users=json.dumps([
                                            {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                                        ]))
        self.log = ReminderLog.objects.create(
            reminder=self.reminder, user_id=self.recipient.id,
            user_name=self.recipient.nickname,
            date_key=date.today().strftime('%Y-%m-%d'),
        )

    def test_ack_success(self):
        """确认成功"""
        resp = self.c_recipient.post('/reminder/ack/', data=json.dumps({
            'log_id': self.log.id,
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.log.refresh_from_db()
        self.assertTrue(self.log.is_acked)
        self.assertIsNotNone(self.log.acked_at)

    def test_ack_by_non_owner(self):
        """非接收人不能确认"""
        resp = self.c_other.post('/reminder/ack/', data=json.dumps({
            'log_id': self.log.id,
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.log.refresh_from_db()
        self.assertFalse(self.log.is_acked)

    def test_ack_already_acked(self):
        """重复确认"""
        self.log.is_acked = True
        self.log.acked_at = timezone.now()
        self.log.save()
        resp = self.c_recipient.post('/reminder/ack/', data=json.dumps({
            'log_id': self.log.id,
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_ack_nonexistent_log(self):
        """确认不存在的 log"""
        resp = self.c_recipient.post('/reminder/ack/', data=json.dumps({
            'log_id': 99999,
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_ack_missing_log_id(self):
        """缺少 log_id"""
        resp = self.c_recipient.post('/reminder/ack/', data=json.dumps({}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# Status 看板测试
# ============================================================

class ReminderStatusTests(TestCase):
    """Status 看板测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = _make_user('admin', tenant_id='t1')
        _grant_perms(self.admin, REMINDER_PERMS)
        self.c_admin = _make_client(self.admin)

        self.recipient = _make_user('recipient', tenant_id='t1')
        self.c_recipient = _make_client(self.recipient)

    def test_status_returns_matching_reminders(self):
        """status 返回今天匹配的提醒"""
        _make_reminder(self.admin, name='今日提醒', target_date=date.today(),
                        recipient_users=json.dumps([
                            {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                        ]))
        _make_reminder(self.admin, name='明日提醒', target_date=date.today() + timedelta(days=1),
                        recipient_users=json.dumps([
                            {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                        ]))
        resp = self.c_admin.get('/reminder/status/')
        body = resp.json()
        names = [r['name'] for r in body['data']]
        self.assertIn('今日提醒', names)
        self.assertNotIn('明日提醒', names)

    def test_status_shows_ack_status(self):
        """status 显示确认状态"""
        obj = _make_reminder(self.admin, name='今日提醒', target_date=date.today(),
                              recipient_users=json.dumps([
                                  {'id': self.recipient.id, 'nickname': self.recipient.nickname}
                              ]))
        # 先让 recipient 确认
        self.c_recipient.get('/reminder/pending/')
        self.c_recipient.post('/reminder/ack/', data=json.dumps({
            'log_id': ReminderLog.objects.get(user_id=self.recipient.id).id,
        }), content_type='application/json')
        # 查看 status
        resp = self.c_admin.get('/reminder/status/')
        body = resp.json()
        reminder_data = body['data'][0]
        self.assertEqual(reminder_data['acked'], 1)
        self.assertEqual(reminder_data['total'], 1)

    def test_status_no_matching(self):
        """无匹配提醒"""
        resp = self.c_admin.get('/reminder/status/')
        body = resp.json()
        self.assertEqual(len(body['data']), 0)

    def test_status_without_permission(self):
        """无权限不能查看 status"""
        noperm = _make_user('noperm', tenant_id='t1')
        c_noperm = _make_client(noperm)
        resp = c_noperm.get('/reminder/status/')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# Users 列表测试
# ============================================================

class ReminderUsersTests(TestCase):
    """Users 列表测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = _make_user('admin', tenant_id='t1')
        _grant_perms(self.admin, REMINDER_PERMS)
        self.c_admin = _make_client(self.admin)

    def test_users_returns_active(self):
        """返回活跃用户"""
        _make_user('user1', tenant_id='t1')
        _make_user('user2', tenant_id='t2')
        resp = self.c_admin.get('/reminder/users/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        usernames = [u['username'] for u in body['data']]
        self.assertIn('admin', usernames)
        self.assertIn('user1', usernames)
        self.assertIn('user2', usernames)

    def test_users_excludes_inactive(self):
        """不返回非活跃用户"""
        _make_user('inactive', tenant_id='t1', is_active=False)
        resp = self.c_admin.get('/reminder/users/')
        body = resp.json()
        usernames = [u['username'] for u in body['data']]
        self.assertNotIn('inactive', usernames)

    def test_users_without_permission(self):
        """无权限不能查看 users"""
        noperm = _make_user('noperm', tenant_id='t1')
        c_noperm = _make_client(noperm)
        resp = c_noperm.get('/reminder/users/')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 重复提交/幂等性测试
# ============================================================

class ReminderDuplicateTests(TestCase):
    """提醒事项重复提交测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, REMINDER_PERMS)
        self.client = _make_client(self.user)

    def test_duplicate_reminder_allowed(self):
        """相同提醒可以重复创建（无幂等性检查）"""
        data = {
            'name': '重复提醒',
            'target_date': '2026-08-08',
            'recipient_users': json.dumps([{'id': self.user.id, 'nickname': 'test'}]),
        }
        resp1 = self.client.post('/reminder/', data=json.dumps(data), content_type='application/json')
        self.assertFalse(resp1.json().get('error'))
        resp2 = self.client.post('/reminder/', data=json.dumps(data), content_type='application/json')
        self.assertFalse(resp2.json().get('error'))
        count = Reminder.objects.filter(name='重复提醒').count()
        self.assertEqual(count, 2)


# ============================================================
# 软删除行为测试
# ============================================================

class ReminderSoftDeleteTests(TestCase):
    """提醒事项软删除测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, REMINDER_PERMS)
        self.client = _make_client(self.user)

    def test_soft_delete_excludes_from_list(self):
        """软删除后不出现在列表中"""
        obj = _make_reminder(self.user)
        self.client.delete(f'/reminder/{obj.id}/')
        resp = self.client.get('/reminder/')
        body = resp.json()
        self.assertEqual(len(body['data']), 0)

    def test_soft_delete_preserves_db_record(self):
        """软删除后数据库记录仍然存在"""
        obj = _make_reminder(self.user)
        self.client.delete(f'/reminder/{obj.id}/')
        self.assertTrue(Reminder.objects.all_with_deleted().filter(pk=obj.pk).exists())
        obj = Reminder.objects.all_with_deleted().get(pk=obj.pk)
        self.assertTrue(obj.is_deleted)

    def test_double_delete(self):
        """重复删除已删除提醒"""
        obj = _make_reminder(self.user)
        self.client.delete(f'/reminder/{obj.id}/')
        resp = self.client.delete(f'/reminder/{obj.id}/')
        self.assertTrue(resp.json().get('error'))

    def test_deleted_reminder_logs_preserved(self):
        """软删除提醒后关联的 log 仍然保留（不级联删除）"""
        obj = _make_reminder(self.user)
        log = ReminderLog.objects.create(
            reminder=obj, user_id=self.user.id, user_name=self.user.nickname,
            date_key=date.today().strftime('%Y-%m-%d'),
        )
        self.client.delete(f'/reminder/{obj.id}/')
        self.assertTrue(ReminderLog.objects.filter(pk=log.pk).exists())
