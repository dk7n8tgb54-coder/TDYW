# -*- coding: utf-8 -*-
"""工单类型收敛（2026-09）稳定契约测试。

收敛规则：
- 顶层工单类型新建只允许 repair（故障维修）/ special_maintenance（专项维护）；
- 技术改造统一由"系统升级管理"承载，新建/编辑接口拒绝 tech_reform；
- 配置变更/现场测试/校准并入专项维护二级分类 maintenance_subtype
  （一般维护/配置变更/现场测试/校准/临时维护，缺省一般维护）；
- 故障生成维修工单固定为 repair；
- 台账异常转工单默认 special_maintenance，允许携带维护分类；
- 历史顶层类型工单仍可查询、查看、筛选与导出（迁移后维护分类落默认值）；
- 健康状态计算不变：仅执行中且影响运行的 repair 工单参与"维修中"。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from django.utils import timezone

from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    OperationLedgerItem,
    SystemFault,
    SystemWorkOrder,
    MAINTENANCE_SUBTYPE_VALUES,
    RETIRED_WORK_TYPE_HINTS,
)

from apps.equipment_lifecycle.tests.base import ALL_SYSTEM_PERMS, make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, entry_payload, item_payload, ledger_payload,
    make_ledger_user, post_json,
)
from apps.equipment_lifecycle.tests.stable_contract.test_fault_management import (
    ALL_FAULT_PERMS, fault_payload,
)
from apps.equipment_lifecycle.tests.stable_contract.test_work_orders import (
    ALL_WO_PERMS, WORK_ORDER_URL, WorkOrderTestBase, work_order_payload,
)

CONVERT_WO_URL = '/equipment-lifecycle/ledgers/{ledger}/items/{item}/convert-to-work-order/'


def make_submitted_abnormal_ledger(self):
    """创建一张已提交台账，含一条异常明细，返回 (ledger_id, item, ledger_client)。

    转单为双权限动作（ledger.handle_exception + work_order.add），
    须用同时持有两个权限的台账用户发起。
    """
    ledger_user = make_ledger_user(
        'wtc_ledger_user',
        perms=ALL_LEDGER_PERMS + ['equipment_lifecycle.ledger.handle_exception']
        + ALL_SYSTEM_PERMS + ALL_WO_PERMS,
        tenant_id='tenant_a')
    ledger_client = make_client(ledger_user)
    payload = ledger_payload([entry_payload(self.system_a.id, [
        item_payload(item_name='电压检查', input_type='number', value_text='',
                     value_number=50, result='abnormal', abnormal_desc='电压偏低'),
    ])])
    body = post_json(ledger_client, '/equipment-lifecycle/ledgers/', payload).json()
    self.assertFalse(body.get('error'), body)
    ledger_id = body['data']['id']
    resp = ledger_client.post(f'/equipment-lifecycle/ledgers/{ledger_id}/submit/',
                              {}, content_type='application/json')
    self.assertFalse(resp.json().get('error'), resp.content)
    item = OperationLedgerItem.objects.filter(
        ledger_id=ledger_id, result='abnormal').first()
    self.assertIsNotNone(item)
    return ledger_id, item, ledger_client


class WorkTypeConvergenceTest(WorkOrderTestBase):
    """顶层工单类型收敛 + 维护二级分类契约。"""

    # ---------- 新建：两种保留类型 ----------

    def test_create_repair_order_with_default_subtype(self):
        """新建故障维修工单成功：维护分类落后端统一默认值（不依赖前端传值）。"""
        data = self.create_order_ok(work_order_payload(
            self.system_a, work_type='repair', maintenance_subtype='calibration'))
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.work_type, 'repair')
        # repair 的二级分类无业务含义：即使前端误传也统一落默认值
        self.assertEqual(order.maintenance_subtype, SystemWorkOrder.SUBTYPE_GENERAL)
        self.assertEqual(data['maintenance_subtype_text'], '一般维护')

    def test_create_special_maintenance_with_subtype(self):
        """新建专项维护工单并保存二级分类：五个合法分类逐一入库。"""
        for subtype in MAINTENANCE_SUBTYPE_VALUES:
            with self.subTest(subtype=subtype):
                data = self.create_order_ok(work_order_payload(
                    self.system_a, work_type='special_maintenance',
                    title=f'专项维护-{subtype}', maintenance_subtype=subtype))
                order = SystemWorkOrder.objects.get(pk=data['id'])
                self.assertEqual(order.work_type, 'special_maintenance')
                self.assertEqual(order.maintenance_subtype, subtype)
                self.assertEqual(
                    data['maintenance_subtype_text'],
                    SystemWorkOrder.SUBTYPE_TEXT_MAP[subtype])

    def test_create_special_maintenance_subtype_defaults_general(self):
        """专项维护未传维护分类时默认"一般维护"。"""
        data = self.create_order_ok(work_order_payload(
            self.system_a, work_type='special_maintenance'))
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.maintenance_subtype, SystemWorkOrder.SUBTYPE_GENERAL)

    def test_special_maintenance_invalid_subtype_rejected(self):
        """专项维护提交非法维护分类被拒绝，不静默兜底。"""
        self.create_order(work_order_payload(
            self.system_a, work_type='special_maintenance',
            maintenance_subtype='not_a_subtype'),
            expect_error='维护分类不合法')
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    # ---------- 新建/编辑：已下线顶层类型拒绝 ----------

    def test_retired_top_level_types_rejected_on_create(self):
        """新建工单使用已下线顶层类型被拒绝（技术改造/配置变更/现场测试/校准）。"""
        for work_type, hint in RETIRED_WORK_TYPE_HINTS.items():
            with self.subTest(work_type=work_type):
                body = self.create_order(work_order_payload(
                    self.system_a, work_type=work_type))
                self.assertTrue(body.get('error'), body)
                self.assertIn('已下线', body['error'])
                self.assertIn(hint, body['error'])
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    def test_tech_reform_hint_points_to_upgrade_module(self):
        """技术改造的拒绝文案指向系统升级管理（界面边界提示的后端事实来源）。"""
        body = self.create_order(work_order_payload(
            self.system_a, work_type='tech_reform'))
        self.assertIn('系统升级管理', body['error'])

    def test_retired_top_level_types_rejected_on_edit(self):
        """编辑工单同样拒绝已下线顶层类型，原工单数据不被改写。"""
        data = self.create_order_ok(work_order_payload(
            self.system_a, work_type='special_maintenance',
            maintenance_subtype='field_test'))
        client = make_client(self.admin)
        for work_type in RETIRED_WORK_TYPE_HINTS:
            resp = client.put(f'{WORK_ORDER_URL}/{data["id"]}/',
                              work_order_payload(self.system_a, work_type=work_type),
                              content_type='application/json')
            self.assertIn('已下线', resp.json().get('error', ''), resp.content)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.work_type, 'special_maintenance')
        self.assertEqual(order.maintenance_subtype, 'field_test')

    def test_edit_executing_order_updates_subtype(self):
        """编辑执行中专项维护工单可更新维护分类。"""
        data = self.create_order_ok(work_order_payload(
            self.system_a, work_type='special_maintenance'))
        resp = make_client(self.admin).put(
            f'{WORK_ORDER_URL}/{data["id"]}/',
            work_order_payload(self.system_a, work_type='special_maintenance',
                               maintenance_subtype='temporary_maintenance'),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.maintenance_subtype, 'temporary_maintenance')

    # ---------- 故障生成维修工单固定 repair ----------

    def create_active_fault(self):
        resp = make_client(self.admin).post(
            '/equipment-lifecycle/faults/',
            fault_payload(self.system_a, impact_status='degraded'),
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return SystemFault.objects.get(pk=body['data']['id'])

    def test_fault_convert_defaults_to_repair(self):
        """故障生成维修工单固定为 repair，维护分类落统一默认值。"""
        fault = self.create_active_fault()
        resp = make_client(self.admin).post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'wtc-fault-1'}, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        order = SystemWorkOrder.objects.get(pk=body['data']['id'])
        self.assertEqual(order.work_type, 'repair')
        self.assertEqual(order.maintenance_subtype, SystemWorkOrder.SUBTYPE_GENERAL)

    def test_fault_convert_rejects_non_repair_type(self):
        """故障转单显式提交非 repair 顶层类型被拒绝（不再冒充其他类型）。"""
        fault = self.create_active_fault()
        resp = make_client(self.admin).post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'wtc-fault-2', 'work_type': 'special_maintenance'},
            content_type='application/json')
        self.assertIn('固定为故障维修', resp.json().get('error', ''), resp.content)
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    # ---------- 台账异常转工单：默认专项维护 + 携带维护分类 ----------

    def test_ledger_convert_defaults_special_maintenance_general(self):
        """台账异常转工单默认专项维护 + 默认"一般维护"维护分类。"""
        ledger_id, item, ledger_client = make_submitted_abnormal_ledger(self)
        resp = ledger_client.post(
            CONVERT_WO_URL.format(ledger=ledger_id, item=item.id),
            {'title': '异常转工单-默认分类', 'client_token': 'wtc-li-1'},
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        order = SystemWorkOrder.objects.get(pk=body['data']['id'])
        self.assertEqual(order.work_type, 'special_maintenance')
        self.assertEqual(order.maintenance_subtype, SystemWorkOrder.SUBTYPE_GENERAL)
        self.assertEqual(order.source_type, 'ledger_item')
        self.assertEqual(order.source_ledger_item_id, item.id)

    def test_ledger_convert_carries_subtype(self):
        """台账异常转工单携带维护分类（校准）成功入库。"""
        ledger_id, item, ledger_client = make_submitted_abnormal_ledger(self)
        resp = ledger_client.post(
            CONVERT_WO_URL.format(ledger=ledger_id, item=item.id),
            {'title': '异常转工单-校准', 'client_token': 'wtc-li-2',
             'work_type': 'special_maintenance', 'maintenance_subtype': 'calibration'},
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        order = SystemWorkOrder.objects.get(pk=body['data']['id'])
        self.assertEqual(order.maintenance_subtype, 'calibration')

    def test_ledger_convert_rejects_retired_type_and_bad_subtype(self):
        """台账异常转工单拒绝已下线顶层类型与非法维护分类。"""
        ledger_id, item, ledger_client = make_submitted_abnormal_ledger(self)
        resp = ledger_client.post(
            CONVERT_WO_URL.format(ledger=ledger_id, item=item.id),
            {'title': '异常转工单-技术改造', 'work_type': 'tech_reform',
             'client_token': 'wtc-li-3'},
            content_type='application/json')
        self.assertIn('已下线', resp.json().get('error', ''), resp.content)
        resp = ledger_client.post(
            CONVERT_WO_URL.format(ledger=ledger_id, item=item.id),
            {'title': '异常转工单-非法分类', 'maintenance_subtype': 'oops',
             'client_token': 'wtc-li-4'},
            content_type='application/json')
        self.assertIn('维护分类不合法', resp.json().get('error', ''), resp.content)
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    # ---------- 历史旧类型工单：可查询/查看/筛选/导出 ----------

    def test_legacy_typed_order_still_queryable_viewable_exportable(self):
        """历史顶层类型工单（技术改造）仍可查询、详情查看、按类型筛选与导出。

        以 queryset.update 模拟收敛前的历史数据（绕过创建接口校验，
        CHECK 约束仍允许历史类型值），不删除、不改写历史记录。
        """
        data = self.create_order_ok(work_order_payload(
            self.system_a, work_type='special_maintenance',
            title='历史技术改造工单'))
        SystemWorkOrder.objects.filter(pk=data['id']).update(work_type='tech_reform')
        client = make_client(self.admin)
        # 未筛选列表仍然可见，且显示原类型文本
        rows = client.get(f'{WORK_ORDER_URL}/').json()['data']['data']
        row = next(r for r in rows if r['id'] == data['id'])
        self.assertEqual(row['work_type'], 'tech_reform')
        self.assertEqual(row['work_type_text'], '技术改造')
        # 历史类型仍可作为筛选条件（筛选不导致历史数据消失）
        rows = client.get(f'{WORK_ORDER_URL}/?work_type=tech_reform').json()['data']['data']
        self.assertIn(data['id'], [r['id'] for r in rows])
        # 详情可查看
        detail = client.get(f'{WORK_ORDER_URL}/{data["id"]}/').json()['data']
        self.assertEqual(detail['work_type'], 'tech_reform')
        self.assertEqual(detail['work_type_text'], '技术改造')
        # 导出包含历史类型文本
        resp = client.get(f'{WORK_ORDER_URL}/export/')
        self.assertEqual(resp.status_code, 200)
        csv_text = resp.content.decode('utf-8-sig')
        self.assertIn('历史技术改造工单', csv_text)
        self.assertIn('技术改造', csv_text)

    # ---------- 健康状态：非 repair 不参与"维修中" ----------

    def test_special_maintenance_executing_does_not_set_repairing(self):
        """执行中且影响运行的专项维护工单不使系统进入"维修中"。"""
        order = self.run_to_executing(work_type='special_maintenance',
                                      title='专项维护-影响运行',
                                      affects=True)
        self.assertTrue(order.affects_system_operation)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        # 服务层直接重算结果一致（幂等）
        fault_services.recompute_systems_health('tenant_a', [self.system_a.id])
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/cancel/',
                                     {'cancel_reason': '测试清理'},
                                     content_type='application/json')

    def test_legacy_typed_executing_order_does_not_set_repairing(self):
        """历史顶层类型工单（执行中 + 影响运行）不参与"维修中"计算。"""
        order = self.run_to_executing(work_type='special_maintenance',
                                      title='历史配置变更-影响运行',
                                      affects=True)
        SystemWorkOrder.objects.filter(pk=order.id).update(work_type='config_change')
        fault_services.recompute_systems_health('tenant_a', [self.system_a.id])
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/cancel/',
                                     {'cancel_reason': '测试清理'},
                                     content_type='application/json')

    def test_repair_order_with_subtype_still_sets_repairing(self):
        """repair 工单参与维修中计算的行为不受维护分类字段影响。"""
        self.create_active_fault()
        order = self.run_to_executing(work_type='repair', title='维修-回归冒烟')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'repairing')
        make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/cancel/',
                                     {'cancel_reason': '测试清理'},
                                     content_type='application/json')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'degraded')

    def test_retired_type_not_written_by_any_create_path(self):
        """任何创建路径都不再写入已下线顶层类型（人工/故障/台账转单三入口）。"""
        fault = self.create_active_fault()
        make_client(self.admin).post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'wtc-b1', 'work_type': 'tech_reform'},
            content_type='application/json')
        ledger_id, item, ledger_client = make_submitted_abnormal_ledger(self)
        ledger_client.post(
            CONVERT_WO_URL.format(ledger=ledger_id, item=item.id),
            {'title': '转单-技术改造拒绝', 'work_type': 'tech_reform',
             'client_token': 'wtc-b2'},
            content_type='application/json')
        self.create_order(work_order_payload(self.system_a, work_type='tech_reform'))
        self.assertFalse(
            SystemWorkOrder.objects.filter(work_type='tech_reform').exists())


class WorkOrderSubtypeSerializationTest(WorkOrderTestBase):
    """二级分类在列表/详情序列化中的展示契约。"""

    def test_list_and_detail_carry_subtype_fields(self):
        """列表与详情均返回 maintenance_subtype 与中文文本。"""
        data = self.create_order_ok(work_order_payload(
            self.system_a, work_type='special_maintenance',
            maintenance_subtype='field_test'))
        client = make_client(self.admin)
        row = next(r for r in client.get(f'{WORK_ORDER_URL}/').json()['data']['data']
                   if r['id'] == data['id'])
        self.assertEqual(row['maintenance_subtype'], 'field_test')
        self.assertEqual(row['maintenance_subtype_text'], '现场测试')
        detail = client.get(f'{WORK_ORDER_URL}/{data["id"]}/').json()['data']
        self.assertEqual(detail['maintenance_subtype'], 'field_test')
        self.assertEqual(detail['maintenance_subtype_text'], '现场测试')

    def test_export_special_maintenance_subtype_column(self):
        """导出含"维护分类"列：专项维护输出分类文本，故障维修留空。"""
        special = self.create_order_ok(work_order_payload(
            self.system_a, work_type='special_maintenance',
            title='导出-专项维护', maintenance_subtype='temporary_maintenance'))
        repair = self.create_order_ok(work_order_payload(
            self.system_a, work_type='repair', title='导出-故障维修'))
        resp = make_client(self.admin).get(f'{WORK_ORDER_URL}/export/')
        self.assertEqual(resp.status_code, 200)
        csv_text = resp.content.decode('utf-8-sig')
        self.assertIn('维护分类', csv_text.splitlines()[0])
        special_line = next(line for line in csv_text.splitlines()
                            if '导出-专项维护' in line)
        self.assertIn('临时维护', special_line)
        repair_line = next(line for line in csv_text.splitlines()
                           if '导出-故障维修' in line)
        # 故障维修行的维护分类列不输出（留空），且不出现"临时维护"串列
        self.assertNotIn('临时维护', repair_line)
        self.assertEqual(SystemWorkOrder.objects.filter(
            pk__in=[special['id'], repair['id']]).count(), 2)

    def test_model_constraint_covers_subtype_values(self):
        """模型 CHECK 约束覆盖全部维护分类取值。"""
        names = [c.name for c in SystemWorkOrder._meta.constraints]
        self.assertIn('el_work_order_subtype_valid', names)
        field = SystemWorkOrder._meta.get_field('maintenance_subtype')
        self.assertEqual(field.default, SystemWorkOrder.SUBTYPE_GENERAL)
        self.assertEqual(
            {v for v, _ in field.choices}, set(MAINTENANCE_SUBTYPE_VALUES))

    def test_cancel_still_records_audit_fields(self):
        """回归冒烟：收敛改造后工单取消链路不受影响（记录取消账号与时间）。"""
        data = self.create_order_ok(work_order_payload(
            self.system_a, work_type='special_maintenance'))
        before = timezone.now()
        resp = make_client(self.admin).post(f'{WORK_ORDER_URL}/{data["id"]}/cancel/',
                                            {'cancel_reason': '收敛回归'},
                                            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_CANCELLED)
        self.assertIsNotNone(order.cancelled_at)
        self.assertGreaterEqual(order.cancelled_at, before)
        self.assertEqual(order.maintenance_subtype, SystemWorkOrder.SUBTYPE_GENERAL)


class WorkOrderUpgradeBoundaryTest(WorkOrderTestBase):
    """技术改造与系统升级的模块边界。"""

    def test_upgrade_module_models_unchanged(self):
        """系统升级模块模型集合不受工单类型收敛影响。"""
        from django.apps import apps
        expected_upgrade = {'UpgradeRecord', 'UpgradeTemplate',
                            'UpgradePlanStep', 'UpgradeRecordStep', 'UpgradeStatusLog'}
        actual_upgrade = {m.__name__ for m in apps.get_app_config('upgrade').get_models()}
        self.assertEqual(actual_upgrade, expected_upgrade)

    def test_make_system_helper_unaffected(self):
        """回归冒烟：系统主数据不受本次改造影响。"""
        system = make_system(self.admin, tenant_id='tenant_a',
                             system_code='SYS-WTC', name='收敛冒烟系统')
        self.assertEqual(system.system_code, 'SYS-WTC')
