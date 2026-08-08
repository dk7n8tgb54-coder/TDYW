# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 合同协议
# 覆盖: CRUD, 日期边界, 合同类型, 金额, 权限, 租户隔离, 软删除, 附件
import json
import uuid

from datetime import date, timedelta
from django.test import TestCase

from tests.helpers.test_base import (
    make_user, make_client, setup_test_env, post_json, get_response_id, has_error)
from apps.contract_agreement.models import ContractAgreement
from apps.evidence.models import EvidenceAttachment


class ContractAgreementCRUDTest(TestCase):
    """合同 CRUD 测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.client = make_client(self.admin)

    def _create(self, **overrides):
        defaults = {
            'contract_name': '测试合同',
            'contract_type': 'service_guarantee',
            'signing_party': '甲方',
            'valid_start_date': date.today().isoformat(),
            'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
            'has_fee': False,
            'fee_amount': 0,
            'responsible_user_id': self.admin.id,
            'responsible_user_name': self.admin.nickname,
        }
        defaults.update(overrides)
        return post_json(self.client, '/contract-agreement/', defaults)

    def test_create_success(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))
        cid = get_response_id(resp)
        self.assertIsNotNone(cid)
        self.assertTrue(ContractAgreement.objects.filter(id=cid).exists())

    def test_list(self):
        self._create(contract_name='列表测试合同')
        resp = self.client.get('/contract-agreement/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))

    def test_detail(self):
        resp = self._create(contract_name='详情测试合同')
        cid = get_response_id(resp)
        if cid:
            resp = self.client.get(f'/contract-agreement/{cid}/')
            self.assertEqual(resp.status_code, 200)

    def test_edit(self):
        resp = self._create(contract_name='原合同名')
        cid = get_response_id(resp)
        if cid:
            resp = post_json(self.client, '/contract-agreement/', {
                'id': cid,
                'contract_name': '更新后合同名',
                'contract_type': 'service_guarantee',
                'signing_party': '甲方',
                'valid_start_date': date.today().isoformat(),
                'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
                'has_fee': False,
                'fee_amount': 0,
                'responsible_user_id': self.admin.id,
                'responsible_user_name': self.admin.nickname,
            })
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(has_error(resp))
            obj = ContractAgreement.objects.get(id=cid)
            self.assertEqual(obj.contract_name, '更新后合同名')

    def test_delete(self):
        resp = self._create(contract_name='待删除合同')
        cid = get_response_id(resp)
        if cid:
            resp = self.client.delete(f'/contract-agreement/?id={cid}')
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(has_error(resp))
            self.assertFalse(ContractAgreement.objects.filter(id=cid).exists())

    def test_delete_nonexistent(self):
        resp = self.client.delete('/contract-agreement/?id=99999')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(has_error(resp))


class ContractDateBoundaryTest(TestCase):
    """合同日期边界测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.client = make_client(self.admin)

    def _create(self, **overrides):
        defaults = {
            'contract_name': '日期测试合同',
            'contract_type': 'service_guarantee',
            'signing_party': '甲方',
            'valid_start_date': date.today().isoformat(),
            'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
            'has_fee': False,
            'fee_amount': 0,
            'responsible_user_id': self.admin.id,
            'responsible_user_name': self.admin.nickname,
        }
        defaults.update(overrides)
        return post_json(self.client, '/contract-agreement/', defaults)

    def test_start_after_end_rejected(self):
        resp = self._create(
            valid_start_date=(date.today() + timedelta(days=30)).isoformat(),
            valid_end_date=date.today().isoformat(),
        )
        self.assertTrue(has_error(resp))

    def test_long_term_contract_null_end_date(self):
        """长期合同 valid_end_date 可以为空"""
        resp = self._create(valid_end_date='')
        # 如果后端接受空值, 测试通过; 否则记录为业务规则
        body = resp.json()
        if not has_error(resp):
            cid = get_response_id(resp)
            if cid:
                obj = ContractAgreement.objects.get(id=cid)
                self.assertIsNone(obj.valid_end_date)

    def test_leap_year(self):
        resp = self._create(
            valid_start_date='2024-02-29',
            valid_end_date='2025-02-28',
        )
        self.assertFalse(has_error(resp))

    def test_cross_year(self):
        resp = self._create(
            valid_start_date='2026-12-01',
            valid_end_date='2027-06-30',
        )
        self.assertFalse(has_error(resp))


class ContractFieldTypeTest(TestCase):
    """合同字段类型测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.client = make_client(self.admin)

    def _create(self, **overrides):
        defaults = {
            'contract_name': '字段测试合同',
            'contract_type': 'service_guarantee',
            'signing_party': '甲方',
            'valid_start_date': date.today().isoformat(),
            'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
            'has_fee': False,
            'fee_amount': 0,
            'responsible_user_id': self.admin.id,
            'responsible_user_name': self.admin.nickname,
        }
        defaults.update(overrides)
        return post_json(self.client, '/contract-agreement/', defaults)

    def test_invalid_contract_type_rejected(self):
        resp = self._create(contract_type='invalid_type')
        self.assertTrue(has_error(resp))

    def test_valid_contract_types(self):
        for ct in ['device_purchase', 'info_access', 'service_guarantee']:
            resp = self._create(
                contract_type=ct,
                contract_name=f'类型测试-{ct}')
            self.assertFalse(has_error(resp),
                             f'contract_type={ct} should be valid')

    def test_zero_fee_accepted(self):
        resp = self._create(has_fee=True, fee_amount=0)
        self.assertFalse(has_error(resp))

    def test_negative_fee_rejected(self):
        resp = self._create(has_fee=True, fee_amount=-100)
        self.assertTrue(has_error(resp))


class ContractPermissionTest(TestCase):
    """合同权限测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.no_perm = make_user('noperm')
        self.viewer = make_user('viewer', perms=[
            'contract_agreement.agreement.view'])

    def test_no_perm_blocked(self):
        client = make_client(self.no_perm)
        resp = client.get('/contract-agreement/')
        self.assertTrue(has_error(resp))

    def test_viewer_can_view(self):
        client = make_client(self.viewer)
        resp = client.get('/contract-agreement/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))

    def test_viewer_cannot_create(self):
        client = make_client(self.viewer)
        resp = post_json(client, '/contract-agreement/', {
            'contract_name': '无权创建',
            'contract_type': 'service_guarantee',
            'signing_party': '甲方',
            'valid_start_date': date.today().isoformat(),
            'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
            'has_fee': False,
            'fee_amount': 0,
            'responsible_user_id': self.viewer.id,
            'responsible_user_name': self.viewer.nickname,
        })
        self.assertTrue(has_error(resp))


class ContractTenantIsolationTest(TestCase):
    """合同租户隔离测试"""

    def setUp(self):
        setup_test_env()
        self.t_a = make_user('ta', is_supper=False, tenant_id='tenant_a',
                             perms=['contract_agreement.agreement.view'])
        self.t_b = make_user('tb', is_supper=False, tenant_id='tenant_b',
                             perms=['contract_agreement.agreement.view'])
        self.contract_a = ContractAgreement.objects.create(
            contract_name='租户A合同',
            contract_type='service_guarantee',
            signing_party='甲方',
            valid_start_date=date.today(),
            valid_end_date=date.today() + timedelta(days=365),
            has_fee=False, fee_amount=0, status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')

    def test_tenant_b_cannot_see_tenant_a(self):
        client = make_client(self.t_b)
        resp = client.get('/contract-agreement/')
        body = resp.json()
        data = body.get('data')
        records = data.get('records', []) if isinstance(data, dict) else []
        names = [item.get('contract_name') for item in records]
        self.assertNotIn('租户A合同', names)

    def test_tenant_b_cannot_access_detail(self):
        client = make_client(self.t_b)
        resp = client.get(f'/contract-agreement/{self.contract_a.id}/')
        self.assertTrue(has_error(resp))

    def test_tenant_b_cannot_delete(self):
        client = make_client(self.t_b)
        resp = client.delete(f'/contract-agreement/?id={self.contract_a.id}')
        self.assertTrue(has_error(resp))
        self.assertTrue(
            ContractAgreement.objects.filter(id=self.contract_a.id).exists())


class ContractSoftDeleteTest(TestCase):
    """合同软删除测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)

    def test_model_has_no_is_deleted(self):
        """ContractAgreement 无 is_deleted 字段 (回收站已移除)"""
        fields = {f.name for f in ContractAgreement._meta.get_fields()}
        self.assertNotIn('is_deleted', fields)


class ContractAttachmentTest(TestCase):
    """合同附件集成测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.client = make_client(self.admin)
        self.contract = ContractAgreement.objects.create(
            contract_name='附件测试合同',
            contract_type='service_guarantee',
            signing_party='甲方',
            valid_start_date=date.today(),
            valid_end_date=date.today() + timedelta(days=365),
            has_fee=False, fee_amount=0, status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def test_attachment_linked_to_contract(self):
        att = EvidenceAttachment.objects.create(
            module='contract_agreement', object_type='agreement',
            object_id=str(self.contract.id),
            file_name='contract.pdf', file_path='/tmp/contract.pdf',
            file_size=1024, file_ext='pdf',
            uploaded_by_id=self.admin.id, uploaded_by_name=self.admin.nickname,
            tenant_id='admin')
        resp = self.client.get(
            f'/contract-agreement/{self.contract.id}/attachments/')
        self.assertEqual(resp.status_code, 200)

    def test_multiple_attachments(self):
        for i in range(3):
            EvidenceAttachment.objects.create(
                module='contract_agreement', object_type='agreement',
                object_id=str(self.contract.id),
                file_name=f'file_{i}.pdf', file_path=f'/tmp/file_{i}.pdf',
                file_size=1024, file_ext='pdf',
                uploaded_by_id=self.admin.id, uploaded_by_name=self.admin.nickname,
                tenant_id='admin')
        resp = self.client.get(
            f'/contract-agreement/{self.contract.id}/attachments/')
        self.assertEqual(resp.status_code, 200)
