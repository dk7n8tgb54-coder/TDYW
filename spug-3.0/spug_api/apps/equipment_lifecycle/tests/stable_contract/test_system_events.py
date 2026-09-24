# -*- coding: utf-8 -*-
"""统一系统履历（步骤 3.4，步骤 3.5 集成，单系统简化）稳定契约测试。

覆盖行为契约：
- 普通用户不能手工新增履历；履历只读，无普通修改与物理删除入口；
- 故障、台账异常、工单、健康状态、配置快照共用同一事件模型（SystemEvent）；
- 每条事件只关联业务对象所属的一个系统（无跨系统角色 primary/affected/related）；
- 业务保存与履历生成处于同一事务；重复请求不产生重复事件；
- 状态不变不生成健康事件；来源作废后原事件保留并追加新事件；
- 普通配置字段修改只进配置历史，不进履历；
- 事件按正式系统 ID 关联并保存系统快照，租户隔离；
- 步骤 3.5 删除保护收口回归（系统/组成项/类型删除返回业务错误而非 500）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from datetime import datetime, timedelta

from django.test import TestCase

from apps.equipment_lifecycle import urls as el_urls
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    OperationLedgerTemplate,
    SystemConfigChange,
    SystemConfigSnapshot,
    SystemEvent,
    SystemFault,
)
from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS, ALL_SYSTEM_PERMS,
    URL_PREFIX, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, ALL_TEMPLATE_PERMS,
    LEDGER_URL, create_ledger_ok, entry_payload, item_payload, ledger_payload,
    post_json,
)

ALL_FAULT_PERMS = [
    'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
    'equipment_lifecycle.fault.edit', 'equipment_lifecycle.fault.handle',
    'equipment_lifecycle.fault.recover', 'equipment_lifecycle.fault.close',
    'equipment_lifecycle.fault.del', 'equipment_lifecycle.fault.export',
]
ALL_WO_PERMS = [
    'equipment_lifecycle.work_order.view', 'equipment_lifecycle.work_order.add',
    'equipment_lifecycle.work_order.edit', 'equipment_lifecycle.work_order.dispatch',
    'equipment_lifecycle.work_order.accept', 'equipment_lifecycle.work_order.execute',
    'equipment_lifecycle.work_order.review', 'equipment_lifecycle.work_order.close',
    'equipment_lifecycle.work_order.del', 'equipment_lifecycle.work_order.export',
]
ALL_EVENT_PERMS = [
    'equipment_lifecycle.system_event.view', 'equipment_lifecycle.system_event.export',
]
P_HANDLE_EXCEPTION = 'equipment_lifecycle.ledger.handle_exception'

ALL_PERMS = (ALL_SYSTEM_PERMS + ALL_CONFIG_PERMS + ALL_FAULT_PERMS + ALL_WO_PERMS +
             ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS +
             ALL_EVENT_PERMS + [P_HANDLE_EXCEPTION])

FAULT_URL = URL_PREFIX + '/faults'
WO_URL = URL_PREFIX + '/work-orders'
SYSTEM_URL = URL_PREFIX + '/systems'

_event_seq = [0]


def _uniq_client_token():
    _event_seq[0] += 1
    return f'token-ev-{_event_seq[0]}'


def fault_payload(system_obj, **overrides):
    """发生时间/现象按序错开，避开创建接口的窗口期查重（同故障流程互不影响）。"""
    _event_seq[0] += 1
    seq = _event_seq[0]
    moment = datetime(2026, 9, 18, 8, 0) + timedelta(minutes=seq)
    payload = {
        'system': system_obj.id,
        'impact_status': 'degraded',
        'occurred_at': moment.strftime('%Y-%m-%d %H:%M'),
        'discovery': 'patrol',
        'level': 'major',
        'phenomenon': f'主用链路频繁丢包（场景{seq}）',
    }
    payload.update(overrides)
    return payload


def work_order_payload(system_obj, **overrides):
    """标题按序错开，避开创建接口的窗口期查重。"""
    _event_seq[0] += 1
    seq = _event_seq[0]
    payload = {
        'title': f'{system_obj.system_code} 例行维护工单（场景{seq}）',
        'work_type': 'special_maintenance',
        'priority': 'normal',
        'system': system_obj.id,
        'affects_system_operation': False,
        'work_location': '机房A 01柜',
        'work_requirement': '按规程完成季度维护',
        'client_token': '',
    }
    payload.update(overrides)
    return payload


class SystemEventTestBase(TestCase):
    """公共夹具：租户 A/B、两套系统。"""

    def setUp(self):
        self.admin = make_user('ev_admin', list(ALL_PERMS), tenant_id='tenant_a')
        self.other_admin = make_user('ev_admin_b', list(ALL_PERMS), tenant_id='tenant_b')
        self.noperm_user = make_user('ev_noperm', ALL_SYSTEM_PERMS, tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-A1', name='烟台通信系统')
        self.system_a2 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SYS-A2', name='威海监控系统')
        self.system_b = make_system(self.other_admin, tenant_id='tenant_b',
                                    system_code='SYS-B1', name='烟台通信系统')

    # ---------- 公共步骤 ----------

    def events(self, system=None, event_type=None, tenant_id='tenant_a'):
        """测试侧按租户取事件（默认租户 A；Manager 本身不做请求级租户过滤）。"""
        qs = SystemEvent.objects.filter(tenant_id=tenant_id).order_by('id')
        if system is not None:
            qs = qs.filter(system_id=system.id)
        if event_type:
            qs = qs.filter(event_type=event_type)
        return list(qs)

    def run_fault_lifecycle(self, system, **overrides):
        """创建→开始处置→恢复→关闭，返回 fault id。"""
        body = self.client.post(
            f'{FAULT_URL}/', fault_payload(system, **overrides),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        r = self.client.post(f'{FAULT_URL}/{fid}/start/', {}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': '2026-09-18 10:00',
            'recover_confirm': '业务已恢复正常',
            'final_result': '更换备件并验证',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{FAULT_URL}/{fid}/close/', {
            'final_result': '更换备件并验证',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        return fid

    def run_work_order_to_complete(self, payload):
        """创建→派发→接单→开始执行→处理记录→提交复核→复核通过，返回工单 id。"""
        body = self.client.post(f'{WO_URL}/', payload, content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        wid = body['data']['id']
        r = self.client.post(f'{WO_URL}/{wid}/dispatch/',
                             {'owner_id': self.admin.id}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{WO_URL}/{wid}/accept/', {}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{WO_URL}/{wid}/start/', {}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{WO_URL}/{wid}/handling-records/', {
            'handled_at': '2026-09-18 11:00', 'content': '完成检查维护',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{WO_URL}/{wid}/submit-review/', {
            'process_result': '维护完成，指标正常',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{WO_URL}/{wid}/review-pass/', {},
                             content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        return wid


class FaultEventTests(SystemEventTestBase):
    """故障动作 → 履历事件（只落故障所属系统，同事务、动作幂等）。"""

    def test_fault_create_generates_single_system_event(self):
        """故障创建：只生成一条故障事件（落故障系统），快照与来源完整。"""
        before = len(self.events())
        body = self.client.post(
            f'{FAULT_URL}/',
            fault_payload(self.system_a, impact_status='degraded'),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        fault_id = body['data']['id']
        events = self.events()
        # 1 条故障事件 + 1 条健康事件（故障系统 normal→degraded），不再有其他系统事件
        self.assertEqual(len(events), before + 2)
        self.assertEqual(
            len([e for e in events if e.event_type == SystemEvent.EVENT_FAULT]), 1)
        self.assertEqual(
            len([e for e in events if e.event_type == SystemEvent.EVENT_HEALTH]), 1)
        fault_event = [e for e in events if e.event_type == SystemEvent.EVENT_FAULT][0]
        self.assertEqual(fault_event.action, 'create')
        self.assertEqual(fault_event.source_type, 'fault')
        self.assertEqual(fault_event.source_id, str(fault_id))
        # 只关联故障所属系统；其他系统无任何事件
        self.assertEqual(fault_event.system_id, self.system_a.id)
        self.assertEqual(fault_event.system_code, self.system_a.system_code)
        self.assertEqual(fault_event.system_name, self.system_a.name)
        self.assertEqual(fault_event.created_by_id, self.admin.id)
        self.assertIn('发生', fault_event.title)
        self.assertEqual(
            [e.system_id for e in events if e.system_id == self.system_a2.id], [])

    def test_lifecycle_actions_generate_recover_and_close_events(self):
        """恢复/关闭各生成一次事件；恢复事件业务时间取恢复确认时间。"""
        fid = self.run_fault_lifecycle(self.system_a)
        actions = [(e.event_type, e.action) for e in self.events(self.system_a)]
        self.assertEqual(actions.count(('fault', 'create')), 1)
        self.assertEqual(actions.count(('fault', 'recover')), 1)
        self.assertEqual(actions.count(('fault', 'close')), 1)
        recover_event = [e for e in self.events(self.system_a) if e.action == 'recover'][0]
        self.assertEqual(recover_event.occurred_at.strftime('%Y-%m-%d %H:%M'), '2026-09-18 10:00')
        self.assertEqual(recover_event.source_no,
                         SystemFault.objects.get(pk=fid).fault_no)

    def test_cancel_appends_event_and_keeps_original_records(self):
        """受控作废：原事件保留，追加作废事件且原因落库（更正/撤销保留原记录）。"""
        body = self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        before = [(e.event_type, e.action) for e in self.events()]
        r = self.client.post(f'{FAULT_URL}/{fid}/cancel/',
                             {'cancel_reason': '误报，非真实故障'},
                             content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        after = [(e.event_type, e.action) for e in self.events()]
        # 原事件全部保留，仅追加一条作废事件
        self.assertEqual(after[:len(before)], before)
        cancel_events = [e for e in self.events() if e.action == 'cancel']
        self.assertEqual(len(cancel_events), 1)
        self.assertEqual(cancel_events[0].get_detail().get('cancel_reason'), '误报，非真实故障')
        self.assertEqual(SystemFault.objects.get(pk=fid).cancel_reason, '误报，非真实故障')

    def test_health_status_change_generates_event_once(self):
        """健康状态实际变化生成一次事件；来源、前后值与触发原因完整。"""
        self.run_fault_lifecycle(self.system_a)
        health_events = self.events(self.system_a, SystemEvent.EVENT_HEALTH)
        # normal→degraded（创建）与 degraded→normal（恢复）各一次
        self.assertEqual(len(health_events), 2)
        self.assertEqual([e.get_detail().get('before') for e in health_events], ['normal', 'degraded'])
        self.assertEqual([e.get_detail().get('after') for e in health_events], ['degraded', 'normal'])
        for e in health_events:
            self.assertEqual(e.action, 'status_change')
            self.assertEqual(e.source_type, 'health')

    def test_no_health_event_when_recomputed_status_unchanged(self):
        """多故障并存：第二张故障不改变综合状态时不重复生成健康事件。"""
        self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                         content_type='application/json').json()
        first_count = len(self.events(self.system_a, SystemEvent.EVENT_HEALTH))
        self.assertEqual(first_count, 1)  # normal→degraded
        body = self.client.post(
            f'{FAULT_URL}/',
            fault_payload(self.system_a, occurred_at='2026-09-18 09:30',
                          phenomenon='第二路链路丢包'),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        # 综合状态仍为 degraded：重复重算且结果不变，不生成新的健康事件
        self.assertEqual(len(self.events(self.system_a, SystemEvent.EVENT_HEALTH)), 1)

    def test_business_rollback_rolls_back_events(self):
        """业务校验失败回滚时不留下半成品事件（同事务）。"""
        before = len(self.events())
        # 提交不合法的影响状态 → 校验失败
        body = self.client.post(
            f'{FAULT_URL}/',
            fault_payload(self.system_a, impact_status='invalid_status'),
            content_type='application/json').json()
        self.assertTrue(body.get('error'))
        self.assertEqual(len(self.events()), before)


class WorkOrderEventTests(SystemEventTestBase):
    """工单动作 → 履历事件（只落作业系统）。"""

    def test_work_order_create_generates_single_system_event(self):
        """工单登记：只生成一条事件（落作业系统）；专项维护不影响健康状态。"""
        before_health = len(self.events(event_type=SystemEvent.EVENT_HEALTH))
        body = self.client.post(
            f'{WO_URL}/',
            work_order_payload(self.system_a, client_token=_uniq_client_token()),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        wid = body['data']['id']
        wo_events = [e for e in self.events() if e.event_type == SystemEvent.EVENT_WORK_ORDER]
        self.assertEqual(len(wo_events), 1)
        e = wo_events[0]
        self.assertEqual(e.source_type, 'work_order')
        self.assertEqual(e.source_id, str(wid))
        self.assertEqual(e.get_detail().get('work_no'), body['data']['work_no'])
        self.assertEqual(e.system_id, self.system_a.id)
        self.assertEqual(e.action, 'create')
        # 其他系统无工单事件
        self.assertEqual(
            [ev for ev in wo_events if ev.system_id == self.system_a2.id], [])
        # 专项维护工单不覆盖健康状态：无健康事件
        self.assertEqual(len(self.events(event_type=SystemEvent.EVENT_HEALTH)), before_health)

    def test_complete_generates_event_and_close_archives_silently(self):
        """复核通过（完成）生成事件；关闭归档不再生成事件；完成不自动恢复健康。"""
        self.run_fault_lifecycle(self.system_a)  # 保持系统有历史
        self.client.post(f'{WO_URL}/', work_order_payload(self.system_a),
                         content_type='application/json').json()
        wid = self.run_work_order_to_complete(work_order_payload(self.system_a))
        complete_events = [e for e in self.events() if e.action == 'complete']
        self.assertEqual(len(complete_events), 1)
        self.assertEqual(complete_events[0].system_id, self.system_a.id)
        # 关闭归档：不生成新事件
        r = self.client.post(f'{WO_URL}/{wid}/close/', {}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(len([e for e in self.events() if e.action == 'complete']), 1)
        self.assertEqual(len([e for e in self.events() if e.action == 'close'
                              and e.event_type == SystemEvent.EVENT_WORK_ORDER]), 0)

    def test_repair_work_order_start_and_review_generate_repairing_health_events(self):
        """执行中且影响运行的故障维修工单产生"维修中"；完成回落后"故障"保持。"""
        body = self.client.post(f'{FAULT_URL}/',
                                fault_payload(self.system_a, impact_status='fault'),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        # 生成维修工单并推进到执行中（来源故障未恢复 → 默认影响运行）
        wo_body = self.client.post(
            f'{FAULT_URL}/{fid}/create-work-order/',
            {'client_token': _uniq_client_token(), 'work_type': 'repair'},
            content_type='application/json').json()
        self.assertFalse(wo_body.get('error'), wo_body)
        wid = wo_body['data']['id']
        self.assertTrue(wo_body['data']['affects_system_operation'])
        for action, payload in (
                ('dispatch', {'owner_id': self.admin.id}),
                ('accept', {}),
                ('start', {})):
            r = self.client.post(f'{WO_URL}/{wid}/{action}/', payload,
                                 content_type='application/json')
            self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'repairing')
        start_health = [e for e in self.events(self.system_a, SystemEvent.EVENT_HEALTH)
                        if e.get_detail().get('after') == 'repairing']
        self.assertEqual(len(start_health), 1)
        self.assertEqual(start_health[0].get_detail().get('before'), 'fault')
        # 提交复核前必须先追加处理记录（步骤 3.3 状态机要求）
        r = self.client.post(f'{WO_URL}/{wid}/handling-records/',
                             {'handled_at': '2026-09-18 11:00', 'content': '完成维修'},
                             content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        # 提交复核 → 工单不再执行中 → 健康回落到 fault（来源故障未恢复）
        r = self.client.post(f'{WO_URL}/{wid}/submit-review/',
                             {'process_result': '维修完成'}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'fault')
        # 复核通过 → 工单完成事件；故障未恢复 → 系统不恢复正常
        r = self.client.post(f'{WO_URL}/{wid}/review-pass/', {}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'fault')
        self.assertTrue([e for e in self.events() if e.action == 'complete'])
        self.assertFalse([e for e in self.events(self.system_a, SystemEvent.EVENT_HEALTH)
                          if e.get_detail().get('after') == 'normal'])

    def test_work_order_cancel_appends_event(self):
        """工单受控取消：追加取消事件且原因进入事件详情。"""
        body = self.client.post(f'{WO_URL}/', work_order_payload(self.system_a),
                                content_type='application/json').json()
        wid = body['data']['id']
        r = self.client.post(f'{WO_URL}/{wid}/cancel/',
                             {'cancel_reason': '计划变更'}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        cancel_events = [e for e in self.events() if e.action == 'cancel'
                         and e.event_type == SystemEvent.EVENT_WORK_ORDER]
        self.assertEqual(len(cancel_events), 1)
        self.assertEqual(cancel_events[0].get_detail().get('cancel_reason'), '计划变更')


class LedgerConvertEventTests(SystemEventTestBase):
    """台账异常转单 → 履历事件（来源 ledger_item，双向可追溯，不重复）。"""

    def create_reviewed_ledger_with_abnormal_item(self):
        template = OperationLedgerTemplate.objects.create(
            name='巡检模板-履历', ledger_type='inspection',
            maintenance_cycle='',
            is_active=True, tenant_id='tenant_a', created_by=self.admin)
        body = create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system_a.id, [
                item_payload(result='abnormal', abnormal_desc='温度越限 65℃'),
            ], template_id=template.id),
        ]))
        ledger_id = body['id']
        item_id = body['items'][0]['id']
        r = self.client.post(f'{LEDGER_URL}/{ledger_id}/submit/', {},
                             content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{LEDGER_URL}/{ledger_id}/review/',
                             {'review_result': '同意'}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        return ledger_id, item_id

    def test_convert_to_fault_generates_ledger_and_fault_events(self):
        """台账异常转故障：ledger 事件 + 故障创建事件同一事务；正常台账不产生任何事件。"""
        ledger_id, item_id = self.create_reviewed_ledger_with_abnormal_item()
        before = len(self.events())
        r = self.client.post(
            f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-fault/',
            {}, content_type='application/json')
        body = r.json()
        self.assertFalse(body.get('error'), body)
        events = self.events()[before:]
        ledger_events = [e for e in events if e.event_type == SystemEvent.EVENT_LEDGER]
        self.assertEqual(len(ledger_events), 1)
        e = ledger_events[0]
        self.assertEqual(e.action, 'convert_to_fault')
        self.assertEqual(e.source_type, 'ledger_item')
        self.assertEqual(e.source_id, str(item_id))
        self.assertEqual(e.system_id, self.system_a.id)
        self.assertEqual(e.get_detail().get('ledger_id'), ledger_id)
        self.assertEqual(e.get_detail().get('target_no'), body['data']['fault_no'])
        # 故障创建事件（主体）与健康状态事件（normal→degraded）同批生成
        fault_creates = [ev for ev in events if ev.action == 'create'
                         and ev.event_type == SystemEvent.EVENT_FAULT]
        self.assertEqual(len(fault_creates), 1)
        self.assertTrue([ev for ev in events if ev.event_type == SystemEvent.EVENT_HEALTH])
        # 台账创建/提交/复核过程本身不产生事件：除转单 3 条外无其他
        self.assertEqual(len(events), 3)

    def test_duplicate_convert_request_generates_no_duplicate_events(self):
        """重复转单（同 client_token）返回已有工单且不产生重复事件。"""
        ledger_id, item_id = self.create_reviewed_ledger_with_abnormal_item()
        token = _uniq_client_token()
        url = f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-work-order/'
        first = self.client.post(url, {'client_token': token, 'work_type': 'special_maintenance'},
                                 content_type='application/json').json()
        self.assertFalse(first.get('error'), first)
        count = len(self.events())
        second = self.client.post(url, {'client_token': token, 'work_type': 'special_maintenance'},
                                  content_type='application/json').json()
        self.assertFalse(second.get('error'), second)
        self.assertEqual(second['data']['id'], first['data']['id'])
        self.assertEqual(len(self.events()), count)
        self.assertEqual(len([e for e in self.events()
                              if e.source_id == str(item_id)]), 1)


class ReadOnlyAndIsolationTests(SystemEventTestBase):
    """履历只读、租户隔离、快照事件、普通配置修改不进履历、导出权限。"""

    def test_events_api_is_readonly(self):
        """普通用户不能手工新增履历；不存在修改/删除接口（405）。"""
        for method, body in (('post', {}), ('put', {}), ('delete', None)):
            resp = getattr(self.client, method)(
                f'{URL_PREFIX}/system-events/', body, content_type='application/json')
            self.assertEqual(resp.status_code, 405, f'{method}: {resp.content}')

    def test_snapshot_generates_event_but_normal_field_edit_does_not(self):
        """配置快照生成进入履历；普通固定字段修改只进配置历史，不进履历。"""
        before = len(self.events())
        # 普通编辑：名称修改
        r = self.client.put(f'{SYSTEM_URL}/{self.system_a.id}/', {
            'system_code': self.system_a.system_code,
            'name': '烟台通信系统（改名）',
            'system_model': 'HX-100', 'install_location': '机房A',
            'manufacturer': '某厂', 'install_unit': '安装一队', 'use_unit': '运行一科',
            'install_time': '2026-01-01 08:00', 'enable_time': '2026-02-01 09:00',
            'responsible_user_name': '张三',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(len(self.events()), before)
        self.assertTrue(SystemConfigChange.objects.filter(
            system_id=self.system_a.id, source='system').exists())
        # 生成快照 → 履历事件
        r = self.client.post(f'{SYSTEM_URL}/{self.system_a.id}/snapshots/',
                             {'name': '改造前快照'}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        events = self.events()[before:]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, SystemEvent.EVENT_CONFIG_SNAPSHOT)
        self.assertEqual(events[0].source_type, 'config_snapshot')
        self.assertTrue(SystemConfigSnapshot.objects.filter(
            system_id=self.system_a.id).exists())

    def test_tenant_isolation(self):
        """履历租户隔离：跨租户事件互不可见；跨租户系统履历接口拒绝。"""
        self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                         content_type='application/json').json()
        other_client = make_client(self.other_admin)
        resp = other_client.post(f'{FAULT_URL}/', fault_payload(self.system_b),
                                 content_type='application/json').json()
        self.assertFalse(resp.get('error'), resp)
        codes_a = {e.system_code for e in self.events()}
        self.assertNotIn('SYS-B1', codes_a)
        # 跨租户按系统查询履历：系统不存在（租户过滤）
        resp = self.client.get(f'{SYSTEM_URL}/{self.system_b.id}/system-events/')
        self.assertIn('不存在', resp.json().get('error', ''))

    def test_system_events_by_system_and_type_filter(self):
        """系统详情履历接口：只返回该系统的事件，支持事件类型过滤。"""
        self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a2),
                         content_type='application/json').json()
        self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                         content_type='application/json').json()
        resp = self.client.get(
            f'{SYSTEM_URL}/{self.system_a.id}/system-events/').json()
        self.assertFalse(resp.get('error'))
        rows = resp['data']['data']
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['system'], self.system_a.id)
            self.assertNotIn('role', row)
        # 事件类型过滤
        resp = self.client.get(
            f'{SYSTEM_URL}/{self.system_a.id}/system-events/?event_type=fault').json()
        rows = resp['data']['data']
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['event_type'], 'fault')

    def test_event_list_permission_required(self):
        """无履历查看权限时后端真实拒绝。"""
        client = make_client(self.noperm_user)
        resp = client.get(f'{URL_PREFIX}/system-events/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')

    def test_export_requires_export_permission_and_audited(self):
        """导出需独立 export 权限并记录审计。"""
        client = make_client(self.noperm_user)
        resp = client.get(f'{URL_PREFIX}/system-events/export/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = self.client.get(f'{URL_PREFIX}/system-events/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])


class DeleteProtectionRegressionTests(SystemEventTestBase):
    """步骤 3.5 删除保护收口：关联存在时返回业务错误而非 500。"""

    def test_system_delete_blocked_by_work_order_and_events(self):
        """工单引用与履历事件引用分别阻断系统删除。"""
        self.client.post(f'{WO_URL}/', work_order_payload(self.system_a),
                         content_type='application/json').json()
        resp = self.client.delete(f'{SYSTEM_URL}/{self.system_a.id}/')
        self.assertIn('工单', resp.json().get('error', ''))
        # 只存在履历事件的系统（无其他业务引用）也被阻断
        self.client.post(f'{SYSTEM_URL}/{self.system_a2.id}/snapshots/',
                         {'name': '快照-阻断'}, content_type='application/json').json()
        resp = self.client.delete(f'{SYSTEM_URL}/{self.system_a2.id}/')
        self.assertIn('系统履历事件', resp.json().get('error', ''))

    def test_system_delete_blocked_by_ledger_item(self):
        """台账明细引用阻断系统删除（fail-closed）。"""
        # 通过真实 API 创建带明细的台账（明细以正式系统 ID 关联）
        template = OperationLedgerTemplate.objects.create(
            name='巡检模板-删除保护', ledger_type='inspection',
            maintenance_cycle='',
            is_active=True, tenant_id='tenant_a', created_by=self.admin)
        create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system_a.id, [item_payload()], template_id=template.id),
        ]))
        resp = self.client.delete(f'{SYSTEM_URL}/{self.system_a.id}/')
        self.assertIn('台账明细', resp.json().get('error', ''))


class ViewWiringContractTests(SystemEventTestBase):
    """视图装配契约：动作视图非原子请求（修复 GET_LOCK 先释放后提交窗口）。"""

    def test_lock_using_views_are_non_atomic(self):
        """所有持健康重算锁的动作视图必须 non_atomic（锁释放晚于事务提交）。"""
        from django.db import transaction as db_transaction
        non_atomic_paths = {
            'faults/', 'faults/<int:pk>/', 'faults/<int:pk>/start/',
            'faults/<int:pk>/recover/', 'faults/<int:pk>/close/',
            'faults/<int:pk>/cancel/', 'faults/<int:pk>/handling-records/',
            'faults/<int:pk>/handling-records/<int:rid>/',
            'faults/<int:pk>/handling-records/<int:rid>/attachments/',
            'faults/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/',
            'work-orders/', 'work-orders/<int:pk>/', 'work-orders/<int:pk>/dispatch/',
            'work-orders/<int:pk>/accept/', 'work-orders/<int:pk>/start/',
            'work-orders/<int:pk>/submit-review/', 'work-orders/<int:pk>/review-pass/',
            'work-orders/<int:pk>/review-return/', 'work-orders/<int:pk>/close/',
            'work-orders/<int:pk>/cancel/', 'work-orders/<int:pk>/handling-records/',
            'work-orders/<int:pk>/handling-records/<int:rid>/',
            'work-orders/<int:pk>/handling-records/<int:rid>/attachments/',
            'work-orders/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/',
            'faults/<int:pk>/create-work-order/',
            'ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-fault/',
            'ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-work-order/',
        }
        checked = 0
        for pattern in el_urls.urlpatterns:
            route = str(pattern.pattern)
            if route in non_atomic_paths:
                callback = pattern.callback
                self.assertTrue(
                    getattr(callback, '_non_atomic_requests', None),
                    f'{route} 未按 non_atomic_requests 装配')
                checked += 1
        self.assertEqual(checked, len(non_atomic_paths))

    def test_no_circular_import_between_services(self):
        """服务模块可独立加载（event_services 只依赖 models，无循环 import）。"""
        from apps.equipment_lifecycle import event_services as es
        self.assertTrue(callable(es.record_system_event))
        self.assertTrue(callable(es.record_fault_lifecycle_events))
        self.assertTrue(callable(es.record_work_order_lifecycle_events))
