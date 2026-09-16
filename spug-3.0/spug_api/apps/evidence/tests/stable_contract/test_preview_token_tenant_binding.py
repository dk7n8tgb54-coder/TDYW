# -*- coding: utf-8 -*-
"""preview_token 租户绑定 stable_contract 测试

背景（超管跨租户预览必失败）：
    get_preview_url 早期把 token 的 tenant 绑定为"查看者租户"。超管/全局管理员
    因 apply_tenant_filter 放行可以取得跨租户附件的预览地址，但回调
    preview_file_response 严格比对"token 租户 == 附件租户"，导致超管跨租户
    预览必然被拒；且 kkFileView 会把错误响应体转换缓存成假预览，污染该
    文件名的所有后续查看。

修复后契约：
    1. token 的 tenant 绑定附件真实租户，合法签发的预览地址回调必然通过；
    2. 超管跨租户预览：签发成功 + 回调返回文件流；
    3. 同租户用户预览：签发成功 + 回调返回文件流；
    4. 无权限的他租户普通用户：签发被拒（权限不放行，不产生令牌）；
    5. 显式 token_tenant_id 覆盖仍然生效（公告/协作任务场景向后兼容）。
"""
import base64
import os
import re
import shutil
import tempfile

from django.test import TestCase

from apps.evidence.attachment_preview_token import validate_attachment_preview_token
from apps.evidence.attachment_service import (
    AttachmentService,
    ATTACHMENT_ACCESS_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment
from apps.utils.test_helpers import make_user, setup_test_env

MODULE = 'token_tenant_mod'
OBJECT_TYPE = 'obj'
TENANT_OWNER = 'tenant_owner'
TENANT_ADMIN = 'admin'
TENANT_OTHER = 'tenant_other'

PREVIEW_API_PATH = '/api/token-tenant/attachments/1/preview-file/'


def _close_response(resp):
    """关闭 FileResponse 持有的文件句柄（避免触发 request_finished 信号，
    防止 TestCase atomic 块被标记 needs_rollback，见 test_attachment_ownership）。"""
    for closable in getattr(resp, '_closable_objects', []):
        closable.close()


def _extract_token(preview_url):
    """从 kkFileView 预览地址中还原 preview_token"""
    b64 = preview_url.split('url=')[1]
    file_url = base64.b64decode(b64).decode('utf-8')
    match = re.search(r'preview_token=([^&]+)', file_url)
    return match.group(1)


class PreviewTokenTenantBindingTestCase(TestCase):
    """token 租户绑定附件真实租户：合法签发的预览回调必须通过"""

    def setUp(self):
        setup_test_env(self)
        self.media = tempfile.mkdtemp(prefix='evidence_token_tenant_')
        self.addCleanup(shutil.rmtree, self.media, True)

        settings_ctx = self.settings(
            MEDIA_ROOT=self.media,
            KKFILEVIEW_API_URL='http://kkfileview.test',
            KKFILEVIEW_SERVER_URL='http://spug-api.test',
        )
        settings_ctx.enable()
        self.addCleanup(settings_ctx.disable)

        self.superadmin = make_user('token_super', is_supper=True)
        self.superadmin.tenant_id = TENANT_ADMIN
        self.superadmin.save()

        self.owner_user = make_user('token_owner_user')
        self.owner_user.tenant_id = TENANT_OWNER
        self.owner_user.save()

        self.other_user = make_user('token_other_user')
        self.other_user.tenant_id = TENANT_OTHER
        self.other_user.save()

        self.attachment = self._make_attachment(TENANT_OWNER)

    # ---------------- 工具 ----------------

    def _make_attachment(self, tenant_id):
        rel = os.path.join(MODULE, tenant_id, '202601', '{}_1'.format(OBJECT_TYPE), 'proof.pdf')
        abs_path = os.path.join(self.media, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(b'pdf-body')
        return EvidenceAttachment.objects.create(
            tenant_id=tenant_id,
            module=MODULE,
            object_type=OBJECT_TYPE,
            object_id='1',
            file_name='proof.pdf',
            file_path=rel,
            file_size=8,
            file_ext='.pdf',
            file_hash_sha256='a' * 64,
            uploaded_by_id=self.owner_user.id,
            uploaded_by_name=self.owner_user.nickname,
        )

    def _issue(self, user, att, **kwargs):
        return AttachmentService.get_preview_url(
            user, att.id, att.module, att.object_type, PREVIEW_API_PATH, **kwargs)

    def _callback(self, preview_url, att):
        token = _extract_token(preview_url)
        return AttachmentService.preview_file_response(token, att.id)

    # ---------------- 用例 ----------------

    def test_superadmin_cross_tenant_preview_passes_callback(self):
        """超管跨租户预览：签发成功，token 绑定附件真实租户，回调返回文件流"""
        data, err = self._issue(self.superadmin, self.attachment)
        self.assertIsNone(err)
        self.assertIsNotNone(data['preview_url'])

        token = _extract_token(data['preview_url'])
        token_data = validate_attachment_preview_token(token)
        self.assertIsNotNone(token_data)
        # 令牌上的租户必须是附件真实租户，而不是查看者的租户
        self.assertEqual(token_data['tenant_id'], TENANT_OWNER)
        self.assertEqual(token_data['user_id'], self.superadmin.id)

        resp, cb_err = self._callback(data['preview_url'], self.attachment)
        self.assertIsNone(cb_err)
        self.assertIsNotNone(resp)
        _close_response(resp)

    def test_same_tenant_user_preview_passes_callback(self):
        """同租户用户预览：签发成功，回调返回文件流"""
        data, err = self._issue(self.owner_user, self.attachment)
        self.assertIsNone(err)
        resp, cb_err = self._callback(data['preview_url'], self.attachment)
        self.assertIsNone(cb_err)
        self.assertIsNotNone(resp)
        _close_response(resp)

    def test_cross_tenant_regular_user_denied(self):
        """他租户普通用户：签发被拒（权限不放行），不产生令牌"""
        data, err = self._issue(self.other_user, self.attachment)
        self.assertIsNone(data)
        self.assertEqual(err, ATTACHMENT_ACCESS_DENIED_ERROR)

    def test_explicit_token_tenant_override_still_works(self):
        """显式 token_tenant_id 覆盖仍生效（公告/协作任务场景向后兼容）"""
        data, err = self._issue(
            self.superadmin, self.attachment, skip_tenant_filter=True,
            token_tenant_id=TENANT_OWNER)
        self.assertIsNone(err)
        resp, cb_err = self._callback(data['preview_url'], self.attachment)
        self.assertIsNone(cb_err)
        self.assertIsNotNone(resp)
        _close_response(resp)
