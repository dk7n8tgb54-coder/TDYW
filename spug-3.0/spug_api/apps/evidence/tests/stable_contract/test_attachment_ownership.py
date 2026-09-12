# -*- coding: utf-8 -*-
"""AttachmentService 附件归属校验 stable_contract 测试

背景（跨模块附件越权）：
    download_response / get_preview_url / soft_delete 早期只按租户过滤，
    不校验附件归属的 module / object_type。业务模块的附件端点把客户端传入的
    附件 ID 直接透传给服务层，而附件 ID 是自增整数可枚举，因此持有任一模块
    附件权限的用户即可越权下载 / 预览 / 软删除同租户其他模块的附件。

修复后契约：
    1. module 与 object_type 为必填强校验项；
    2. 命中附件必须同时满足 is_deleted=False + module + object_type + 租户范围；
    3. skip_tenant_filter=True 只绕过租户过滤，绝不绕过 module / object_type；
    4. 拒绝时统一返回不泄露归属信息的业务错误。
"""
import os
import shutil
import tempfile

from django.test import TestCase

from apps.evidence.attachment_service import (
    AttachmentService,
    ATTACHMENT_ACCESS_DENIED_ERROR,
    ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment
from apps.utils.test_helpers import make_user, setup_test_env

# 调用方声明的归属（本模块）
MODULE_A = 'ownership_mod_a'
OBJECT_TYPE_A = 'obj_a'
# 同租户其他模块 / 其他对象类型
MODULE_B = 'ownership_mod_b'
OBJECT_TYPE_B = 'obj_b'

TENANT_A = 'tenant_a'
TENANT_B = 'tenant_b'

PREVIEW_API_PATH = '/api/ownership/attachments/1/preview-file/'


def _close_response(resp):
    """关闭 FileResponse 持有的文件句柄。

    注意：不能直接调用 HttpResponse.close()，它会发送 request_finished 信号，
    Django 的接收器会重置 / 关闭数据库连接，从而把 TestCase 的 atomic 块标记为
    needs_rollback，导致后续所有用例在 setUp 阶段报
    "An error occurred in the current transaction"。
    """
    for closable in getattr(resp, '_closable_objects', []):
        closable.close()


class AttachmentOwnershipTestCase(TestCase):
    """服务层归属校验：正确归属放行，错误归属 / 软删除 / 缺参一律拒绝"""

    def setUp(self):
        setup_test_env(self)
        self.media = tempfile.mkdtemp(prefix='evidence_ownership_')
        self.addCleanup(shutil.rmtree, self.media, True)

        # MEDIA_ROOT 指向临时目录 + 打开 kkFileView 配置（get_preview_url 前置依赖）
        settings_ctx = self.settings(
            MEDIA_ROOT=self.media,
            KKFILEVIEW_API_URL='http://kkfileview.test',
            KKFILEVIEW_SERVER_URL='http://spug-api.test',
        )
        settings_ctx.enable()
        self.addCleanup(settings_ctx.disable)

        self.user = make_user('ownership_user')
        self.user.tenant_id = TENANT_A
        self.user.save()

    # ---------------- 工具 ----------------

    def _make_attachment(self, tenant_id, module, object_type,
                         file_name='proof.pdf', is_deleted=False):
        rel = os.path.join(module, tenant_id, '202601', f'{object_type}_1', file_name)
        abs_path = os.path.join(self.media, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(b'pdf-body')
        return EvidenceAttachment.objects.create(
            tenant_id=tenant_id,
            module=module,
            object_type=object_type,
            object_id='1',
            file_name=file_name,
            file_path=rel,
            file_size=8,
            file_ext='.pdf',
            file_hash_sha256='a' * 64,
            uploaded_by_id=self.user.id,
            uploaded_by_name=self.user.nickname,
            is_deleted=is_deleted,
        )

    @staticmethod
    def _is_deleted(attachment_id):
        """无视默认 Manager 的软删除过滤，读取真实 is_deleted"""
        return EvidenceAttachment.objects.all_with_deleted().get(pk=attachment_id).is_deleted

    def _download(self, att, module=MODULE_A, object_type=OBJECT_TYPE_A, skip=False):
        return AttachmentService.download_response(
            self.user, att.id, module, object_type, skip_tenant_filter=skip)

    def _preview(self, att, module=MODULE_A, object_type=OBJECT_TYPE_A, skip=False):
        return AttachmentService.get_preview_url(
            self.user, att.id, module, object_type, PREVIEW_API_PATH,
            skip_tenant_filter=skip)

    def _delete(self, att, module=MODULE_A, object_type=OBJECT_TYPE_A):
        return AttachmentService.soft_delete(
            self.user, att.id, module, object_type)

    def _assert_download_denied(self, att, **kwargs):
        resp, err = self._download(att, **kwargs)
        self.assertIsNone(resp, '错误归属的附件不应返回文件流')
        self.assertEqual(err, ATTACHMENT_ACCESS_DENIED_ERROR)
        self.assertNotIn(att.module, err, '错误信息不应泄露附件真实模块')
        self.assertNotIn(att.file_path, err, '错误信息不应泄露文件路径')

    def _assert_preview_denied(self, att, **kwargs):
        data, err = self._preview(att, **kwargs)
        self.assertIsNone(data, '错误归属的附件不应签发预览地址')
        self.assertEqual(err, ATTACHMENT_ACCESS_DENIED_ERROR)
        self.assertNotIn(att.module, err, '错误信息不应泄露附件真实模块')

    def _assert_delete_denied(self, att, **kwargs):
        err = self._delete(att, **kwargs)
        self.assertEqual(err, ATTACHMENT_DELETE_DENIED_ERROR)
        self.assertFalse(self._is_deleted(att.id), '被拒绝的删除不应改动附件')
        self.assertIsNone(
            EvidenceAttachment.objects.all_with_deleted().get(pk=att.id).deleted_at,
            '被拒绝的删除不应写入删除痕迹',
        )

    # ---------------- 1. 同租户 + 正确归属：放行 ----------------

    def test_correct_ownership_download_ok(self):
        att = self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_A)
        resp, err = self._download(att)
        self.assertIsNone(err, f'正确归属应允许下载: {err}')
        self.assertIsNotNone(resp)
        _close_response(resp)

    def test_correct_ownership_preview_ok(self):
        att = self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_A)
        data, err = self._preview(att)
        self.assertIsNone(err, f'正确归属应允许生成预览地址: {err}')
        self.assertIsNotNone(data)
        self.assertIn('preview_url', data)
        self.assertIn('file_name', data)

    def test_correct_ownership_soft_delete_ok(self):
        att = self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_A)
        self.assertIsNone(self._delete(att), '正确归属应允许软删除')
        self.assertTrue(self._is_deleted(att.id), '软删除后 is_deleted 应为 True')

    # ---------------- 2. 同租户 + 错误 module：全部拒绝 ----------------

    def test_wrong_module_download_denied(self):
        self._assert_download_denied(
            self._make_attachment(TENANT_A, MODULE_B, OBJECT_TYPE_A))

    def test_wrong_module_preview_denied(self):
        self._assert_preview_denied(
            self._make_attachment(TENANT_A, MODULE_B, OBJECT_TYPE_A))

    def test_wrong_module_delete_denied(self):
        self._assert_delete_denied(
            self._make_attachment(TENANT_A, MODULE_B, OBJECT_TYPE_A))

    # ---------------- 3. 同 module + 错误 object_type：全部拒绝 ----------------

    def test_wrong_object_type_download_denied(self):
        self._assert_download_denied(
            self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_B))

    def test_wrong_object_type_preview_denied(self):
        self._assert_preview_denied(
            self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_B))

    def test_wrong_object_type_delete_denied(self):
        self._assert_delete_denied(
            self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_B))

    # ---------------- 4. 跨租户：普通用户全部拒绝 ----------------

    def test_cross_tenant_download_denied(self):
        self._assert_download_denied(
            self._make_attachment(TENANT_B, MODULE_A, OBJECT_TYPE_A))

    def test_cross_tenant_preview_denied(self):
        self._assert_preview_denied(
            self._make_attachment(TENANT_B, MODULE_A, OBJECT_TYPE_A))

    def test_cross_tenant_delete_denied(self):
        self._assert_delete_denied(
            self._make_attachment(TENANT_B, MODULE_A, OBJECT_TYPE_A))

    # ---------------- 5. skip_tenant_filter：仅绕过租户过滤 ----------------

    def test_skip_tenant_filter_allows_cross_tenant(self):
        """调用方已完成可见性校验时，跨租户附件可访问"""
        att = self._make_attachment(TENANT_B, MODULE_A, OBJECT_TYPE_A)

        resp, err = self._download(att, skip=True)
        self.assertIsNone(err, f'skip_tenant_filter 应允许跨租户下载: {err}')
        self.assertIsNotNone(resp)
        _close_response(resp)

        data, err = self._preview(att, skip=True)
        self.assertIsNone(err, f'skip_tenant_filter 应允许跨租户预览: {err}')
        self.assertIsNotNone(data)

    def test_skip_tenant_filter_still_enforces_module(self):
        """skip_tenant_filter 绝不能绕过 module 校验"""
        att = self._make_attachment(TENANT_B, MODULE_B, OBJECT_TYPE_B)
        self._assert_download_denied(att, skip=True)
        self._assert_preview_denied(att, skip=True)

    def test_skip_tenant_filter_still_enforces_object_type(self):
        """skip_tenant_filter 绝不能绕过 object_type 校验"""
        att = self._make_attachment(TENANT_B, MODULE_A, OBJECT_TYPE_B)
        self._assert_download_denied(att, skip=True)
        self._assert_preview_denied(att, skip=True)

    # ---------------- 6. 软删除附件不可访问 ----------------

    def test_soft_deleted_attachment_inaccessible(self):
        att = self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_A, is_deleted=True)
        self._assert_download_denied(att)
        self._assert_preview_denied(att)
        self.assertEqual(self._delete(att), ATTACHMENT_DELETE_DENIED_ERROR)

    # ---------------- 7. 缺失归属参数：fail-closed ----------------

    def test_missing_module_denied(self):
        att = self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_A)
        resp, err = self._download(att, module='')
        self.assertIsNone(resp)
        self.assertEqual(err, ATTACHMENT_ACCESS_DENIED_ERROR)

        data, err = self._preview(att, module=None)
        self.assertIsNone(data)
        self.assertEqual(err, ATTACHMENT_ACCESS_DENIED_ERROR)

    def test_missing_object_type_denied(self):
        att = self._make_attachment(TENANT_A, MODULE_A, OBJECT_TYPE_A)
        resp, err = self._download(att, object_type='')
        self.assertIsNone(resp)
        self.assertEqual(err, ATTACHMENT_ACCESS_DENIED_ERROR)

        self.assertEqual(
            self._delete(att, object_type=''), ATTACHMENT_DELETE_DENIED_ERROR)
        self.assertFalse(self._is_deleted(att.id), '缺参时应拒绝删除，附件保持未删除')
