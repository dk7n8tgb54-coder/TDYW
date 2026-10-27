# -*- coding: utf-8 -*-
"""回归测试（2026-10-25）：调查事件关联事务完整性、权限契约与列表 N+1。

覆盖三项问题：
1. 批量关联事件中途遇到重复关联时，接口报错但此前已创建的关联随事务
   一起提交（InvestigationEventsView.post 在 atomic 块内直接 return
   json_response(error=...)，未回滚）。修复后报错必须整体回滚。
2. 调查列表逐条 to_view 的 N+1：每个调查 3 次查询（关联/地面明细/空中
   明细），查询数随页内行数线性增长。修复后查询数与行数无关。
3. 权限契约文档化：调查创建/事件关联/测量新增的后端 OR 权限组合口径
   （与前端按钮权限串的口径差异在汇报中列为待确认决策，本测试固定后端
   行为，防止无意识变更）。
"""
import json
from datetime import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.interference.models import (
    AirInterferenceDetail,
    GroundInterferenceDetail,
    InterferenceEvent,
    InterferenceInvestigation,
    InvestigationEvent,
    SpectrumMeasurement,
)
from apps.utils.test_helpers import make_client, make_user, setup_test_env

P_EVENT_VIEW = 'interference.interference.view'
P_EVENT_ADD = 'interference.interference.add'
P_EVENT_EDIT = 'interference.interference.edit'
P_INV_VIEW = 'interference.investigation.view'
P_INV_ADD = 'interference.investigation.add'
P_INV_EDIT = 'interference.investigation.edit'
P_MEAS_VIEW = 'interference.measurement.view'
P_MEAS_ADD = 'interference.measurement.add'
P_MEAS_EDIT = 'interference.measurement.edit'


def _make_event(user, **overrides):
    defaults = dict(
        tenant_id=user.tenant_id, datetime=datetime(2026, 10, 20, 9, 0),
        scene_code='ground', phenomenon='杂音', created_by=user)
    defaults.update(overrides)
    return InterferenceEvent.objects.create(**defaults)


class InvestigationLinkAtomicityTest(TestCase):
    """问题2：批量关联中途重复时必须整体回滚。"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('interference_link_tx', [
            P_EVENT_VIEW, P_EVENT_ADD, P_INV_VIEW, P_INV_EDIT])
        self.client_auth = make_client(self.user)
        self.investigation = InterferenceInvestigation.objects.create(
            tenant_id=self.user.tenant_id, name='原子性调查',
            created_by=self.user)
        # fresh 先建且发生时间更晚：InterferenceEvent 默认排序 -datetime, -id，
        # 保证 _link_events 的批量循环先处理新事件（创建关联）、后命中重复
        self.fresh = _make_event(self.user, phenomenon='新事件甲',
                                 datetime=datetime(2026, 10, 21, 9, 0))
        self.linked = _make_event(self.user, phenomenon='已关联事件')
        response = self.client_auth.post(
            '/interference/investigations/%d/events/' % self.investigation.id,
            {'event_ids': [self.linked.id]}, content_type='application/json')
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)

    def _link(self, event_ids):
        return self.client_auth.post(
            '/interference/investigations/%d/events/' % self.investigation.id,
            {'event_ids': event_ids}, content_type='application/json')

    def test_duplicate_midway_rolls_back_earlier_links(self):
        response = self._link([self.fresh.id, self.linked.id])
        data = json.loads(response.content)
        self.assertIn('重复关联', data.get('error', ''), response.content)
        # 修复前：报错的同时 fresh 的关联已经随事务提交
        self.assertFalse(
            InvestigationEvent.objects.filter(
                investigation=self.investigation, event=self.fresh).exists(),
            '接口报错但新事件的关联已被提交（事务未回滚）')
        # 已有关联不受影响
        self.assertTrue(
            InvestigationEvent.objects.filter(
                investigation=self.investigation, event=self.linked,
                is_deleted=False).exists())

    def test_valid_batch_still_links_all(self):
        """护栏：无重复的批量关联仍然全部成功。"""
        other = _make_event(self.user, phenomenon='新事件乙')
        response = self._link([self.fresh.id, other.id])
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)
        self.assertEqual(
            InvestigationEvent.objects.filter(
                investigation=self.investigation, is_deleted=False).count(), 3)

    def test_create_investigation_with_bad_event_ids_is_atomic(self):
        """护栏：创建调查携带不可关联的 event_ids 时整体回滚（既有 set_rollback 路径）。"""
        response = self.client_auth.post(
            '/interference/investigations/', {
                'name': '创建即关联调查',
                'event_ids': [self.fresh.id, 999999],
            }, content_type='application/json')
        self.assertTrue(json.loads(response.content).get('error'))
        self.assertFalse(InterferenceInvestigation.objects.filter(
            name='创建即关联调查').exists())


class InvestigationListQueryCountTest(TestCase):
    """问题5：调查列表序列化的查询数不得随页内行数线性增长。"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('interference_nplus1', [
            P_EVENT_VIEW, P_INV_VIEW])
        self.client_auth = make_client(self.user)
        for index in range(12):
            investigation = InterferenceInvestigation.objects.create(
                tenant_id=self.user.tenant_id, name='调查%02d' % index,
                created_by=self.user)
            for event_index in range(2):
                event = _make_event(
                    self.user, phenomenon='调查%02d事件%d' % (index, event_index))
                GroundInterferenceDetail.objects.create(
                    event=event, tenant_id=self.user.tenant_id,
                    location='机坪%02d' % index, frequency='118.%d' % event_index)
                AirInterferenceDetail.objects.create(
                    event=_make_event(self.user, scene_code='air'),
                    tenant_id=self.user.tenant_id, route='HFE-VVO',
                    alert_frequency='118.6')
                InvestigationEvent.objects.create(
                    tenant_id=self.user.tenant_id, investigation=investigation,
                    event=event, created_by=self.user)

    def test_list_query_count_does_not_scale_with_rows(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client_auth.get('/interference/investigations/',
                                            {'page': 1, 'page_size': 20})
        data = json.loads(response.content)
        self.assertFalse(data.get('error'), response.content)
        self.assertEqual(len(data['data']['records']), 12)
        # 修复前：每个调查 to_view 触发 3 次查询（关联+地面+空中），12 行实测
        # 49 次；修复后批量序列化只剩每页固定 3 次批量查询。请求路径本身有
        # 与行数无关的固定开销（认证中间件刷新 token 的 user.save()、权限
        # 版本核对、租户范围 exists 检查），本环境实测固定开销 13 条 + 3 条
        # 批量查询 = 16 条，阈值取 20 防止夹具抖动；若 N+1 复发 12 行至少
        # 再加 36 条，必然击穿阈值。
        self.assertLess(
            len(ctx.captured_queries), 20,
            '调查列表查询数随行数线性增长（N+1）：%d 条查询' % len(ctx.captured_queries))
        # 行数无关性固化：单行页与 12 行页查询数必须完全相等（N+1 时单行页
        # 比 12 行页少 3 的倍数条查询，等值断言直接击穿）。
        with CaptureQueriesContext(connection) as ctx_one_row:
            response_one = self.client_auth.get('/interference/investigations/',
                                                {'page': 1, 'page_size': 1})
        data_one = json.loads(response_one.content)
        self.assertFalse(data_one.get('error'), response_one.content)
        self.assertEqual(len(data_one['data']['records']), 1)
        self.assertEqual(
            len(ctx_one_row.captured_queries), len(ctx.captured_queries),
            '查询数随页内行数变化：%d 行页 %d 条 vs 1 行页 %d 条' % (
                len(data['data']['records']), len(ctx.captured_queries),
                len(ctx_one_row.captured_queries)))


class InvestigationPermissionMatrixTest(TestCase):
    """问题3：后端权限 OR 组合契约文档化（口径差异见汇报待确认决策）。

    后端现状口径：
    - 创建调查 POST /investigations/：investigation.add 或 interference.add；
    - 关联事件 POST /investigations/<pk>/events/：investigation.edit 或
      interference.add；
    - 录入测量 POST /investigations/<pk>/measurements/：measurement.add 或
      investigation.edit。
    """

    def _user(self, username, perms):
        setup_test_env(self)
        user = make_user(username, perms)
        self.client_auth = make_client(user)
        return user

    def _create_investigation(self):
        return self.client_auth.post(
            '/interference/investigations/', {'name': '契约调查'},
            content_type='application/json')

    def test_event_add_user_can_create_investigation_and_link_events(self):
        user = self._user('perm_event_add', [P_EVENT_VIEW, P_EVENT_ADD])
        event = _make_event(user)
        response = self._create_investigation()
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)
        investigation_id = json.loads(response.content)['data']['id']
        response = self.client_auth.post(
            '/interference/investigations/%d/events/' % investigation_id,
            {'event_ids': [event.id]}, content_type='application/json')
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)

    def test_event_add_user_cannot_edit_or_measure(self):
        user = self._user('perm_event_add_ro', [P_EVENT_VIEW, P_EVENT_ADD])
        investigation = InterferenceInvestigation.objects.create(
            tenant_id=user.tenant_id, name='不可编辑调查', created_by=user)
        response = self.client_auth.put(
            '/interference/investigations/%d/' % investigation.id,
            {'name': '尝试改名'}, content_type='application/json')
        self.assertEqual(json.loads(response.content).get('error'), '权限拒绝')
        response = self.client_auth.post(
            '/interference/investigations/%d/measurements/' % investigation.id,
            {'measured_at': '2026-10-25 10:00:00'},
            content_type='application/json')
        self.assertEqual(json.loads(response.content).get('error'), '权限拒绝')

    def test_investigation_edit_user_can_link_and_measure(self):
        user = self._user('perm_inv_edit', [P_EVENT_VIEW, P_INV_EDIT])
        investigation = InterferenceInvestigation.objects.create(
            tenant_id=user.tenant_id, name='可编辑调查', created_by=user)
        event = _make_event(user)
        response = self.client_auth.post(
            '/interference/investigations/%d/events/' % investigation.id,
            {'event_ids': [event.id]}, content_type='application/json')
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)
        response = self.client_auth.post(
            '/interference/investigations/%d/measurements/' % investigation.id,
            {'measured_at': '2026-10-25 10:00:00'},
            content_type='application/json')
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)
        self.assertTrue(SpectrumMeasurement.objects.filter(
            investigation=investigation).exists())

    def test_investigation_edit_user_cannot_create_investigation(self):
        self._user('perm_inv_edit_only', [P_INV_VIEW, P_INV_EDIT])
        response = self._create_investigation()
        self.assertEqual(json.loads(response.content).get('error'), '权限拒绝')

    def test_measurement_add_user_can_add_measurement(self):
        user = self._user('perm_meas_add', [P_INV_VIEW, P_MEAS_VIEW, P_MEAS_ADD])
        investigation = InterferenceInvestigation.objects.create(
            tenant_id=user.tenant_id, name='可测量调查', created_by=user)
        response = self.client_auth.post(
            '/interference/investigations/%d/measurements/' % investigation.id,
            {'measured_at': '2026-10-25 10:00:00'},
            content_type='application/json')
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)

    def test_permissionless_user_rejected_everywhere(self):
        user = self._user('perm_none', [])
        investigation = InterferenceInvestigation.objects.create(
            tenant_id=user.tenant_id, name='无权调查', created_by=user)
        cases = [
            ('post', '/interference/investigations/', {'name': 'x'}),
            ('post', '/interference/investigations/%d/events/' % investigation.id,
             {'event_ids': [1]}),
            ('post', '/interference/investigations/%d/measurements/' % investigation.id,
             {'measured_at': '2026-10-25 10:00:00'}),
        ]
        for method, url, body in cases:
            response = getattr(self.client_auth, method)(url, body,
                                                         content_type='application/json')
            self.assertEqual(json.loads(response.content).get('error'), '权限拒绝',
                             '%s %s: %s' % (method, url, response.content))

    def test_event_add_only_user_can_create_and_link_but_not_measure(self):
        """后端 OR 组合第二支固化：仅 interference.add 可创建调查并关联事件。

        前端"创建调查"/"加入已有调查"按钮只认 investigation.add/edit，本用例
        固化后端对 interference.add 用户的额外放行（口径差异见汇报待确认
        决策 D1/D2）；同时固化其不能录入测量（无 measurement.add 且无
        investigation.edit）。
        """
        user = self._user('perm_event_add_only', [P_EVENT_VIEW, P_EVENT_ADD])
        event = _make_event(user)
        response = self._create_investigation()
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)
        investigation_id = json.loads(response.content)['data']['id']
        response = self.client_auth.post(
            '/interference/investigations/%d/events/' % investigation_id,
            {'event_ids': [event.id]}, content_type='application/json')
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)
        response = self.client_auth.post(
            '/interference/investigations/%d/measurements/' % investigation_id,
            {'measured_at': '2026-10-25 10:00:00'},
            content_type='application/json')
        self.assertEqual(json.loads(response.content).get('error'), '权限拒绝')

    def test_measurement_edit_only_user_cannot_add_measurement(self):
        """固化 measurement.edit 不在创建测量的 OR 组合内（仅编辑既有测量）。"""
        user = self._user('perm_meas_edit_only', [P_INV_VIEW, P_MEAS_VIEW,
                                                  P_MEAS_EDIT])
        investigation = InterferenceInvestigation.objects.create(
            tenant_id=user.tenant_id, name='仅测量编辑调查', created_by=user)
        response = self.client_auth.post(
            '/interference/investigations/%d/measurements/' % investigation.id,
            {'measured_at': '2026-10-25 10:00:00'},
            content_type='application/json')
        self.assertEqual(json.loads(response.content).get('error'), '权限拒绝')
        self.assertFalse(SpectrumMeasurement.objects.filter(
            investigation=investigation).exists())

    def test_measurement_add_only_user_cannot_link_events(self):
        """固化 measurement.add 不能关联事件（无 investigation.edit/interference.add）。"""
        user = self._user('perm_meas_add_only', [P_INV_VIEW, P_MEAS_VIEW,
                                                 P_MEAS_ADD])
        investigation = InterferenceInvestigation.objects.create(
            tenant_id=user.tenant_id, name='仅测量新增调查', created_by=user)
        event = _make_event(user)
        response = self.client_auth.post(
            '/interference/investigations/%d/events/' % investigation.id,
            {'event_ids': [event.id]}, content_type='application/json')
        self.assertEqual(json.loads(response.content).get('error'), '权限拒绝')
        self.assertFalse(InvestigationEvent.objects.filter(
            investigation=investigation).exists())
