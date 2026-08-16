# -*- coding: utf-8 -*-
"""提醒事项模块缺陷复现/修复验证测试

缺陷背景（视图层表单校验缺口，修复前触发数据库异常并落入全局异常中间件）：

1. repeat_type='none' 时 repeat_interval=0/负数绕过校验
   （models.CheckConstraint ck_reminder_interval_gte1 触发 IntegrityError）
2. repeat_interval 超出数据库 INT 上限（MariaDB 严格模式 Out of range）
3. name 超过 CharField(max_length=100)
   （前端 Input 未设 maxLength，普通用户在 UI 即可触发）

本文件断言修复后的正确行为：业务错误必须由视图层校验返回（错误文案指向具体字段），
而不是触发数据库异常、落入全局异常中间件（其返回通用文案"服务器内部错误，
请联系管理员"并误发 500 告警），且不产生脏数据。
"""
import json

from django.test import TestCase

from apps.reminder.models import Reminder
from apps.reminder.tests.characterization.test_reminder import (
    REMINDER_PERMS,
    _grant_perms,
    _make_reminder,
    _make_client,
    _make_user,
)
from apps.utils.test_helpers import setup_test_env

GENERIC_ERROR = '服务器内部错误，请联系管理员'


class ReminderFormValidationGapTests(TestCase):
    """表单校验缺口：非法入参必须返回具体业务错误而非数据库异常兜底"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, REMINDER_PERMS)
        self.client = _make_client(self.user)
        # 视图内未处理异常以 500 响应返回而非直接抛出，便于断言真实 HTTP 行为
        self.client.raise_request_exception = False
        self.recipients = json.dumps([{'id': self.user.id, 'nickname': self.user.nickname}])

    def _post(self, data, pk=None):
        url = f'/reminder/{pk}/' if pk else '/reminder/'
        return self.client.post(url, data=json.dumps(data), content_type='application/json')

    def _payload(self, **overrides):
        payload = {
            'name': '测试提醒',
            'target_date': '2026-08-08',
            'recipient_users': self.recipients,
        }
        payload.update(overrides)
        return payload

    def _assert_field_error(self, resp, keyword):
        """断言错误来自视图层校验：指向具体字段，而非异常中间件的通用文案"""
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        error = body.get('error')
        self.assertTrue(error)
        self.assertIn(keyword, error)
        self.assertNotEqual(error, GENERIC_ERROR)

    # ---------- repeat_interval 下界（none 类型此前不校验） ----------

    def test_create_none_with_zero_interval(self):
        """none + repeat_interval=0 必须返回具体校验错误（原为 IntegrityError 兜底）"""
        resp = self._post(self._payload(repeat_type='none', repeat_interval=0))
        self._assert_field_error(resp, '重复间隔')
        self.assertFalse(Reminder.objects.filter(name='测试提醒').exists())

    def test_create_default_type_with_zero_interval(self):
        """不传 repeat_type（默认 none）+ repeat_interval=0 同样必须拦截"""
        resp = self._post(self._payload(repeat_interval=0))
        self._assert_field_error(resp, '重复间隔')
        self.assertFalse(Reminder.objects.filter(name='测试提醒').exists())

    def test_create_none_with_negative_interval(self):
        """none + repeat_interval=-1 必须返回具体校验错误"""
        resp = self._post(self._payload(repeat_type='none', repeat_interval=-1))
        self._assert_field_error(resp, '重复间隔')
        self.assertFalse(Reminder.objects.filter(name='测试提醒').exists())

    def test_update_none_with_zero_interval(self):
        """更新路径同样拦截：none + repeat_interval=0 返回校验错误且数据不变"""
        obj = _make_reminder(self.user)
        resp = self._post(self._payload(repeat_type='none', repeat_interval=0), pk=obj.id)
        self._assert_field_error(resp, '重复间隔')
        obj.refresh_from_db()
        self.assertEqual(obj.repeat_interval, 1)

    # ---------- repeat_interval 上界（数据库 INT 溢出） ----------

    def test_create_huge_interval(self):
        """repeat_interval 超出 INT 上限必须返回校验错误（原为 Out of range 兜底）"""
        resp = self._post(self._payload(repeat_type='daily', repeat_interval=2147483648))
        self._assert_field_error(resp, '重复间隔')
        self.assertFalse(Reminder.objects.filter(name='测试提醒').exists())

    def test_update_huge_interval(self):
        """更新路径同样拦截 INT 溢出"""
        obj = _make_reminder(self.user)
        resp = self._post(self._payload(repeat_type='daily', repeat_interval=2147483648), pk=obj.id)
        self._assert_field_error(resp, '重复间隔')
        obj.refresh_from_db()
        self.assertEqual(obj.repeat_interval, 1)

    # ---------- name 长度（CharField max_length=100，前端 Input 无 maxLength） ----------

    def test_create_name_too_long(self):
        """name 超过 100 字符必须返回校验错误（原为 Data too long 兜底）"""
        resp = self._post(self._payload(name='长' * 101))
        self._assert_field_error(resp, '事件名称')
        self.assertFalse(Reminder.objects.filter(name='长' * 101).exists())

    def test_update_name_too_long(self):
        """更新路径同样拦截超长 name"""
        obj = _make_reminder(self.user)
        resp = self._post(self._payload(name='长' * 101), pk=obj.id)
        self._assert_field_error(resp, '事件名称')
        obj.refresh_from_db()
        self.assertNotEqual(obj.name, '长' * 101)

    def test_create_name_boundary_100_chars(self):
        """name 恰好 100 字符应创建成功（边界不误伤）"""
        resp = self._post(self._payload(name='边' * 100))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.json().get('error'))
        self.assertTrue(Reminder.objects.filter(name='边' * 100).exists())

    def test_create_interval_boundary_365(self):
        """repeat_interval=365 应创建成功（与前端 InputNumber max 一致的边界）"""
        resp = self._post(self._payload(repeat_type='daily', repeat_interval=365))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.json().get('error'))
        obj = Reminder.objects.get(name='测试提醒')
        self.assertEqual(obj.repeat_interval, 365)


class ReminderValidationReturnContractTests(TestCase):
    """根因复现：post() 原以嵌套解包调用校验函数，所有校验错误路径
    均因 (target_date, recipients) = None 抛 TypeError，落入全局异常中间件，
    返回通用文案而非具体校验错误（既有特征测试仅断言 error 真值而未察觉）。
    """

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, REMINDER_PERMS)
        self.client = _make_client(self.user)
        self.client.raise_request_exception = False
        self.recipients = json.dumps([{'id': self.user.id, 'nickname': self.user.nickname}])

    def _post(self, data, pk=None):
        url = f'/reminder/{pk}/' if pk else '/reminder/'
        return self.client.post(url, data=json.dumps(data), content_type='application/json')

    def _payload(self, **overrides):
        payload = {
            'name': '测试提醒',
            'target_date': '2026-08-08',
            'recipient_users': self.recipients,
        }
        payload.update(overrides)
        return payload

    def _assert_field_error(self, resp, keyword):
        self.assertEqual(resp.status_code, 200, resp.content)
        error = resp.json().get('error')
        self.assertTrue(error)
        self.assertIn(keyword, error)
        self.assertNotEqual(error, GENERIC_ERROR)

    def test_invalid_target_date_format_message(self):
        """目标日格式错误必须返回具体文案（原为 TypeError 兜底）"""
        resp = self._post(self._payload(target_date='2026/08/08'))
        self._assert_field_error(resp, '目标日')
        self.assertFalse(Reminder.objects.filter(name='测试提醒').exists())

    def test_invalid_repeat_type_message(self):
        """非法重复类型必须返回具体文案（原为 TypeError 兜底）"""
        resp = self._post(self._payload(repeat_type='hourly'))
        self._assert_field_error(resp, '重复类型')

    def test_empty_recipients_message(self):
        """空接收人列表必须返回具体文案（原为 TypeError 兜底）"""
        resp = self._post(self._payload(recipient_users='[]'))
        self._assert_field_error(resp, '接收人')

    def test_malformed_recipients_message(self):
        """接收人元素缺 id 必须返回具体文案（原为 TypeError 兜底）"""
        resp = self._post(self._payload(recipient_users=json.dumps([{'nickname': 'x'}])))
        self._assert_field_error(resp, '接收人')

    def test_update_invalid_target_date_message(self):
        """更新路径的目标日格式错误同样返回具体文案"""
        obj = _make_reminder(self.user)
        resp = self._post(self._payload(target_date='bad-date'), pk=obj.id)
        self._assert_field_error(resp, '目标日')
        # 校验失败后原值不变（_make_reminder 默认 target_date=date.today()）
        obj.refresh_from_db()
        from datetime import date as date_cls
        self.assertEqual(obj.target_date, date_cls.today())
