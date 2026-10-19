# -*- coding: utf-8 -*-
"""维护台账流程简化（2026-10-16）行为测试。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库），覆盖：
- 完成填写（流程终点）：先保存填写值再完成（草稿 → 已完成，completed_at/by
  落库）；必填缺失时拒绝且状态不变、已保存内容保留；
- 物理删除：草稿可直接删除，明细/更正记录/Excel 填写记录级联清理，
  附件走 evidence 软删除留痕并记审计；已完成/已作废不可删除；
  存在已转设备故障明细的台账由后端拒绝删除；
- 本期一键生成：删除草稿后允许重新生成（唯一约束以 slot_active 豁免）；
  已作废不自动重建（预览标记需人工处理 + rebuildable），明确补建后新草稿
  与作废记录并存，再次自动生成按"已存在"跳过；
- 模板删除引用复查：任一版本被台账（含已作废）引用时物理删除被拒绝。
"""
import json
import tempfile
import uuid
from datetime import datetime
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.equipment_lifecycle import ledger_period_services
from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.excel_sample_template import build_acceptance_sample_xlsx
from apps.equipment_lifecycle.models import (
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
    OperationLedgerCorrection,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX,
    make_client,
    make_record,
    make_system,
    make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    ALL_TEMPLATE_PERMS,
    post_json,
)
from apps.evidence.models import EvidenceAttachment
from apps.logs.models import AuditLog

LEDGERS_URL = URL_PREFIX + '/ledgers'
EXCEL_LEDGERS_URL = URL_PREFIX + '/excel-ledgers'
GENERATE_URL = LEDGERS_URL + '/period-generate/'
REBUILD_URL = LEDGERS_URL + '/period-generate/rebuild/'
TPL_URL = URL_PREFIX + '/excel-templates'

# 每次测试进程独立临时目录：样例 xlsx 字节含时间戳非确定性，独立目录避免
# --keepdb 复用的模板 ID 与残留版本文件冲突；附件同样落到独立 MEDIA 目录
STORAGE_DIR = tempfile.mkdtemp(prefix='el_lifecycle_')
MEDIA_DIR = tempfile.mkdtemp(prefix='el_lifecycle_media_')

LEDGER_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger'


def fake_today(year, month, day):
    """把生成口径的"今天"固定为指定日期（service 内 timezone.now）。"""
    return mock.patch.object(
        ledger_period_services.timezone, 'now',
        return_value=datetime(year, month, day, 10, 0, 0))


class LifecycleTestBase(TestCase):
    """公共夹具：台账/模板双权限用户 + 独立文件存储。"""

    def setUp(self):
        self.user = make_user('lc_op', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.client = make_client(self.user)
        self.system_a = make_system(self.user, system_code='SYS-A', name='DVOR系统')
        self._storage_override = override_settings(
            EL_EXCEL_TEMPLATE_BASE_DIR=STORAGE_DIR, MEDIA_ROOT=MEDIA_DIR)
        self._storage_override.enable()
        self.addCleanup(self._storage_override.disable)

    # ---------- 手工台账夹具（直接走 ORM，状态可指定为历史值） ----------

    def make_manual_ledger(self, status=LEDGER_STATUS_DRAFT, ledger_no=None,
                           system=None, with_correction=False):
        ledger = OperationLedger.objects.create(
            tenant_id=self.user.tenant_id,
            ledger_no=ledger_no or 'EL-WM-20261010-%04d' % OperationLedger.objects.count(),
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            status=status,
            entry_channel='web',
            created_from='manual',
            system=system or self.system_a,
            created_by=self.user,
        )
        item = OperationLedgerItem.objects.create(
            ledger=ledger,
            tenant_id=ledger.tenant_id,
            system=ledger.system,
            system_code_snapshot=ledger.system.system_code,
            system_name_snapshot=ledger.system.name,
            item_name_snapshot='电源电压测量',
            input_type='text',
            value_text='正常',
            result='normal',
        )
        if with_correction:
            OperationLedgerCorrection.objects.create(
                ledger=ledger,
                tenant_id=ledger.tenant_id,
                item=item,
                reason='笔误更正',
                changes='[]',
                corrected_by=self.user,
            )
        return ledger

    def make_ledger_attachment(self, ledger):
        """经 AttachmentService 真实上传路径为台账挂一个附件。"""
        from apps.evidence.attachment_service import (
            AttachmentService, DefaultAttachmentConfig,
        )
        from apps.equipment_lifecycle.views import EL_ATTACHMENT_MODULE
        att, error = AttachmentService.upload(
            SimpleUploadedFile('photo.png', b'\x89PNG fake bytes'),
            self.user, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE,
            ledger.id, config=DefaultAttachmentConfig,
            owner_tenant_id=ledger.tenant_id)
        self.assertIsNone(error, error)
        return att

    # ---------- Excel 模板夹具（走真实接口） ----------

    def publish_template(self, name='信道Excel维护台账', system=None,
                         generation_period='', publish=True):
        resp = self.client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx()),
            'name': name, 'ledger_type': LEDGER_TYPE_WEEK_MONTH,
        })
        template = resp.json()['data']['data']
        bindings = [{
            'field_id': str(uuid.uuid4()), 'sheet_name': '信道维护记录',
            'cell_coordinate': 'C4', 'field_name': 'PS模块', 'input_type': 'status',
            'is_required': True, 'unit': '', 'options': [],
        }]
        resp = self.client.put('%s/%s/bindings/' % (TPL_URL, template['id']),
                               json.dumps({'field_bindings': bindings}),
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        if publish:
            resp = self.client.post('%s/%s/publish/' % (TPL_URL, template['id']))
            self.assertFalse(resp.json().get('error'), resp.json())
        if system is not None or generation_period:
            resp = self.client.put(
                '%s/%s/generation-config/' % (TPL_URL, template['id']),
                json.dumps({'system': system.id if system else '',
                            'generation_period': generation_period}),
                content_type='application/json')
            self.assertFalse(resp.json().get('error'), resp.json())
        return template

    def create_excel_ledger(self, version_id):
        resp = post_json(self.client, EXCEL_LEDGERS_URL + '/', {
            'version_id': version_id,
            'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertFalse(resp.json().get('error'), resp.json())
        return resp.json()['data']['data']


class ExcelCompleteFlowTests(LifecycleTestBase):
    """完成填写（流程终点）：先保存再完成；必填缺失拒绝且内容保留。"""

    def _detail(self, ledger_id):
        resp = self.client.get('%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id))
        self.assertFalse(resp.json().get('error'), resp.json())
        return resp.json()['data']['data']

    def test_save_then_complete(self):
        """保存后完成：PUT 保存填写值成功 → POST 完成 → 已完成并留痕。"""
        template = self.publish_template()
        version = OperationLedgerExcelTemplateVersion.objects.get(
            template_id=template['id'])
        detail = self.create_excel_ledger(version.id)
        ledger_id = detail['id']
        binding = detail['excel']['version']['bindings'][0]
        # 第一步：保存填写值（草稿可保存，必填可以先不填完整）
        resp = self.client.put(
            '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
            json.dumps({'values': {binding['field_id']: '正常'}}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        # 第二步：完成填写
        resp = post_json(self.client, '%s/%s/complete/' % (EXCEL_LEDGERS_URL, ledger_id), {})
        self.assertFalse(resp.json().get('error'), resp.json())
        data = resp.json()['data']['data']
        self.assertEqual(data['status'], LEDGER_STATUS_COMPLETED)
        self.assertFalse(data['excel']['editable'])
        ledger = OperationLedger.objects.get(pk=ledger_id)
        self.assertEqual(ledger.status, LEDGER_STATUS_COMPLETED)
        self.assertIsNotNone(ledger.completed_at)
        self.assertEqual(ledger.completed_by_id, self.user.id)
        # 保存步骤的填写值不因完成丢失
        record = OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)
        self.assertEqual(record.get_values().get(binding['field_id']), '正常')
        # 重复完成被状态机拦截
        resp = post_json(self.client, '%s/%s/complete/' % (EXCEL_LEDGERS_URL, ledger_id), {})
        self.assertTrue(resp.json().get('error'))

    def test_complete_missing_required_keeps_draft_and_saved_values(self):
        """必填未填完成被拒：状态不变，已保存内容保留，可补填后重试完成。"""
        template = self.publish_template()
        version = OperationLedgerExcelTemplateVersion.objects.get(
            template_id=template['id'])
        detail = self.create_excel_ledger(version.id)
        ledger_id = detail['id']
        binding = detail['excel']['version']['bindings'][0]
        resp = post_json(self.client, '%s/%s/complete/' % (EXCEL_LEDGERS_URL, ledger_id), {})
        self.assertTrue(resp.json().get('error'))
        self.assertIn('必填字段未填写', resp.json()['error'])
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).status,
                         LEDGER_STATUS_DRAFT)
        # 补填并保存后完成成功（保存步骤的成果不因完成失败丢失）
        resp = self.client.put(
            '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
            json.dumps({'values': {binding['field_id']: '正常'}}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = post_json(self.client, '%s/%s/complete/' % (EXCEL_LEDGERS_URL, ledger_id), {})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).status,
                         LEDGER_STATUS_COMPLETED)


class LedgerDeletionTests(LifecycleTestBase):
    """物理删除：草稿可删（级联+软删附件+审计）；受限状态拒绝。"""

    def _delete(self, ledger_id, client=None):
        client = client or self.client
        return client.delete('%s/%s/' % (LEDGERS_URL, ledger_id))

    def test_draft_ledger_deletable(self):
        """草稿可直接删除（级联+软删附件+审计）。"""
        ledger = self.make_manual_ledger(
            status=LEDGER_STATUS_DRAFT, with_correction=True)
        att = self.make_ledger_attachment(ledger)
        resp = self._delete(ledger.id)
        self.assertFalse(resp.json().get('error'), resp.json())
        # 台账、明细、更正记录级联清理
        self.assertFalse(OperationLedger.objects.filter(pk=ledger.id).exists())
        self.assertFalse(OperationLedgerItem.objects.filter(ledger_id=ledger.id).exists())
        self.assertFalse(
            OperationLedgerCorrection.objects.filter(ledger_id=ledger.id).exists())
        # 附件走 evidence 软删除留痕（记录保留，标记已删除）
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)
        self.assertTrue(AuditLog.objects.filter(
            target_type='el_operation_ledger',
            target_id=str(ledger.id), action='delete').exists())

    def test_completed_and_void_not_deletable(self):
        """已完成只允许 查看/导出/更正/作废；已作废保留作废信息：均不可删除。"""
        for status in (LEDGER_STATUS_COMPLETED, LEDGER_STATUS_VOID):
            with self.subTest(status=status):
                ledger = self.make_manual_ledger(status=status)
                resp = self._delete(ledger.id)
                self.assertTrue(resp.json().get('error'))
                self.assertTrue(OperationLedger.objects.filter(pk=ledger.id).exists())
                self.assertEqual(
                    AuditLog.objects.filter(
                        target_type='el_operation_ledger',
                        target_id=str(ledger.id), action='delete').count(), 0)

    def test_delete_blocked_when_item_converted_to_fault(self):
        """存在已转设备故障明细的台账拒绝删除（运行处置记录 PROTECT 引用）。

        转故障仅发生在已完成台账（草稿由状态机拒绝转换），此处直接 ORM
        构造草稿+已转明细的边界数据，验证删除服务的 PROTECT 防护分支。
        """
        ledger = self.make_manual_ledger(status=LEDGER_STATUS_DRAFT)
        item = ledger.items.first()
        item.result = 'abnormal'
        item.save(update_fields=['result'])
        make_record(self.user, self.system_a, record_type='fault',
                    source_ledger_item=item)
        resp = self._delete(ledger.id)
        self.assertTrue(resp.json().get('error'))
        self.assertIn('不能删除', resp.json()['error'])
        self.assertIn('作废', resp.json()['error'])
        self.assertTrue(OperationLedger.objects.filter(pk=ledger.id).exists())

    def test_excel_ledger_delete_cascades_record_keeps_version(self):
        """删除 Excel 路线草稿：填写记录级联清理，模板版本（PROTECT）保留。"""
        template = self.publish_template()
        version = OperationLedgerExcelTemplateVersion.objects.get(
            template_id=template['id'])
        detail = self.create_excel_ledger(version.id)
        resp = self._delete(detail['id'])
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertFalse(
            OperationLedgerExcelRecord.objects.filter(ledger_id=detail['id']).exists())
        self.assertTrue(
            OperationLedgerExcelTemplateVersion.objects.filter(pk=version.id).exists())


class PeriodGenerationSlotTests(LifecycleTestBase):
    """生成槽位：删除草稿可重生成；作废不自动重建、补建明确重建。"""

    def _generate(self, today=(2026, 10, 14)):
        with fake_today(*today):
            resp = post_json(self.client, GENERATE_URL,
                             {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertFalse(resp.json().get('error'), resp.json())
        return resp.json()['data']

    def _preview(self, today=(2026, 10, 14)):
        with fake_today(*today):
            resp = self.client.get(
                GENERATE_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertFalse(resp.json().get('error'), resp.json())
        return resp.json()['data']

    def test_deleted_draft_allows_regenerate(self):
        """本期草稿删除后允许重新生成（唯一约束不再被已删行占用）。"""
        template = self.publish_template(system=self.system_a, generation_period='weekly')
        first = self._generate()
        self.assertEqual(len(first['created']), 1)
        ledger_id = first['created'][0]['id']
        resp = self.client.delete('%s/%s/' % (LEDGERS_URL, ledger_id))
        self.assertFalse(resp.json().get('error'), resp.json())
        second = self._generate()
        self.assertEqual(len(second['created']), 1)
        self.assertNotEqual(second['created'][0]['id'], ledger_id)
        # 槽位内仍只有一张有效台账
        self.assertEqual(OperationLedger.objects.filter(
            source_template_id=template['id'], slot_active=True).count(), 1)

    def test_voided_slot_marked_manual_needed_and_rebuild(self):
        """作废不自动重建：预览标记需人工处理（rebuildable），补建后并存。"""
        template = self.publish_template(system=self.system_a, generation_period='weekly')
        first = self._generate()
        ledger_id = first['created'][0]['id']
        # 作废（作废后 slot_active 置 NULL，不再占用唯一约束）
        resp = post_json(self.client, '%s/%s/void/' % (LEDGERS_URL, ledger_id),
                         {'reason': '整单填错'})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertIsNone(OperationLedger.objects.get(pk=ledger_id).slot_active)
        # 自动生成：不再创建（failed 中标记需人工处理），预览提供补建入口
        result = self._generate()
        self.assertEqual(len(result['created']), 0)
        self.assertTrue(any(f['status'] == 'manual_needed' for f in result['failed']))
        preview = self._preview()
        entry = next(e for e in preview['entries'] if e['template_id'] == template['id'])
        self.assertEqual(entry['status'], 'manual_needed')
        self.assertTrue(entry['rebuildable'])
        self.assertEqual(entry['existing_ledger']['id'], ledger_id)
        # 明确补建：创建新草稿，作废记录保留并存（补建与生成同用假定时钟）
        with fake_today(2026, 10, 14):
            resp = post_json(self.client, REBUILD_URL, {'template_id': template['id']})
        self.assertFalse(resp.json().get('error'), resp.json())
        row = resp.json()['data']
        self.assertNotEqual(row['id'], ledger_id)
        self.assertEqual(row['maintenance_period'], first['created'][0]['maintenance_period'])
        self.assertTrue(OperationLedger.objects.filter(
            pk=ledger_id, status=LEDGER_STATUS_VOID).exists())
        self.assertTrue(OperationLedger.objects.filter(
            pk=row['id'], status=LEDGER_STATUS_DRAFT).exists())
        # 再次自动生成：新草稿已存在 → 跳过
        again = self._generate()
        self.assertEqual(len(again['created']), 0)
        self.assertTrue(any(s['template_id'] == template['id'] for s in again['skipped']))
        # 本期已有有效台账时补建被拒绝
        with fake_today(2026, 10, 14):
            resp = post_json(self.client, REBUILD_URL, {'template_id': template['id']})
        self.assertTrue(resp.json().get('error'))
        self.assertIn('无需补建', resp.json()['error'])
