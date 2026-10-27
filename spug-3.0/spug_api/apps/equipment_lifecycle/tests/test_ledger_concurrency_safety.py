# -*- coding: utf-8 -*-
"""维护台账并发安全行为测试（2026-10-26，分类：defect_reproduction + stable_contract）。

缺陷复现（修复前行为，断言不弱化）：
- P1 保存填写值 TOCTOU：update_values 状态检查基于视图传入的锁外快照对象，
  与"完成填写/作废"并发时完成后/作废后仍可写入 values（mock 交错复现）；
- P2 保存无乐观令牌：旧页面不带版本直接全量覆盖他人修改；
- P3 Excel 更正无锁：correct_completed_ledger 状态检查/diff 基线均基于锁外
  快照，并发更正第二条不再基于陈旧基线放行；
- P4 台账编号生成三路（手工/Excel/数字表单）未捕获编号唯一约束
  IntegrityError，并发撞号泄漏为服务器内部错误。

契约（stable_contract，可纳入发布门禁）：
- update_values / correct_completed_ledger 服务层行锁内重取并复查状态；
- expected_version 可选乐观并发校验（缺省不校验，向后兼容），成功后
  version+1，详情/保存响应顶层含 version；
- 编号冲突有界重试（首attempt 无锁、重试轮锁内当前读），非编号约束的
  IntegrityError 原样抛出，重试耗尽转业务错误。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）；
并发交错按"挂钟交错"确定性复现（mock 视图读取时点的快照对象，服务层
锁内读取走真实查询），不 mock 被测的锁内校验/写入逻辑本身。另含真实
双事务竞争用例（ExcelSaveCompleteRealRaceTests：两个独立 MariaDB 连接
真实竞争台账行锁，验证锁串行化本身）。

二轮复核补充（2026-10-26）：更正成功响应回显锁内最新填写值（缓存回挂）、
编号重试耗尽文案不携带数据库异常细节、真实双事务竞争用例。
"""
import json
import tempfile
import threading
import time
import uuid
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from apps.equipment_lifecycle import (
    excel_ledger_services,
    form_ledger_services,
    ledger_services,
)
from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.excel_sample_template import build_acceptance_sample_xlsx
from apps.equipment_lifecycle.form_models import OperationLedgerFormRecord
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
    make_system,
    make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    ALL_TEMPLATE_PERMS,
    entry_payload,
    item_payload,
    ledger_payload,
    post_json,
    put_json,
)

LEDGERS_URL = URL_PREFIX + '/ledgers'
EXCEL_LEDGERS_URL = URL_PREFIX + '/excel-ledgers'
EXCEL_TPL_URL = URL_PREFIX + '/excel-templates'
FORM_TPL_URL = URL_PREFIX + '/form-templates'
FORM_LEDGER_URL = URL_PREFIX + '/form-ledgers'

STALE_VERSION_ERROR = '台账已被他人修改，请刷新后重试'

STORAGE_DIR = tempfile.mkdtemp(prefix='el_conc_tpl_')
MEDIA_DIR = tempfile.mkdtemp(prefix='el_conc_media_')


def _concurrency_form():
    """数字表单夹具：单普通分组两个非必填字段（保持草稿即可测保存链路）。"""
    return {'protocol_version': 1, 'groups': [
        {'id': 'g_conc0001', 'name': '检查情况', 'description': '', 'kind': 'fields',
         'item_name': '', 'columns': [], 'fields': [
             {'id': 'f_conc0001', 'name': '检查日期', 'type': 'date', 'required': False,
              'description': '', 'unit': '', 'options': []},
             {'id': 'f_conc0002', 'name': '检查结论', 'type': 'normal_abnormal',
              'required': False, 'description': '', 'unit': '', 'options': []},
         ]},
    ]}


class ConcurrencyFixtureBase:
    """公共夹具（TestCase/TransactionTestCase 共用）：台账/模板双权限用户 + 系统 + 独立文件存储。"""

    def setUp(self):
        self.user = make_user('conc_op', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user, system_code='SYS-CONC', name='并发测试系统')
        self._storage_override = override_settings(
            EL_EXCEL_TEMPLATE_BASE_DIR=STORAGE_DIR, MEDIA_ROOT=MEDIA_DIR)
        self._storage_override.enable()
        self.addCleanup(self._storage_override.disable)

    # ---------- Excel 路线夹具（走真实接口） ----------

    def _publish_excel_template(self):
        """发布单字段（正常/异常）Excel 模板，返回 (版本对象, field_id)。"""
        resp = self.client.post(EXCEL_TPL_URL + '/', {
            'file': SimpleUploadedFile('race.xlsx', build_acceptance_sample_xlsx()),
            'name': '并发安全Excel模板', 'ledger_type': LEDGER_TYPE_WEEK_MONTH,
        })
        template = resp.json()['data']['data']
        field_id = str(uuid.uuid4())
        bindings = [{
            'field_id': field_id, 'sheet_name': '信道维护记录',
            'cell_coordinate': 'C4', 'field_name': 'PS模块', 'input_type': 'status',
            'is_required': True, 'unit': '', 'options': [],
        }]
        resp = self.client.put('%s/%s/bindings/' % (EXCEL_TPL_URL, template['id']),
                               json.dumps({'field_bindings': bindings}),
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = self.client.post('%s/%s/publish/' % (EXCEL_TPL_URL, template['id']))
        self.assertFalse(resp.json().get('error'), resp.json())
        version = OperationLedgerExcelTemplateVersion.objects.get(
            template_id=template['id'])
        return version, field_id

    def _make_excel_draft(self):
        """创建一张 Excel 路线草稿台账，返回 (ledger_id, field_id)。"""
        version, field_id = self._publish_excel_template()
        resp = post_json(self.client, EXCEL_LEDGERS_URL + '/', {
            'version_id': version.id, 'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertFalse(resp.json().get('error'), resp.json())
        return resp.json()['data']['data']['id'], field_id

    def _make_excel_completed(self, value='正常'):
        """创建并完成一张 Excel 台账，返回 (ledger_id, field_id, version)。"""
        ledger_id, field_id = self._make_excel_draft()
        resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                        {'values': {field_id: value}})
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = post_json(self.client, '%s/%s/complete/' % (EXCEL_LEDGERS_URL, ledger_id), {})
        self.assertFalse(resp.json().get('error'), resp.json())
        return ledger_id, field_id, OperationLedger.objects.get(pk=ledger_id).version

    # ---------- 数字表单路线夹具（走真实接口） ----------

    def _publish_form_template(self):
        resp = post_json(self.client, FORM_TPL_URL + '/', {
            'name': '并发安全数字表单', 'ledger_type': LEDGER_TYPE_WEEK_MONTH,
            'description': '', 'system': None, 'generation_period': ''})
        self.assertEqual(resp.json().get('error', ''), '')
        template_id = resp.json()['data']['id']
        resp = put_json(self.client, '%s/%s/' % (FORM_TPL_URL, template_id),
                        {'form': _concurrency_form()})
        self.assertEqual(resp.json().get('error', ''), '')
        resp = self.client.post('%s/%s/publish/' % (FORM_TPL_URL, template_id))
        self.assertEqual(resp.json().get('error', ''), '')
        return resp.json()['data']

    def _make_form_ledger(self):
        resp = post_json(self.client, FORM_LEDGER_URL + '/', {'version_id': self._publish_form_template()['id']})
        self.assertEqual(resp.json().get('error', ''), '')
        return resp.json()['data']['id']

    # ---------- 编号冲突夹具 ----------

    def _precreate_dup_ledger_nos(self):
        """预置两个占用号（与被测创建同租户），返回 [dup1, dup2]。

        编号带随机戳：mock 返回什么号，创建就用什么号——只要求与预置行
        完全相同即可触发编号唯一约束，随机化避免与库内遗留数据撞车。
        """
        stamp = uuid.uuid4().hex[:8].upper()
        dup_nos = ['EL-WM-CONC%s-%04d' % (stamp, seq) for seq in (1, 2)]
        for no in dup_nos:
            OperationLedger.objects.create(
                tenant_id=self.user.tenant_id, ledger_no=no,
                ledger_type=LEDGER_TYPE_WEEK_MONTH, status=LEDGER_STATUS_COMPLETED,
                entry_channel='web', created_from='manual', created_by=self.user)
        return dup_nos

    def _dup_no_generator(self, module, dup_nos):
        """mock generate_ledger_no：前两次返回占用号，之后走真实生成。"""
        real_generate = ledger_services.generate_ledger_no
        attempts = []

        def fake_generate(*args, **kwargs):
            attempts.append(bool(kwargs.get('locked')))
            if len(attempts) <= len(dup_nos):
                return dup_nos[len(attempts) - 1]
            return real_generate(*args, **kwargs)

        return mock.patch.object(module, 'generate_ledger_no',
                                 side_effect=fake_generate), attempts


class ConcurrencyTestBase(ConcurrencyFixtureBase, TestCase):
    """顺序/模拟交错用例基座。"""


class ExcelSaveRaceTests(ConcurrencyTestBase):
    """P1/P2：Excel 保存填写值的 TOCTOU 与乐观令牌。"""

    def test_save_rejected_when_completed_concurrently(self):
        """视图快照仍是草稿、库内已完成：锁内复查拒绝，values 不被写入。"""
        ledger_id, field_id = self._make_excel_draft()
        # 视图读取时点的快照（仍是 draft），随后并发链路已把库内置为 completed
        stale = excel_ledger_services.get_ledger(ledger_id, self.user)
        self.assertEqual(stale.status, LEDGER_STATUS_DRAFT)
        OperationLedger.objects.filter(pk=ledger_id).update(status=LEDGER_STATUS_COMPLETED)
        real_get_ledger = excel_ledger_services.get_ledger

        def interlocked(pk, user, for_update=False):
            # 视图（锁外）拿到的旧快照；服务层（锁内）走真实查询
            return real_get_ledger(pk, user, for_update=for_update) if for_update else stale

        with mock.patch.object(excel_ledger_services, 'get_ledger',
                               side_effect=interlocked):
            resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                            {'values': {field_id: '正常'}})
        self.assertIn('不允许修改填写值', resp.json()['error'])
        record = OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)
        self.assertNotIn(field_id, record.get_values())
        ledger = OperationLedger.objects.get(pk=ledger_id)
        self.assertEqual(ledger.status, LEDGER_STATUS_COMPLETED)
        self.assertEqual(ledger.version, 1, '被拒请求不应 bump 版本')

    def test_save_rejected_after_void(self):
        """作废后保存拒绝（锁内复查生效；不依赖 expected_version）。"""
        ledger_id, field_id = self._make_excel_draft()
        OperationLedger.objects.filter(pk=ledger_id).update(status=LEDGER_STATUS_VOID)
        resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                        {'values': {field_id: '正常'}})
        self.assertIn('不允许修改填写值', resp.json()['error'])
        self.assertNotIn(field_id, OperationLedgerExcelRecord.objects.get(
            ledger_id=ledger_id).get_values())
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).version, 1)

    def test_expected_version_conflict_and_bump(self):
        """P2：令牌错配拒绝且值不变；正确令牌/缺省通过；成功后 version+1。"""
        ledger_id, field_id = self._make_excel_draft()
        detail = self.client.get('%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id)).json()['data']['data']
        self.assertEqual(detail['version'], 1, '详情响应顶层应含 version')
        # 缺省不校验（向后兼容）：不带 expected_version 照常保存
        resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                        {'values': {field_id: '正常'}})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(resp.json()['data']['data']['version'], 2)
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).version, 2)
        # 携带正确令牌：通过并再次 bump
        resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                        {'values': {field_id: '正常'}, 'expected_version': 2})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(resp.json()['data']['data']['version'], 3)
        # 陈旧令牌：拒绝，填写值与版本不变（旧页面不再全量覆盖）
        resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                        {'values': {field_id: '异常'}, 'expected_version': 1})
        self.assertEqual(resp.json()['error'], STALE_VERSION_ERROR)
        record = OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)
        self.assertEqual(record.get_values().get(field_id), '正常')
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).version, 3)
        # 非法令牌参数：明确业务错误
        resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                        {'values': {}, 'expected_version': 'abc'})
        self.assertEqual(resp.json()['error'], '版本参数不合法')

    def test_save_after_sequential_complete_rejected(self):
        """回归：顺序语义不变——真实完成后的保存仍被拒绝。"""
        ledger_id, field_id, _ = self._make_excel_completed()
        resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                        {'values': {field_id: '异常'}})
        self.assertIn('不允许修改填写值', resp.json()['error'])


class FormSaveRaceTests(ConcurrencyTestBase):
    """P1/P2：数字表单保存填写值的 TOCTOU 与乐观令牌。"""

    def test_save_rejected_when_completed_concurrently(self):
        ledger_id = self._make_form_ledger()
        stale = form_ledger_services.get_form_ledger(ledger_id, self.user)
        self.assertEqual(stale.status, LEDGER_STATUS_DRAFT)
        OperationLedger.objects.filter(pk=ledger_id).update(status=LEDGER_STATUS_COMPLETED)
        real_get = form_ledger_services.get_form_ledger

        def interlocked(pk, user, for_update=False):
            return real_get(pk, user, for_update=for_update) if for_update else stale

        with mock.patch.object(form_ledger_services, 'get_form_ledger',
                               side_effect=interlocked):
            resp = put_json(self.client, '%s/%s/' % (FORM_LEDGER_URL, ledger_id),
                            {'values': {'f_conc0002': 'normal'}})
        self.assertIn('不允许修改填写值', resp.json()['error'])
        record = OperationLedgerFormRecord.objects.get(ledger_id=ledger_id)
        self.assertEqual(record.get_values(), {})
        ledger = OperationLedger.objects.get(pk=ledger_id)
        self.assertEqual(ledger.status, LEDGER_STATUS_COMPLETED)
        self.assertEqual(ledger.version, 1)

    def test_save_rejected_after_void(self):
        ledger_id = self._make_form_ledger()
        OperationLedger.objects.filter(pk=ledger_id).update(status=LEDGER_STATUS_VOID)
        resp = put_json(self.client, '%s/%s/' % (FORM_LEDGER_URL, ledger_id),
                        {'values': {'f_conc0002': 'normal'}})
        self.assertIn('不允许修改填写值', resp.json()['error'])
        self.assertEqual(OperationLedgerFormRecord.objects.get(
            ledger_id=ledger_id).get_values(), {})
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).version, 1)

    def test_expected_version_conflict_and_bump(self):
        ledger_id = self._make_form_ledger()
        detail = self.client.get('%s/%s/' % (FORM_LEDGER_URL, ledger_id)).json()['data']
        self.assertEqual(detail['version'], 1)
        # 缺省不校验 + 正确令牌两轮保存：version 递增、响应回显最新值
        resp = put_json(self.client, '%s/%s/' % (FORM_LEDGER_URL, ledger_id),
                        {'values': {'f_conc0002': 'normal'}})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(resp.json()['data']['version'], 2)
        resp = put_json(self.client, '%s/%s/' % (FORM_LEDGER_URL, ledger_id),
                        {'values': {'f_conc0002': 'normal'}, 'expected_version': 2})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(resp.json()['data']['version'], 3)
        # 陈旧令牌拒绝：他人保存的值不被旧页面覆盖
        resp = put_json(self.client, '%s/%s/' % (FORM_LEDGER_URL, ledger_id),
                        {'values': {'f_conc0002': 'abnormal'}, 'expected_version': 1})
        self.assertEqual(resp.json()['error'], STALE_VERSION_ERROR)
        record = OperationLedgerFormRecord.objects.get(ledger_id=ledger_id)
        self.assertEqual(record.get_values().get('f_conc0002'), 'normal')
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).version, 3)


class ExcelCorrectRaceTests(ConcurrencyTestBase):
    """P3：Excel 已完成台账更正的锁内复查与 diff 基线。"""

    def _correct(self, ledger_id, body):
        return post_json(self.client,
                         '%s/%s/correct/' % (EXCEL_LEDGERS_URL, ledger_id), body)

    def test_diff_baseline_is_locked_latest_values(self):
        """更正 diff 基线为锁内最新值：第二次更正的 before=V1 而非 V0。"""
        ledger_id, field_id, version = self._make_excel_completed(value='正常')
        # 第一次更正：正常 → 异常（成功后 version+1）
        resp = self._correct(ledger_id, {'reason': '记录有误', 'expected_version': version,
                                         'values': {field_id: '异常'}})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(resp.json()['data']['data']['version'], version + 1)
        correction1 = OperationLedgerCorrection.objects.get(ledger_id=ledger_id)
        self.assertEqual(json.loads(correction1.changes)[0]['old'], '正常')
        self.assertEqual(json.loads(correction1.changes)[0]['new'], '异常')
        # 第二次更正（提交基于 V0 快照构造的目标值）：before 必须取库内
        # 最新值 V1='异常'，而不是陈旧快照的 V0='正常'
        resp = self._correct(ledger_id, {'reason': '二次复核', 'values': {field_id: '正常'}})
        self.assertFalse(resp.json().get('error'), resp.json())
        corrections = OperationLedgerCorrection.objects.filter(
            ledger_id=ledger_id).order_by('id')
        self.assertEqual(corrections.count(), 2)
        second_changes = json.loads(corrections[1].changes)
        self.assertEqual(second_changes[0]['old'], '异常')
        self.assertEqual(second_changes[0]['new'], '正常')
        # 提交与库内最新值相同 → 基线为最新值，判定"没有需要更正的内容"
        resp = self._correct(ledger_id, {'reason': '重复提交', 'values': {field_id: '正常'}})
        self.assertIn('没有需要更正的内容', resp.json()['error'])
        self.assertEqual(OperationLedgerCorrection.objects.filter(
            ledger_id=ledger_id).count(), 2)

    def test_correct_success_response_reflects_corrected_values(self):
        """缺陷回归（二轮复核）：更正成功响应必须回显更正后的填写值。

        更正服务在锁内另查填写记录保存，台账对象上的 select_related 缓存
        仍是更正前对象；响应经 ledger_detail(ledger) 从缓存取值，不回挂则
        数据库与更正记录已更新、页面收到的却是更正前旧值。
        """
        ledger_id, field_id, version = self._make_excel_completed(value='正常')
        resp = self._correct(ledger_id, {'reason': '记录有误',
                                         'expected_version': version,
                                         'values': {field_id: '异常'}})
        self.assertFalse(resp.json().get('error'), resp.json())
        data = resp.json()['data']['data']
        self.assertEqual(data['excel']['values'].get(field_id), '异常')
        self.assertEqual(data['version'], version + 1)

    def test_concurrent_second_correct_with_stale_version_rejected(self):
        """并发两次更正：第二条携带陈旧 expected_version 被拒，不产生第二条更正。"""
        ledger_id, field_id, version = self._make_excel_completed(value='正常')
        # 第一条更正成功：version → version+1
        resp = self._correct(ledger_id, {'reason': '第一条', 'values': {field_id: '异常'}})
        self.assertFalse(resp.json().get('error'), resp.json())
        # 第二条基于第一条更正前的页面快照（expected_version=version）
        resp = self._correct(ledger_id, {'reason': '第二条', 'expected_version': version,
                                         'values': {field_id: '异常'}})
        self.assertEqual(resp.json()['error'], STALE_VERSION_ERROR)
        self.assertEqual(OperationLedgerCorrection.objects.filter(
            ledger_id=ledger_id).count(), 1)
        record = OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)
        self.assertEqual(record.get_values().get(field_id), '异常')

    def test_correct_after_void_rejected_with_stale_view_snapshot(self):
        """视图快照仍是已完成、库内已作废：锁内复查拒绝更正。"""
        ledger_id, field_id, _ = self._make_excel_completed()
        stale = excel_ledger_services.get_ledger(ledger_id, self.user)
        self.assertEqual(stale.status, LEDGER_STATUS_COMPLETED)
        OperationLedger.objects.filter(pk=ledger_id).update(status=LEDGER_STATUS_VOID)
        real_get_ledger = excel_ledger_services.get_ledger

        def interlocked(pk, user, for_update=False):
            return real_get_ledger(pk, user, for_update=for_update) if for_update else stale

        with mock.patch.object(excel_ledger_services, 'get_ledger',
                               side_effect=interlocked):
            resp = self._correct(ledger_id, {'reason': '作废后误操作',
                                             'values': {field_id: '异常'}})
        self.assertIn('只有已完成台账可以进行更正', resp.json()['error'])
        self.assertEqual(OperationLedgerCorrection.objects.filter(
            ledger_id=ledger_id).count(), 0)
        record = OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)
        self.assertEqual(record.get_values().get(field_id), '正常')


class LedgerNoRetryTests(ConcurrencyTestBase):
    """P4：台账编号生成冲突的有界重试（手工/Excel/数字表单三路）。"""

    def test_manual_create_retries_duplicate_ledger_no(self):
        dup_nos = self._precreate_dup_ledger_nos()
        patcher, attempts = self._dup_no_generator(ledger_services, dup_nos)
        payload = ledger_payload([entry_payload(self.system.id, [item_payload()])])
        with patcher:
            resp = post_json(self.client, LEDGERS_URL + '/', payload)
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        ledger_no = data['data']['ledger_no']
        self.assertNotIn(ledger_no, dup_nos, '重试后必须换号')
        self.assertEqual(OperationLedger.objects.filter(ledger_no=ledger_no).count(), 1)
        # 重试路径未重复写明细（保存点回滚干净）
        self.assertEqual(OperationLedgerItem.objects.filter(
            ledger__ledger_no=ledger_no).count(), 1)
        # 首次无锁、重试轮锁内当前读（与 generate_ledger_no locked 契约一致）
        self.assertEqual(attempts, [False, True, True])

    def test_excel_create_retries_duplicate_ledger_no(self):
        dup_nos = self._precreate_dup_ledger_nos()
        version, _ = self._publish_excel_template()
        patcher, attempts = self._dup_no_generator(excel_ledger_services, dup_nos)
        with patcher:
            resp = post_json(self.client, EXCEL_LEDGERS_URL + '/', {
                'version_id': version.id, 'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        ledger_no = data['data']['data']['ledger_no']
        self.assertNotIn(ledger_no, dup_nos)
        self.assertEqual(OperationLedger.objects.filter(ledger_no=ledger_no).count(), 1)
        self.assertEqual(OperationLedgerExcelRecord.objects.filter(
            ledger__ledger_no=ledger_no).count(), 1)
        self.assertEqual(attempts, [False, True, True])

    def test_form_create_retries_duplicate_ledger_no(self):
        dup_nos = self._precreate_dup_ledger_nos()
        version = self._publish_form_template()
        patcher, attempts = self._dup_no_generator(form_ledger_services, dup_nos)
        with patcher:
            resp = post_json(self.client, FORM_LEDGER_URL + '/',
                             {'version_id': version['id']})
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        ledger_no = data['data']['ledger_no']
        self.assertNotIn(ledger_no, dup_nos)
        self.assertEqual(OperationLedger.objects.filter(ledger_no=ledger_no).count(), 1)
        self.assertEqual(OperationLedgerFormRecord.objects.filter(
            ledger__ledger_no=ledger_no).count(), 1)
        self.assertEqual(attempts, [False, True, True])

    def test_helper_reraises_unrelated_integrity_error(self):
        """非编号唯一约束的 IntegrityError 不被吞掉（原样抛出）。"""

        def build_row(locked=False):
            raise IntegrityError(
                "(1062, \"Duplicate entry 'x' for key 'uniq_other_constraint'\")")

        with self.assertRaises(IntegrityError):
            ledger_services.create_ledger_row_with_no_retry(build_row)

    def test_helper_raises_business_error_after_retry_exhausted(self):
        """编号冲突重试耗尽：转业务错误（不再泄漏 IntegrityError）。"""
        calls = []

        def build_row(locked=False):
            calls.append(locked)
            raise IntegrityError(
                "(1062, \"Duplicate entry 'x' for key 'uniq_el_operation_ledger_no'\")")

        with self.assertRaises(ledger_services.LedgerValidationError) as ctx:
            ledger_services.create_ledger_row_with_no_retry(build_row)
        # 二轮复核：耗尽文案不得携带原始异常（重复键/约束细节泄漏给用户）
        message = str(ctx.exception)
        self.assertEqual(message, '台账编号生成冲突，请重试')
        self.assertNotIn('uniq_el_operation_ledger_no', message)
        self.assertNotIn('Duplicate entry', message)
        self.assertEqual(calls, [False, True, True])


class ExcelSaveCompleteRealRaceTests(ConcurrencyFixtureBase, TransactionTestCase):
    """真实双事务竞争（二轮复核补充）：两个独立 MariaDB 连接真实竞争行锁。

    上方 mock 交错用例验证锁内复查逻辑本身；本类验证 select_for_update
    在真实数据库上把"保存"与"完成"两条请求路径串行化——保存请求必须
    等待完成事务提交后在锁内读到最新状态并拒绝（修复前：状态检查基于
    锁外快照，会在完成提交后仍把已完成台账的填写值改写）。

    三轮复核强化：固定 sleep 持锁无法证明保存请求真的进入了锁等待
    （可能恰在提交后才到达）。第一条用例以 traced 视图预检读取为锚点
    ——完成事务等保存请求的锁外预检读发生（此时行锁仍被持有）后再
    缓冲提交，保存的服务层锁定读只能阻塞等待；并以耗时下限佐证锁等待。
    第二条用例让完成与保存两条真实生产服务路径经 barrier 真实并发，
    断言两种串行化次序下的不变量。
    """

    def test_save_blocked_until_complete_commits_then_rejected(self):
        ledger_id, field_id = self._make_excel_draft()
        lock_acquired = threading.Event()
        save_view_read = threading.Event()
        completer_errors = []
        real_get_ledger = excel_ledger_services.get_ledger

        def traced_get(pk, user, for_update=False):
            # 锚点：保存请求的视图锁外预检读发生时，完成事务仍持有行锁
            # ——其后的服务层 select_for_update 只能阻塞等待，不存在
            # "完成先提交、保存后到也能读出 completed"的旁路时序
            if not for_update:
                save_view_read.set()
            return real_get_ledger(pk, user, for_update=for_update)

        def completer():
            # 独立线程 = 独立数据库连接（TransactionTestCase 夹具已提交，可见）
            try:
                with transaction.atomic():
                    ledger = OperationLedger.objects.select_for_update().get(
                        pk=ledger_id)
                    # 行锁已握在完成事务手里，此时才放行保存请求
                    lock_acquired.set()
                    # 等保存请求进入视图预检读（锁仍持有），再缓冲一段
                    # 确保其服务层锁定读已发起，然后提交
                    if not save_view_read.wait(timeout=5):
                        raise AssertionError('保存请求未在持锁窗口内进入视图读取')
                    time.sleep(0.2)
                    ledger.status = LEDGER_STATUS_COMPLETED
                    ledger.save(update_fields=['status'])
            except Exception as error:  # 线程异常传导到主线程断言
                completer_errors.append(error)
                lock_acquired.set()
            finally:
                connections.close_all()

        with mock.patch.object(excel_ledger_services, 'get_ledger',
                               side_effect=traced_get):
            thread = threading.Thread(target=completer)
            thread.start()
            self.assertTrue(lock_acquired.wait(timeout=5),
                            '完成事务未按预期取得台账行锁')
            started = time.monotonic()
            resp = put_json(self.client, '%s/%s/' % (EXCEL_LEDGERS_URL, ledger_id),
                            {'values': {field_id: '异常'}})
            elapsed = time.monotonic() - started
            thread.join(timeout=5)
        self.assertEqual(completer_errors, [])
        self.assertIn('不允许修改填写值', resp.json()['error'])
        # 锁等待真实发生：保存请求在完成事务持锁期间发起，提交前无法
        # 越过锁定读——请求耗时必须覆盖持锁缓冲窗口
        self.assertGreaterEqual(elapsed, 0.15)
        # 完成事务的写入保留；保存请求未改写任何数据（values/版本不变）
        ledger = OperationLedger.objects.get(pk=ledger_id)
        self.assertEqual(ledger.status, LEDGER_STATUS_COMPLETED)
        self.assertEqual(ledger.version, 1)
        record = OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)
        self.assertNotEqual(record.get_values().get(field_id), '异常')

    def test_real_concurrent_save_and_complete_serialize(self):
        """双真实服务并发：update_values 与 complete_ledger 同时发起。

        两条真实生产服务路径（含各自的 select_for_update）在两个独立
        连接上真实竞争，行锁把两者串行化，断言两种次序下的不变量：
        - 保存先提交 → 完成随后成功，终态 completed 且 values=保存值；
        - 完成先提交 → 保存在锁内读到 completed 被拒，values 不变。
        即无论次序如何，都不存在"完成提交后保存仍写入"的交错。
        """
        ledger_id, field_id = self._make_excel_draft()
        start = threading.Barrier(2, timeout=5)
        completer_errors = []
        outcome = {}

        def completer():
            try:
                start.wait()
                _, complete_error = excel_ledger_services.complete_ledger(
                    self.user, ledger_id)
                outcome['complete_error'] = complete_error
            except Exception as error:  # 线程异常传导到主线程断言
                completer_errors.append(error)
            finally:
                connections.close_all()

        thread = threading.Thread(target=completer)
        thread.start()
        start.wait()
        save_error = None
        try:
            excel_ledger_services.update_values(
                self.user, ledger_id, {field_id: '异常'})
        except excel_ledger_services.ExcelLedgerError as error:
            save_error = str(error)
        thread.join(timeout=5)
        self.assertEqual(completer_errors, [])
        self.assertIsNone(outcome.get('complete_error'), outcome)
        record = OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)
        ledger = OperationLedger.objects.get(pk=ledger_id)
        if save_error is None:
            # 保存先提交：完成随后成功，终态必须包含保存值
            self.assertEqual(ledger.status, LEDGER_STATUS_COMPLETED)
            self.assertEqual(record.get_values().get(field_id), '异常')
        else:
            # 完成先提交：保存在锁内被状态复查拒绝，values 不变
            self.assertIn('不允许修改填写值', save_error)
            self.assertEqual(ledger.status, LEDGER_STATUS_COMPLETED)
            self.assertNotEqual(record.get_values().get(field_id), '异常')
