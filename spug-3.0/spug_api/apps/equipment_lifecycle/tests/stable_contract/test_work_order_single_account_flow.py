# -*- coding: utf-8 -*-
"""工单单账号协同流程稳定契约（2026-09 改造）。

覆盖契约（任务清单 26 项中未被 test_work_orders.py 覆盖的部分）：
- 完成工单审计事件内容（原状态/新状态/处理结果填写/实际完成时间）与
  工单完成履历（目标系统、来源关系保留）；
- 故障转工单 / 周·月·季维护台账异常转工单 / 值班巡检异常转工单
  （服务路径）创建即执行中并自动记录 actual_start，来源关系不变；
- 迁移 0033 数据迁移：历史 pending_dispatch / pending_accept 受控归并为
  executing 并按 accepted_at → dispatched_at → created_at 补 actual_start；
  pending_review 不被自动完成；
- 管理命令 complete_pending_review_work_orders：dry-run 不改数据，
  --confirm 人工确认后写入完成账号/时间与完成履历，缺处理结果的跳过；
- 跨租户完成工单被拒绝；健康重算锁超时返回业务错误。

全部通过真实代码路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
import importlib
import json
import time
from unittest import mock

from django.core.management import call_command
from django.db import transaction
from django.test import TestCase
from django.utils import timezone as dj_timezone

from apps.equipment_lifecycle import fault_services, work_order_services
from apps.equipment_lifecycle.models import (
    InspectionRecord,
    OperationLedger,
    SystemEvent,
    SystemWorkOrder,
)
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS, make_client, make_system,
)
from apps.equipment_lifecycle.tests.stable_contract.test_work_orders import (
    ALL_WO_PERMS, WORK_ORDER_URL, WorkOrderTestBase, work_order_payload,
)

_migration_module = importlib.import_module(
    'apps.equipment_lifecycle.migrations.0033_work_order_single_account_flow')
migrate_legacy_pending_statuses = _migration_module.migrate_legacy_pending_statuses


def timezone_now():
    return dj_timezone.now()


def _uniq_title(prefix):
    return f'{prefix}-{time.time_ns()}'

WORK_ORDER_STATUS_TEXT = SystemWorkOrder.STATUS_TEXT_MAP


class SingleAccountFlowTestBase(WorkOrderTestBase):
    """复用工单夹具（两租户 + 全权限用户 + 多系统）。"""


class CompleteAuditAndHistoryTest(SingleAccountFlowTestBase):
    """完成工单：审计事件 + 系统履历 + 完成账号/时间。"""

    def test_complete_writes_audit_event_with_required_fields(self):
        """完成工单审计：原状态/新状态/处理结果填写/实际完成时间/操作账号。"""
        order = self.run_to_executing(work_type='special_maintenance', title='审计字段工单')
        self.add_record(order.id)
        resp = make_client(self.admin).post(
            f'{WORK_ORDER_URL}/{order.id}/complete/',
            {'process_result': '处理完毕', 'work_hours': 2},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        audit = AuditLog.objects.filter(
            target_type='el_work_order', target_id=str(order.id),
            action='update').order_by('-id').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.username, self.admin.username)
        detail = json.loads(audit.detail or '{}')
        self.assertEqual(detail.get('before', {}).get('status'), 'executing')
        self.assertEqual(detail.get('after', {}).get('status'), 'completed')
        self.assertTrue(detail.get('after', {}).get('process_result_filled'))
        self.assertTrue(detail.get('after', {}).get('actual_end'))

    def test_complete_writes_system_event_with_source_relation(self):
        """完成履历落到作业系统，来源故障关系保留（工单完成不改动来源）。"""
        fault = self.create_active_fault(self.system_a, impact='degraded')
        resp = make_client(self.admin).post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'tok-ev-audit'}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        oid = resp.json()['data']['id']
        self.add_record(oid)
        self.complete_order(oid)
        events = SystemEvent.objects.filter(
            tenant_id='tenant_a', event_type=SystemEvent.EVENT_WORK_ORDER,
            action='complete', source_id=str(oid))
        self.assertEqual(events.count(), 1)
        event = events.first()
        self.assertEqual(event.system_id, self.system_a.id)
        self.assertEqual(event.get_detail().get('work_no'),
                         SystemWorkOrder.objects.get(pk=oid).work_no)
        # 来源故障未被完成动作改动
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'pending')
        self.assertEqual(
            SystemWorkOrder.objects.get(pk=oid).source_fault_id, fault.id)


class SourceConversionDirectExecutingTest(SingleAccountFlowTestBase):
    """三类来源转单创建即执行中，来源关系保持（清单 21/22/23/24）。"""

    def test_ledger_item_convert_to_work_order_direct_executing(self):
        """周/月/季维护台账异常转工单：创建即执行中 + actual_start + 来源关系。"""
        from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
            ALL_LEDGER_PERMS, entry_payload, item_payload,
            ledger_payload, make_ledger_user, post_json,
        )
        ledger_user = make_ledger_user(
            'sa_ledger_user', perms=ALL_LEDGER_PERMS + ALL_SYSTEM_PERMS + ALL_WO_PERMS +
            ['equipment_lifecycle.ledger.handle_exception'], tenant_id='tenant_a')
        client = make_client(ledger_user)
        payload = ledger_payload([entry_payload(self.system_a.id, [
            item_payload(item_name='电压检查', input_type='number', value_text='',
                         value_number=50, result='abnormal', abnormal_desc='电压偏低'),
        ])])
        body = post_json(client, '/equipment-lifecycle/ledgers/', payload).json()
        self.assertFalse(body.get('error'), body)
        ledger_id = body['data']['id']
        resp = client.post(f'/equipment-lifecycle/ledgers/{ledger_id}/submit/', {},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        ledger = OperationLedger.objects.get(pk=ledger_id)
        item_id = ledger.items.filter(result='abnormal').order_by('id').first().id
        resp = client.post(
            f'/equipment-lifecycle/ledgers/{ledger_id}/items/{item_id}/convert-to-work-order/',
            {'client_token': 'tok-sa-ledger'}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        order = SystemWorkOrder.objects.get(pk=resp.json()['data']['id'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        self.assertIsNotNone(order.actual_start)
        self.assertEqual(order.source_type, 'ledger_item')
        self.assertEqual(order.source_ledger_item_id, item_id)
        self.assertIsNone(order.dispatched_by_id)
        self.assertIsNone(order.reviewer_id)

    def test_inspection_record_convert_via_service_direct_executing(self):
        """值班巡检异常转工单（服务路径）：创建即执行中 + 来源关系。"""
        # 构造一条已提交巡检单的异常明细（复用巡检 base 的真实创建路径）
        from apps.equipment_lifecycle.tests.stable_contract.inspection_base import (
            create_sheet_ok, get_template_items, get_sheet_detail,
            make_inspection_template, make_inspection_user, put_records_ok,
            sheet_payload, submit_sheet_ok,
        )
        ins_admin = make_inspection_user('sa_ins_admin', tenant_id='tenant_a')
        ins_client = make_client(ins_admin)
        template = make_inspection_template(tenant_id='tenant_a', created_by=ins_admin)
        items = get_template_items(template)
        body = create_sheet_ok(ins_client, sheet_payload(
            template.id, duty_date='2026-09-25',
            persons=[{'person_name': '值班员乙'}]))
        put_records_ok(ins_client, body['id'], 1, records=[
            {'template_item_id': items['面板指示灯'].id, 'round_no': 'r1',
             'value_text': '不正常', 'abnormal_desc': '告警灯红色',
             'onsite_action': '已切换备用'},
        ])
        submit_sheet_ok(ins_client, body['id'])
        detail = get_sheet_detail(ins_client, body['id'])
        record_id = next(
            r['id'] for r in detail['records'] if r['result'] == 'abnormal')
        record = InspectionRecord.objects.get(pk=record_id)
        # 服务创建路径（新巡检转单接口下线后，来源数据由该唯一入口写入）
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                order = work_order_services.create_work_order_record(
                    tenant_id='tenant_a', created_by=ins_admin,
                    title='巡检异常维修', work_type=SystemWorkOrder.TYPE_REPAIR,
                    system=self.system_a,
                    source_type='inspection_record',
                    source_inspection_record=record,
                    source_no=detail['sheet_no'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        self.assertIsNotNone(order.actual_start)
        self.assertEqual(order.source_inspection_record_id, record_id)
        self.assertIsNone(order.owner_id)


class LegacyDataMigrationTest(SingleAccountFlowTestBase):
    """迁移 0033 数据迁移与管理命令（清单 19/20）。"""

    @staticmethod
    class _AppsShim:
        """把迁移函数指向当前模型（测试库 schema 与迁移后一致）。"""

        def get_model(self, app_label, model_name):
            return SystemWorkOrder

    def make_legacy_order(self, status, **overrides):
        """绕过状态机制造历史状态工单（模拟迁移前的真实历史数据）。"""
        data = self.create_order_ok(work_order_payload(
            self.system_a, title=_uniq_title(f'历史工单-{status}'), **overrides))
        oid = data['id']
        now = timezone_now()
        update_fields = {'status': status}
        if status == 'pending_accept':
            update_fields.update({
                'owner_id': self.admin.id, 'dispatched_by_id': self.admin.id,
                'dispatched_at': now, 'accepted_by_id': self.admin.id,
                'accepted_at': now})
        elif status == 'pending_dispatch':
            update_fields.update({'actual_start': None})
        SystemWorkOrder.objects.filter(pk=oid).update(**update_fields)
        return SystemWorkOrder.objects.get(pk=oid)

    def test_migration_merges_legacy_pending_into_executing(self):
        """pending_dispatch/accept → executing，actual_start 按
        accepted_at → dispatched_at → created_at 优先级补写。"""
        # accepted_at 在位 → 优先取接单时间
        accepted = self.make_legacy_order('pending_accept')
        # 仅派发 → 取派发时间
        dispatched = self.make_legacy_order('pending_accept')
        SystemWorkOrder.objects.filter(pk=dispatched.id).update(
            accepted_by_id=None, accepted_at=None)
        # 两者皆无 → 取创建时间
        created = self.make_legacy_order('pending_dispatch')
        migrate_legacy_pending_statuses(self._AppsShim(), None)
        accepted.refresh_from_db()
        dispatched.refresh_from_db()
        created.refresh_from_db()
        self.assertEqual(accepted.status, 'executing')
        self.assertEqual(accepted.actual_start, accepted.accepted_at)
        self.assertEqual(dispatched.status, 'executing')
        self.assertEqual(dispatched.actual_start, dispatched.dispatched_at)
        self.assertEqual(created.status, 'executing')
        self.assertEqual(created.actual_start, created.created_at)

    def test_migration_does_not_touch_pending_review(self):
        """pending_review 不被迁移自动完成（不得猜测自动完成）。"""
        review = self.make_legacy_order('pending_review')
        review.process_result = ''
        review.save(update_fields=['process_result'])
        migrate_legacy_pending_statuses(self._AppsShim(), None)
        review.refresh_from_db()
        self.assertEqual(review.status, 'pending_review')
        self.assertIsNone(review.completed_by_id)

    def test_management_command_dry_run_changes_nothing(self):
        """管理命令缺省 dry-run：只列出待复核工单，不改任何数据。"""
        review = self.make_legacy_order('pending_review')
        review.process_result = '待复核结果'
        review.save(update_fields=['process_result'])
        out = _capture_command('complete_pending_review_work_orders')
        review.refresh_from_db()
        self.assertEqual(review.status, 'pending_review')
        self.assertIn(review.work_no, out)

    def test_management_command_confirm_completes_with_operator(self):
        """--confirm --username：人工确认迁移为已完成并记录完成账号/时间。"""
        review = self.make_legacy_order('pending_review')
        review.process_result = '待复核结果'
        review.reviewed_at = timezone_now()
        review.save(update_fields=['process_result', 'reviewed_at'])
        call_command('complete_pending_review_work_orders',
                     confirm=True, username=self.admin.username)
        review.refresh_from_db()
        self.assertEqual(review.status, 'completed')
        self.assertEqual(review.completed_by_id, self.admin.id)
        self.assertIsNotNone(review.completed_at)
        self.assertEqual(review.actual_end, review.reviewed_at)
        self.assertIsNone(review.reviewer_id)
        # 完成履历已写入
        self.assertTrue(SystemEvent.objects.filter(
            event_type=SystemEvent.EVENT_WORK_ORDER, action='complete',
            source_id=str(review.id)).exists())

    def test_management_command_skips_missing_process_result(self):
        """缺处理结果的待复核工单被跳过（fail-safe，不猜测完成）。"""
        review = self.make_legacy_order('pending_review')
        SystemWorkOrder.objects.filter(pk=review.id).update(process_result='')
        call_command('complete_pending_review_work_orders',
                     confirm=True, username=self.admin.username)
        review.refresh_from_db()
        self.assertEqual(review.status, 'pending_review')


class CompleteBoundaryTest(SingleAccountFlowTestBase):
    """完成工单边界：租户隔离、锁超时。"""

    def test_cross_tenant_complete_rejected(self):
        """跨租户工单完成被拒绝（工单不存在）。"""
        data_b = self.create_order_ok(work_order_payload(self.system_b, title='B租户工单'),
                                      user=self.other_admin)
        self.add_record(data_b['id'], user=self.other_admin)
        resp = make_client(self.admin).post(
            f'{WORK_ORDER_URL}/{data_b["id"]}/complete/',
            {'process_result': '越权结果'}, content_type='application/json')
        self.assertIn('不存在', resp.json().get('error', ''), resp.content)
        order = SystemWorkOrder.objects.get(pk=data_b['id'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        self.assertIsNone(order.completed_by_id)

    def test_health_lock_timeout_returns_error(self):
        """健康重算锁超时转为业务错误，状态不变化。"""
        order = self.run_to_executing(work_type='special_maintenance', title='锁超时工单')
        self.add_record(order.id)
        with mock.patch.object(
                fault_services, 'health_recalc_lock',
                side_effect=fault_services.HealthRecalcLockTimeout('系统繁忙，请稍后重试')):
            resp = make_client(self.admin).post(
                f'{WORK_ORDER_URL}/{order.id}/complete/',
                {'process_result': '结果'}, content_type='application/json')
        self.assertIn('繁忙', resp.json().get('error', ''), resp.content)
        order.refresh_from_db()
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)


def _capture_command(name, *args, **kwargs):
    from io import StringIO
    out = StringIO()
    call_command(name, *args, stdout=out, **kwargs)
    return out.getvalue()
