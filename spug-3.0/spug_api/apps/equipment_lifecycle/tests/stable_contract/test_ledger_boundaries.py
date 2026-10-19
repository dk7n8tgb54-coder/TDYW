# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：租户隔离与模块边界（提示词二十三 第 24、29-30、33-36 项）。"""
from django.apps import apps as django_apps
from django.test import TestCase, TransactionTestCase

from apps.equipment_lifecycle.models import (
    ENTRY_CHANNEL_VALUES,
    LifecycleSystem,
    OperationLedger,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    LEDGER_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
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
        # 租户B 不能完成填写/作废他人台账
        resp = post_json(self.client_b, '%s/%s/complete/' % (LEDGER_URL, ledger['id']), {})
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

    def test_abnormal_ledger_does_not_create_record(self):
        """34. 台账异常不会自动创建统一记录（只有显式转故障动作才创建）。"""
        from apps.equipment_lifecycle.operation_models import SystemOperationRecord
        before = SystemOperationRecord.objects.count()
        create_ledger_ok(self.client_, ledger_payload(
            [entry_payload(self.system.id, [
                item_payload(result='abnormal', abnormal_desc='疑似硬件异常')])]))
        self.assertEqual(SystemOperationRecord.objects.count(), before)

    def test_no_offline_or_mobile_models(self):
        """35. 没有二维码、移动端或离线同步模型。"""
        model_names = {m.__name__ for m in django_apps.get_app_config('equipment_lifecycle').get_models()}
        forbidden = {'QrCode', 'MobileTask', 'OfflineTask', 'OfflineSyncQueue', 'SyncQueue',
                     'FieldTerminal', 'SiteCollection'}
        self.assertEqual(forbidden & model_names, set())
        # 台账模型集合精确可控：步骤二 + 运行处置记录（2026-10-11 合并改造，
        # 统一主表/进展表）的模型
        # （类型主数据模型已随机制移除删除；工单三表已随工单功能删除 2026-09-30；
        # 单系统简化删除受影响系统关联两表；自定义字段机制下线删除字段定义/
        # 字段值两表；旧故障四表与 SystemEvent 已随合并改造退役删除 2026-10-11；
        # 值班巡检六模型与旧设计器两模型已随迁移 0017 退役删除 2026-10-14）
        expected = {
            'LifecycleSystem',
            'SystemOperationRecord', 'SystemOperationProgress',
            # 旧可视化模板四表已随路线整体删除（2026-10，迁移 0045）
            'OperationLedger', 'OperationLedgerItem', 'OperationLedgerCorrection',
            # Excel 上传版维护台账模板（2026-09-28 试点）：模板 + 不可变版本 + 台账填写记录
            'OperationLedgerExcelTemplate', 'OperationLedgerExcelTemplateVersion',
            'OperationLedgerExcelRecord',
            # 原生维护台账模板（2026-10-18 接入，Univer 在线编辑路线）：
            # 模板 + 不可变版本 + 台账填写记录（与 Excel 三件套同构）
            'OperationLedgerNativeTemplate', 'OperationLedgerNativeTemplateVersion',
            'OperationLedgerNativeRecord',
            # 系统配置（2026-10）：参数定义/适用系统/当前值 + 配置变更主表/明细
            # （SystemParamValue 与 0023 已删除的旧自定义字段值表 SystemConfigValue 刻意区分命名）
            # 2026-10-19 增补：系统初始配置建档主表/明细（参数分类 + 基线建档）
            'ConfigParamDefinition', 'ConfigParamSystemScope', 'SystemParamValue',
            'ConfigChangeRecord', 'ConfigChangeItem',
            'SystemConfigBaseline', 'SystemConfigBaselineItem',
        }
        self.assertEqual(model_names, expected)

    def test_upgrade_and_operation_logic_untouched(self):
        """36. upgrade 和运行处置记录的状态/健康逻辑未发生无关变化。"""
        # upgrade 模型关键字段仍然在位
        upgrade_fields = {f.name for f in django_apps.get_model('upgrade', 'UpgradeRecord')._meta.get_fields()}
        self.assertIn('title', upgrade_fields)
        # 统一记录状态枚举与健康计算入口在位
        # （2026-10-11 合并改造：统一六状态，健康重算迁至 operation_services）
        from apps.equipment_lifecycle import operation_services
        from apps.equipment_lifecycle.operation_models import (
            RECORD_STATUS_VALUES, SystemOperationRecord,
        )
        self.assertEqual(
            set(RECORD_STATUS_VALUES),
            {'recorded', 'following_up', 'completed',
             'handling', 'closed', 'cancelled'})
        self.assertTrue(callable(operation_services.compute_health_status))
        self.assertTrue(callable(operation_services.recompute_systems_health))
        self.assertTrue(callable(operation_services.collect_active_impacts))
        # 旧故障编号生成已随合并退役（统一编号 JL）
        self.assertFalse(hasattr(operation_services, 'generate_fault_no'))
        self.assertTrue(callable(operation_services.generate_record_no))
        self.assertEqual(SystemOperationRecord._meta.db_table, 'tdyw_el_operation_record')
        # 本步骤新增表均使用 tdyw_el_* 新表名，不复用步骤一删除的旧表
        for model_name in ('OperationLedger', 'OperationLedgerItem',
                           'OperationLedgerCorrection'):
            table = django_apps.get_model('equipment_lifecycle', model_name)._meta.db_table
            self.assertTrue(table.startswith('tdyw_el_'), table)
            self.assertNotIn(table, {'tdyw_fault_records', 'tdyw_fault_parts',
                                     'tdyw_lifecycle_devices', 'tdyw_lifecycle_device_relations'})


class DesignerRouteRemovedContractTests(TestCase):
    """在线设计器路线下线契约（2026-09-29）：layout-templates 端点全部 404。

    设计器模型与历史表休眠保留（模型清单见
    test_no_offline_or_mobile_models），但不再存在任何 HTTP 入口；
    Excel 路线（excel-templates/excel-ledgers）不受影响。
    未认证请求会被认证中间件在 URL 解析前以 401 短路，因此本测试
    以已认证客户端发起，验证的是真实路由解析行为。
    """

    DESIGNER_PATHS = (
        '/equipment-lifecycle/layout-templates/',
        '/equipment-lifecycle/layout-templates/1/',
        '/equipment-lifecycle/layout-templates/1/draft/',
        '/equipment-lifecycle/layout-templates/1/draft/from-version/',
        '/equipment-lifecycle/layout-templates/1/publish/',
        '/equipment-lifecycle/layout-templates/1/versions/',
        '/equipment-lifecycle/layout-templates/1/versions/1/',
    )

    def setUp(self):
        self.admin = make_ledger_user('designer_gone_admin')
        self.client_ = make_client(self.admin)

    def test_layout_template_endpoints_are_gone(self):
        """设计器 CRUD/草稿/发布/版本端点均不再解析到任何视图。"""
        for path in self.DESIGNER_PATHS:
            resp = self.client_.get(path)
            self.assertEqual(resp.status_code, 404, path)
            resp = self.client_.post(path, {}, content_type='application/json')
            self.assertEqual(resp.status_code, 404, path)

    def test_excel_template_endpoints_still_served(self):
        """同前缀下的 Excel 模板端点仍正常路由（无模板权限时 @auth 拒绝而非 404）。"""
        resp = self.client_.get('/equipment-lifecycle/excel-templates/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['error'], '权限拒绝')


class VisualTemplateRouteRemovedContractTests(TestCase):
    """旧可视化模板路线下线契约（2026-10，迁移 0045）。

    正式维护台账统一走 Excel/WPS 模板路线；旧可视化模板接口（模板 CRUD、
    预览、行实例、单元格）全部 404；台账创建/编辑携带模板引用时显式拒绝；
    手工补录（manual）与 Excel（excel_template）路线不受影响。
    """

    def setUp(self):
        self.admin = make_ledger_user('visual_gone_admin')
        self.system = make_system(self.admin)
        self.client_ = make_client(self.admin)

    def test_visual_template_endpoints_are_gone(self):
        """模板 CRUD / 行节点 / 行实例 / 单元格 / 预览端点均 404。"""
        paths = (
            '/equipment-lifecycle/ledger-templates/',
            '/equipment-lifecycle/ledger-templates/1/',
            '/equipment-lifecycle/ledger-templates/1/items/',
            '/equipment-lifecycle/ledger-templates/1/row-nodes/',
            '/equipment-lifecycle/ledger-templates/available/',
            '/equipment-lifecycle/ledgers/preview/',
            '%s/1/row-instances/' % LEDGER_URL,
            '%s/1/row-instances/9/' % LEDGER_URL,
            '%s/1/cells/' % LEDGER_URL,
        )
        for path in paths:
            resp = self.client_.get(path)
            self.assertEqual(resp.status_code, 404, path)
            resp = self.client_.post(path, {}, content_type='application/json')
            self.assertEqual(resp.status_code, 404, path)

    def test_create_rejects_visual_template_source(self):
        """POST /ledgers/ 携带 created_from='template' 显式拒绝。"""
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload()])],
            created_from='template')
        resp = post_json(self.client_, LEDGER_URL + '/', payload)
        self.assertTrue(resp.json().get('error'))
        self.assertIn('不合法', resp.json()['error'])
        self.assertFalse(OperationLedger.objects.exists())

    def test_create_rejects_template_id_entries(self):
        """entries 携带 template_id（旧可视化模板引用）显式拒绝。"""
        payload = ledger_payload([
            dict(entry_payload(self.system.id, [item_payload()]), template_id=123),
        ])
        resp = post_json(self.client_, LEDGER_URL + '/', payload)
        self.assertTrue(resp.json().get('error'))
        self.assertIn('已下线', resp.json()['error'])
        self.assertFalse(OperationLedger.objects.exists())

    def test_manual_ledger_still_creatable(self):
        """手工补录路线保持可用（同一入口，manual 来源）。"""
        ledger = create_ledger_ok(self.client_, ledger_payload(
            [entry_payload(self.system.id, [item_payload()])],
            created_from='manual'))
        record = OperationLedger.objects.get(pk=ledger['id'])
        self.assertEqual(record.created_from, 'manual')
        self.assertEqual(record.items.count(), 1)
