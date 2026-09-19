# -*- coding: utf-8 -*-
"""配置档案附件（attachment 动态字段）稳定契约测试。

按项目附件范式要求，覆盖：
- 上传归属 module/object_type/object_id 正确落库；
- 配置值引用本系统附件通过，引用跨模块/跨租户附件被拒；
- 跨模块附件访问/删除被拒绝（稳定契约）。
"""
import tempfile
import time

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.equipment_lifecycle.models import SystemConfigValue
from apps.evidence.models import EvidenceAttachment

from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS,
    make_client, make_field, make_system, make_user,
)


def make_evidence_user(username, tenant_id='t1'):
    from apps.account.models import User
    return User.objects.create(
        username=username, nickname=username, password_hash='x', is_active=True,
        access_token=(username * 10)[:32], token_expired=int(time.time()) + 3600,
        last_login='2026-01-01', last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='el_att_test_'))
class ConfigAttachmentTest(TestCase):
    def setUp(self):
        self.admin = make_user('att_admin', ALL_CONFIG_PERMS, tenant_id='t1')
        self.client = make_client(self.admin)
        self.system = make_system(self.admin, tenant_id='t1')
        self.attachment_field = make_field(
            self.system, self.admin, tenant_id='t1', field_code='topology_files',
            display_name='拓扑附件', field_type='attachment')

    def _upload(self, system_id=None, name='topo.png'):
        target = system_id or self.system.id
        return self.client.post(
            f'/equipment-lifecycle/systems/{target}/config/attachments/',
            {'file': SimpleUploadedFile(name, b'file-bytes', content_type='image/png')})

    def test_upload_belongs_to_system_config(self):
        resp = self._upload()
        self.assertFalse(resp.json().get('error'), resp.content)
        att = EvidenceAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertEqual(att.module, 'equipment_lifecycle')
        self.assertEqual(att.object_type, 'el_system_config')
        self.assertEqual(att.object_id, str(self.system.id))
        self.assertEqual(att.tenant_id, 't1')

    def test_attachment_value_reference_valid(self):
        resp = self._upload()
        att_id = resp.json()['data']['id']
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(self.attachment_field.id): [att_id]}},
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertTrue(SystemConfigValue.objects.filter(
            system=self.system, field=self.attachment_field).exists())

    def test_attachment_value_reference_cross_module_rejected(self):
        """跨模块附件 ID 引用被拒（稳定契约）。"""
        other_user = make_evidence_user('att_other_owner', tenant_id='t1')
        foreign = EvidenceAttachment.objects.create(
            tenant_id='t1', module='contract_agreement', object_type='agreement',
            object_id='999', file_name='x.png', file_path='contract_agreement/t1/x/x.png',
            file_size=10, file_ext='.png', uploaded_by_id=other_user.id,
            uploaded_by_name='x')
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(self.attachment_field.id): [foreign.id]}},
                               content_type='application/json')
        self.assertIn('附件不存在', resp.json()['error'])

    def test_attachment_value_reference_cross_tenant_rejected(self):
        outsider_admin = make_user('att_t2_admin', ALL_CONFIG_PERMS, tenant_id='t2')
        foreign = EvidenceAttachment.objects.create(
            tenant_id='t2', module='equipment_lifecycle', object_type='el_system_config',
            object_id='1', file_name='y.png', file_path='equipment_lifecycle/t2/x/y.png',
            file_size=10, file_ext='.png', uploaded_by_id=outsider_admin.id,
            uploaded_by_name='y')
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(self.attachment_field.id): [foreign.id]}},
                               content_type='application/json')
        self.assertIn('附件不存在', resp.json()['error'])

    def test_cross_tenant_upload_denied(self):
        outsider = make_user('att_t2_up', ALL_CONFIG_PERMS, tenant_id='t2')
        client = make_client(outsider)
        resp = client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/config/attachments/',
            {'file': SimpleUploadedFile('z.png', b'z', content_type='image/png')})
        self.assertEqual(resp.json().get('error'), '系统不存在')

    def test_cross_module_delete_denied(self):
        """跨模块附件删除被拒（稳定契约）。"""
        other_user = make_evidence_user('att_del_owner', tenant_id='t1')
        foreign = EvidenceAttachment.objects.create(
            tenant_id='t1', module='radio_license', object_type='license',
            object_id='1', file_name='w.png', file_path='radio_license/t1/x/w.png',
            file_size=10, file_ext='.png', uploaded_by_id=other_user.id,
            uploaded_by_name='w')
        resp = self.client.delete(
            f'/equipment-lifecycle/systems/{self.system.id}/config/attachments/{foreign.id}/')
        self.assertIn('附件不存在', resp.json()['error'])
        self.assertFalse(
            EvidenceAttachment.objects.get(pk=foreign.id).is_deleted)

    def test_cross_module_download_denied(self):
        other_user = make_evidence_user('att_dl_owner', tenant_id='t1')
        foreign = EvidenceAttachment.objects.create(
            tenant_id='t1', module='radio_license', object_type='license',
            object_id='1', file_name='v.png', file_path='radio_license/t1/x/v.png',
            file_size=10, file_ext='.png', uploaded_by_id=other_user.id,
            uploaded_by_name='v')
        resp = self.client.get(
            f'/equipment-lifecycle/systems/{self.system.id}/config/attachments/{foreign.id}/download/')
        self.assertIn('附件不存在', resp.json()['error'])

    def test_own_attachment_download_allowed(self):
        resp = self._upload()
        att_id = resp.json()['data']['id']
        resp = self.client.get(
            f'/equipment-lifecycle/systems/{self.system.id}/config/attachments/{att_id}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.streaming)
        self.assertEqual(b''.join(resp.streaming_content), b'file-bytes')

    def test_own_attachment_soft_delete(self):
        resp = self._upload()
        att_id = resp.json()['data']['id']
        resp = self.client.delete(
            f'/equipment-lifecycle/systems/{self.system.id}/config/attachments/{att_id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 默认管理器过滤软删除记录，用 all_with_deleted 验证留痕
        att = EvidenceAttachment.objects.all_with_deleted().get(pk=att_id)
        self.assertTrue(att.is_deleted)
