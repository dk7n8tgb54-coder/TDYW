# -*- coding: utf-8 -*-
"""设备管理——安全专项（quality/equipment_quality）。

覆盖：跨租户读写与关联、权限后端独立校验（无权限/仅查看）、附件跨模块与
跨租户归属、上传校验、敏感信息泄露、超管与普通用户差异。
全部走真实 HTTP + 数据库状态断言；测试数据均为临时夹具，不含真实敏感数据。
"""
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LifecycleSystem, OperationLedger,
)
from apps.equipment_lifecycle.operation_models import SystemOperationRecord
from apps.evidence.models import EvidenceAttachment
from apps.upgrade.models import UpgradeRecord

from quality.equipment_quality.qa_base import (
    EXCEL_LEDGER_URL, LEDGER_URL, NONEXISTENT_ID, RECORDS_URL, SYSTEMS_URL,
    TPL_URL, UPGRADE_URL, ExcelTemplateFlowMixin, IsoStorageMixin,
    assert_no_500, create_ledger_ok, entry_payload, inner, item_payload,
    ledger_payload, make_client, make_record, make_system, make_user,
    post_json, put_json, uniq,
)


def upgrade_record_row(tenant_id, created_by, system=None, no=None):
    return UpgradeRecord.objects.create(
        upgrade_no=no or uniq('SJQA'),
        tenant_id=tenant_id, title='质量专项升级记录',
        system=system, system_name=system.name if system else '',
        upgrade_type='软件升级', owner='测试负责人',
        created_by=created_by,
    )


class CrossTenantSystemTests(TestCase):
    """系统主数据跨租户边界。"""

    def setUp(self):
        self.tenant_a = uniq('ta')
        self.tenant_b = uniq('tb')
        self.user_a = make_user(uniq('ua'), perms=[
            'equipment_lifecycle.system.view', 'equipment_lifecycle.system.edit',
            'equipment_lifecycle.system.del', 'equipment_lifecycle.system.deactivate',
            'equipment_lifecycle.operation_record.view',
            'upgrade.upgrade.view',
        ], tenant_id=self.tenant_a)
        self.user_b = make_user(uniq('ub'), perms=[
            'equipment_lifecycle.system.view', 'equipment_lifecycle.system.edit',
            'equipment_lifecycle.system.del', 'equipment_lifecycle.system.deactivate',
        ], tenant_id=self.tenant_b)
        self.client_a = make_client(self.user_a)
        self.client_b = make_client(self.user_b)
        self.system_b = make_system(self.user_b, tenant_id=self.tenant_b,
                                    name='B租户系统')

    def test_list_does_not_leak_other_tenant_systems(self):
        rows = inner(self.client_a.get(SYSTEMS_URL + '/'))['data']
        self.assertNotIn(self.system_b.id, [s['id'] for s in rows])

    def test_detail_cross_tenant_rejected(self):
        res = self.client_a.get('%s/%s/' % (SYSTEMS_URL, self.system_b.id))
        assert_no_500(res, 'cross tenant system detail')
        self.assertTrue(res.json().get('error'))

    def test_update_cross_tenant_rejected_and_unchanged(self):
        res = put_json(self.client_a, '%s/%s/' % (SYSTEMS_URL, self.system_b.id),
                       {'name': '被篡改'})
        assert_no_500(res, 'cross tenant system update')
        self.assertTrue(res.json().get('error'))
        self.system_b.refresh_from_db()
        self.assertEqual(self.system_b.name, 'B租户系统')

    def test_delete_cross_tenant_rejected(self):
        res = self.client_a.delete('%s/%s/' % (SYSTEMS_URL, self.system_b.id))
        assert_no_500(res, 'cross tenant system delete')
        self.assertTrue(res.json().get('error'))
        self.assertTrue(LifecycleSystem.objects.filter(pk=self.system_b.id).exists())

    def test_deactivate_cross_tenant_rejected(self):
        res = post_json(self.client_a, '%s/%s/active/' % (SYSTEMS_URL, self.system_b.id),
                        {'is_active': False})
        assert_no_500(res, 'cross tenant system deactivate')
        self.assertTrue(res.json().get('error'))
        self.system_b.refresh_from_db()
        self.assertTrue(self.system_b.is_active)

    def test_records_tab_cross_tenant_rejected(self):
        res = self.client_a.get('%s/%s/records/' % (SYSTEMS_URL, self.system_b.id))
        assert_no_500(res, 'cross tenant system records tab')
        self.assertTrue(res.json().get('error'))

    def test_upgrade_records_tab_cross_tenant_rejected(self):
        res = self.client_a.get('%s/%s/upgrade-records/' % (SYSTEMS_URL, self.system_b.id))
        assert_no_500(res, 'cross tenant system upgrade records tab')
        self.assertTrue(res.json().get('error'))


class CrossTenantRecordTests(TestCase):
    """运行处置记录跨租户读写边界。"""

    def setUp(self):
        self.tenant_a = uniq('ta')
        self.tenant_b = uniq('tb')
        perms = ['equipment_lifecycle.operation_record.view',
                 'equipment_lifecycle.operation_record.add',
                 'equipment_lifecycle.operation_record.edit',
                 'equipment_lifecycle.operation_record.progress',
                 'equipment_lifecycle.operation_record.complete',
                 'equipment_lifecycle.operation_record.del']
        self.user_a = make_user(uniq('ua'), perms=perms, tenant_id=self.tenant_a)
        self.user_b = make_user(uniq('ub'), perms=perms, tenant_id=self.tenant_b)
        self.client_a = make_client(self.user_a)
        self.client_b = make_client(self.user_b)
        self.system_b = make_system(self.user_b, tenant_id=self.tenant_b)
        self.record_b = make_record(self.user_b, self.system_b,
                                    tenant_id=self.tenant_b)

    def test_detail_cross_tenant_rejected(self):
        res = self.client_a.get('%s/%s/' % (RECORDS_URL, self.record_b.id))
        assert_no_500(res, 'cross tenant record detail')
        self.assertTrue(res.json().get('error'))

    def test_progress_cross_tenant_rejected(self):
        res = post_json(self.client_a, '%s/%s/progress/' % (RECORDS_URL, self.record_b.id),
                        {'content': '跨租户进展'})
        assert_no_500(res, 'cross tenant record progress')
        self.assertTrue(res.json().get('error'))
        self.assertEqual(self.record_b.progress_records.count(), 0)

    def test_complete_cross_tenant_rejected(self):
        res = post_json(self.client_a, '%s/%s/complete/' % (RECORDS_URL, self.record_b.id),
                        {'summary': '跨租户完成'})
        assert_no_500(res, 'cross tenant record complete')
        self.assertTrue(res.json().get('error'))
        self.record_b.refresh_from_db()
        self.assertEqual(self.record_b.status, 'recorded')

    def test_attachment_upload_cross_tenant_rejected(self):
        res = self.client_a.post(
            '%s/%s/attachments/' % (RECORDS_URL, self.record_b.id),
            {'file': SimpleUploadedFile('x.txt', b'x')})
        assert_no_500(res, 'cross tenant attachment upload')
        self.assertTrue(res.json().get('error'))
        self.assertFalse(EvidenceAttachment.objects.filter(
            module='equipment_lifecycle',
            object_type='el_operation_record',
            object_id=str(self.record_b.id)).exists())

    def test_attachment_download_cross_tenant_rejected(self):
        upload = self.client_b.post(
            '%s/%s/attachments/' % (RECORDS_URL, self.record_b.id),
            {'file': SimpleUploadedFile('b.txt', b'content-b')})
        self.assertFalse(upload.json().get('error'), upload.content[:200])
        att_id = upload.json()['data']['id']
        res = self.client_a.get('%s/%s/attachments/%s/download/'
                                % (RECORDS_URL, self.record_b.id, att_id))
        assert_no_500(res, 'cross tenant attachment download')
        self.assertTrue(res.json().get('error'))

    def test_attachment_delete_cross_tenant_rejected(self):
        upload = self.client_b.post(
            '%s/%s/attachments/' % (RECORDS_URL, self.record_b.id),
            {'file': SimpleUploadedFile('b2.txt', b'content-b2')})
        att_id = upload.json()['data']['id']
        res = self.client_a.delete('%s/%s/attachments/%s/'
                                   % (RECORDS_URL, self.record_b.id, att_id))
        assert_no_500(res, 'cross tenant attachment delete')
        self.assertTrue(res.json().get('error'))
        self.assertFalse(EvidenceAttachment.objects.get(pk=att_id).is_deleted)


class CrossTenantLedgerAndTemplateTests(IsoStorageMixin, TestCase):
    """台账与 Excel 模板跨租户边界。"""

    def setUp(self):
        super().setUp()
        self.tenant_a = uniq('ta')
        self.tenant_b = uniq('tb')
        perms = ['equipment_lifecycle.ledger.view', 'equipment_lifecycle.ledger.add',
                 'equipment_lifecycle.ledger.edit', 'equipment_lifecycle.ledger.del',
                 'equipment_lifecycle.ledger.export',
                 'equipment_lifecycle.ledger_template.view',
                 'equipment_lifecycle.ledger_template.add',
                 'equipment_lifecycle.ledger_template.edit',
                 'equipment_lifecycle.ledger_template.del']
        self.user_a = make_user(uniq('ua'), perms=perms, tenant_id=self.tenant_a)
        self.user_b = make_user(uniq('ub'), perms=perms, tenant_id=self.tenant_b)
        self.client_a = make_client(self.user_a)
        self.client_b = make_client(self.user_b)
        self.system_b = make_system(self.user_b, tenant_id=self.tenant_b)
        self.ledger_b = create_ledger_ok(
            self.client_b, ledger_payload(
                [entry_payload(self.system_b.id, [item_payload()])]))
        self.flow = ExcelTemplateFlowMixin()
        self.flow.client = self.client_b
        self.template_b = self.flow.upload_template()

    def test_ledger_detail_cross_tenant_rejected(self):
        res = self.client_a.get('%s/%s/' % (LEDGER_URL, self.ledger_b['id']))
        assert_no_500(res, 'cross tenant ledger detail')
        self.assertTrue(res.json().get('error'))

    def test_ledger_list_does_not_leak(self):
        rows = inner(self.client_a.get(LEDGER_URL + '/'))['data']
        self.assertNotIn(self.ledger_b['id'], [r['id'] for r in rows])

    def test_ledger_void_cross_tenant_rejected(self):
        res = post_json(self.client_a, '%s/%s/void/' % (LEDGER_URL, self.ledger_b['id']),
                        {'reason': '跨租户作废'})
        assert_no_500(res, 'cross tenant ledger void')
        self.assertTrue(res.json().get('error'))
        row = OperationLedger.objects.get(pk=self.ledger_b['id'])
        self.assertEqual(row.status, 'draft')

    def test_ledger_complete_cross_tenant_rejected(self):
        res = post_json(self.client_a, '%s/%s/complete/' % (LEDGER_URL, self.ledger_b['id']),
                        {})
        assert_no_500(res, 'cross tenant ledger complete')
        self.assertTrue(res.json().get('error'))
        row = OperationLedger.objects.get(pk=self.ledger_b['id'])
        self.assertEqual(row.status, 'draft')

    def test_template_detail_and_bindings_cross_tenant_rejected(self):
        res = self.client_a.get('%s/%s/' % (TPL_URL, self.template_b['id']))
        assert_no_500(res, 'cross tenant template detail')
        self.assertTrue(res.json().get('error'))
        res_put = put_json(self.client_a,
                           '%s/%s/bindings/' % (TPL_URL, self.template_b['id']),
                           {'field_bindings': []})
        assert_no_500(res_put, 'cross tenant template bindings')
        self.assertTrue(res_put.json().get('error'))

    def test_template_publish_and_delete_cross_tenant_rejected(self):
        res = self.client_a.post('%s/%s/publish/' % (TPL_URL, self.template_b['id']))
        assert_no_500(res, 'cross tenant template publish')
        self.assertTrue(res.json().get('error'))
        res_del = self.client_a.delete('%s/%s/' % (TPL_URL, self.template_b['id']))
        assert_no_500(res_del, 'cross tenant template delete')
        self.assertTrue(res_del.json().get('error'))

    def test_template_list_does_not_leak(self):
        rows = inner(self.client_a.get(TPL_URL + '/'))['data']
        self.assertNotIn(self.template_b['id'], [t['id'] for t in rows])


class PermissionEnforcementTests(TestCase):
    """权限后端独立校验：无权限与仅查看用户。"""

    def setUp(self):
        self.tenant = uniq('perm_t')
        self.view_user = make_user(uniq('viewer'), perms=[
            'equipment_lifecycle.system.view',
            'equipment_lifecycle.operation_record.view',
            'equipment_lifecycle.ledger.view',
            'equipment_lifecycle.ledger_template.view',
            'upgrade.upgrade.view',
        ], tenant_id=self.tenant)
        self.no_user = make_user(uniq('noperm'), perms=[], tenant_id=self.tenant)
        self.view_client = make_client(self.view_user)
        self.no_client = make_client(self.no_user)
        self.system = make_system(self.view_user, tenant_id=self.tenant)

    def test_unauthenticated_rejected(self):
        from django.test import Client
        res = Client().get(SYSTEMS_URL + '/')
        self.assertTrue(res.json().get('error'), res.content[:200])

    def test_no_perm_list_rejected_everywhere(self):
        for url in (SYSTEMS_URL + '/', RECORDS_URL + '/', LEDGER_URL + '/',
                    TPL_URL + '/', UPGRADE_URL + '/records/'):
            res = self.no_client.get(url)
            assert_no_500(res, 'no perm GET %s' % url)
            self.assertTrue(res.json().get('error'), (url, res.content[:200]))

    def test_view_only_cannot_write(self):
        payloads = [
            ('POST', SYSTEMS_URL + '/', {'name': 'x'}),
            ('POST', RECORDS_URL + '/', {'record_type': 'abnormal'}),
            ('POST', UPGRADE_URL + '/records/create/',
             {'title': 'x', 'system': self.system.id, 'upgrade_type': '软件升级',
              'upgrade_time': '2026-10-20 10:00:00', 'owner': 'o',
              'upgrade_content': 'c'}),
        ]
        for method, url, payload in payloads:
            res = post_json(self.view_client, url, payload)
            assert_no_500(res, 'view-only write %s' % url)
            self.assertTrue(res.json().get('error'), (url, res.content[:200]))
        res = self.view_client.post(LEDGER_URL + '/', ledger_payload([]))
        assert_no_500(res, 'view-only ledger create')
        self.assertTrue(res.json().get('error'))

    def test_view_only_cannot_upload_attachment(self):
        record = make_record(self.view_user, self.system, tenant_id=self.tenant)
        res = self.view_client.post(
            '%s/%s/attachments/' % (RECORDS_URL, record.id),
            {'file': SimpleUploadedFile('v.txt', b'v')})
        assert_no_500(res, 'view-only attachment upload')
        self.assertTrue(res.json().get('error'))


class AttachmentCrossModuleTests(IsoStorageMixin, TestCase):
    """附件跨模块越权：模块/对象类型强校验。"""

    def setUp(self):
        super().setUp()
        self.tenant = uniq('attm_t')
        self.user = make_user(uniq('attm_user'), perms=[
            'equipment_lifecycle.operation_record.view',
            'equipment_lifecycle.operation_record.edit',
            'equipment_lifecycle.ledger.view',
            'upgrade.upgrade.view',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)
        self.system = make_system(self.user, tenant_id=self.tenant)
        self.record = make_record(self.user, self.system, tenant_id=self.tenant)

    def _orm_attachment(self, module, object_type, object_id, name='f.txt'):
        return EvidenceAttachment.objects.create(
            tenant_id=self.tenant, module=module, object_type=object_type,
            object_id=str(object_id), file_name=name,
            file_path='quality_qa_probe/%s' % uniq('path'), file_size=3,
            file_ext='txt', file_hash_sha256='0' * 64,
            uploaded_by_id=self.user.id, uploaded_by_name='qa',
        )

    def test_upgrade_attachment_not_readable_via_record_endpoint(self):
        upgrade = upgrade_record_row(self.tenant, self.user, system=self.system)
        att = self._orm_attachment('upgrade', 'record', upgrade.id)
        res = self.client.get('%s/%s/attachments/%s/download/'
                              % (RECORDS_URL, self.record.id, att.id))
        assert_no_500(res, 'cross module attachment download')
        self.assertTrue(res.json().get('error'))

    def test_record_attachment_not_deletable_via_ledger_route(self):
        """台账附件路由无法操作记录附件：对象类型强校验 + 归属复核。"""
        att = self._orm_attachment('equipment_lifecycle', 'el_operation_record',
                                   self.record.id)
        ledger_user = make_user(uniq('ledpeer'), perms=[
            'equipment_lifecycle.ledger.view',
            'equipment_lifecycle.ledger.edit',
            'equipment_lifecycle.ledger.add',
        ], tenant_id=self.tenant)
        ledger_client = make_client(ledger_user)
        ledger = create_ledger_ok(
            ledger_client, ledger_payload(
                [entry_payload(self.system.id, [item_payload()])]))
        res = ledger_client.delete('%s/%s/attachments/%s/'
                                   % (LEDGER_URL, ledger['id'], att.id))
        assert_no_500(res, 'cross object-type attachment delete')
        self.assertTrue(res.json().get('error'))
        att.refresh_from_db()
        self.assertFalse(att.is_deleted)

    def test_record_attachment_deletable_by_owner_route(self):
        """对照组：同租户同模块同对象的删除走真实路由成功。"""
        att = self._orm_attachment('equipment_lifecycle', 'el_operation_record',
                                   self.record.id)
        res = self.client.delete('%s/%s/attachments/%s/'
                                 % (RECORDS_URL, self.record.id, att.id))
        assert_no_500(res, 'record attachment delete')
        self.assertFalse(res.json().get('error'), res.content[:200])
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)


class UploadValidationTests(IsoStorageMixin, TestCase):
    """上传校验：非法模板文件必须拒绝且不落盘不落库。"""

    def setUp(self):
        super().setUp()
        self.tenant = uniq('up_t')
        self.user = make_user(uniq('up_user'), perms=[
            'equipment_lifecycle.ledger_template.view',
            'equipment_lifecycle.ledger_template.add',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)

    def test_template_upload_non_xlsx_rejected(self):
        res = self.client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('fake.xlsx', b'this is not a zip'),
            'name': uniq('伪xlsx模板'), 'ledger_type': 'week_month',
        })
        assert_no_500(res, 'template upload non xlsx')
        self.assertTrue(res.json().get('error'), res.content[:200])

    def test_template_upload_missing_file_rejected(self):
        res = self.client.post(TPL_URL + '/', {'name': uniq('无文件模板')})
        assert_no_500(res, 'template upload missing file')
        self.assertTrue(res.json().get('error'))

    def test_record_attachment_missing_file_rejected(self):
        user = make_user(uniq('upatt'), perms=[
            'equipment_lifecycle.operation_record.view',
            'equipment_lifecycle.operation_record.edit',
        ], tenant_id=self.tenant)
        client = make_client(user)
        system = make_system(user, tenant_id=self.tenant)
        record = make_record(user, system, tenant_id=self.tenant)
        res = client.post('%s/%s/attachments/' % (RECORDS_URL, record.id), {})
        assert_no_500(res, 'record attachment missing file')
        self.assertTrue(res.json().get('error'))


class SensitiveLeakageTests(IsoStorageMixin, TestCase):
    """错误信息不得泄露内部路径/堆栈。"""

    FORBIDDEN_MARKERS = ('Traceback', '/data/spug', 'MEDIA_ROOT',
                         'settings.py', '.py", line')

    def setUp(self):
        super().setUp()
        self.tenant = uniq('leak_t')
        self.user = make_user(uniq('leak_user'), perms=[
            'equipment_lifecycle.system.view',
            'equipment_lifecycle.ledger.view',
            'equipment_lifecycle.ledger.export',
            'equipment_lifecycle.ledger_template.view',
            'equipment_lifecycle.ledger_template.add',
            'equipment_lifecycle.ledger_template.edit',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)
        self.flow = ExcelTemplateFlowMixin()
        self.flow.client = self.client

    def _assert_no_leak(self, response, context):
        body = response.content.decode('utf-8', errors='replace')
        for marker in self.FORBIDDEN_MARKERS:
            self.assertNotIn(marker, body,
                             '%s 泄露内部信息: %s' % (context, marker))

    def test_error_responses_do_not_leak_internal_paths(self):
        urls = [
            '%s/%s/' % (SYSTEMS_URL, NONEXISTENT_ID),
            '%s/%s/' % (RECORDS_URL, NONEXISTENT_ID),
            '%s/%s/' % (LEDGER_URL, NONEXISTENT_ID),
            '%s/%s/' % (TPL_URL, NONEXISTENT_ID),
        ]
        for url in urls:
            res = self.client.get(url)
            assert_no_500(res, 'leak probe %s' % url)
            self.assertTrue(res.json().get('error'))
            self._assert_no_leak(res, url)

    def test_missing_file_error_does_not_leak_path(self):
        template = self.flow.upload_template()
        self.flow.save_bindings(template['id'],
                                [self.flow.make_binding('C4', 'PS模块')])
        self.flow.publish(template['id'])
        self.remove_template_files(template['id'])
        res = self.client.post('%s/%s/preview/pdf/' % (TPL_URL, template['id']))
        assert_no_500(res, 'missing file leak probe')
        if 'application/json' not in res.get('Content-Type', ''):
            self.fail('非 JSON 响应: status=%s ctype=%s body=%r' % (
                res.status_code, res.get('Content-Type'), res.content[:300]))
        self.assertTrue(res.json().get('error'))
        self._assert_no_leak(res, 'preview/pdf missing file')


class SuperuserVsNormalTests(TestCase):
    """超管与普通用户的跨租户差异（记录当前设计行为）。"""

    def setUp(self):
        self.tenant_a = uniq('ta')
        self.tenant_b = uniq('tb')
        self.supper = make_user(uniq('super'), perms=[], tenant_id=self.tenant_a,
                                is_supper=True)
        self.normal = make_user(uniq('normal'), perms=[
            'equipment_lifecycle.system.view',
        ], tenant_id=self.tenant_a)
        self.supper_client = make_client(self.supper)
        self.normal_client = make_client(self.normal)
        self.system_b = make_system(
            make_user(uniq('ub'), perms=[], tenant_id=self.tenant_b),
            tenant_id=self.tenant_b, name='B租户系统')

    def test_normal_user_cannot_read_other_tenant(self):
        res = self.normal_client.get('%s/%s/' % (SYSTEMS_URL, self.system_b.id))
        assert_no_500(res, 'normal cross tenant read')
        self.assertTrue(res.json().get('error'))

    def test_supper_user_cross_tenant_behavior_recorded(self):
        """当前设计：超管放行跨租户（见 AGENTS.md 租户隔离例外说明）。"""
        res = self.supper_client.get('%s/%s/' % (SYSTEMS_URL, self.system_b.id))
        assert_no_500(res, 'supper cross tenant read')
        self.assertFalse(res.json().get('error'),
                         '超管跨租户读取被拒：与 AGENTS.md 超管放行设计不符 %s'
                         % res.content[:200])
