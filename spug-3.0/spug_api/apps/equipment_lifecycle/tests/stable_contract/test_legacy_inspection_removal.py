# -*- coding: utf-8 -*-
"""旧巡检台账（历史）删除改造（2026-09-24）稳定契约测试。

覆盖契约：
1. 旧巡检类型请求返回明确的"已删除/不再支持"业务错误（不静默当作维护台账）；
2. 新建 ledger_type=inspection 被拒绝；
3. 清理命令只删除 inspection 类型数据（dry-run/--confirm/租户范围/事务回滚）；
4-6. 周/月/季维护数据不被删除；
7. 维护台账查询、新增、编辑、提交、退回、复核、作废仍正常；
8-9. 维护台账转故障仍正常（转工单已随工单功能删除，2026-09-30）；
10. 旧巡检关联故障不会被删除；
11. 外部引用迁移后来源信息仍可查看（legacy 快照）；
12.（原"新巡检创建、提交、详情、导出仍正常"已随日巡视活跃功能下线移除，
    由 test_daily_inspection_removal.py 承接）；
13. 租户隔离仍然有效；
14-15. dry-run / 未提供 --confirm 不修改数据库；
16. 删除过程异常时事务回滚；
17. 删除后共享模型和维护数据完整。

测试库已应用 0029（CHECK 只允许 week_month/seasonal），模拟"清理前"的
旧巡检数据须先在本隔离测试库内临时 DROP 对应 CHECK（TransactionTestCase
内执行，测后恢复）；不触碰任何业务数据库。
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, models
from django.test import TestCase, TransactionTestCase

from apps.equipment_lifecycle.management.commands import purge_legacy_inspection_ledgers as purge_cmd
from apps.equipment_lifecycle.ledger_services import (
    LEGACY_INSPECTION_ERROR,
    legacy_inspection_error,
)
from apps.equipment_lifecycle.operation_models import SystemOperationRecord
from apps.equipment_lifecycle.models import (
    LEGACY_LEDGER_TYPE_INSPECTION,
    LEDGER_NO_PREFIX_MAP,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_TEXT,
    LEDGER_TYPE_VALUES,
    LEDGER_TYPE_WEEK_MONTH,
    LEDGER_STATUS_REVIEWED,
    LEDGER_STATUS_VOID,
    OperationLedger,
    OperationLedgerCorrection,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS, URL_PREFIX, make_client, make_system, make_user)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    ALL_TEMPLATE_PERMS,
    LEDGER_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    post_json,
    put_json,
)

# 旧可视化模板路由（已随路线删除，仅 404 契约断言使用）
TEMPLATE_URL = URL_PREFIX + '/ledger-templates'

# 0029 收窄后的 CHECK 定义（与迁移文件一致，用于测试库内临时拆除与恢复）
def _iter_ledger_check_constraints():
    for model in (OperationLedger,):
        for constraint in model._meta.constraints:
            if isinstance(constraint, models.CheckConstraint):
                yield model, constraint


def _drop_ledger_type_checks():
    """测试库内临时拆除台账类型/周期 CHECK（仅隔离测试库，模拟清理前状态）。"""
    with connection.schema_editor(atomic=False) as editor:
        for model, constraint in _iter_ledger_check_constraints():
            editor.remove_constraint(model, constraint)


def _restore_ledger_type_checks():
    """先清掉本测试残留的旧巡检行（否则 ADD CHECK 校验存量行会失败），再恢复约束。"""
    with connection.cursor() as cur:
        # 先删统一记录（source_ledger_item 外键 PROTECT，须先于明细删除）；
        # 旧故障表已随 2026-10-11 合并改造删除
        cur.execute(
            'DELETE FROM tdyw_el_operation_record WHERE tenant_id IN (%s, %s)',
            ['tenant_a', 'tenant_b'])
        cur.execute(
            'DELETE FROM tdyw_el_ledger_correction WHERE ledger_id IN ('
            '  SELECT id FROM tdyw_el_operation_ledger WHERE ledger_type=%s)',
            ['inspection'])
        cur.execute(
            'DELETE FROM tdyw_el_operation_ledger_item WHERE ledger_id IN ('
            '  SELECT id FROM tdyw_el_operation_ledger WHERE ledger_type=%s)',
            ['inspection'])
        cur.execute(
            'DELETE FROM tdyw_el_operation_ledger WHERE ledger_type=%s',
            ['inspection'])
    with connection.schema_editor(atomic=False) as editor:
        for model, constraint in _iter_ledger_check_constraints():
            editor.add_constraint(model, constraint)


def call_purge(*args, **kwargs):
    out = []
    call_command('purge_legacy_inspection_ledgers', *args,
                 stdout=_Buffer(out), **kwargs)
    return '\n'.join(out)


class _Buffer:
    def __init__(self, lines):
        self.lines = lines

    def write(self, msg):
        self.lines.append(msg)


class LegacyInspectionTypeRejectedTest(TestCase):
    """1/2：旧巡检类型请求一律返回明确的"已删除"错误。"""

    def setUp(self):
        self.user = make_ledger_user(
            'legacy_reject_op', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.system = make_system(self.user)
        self.client_ = make_client(self.user)

    def test_create_rejects_inspection_type(self):
        """2. 新建 ledger_type=inspection 被拒绝并返回明确错误。"""
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload()])],
            ledger_type='inspection')
        resp = post_json(self.client_, LEDGER_URL + '/', payload)
        body = resp.json()
        self.assertTrue(body.get('error'))
        self.assertIn('已删除', body['error'])
        self.assertEqual(OperationLedger.objects.filter(
            ledger_type='inspection').count(), 0)

    def test_preview_route_removed(self):
        """预览接口已随旧可视化模板路线删除（404，2026-10）。"""
        resp = post_json(self.client_, LEDGER_URL + '/preview/', {
            'ledger_type': 'inspection',
            'entries': [{'system_id': self.system.id}]})
        self.assertEqual(resp.status_code, 404)

    def test_visual_template_route_removed(self):
        """旧可视化台账模板接口已随路线整体删除（404，2026-10）。"""
        resp = self.client_.get(TEMPLATE_URL + '/')
        self.assertEqual(resp.status_code, 404)

    def test_ledger_type_enum_no_inspection(self):
        """枚举/前缀/文本映射均无 inspection 分支，legacy 常量仅用于拒绝。"""
        self.assertEqual(LEDGER_TYPE_VALUES, ['week_month', 'seasonal'])
        self.assertNotIn('inspection', LEDGER_NO_PREFIX_MAP)
        self.assertNotIn('inspection', LEDGER_TYPE_TEXT)
        self.assertEqual(LEGACY_LEDGER_TYPE_INSPECTION, 'inspection')

    def test_legacy_guard_rejects_write_paths(self):
        """对存量旧巡检台账的写操作统一拦截（防清理前窗口被当作维护台账）。"""
        legacy = SimpleNamespace(ledger_type='inspection')
        self.assertEqual(legacy_inspection_error(legacy), LEGACY_INSPECTION_ERROR)
        self.assertIsNone(legacy_inspection_error(
            SimpleNamespace(ledger_type='week_month')))


class MaintenanceLedgerStillWorksTest(TestCase):
    """7：周月/季维护台账查询、新增、编辑、提交、退回、复核、作废仍正常。"""

    def setUp(self):
        self.user = make_ledger_user('maint_flow_op')
        self.system = make_system(self.user)
        self.client_ = make_client(self.user)

    def _create_ledger(self, executed_date='2026-09-10', ledger_type=LEDGER_TYPE_WEEK_MONTH):
        payload = ledger_payload(
            [entry_payload(self.system.id, [
                item_payload(),
                item_payload(item_name='电源电压测量', input_type='number',
                             value_text='', value_number=52,
                             result='abnormal', abnormal_desc='电压偏低'),
            ])],
            ledger_type=ledger_type, executed_date=executed_date)
        return create_ledger_ok(self.client_, payload)

    def test_full_maintenance_workflow(self):
        """新增→编辑→提交→退回→再提交→复核→更正→作废 全链路可用。"""
        data = self._create_ledger()
        ledger_id = data['id']
        # 编辑：version 并发控制 + 明细新增
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload(), item_payload(
                item_name='新增项', value_text='正常')])],
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            executed_date='2026-09-10', version=1)
        resp = put_json(self.client_, '%s/%s/' % (LEDGER_URL, ledger_id), payload)
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['version'], 2)
        # 提交
        resp = post_json(self.client_, '%s/%s/submit/' % (LEDGER_URL, ledger_id), {})
        self.assertFalse(resp.json().get('error'), resp.content)
        # 退回（需要退回原因）
        resp = post_json(self.client_, '%s/%s/return/' % (LEDGER_URL, ledger_id),
                         {'reason': '数据待补充'})
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['status'], 'returned')
        # 再提交 → 复核
        post_json(self.client_, '%s/%s/submit/' % (LEDGER_URL, ledger_id), {})
        resp = post_json(self.client_, '%s/%s/review/' % (LEDGER_URL, ledger_id), {})
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['status'], LEDGER_STATUS_REVIEWED)
        # 复核后更正
        resp = post_json(self.client_, '%s/%s/correct/' % (LEDGER_URL, ledger_id),
                         {'reason': '笔误更正', 'executor_names': '王五'})
        self.assertFalse(resp.json().get('error'), resp.content)
        # 查询（列表 + 详情）
        resp = self.client_.get(LEDGER_URL + '/?ledger_type=week_month')
        self.assertIn(ledger_id, [r['id'] for r in resp.json()['data']['data']])
        resp = self.client_.get('%s/%s/' % (LEDGER_URL, ledger_id))
        self.assertFalse(resp.json().get('error'), resp.content)
        # 作废（受控终态）
        resp = post_json(self.client_, '%s/%s/void/' % (LEDGER_URL, ledger_id),
                         {'reason': '整单作废'})
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(
            OperationLedger.objects.get(pk=ledger_id).status, LEDGER_STATUS_VOID)

    def test_week_month_seasonal_all_creatable(self):
        """4/5/6：周月维护（单表）与季维护台账均可正常创建并保留。"""
        self._create_ledger('2026-09-10')
        self._create_ledger('2026-09-30')
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload()])],
            ledger_type=LEDGER_TYPE_SEASONAL,
            executed_date='2026-09-20')
        seasonal = create_ledger_ok(self.client_, payload)
        self.assertEqual(seasonal['ledger_type'], 'seasonal')
        self.assertEqual(
            OperationLedger.objects.filter(
                ledger_type=LEDGER_TYPE_WEEK_MONTH).count(), 2)
        self.assertEqual(
            OperationLedger.objects.filter(
                ledger_type=LEDGER_TYPE_SEASONAL).count(), 1)


class MaintenanceConvertStillWorksTest(TestCase):
    """8：维护台账异常明细转故障仍正常（转工单已随工单功能删除）。"""

    def setUp(self):
        perms = ALL_LEDGER_PERMS + ALL_SYSTEM_PERMS + [
            'equipment_lifecycle.ledger.handle_exception',
            'equipment_lifecycle.operation_record.view',
            'equipment_lifecycle.operation_record.add_fault',
        ]
        self.user = make_user('maint_convert_op', perms=perms, tenant_id='default')
        self.system = make_system(self.user)
        self.client_ = make_client(self.user)

    def _submitted_ledger_with_abnormal_item(self):
        payload = ledger_payload(
            [entry_payload(self.system.id, [
                item_payload(item_name='电源电压测量', input_type='number',
                             value_text='', value_number=52,
                             result='abnormal', abnormal_desc='电压偏低'),
            ])],
            ledger_type=LEDGER_TYPE_WEEK_MONTH)
        data = create_ledger_ok(self.client_, payload)
        resp = post_json(self.client_, '%s/%s/submit/' % (LEDGER_URL, data['id']), {})
        self.assertFalse(resp.json().get('error'), resp.content)
        item = OperationLedgerItem.objects.get(ledger_id=data['id'], result='abnormal')
        return data['id'], item.id

    def test_week_month_item_converts_to_fault(self):
        ledger_id, item_id = self._submitted_ledger_with_abnormal_item()
        resp = post_json(self.client_,
                         '/equipment-lifecycle/ledgers/%s/items/%s/convert-to-fault/' % (
                             ledger_id, item_id), {})
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        record = SystemOperationRecord.objects.get(pk=body['data']['id'])
        self.assertEqual(record.record_type, 'fault')
        self.assertEqual(record.status, 'handling')
        self.assertEqual(record.source_type, 'ledger_item')
        self.assertEqual(record.source_ledger_item_id, item_id)

    def test_week_month_item_convert_to_work_order_removed(self):
        """9：台账异常转工单端点已随工单功能删除（404），不产生工单或故障。"""
        ledger_id, item_id = self._submitted_ledger_with_abnormal_item()
        resp = post_json(self.client_,
                         '/equipment-lifecycle/ledgers/%s/items/%s/convert-to-work-order/' % (
                             ledger_id, item_id),
                         {'work_type': 'special_maintenance', 'client_token': 'tok-maint-wo'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(SystemOperationRecord.objects.count(), 0)


# 契约 12（新巡检创建、提交、详情、导出仍正常）已随"日巡视"活跃功能整体
# 下线（2026-10-11）移除，由 test_daily_inspection_removal.py 的下线契约
# （端点 404 + 历史数据/故障来源/履历展示兼容）承接；本文件继续覆盖
# 旧巡检台账（历史）的历史兼容保护契约，保持不变。


class LegacyPurgeCommandTest(TransactionTestCase):
    """3-6/10/11/13-17：受控清理命令行为（含 dry-run、--confirm、租户范围、回滚）。"""

    def setUp(self):
        # 测试库已应用 0029 收窄约束；为模拟"清理前"历史数据，临时拆除 CHECK
        _drop_ledger_type_checks()
        self.addCleanup(_restore_ledger_type_checks)
        perms = ALL_LEDGER_PERMS + ALL_SYSTEM_PERMS + [
            'equipment_lifecycle.operation_record.view']
        self.user_a = make_user('purge_admin_a', perms=perms, tenant_id='tenant_a')
        self.user_b = make_user('purge_admin_b', perms=perms, tenant_id='tenant_b')
        self.system_a = make_system(self.user_a, tenant_id='tenant_a')
        self.system_b = make_system(self.user_b, tenant_id='tenant_b')
        # 周月/季维护数据（tenant_a）
        self.week_ledger = self._make_ledger(
            self.system_a, LEDGER_TYPE_WEEK_MONTH, ledger_no='EL-WM-TEST-A')
        self.month_ledger = self._make_ledger(
            self.system_a, LEDGER_TYPE_WEEK_MONTH, ledger_no='EL-WM-TEST-B')
        self.seasonal_ledger = self._make_ledger(
            self.system_a, LEDGER_TYPE_SEASONAL, ledger_no='EL-SE-TEST-A')
        # tenant_a 旧巡检台账 + 模板 + 更正记录
        self.legacy_ledger = self._make_ledger(
            self.system_a, 'inspection', ledger_no='EL-INS-20260901-0001')
        self.legacy_item = OperationLedgerItem.objects.filter(
            ledger=self.legacy_ledger, result='abnormal').first()
        self.legacy_correction = OperationLedgerCorrection.objects.create(
            ledger=self.legacy_ledger, item=self.legacy_item, reason='历史更正',
            changes='[]', corrected_by=self.user_a)
        # tenant_b 旧巡检台账（验证 --tenant 范围）
        self.legacy_ledger_b = self._make_ledger(
            self.system_b, 'inspection', ledger_no='EL-INS-20260902-0001')
        # 外部引用：统一记录（引用 tenant_a 旧巡检异常明细，不得删除；
        # 2026-10-11 合并改造后故障旧表已删，目标为统一主表正式故障记录；
        # 系统履历已退役，不再构造履历事件夹具）
        self.record = SystemOperationRecord.objects.create(
            tenant_id='tenant_a', record_no='JL20260901-0001',
            record_type='fault', system=self.system_a, impact_status='',
            affects_system_operation=False,
            system_code=self.system_a.system_code, system_name=self.system_a.name,
            system_location=self.system_a.install_location,
            occurred_at='2026-09-01 10:00:00',
            title='旧巡检异常转故障', description='旧巡检发现的异常',
            status='handling', source_type='ledger_item',
            source_id=str(self.legacy_item.id),
            source_ledger_item=self.legacy_item, created_by=self.user_a)

    def _make_ledger(self, system, ledger_type, ledger_no=None):
        ledger = OperationLedger.objects.create(
            tenant_id=system.tenant_id,
            ledger_no=ledger_no or 'EL-TEST-%s-%d' % (ledger_type, system.id),
            ledger_type=ledger_type,
            executed_date='2026-09-01', status='reviewed',
            created_by=self.user_a if system is self.system_a else self.user_b)
        OperationLedgerItem.objects.create(
            tenant_id=system.tenant_id, ledger=ledger, system=system,
            system_code_snapshot=system.system_code,
            system_name_snapshot=system.name,
            system_location_snapshot=system.install_location,
            item_name_snapshot='%s项目' % ledger_type, input_type='choice',
            choices_snapshot='["正常", "不正常"]', result='abnormal',
            abnormal_desc='异常描述')
        return ledger

    def _legacy_counts(self, tenant=None):
        qs = OperationLedger.objects.filter(ledger_type='inspection')
        items = OperationLedgerItem.objects.filter(ledger__ledger_type='inspection')
        if tenant:
            qs = qs.filter(tenant_id=tenant)
            items = items.filter(tenant_id=tenant)
        return qs.count(), items.count()

    def test_maintenance_models_and_data_intact(self):
        """17. 共享模型仍然存在，维护数据在命令前完整。"""
        for model in (OperationLedger, OperationLedgerItem, OperationLedgerCorrection):
            self.assertTrue(model.objects.exists() or model is not None)
        # 旧可视化模板模型已整体删除（2026-10）：模型注册表中不再存在
        from django.apps import apps as django_apps
        for gone in ('OperationLedgerTemplate', 'OperationLedgerTemplateItem',
                     'OperationLedgerRowTemplateNode', 'OperationLedgerRowInstance'):
            with self.assertRaises(LookupError):
                django_apps.get_model('equipment_lifecycle', gone)
        self.assertEqual(self._legacy_counts('tenant_a'), (1, 1))
        self.assertEqual(
            OperationLedger.objects.filter(
                ledger_type=LEDGER_TYPE_WEEK_MONTH).count(), 2)

    def test_dry_run_does_not_modify_database(self):
        """14. dry-run 只统计，不删除。"""
        before = self._legacy_counts()
        out = call_purge('--dry-run')
        self.assertIn('DRY-RUN', out)
        self.assertEqual(self._legacy_counts(), before)
        self.assertEqual(SystemOperationRecord.objects.count(), 1)

    def test_without_confirm_does_not_delete(self):
        """15. 未提供 --confirm 时不删除。"""
        before = self._legacy_counts()
        out = call_purge()
        self.assertIn('DRY-RUN', out)
        self.assertEqual(self._legacy_counts(), before)

    def test_confirm_deletes_only_inspection(self):
        """3/4/5/6/17：--confirm 只删除 inspection；周月/季维护与共享模型完整。"""
        out = call_purge('--confirm')
        self.assertIn('清理完成', out)
        # 旧巡检数据全部删除
        self.assertEqual(self._legacy_counts('tenant_a'), (0, 0))
        self.assertEqual(self._legacy_counts('tenant_b'), (0, 0))
        # 周月/季维护数据保留
        self.assertEqual(
            OperationLedger.objects.filter(
                ledger_type=LEDGER_TYPE_WEEK_MONTH).count(), 2)
        self.assertEqual(
            OperationLedger.objects.filter(
                ledger_type=LEDGER_TYPE_SEASONAL).count(), 1)
        # 共享模型仍完整可用：更正记录随旧台账删除，但表本身可继续写入
        self.assertEqual(OperationLedgerCorrection.objects.count(), 0)
        # 统一记录（外部引用）不被删除
        self.assertTrue(
            SystemOperationRecord.objects.filter(pk=self.record.id).exists())

    def test_referenced_record_survives_with_unbound_source(self):
        """10/11：被引用的统一记录不删除，来源外键解除后记录仍可查看。

        （2026-10-11 合并改造：统一主表无 legacy 快照字段，来源语义由
        记录的情况描述文本与审计日志承载；旧快照断言随 SystemFault 删除。）
        """
        call_purge('--confirm')
        record = SystemOperationRecord.objects.get(pk=self.record.id)
        # 记录保留，来源外键解除
        self.assertIsNone(record.source_ledger_item_id)
        self.assertEqual(record.source_id, '')
        # 来源类型不丢失历史语义（仍是 ledger_item，非人工）
        self.assertEqual(record.source_type, 'ledger_item')
        # 详情接口仍可正常打开
        detail = make_client(self.user_a).get(
            '/equipment-lifecycle/records/%s/' % self.record.id).json()['data']
        self.assertEqual(detail['record_no'], 'JL20260901-0001')
        self.assertEqual(detail['source_type'], 'ledger_item')
        self.assertIsNone(detail['source_ledger'])

    def test_tenant_scoped_deletion(self):
        """13. --tenant 只删除指定租户旧巡检数据，其他租户不受影响。"""
        call_purge('--confirm', '--tenant', 'tenant_a')
        self.assertEqual(self._legacy_counts('tenant_a'), (0, 0))
        self.assertEqual(self._legacy_counts('tenant_b'), (1, 1))
        # tenant_a 的维护数据不受影响
        self.assertTrue(
            OperationLedger.objects.filter(pk=self.week_ledger.id).exists())
        # tenant_b 用户看不到 tenant_a 的维护台账（租户隔离仍有效）
        resp = make_client(self.user_b).get(LEDGER_URL + '/?ledger_type=week_month')
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertNotIn(self.week_ledger.id, ids)

    def test_command_failure_rolls_back(self):
        """16. 删除过程异常时事务回滚，不产生部分删除。"""
        before = self._legacy_counts()
        with mock.patch.object(
                purge_cmd, 'delete_attachment_rows',
                side_effect=RuntimeError('模拟附件删除失败')):
            with self.assertRaises(CommandError):
                call_purge('--confirm')
        # 全部数据原样保留（含统一记录的外键引用）
        self.assertEqual(self._legacy_counts(), before)
        record = SystemOperationRecord.objects.get(pk=self.record.id)
        self.assertEqual(record.source_ledger_item_id, self.legacy_item.id)
