# -*- coding: utf-8 -*-
"""规律调查生命周期契约测试（2026-10-26 三态收敛）。

业务方案（2026-10-26 拍板）：
- 干扰事件是独立事实：不自动创建调查、不显示调查状态；
- 调查只由用户从选中记录主动发起，保存后直接为 investigating（调查中），
  不设草稿；生命周期只保留 investigating/ended/cancelled；
- 「结束调查」「取消调查」是仅有的两个状态变更动作（专用端点），
  通用 POST/PUT/PATCH 一律拒绝 status/result/cancel_reason 键（fail-closed）；
- 结束必须提交 result（found/not_found/undetermined）+ 非空 conclusion，
  可选 end_at（缺省当前时间）；取消必须提交非空 cancel_reason；
- 两个动作均要求 INVESTIGATION_EDIT_PERMISSION 并记录变更前后审计。
"""

import json

from django.test import TestCase

from apps.interference.models import (
    InterferenceInvestigation,
    InvestigationEvent,
)
from apps.logs.models import AuditLog
from apps.utils.test_helpers import make_client, make_user, setup_test_env

P_EVENT_VIEW = 'interference.interference.view'
P_EVENT_ADD = 'interference.interference.add'
P_INV_VIEW = 'interference.investigation.view'
P_INV_ADD = 'interference.investigation.add'
P_INV_EDIT = 'interference.investigation.edit'

INV_EDIT_PERMS = [P_EVENT_VIEW, P_EVENT_ADD, P_INV_VIEW, P_INV_ADD, P_INV_EDIT]
INV_VIEW_ONLY_PERMS = [P_EVENT_VIEW, P_INV_VIEW]

EVENTS_URL = '/interference/events/'
INVESTIGATIONS_URL = '/interference/investigations/'


def biz(response):
    """解析响应业务载荷；非 JSON 响应（如端点不存在 404）返回空 dict。"""
    try:
        return json.loads(response.content)
    except (TypeError, ValueError):
        return {}


def ok_data(response):
    payload = biz(response)
    assert not payload.get('error'), payload
    return payload.get('data') or {}


def err(response):
    return biz(response).get('error') or ''


def _event_payload(seq=0, **overrides):
    """事件负载：seq 保证同测试内 datetime/航班号不撞重复提交窗口。"""
    payload = {
        'datetime': '2026-10-2%d 09:%02d:00' % (seq % 10, (seq * 7) % 60),
        'scene_code': 'ground',
        'phenomenon': '通信杂音',
        'flight_number': 'CA%d' % (1000 + seq),
    }
    payload.update(overrides)
    return payload


class InvestigationLifecycleTestBase(TestCase):

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inv_life_owner', INV_EDIT_PERMS)
        self.client_auth = make_client(self.user)

    def _create_event(self, seq=0, **overrides):
        data = ok_data(self.client_auth.post(
            EVENTS_URL, _event_payload(seq, **overrides),
            content_type='application/json'))
        return data['id']

    def _create_investigation(self, event_ids=(), name='规律调查', **overrides):
        payload = {'name': name, 'event_ids': list(event_ids)}
        payload.update(overrides)
        return self.client_auth.post(
            INVESTIGATIONS_URL, payload, content_type='application/json')

    def _finish_url(self, pk):
        return '%s%d/finish/' % (INVESTIGATIONS_URL, pk)

    def _cancel_url(self, pk):
        return '%s%d/cancel/' % (INVESTIGATIONS_URL, pk)


class InvestigationStandaloneTest(InvestigationLifecycleTestBase):
    """事件独立存在：不自动创建调查，列表不显示调查状态。"""

    def test_create_event_stands_alone(self):
        event_id = self._create_event(seq=1)
        self.assertTrue(event_id)
        self.assertFalse(InvestigationEvent.objects.exists())
        self.assertFalse(InterferenceInvestigation.objects.exists())
        data = ok_data(self.client_auth.get(EVENTS_URL))
        row = next(item for item in data['records'] if item['id'] == event_id)
        self.assertEqual(row.get('investigations'), [])


class InvestigationCreateTest(InvestigationLifecycleTestBase):
    """调查创建：从选中事件发起，保存后直接调查中，不设草稿。"""

    def test_create_investigation_from_selected_events(self):
        event_id = self._create_event(seq=2)
        data = ok_data(self._create_investigation([event_id], name='同频干扰排查'))
        self.assertEqual(data['status'], 'investigating')
        self.assertEqual(data['status_text'], '调查中')
        investigation = InterferenceInvestigation.objects.get(name='同频干扰排查')
        self.assertEqual(investigation.status, 'investigating')
        self.assertTrue(InvestigationEvent.objects.filter(
            investigation_id=investigation.id, event_id=event_id,
            is_deleted=False).exists())
        detail = ok_data(self.client_auth.get(
            '%s%d/' % (INVESTIGATIONS_URL, investigation.id)))
        self.assertIn(event_id, [item['id'] for item in detail['events']])

    def test_create_rejects_client_status(self):
        response = self._create_investigation([], name='带状态调查', status='draft')
        self.assertTrue(err(response))
        self.assertFalse(
            InterferenceInvestigation.objects.filter(name='带状态调查').exists())


class InvestigationFinishTest(InvestigationLifecycleTestBase):
    """结束调查：result + conclusion 必填，状态机与审计。"""

    def _create_investigating(self):
        return ok_data(self._create_investigation([]))['id']

    def test_finish_requires_result_and_conclusion(self):
        investigation_id = self._create_investigating()
        finish_url = self._finish_url(investigation_id)
        invalid_payloads = (
            {'conclusion': '只有结论'},
            {'result': 'bogus', 'conclusion': '结论'},
            {'result': 'not_found'},
            {},
        )
        for payload in invalid_payloads:
            response = self.client_auth.post(
                finish_url, payload, content_type='application/json')
            self.assertTrue(err(response), payload)
        investigation = InterferenceInvestigation.objects.get(pk=investigation_id)
        self.assertEqual(investigation.status, 'investigating')
        self.assertEqual(investigation.result, '')
        data = ok_data(self.client_auth.post(
            finish_url, {'result': 'not_found', 'conclusion': '未发现规律来源'},
            content_type='application/json'))
        self.assertEqual(data['status'], 'ended')
        self.assertEqual(data['result'], 'not_found')
        self.assertEqual(data['result_text'], '未发现规律')
        self.assertTrue(data['end_at'])
        investigation.refresh_from_db()
        self.assertEqual(investigation.status, 'ended')
        self.assertEqual(investigation.result, 'not_found')
        audit = AuditLog.objects.filter(
            action='update', target_type='interference_investigation',
            target_id=str(investigation_id)).order_by('-id').first()
        self.assertIsNotNone(audit)
        detail = json.loads(audit.detail)
        self.assertEqual(detail.get('after', {}).get('status'), 'ended')
        self.assertEqual(detail.get('after', {}).get('result'), 'not_found')

    def test_finish_sets_given_end_at(self):
        investigation_id = self._create_investigating()
        data = ok_data(self.client_auth.post(
            self._finish_url(investigation_id),
            {'result': 'found', 'conclusion': '已定位干扰源',
             'end_at': '2026-10-25 18:00:00'},
            content_type='application/json'))
        self.assertEqual(data['status'], 'ended')
        investigation = InterferenceInvestigation.objects.get(pk=investigation_id)
        self.assertEqual(
            investigation.end_at.strftime('%Y-%m-%d %H:%M:%S'),
            '2026-10-25 18:00:00')

    def test_finish_only_from_investigating(self):
        ended_id = InterferenceInvestigation.objects.create(
            tenant_id=self.user.tenant_id, name='已结束调查', status='ended',
            result='found', conclusion='已有结论', created_by=self.user).id
        cancelled_id = InterferenceInvestigation.objects.create(
            tenant_id=self.user.tenant_id, name='已取消调查', status='cancelled',
            cancel_reason='重复建项', created_by=self.user).id
        for pk in (ended_id, cancelled_id):
            response = self.client_auth.post(
                self._finish_url(pk),
                {'result': 'not_found', 'conclusion': '再结一次'},
                content_type='application/json')
            self.assertTrue(err(response), pk)
        ended = InterferenceInvestigation.objects.get(pk=ended_id)
        cancelled = InterferenceInvestigation.objects.get(pk=cancelled_id)
        self.assertEqual(ended.status, 'ended')
        self.assertEqual(ended.result, 'found')
        self.assertEqual(ended.conclusion, '已有结论')
        self.assertEqual(cancelled.status, 'cancelled')
        self.assertEqual(cancelled.cancel_reason, '重复建项')

    def test_finish_duplicate_submit_rejected(self):
        investigation_id = self._create_investigating()
        finish_url = self._finish_url(investigation_id)
        ok_data(self.client_auth.post(
            finish_url, {'result': 'found', 'conclusion': '首次结论'},
            content_type='application/json'))
        second = self.client_auth.post(
            finish_url, {'result': 'not_found', 'conclusion': '二次提交'},
            content_type='application/json')
        self.assertTrue(err(second))
        investigation = InterferenceInvestigation.objects.get(pk=investigation_id)
        self.assertEqual(investigation.status, 'ended')
        self.assertEqual(investigation.result, 'found')
        self.assertEqual(investigation.conclusion, '首次结论')

    def test_finish_cancel_need_edit_permission(self):
        investigation_id = self._create_investigating()
        viewer = make_user('inv_life_viewer', INV_VIEW_ONLY_PERMS)
        viewer_client = make_client(viewer)
        response = viewer_client.post(
            self._finish_url(investigation_id),
            {'result': 'found', 'conclusion': '越权结论'},
            content_type='application/json')
        self.assertEqual(err(response), '权限拒绝')
        response = viewer_client.post(
            self._cancel_url(investigation_id), {'cancel_reason': '越权取消'},
            content_type='application/json')
        self.assertEqual(err(response), '权限拒绝')
        investigation = InterferenceInvestigation.objects.get(pk=investigation_id)
        self.assertEqual(investigation.status, 'investigating')

    def test_cross_tenant_actions_rejected(self):
        investigation_id = self._create_investigating()
        outsider = make_user('inv_life_outsider', INV_EDIT_PERMS)
        outsider.tenant_id = 'tenant-outsider-b'
        outsider.save(update_fields=['tenant_id'])
        outsider_client = make_client(outsider)
        response = outsider_client.post(
            self._finish_url(investigation_id),
            {'result': 'found', 'conclusion': '跨租户结论'},
            content_type='application/json')
        self.assertTrue(err(response))
        response = outsider_client.post(
            self._cancel_url(investigation_id), {'cancel_reason': '跨租户取消'},
            content_type='application/json')
        self.assertTrue(err(response))
        investigation = InterferenceInvestigation.objects.get(pk=investigation_id)
        self.assertEqual(investigation.status, 'investigating')


class InvestigationCancelTest(InvestigationLifecycleTestBase):
    """取消调查：cancel_reason 必填，只能取消调查中的调查。"""

    def test_cancel_requires_reason(self):
        investigation_id = ok_data(self._create_investigation([]))['id']
        cancel_url = '%s%d/cancel/' % (INVESTIGATIONS_URL, investigation_id)
        for payload in ({}, {'cancel_reason': ''}, {'cancel_reason': '   '}):
            response = self.client_auth.post(
                cancel_url, payload, content_type='application/json')
            self.assertTrue(err(response), payload)
        investigation = InterferenceInvestigation.objects.get(pk=investigation_id)
        self.assertEqual(investigation.status, 'investigating')
        data = ok_data(self.client_auth.post(
            cancel_url, {'cancel_reason': '误建重复调查'},
            content_type='application/json'))
        self.assertEqual(data['status'], 'cancelled')
        investigation.refresh_from_db()
        self.assertEqual(investigation.status, 'cancelled')
        self.assertEqual(investigation.cancel_reason, '误建重复调查')
        self.assertTrue(AuditLog.objects.filter(
            action='update', target_type='interference_investigation',
            target_id=str(investigation_id)).exists())

    def test_cancel_only_from_investigating(self):
        ended_id = InterferenceInvestigation.objects.create(
            tenant_id=self.user.tenant_id, name='结束后再取消', status='ended',
            result='found', conclusion='已有结论', created_by=self.user).id
        response = self.client_auth.post(
            '%s%d/cancel/' % (INVESTIGATIONS_URL, ended_id),
            {'cancel_reason': '不该被取消'}, content_type='application/json')
        self.assertTrue(err(response))
        ended = InterferenceInvestigation.objects.get(pk=ended_id)
        self.assertEqual(ended.status, 'ended')
        self.assertEqual(ended.cancel_reason, '')


class InvestigationUpdateGuardTest(InvestigationLifecycleTestBase):
    """通用编辑路径 fail-closed：状态与动作字段只能走专用端点。"""

    def test_update_rejects_status_and_action_fields(self):
        investigation_id = ok_data(self._create_investigation([]))['id']
        detail_url = '%s%d/' % (INVESTIGATIONS_URL, investigation_id)
        rejected_payloads = (
            ({'status': 'ended'}, '结束调查'),
            ({'status': 'cancelled'}, '取消调查'),
            ({'result': 'found'}, '结束调查'),
            ({'cancel_reason': 'x'}, '取消调查'),
        )
        for payload, keyword in rejected_payloads:
            response = self.client_auth.put(
                detail_url, payload, content_type='application/json')
            error = err(response)
            self.assertTrue(error, payload)
            self.assertIn(keyword, error, payload)
        investigation = InterferenceInvestigation.objects.get(pk=investigation_id)
        self.assertEqual(investigation.status, 'investigating')
        data = ok_data(self.client_auth.put(
            detail_url, {'owner': '张三'}, content_type='application/json'))
        self.assertEqual(data['owner'], '张三')
        investigation.refresh_from_db()
        self.assertEqual(investigation.owner, '张三')
        self.assertEqual(investigation.status, 'investigating')


class EventListAssociationTest(InvestigationLifecycleTestBase):
    """事件列表：显示关联调查摘要数组，不再输出单值调查状态。"""

    def test_event_list_shows_association_info(self):
        event_id = self._create_event(seq=4)
        ok_data(self._create_investigation([event_id], name='调查甲'))
        second = ok_data(self._create_investigation([event_id], name='调查乙'))
        ok_data(self.client_auth.post(
            '%s%d/finish/' % (INVESTIGATIONS_URL, second['id']),
            {'result': 'undetermined', 'conclusion': '证据不足暂无法确认'},
            content_type='application/json'))
        data = ok_data(self.client_auth.get(EVENTS_URL))
        row = next(item for item in data['records'] if item['id'] == event_id)
        self.assertIn('investigation_ids', row)
        self.assertNotIn('investigation_status', row)
        investigations = row['investigations']
        self.assertEqual(len(investigations), 2)
        by_status = {item['status']: item for item in investigations}
        self.assertEqual(set(by_status), {'investigating', 'ended'})
        self.assertEqual(by_status['investigating']['status_text'], '调查中')
        self.assertEqual(by_status['ended']['status_text'], '已结束')
        for item in investigations:
            self.assertTrue(
                {'id', 'name', 'status', 'status_text'} <= set(item), item)
            self.assertTrue(item['name'], item)
        names = {item['name'] for item in investigations}
        self.assertEqual(names, {'调查甲', '调查乙'})
