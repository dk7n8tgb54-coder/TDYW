# -*- coding: utf-8 -*-
"""附件与物理文件稳定契约测试。"""
import base64
import os
import tempfile
from unittest import mock

from django.test import override_settings

from apps.evidence.models import EvidenceAttachment
from apps.logs.models import AuditLog
from .base import (ContractTestCase, ContractTransactionTestCase, make_user,
                   make_client, upload_file, PERM_VIEW, PERM_DOWNLOAD)

PREVIEW_URL = 'http://127.0.0.1:8012'
PREVIEW_SERVER = 'http://127.0.0.1:80'


class AttachmentUploadValidationTest(ContractTestCase):
    """上传校验：格式 / 大小 / 文件名"""

    def setUp(self):
        super().setUp()
        created = self.create_via_api(contract_name='附件宿主合同')
        self.pk = created['data']['id']

    def test_allowed_formats(self):
        cases = [
            ('合同.pdf', b'%PDF-1.4 fake pdf', 'application/pdf'),
            ('照片.jpg', b'\xff\xd8\xff\xe0 fake jpg', 'image/jpeg'),
            ('图片.png', b'\x89PNG fake png', 'image/png'),
            ('表格.xlsx', b'PK fake xlsx', 'application/vnd.ms-excel'),
            ('文档.docx', b'PK fake docx', 'application/msword'),
            ('演示.pptx', b'PK fake pptx', 'application/vnd.ms-powerpoint'),
            ('压缩包.zip', b'PK fake zip', 'application/zip'),
        ]
        for name, content, ctype in cases:
            body = self.upload(self.pk, upload_file(name, content, ctype))
            self.assertNoError(body, f'{name} 应上传成功')
            self.assertEqual(body['data']['file_name'], name)
            self.assertIn(body['data']['file_ext'],
                          ['.pdf', '.jpg', '.png', '.xlsx', '.docx', '.pptx', '.zip'])
        listing = self.get_json(f'{self.URL}{self.pk}/attachments/')
        self.assertEqual(len(listing['data']), len(cases))

    def test_disallowed_extension_rejected(self):
        for name in ['木马.exe', '脚本.sh', '木马.php', '二进制.bin']:
            body = self.upload(self.pk, upload_file(name, b'malicious'))
            self.assertBusinessError(body, f'{name} 应被拒绝')

    def test_empty_file_behaviour(self):
        """空文件：记录实际行为（当前仅校验扩展名，不校验空文件）。"""
        body = self.upload(self.pk, upload_file('空文件.pdf', b''))
        self.assertNoError(body)
        self.assertEqual(body['data']['file_size'], 0)

    def test_oversize_file_rejected(self):
        big_path = os.path.join(tempfile.mkdtemp(prefix='contract_big_'), 'big.pdf')
        size = 50 * 1024 * 1024 + 1
        with open(big_path, 'wb') as f:
            f.write(b'x' * size)
        with open(big_path, 'rb') as fh:
            body = self.upload(self.pk, upload_file('超大文件.pdf', fh.read()))
        tempfile_dir = os.path.dirname(big_path)
        try:
            self.assertBusinessError(body, '超过 50MB 的文件应被拒绝')
            self.assertIn('50MB', body.get('error', ''))
        finally:
            try:
                os.remove(big_path)
                os.rmdir(tempfile_dir)
            except OSError:
                pass

    def test_path_traversal_filename_sanitized(self):
        body = self.upload(self.pk, upload_file('../../../../etc/passwd.pdf', b'pwned'))
        self.assertNoError(body)
        att = EvidenceAttachment.objects.get(pk=body['data']['id'])
        self.assertNotIn('..', att.file_path)
        self.assertTrue(att.file_path.startswith('contract_agreement'))
        self.assertEqual(os.path.basename(att.file_path), 'passwd.pdf')

    def test_no_file_rejected(self):
        resp = self.client.post(f'{self.URL}{self.pk}/attachments/', {})
        self.assertBusinessError(self._decode(resp))

    def test_upload_to_nonexistent_contract_rejected(self):
        body = self.upload(999999, upload_file('x.pdf', b'x'))
        self.assertBusinessError(body)


class AttachmentAccessTest(ContractTestCase):
    """附件列表 / 下载 / 预览 / 删除"""

    def setUp(self):
        super().setUp()
        created = self.create_via_api(contract_name='附件访问合同')
        self.pk = created['data']['id']
        self.up = self.upload(self.pk, upload_file('访问.pdf', b'attachment-bytes'))
        self.att_id = self.up['data']['id']

    def test_attachment_associated_with_contract(self):
        att = EvidenceAttachment.objects.get(pk=self.att_id)
        self.assertEqual(att.module, 'contract_agreement')
        self.assertEqual(att.object_type, 'agreement')
        self.assertEqual(att.object_id, str(self.pk))
        self.assertEqual(att.tenant_id, 'admin')

    def test_list_returns_attachments(self):
        self.upload(self.pk, upload_file('第二个.pdf', b'second'))
        listing = self.get_json(f'{self.URL}{self.pk}/attachments/')
        self.assertNoError(listing)
        self.assertEqual(len(listing['data']), 2)
        detail = self.get_json(f'{self.URL}{self.pk}/')
        self.assertEqual(detail['data']['attachment_count'], 2)

    def test_download_content_and_headers(self):
        resp = self.client.get(f'{self.URL}attachments/{self.att_id}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.response_bytes(resp), b'attachment-bytes')
        self.assertIn('attachment', resp['Content-Disposition'])

    def test_download_inline(self):
        resp = self.client.get(f'{self.URL}attachments/{self.att_id}/download/',
                               {'inline': '1'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('inline', resp['Content-Disposition'])
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_download_writes_audit_log(self):
        before = AuditLog.objects.filter(target_type='contract_agreement_attachment').count()
        self.client.get(f'{self.URL}attachments/{self.att_id}/download/')
        after = AuditLog.objects.filter(target_type='contract_agreement_attachment').count()
        self.assertEqual(after, before + 1)
        log = AuditLog.objects.filter(
            target_type='contract_agreement_attachment').order_by('-id').first()
        self.assertEqual(log.action, 'other')
        self.assertEqual(log.username, self.user.username)
        self.assertEqual(log.tenant_id, 'admin')
        self.assertIn('download', log.detail)

    def _preview_token(self, att_id):
        """取预览 URL 中的 preview_token（kkFileView URL 为 base64 编码）。"""
        from urllib.parse import urlparse, parse_qs
        body = self.get_json(f'{self.URL}attachments/{att_id}/preview-url/')
        self.assertNoError(body)
        preview_url = body['data']['preview_url']
        encoded = parse_qs(urlparse(preview_url).query)['url'][0]
        file_url = base64.b64decode(encoded).decode('utf-8')
        self.assertIn(f'/api/contract-agreement/attachments/{att_id}/preview-file/', file_url)
        return parse_qs(urlparse(file_url).query)['preview_token'][0]

    @override_settings(KKFILEVIEW_API_URL=PREVIEW_URL, KKFILEVIEW_SERVER_URL=PREVIEW_SERVER)
    def test_preview_url_flow(self):
        body = self.get_json(f'{self.URL}attachments/{self.att_id}/preview-url/')
        self.assertNoError(body)
        self.assertIn('preview_url', body['data'])
        self.assertIn('onlinePreview', body['data']['preview_url'])
        token = self._preview_token(self.att_id)
        self.assertTrue(token, '预览 URL 中应包含 preview_token')

    @override_settings(KKFILEVIEW_API_URL=PREVIEW_URL, KKFILEVIEW_SERVER_URL=PREVIEW_SERVER)
    def test_preview_file_requires_valid_token(self):
        token = self._preview_token(self.att_id)

        ok = self.client.get(f'{self.URL}attachments/{self.att_id}/preview-file/',
                             {'preview_token': token})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.response_bytes(ok), b'attachment-bytes')

        missing = self.client.get(f'{self.URL}attachments/{self.att_id}/preview-file/')
        self.assertTrue(self._decode(missing).get('error'), '缺少 token 应被拒绝')

        bad = self.client.get(f'{self.URL}attachments/{self.att_id}/preview-file/',
                              {'preview_token': 'invalid.token.value'})
        self.assertTrue(self._decode(bad).get('error'), '无效 token 应被拒绝')

    @override_settings(KKFILEVIEW_API_URL=PREVIEW_URL, KKFILEVIEW_SERVER_URL=PREVIEW_SERVER)
    def test_preview_token_cannot_be_reused_for_other_attachment(self):
        second = self.upload(self.pk, upload_file('第二个.pdf', b'second'))
        second_id = second['data']['id']
        token = self._preview_token(self.att_id)

        swapped = self.client.get(f'{self.URL}attachments/{second_id}/preview-file/',
                                  {'preview_token': token})
        self.assertTrue(self._decode(swapped).get('error'),
                        'preview_token 不得跨附件复用')

    @override_settings(KKFILEVIEW_API_URL=PREVIEW_URL, KKFILEVIEW_SERVER_URL=PREVIEW_SERVER)
    def test_expired_preview_token_rejected(self):
        token = self._preview_token(self.att_id)
        with mock.patch('apps.evidence.attachment_preview_token.'
                        'ATTACHMENT_PREVIEW_TOKEN_MAX_AGE', -1):
            resp = self.client.get(f'{self.URL}attachments/{self.att_id}/preview-file/',
                                   {'preview_token': token})
        self.assertTrue(self._decode(resp).get('error'), '过期 token 应被拒绝')

    @override_settings(KKFILEVIEW_API_URL=PREVIEW_URL, KKFILEVIEW_SERVER_URL=PREVIEW_SERVER)
    def test_non_previewable_extension_rejected(self):
        up = self.upload(self.pk, upload_file('归档.zip', b'PK zip'))
        self.assertNoError(up)
        body = self.get_json(f'{self.URL}attachments/{up["data"]["id"]}/preview-url/')
        self.assertBusinessError(body, 'zip 类型不应生成在线预览地址')

    def test_delete_attachment_soft_deletes_and_audits(self):
        self.assertNoError(self.delete_attachment(self.att_id, reason='测试删除'))
        att = EvidenceAttachment.objects.all_with_deleted().get(pk=self.att_id)
        self.assertTrue(att.is_deleted)
        self.assertEqual(att.delete_reason, '测试删除')
        self.assertEqual(att.deleted_by_id, self.user.id)
        log = AuditLog.objects.filter(
            target_type='contract_agreement_attachment', action='delete').first()
        self.assertIsNotNone(log, '删除附件必须写审计日志')
        self.assertIn('测试删除', log.detail)

    def test_deleted_attachment_not_listed(self):
        self.delete_attachment(self.att_id)
        listing = self.get_json(f'{self.URL}{self.pk}/attachments/')
        self.assertEqual(len(listing['data']), 0)
        detail = self.get_json(f'{self.URL}{self.pk}/')
        self.assertEqual(detail['data']['attachment_count'], 0)

    def test_delete_attachment_twice_returns_error(self):
        self.delete_attachment(self.att_id)
        self.assertBusinessError(self.delete_attachment(self.att_id))

    def test_delete_attachment_requires_id(self):
        body = self._decode(self.client.delete('/contract-agreement/attachments/'))
        self.assertBusinessError(body)

    def _make_foreign_attachment(self, tenant_id, module, object_type, content=b'foreign'):
        """构造其他模块/其他租户的附件记录，并真实落盘（避免"文件不存在"掩盖越权判定）。"""
        rel = f'{module}/{tenant_id}/202609/{object_type}_999/foreign.pdf'
        full = self.media_path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as fh:
            fh.write(content)
        return EvidenceAttachment.objects.create(
            tenant_id=tenant_id, module=module, object_type=object_type,
            object_id='999', file_name='其他模块.pdf', file_path=rel,
            file_size=len(content), file_ext='.pdf', uploaded_by_id=self.user.id,
            uploaded_by_name=self.user.nickname,
        )

    def test_cross_module_attachment_access_rejected(self):
        """合同协议附件权限不得用于访问同租户内其他模块的附件。"""
        foreign = self._make_foreign_attachment('admin', 'upgrade', 'record')
        resp = self.client.get(f'{self.URL}attachments/{foreign.id}/download/')
        self.assertTrue(
            self._decode(resp).get('error'),
            f'合同协议下载接口不得下载其他模块（upgrade）的附件，实际响应: '
            f'status={resp.status_code}, content-type={resp.get("Content-Type")}')

    def test_cross_module_attachment_delete_rejected(self):
        """合同协议附件删除权限不得用于删除同租户内其他模块的附件。"""
        foreign = self._make_foreign_attachment('admin', 'upgrade', 'record')
        self.assertBusinessError(
            self.delete_attachment(foreign.id),
            '合同协议删除接口不得删除其他模块（upgrade）的附件')
        self.assertFalse(EvidenceAttachment.objects.get(pk=foreign.id).is_deleted)

    def test_cross_tenant_attachment_download_rejected(self):
        victim = make_user('qa_att_victim', tenant_id='t_att')
        victim_att = EvidenceAttachment.objects.create(
            tenant_id='t_att', module='contract_agreement', object_type='agreement',
            object_id='1', file_name='他租户.pdf', file_path='contract_agreement/t_att/202609/agreement_1/x.pdf',
            file_size=10, file_ext='.pdf', uploaded_by_id=victim.id,
            uploaded_by_name=victim.nickname,
        )
        resp = self.client.get(f'{self.URL}attachments/{victim_att.id}/download/')
        self.assertTrue(self._decode(resp).get('error'),
                        '不得跨租户下载附件')

    def test_cross_tenant_attachment_delete_rejected(self):
        victim = make_user('qa_att_victim2', tenant_id='t_att2')
        victim_att = EvidenceAttachment.objects.create(
            tenant_id='t_att2', module='contract_agreement', object_type='agreement',
            object_id='1', file_name='他租户2.pdf', file_path='contract_agreement/t_att2/202609/agreement_1/x.pdf',
            file_size=10, file_ext='.pdf', uploaded_by_id=victim.id,
            uploaded_by_name=victim.nickname,
        )
        body = self.delete_attachment(victim_att.id)
        self.assertBusinessError(body)
        self.assertFalse(EvidenceAttachment.objects.get(pk=victim_att.id).is_deleted)


class AttachmentPhysicalFileTest(ContractTransactionTestCase):
    """真实物理文件生命周期（依赖 transaction.on_commit，需事务外执行）"""

    def setUp(self):
        super().setUp()
        # 注意：不可在此再次 cache.clear()，会清掉基类 setUp 写入的用户权限缓存
        self.created = self.create_via_api(contract_name='物理文件合同')
        self.pk = self.created['data']['id']

    def _disk_path(self, att_id):
        rel = EvidenceAttachment.objects.get(pk=att_id).file_path
        return self.media_path(rel)

    def test_upload_writes_physical_file(self):
        up = self.upload(self.pk, upload_file('物理.pdf', b'physical-content'))
        self.assertNoError(up)
        path = self._disk_path(up['data']['id'])
        self.assertTrue(os.path.exists(path), f'物理文件应落盘: {path}')
        with open(path, 'rb') as fh:
            self.assertEqual(fh.read(), b'physical-content')

    def test_delete_attachment_removes_physical_file(self):
        up = self.upload(self.pk, upload_file('待删.pdf', b'to-be-removed'))
        path = self._disk_path(up['data']['id'])
        self.assertTrue(os.path.exists(path))
        self.assertNoError(self.delete_attachment(up['data']['id']))
        self.assertFalse(os.path.exists(path), '删除附件后物理文件应被清理')

    def test_delete_contract_removes_attachment_files(self):
        up = self.upload(self.pk, upload_file('随合同删除.pdf', b'cascade'))
        path = self._disk_path(up['data']['id'])
        self.assertTrue(os.path.exists(path))
        self.delete_json({'id': self.pk})
        self.assertFalse(os.path.exists(path), '删除合同后附件物理文件应被清理')
        self.assertTrue(
            EvidenceAttachment.objects.all_with_deleted().filter(pk=up['data']['id']).exists(),
            '附件数据库记录应保留（软删除）')

    def test_physical_delete_failure_keeps_retryable_record(self):
        """物理删除失败时必须保留可重试状态，不能静默丢失记录。"""
        up = self.upload(self.pk, upload_file('删除失败.pdf', b'keep-me'))
        att_id = up['data']['id']
        path = self._disk_path(att_id)
        self.assertTrue(os.path.exists(path))

        with mock.patch('apps.evidence.attachment_service.os.remove',
                        side_effect=OSError('Permission denied')):
            body = self.delete_attachment(att_id)
        self.assertNoError(body, '物理删除失败时接口应正常返回（记录已软删除，可重试）')
        att = EvidenceAttachment.objects.all_with_deleted().get(pk=att_id)
        self.assertTrue(att.is_deleted, '数据库记录应保留，供重试清理')
        self.assertTrue(os.path.exists(path), '物理文件删除失败应保留文件')

    def test_sha256_recorded(self):
        up = self.upload(self.pk, upload_file('哈希.pdf', b'hash-me'))
        self.assertNoError(up)
        att = EvidenceAttachment.objects.get(pk=up['data']['id'])
        self.assertEqual(len(att.file_hash_sha256), 64, '上传应计算 SHA256')
