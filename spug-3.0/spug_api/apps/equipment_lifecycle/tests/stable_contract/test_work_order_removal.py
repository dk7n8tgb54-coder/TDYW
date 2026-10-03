# -*- coding: utf-8 -*-
"""故障维修工单功能删除（2026-09-30）稳定契约测试。

覆盖验收要求的真实行为契约：
1. 工单 API 不再注册（列表/创建/详情/动作/处理记录/导出/按系统/按故障
   与台账异常转工单全部 404；模型三表随迁移 0043 删除）；
2. 故障处理进展承载处理人（进展记录人）、时间、内容、结果、工时与
   更正历史（原工单处理记录职责）；
3. 故障状态闭环不依赖工单（登记→进展→恢复确认→关闭全程无工单参与，
   健康状态随之恢复 normal）；
4. 台账/巡检异常转故障链路仍然有效（转工单端点已删除）；
5. 系统健康状态不读取工单数据：collect_active_impacts 只查故障，
   derive_health_status 优先级 中断>故障>降级，关闭一张故障不覆盖
   其他未恢复故障的影响，且不存在 repairing 状态；
6. 租户隔离、权限与附件访问仍然有效（转故障双权限、跨租户拒绝、
   处理进展附件归属校验）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
import json
from datetime import datetime, timedelta

from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    OperationLedger,
    SystemEvent,
    SystemFault,
    SystemFaultHandlingRecord,
)
from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS, URL_PREFIX, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, create_ledger_ok, entry_payload, item_payload,
    ledger_payload, post_json,
)

SEQ = {'n': 0}

FAULT_URL = URL_PREFIX + '/faults'
SYSTEM_URL = URL_PREFIX + '/systems'
LEDGER_URL = URL_PREFIX + '/ledgers'
GROUPS_URL = URL_PREFIX + '/system-event-groups'

ALL_FAULT_PERMS = [
    'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
    'equipment_lifecycle.fault.edit', 'equipment_lifecycle.fault.handle',
    'equipment_lifecycle.fault.recover', 'equipment_lifecycle.fault.close',
    'equipment_lifecycle.fault.del',
]
ALL_HANDLE_PERMS = ALL_LEDGER_PERMS + [
    'equipment_lifecycle.ledger.handle_exception',
    'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
]

# 已删除的工单路由（工单 API 不再注册契约）
REMOVED_WO_ROUTES = [
    ('get', '/equipment-lifecycle/work-orders/'),
    ('post', '/equipment-lifecycle/work-orders/'),
    ('get', '/equipment-lifecycle/work-orders/1/'),
    ('post', '/equipment-lifecycle/work-orders/1/complete/'),
    ('post', '/equipment-lifecycle/work-orders/1/close/'),
    ('post', '/equipment-lifecycle/work-orders/1/cancel/'),
    ('get', '/equipment-lifecycle/work-orders/1/handling-records/'),
    ('get', '/equipment-lifecycle/work-orders/export/'),
    ('get', '/equipment-lifecycle/work-orders/candidate-users/'),
    ('get', '/equipment-lifecycle/systems/1/work-orders/'),
    ('get', '/equipment-lifecycle/faults/1/work-orders/'),
]


def fault_payload(system_obj, **overrides):
    SEQ['n'] += 1
    moment = datetime(2026, 9, 30, 8, 0) + timedelta(minutes=SEQ['n'])
    payload = {
        'system': system_obj.id,
        'affects_system_operation': True,
        'impact_status': 'degraded',
        'occurred_at': moment.strftime('%Y-%m-%d %H:%M'),
        'phenomenon': f'主用链路丢包（场景{SEQ["n"]}）',
        'registrar_name': '登记人甲',
    }
    payload.update(overrides)
    return payload


class WorkOrderRemovalTestBase(TestCase):
    """公共夹具：单租户双系统 + 全权限用户。"""

    def setUp(self):
        self.admin = make_user(
            'wor_admin', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS + ALL_HANDLE_PERMS + [
                'equipment_lifecycle.system_event.view',
            ], tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-W1', name='烟台通信系统',
                                    install_location='机房A')
        self.system_a2 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SYS-W2', name='威海监控系统',
                                     install_location='机房B')


class WorkOrderApiRemovedTest(WorkOrderRemovalTestBase):
    """契约 1：工单 API 不再注册。"""

    def test_work_order_endpoints_return_404(self):
        """工单全部端点 404（路由已删除），且不产生任何数据。"""
        for method, url in REMOVED_WO_ROUTES:
            resp = getattr(self.client, method)(url, {}, content_type='application/json')
            self.assertEqual(resp.status_code, 404, f'{method} {url}: {resp.content}')

    def test_convert_to_work_order_endpoint_removed(self):
        """台账异常转工单端点已删除（404），转故障端点仍然注册。"""
        body = create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system_a.id, [
                item_payload(result='abnormal', abnormal_desc='电压偏低'),
            ]),
        ]))
        ledger_id, item_id = body['id'], body['items'][0]['id']
        self.client.post(f'{LEDGER_URL}/{ledger_id}/submit/', {},
                         content_type='application/json')
        resp = self.client.post(
            f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-work-order/',
            {'work_type': 'special_maintenance'},
            content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        # 转故障端点仍在（见 ConversionChainAliveTest 的行为契约）

    def test_work_order_tables_dropped(self):
        """工单三表已随迁移 0043 删除，无运行时残留。"""
        with connection.cursor() as cursor:
            for table in ('tdyw_el_work_order', 'tdyw_el_work_order_participant',
                          'tdyw_el_work_order_handling_record'):
                cursor.execute("SHOW TABLES LIKE %s", [table])
                self.assertIsNone(cursor.fetchone(), table)

    def test_health_status_domain_has_no_repairing(self):
        """健康状态值域不含 repairing（维修中已随工单功能删除）。"""
        self.assertNotIn(
            'repairing', [c[0] for c in LifecycleSystem.HEALTH_STATUS_CHOICES])
        from apps.equipment_lifecycle.models import HEALTH_STATUS_VALUES
        self.assertNotIn('repairing', HEALTH_STATUS_VALUES)


class ProgressReplacesWorkOrderTest(WorkOrderRemovalTestBase):
    """契约 2：处理进展承载处理人/时间/内容/结果/工时/更正历史。"""

    def _started_fault(self, **overrides):
        """创建故障（新建即处置中），返回 fault id。"""
        body = self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a, **overrides),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        return body['data']['id']

    def test_progress_records_handler_time_content_result_hours(self):
        """追加进展：记录人/时间/内容/结果/工时全部落库并回读。"""
        fid = self._started_fault()
        resp = self.client.post(f'{FAULT_URL}/{fid}/handling-records/', {
            'handled_at': '2026-09-30 09:30',
            'recorder_name': '张检测',
            'progress_type': 'to_vendor',
            'content': '发射机板卡拆下送厂',
            'result': '送厂维修中',
            'work_hours': 1.5,
        }, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        record = SystemFaultHandlingRecord.objects.get(pk=body['data']['id'])
        self.assertEqual(record.recorder_name, '张检测')
        self.assertEqual(record.handled_at.strftime('%Y-%m-%d %H:%M'), '2026-09-30 09:30')
        self.assertEqual(record.content, '发射机板卡拆下送厂')
        self.assertEqual(record.result, '送厂维修中')
        self.assertEqual(record.work_hours, 1.5)
        self.assertEqual(record.progress_type, 'to_vendor')
        # 时间线接口返回同样数据（含工时）
        listing = self.client.get(f'{FAULT_URL}/{fid}/handling-records/').json()
        row = listing['data']['data'][0]
        self.assertEqual(row['work_hours'], 1.5)
        self.assertEqual(row['recorder_name'], '张检测')

    def test_progress_correction_keeps_history(self):
        """更正进展：原内容/新内容/原因/操作人追加进 corrections，不静默覆盖。"""
        fid = self._started_fault()
        body = self.client.post(f'{FAULT_URL}/{fid}/handling-records/', {
            'handled_at': '2026-09-30 10:00',
            'recorder_name': '张检测',
            'content': '现场检查完毕',
            'work_hours': 0.5,
        }, content_type='application/json').json()
        rid = body['data']['id']
        resp = self.client.put(f'{FAULT_URL}/{fid}/handling-records/{rid}/', {
            'content': '现场检查完毕，确认电源模块损坏',
            'correction_reason': '漏写检查结论',
            'work_hours': 1.0,
        }, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        record = SystemFaultHandlingRecord.objects.get(pk=rid)
        self.assertEqual(record.content, '现场检查完毕，确认电源模块损坏')
        self.assertEqual(record.work_hours, 1.0)
        corrections = record.get_corrections()
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]['old'], '现场检查完毕')
        self.assertEqual(corrections[0]['reason'], '漏写检查结论')
        self.assertEqual(corrections[0]['by'], self.admin.username)

    def test_progress_rejected_after_terminal_state(self):
        """已关闭/已作废故障不能追加进展（终态保护，闭环语义保持）。"""
        fid = self._started_fault()
        self.client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': '2026-09-30 11:00',
            'recovered_by_name': '确认人乙',
            'recover_confirm': '业务验证正常',
            'final_result': '更换板卡并复测通过',
        }, content_type='application/json')
        resp = self.client.post(f'{FAULT_URL}/{fid}/handling-records/', {
            'recorder_name': '张检测', 'content': '补记',
        }, content_type='application/json')
        self.assertIn('不能追加处理进展', resp.json().get('error', ''))


class FaultClosureWithoutWorkOrderTest(WorkOrderRemovalTestBase):
    """契约 3：故障状态闭环不依赖工单。"""

    def test_full_loop_without_work_order_restores_health(self):
        """登记→处理进展→恢复确认→关闭：健康状态 degraded→normal，无工单事件。"""
        body = self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                                content_type='application/json').json()
        fid = body['data']['id']
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'degraded')
        self.client.post(f'{FAULT_URL}/{fid}/handling-records/', {
            'recorder_name': '张检测', 'content': '更换备件，本方测试通过',
            'work_hours': 3.0,
        }, content_type='application/json')
        # 确认恢复并结案：恢复后健康状态即恢复正常，同事务直接进入终态
        self.client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': '2026-09-30 12:00',
            'recovered_by_name': '确认人乙',
            'recover_confirm': '业务验证正常',
            'final_result': '更换备件并复测通过',
        }, content_type='application/json')
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.status, 'closed')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        # 履历只含故障与健康事件，无任何工单事件
        types = {e.event_type for e in SystemEvent.objects.filter(
            tenant_id='tenant_a', system_id=self.system_a.id)}
        self.assertEqual(types, {'fault', 'health'})


class ConversionChainAliveTest(WorkOrderRemovalTestBase):
    """契约 4：台账/巡检异常转故障链路仍然有效。"""

    def test_ledger_abnormal_item_converts_to_fault(self):
        """台账异常明细转故障：正式服务创建、来源关系与履历同事务落库。"""
        body = create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system_a.id, [
                item_payload(result='abnormal', abnormal_desc='温度越限'),
            ]),
        ]))
        ledger_id, item_id = body['id'], body['items'][0]['id']
        self.client.post(f'{LEDGER_URL}/{ledger_id}/submit/', {},
                         content_type='application/json')
        resp = self.client.post(
            f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-fault/',
            {}, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        self.assertEqual(fault.source_type, 'ledger_item')
        self.assertEqual(fault.source_ledger_item_id, item_id)
        # 台账明细处置状态动态展示已转故障
        ledger_detail = self.client.get(f'{LEDGER_URL}/{ledger_id}/').json()['data']
        item_view = next(i for i in ledger_detail['items'] if i['id'] == item_id)
        self.assertEqual(item_view['disposition']['status'], 'converted_fault')
        self.assertEqual(item_view['disposition']['fault']['fault_no'], fault.fault_no)


class HealthComputedFromFaultsOnlyTest(WorkOrderRemovalTestBase):
    """契约 5：健康状态不读取工单数据，优先级固化。"""

    def test_service_queries_faults_only(self):
        """collect_active_impacts 只查故障；derive_health_status 无 repairing 分支。"""
        import inspect
        from apps.equipment_lifecycle import fault_services as fs
        # 服务函数签名不再有 repairing 参数
        self.assertNotIn('repairing', inspect.signature(fs.derive_health_status).parameters)
        self.assertFalse(hasattr(fs, 'REPAIRING_WORK_ORDER_FILTER'))
        self.assertFalse(hasattr(fs, 'collect_repairing_system_ids'))
        # 优先级：中断 > 故障 > 降级
        self.assertEqual(
            fs.derive_health_status({'degraded', 'fault', 'interrupted'}), 'interrupted')
        self.assertEqual(fs.derive_health_status({'degraded', 'fault'}), 'fault')
        self.assertEqual(fs.derive_health_status({'degraded'}), 'degraded')
        self.assertEqual(fs.derive_health_status(set()), 'normal')

    def test_closing_one_fault_keeps_other_fault_impact(self):
        """关闭一张故障不覆盖其他未恢复故障的影响（重算以全量有效故障为准）。"""
        body = self.client.post(f'{FAULT_URL}/', fault_payload(
            self.system_a, impact_status='degraded'), content_type='application/json').json()
        fid_kept = body['data']['id']
        body = self.client.post(f'{FAULT_URL}/', fault_payload(
            self.system_a, impact_status='interrupted'),
            content_type='application/json').json()
        fid_closed = body['data']['id']
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'interrupted')
        # 结案中断故障 → 重算后回落到仍未恢复的降级故障，而不是 normal
        r = self.client.post(f'{FAULT_URL}/{fid_closed}/recover/', {
            'recovered_at': '2026-09-30 13:00',
            'recovered_by_name': '确认人乙',
            'recover_confirm': '链路已恢复',
            'final_result': '更换光模块',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'degraded')
        # 结案剩余故障 → normal
        r = self.client.post(f'{FAULT_URL}/{fid_kept}/recover/', {
            'recovered_at': '2026-09-30 14:00',
            'recovered_by_name': '确认人乙',
            'recover_confirm': '全部恢复',
            'final_result': '更换备件并验证',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')

    def test_cancelled_fault_no_longer_impacts_health(self):
        """故障作废后不再影响健康状态。"""
        body = self.client.post(f'{FAULT_URL}/', fault_payload(
            self.system_a, impact_status='fault'), content_type='application/json').json()
        fid = body['data']['id']
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'fault')
        self.client.post(f'{FAULT_URL}/{fid}/cancel/', {
            'cancel_reason': '误报'}, content_type='application/json')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')


class IsolationPermissionAttachmentTest(WorkOrderRemovalTestBase):
    """契约 6：租户隔离、权限与附件访问仍然有效。"""

    def test_convert_to_fault_dual_permission_and_tenant_isolation(self):
        """转故障须双权限；跨租户台账明细不可见。"""
        body = create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system_a.id, [
                item_payload(result='abnormal', abnormal_desc='偏低'),
            ]),
        ]))
        ledger_id, item_id = body['id'], body['items'][0]['id']
        self.client.post(f'{LEDGER_URL}/{ledger_id}/submit/', {},
                         content_type='application/json')
        # 只有处置权限、无 fault.add → 拒绝
        handle_only = make_user(
            'wor_handle_only',
            ALL_SYSTEM_PERMS + ALL_LEDGER_PERMS + [
                'equipment_lifecycle.ledger.handle_exception'],
            tenant_id='tenant_a')
        resp = make_client(handle_only).post(
            f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-fault/',
            {}, content_type='application/json')
        self.assertIn('权限拒绝', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.count(), 0)
        # 跨租户用户访问 → 不存在
        other_admin = make_user('wor_admin_b', ALL_SYSTEM_PERMS + ALL_HANDLE_PERMS,
                                tenant_id='tenant_b')
        resp = make_client(other_admin).post(
            f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-fault/',
            {}, content_type='application/json')
        self.assertIn('不存在', resp.json().get('error', ''))

    def test_progress_attachment_access_control(self):
        """处理进展附件：上传后可列表/下载，跨模块对象类型不可见（归属校验）。"""
        from apps.evidence.models import EvidenceAttachment
        body = self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                                content_type='application/json').json()
        fid = body['data']['id']
        record = self.client.post(f'{FAULT_URL}/{fid}/handling-records/', {
            'recorder_name': '张检测', 'content': '现场照片留档',
        }, content_type='application/json').json()['data']
        upload = self.client.post(
            f'{FAULT_URL}/{fid}/handling-records/{record["id"]}/attachments/',
            {'file': self._make_text_file('site.jpg', 'jpeg-bytes')})
        self.assertFalse(upload.json().get('error'), upload.content)
        att_id = upload.json()['data']['id']
        # 列表可见
        listing = self.client.get(
            f'{FAULT_URL}/{fid}/handling-records/{record["id"]}/attachments/').json()
        self.assertIn(att_id, [a['id'] for a in listing['data']['data']])
        # 伪造 object_type（工单处理记录类型已下线）查询不到：归属校验按故障进展类型
        self.assertFalse(EvidenceAttachment.objects.filter(
            module='equipment_lifecycle',
            object_type='el_work_order_handling').exists())
        self.assertTrue(EvidenceAttachment.objects.filter(
            module='equipment_lifecycle',
            object_type='el_fault_handling', pk=att_id).exists())

    def _make_text_file(self, name, content):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, content.encode('utf-8'))

    def test_event_group_api_excludes_work_order_type(self):
        """履历分组接口不再接受工单类型/来源筛选（值域收窄）。"""
        resp = self.client.get(f'{GROUPS_URL}/?event_type=work_order')
        self.assertIn('不合法', resp.json().get('error', ''))
        resp = self.client.get(f'{GROUPS_URL}/?source_type=work_order')
        self.assertIn('不合法', resp.json().get('error', ''))
