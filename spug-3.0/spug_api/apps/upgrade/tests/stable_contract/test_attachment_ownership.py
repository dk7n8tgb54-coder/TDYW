# -*- coding: utf-8 -*-
"""升级模块附件跨模块越权回归测试（stable_contract）

背景：
    `apps/upgrade/views/upload.py` 的下载 / 预览地址 / 删除入口此前把客户端传入的
    附件 ID 直接透传给 AttachmentService，而服务层只按租户过滤，导致持有
    `upgrade.upgrade.*` 权限的用户可枚举自增附件 ID，越权下载、预览、删除同租户
    其他模块（执照 / 批复 / 合同 / 干扰 / 协作任务等）的附件。

修复后契约：
    归属校验下沉到 AttachmentService，upgrade 端点只放行
    module='upgrade' / object_type='record' 的附件。
"""
import os
import shutil
import tempfile

from django.test import TestCase

from apps.evidence.models import EvidenceAttachment
from apps.upgrade.models import UpgradeRecord
from apps.utils.test_helpers import make_user, make_client, setup_test_env

UPGRADE_MODULE = 'upgrade'
UPGRADE_OBJECT_TYPE = 'record'
# 同租户的其他模块附件（模拟被枚举到的越权目标）
OTHER_MODULE = 'radio_license'
OTHER_OBJECT_TYPE = 'license'


class UpgradeAttachmentOwnershipTest(TestCase):
    """升级接口不得触达其他模块的附件，同时必须正常服务本模块附件"""

    def setUp(self):
        setup_test_env(self)
        self.media = tempfile.mkdtemp(prefix='upgrade_attachment_')
        self.addCleanup(shutil.rmtree, self.media, True)

        settings_ctx = self.settings(
            MEDIA_ROOT=self.media,
            KKFILEVIEW_API_URL='http://kkfileview.test',
            KKFILEVIEW_SERVER_URL='http://spug-api.test',
        )
        settings_ctx.enable()
        self.addCleanup(settings_ctx.disable)

        self.user = make_user('upg_att_owner', [
            'upgrade.upgrade.view', 'upgrade.upgrade.add', 'upgrade.upgrade.edit',
        ])
        self.client_auth = make_client(self.user)

        self.record = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id,
            title='升级附件归属测试',
            system='测试系统',
            upgrade_type='软件升级',
            created_by=self.user,
        )

    def _make_attachment(self, module, object_type, object_id, file_name='proof.pdf'):
        rel = os.path.join(module, self.user.tenant_id, '202601',
                           f'{object_type}_{object_id}', file_name)
        abs_path = os.path.join(self.media, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(b'pdf-body')
        return EvidenceAttachment.objects.create(
            tenant_id=self.user.tenant_id,
            module=module,
            object_type=object_type,
            object_id=str(object_id),
            file_name=file_name,
            file_path=rel,
            file_size=8,
            file_ext='.pdf',
            file_hash_sha256='a' * 64,
            uploaded_by_id=self.user.id,
            uploaded_by_name=self.user.nickname,
        )

    @staticmethod
    def _is_deleted(attachment_id):
        return EvidenceAttachment.objects.all_with_deleted().get(pk=attachment_id).is_deleted

    # ---------------- 正向：本模块附件正常可用 ----------------

    def test_own_attachment_download_ok(self):
        att = self._make_attachment(UPGRADE_MODULE, UPGRADE_OBJECT_TYPE, self.record.id)
        resp = self.client_auth.get(f'/upgrade/attachments/{att.id}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            resp['Content-Disposition'].startswith('attachment'),
            '本模块附件应返回文件流而非业务错误',
        )

    def test_own_attachment_preview_url_ok(self):
        att = self._make_attachment(UPGRADE_MODULE, UPGRADE_OBJECT_TYPE, self.record.id)
        resp = self.client_auth.get(f'/upgrade/attachments/{att.id}/preview-url/')
        data = resp.json()
        self.assertFalse(data.get('error'), f'本模块附件应可生成预览地址: {data}')
        self.assertIn('preview_url', data.get('data', {}))

    # ---------------- 反向：其他模块附件一律拒绝 ----------------

    def test_other_module_attachment_download_rejected(self):
        att = self._make_attachment(OTHER_MODULE, OTHER_OBJECT_TYPE, 999)
        resp = self.client_auth.get(f'/upgrade/attachments/{att.id}/download/')
        data = resp.json()
        self.assertTrue(data.get('error'), '其他模块附件不应可下载')
        self.assertEqual(data.get('error'), '附件不存在或无权限访问')

    def test_other_module_attachment_preview_url_rejected(self):
        att = self._make_attachment(OTHER_MODULE, OTHER_OBJECT_TYPE, 999)
        resp = self.client_auth.get(f'/upgrade/attachments/{att.id}/preview-url/')
        data = resp.json()
        self.assertTrue(data.get('error'), '其他模块附件不应可生成预览地址')
        self.assertEqual(data.get('error'), '附件不存在或无权限访问')

    def test_other_module_attachment_delete_rejected(self):
        att = self._make_attachment(OTHER_MODULE, OTHER_OBJECT_TYPE, 999)
        resp = self.client_auth.delete(f'/upgrade/attachments/?id={att.id}')
        data = resp.json()
        self.assertTrue(data.get('error'), '其他模块附件不应可被删除')
        self.assertEqual(data.get('error'), '附件不存在或无权限删除')
        self.assertFalse(self._is_deleted(att.id), '被拒绝的删除不应改动附件')

    def test_own_attachment_delete_ok(self):
        """正向对照：本模块附件仍可正常软删除"""
        att = self._make_attachment(UPGRADE_MODULE, UPGRADE_OBJECT_TYPE, self.record.id)
        resp = self.client_auth.delete(f'/upgrade/attachments/?id={att.id}')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertTrue(self._is_deleted(att.id), '本模块附件应被软删除')
