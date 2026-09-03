# -*- coding: utf-8 -*-
"""干扰管理附件归属校验稳定契约测试（DEF-01 修复的回归守卫）。

AttachmentService 只按租户过滤、不校验模块归属，因此干扰管理的附件
下载 / 删除 / 预览地址端点必须在视图层完成归属校验：
同租户其他模块（如 upgrade）的附件一律拒绝，跨租户附件一律拒绝，
本模块附件正常放行。范式与规则见 spug_api/AGENTS.md「附件接口归属校验」。
"""
import os
import tempfile

from django.conf import settings
from django.test import TestCase, override_settings

from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.interference.models import Interference
from apps.evidence.models import EvidenceAttachment

PERMS = ['interference.interference.view', 'interference.interference.add',
         'interference.interference.edit', 'interference.interference.del']


def _make_record(user, serial_number, tenant_id):
    return Interference.objects.create(
        tenant_id=tenant_id, serial_number=serial_number,
        frequency='100MHz', report_dept='D', datetime='2026-01-01 10:00:00',
        interference_type='T', phenomenon='P', created_by=user)


def _make_attachment(user, tenant_id, module, object_type, rel_path, content=b'foreign-bytes'):
    """构造指定模块/租户的附件记录并真实落盘到 MEDIA_ROOT，避免「文件不存在」掩盖越权判定。"""
    full = os.path.join(settings.MEDIA_ROOT, rel_path.replace('/', os.sep))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'wb') as fh:
        fh.write(content)
    return EvidenceAttachment.objects.create(
        tenant_id=tenant_id, module=module, object_type=object_type,
        object_id='999', file_name='附件.pdf', file_path=rel_path,
        file_size=len(content), file_ext='.pdf', uploaded_by_id=user.id,
        uploaded_by_name=user.nickname,
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='int_att_qa_'))
class AttachmentScopingTest(TestCase):
    """跨模块 / 跨租户附件必须被干扰管理附件端点拒绝"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('int_att_user', PERMS)
        self.client = make_client(self.user)
        self.record = _make_record(self.user, 901, 'admin')

    def _make_foreign(self):
        return _make_attachment(
            self.user, 'admin', 'upgrade', 'record',
            'upgrade/admin/202609/record_999/foreign.pdf')

    def _make_own(self):
        return _make_attachment(
            self.user, 'admin', 'interference', 'interference',
            'interference/admin/202609/interference_%d/own.pdf' % self.record.id,
            content=b'own-bytes')

    def _make_other_tenant(self):
        return _make_attachment(
            self.user, 't_int_other', 'interference', 'interference',
            'interference/t_int_other/202609/interference_999/x.pdf')

    @staticmethod
    def _body(resp):
        if resp.streaming:
            return {'_streaming': True, '_status': resp.status_code}
        return resp.json()

    def test_cross_module_download_rejected(self):
        foreign = self._make_foreign()
        resp = self.client.get(f'/interference/attachments/{foreign.id}/download/')
        body = self._body(resp)
        self.assertTrue(body.get('error') or body.get('_streaming'),
                        '同租户其他模块附件不得通过干扰管理接口下载')
        self.assertTrue(body.get('error'),
                        f'下载 upgrade 模块附件应返回业务错误，实际: {body}')

    def test_cross_module_delete_rejected(self):
        foreign = self._make_foreign()
        resp = self.client.delete(f'/interference/attachments/?id={foreign.id}')
        self.assertTrue(resp.json().get('error'),
                        '同租户其他模块附件不得通过干扰管理接口删除')
        self.assertFalse(EvidenceAttachment.objects.get(pk=foreign.id).is_deleted)

    def test_cross_module_preview_url_rejected(self):
        foreign = self._make_foreign()
        with override_settings(KKFILEVIEW_API_URL='http://127.0.0.1:8012',
                               KKFILEVIEW_SERVER_URL='http://127.0.0.1:80'):
            resp = self.client.get(f'/interference/attachments/{foreign.id}/preview-url/')
        self.assertTrue(resp.json().get('error'),
                        '不得为其他模块附件生成干扰管理预览地址')

    def test_cross_tenant_attachment_rejected(self):
        other = self._make_other_tenant()
        resp = self.client.get(f'/interference/attachments/{other.id}/download/')
        self.assertTrue(self._body(resp).get('error'), '跨租户附件不得下载')
        resp = self.client.delete(f'/interference/attachments/?id={other.id}')
        self.assertTrue(resp.json().get('error'), '跨租户附件不得删除')
        self.assertFalse(EvidenceAttachment.objects.get(pk=other.id).is_deleted)

    def test_own_attachment_download_allowed(self):
        own = self._make_own()
        resp = self.client.get(f'/interference/attachments/{own.id}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.streaming, '本模块附件应正常放行下载')
