# -*- coding: utf-8 -*-
"""巡检单"退回整改"稳定契约（超级管理员专用）。

覆盖行为契约：
- 仅超级管理员（User.is_supper）可退回：普通管理员（即使持有全部巡检权限）
  与普通用户直接调用接口均被拒绝（后端独立校验，不依赖前端按钮）；
- 仅允许 submitted → returned：草稿/已退回/已作废一律拒绝；退回原因必填；
- 退回留痕（退回人/退回时间/退回原因）真实落库；原有巡检记录、值班人员、
  uniq_key 唯一占用与历史故障/工单来源关系（source_inspection_record）
  原样保留，不被删除或破坏；
- 已退回单可编辑：已记录轮次允许重改（recorded_rounds 不拦截整改）、
  值班人员可补改，version 乐观锁仍然生效；
- 重新提交：returned → submitted，仍执行值班人员/巡检记录等原有提交校验，
  更新提交人与提交时间；退回历史留痕与审计日志保留；
- 退回动作写入业务审计日志（前后状态与原因）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
import json

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.equipment_lifecycle import fault_services, work_order_services
from apps.equipment_lifecycle.models import (
    InspectionDutySheet,
    InspectionRecord,
    SystemFault,
    SystemWorkOrder,
    INSPECTION_SHEET_SUBMITTED,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system, make_user
from apps.equipment_lifecycle.tests.stable_contract.inspection_base import (
    ALL_INSPECTION_PERMS,
    INS_URL,
    create_sheet_ok,
    get_sheet_detail,
    get_template_items,
    make_inspection_template,
    make_inspection_user,
    put_records_ok,
    sheet_payload,
    submit_sheet_ok,
)

RETURN_URL = INS_URL + '/{pk}/return/'


class InspectionReturnTestBase(TestCase):
    """公共夹具：tenant_a 已提交巡检单（含一条 r1"不正常"明细）+ 超级管理员。"""

    def setUp(self):
        self.admin = make_inspection_user('ins_ret_admin', tenant_id='tenant_a')
        self.super_admin = make_user('ins_ret_sa', is_supper=True, tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.sa_client = make_client(self.super_admin)
        self.template = make_inspection_template(
            tenant_id='tenant_a', created_by=self.admin)
        self.items = get_template_items(self.template)
        # 建单 → 记录 r1（含异常）+ r2 → 提交（单轮契约逐轮记录）
        body = create_sheet_ok(self.client, sheet_payload(
            self.template.id, duty_date='2026-09-23',
            persons=[{'person_name': '值班员甲'}, {'person_name': '值班员乙'}]))
        put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': self.items['面板指示灯'].id,
             'round_no': 'r1', 'value_text': '不正常',
             'abnormal_desc': '告警灯红色', 'onsite_action': '已切换备用'},
        ])
        put_records_ok(self.client, body['id'], 2, records=[
            {'template_item_id': self.items['输出功率读数'].id,
             'round_no': 'r2', 'value_text': '480'},
        ])
        submit_sheet_ok(self.client, body['id'])
        self.sheet_id = body['id']
        self.sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.abnormal_record_id = InspectionRecord.objects.filter(
            sheet_id=self.sheet_id, result='abnormal').get().id

    def return_sheet(self, reason='巡检数据有误，请整改后重新提交', client=None):
        target = client or self.sa_client
        return target.post(
            RETURN_URL.format(pk=self.sheet_id), {'return_reason': reason},
            content_type='application/json')


class SuperAdminReturnPermissionTest(InspectionReturnTestBase):
    """退回权限：仅超级管理员，后端独立校验。"""

    def test_super_admin_can_return_submitted_sheet(self):
        """超级管理员退回已提交单：状态/退回人/退回时间/退回原因正确落库。"""
        before = timezone.now()
        resp = self.return_sheet()
        self.assertFalse(resp.json().get('error'), resp.json())
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(sheet.status, 'returned')
        self.assertEqual(sheet.returned_by_id, self.super_admin.id)
        self.assertIsNotNone(sheet.returned_at)
        self.assertGreaterEqual(sheet.returned_at, before)
        self.assertEqual(sheet.return_reason, '巡检数据有误，请整改后重新提交')
        self.assertEqual(sheet.updated_by_id, self.super_admin.id)

    def test_return_detail_response_carries_return_info(self):
        """退回接口返回更新后的详情：状态文案与退回留痕字段一并返回。"""
        resp = self.return_sheet()
        data = resp.json().get('data') or resp.json()
        self.assertEqual(data['status'], 'returned')
        self.assertEqual(data['status_text'], '已退回')
        self.assertEqual(data['return_reason'], '巡检数据有误，请整改后重新提交')
        self.assertEqual(data['returned_by_name'], self.super_admin.username)
        self.assertIsNotNone(data['returned_at'])

    def test_normal_admin_with_all_inspection_perms_rejected(self):
        """普通管理员即使持有全部巡检权限码也必须被拒绝（后端独立校验）。"""
        resp = self.return_sheet(client=self.client)
        self.assertIn('仅超级管理员', resp.json().get('error', ''))
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(sheet.status, INSPECTION_SHEET_SUBMITTED)
        self.assertIsNone(sheet.returned_by_id)

    def test_plain_user_rejected(self):
        """无权限普通用户直接调用被 @auth 拒绝，单据状态不变。"""
        plain = make_user('ins_ret_plain', tenant_id='tenant_a')
        resp = self.return_sheet(client=make_client(plain))
        self.assertTrue(resp.json().get('error'))
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(sheet.status, INSPECTION_SHEET_SUBMITTED)

    def test_tenant_isolation_still_enforced_for_non_super(self):
        """跨租户普通管理员仍被拒绝（租户隔离与身份校验双保险）。"""
        other_admin = make_inspection_user('ins_ret_admin_b', tenant_id='tenant_b')
        resp = self.return_sheet(client=make_client(other_admin))
        self.assertTrue(resp.json().get('error'))
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(sheet.status, INSPECTION_SHEET_SUBMITTED)


class ReturnStateTransitionTest(InspectionReturnTestBase):
    """退回状态机：仅 submitted → returned，原因必填。"""

    def test_draft_cannot_be_returned(self):
        create_resp = self.client.post(
            f'{INS_URL}/', sheet_payload(
                self.template.id, duty_date='2026-09-24',
                client_token='tok-return-draft'),
            content_type='application/json')
        draft_id = create_resp.json()['data']['id']
        resp = self.sa_client.post(
            RETURN_URL.format(pk=draft_id), {'return_reason': '原因'},
            content_type='application/json')
        self.assertIn('只有已提交状态', resp.json().get('error', ''))
        self.assertEqual(
            InspectionDutySheet.objects.get(pk=draft_id).status, 'draft')

    def test_returned_sheet_cannot_be_returned_twice(self):
        self.return_sheet()
        resp = self.return_sheet(reason='第二次退回')
        self.assertIn('只有已提交状态', resp.json().get('error', ''))
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(sheet.status, 'returned')
        self.assertEqual(sheet.return_reason, '巡检数据有误，请整改后重新提交')

    def test_voided_sheet_cannot_be_returned(self):
        self.client.post(f'{INS_URL}/{self.sheet_id}/void/',
                         {'void_reason': '整体作废重开'},
                         content_type='application/json')
        resp = self.return_sheet()
        self.assertIn('只有已提交状态', resp.json().get('error', ''))
        self.assertEqual(
            InspectionDutySheet.objects.get(pk=self.sheet_id).status, 'void')

    def test_empty_reason_rejected(self):
        for reason in ('', '   ', None):
            body = {'return_reason': reason} if reason is not None else {}
            resp = self.sa_client.post(
                RETURN_URL.format(pk=self.sheet_id), body,
                content_type='application/json')
            self.assertIn('退回原因不能为空', resp.json().get('error', ''), body)
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(sheet.status, INSPECTION_SHEET_SUBMITTED)

    def test_overlong_reason_rejected(self):
        resp = self.sa_client.post(
            RETURN_URL.format(pk=self.sheet_id),
            {'return_reason': '长' * 201}, content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(sheet.status, INSPECTION_SHEET_SUBMITTED)

    def test_nonexistent_sheet_rejected(self):
        resp = self.sa_client.post(
            RETURN_URL.format(pk=99999), {'return_reason': '原因'},
            content_type='application/json')
        self.assertIn('巡检单不存在', resp.json().get('error', ''))


class ReturnDataPreservationTest(InspectionReturnTestBase):
    """退回不破坏历史数据：明细/人员/唯一占用/来源关系全部保留。"""

    def test_return_preserves_records_and_persons(self):
        records_before = list(InspectionRecord.objects.filter(
            sheet_id=self.sheet_id).order_by('id').values(
            'id', 'round_no', 'value_text', 'result', 'onsite_action'))
        persons_before = list(self.sheet.persons.order_by('id').values_list(
            'person_name', flat=True))
        uniq_key_before = self.sheet.uniq_key
        self.return_sheet()
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        records_after = list(InspectionRecord.objects.filter(
            sheet_id=self.sheet_id).order_by('id').values(
            'id', 'round_no', 'value_text', 'result', 'onsite_action'))
        self.assertEqual(records_after, records_before)
        self.assertEqual(
            list(sheet.persons.order_by('id').values_list(
                'person_name', flat=True)), persons_before)
        # 退回不释放值班日+模板唯一占用（单据仍有效，仅回到可编辑状态）
        self.assertEqual(sheet.uniq_key, uniq_key_before)

    def _make_historical_relations(self):
        """走正式服务构造历史"巡检异常转故障/转工单"来源关系。"""
        record = InspectionRecord.objects.get(pk=self.abnormal_record_id)
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = fault_services.create_fault_record(
                    tenant_id='tenant_a', created_by=self.admin,
                    system=self.system, impact_status='',
                    occurred_at=timezone.now(),
                    discovery=SystemFault.DISCOVERY_PATROL,
                    level=SystemFault.LEVEL_MINOR,
                    phenomenon='巡检异常转入的故障',
                    source_type='inspection_record',
                    source_inspection_record=record)
                order = work_order_services.create_work_order_record(
                    tenant_id='tenant_a', created_by=self.admin,
                    title='巡检异常维修', work_type=SystemWorkOrder.TYPE_REPAIR,
                    system=self.system,
                    source_type='inspection_record',
                    source_inspection_record=record,
                    source_no=self.sheet.sheet_no)
        return fault, order

    def test_return_preserves_fault_and_work_order_relations(self):
        """退回后来源关系外键不变，详情处置状态仍为已转故障/已转工单。"""
        self.system = make_system(
            self.admin, tenant_id='tenant_a',
            system_code='SYS-RET', name='退回目标系统', install_location='机房R')
        fault, order = self._make_historical_relations()
        self.return_sheet()
        self.assertEqual(
            SystemFault.objects.get(pk=fault.id).source_inspection_record_id,
            self.abnormal_record_id)
        self.assertEqual(
            SystemWorkOrder.objects.get(pk=order.id).source_inspection_record_id,
            self.abnormal_record_id)
        detail = get_sheet_detail(self.sa_client, self.sheet_id)
        disposition = next(
            r['disposition'] for r in detail['records']
            if r['id'] == self.abnormal_record_id)
        self.assertEqual(disposition['status'], 'converted_fault')
        self.assertEqual(disposition['fault']['id'], fault.id)
        self.assertEqual(disposition['work_order']['id'], order.id)


class ReturnedSheetEditAndResubmitTest(InspectionReturnTestBase):
    """已退回单整改：可改已记录轮次与人员，可重新提交。"""

    def return_first(self):
        resp = self.return_sheet()
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_returned_sheet_allows_modifying_recorded_round(self):
        """recorded_rounds 不阻止整改：已记录的 r1 可重改，轮次标记保留。"""
        self.return_first()
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertIn('r1', sheet.get_recorded_rounds())
        detail = put_records_ok(self.sa_client, self.sheet_id, sheet.version, records=[
            {'template_item_id': self.items['面板指示灯'].id,
             'round_no': 'r1', 'value_text': '正常',
             'abnormal_desc': '', 'onsite_action': ''},
        ])
        record = next(r for r in detail['records'] if r['round_no'] == 'r1')
        self.assertEqual(record['value_text'], '正常')
        self.assertEqual(record['result'], 'normal')
        db_sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(db_sheet.status, 'returned')
        self.assertIn('r1', db_sheet.get_recorded_rounds())

    def test_returned_sheet_allows_new_round_and_persons(self):
        """已退回单可补录未记录轮次与补改值班人员。"""
        self.return_first()
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        put_records_ok(self.sa_client, self.sheet_id, sheet.version, persons=[
            {'person_name': '值班员甲'}, {'person_name': '整改复核员'},
        ], records=[
            {'template_item_id': self.items['驻波比检查'].id,
             'round_no': 'r3', 'value_text': '正常'},
        ])
        db_sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertTrue(db_sheet.persons.filter(person_name='整改复核员').exists())
        self.assertIn('r3', db_sheet.get_recorded_rounds())

    def test_returned_sheet_version_lock_still_enforced(self):
        """退回状态下 version 乐观锁仍然生效。"""
        self.return_first()
        resp = self.sa_client.put(
            f'{INS_URL}/{self.sheet_id}/',
            {'version': 999, 'records': [
                {'template_item_id': self.items['面板指示灯'].id,
                 'round_no': 'r1', 'value_text': '正常'}]},
            content_type='application/json')
        self.assertIn('请刷新后重试', resp.json().get('error', ''))

    def test_resubmit_returns_to_submitted_and_updates_submitter(self):
        """重新提交：returned → submitted，更新提交人/提交时间，退回留痕保留。"""
        self.return_first()
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        returned_at = sheet.returned_at
        resp = self.sa_client.post(
            f'{INS_URL}/{self.sheet_id}/submit/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        db_sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(db_sheet.status, 'submitted')
        self.assertEqual(db_sheet.submitted_by_id, self.super_admin.id)
        self.assertIsNotNone(db_sheet.submitted_at)
        # 退回历史留痕不被清除（审计链与字段留痕均保留）
        self.assertEqual(db_sheet.returned_by_id, self.super_admin.id)
        self.assertEqual(db_sheet.return_reason, '巡检数据有误，请整改后重新提交')
        self.assertEqual(db_sheet.returned_at, returned_at)
        # 原有巡检明细保留（本用例未做整改，明细应原样保留）
        records = InspectionRecord.objects.filter(sheet_id=self.sheet_id)
        self.assertEqual(records.count(), 2)
        self.assertTrue(records.filter(
            round_no='r1', value_text='不正常', result='abnormal').exists())

    def test_resubmit_still_validates_persons_and_records(self):
        """重新提交仍执行原有提交校验：无人员/无记录不能提交。"""
        self.return_first()
        # 清空值班人员后重新提交必须被拒绝
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        put_records_ok(self.sa_client, self.sheet_id, sheet.version, persons=[])
        resp = self.sa_client.post(
            f'{INS_URL}/{self.sheet_id}/submit/', {},
            content_type='application/json')
        self.assertIn('请先登记值班人员再提交', resp.json().get('error', ''))
        self.assertEqual(
            InspectionDutySheet.objects.get(pk=self.sheet_id).status, 'returned')

    def test_resubmitted_sheet_no_longer_editable(self):
        """重新提交后恢复只读：编辑被拒绝；再次退回是合法流转（submitted→returned）。"""
        self.return_first()
        self.sa_client.post(f'{INS_URL}/{self.sheet_id}/submit/', {},
                            content_type='application/json')
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        resp = self.sa_client.put(
            f'{INS_URL}/{self.sheet_id}/',
            {'version': sheet.version, 'records': [
                {'template_item_id': self.items['面板指示灯'].id,
                 'round_no': 'r1', 'value_text': '不正常'}]},
            content_type='application/json')
        self.assertIn('不能再修改', resp.json().get('error', ''))
        # 重新提交后单据处于已提交态：再次退回属于合法状态流转
        resp = self.sa_client.post(
            RETURN_URL.format(pk=self.sheet_id), {'return_reason': '再次退回'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        sheet = InspectionDutySheet.objects.get(pk=self.sheet_id)
        self.assertEqual(sheet.status, 'returned')
        self.assertEqual(sheet.return_reason, '再次退回')
        # 此时单据可再次编辑整改（退回状态可编辑契约闭环）
        detail = put_records_ok(self.sa_client, self.sheet_id, sheet.version, records=[
            {'template_item_id': self.items['输出功率读数'].id,
             'round_no': 'r2', 'value_text': '512'},
        ])
        record = next(r for r in detail['records'] if r['round_no'] == 'r2')
        self.assertEqual(record['value_text'], '512')


class ReturnAuditTest(InspectionReturnTestBase):
    """退回审计：业务审计日志真实写入（前后状态与原因）。"""

    def test_return_audit_event_recorded(self):
        self.return_sheet()
        from apps.logs.models import AuditLog
        audit = AuditLog.objects.filter(
            target_type='el_inspection_sheet',
            target_id=str(self.sheet_id), action='update',
            detail__contains='return_for_rectification').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.username, self.super_admin.username)
        detail = json.loads(audit.detail)
        before = detail.get('before') or {}
        after = detail.get('after') or {}
        self.assertEqual(before.get('status'), 'submitted')
        self.assertEqual(after.get('status'), 'returned')
        self.assertEqual(after.get('return_reason'),
                         '巡检数据有误，请整改后重新提交')
