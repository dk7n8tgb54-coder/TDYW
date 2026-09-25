# -*- coding: utf-8 -*-
"""系统履历事项聚合（按系统分组、按业务事项聚合）稳定契约测试。

覆盖行为契约：
- 同一故障的 create/recover/close 等节点聚合成一条事项，节点时间线升序可查；
- 不同故障/不同系统之间严格隔离，不发生错误合并；
- 健康状态与配置快照事件默认不进入主事项列表，但原始数据保留且健康历史
  经系统详情履历接口（/systems/<pk>/system-events/）仍可查询；
- 台账异常转故障/工单节点按 target_no 归并进目标事项（显示来源台账），
  找不到目标时独立成项；
- 工单与升级记录可正确聚合；分页以系统分组为单位，按最近事项时间倒序；
- 权限不足拒绝访问；导出按系统分组连续输出且列序符合契约。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
升级事件经升级模块真实履历写入服务（record_upgrade_lifecycle_events）生成，
其 HTTP 工作流由升级模块自身契约测试覆盖，此处验证聚合对真实事件形态的兼容。
"""
from datetime import datetime, timedelta

from django.test import TestCase

from apps.equipment_lifecycle import event_services
from apps.equipment_lifecycle.models import (
    OperationLedger,
    OperationLedgerItem,
    OperationLedgerTemplate,
    SystemEvent,
)
from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS, URL_PREFIX, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, ALL_TEMPLATE_PERMS, LEDGER_URL, create_ledger_ok,
    entry_payload, item_payload, ledger_payload,
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

ALL_PERMS = (ALL_SYSTEM_PERMS + ALL_FAULT_PERMS + ALL_WO_PERMS +
             ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS +
             ALL_EVENT_PERMS + [P_HANDLE_EXCEPTION])

FAULT_URL = URL_PREFIX + '/faults'
WO_URL = URL_PREFIX + '/work-orders'
SYSTEM_URL = URL_PREFIX + '/systems'
GROUPS_URL = URL_PREFIX + '/system-event-groups'
NODES_URL = GROUPS_URL + '/nodes'
EXPORT_URL = GROUPS_URL + '/export'

_seq = [0]


def fault_payload(system_obj, **overrides):
    """发生时间按序错开；默认不影响系统运行（不产生健康状态事件）。"""
    _seq[0] += 1
    seq = _seq[0]
    moment = datetime(2026, 9, 18, 8, 0) + timedelta(minutes=seq)
    payload = {
        'system': system_obj.id,
        'affects_system_operation': False,
        'impact_status': '',
        'occurred_at': moment.strftime('%Y-%m-%d %H:%M'),
        'discovery': 'patrol',
        'level': 'major',
        'phenomenon': f'主用链路频繁丢包（场景{seq}）',
        'registrar_name': '登记人甲',
    }
    payload.update(overrides)
    return payload


class SystemEventGroupTestBase(TestCase):
    """公共夹具：租户 A/B、租户 A 三套系统。"""

    def setUp(self):
        self.admin = make_user('evg_admin', list(ALL_PERMS), tenant_id='tenant_a')
        self.other_admin = make_user('evg_admin_b', list(ALL_PERMS), tenant_id='tenant_b')
        self.noperm_user = make_user('evg_noperm', ALL_SYSTEM_PERMS, tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-A1', name='烟台通信系统')
        self.system_a2 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SYS-A2', name='威海监控系统')
        self.system_a3 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SYS-A3', name='大连导航系统')
        self.system_b = make_system(self.other_admin, tenant_id='tenant_b',
                                    system_code='SYS-B1', name='烟台通信系统')

    # ---------- 公共步骤 ----------

    def groups(self, query=''):
        """调用分组列表接口并返回业务数据体（{data/total/page/page_size}）。"""
        resp = self.client.get(f'{GROUPS_URL}/{query}')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def group_items(self, query=''):
        """返回（分组列表, 全部事项拍平列表）。"""
        payload = self.groups(query)
        items = [item for group in payload['data'] for item in group['items']]
        return payload['data'], items

    def run_fault(self, system, close=True, recover_at='2026-09-18 10:00', **overrides):
        """创建→开始处置→恢复（→关闭），返回 (fault_id, fault_no)。"""
        body = self.client.post(
            f'{FAULT_URL}/', fault_payload(system, **overrides),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        fid, fno = body['data']['id'], body['data']['fault_no']
        r = self.client.post(f'{FAULT_URL}/{fid}/start/', {},
                             content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': recover_at,
            'recover_confirm': '业务已恢复正常',
            'final_result': '更换备件并验证',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        if close:
            r = self.client.post(f'{FAULT_URL}/{fid}/close/', {
                'final_result': '更换备件并验证',
            }, content_type='application/json')
            self.assertFalse(r.json().get('error'), r.content)
        return fid, fno

    def create_work_order(self, system, **overrides):
        """创建工单（登记事件），返回 (order_id, work_no)。"""
        _seq[0] += 1
        payload = {
            'title': f'{system.system_code} 例行维护工单（场景{_seq[0]}）',
            'work_type': 'special_maintenance',
            'priority': 'normal',
            'system': system.id,
            'affects_system_operation': False,
            'work_location': '机房A 01柜',
            'work_requirement': '按规程完成季度维护',
            'client_token': '',
        }
        payload.update(overrides)
        body = self.client.post(
            f'{WO_URL}/', payload, content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        return body['data']['id'], body['data']['work_no']

    def create_reviewed_ledger_with_abnormal_item(self):
        """创建→提交→复核一张含异常明细的台账，返回 (ledger_id, item_id)。"""
        template = OperationLedgerTemplate.objects.create(
            name='维护模板-履历聚合', ledger_type='week_month',
            maintenance_cycle='week', is_active=True, tenant_id='tenant_a',
            created_by=self.admin)
        body = create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system_a.id, [
                item_payload(result='abnormal', abnormal_desc='温度越限 65℃'),
            ], template_id=template.id),
        ]))
        ledger_id, item_id = body['id'], body['items'][0]['id']
        r = self.client.post(f'{LEDGER_URL}/{ledger_id}/submit/', {},
                             content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = self.client.post(f'{LEDGER_URL}/{ledger_id}/review/',
                             {'review_result': '同意'}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        return ledger_id, item_id

    def record_upgrade_events(self, system, title='DVOR 数字板升级'):
        """经升级模块真实履历写入服务生成升级 create/complete 两个节点。"""
        from apps.upgrade.models import UpgradeRecord
        record = UpgradeRecord.objects.create(
            title=title, upgrade_type='software', status='处理中', owner='张三',
            system=system, tenant_id='tenant_a', created_by=self.admin)
        event_services.record_upgrade_lifecycle_events(record, 'create', created_by=self.admin)
        record.status = '已完成'
        event_services.record_upgrade_lifecycle_events(record, 'complete', created_by=self.admin)
        return record.id


class FaultItemAggregationTests(SystemEventGroupTestBase):
    """故障事项聚合与节点时间线。"""

    def test_fault_nodes_aggregate_to_single_item(self):
        """同一故障 create/recover/close 三节点聚合为一条事项，状态/等级/持续时间正确。"""
        fid, fno = self.run_fault(self.system_a, occurred_at='2026-09-18 08:00',
                                  recover_at='2026-09-18 10:00')
        payload = self.groups()
        self.assertEqual(payload['total'], 1)
        group = payload['data'][0]
        self.assertEqual(group['system']['id'], self.system_a.id)
        self.assertEqual(group['item_count'], 1)
        item = group['items'][0]
        self.assertEqual(item['source_type'], 'fault')
        self.assertEqual(item['source_id'], str(fid))
        self.assertEqual(item['item_no'], fno)
        self.assertEqual(item['node_count'], 3)
        self.assertEqual(item['status_text'], '已关闭')
        self.assertEqual(item['level_text'], '严重')
        self.assertEqual(item['duration_seconds'], 7200)
        self.assertIn('主用链路频繁丢包', item['title'])

    def test_item_nodes_timeline_order(self):
        """事项节点时间线接口按发生时间升序返回完整节点。"""
        fid, _ = self.run_fault(self.system_a, occurred_at='2026-09-18 08:00',
                                recover_at='2026-09-18 10:00')
        resp = self.client.get(
            f'{NODES_URL}/?system={self.system_a.id}&source_type=fault&source_id={fid}')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        nodes = body['data']['data']
        self.assertEqual([n['action'] for n in nodes], ['create', 'recover', 'close'])
        occurred = [n['occurred_at'] for n in nodes]
        self.assertEqual(occurred, sorted(occurred))
        for node in nodes:
            self.assertIn('title', node)
            self.assertIn('created_by_name', node)
            self.assertIn('detail', node)

    def test_different_faults_not_merged(self):
        """同一系统的两个独立故障不会合并，各自保留节点。"""
        fid1, fno1 = self.run_fault(self.system_a)
        fid2, fno2 = self.run_fault(self.system_a)
        self.assertNotEqual(fno1, fno2)
        _, items = self.group_items()
        self.assertEqual(len(items), 2)
        nos = {item['item_no'] for item in items}
        self.assertEqual(nos, {fno1, fno2})
        for item in items:
            self.assertEqual(item['node_count'], 3)
            self.assertIn(item['source_id'], {str(fid1), str(fid2)})

    def test_groups_isolated_by_system_and_tenant(self):
        """系统之间严格隔离：分组只含本系统事项；跨租户分组不可见。"""
        self.run_fault(self.system_a)
        self.run_fault(self.system_a2)
        other_client = make_client(self.other_admin)
        r = other_client.post(f'{FAULT_URL}/', fault_payload(self.system_b),
                              content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        payload = self.groups()
        codes = {g['system']['system_code'] for g in payload['data']}
        self.assertEqual(codes, {'SYS-A1', 'SYS-A2'})
        # 跨租户（SYS-B1）故障不产生分组；每个分组只含本系统的一条事项
        for group in payload['data']:
            self.assertEqual(group['item_count'], 1)
            self.assertEqual(group['open_fault_count'], 0)
        self.assertEqual(payload['total'], 2)


class HealthAndLegacyEventTests(SystemEventGroupTestBase):
    """健康状态/配置快照事件的主列表排除与历史可查性。"""

    def setUp(self):
        super().setUp()
        # 影响系统运行的故障：产生健康状态变化事件（normal→degraded→normal）
        self.fid, self.fno = self.run_fault(
            self.system_a, occurred_at='2026-09-18 08:00',
            recover_at='2026-09-18 10:00',
            affects_system_operation=True, impact_status='degraded')

    def test_health_events_excluded_from_main_list(self):
        """健康状态事件默认不进入主事项列表，故障事项节点只含业务节点。"""
        health_events = SystemEvent.objects.filter(
            tenant_id='tenant_a', event_type='health')
        self.assertEqual(health_events.count(), 2)
        payload = self.groups()
        self.assertEqual(payload['total'], 1)
        item = payload['data'][0]['items'][0]
        self.assertEqual(item['node_count'], 3)
        self.assertTrue(all(n.action != 'status_change' for n in
                            SystemEvent.objects.filter(
                                source_type='fault', source_id=str(self.fid))))
        # 分组头显示系统当前健康状态（恢复后回到正常）
        self.assertEqual(payload['data'][0]['system']['health_status'], 'normal')

    def test_health_history_still_queryable(self):
        """健康状态历史经系统详情履历接口仍可查询（原接口契约不变）。"""
        resp = self.client.get(
            f'{SYSTEM_URL}/{self.system_a.id}/system-events/?event_type=health').json()
        self.assertFalse(resp.get('error'))
        rows = resp['data']['data']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['event_type'] == 'health' for row in rows))

    def test_config_snapshot_not_in_main_list(self):
        """存量配置快照事件兼容保留，但默认不进入主事项列表。"""
        SystemEvent.objects.create(
            tenant_id='tenant_a', system=self.system_a,
            event_type='config_snapshot', action='snapshot',
            source_type='config_snapshot', title='历史配置快照',
            system_code=self.system_a.system_code,
            system_name=self.system_a.name, occurred_at=datetime(2026, 9, 1, 9, 0))
        # 平铺接口仍返回（含健康/快照），契约不变
        flat = self.client.get(f'{URL_PREFIX}/system-events/').json()
        types = {row['event_type'] for row in flat['data']['data']}
        self.assertIn('health', types)
        self.assertIn('config_snapshot', types)
        # 分组主列表不含配置快照事项
        _, items = self.group_items()
        self.assertEqual([i['event_type'] for i in items], ['fault'])


class LedgerMergeTests(SystemEventGroupTestBase):
    """台账异常转换节点的归并规则。"""

    def test_ledger_convert_merges_into_fault_item(self):
        """台账异常转故障：转换节点并入目标故障事项并显示来源台账。"""
        ledger_id, item_id = self.create_reviewed_ledger_with_abnormal_item()
        r = self.client.post(
            f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-fault/',
            {'affects_system_operation': False}, content_type='application/json')
        body = r.json()
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        _, items = self.group_items()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item['source_type'], 'fault')
        self.assertEqual(item['source_id'], str(fid))
        self.assertEqual(item['node_count'], 2)
        self.assertEqual(len(item['ledger_sources']), 1)
        source = item['ledger_sources'][0]
        self.assertEqual(source['ledger_type'], 'week_month')
        self.assertEqual(source['item_name'], '设备指示灯检查')
        # 节点时间线接口返回同样的归并结果（故障节点 + 台账转换节点）
        resp = self.client.get(
            f'{NODES_URL}/?system={self.system_a.id}&source_type=fault&source_id={fid}')
        nodes = resp.json()['data']['data']
        self.assertEqual([n['action'] for n in nodes].count('convert_to_fault'), 1)
        self.assertEqual(len(nodes), 2)

    def test_ledger_convert_merges_into_work_order_item(self):
        """台账异常转工单：转换节点并入目标工单事项。"""
        ledger_id, item_id = self.create_reviewed_ledger_with_abnormal_item()
        r = self.client.post(
            f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-work-order/',
            {'client_token': 'token-evg-wo', 'work_type': 'special_maintenance'},
            content_type='application/json')
        body = r.json()
        self.assertFalse(body.get('error'), body)
        _, items = self.group_items()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item['source_type'], 'work_order')
        self.assertEqual(item['node_count'], 2)
        self.assertEqual(len(item['ledger_sources']), 1)

    def test_ledger_convert_without_target_standalone(self):
        """台账转换找不到目标事项时独立成项（防御路径）。"""
        ledger_id, item_id = self.create_reviewed_ledger_with_abnormal_item()
        ledger = OperationLedger.objects.get(pk=ledger_id)
        ledger_item = OperationLedgerItem.objects.get(pk=item_id)
        event_services.record_ledger_convert_event(
            ledger_item, ledger, 'convert_to_fault',
            target_no='GZ-20260918-9999', created_by=self.admin)
        _, items = self.group_items()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item['source_type'], 'ledger_item')
        self.assertEqual(item['event_type'], 'ledger')
        self.assertEqual(item['item_no'], ledger.ledger_no)
        self.assertEqual(item['node_count'], 1)
        self.assertEqual(item['status_text'], '')


class WorkOrderUpgradeAggregationTests(SystemEventGroupTestBase):
    """工单与升级事项聚合。"""

    def test_work_order_and_upgrade_aggregate(self):
        """工单登记与升级登记/完成各自聚合成独立事项。"""
        _, work_no = self.create_work_order(self.system_a)
        self.record_upgrade_events(self.system_a, title='DVOR 数字板升级')
        _, items = self.group_items()
        self.assertEqual(len(items), 2)
        by_type = {item['event_type']: item for item in items}
        self.assertEqual(by_type['work_order']['item_no'], work_no)
        self.assertEqual(by_type['work_order']['status_text'], '待派发')
        self.assertEqual(by_type['work_order']['node_count'], 1)
        upgrade = by_type['upgrade']
        self.assertEqual(upgrade['title'], 'DVOR 数字板升级')
        self.assertEqual(upgrade['status_text'], '已完成')
        self.assertEqual(upgrade['node_count'], 2)


class GroupPaginationFilterTests(SystemEventGroupTestBase):
    """分组分页、排序与筛选。"""

    def setUp(self):
        super().setUp()
        # system_a：两个故障（后者恢复更晚，事项应排前）
        self.run_fault(self.system_a, close=False, occurred_at='2026-09-18 08:00',
                       recover_at='2026-09-18 10:00')
        self.run_fault(self.system_a, close=False, occurred_at='2026-09-20 08:00',
                       recover_at='2026-09-20 09:00')
        # system_a2：一个较早故障
        self.run_fault(self.system_a2, close=False, occurred_at='2026-09-19 08:00',
                       recover_at='2026-09-19 11:00')
        # system_a3：工单登记事件发生于当前时间（最新）
        _, self.work_no = self.create_work_order(self.system_a3)

    def test_pagination_by_system_group(self):
        """分页以系统分组为单位，分组按最近事项时间倒序。"""
        page1 = self.groups('?page=1&page_size=2')
        self.assertEqual(page1['total'], 3)
        self.assertEqual([g['system']['system_code'] for g in page1['data']],
                         ['SYS-A3', 'SYS-A1'])
        page2 = self.groups('?page=2&page_size=2')
        self.assertEqual([g['system']['system_code'] for g in page2['data']],
                         ['SYS-A2'])
        # 同一系统内事项按最近更新时间倒序
        items = page1['data'][1]['items']
        firsts = [item['first_occurred_at'] for item in items]
        self.assertEqual(sorted(firsts, reverse=True), firsts)

    def test_filters_apply_at_node_level(self):
        """筛选条件作用于节点级决定事项是否入选。"""
        _, items = self.group_items('?event_type=work_order')
        self.assertEqual([i['event_type'] for i in items], ['work_order'])
        _, items = self.group_items(f'?keyword={self.work_no}')
        self.assertEqual([i['item_no'] for i in items], [self.work_no])
        # 时间范围排除 9-18/9-19/9-20 的故障，只剩工单登记节点
        payload = self.groups('?occurred_from=2026-09-21 00:00')
        codes = [g['system']['system_code'] for g in payload['data']]
        self.assertEqual(codes, ['SYS-A3'])
        # 健康状态类型不参与事项聚合
        resp = self.client.get(f'{GROUPS_URL}/?event_type=health')
        self.assertIn('不合法', resp.json().get('error', ''))


class GroupPermissionExportTests(SystemEventGroupTestBase):
    """分组接口权限与导出契约。"""

    def test_group_apis_permission_required(self):
        """分组列表/节点/导出接口在无履历权限时真实拒绝。"""
        client = make_client(self.noperm_user)
        self.assertEqual(client.get(f'{GROUPS_URL}/').json().get('error'), '权限拒绝')
        self.assertEqual(client.get(
            f'{NODES_URL}/?system={self.system_a.id}&source_type=fault&source_id=1'
        ).json().get('error'), '权限拒绝')
        self.assertEqual(client.get(f'{EXPORT_URL}/').json().get('error'), '权限拒绝')

    def test_nodes_endpoint_validates_params(self):
        """节点接口校验来源类型与系统归属。"""
        self.run_fault(self.system_a)
        resp = self.client.get(f'{NODES_URL}/?system={self.system_a.id}&source_type=health&source_id=1')
        self.assertIn('不合法', resp.json().get('error', ''))
        # 跨租户系统返回业务错误（租户过滤）
        resp = self.client.get(
            f'{NODES_URL}/?system={self.system_b.id}&source_type=fault&source_id=1')
        self.assertIn('不存在', resp.json().get('error', ''))

    def test_export_orders_by_system_and_item(self):
        """导出按系统分组连续输出，组内按事项最近更新倒序，列序符合契约。"""
        _, work_no = self.create_work_order(self.system_a3)
        fid1, fno1 = self.run_fault(self.system_a, close=False,
                                    occurred_at='2026-09-18 08:00',
                                    recover_at='2026-09-18 10:00')
        fid2, fno2 = self.run_fault(self.system_a, close=False,
                                    occurred_at='2026-09-20 08:00',
                                    recover_at='2026-09-20 09:00')
        resp = self.client.get(f'{EXPORT_URL}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        lines = [line for line in resp.content.decode('utf-8-sig').splitlines() if line]
        self.assertEqual(lines[0].split(',')[0], '系统')
        rows = [line.split(',') for line in lines[1:]]
        self.assertEqual(len(rows), 3)
        # 分组顺序：system_a3（工单，最新）→ system_a（两个故障连续，倒序）
        self.assertEqual(rows[0][3], work_no)
        self.assertEqual(rows[1][3], fno2)
        self.assertEqual(rows[2][3], fno1)
        self.assertIn('SYS-A3', rows[0][0])
        self.assertIn('SYS-A1', rows[1][0])
        self.assertEqual(rows[1][0], rows[2][0])
        # 未关闭（未走 close）的故障节点数 = create + recover = 2
        self.assertEqual(rows[1][7], '2')
