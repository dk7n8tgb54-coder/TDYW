# -*- coding: utf-8 -*-
"""设备管理——异常与容错专项（quality/equipment_quality）。

覆盖：非法参数、缺失数据、重复提交、状态机误用、模板/附件物理文件缺失、
单条脏数据不影响列表/统计/其他记录导出。全部走真实 HTTP + 数据库断言；
任何场景均不允许 5xx，业务失败必须以 json error 呈现且不留下不一致数据。

隔离约定：每个用例使用独立租户（uuid 后缀），不受隔离测试库残留数据影响。
"""
import json
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase

from apps.equipment_lifecycle.models import OperationLedger
from apps.equipment_lifecycle.operation_models import SystemOperationRecord
from apps.evidence.models import EvidenceAttachment

from quality.equipment_quality.qa_base import (
    CANDIDATES_URL, EXCEL_LEDGER_URL, GENERATE_URL, LEDGER_URL, NONEXISTENT_ID,
    RECORDS_URL, SYSTEMS_URL, TPL_URL, ExcelTemplateFlowMixin, IsoStorageMixin,
    assert_no_500, create_ledger_ok, entry_payload, inner, item_payload,
    ledger_payload, make_client, make_record, make_system, make_user,
    post_json, put_json, uniq,
)


class QaCase(IsoStorageMixin, TestCase):
    """公共 setUp：独立租户用户 + 客户端。"""

    perms = []

    def setUp(self):
        super().setUp()
        self.tenant = uniq('t')
        self.user = make_user(uniq('qa_user'), perms=self.perms,
                              tenant_id=self.tenant)
        self.client = make_client(self.user)

    def make_tenant_system(self, **kwargs):
        return make_system(self.user, tenant_id=self.tenant, **kwargs)


class SystemInvalidParamsTests(QaCase):
    """系统主数据：非法参数与缺失数据。"""

    perms = ['equipment_lifecycle.system.view',
             'equipment_lifecycle.system.deactivate']

    def setUp(self):
        super().setUp()
        self.system = self.make_tenant_system()

    def test_detail_nonexistent_is_business_error(self):
        res = self.client.get('%s/%s/' % (SYSTEMS_URL, NONEXISTENT_ID))
        assert_no_500(res, 'system detail')
        self.assertTrue(res.json().get('error'), res.content[:200])

    def test_update_nonexistent_is_business_error(self):
        res = put_json(self.client, '%s/%s/' % (SYSTEMS_URL, NONEXISTENT_ID),
                       {'name': '不存在系统'})
        assert_no_500(res, 'system update')
        self.assertTrue(res.json().get('error'))

    def test_delete_nonexistent_is_business_error(self):
        res = self.client.delete('%s/%s/' % (SYSTEMS_URL, NONEXISTENT_ID))
        assert_no_500(res, 'system delete')
        self.assertTrue(res.json().get('error'))

    def test_active_toggle_nonexistent_is_business_error(self):
        res = post_json(self.client, '%s/%s/active/' % (SYSTEMS_URL, NONEXISTENT_ID),
                        {'is_active': False})
        assert_no_500(res, 'system active')
        self.assertTrue(res.json().get('error'))

    def test_list_invalid_pagination_clamped_no_500(self):
        for query in ('?page=0', '?page=-3', '?page=abc',
                      '?page_size=999999', '?page_size=-1', '?page=1&page_size=0'):
            res = self.client.get(SYSTEMS_URL + '/' + query)
            assert_no_500(res, 'system list %s' % query)
            body = res.json()
            self.assertFalse(body.get('error'), (query, body))
            self.assertLessEqual(body.get('page_size', 20), 200)

    def test_list_keyword_special_chars_no_500(self):
        for keyword in ("'", '"', '%', '\\', '%lok%'):
            res = self.client.get(SYSTEMS_URL + '/?keyword=' + keyword)
            assert_no_500(res, 'system keyword %r' % keyword)
            self.assertFalse(res.json().get('error'))


class RecordInvalidParamsTests(QaCase):
    """运行处置记录：非法参数、缺失数据、幂等重复提交。"""

    perms = ['equipment_lifecycle.operation_record.view',
             'equipment_lifecycle.operation_record.add']

    def setUp(self):
        super().setUp()
        self.system = self.make_tenant_system()

    def _payload(self, **overrides):
        payload = {
            'record_type': 'abnormal', 'system': self.system.id,
            'occurred_at': '2026-10-20 08:30', 'title': '容错测试记录',
            'description': '异常与容错专项', 'registrar_name': '测试员',
        }
        payload.update(overrides)
        return payload

    def test_detail_nonexistent_is_business_error(self):
        res = self.client.get('%s/%s/' % (RECORDS_URL, NONEXISTENT_ID))
        assert_no_500(res, 'record detail')
        self.assertTrue(res.json().get('error'))

    def test_progress_nonexistent_is_business_error(self):
        res = post_json(self.client, '%s/%s/progress/' % (RECORDS_URL, NONEXISTENT_ID),
                        {'content': '跟进'})
        assert_no_500(res, 'record progress')
        self.assertTrue(res.json().get('error'))

    def test_create_invalid_occurred_at_rejected(self):
        res = post_json(self.client, RECORDS_URL + '/',
                        self._payload(occurred_at='not-a-date'))
        assert_no_500(res, 'record create bad date')
        self.assertTrue(res.json().get('error'))
        self.assertFalse(SystemOperationRecord.objects.filter(
            tenant_id=self.tenant, title='容错测试记录').exists())

    def test_create_nonexistent_system_rejected(self):
        res = post_json(self.client, RECORDS_URL + '/',
                        self._payload(system=NONEXISTENT_ID))
        assert_no_500(res, 'record create bad system')
        self.assertTrue(res.json().get('error'))

    def test_list_invalid_filters_no_500(self):
        for query in ('?record_type=bogus', '?status=bogus', '?system=abc',
                      '?occurred_from=bad-date', '?page=0&page_size=99999'):
            res = self.client.get(RECORDS_URL + '/' + query)
            assert_no_500(res, 'record list %s' % query)
            # 非法筛选值允许显式业务报错或安全空结果，但不允许 500（上面已断言）

    def test_double_submit_same_client_token_returns_same_record(self):
        token = uniq('tok')
        first = post_json(self.client, RECORDS_URL + '/',
                          self._payload(client_token=token))
        assert_no_500(first, 'record create 1')
        self.assertFalse(first.json().get('error'), first.content[:200])
        second = post_json(self.client, RECORDS_URL + '/',
                           self._payload(client_token=token))
        assert_no_500(second, 'record create 2')
        self.assertFalse(second.json().get('error'), second.content[:200])
        self.assertEqual(first.json()['data']['id'], second.json()['data']['id'])
        self.assertEqual(
            SystemOperationRecord.objects.filter(client_token=token).count(), 1)

    def test_huge_description_record_does_not_break_list_and_statistics(self):
        res = post_json(self.client, RECORDS_URL + '/',
                        self._payload(description='描' * 200000))
        assert_no_500(res, 'record create huge desc')
        huge_id = None
        if not res.json().get('error'):
            huge_id = res.json()['data']['id']
        listing = self.client.get(RECORDS_URL + '/')
        assert_no_500(listing, 'record list after huge desc')
        self.assertFalse(listing.json().get('error'))
        stats = self.client.get(RECORDS_URL + '/statistics/')
        assert_no_500(stats, 'record statistics after huge desc')
        todo = self.client.get(RECORDS_URL + '/todo/')
        assert_no_500(todo, 'record todo after huge desc')
        if huge_id:
            SystemOperationRecord.objects.get(pk=huge_id).delete()

    def test_unicode_emoji_title_survives_roundtrip(self):
        title = 'UPS告警⚠️-电房温度🔥'
        res = post_json(self.client, RECORDS_URL + '/', self._payload(title=title))
        assert_no_500(res, 'record create emoji')
        self.assertFalse(res.json().get('error'), res.content[:200])
        detail = self.client.get('%s/%s/' % (RECORDS_URL, res.json()['data']['id']))
        self.assertEqual(detail.json()['data']['title'], title)


class RecordActionStateMachineTests(QaCase):
    """状态动作误用：非法流转必须拒绝且不落库。"""

    perms = ['equipment_lifecycle.operation_record.view',
             'equipment_lifecycle.operation_record.progress',
             'equipment_lifecycle.operation_record.complete',
             'equipment_lifecycle.operation_record.identify_fault']

    def setUp(self):
        super().setUp()
        self.system = self.make_tenant_system()

    def test_complete_twice_second_rejected(self):
        # 完成跟进的动作语义：仅"跟进中"记录可完成（先追加进展触发 following_up）
        record = make_record(self.user, self.system, tenant_id=self.tenant)
        progress = post_json(self.client,
                             '%s/%s/progress/' % (RECORDS_URL, record.id),
                             {'content': '现场跟进', 'handled_at': '2026-10-20 09:00'})
        assert_no_500(progress, 'record progress for complete')
        self.assertFalse(progress.json().get('error'), progress.content[:200])
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')
        first = post_json(self.client, '%s/%s/complete/' % (RECORDS_URL, record.id),
                          {'summary': '已完成跟进'})
        assert_no_500(first, 'complete 1')
        self.assertFalse(first.json().get('error'), first.content[:200])
        second = post_json(self.client, '%s/%s/complete/' % (RECORDS_URL, record.id),
                           {'summary': '重复完成'})
        assert_no_500(second, 'complete 2')
        self.assertTrue(second.json().get('error'))
        record.refresh_from_db()
        self.assertEqual(record.status, 'completed')

    def test_complete_on_recorded_rejected(self):
        """recorded（未跟进）直接完成跟进必须被拒绝。"""
        record = make_record(self.user, self.system, tenant_id=self.tenant)
        res = post_json(self.client, '%s/%s/complete/' % (RECORDS_URL, record.id),
                        {'summary': '未跟进就完成'})
        assert_no_500(res, 'complete on recorded')
        self.assertTrue(res.json().get('error'))
        record.refresh_from_db()
        self.assertEqual(record.status, 'recorded')

    def test_identify_fault_on_fault_record_rejected(self):
        record = make_record(self.user, self.system, record_type='fault',
                             tenant_id=self.tenant)
        res = post_json(self.client,
                        '%s/%s/identify-fault/' % (RECORDS_URL, record.id), {})
        assert_no_500(res, 'identify fault on fault')
        self.assertTrue(res.json().get('error'))

    def test_complete_nonexistent_is_business_error(self):
        res = post_json(self.client, '%s/%s/complete/' % (RECORDS_URL, NONEXISTENT_ID),
                        {'summary': 'x'})
        assert_no_500(res, 'complete nonexistent')
        self.assertTrue(res.json().get('error'))


class LedgerInvalidParamsTests(QaCase):
    """维护台账：非法参数与状态机误用。"""

    perms = ['equipment_lifecycle.ledger.view', 'equipment_lifecycle.ledger.add',
             'equipment_lifecycle.ledger.edit', 'equipment_lifecycle.ledger.del',
             'equipment_lifecycle.ledger.submit']

    def setUp(self):
        super().setUp()
        self.system = self.make_tenant_system()

    def _create_ledger(self):
        return create_ledger_ok(self.client, ledger_payload(
            [entry_payload(self.system.id, [item_payload()])]))

    def test_create_without_entries_rejected(self):
        res = post_json(self.client, LEDGER_URL + '/',
                        ledger_payload([], executed_start='2026-10-20 09:00',
                                       executed_end='2026-10-20 10:00'))
        assert_no_500(res, 'ledger create no entries')
        self.assertTrue(res.json().get('error'))

    def test_create_nonexistent_system_rejected(self):
        before = OperationLedger.objects.filter(tenant_id=self.tenant).count()
        res = post_json(self.client, LEDGER_URL + '/', ledger_payload(
            [entry_payload(NONEXISTENT_ID, [item_payload()])]))
        assert_no_500(res, 'ledger create bad system')
        self.assertTrue(res.json().get('error'))
        self.assertEqual(
            OperationLedger.objects.filter(tenant_id=self.tenant).count(), before)

    def test_detail_nonexistent_is_business_error(self):
        res = self.client.get('%s/%s/' % (LEDGER_URL, NONEXISTENT_ID))
        assert_no_500(res, 'ledger detail')
        self.assertTrue(res.json().get('error'))

    def test_list_invalid_filters_no_500(self):
        for query in ('?ledger_type=bogus', '?status=bogus', '?system=abc',
                      '?keyword=%27', '?page=0&page_size=99999'):
            res = self.client.get(LEDGER_URL + '/' + query)
            assert_no_500(res, 'ledger list %s' % query)
            self.assertFalse(res.json().get('error'), (query, res.content[:200]))

    def test_complete_twice_second_rejected(self):
        ledger = self._create_ledger()
        first = post_json(self.client, '%s/%s/complete/' % (LEDGER_URL, ledger['id']), {})
        assert_no_500(first, 'ledger complete 1')
        self.assertFalse(first.json().get('error'), first.content[:200])
        second = post_json(self.client, '%s/%s/complete/' % (LEDGER_URL, ledger['id']), {})
        assert_no_500(second, 'ledger complete 2')
        self.assertTrue(second.json().get('error'))
        row = OperationLedger.objects.get(pk=ledger['id'])
        self.assertEqual(row.status, 'completed')

    def test_void_requires_reason(self):
        ledger = self._create_ledger()
        res = post_json(self.client, '%s/%s/void/' % (LEDGER_URL, ledger['id']), {})
        assert_no_500(res, 'ledger void no reason')
        self.assertTrue(res.json().get('error'))
        row = OperationLedger.objects.get(pk=ledger['id'])
        self.assertEqual(row.status, 'draft')

    def test_void_then_complete_rejected(self):
        ledger = self._create_ledger()
        void = post_json(self.client, '%s/%s/void/' % (LEDGER_URL, ledger['id']),
                         {'reason': '误建'})
        assert_no_500(void, 'ledger void')
        self.assertFalse(void.json().get('error'), void.content[:200])
        complete = post_json(self.client,
                             '%s/%s/complete/' % (LEDGER_URL, ledger['id']), {})
        assert_no_500(complete, 'ledger complete after void')
        self.assertTrue(complete.json().get('error'))
        row = OperationLedger.objects.get(pk=ledger['id'])
        self.assertEqual(row.status, 'void')

    def test_void_twice_second_rejected(self):
        ledger = self._create_ledger()
        first = post_json(self.client, '%s/%s/void/' % (LEDGER_URL, ledger['id']),
                          {'reason': '误建'})
        self.assertFalse(first.json().get('error'), first.content[:200])
        second = post_json(self.client, '%s/%s/void/' % (LEDGER_URL, ledger['id']),
                           {'reason': '再次作废'})
        assert_no_500(second, 'ledger void 2')
        self.assertTrue(second.json().get('error'))


class PeriodGenerateRobustnessTests(IsoStorageMixin, TransactionTestCase):
    """本期应填台账生成：重复生成幂等、非法周期参数。

    与既有 test_ledger_period_generate 一致使用 TransactionTestCase
    （生成路径持 GET_LOCK/行锁，与 TestCase 事务语义不兼容）。
    """

    def setUp(self):
        super().setUp()
        self.tenant = uniq('gen_t')
        self.user = make_user(uniq('gen_user'), perms=[
            'equipment_lifecycle.ledger_template.view',
            'equipment_lifecycle.ledger_template.add',
            'equipment_lifecycle.ledger_template.edit',
            'equipment_lifecycle.ledger.view',
            'equipment_lifecycle.ledger.add',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)
        self.system = make_system(self.user, tenant_id=self.tenant)
        self.flow = ExcelTemplateFlowMixin()
        self.flow.client = self.client
        self.template = self.flow.upload_template()
        self.flow.save_bindings(self.template['id'],
                                [self.flow.make_binding('C4', 'PS模块')])
        self.flow.publish(self.template['id'])
        self.flow.set_generation_config(self.template['id'], self.system)

    def _generate(self, ledger_type='week_month'):
        return post_json(self.client, GENERATE_URL, {'ledger_type': ledger_type})

    def _template_ledger_count(self):
        return OperationLedger.objects.filter(
            tenant_id=self.tenant, source_template_id=self.template['id']).count()

    def test_generate_twice_does_not_duplicate(self):
        first = self._generate()
        assert_no_500(first, 'generate 1')
        self.assertFalse(first.json().get('error'), first.content[:200])
        created_first = first.json()['data'].get('created', [])
        self.assertTrue(created_first)
        second = self._generate()
        assert_no_500(second, 'generate 2')
        body = second.json()
        # 幂等语义：重复生成要么业务报错，要么返回空创建列表；都不允许新增台账
        if not body.get('error'):
            self.assertEqual(body['data'].get('created', []), [])
        self.assertEqual(self._template_ledger_count(), len(created_first))

    def test_generate_invalid_ledger_type_rejected(self):
        before = self._template_ledger_count()
        res = self._generate(ledger_type='bogus_type')
        assert_no_500(res, 'generate bad type')
        self.assertTrue(res.json().get('error'))
        self.assertEqual(self._template_ledger_count(), before)


class ExcelTemplateFileMissingTests(IsoStorageMixin, TestCase):
    """模板/台账物理文件缺失：必须业务错误降级，不允许 5xx，且不波及他人。"""

    def setUp(self):
        super().setUp()
        self.tenant = uniq('file_t')
        self.user = make_user(uniq('file_user'), perms=[
            'equipment_lifecycle.ledger_template.view',
            'equipment_lifecycle.ledger_template.add',
            'equipment_lifecycle.ledger_template.edit',
            'equipment_lifecycle.ledger.view',
            'equipment_lifecycle.ledger.add',
            'equipment_lifecycle.ledger.edit',
            'equipment_lifecycle.ledger.export',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)
        self.flow = ExcelTemplateFlowMixin()
        self.flow.client = self.client

    def _make_published_template(self):
        template = self.flow.upload_template()
        bindings = [self.flow.make_binding('C4', 'PS模块')]
        self.flow.save_bindings(template['id'], bindings)
        version = self.flow.publish(template['id'])
        return template, version, bindings

    def _make_filled_ledger(self, version, bindings):
        ledger = self.flow.create_excel_ledger(version['id'])
        self.flow.fill_excel_ledger(
            ledger['id'], [b['field_id'] for b in bindings])
        return ledger

    def test_template_preview_pdf_with_missing_draft_is_business_error(self):
        template, _version, _bindings = self._make_published_template()
        self.remove_template_files(template['id'])
        res = self.client.post('%s/%s/preview/pdf/' % (TPL_URL, template['id']))
        assert_no_500(res, 'template preview missing draft')
        self.assertTrue(res.json().get('error'), res.content[:200])

    def test_ledger_export_missing_source_is_business_error_and_others_unaffected(self):
        template_a, version_a, bindings_a = self._make_published_template()
        template_b, version_b, bindings_b = self._make_published_template()
        ledger_a = self._make_filled_ledger(version_a, bindings_a)
        ledger_b = self._make_filled_ledger(version_b, bindings_b)
        self.remove_template_files(template_a['id'])

        res_excel = self.client.post(
            '%s/%s/export/excel/' % (EXCEL_LEDGER_URL, ledger_a['id']))
        assert_no_500(res_excel, 'ledger a export excel missing file')
        self.assertTrue(res_excel.json().get('error'), res_excel.content[:200])

        res_pdf = self.client.post(
            '%s/%s/export/pdf/' % (EXCEL_LEDGER_URL, ledger_a['id']))
        assert_no_500(res_pdf, 'ledger a export pdf missing file')
        self.assertTrue(res_pdf.json().get('error'), res_pdf.content[:200])

        # 其他模板的台账导出不受影响（局部失败不扩大）：二进制 xlsx 正常返回
        ok = self.client.post(
            '%s/%s/export/excel/' % (EXCEL_LEDGER_URL, ledger_b['id']))
        assert_no_500(ok, 'ledger b export excel intact')
        self.assertEqual(ok.status_code, 200, ok.content[:200])
        if ok.content[:2] != b'PK':
            self.fail('非 xlsx 响应: ctype=%s body=%r' % (
                ok.get('Content-Type'), ok.content[:300]))

    def test_ledger_list_survives_missing_template_files(self):
        template, version, bindings = self._make_published_template()
        self.flow.create_excel_ledger(version['id'])
        self.remove_template_files(template['id'])
        res = self.client.get(LEDGER_URL + '/')
        assert_no_500(res, 'ledger list missing files')
        self.assertFalse(res.json().get('error'), res.content[:200])


class RecordAttachmentFileMissingTests(IsoStorageMixin, TestCase):
    """记录附件物理文件缺失：下载/删除降级不 5xx，软删除标记照常落库。"""

    def setUp(self):
        super().setUp()
        self.tenant = uniq('att_t')
        self.user = make_user(uniq('att_user'), perms=[
            'equipment_lifecycle.operation_record.view',
            'equipment_lifecycle.operation_record.edit',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)
        self.system = make_system(self.user, tenant_id=self.tenant)
        self.record = make_record(self.user, self.system, tenant_id=self.tenant)

    def _upload_attachment(self, name='note.txt'):
        res = self.client.post(
            '%s/%s/attachments/' % (RECORDS_URL, self.record.id),
            {'file': SimpleUploadedFile(name, b'attachment-content')})
        assert_no_500(res, 'attachment upload')
        self.assertFalse(res.json().get('error'), res.content[:200])
        return res.json()['data']

    def _physical_path(self, att_id):
        att_row = EvidenceAttachment.objects.get(pk=att_id)
        return os.path.join(self._media_dir, att_row.file_path)

    def test_download_after_physical_file_removed_is_graceful(self):
        att = self._upload_attachment()
        physical = self._physical_path(att['id'])
        self.assertTrue(os.path.exists(physical), physical)
        os.remove(physical)

        res = self.client.get('%s/%s/attachments/%s/download/'
                              % (RECORDS_URL, self.record.id, att['id']))
        assert_no_500(res, 'attachment download missing file')
        self.assertTrue(res.json().get('error'), res.content[:200])

        listing = self.client.get('%s/%s/attachments/' % (RECORDS_URL, self.record.id))
        assert_no_500(listing, 'attachment list missing file')
        self.assertFalse(listing.json().get('error'))

    def test_soft_delete_after_physical_file_removed_is_graceful(self):
        att = self._upload_attachment()
        os.remove(self._physical_path(att['id']))

        res = self.client.delete('%s/%s/attachments/%s/'
                                 % (RECORDS_URL, self.record.id, att['id']))
        assert_no_500(res, 'attachment soft delete missing file')
        att_row = EvidenceAttachment.objects.all_with_deleted().get(pk=att['id'])
        self.assertTrue(att_row.is_deleted)


class TenantOptionsConsistencyTests(QaCase):
    """候选系统口径：停用系统不得出现在候选；记录引用停用系统被拒。"""

    perms = ['equipment_lifecycle.operation_record.view',
             'equipment_lifecycle.operation_record.add',
             'equipment_lifecycle.system.view',
             'equipment_lifecycle.system.deactivate']

    def setUp(self):
        super().setUp()
        self.system = self.make_tenant_system()

    def test_deactivated_system_excluded_from_candidates_and_record_rejected(self):
        res = post_json(self.client, '%s/%s/active/' % (SYSTEMS_URL, self.system.id),
                        {'is_active': False})
        assert_no_500(res, 'deactivate system')
        self.assertFalse(res.json().get('error'), res.content[:200])
        candidates = inner(self.client.get(CANDIDATES_URL))['data']
        self.assertEqual([s['id'] for s in candidates], [])
        create = post_json(self.client, RECORDS_URL + '/', {
            'record_type': 'abnormal', 'system': self.system.id,
            'occurred_at': '2026-10-20 08:30', 'title': '停用系统登记',
            'description': '应拒绝', 'registrar_name': '测试员',
        })
        assert_no_500(create, 'record create on deactivated system')
        self.assertTrue(create.json().get('error'), create.content[:200])

    def test_active_system_in_candidates(self):
        candidates = inner(self.client.get(CANDIDATES_URL))['data']
        self.assertIn(self.system.id, [s['id'] for s in candidates])
