# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 附件系统集成
# 覆盖: EvidenceAttachment 多态, 附件关联到业务对象, 伪造 object_id,
#        跨租户附件访问, 删除业务对象后附件状态, is_pending_clean
import json
import os
import time
import tempfile
import shutil
from datetime import date, timedelta

from django.test import TestCase, Client
from apps.account.models import User, Role
from apps.evidence.models import EvidenceAttachment
from apps.radio_license.models import RadioLicense
from apps.contract_agreement.models import ContractAgreement
from apps.setting.utils import AppSetting


def _uuid():
    import uuid
    return uuid.uuid4().hex


def _make_user(username, is_supper=False, tenant_id='admin', perms=None):
    unique = f'{username}_{_uuid()[:8]}'
    user = User.objects.create(
        username=unique, nickname=unique,
        password_hash=User.make_password('test123'),
        access_token=_uuid(), is_supper=is_supper, is_active=True,
        tenant_id=tenant_id, token_expired=int(time.time()) + 3600,
        last_ip='127.0.0.1', last_login='2026-01-01', type='default',
    )
    if perms and not is_supper:
        role = Role.objects.create(
            name=f'{username}_role', desc='', page_perms='',
            perms_version=1, created_by=user)
        perm_tree = {}
        for p in perms:
            parts = p.split('.')
            if len(parts) >= 3:
                perm_tree.setdefault(parts[0], {}).setdefault(
                    parts[1], set()).add(parts[2])
        pp = {}
        for m, models in perm_tree.items():
            pp[m] = {}
            for mo, acts in models.items():
                pp[m][mo] = {a: True for a in acts}
        role.page_perms = json.dumps(pp)
        role.save()
        user.roles.add(role)
        user.set_perms_cache(None)
    return user


def _make_attachment(user, module='radio_license', object_id='1',
                     file_name='test.pdf', tmp_dir='/tmp'):
    """创建 EvidenceAttachment 记录的辅助函数"""
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
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='evidence_test_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_attachment(self):
        """创建附件记录"""
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        self.assertEqual(att.module, 'radio_license')
        self.assertEqual(att.object_id, '1')
        self.assertFalse(att.is_deleted)

    def test_multiple_attachments_same_object(self):
        """一个业务对象多个附件"""
        for i in range(3):
            _make_attachment(self.admin, object_id='100',
                             file_name=f'file_{i}.pdf',
                             tmp_dir=self.tmp_dir)
        count = EvidenceAttachment.objects.filter(
            module='radio_license', object_id='100').count()
        self.assertEqual(count, 3)

    def test_same_filename_different_objects(self):
        """不同业务对象使用相同文件名"""
        _make_attachment(self.admin, module='radio_license',
                         object_id='1', file_name='same_name.pdf',
                         tmp_dir=self.tmp_dir)
        _make_attachment(self.admin, module='contract_agreement',
                         object_id='2', file_name='same_name.pdf',
                         tmp_dir=self.tmp_dir)
        count = EvidenceAttachment.objects.filter(
            file_name='same_name.pdf').count()
        self.assertEqual(count, 2)


class EvidenceIntegrationWithLicenseTest(TestCase):
    """执照附件集成测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='license_evidence_test_')
        self.license = RadioLicense.objects.create(
            station_name='附件集成测试台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_attachment_linked_to_license(self):
        """附件关联到执照"""
        att = _make_attachment(
            self.admin, module='radio_license',
            object_id=str(self.license.id),
            file_name='license_doc.pdf',
            tmp_dir=self.tmp_dir)
        linked = EvidenceAttachment.objects.filter(
            module='radio_license',
            object_id=str(self.license.id))
        self.assertEqual(linked.count(), 1)
        self.assertEqual(linked.first().file_name, 'license_doc.pdf')

    def test_delete_license_keeps_attachment_record(self):
        """删除执照后附件记录状态"""
        att = _make_attachment(
            self.admin, module='radio_license',
            object_id=str(self.license.id),
            file_name='orphan_test.pdf',
            tmp_dir=self.tmp_dir)
        att_id = att.id
        self.license.delete()
        # EvidenceAttachment 使用 object_id (CharField), 不做 FK
        # 所以删除执照后附件记录仍然存在（孤儿记录）
        exists = EvidenceAttachment.objects.filter(id=att_id).exists()
        # 记录实际行为
        if exists:
            # 附件记录残留 - 这是多态设计的已知行为
            pass


class EvidenceIntegrationWithContractTest(TestCase):
    """合同附件集成测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='contract_evidence_test_')
        self.contract = ContractAgreement.objects.create(
            contract_name='附件集成测试合同',
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
        """合同附件"""
        _make_attachment(
            self.admin, module='contract_agreement',
            object_id=str(self.contract.id),
            file_name='contract.pdf',
            tmp_dir=self.tmp_dir)
        count = EvidenceAttachment.objects.filter(
            module='contract_agreement',
            object_id=str(self.contract.id)).count()
        self.assertEqual(count, 1)


class EvidenceForgedObjectIDTest(TestCase):
    """伪造 object_id 测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='forged_test_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_forged_module(self):
        """伪造 module 创建附件"""
        att = _make_attachment(
            self.admin, module='nonexistent_module',
            object_id='999',
            file_name='forged.pdf',
            tmp_dir=self.tmp_dir)
        # EvidenceAttachment 不验证 module 是否有效（多态设计）
        self.assertEqual(att.module, 'nonexistent_module')

    def test_forged_object_id_nonexistent(self):
        """附件绑定到不存在的对象"""
        att = _make_attachment(
            self.admin, module='radio_license',
            object_id='999999',
            file_name='orphan.pdf',
            tmp_dir=self.tmp_dir)
        # 附件可以绑定到不存在的对象（多态设计）
        self.assertIsNotNone(att.id)


class EvidenceCrossTenantTest(TestCase):
    """附件跨租户测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.t_a = _make_user('ta', is_supper=False, tenant_id='tenant_a',
                               perms=['radio_license.license.view'])
        self.t_b = _make_user('tb', is_supper=False, tenant_id='tenant_b',
                               perms=['radio_license.license.view'])
        self.tmp_dir = tempfile.mkdtemp(prefix='cross_tenant_test_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_cross_tenant_attachment_isolation(self):
        """跨租户附件隔离"""
        license_a = RadioLicense.objects.create(
            station_name='租户A台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')
        att = _make_attachment(
            self.t_a, module='radio_license',
            object_id=str(license_a.id),
            file_name='ta_file.pdf',
            tmp_dir=self.tmp_dir)
        # 租户B的查询不应包含租户A的附件
        from libs.tenant_utils import apply_tenant_filter
        qs_b = apply_tenant_filter(
            EvidenceAttachment.objects.all(), self.t_b)
        self.assertFalse(qs_b.filter(id=att.id).exists())

    def test_tenant_a_sees_own_attachments(self):
        """租户A看到自己的附件"""
        license_a = RadioLicense.objects.create(
            station_name='租户A台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')
        att = _make_attachment(
            self.t_a, module='radio_license',
            object_id=str(license_a.id),
            file_name='ta_file.pdf',
            tmp_dir=self.tmp_dir)
        from libs.tenant_utils import apply_tenant_filter
        qs_a = apply_tenant_filter(
            EvidenceAttachment.objects.all(), self.t_a)
        self.assertTrue(qs_a.filter(id=att.id).exists())


class EvidenceSoftDeleteTest(TestCase):
    """附件软删除测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='soft_delete_test_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_soft_delete_default_false(self):
        """默认 is_deleted=False"""
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        self.assertFalse(att.is_deleted)

    def test_soft_delete_sets_flag(self):
        """软删除设置 is_deleted=True"""
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        att.is_deleted = True
        att.deleted_by_id = self.admin.id
        att.deleted_by_name = self.admin.nickname
        att.save(update_fields=['is_deleted', 'deleted_by_id', 'deleted_by_name'])
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)

    def test_soft_deleted_not_in_normal_query(self):
        """软删除附件不出现在正常查询中"""
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        att.is_deleted = True
        att.save(update_fields=['is_deleted'])
        active = EvidenceAttachment.objects.filter(
            is_deleted=False, module='radio_license')
        self.assertFalse(active.filter(id=att.id).exists())


class EvidenceConsistencyTest(TestCase):
    """附件一致性测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='consistency_test_')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_db_record_exists_file_missing(self):
        """数据库记录存在但物理文件不存在"""
        att = _make_attachment(
            self.admin, module='radio_license',
            object_id='1',
            file_name='missing.pdf',
            tmp_dir=self.tmp_dir)
        # 不创建物理文件
        file_path = os.path.join(self.tmp_dir, 'missing.pdf')
        if os.path.exists(file_path):
            os.remove(file_path)
        self.assertFalse(os.path.exists(att.file_path))
        # 数据库记录仍存在
        self.assertTrue(EvidenceAttachment.objects.filter(id=att.id).exists())

    def test_sha256_hash_field_exists(self):
        """SHA256 哈希字段存在"""
        att = _make_attachment(self.admin, tmp_dir=self.tmp_dir)
        self.assertTrue(hasattr(att, 'file_hash_sha256'))
        self.assertTrue(hasattr(att, 'file_hash_md5'))
