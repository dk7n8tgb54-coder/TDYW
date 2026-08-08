# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 附件系统集成
# 覆盖: EvidenceAttachment 多态, 伪造 object_id, 跨租户, 软删除,
#        DB/物理一致性, 执照/合同附件集成
import os
import tempfile
import shutil

from datetime import date, timedelta
from django.test import TestCase

from tests.helpers.test_base import (
    make_user, make_client, setup_test_env)
from apps.evidence.models import EvidenceAttachment
from apps.radio_license.models import RadioLicense
from apps.contract_agreement.models import ContractAgreement
from libs.tenant_utils import apply_tenant_filter


def _make_attachment(user, module='radio_license', object_id='1',
                     file_name='test.pdf', tmp_dir='/tmp'):
    return EvidenceAttachment.objects.create(
        module=module,
        object_type='main',
        object_id=str(object_id),
        file_name=file_name,
        file_path=os.path.join(tmp_dir, file_name),
        file_size=1024,
        file_ext='pdf',
        uploaded_by_id=user.id,
        uploaded_by_name=user.nickname,
        tenant_id=user.tenant_id,
    )


class EvidenceAttachmentModelTest(TestCase):
    """EvidenceAttachment 模型测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='evidence_test_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_attachment(self):
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        self.assertEqual(att.module, 'radio_license')
        self.assertEqual(att.object_id, '1')
        self.assertFalse(att.is_deleted)

    def test_multiple_attachments_same_object(self):
        for i in range(3):
            _make_attachment(self.admin, object_id='100',
                             file_name=f'file_{i}.pdf',
                             tmp_dir=self.tmp_dir)
        count = EvidenceAttachment.objects.filter(
            module='radio_license', object_id='100').count()
        self.assertEqual(count, 3)

    def test_same_filename_different_objects(self):
        _make_attachment(self.admin, module='radio_license',
                         object_id='1', file_name='same.pdf',
                         tmp_dir=self.tmp_dir)
        _make_attachment(self.admin, module='contract_agreement',
                         object_id='2', file_name='same.pdf',
                         tmp_dir=self.tmp_dir)
        count = EvidenceAttachment.objects.filter(file_name='same.pdf').count()
        self.assertEqual(count, 2)


class EvidenceForgedObjectIDTest(TestCase):
    """伪造 object_id 测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='forged_test_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_forged_module_accepted(self):
        """伪造 module 被接受 (多态设计, 不验证白名单)"""
        att = _make_attachment(
            self.admin, module='nonexistent_module',
            object_id='999', tmp_dir=self.tmp_dir)
        self.assertEqual(att.module, 'nonexistent_module')

    def test_nonexistent_object_id_accepted(self):
        """附件可绑定到不存在的对象 (无 FK 约束)"""
        att = _make_attachment(
            self.admin, module='radio_license',
            object_id='999999', tmp_dir=self.tmp_dir)
        self.assertIsNotNone(att.id)


class EvidenceCrossTenantTest(TestCase):
    """附件跨租户测试"""

    def setUp(self):
        setup_test_env()
        self.t_a = make_user('ta', is_supper=False, tenant_id='tenant_a',
                             perms=['radio_license.license.view'])
        self.t_b = make_user('tb', is_supper=False, tenant_id='tenant_b',
                             perms=['radio_license.license.view'])
        self.tmp_dir = tempfile.mkdtemp(prefix='cross_tenant_att_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_cross_tenant_isolation(self):
        """租户B看不到租户A的附件"""
        lic = RadioLicense.objects.create(
            station_name='租户A台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')
        att = _make_attachment(
            self.t_a, module='radio_license',
            object_id=str(lic.id), tmp_dir=self.tmp_dir)
        qs_b = apply_tenant_filter(
            EvidenceAttachment.objects.all(), self.t_b)
        self.assertFalse(qs_b.filter(id=att.id).exists())

    def test_own_tenant_visible(self):
        """租户A看到自己的附件"""
        lic = RadioLicense.objects.create(
            station_name='租户A台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')
        att = _make_attachment(
            self.t_a, module='radio_license',
            object_id=str(lic.id), tmp_dir=self.tmp_dir)
        qs_a = apply_tenant_filter(
            EvidenceAttachment.objects.all(), self.t_a)
        self.assertTrue(qs_a.filter(id=att.id).exists())


class EvidenceSoftDeleteTest(TestCase):
    """附件软删除测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='soft_del_att_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_default_not_deleted(self):
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        self.assertFalse(att.is_deleted)

    def test_soft_delete_sets_flag(self):
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        att.is_deleted = True
        att.save(update_fields=['is_deleted'])
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)

    def test_soft_deleted_not_in_normal_query(self):
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        att.is_deleted = True
        att.save(update_fields=['is_deleted'])
        active = EvidenceAttachment.objects.filter(
            is_deleted=False, module='radio_license')
        self.assertFalse(active.filter(id=att.id).exists())


class EvidenceConsistencyTest(TestCase):
    """附件一致性测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='consistency_att_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_db_record_exists_file_missing(self):
        att = _make_attachment(
            self.admin, module='radio_license',
            object_id='1', file_name='missing.pdf',
            tmp_dir=self.tmp_dir)
        if os.path.exists(att.file_path):
            os.remove(att.file_path)
        self.assertFalse(os.path.exists(att.file_path))
        self.assertTrue(EvidenceAttachment.objects.filter(id=att.id).exists())

    def test_hash_fields_exist(self):
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        self.assertTrue(hasattr(att, 'file_hash_sha256'))
        self.assertTrue(hasattr(att, 'file_hash_md5'))


class EvidenceIntegrationWithLicenseTest(TestCase):
    """执照附件集成测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='license_att_')
        self.license = RadioLicense.objects.create(
            station_name='附件集成台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_attachment_linked_to_license(self):
        att = _make_attachment(
            self.admin, module='radio_license',
            object_id=str(self.license.id),
            file_name='license_doc.pdf',
            tmp_dir=self.tmp_dir)
        linked = EvidenceAttachment.objects.filter(
            module='radio_license', object_id=str(self.license.id))
        self.assertEqual(linked.count(), 1)

    def test_delete_license_keeps_attachment(self):
        """删除执照后附件记录残留 (多态设计, 无 FK)"""
        att = _make_attachment(
            self.admin, module='radio_license',
            object_id=str(self.license.id),
            file_name='orphan.pdf',
            tmp_dir=self.tmp_dir)
        att_id = att.id
        self.license.delete()
        self.assertTrue(
            EvidenceAttachment.objects.filter(id=att_id).exists())


class EvidenceIntegrationWithContractTest(TestCase):
    """合同附件集成测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='contract_att_')
        self.contract = ContractAgreement.objects.create(
            contract_name='附件集成合同',
            contract_type='service_guarantee',
            signing_party='甲方',
            valid_start_date=date.today(),
            valid_end_date=date.today() + timedelta(days=365),
            has_fee=False, fee_amount=0, status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_contract_attachment(self):
        _make_attachment(
            self.admin, module='contract_agreement',
            object_id=str(self.contract.id),
            file_name='contract.pdf',
            tmp_dir=self.tmp_dir)
        count = EvidenceAttachment.objects.filter(
            module='contract_agreement',
            object_id=str(self.contract.id)).count()
        self.assertEqual(count, 1)
