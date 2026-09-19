# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：租户隔离与模块边界（提示词二十三 第 24、29-30、33-36 项）。"""
from django.apps import apps as django_apps
from django.test import TestCase, TransactionTestCase

from apps.equipment_lifecycle.models import (
    ENTRY_CHANNEL_VALUES,
    LEDGER_TYPE_INSPECTION,
    LifecycleSystem,
    OperationLedger,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    LEDGER_URL,
    POINT_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    make_point,
    post_json,
)


class LedgerIsolationContractTests(TestCase):
    def setUp(self):
        self.admin_a = make_ledger_user('iso_admin_a', tenant_id='tenant-a')
        self.admin_b = make_ledger_user('iso_admin_b', tenant_id='tenant-b')
        self.system_a = make_system(self.admin_a, tenant_id='tenant-a',
                                    system_code='SYS-A1', name='A租户系统')
        self.client_a = make_client(self.admin_a)
        self.client_b = make_client(self.admin_b)

    def test_tenant_ledgers_invisible_to_each_other(self):
        """29. 不同租户的台账互不可见。"""
        ledger = create_ledger_ok(self.client_a, ledger_payload(
            [entry_payload(self.system_a.id, [item_payload()])]))
        # 租户B 列表看不到
        resp = self.client_b.get(LEDGER_URL + '/')
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertNotIn(ledger['id'], ids)
        # 租户B 详情拿不到
        resp = self.client_b.get('%s/%s/' % (LEDGER_URL, ledger['id']))
        self.assertTrue(resp.json().get('error'))
        # 租户B 不能提交/作废他人台账
        resp = post_json(self.client_b, '%s/%s/submit/' % (LEDGER_URL, ledger['id']), {})
        self.assertTrue(resp.json().get('error'))

    def test_system_detail_items_scoped_to_current_system(self):
        """30. 系统详情只能读取有权限查看的当前系统明细。"""
        system_b_tenant_a = make_system(
            self.admin_a, tenant_id='tenant-a',
            system_code='SYS-A2', name='A租户第二系统')
        ledger = create_ledger_ok(self.client_a, ledger_payload([
            entry_payload(self.system_a.id, [item_payload(item_name='A系统项')]),
            entry_payload(system_b_tenant_a.id, [item_payload(item_name='第二系统项')]),
        ]))
        # 一张台账包含两个系统，但按系统查询只返回当前系统明细
        resp = self.client_a.get('/equipment-lifecycle/systems/%s/ledger-items/' % self.system_a.id)
        self.assertFalse(resp.json().get('error'))
        names = [i['item_name'] for i in resp.json()['data']['data']]
        self.assertIn('A系统项', names)
        self.assertNotIn('第二系统项', names)
        # 无权限（其他租户）访问该系统 → 拒绝
        resp = self.client_b.get('/equipment-lifecycle/systems/%s/ledger-items/' % self.system_a.id)
        self.assertTrue(resp.json().get('error'))

    def test_entry_channel_fixed_to_web(self):
        """24. entry_channel 当前只能为 WEB。"""
        ledger = create_ledger_ok(self.client_a, ledger_payload(
            [entry_payload(self.system_a.id, [item_payload()])]))
        record = OperationLedger.objects.get(pk=ledger['id'])
        self.assertEqual(record.entry_channel, 'web')
        self.assertEqual(ENTRY_CHANNEL_VALUES, ['web'])


class LedgerBoundaryContractTests(TestCase):
    """跨模块边界验证（3.1 故障模型 / 健康状态 / 禁建能力）。"""

    def setUp(self):
        self.admin = make_ledger_user('boundary_op')
        self.system = make_system(self.admin)
        self.client_ = make_client(self.admin)

    def test_abnormal_ledger_does_not_touch_health_status(self):
        """33. 台账异常不会自动修改系统健康状态。"""
        self.system.health_status = 'normal'
        self.system.save()
        create_ledger_ok(self.client_, ledger_payload(
            [entry_payload(self.system.id, [
                item_payload(result='abnormal', abnormal_desc='链路中断')])]))
        self.system.refresh_from_db()
        self.assertEqual(self.system.health_status, 'normal')

    def test_abnormal_ledger_does_not_create_fault(self):
        """34. 台账异常不会自动创建故障或工单（步骤 3.1 SystemFault 数量不变）。"""
        from apps.equipment_lifecycle.models import SystemFault
        before = SystemFault.objects.count()
        create_ledger_ok(self.client_, ledger_payload(
            [entry_payload(self.system.id, [
                item_payload(result='abnormal', abnormal_desc='疑似硬件异常')])]))
        self.assertEqual(SystemFault.objects.count(), before)

    def test_no_offline_or_mobile_models(self):
        """35. 没有二维码、移动端或离线同步模型。"""
        model_names = {m.__name__ for m in django_apps.get_app_config('equipment_lifecycle').get_models()}
        forbidden = {'QrCode', 'MobileTask', 'OfflineTask', 'OfflineSyncQueue', 'SyncQueue',
                     'FieldTerminal', 'SiteCollection'}
        self.assertEqual(forbidden & model_names, set())
        # 台账模型集合精确可控：仅允许步骤二 + 3.1 + 3.2 + 3.3（工单四表）
        # + 3.4（统一系统履历）的模型（类型主数据模型已随机制移除删除）
        expected = {
            'LifecycleSystem', 'ConfigFieldDefinition', 'SystemConfigValue',
            'SystemConfigComponent', 'SystemConfigChange', 'SystemConfigSnapshot',
            'SystemFault', 'SystemFaultAffectedSystem', 'SystemFaultHandlingRecord',
            'SystemInspectionPoint', 'OperationLedgerTemplate', 'OperationLedgerTemplateItem',
            'OperationLedger', 'OperationLedgerItem', 'OperationLedgerCorrection',
            'SystemWorkOrder', 'SystemWorkOrderAffectedSystem',
            'SystemWorkOrderParticipant', 'SystemWorkOrderHandlingRecord',
            'SystemEvent',
        }
        self.assertEqual(model_names, expected)

    def test_device_upgrade_and_fault_logic_untouched(self):
        """36. device、upgrade 和步骤 3.1 故障状态逻辑未发生无关变化。"""
        # device / upgrade 模型关键字段仍然在位
        device_fields = {f.name for f in django_apps.get_model('device', 'DeviceResume')._meta.get_fields()}
        self.assertIn('device_name', device_fields)
        upgrade_fields = {f.name for f in django_apps.get_model('upgrade', 'UpgradeRecord')._meta.get_fields()}
        self.assertIn('title', upgrade_fields)
        # 步骤 3.1 故障模型与状态计算入口未被本步骤修改
        from apps.equipment_lifecycle import fault_services
        from apps.equipment_lifecycle.models import SystemFault
        self.assertEqual(
            {SystemFault.STATUS_PENDING, SystemFault.STATUS_HANDLING, SystemFault.STATUS_RECOVERED,
             SystemFault.STATUS_CLOSED, SystemFault.STATUS_CANCELLED},
            {'pending', 'handling', 'recovered', 'closed', 'cancelled'})
        self.assertTrue(callable(fault_services.compute_health_status))
        self.assertTrue(callable(fault_services.recompute_systems_health))
        self.assertTrue(callable(fault_services.collect_active_impacts))
        # 本步骤新增表均使用 tdyw_el_* 新表名，不复用步骤一删除的旧表
        for model_name in ('OperationLedger', 'OperationLedgerItem', 'OperationLedgerTemplate',
                           'OperationLedgerTemplateItem', 'SystemInspectionPoint',
                           'OperationLedgerCorrection'):
            table = django_apps.get_model('equipment_lifecycle', model_name)._meta.db_table
            self.assertTrue(table.startswith('tdyw_el_'), table)
            self.assertNotIn(table, {'tdyw_fault_records', 'tdyw_fault_parts',
                                     'tdyw_lifecycle_devices', 'tdyw_lifecycle_device_relations'})
