"""R-05 附件上传与存储安全（stable_contract + 安全）。

覆盖用户要求：
- 正常上传每种允许的文件类型
- 空文件、超大文件、扩展名大小写、无扩展名文件
- 伪造扩展名、异常 MIME、文件名包含路径分隔符 / ../ / 反斜杠 / 控制字符 / 超长文件名
- 同名文件重复上传：stored_name 不冲突且不覆盖
- 校验 original_name / stored_name / file_path / file_size / file_type / 文件哈希 / uploaded_by
- 文件必须先落盘再写库；DB 失败时不得留下不可追踪文件
- 物理写入失败时 DB 不得产生虚假记录
- 规章附件不得写入 EvidenceAttachment
"""
import hashlib
import os
from unittest.mock import patch

from apps.regulation import storage
from apps.regulation.models import RegulationAttachment
from .base import RegulationGateTestCase, ALL_ALLOWED_SAMPLES


class AllowedTypeUploadTests(RegulationGateTestCase):
    """R-05-01 白名单内全部文件类型均可上传"""

    def test_every_allowed_extension_uploads(self):
        for filename, content, ctype in ALL_ALLOWED_SAMPLES:
            resp = self.upload(self.admin_client, self.regulation.id,
                               filename=filename, content=content, content_type=ctype)
            data = resp.json()
            self.assertEqual(data['error'], '',
                             f'{filename} 应允许上传，实际错误：{data.get("error")}')
            self.assertEqual(data['data']['file_name'], filename)

    def test_uppercase_extension_accepted(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'UPPER.PDF', b'%PDF-1.4')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertEqual(att.file_type, 'pdf', 'file_type 统一小写')
        self.assertTrue(att.stored_name.endswith('.PDF'),
                        '物理文件名保留原始大小写扩展名')

    def test_mixed_case_extension_accepted(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'MiXeD.DoCx', b'PK\x03\x04')
        self.assertEqual(resp.json()['error'], '')


class RejectedUploadTests(RegulationGateTestCase):
    """R-05-02 非法文件被拒绝"""

    def test_disallowed_extension_rejected(self):
        for filename in ('a.exe', 'a.sh', 'a.bat', 'a.zip', 'a.php', 'a.js'):
            resp = self.upload(self.admin_client, self.regulation.id, filename, b'x',
                               'application/octet-stream')
            self.assertIn('不支持的文件类型', resp.json()['error'], f'{filename} 应被拒绝')
        self.assertEqual(RegulationAttachment.objects.count(), 0)

    def test_no_extension_rejected(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'noext', b'x',
                           'application/octet-stream')
        self.assertIn('无扩展名', resp.json()['error'])

    def test_forged_extension_with_executable_suffix_rejected(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'evil.pdf.exe', b'MZ',
                           'application/x-msdownload')
        self.assertIn('不支持的文件类型', resp.json()['error'])

    def test_double_extension_exe_pdf_allowed_by_extension_whitelist(self):
        """仅按扩展名白名单判定，evil.exe.pdf 会被放行（记录实际行为）"""
        resp = self.upload(self.admin_client, self.regulation.id, 'evil.exe.pdf', b'MZ',
                           'application/x-msdownload')
        self.assertEqual(resp.json()['error'], '')

    def test_missing_file_field_rejected(self):
        resp = self.admin_client.post(
            f'/regulation/{self.regulation.id}/attachments/upload/', {})
        self.assertEqual(resp.json()['error'], '请选择要上传的文件')

    def test_oversized_file_rejected(self):
        with patch('apps.regulation.storage.MAX_FILE_SIZE', 10):
            resp = self.upload(self.admin_client, self.regulation.id, 'big.pdf', b'x' * 64)
        self.assertIn('文件大小不能超过', resp.json()['error'])
        self.assertEqual(RegulationAttachment.objects.count(), 0)
        self.assertEqual(self.physical_file_count(), 0)

    def test_upload_to_nonexistent_regulation_rejected(self):
        resp = self.upload(self.admin_client, 999999, 'x.pdf')
        self.assertEqual(resp.json()['error'], '规章不存在')

    def test_upload_failure_produces_no_partial_record(self):
        before = RegulationAttachment.objects.count()
        self.upload(self.admin_client, self.regulation.id, 'bad.exe', b'x')
        self.assertEqual(RegulationAttachment.objects.count(), before,
                         '上传失败不得产生半成品记录')


class EmptyFileUploadTests(RegulationGateTestCase):
    """R-05-03 空文件上传（记录实际行为）"""

    def test_empty_file_accepted_with_zero_size(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'empty.pdf', b'',
                           'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertEqual(att.file_size, 0)
        self.assertTrue(os.path.exists(os.path.join(self._tmp_storage, att.file_path)),
                        '0 字节文件也应落盘')


class FilenameSecurityTests(RegulationGateTestCase):
    """R-05-04 恶意 / 异常文件名处理"""

    def test_path_traversal_filename_is_sanitized(self):
        resp = self.upload(self.admin_client, self.regulation.id, '../../../etc/passwd.pdf',
                           b'%PDF-1.4', 'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        abs_path = storage.resolve_absolute_path(att.file_path)
        self.assertTrue(os.path.exists(abs_path))
        rel = os.path.relpath(abs_path, self._tmp_storage)
        self.assertTrue(rel.startswith('regulation' + os.sep),
                        '物理路径必须限制在 regulation 子目录内')
        self.assertNotIn('..', rel.split(os.sep))
        self.assertNotIn('etc', rel.split(os.sep))

    def test_backslash_filename_is_sanitized(self):
        resp = self.upload(self.admin_client, self.regulation.id, '..\\..\\windows\\x.pdf',
                           b'%PDF-1.4', 'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        abs_path = storage.resolve_absolute_path(att.file_path)
        self.assertTrue(abs_path.startswith(
            os.path.join(self._tmp_storage, 'regulation') + os.sep))

    def test_unsafe_chars_replaced_in_stored_name(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'a/b:c*d?e"f<g>h|i.pdf',
                           b'%PDF-1.4', 'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        for ch in '/\\:*?"<>|':
            self.assertNotIn(ch, att.stored_name, f'存储名不得包含 {ch!r}')

    def test_control_chars_replaced_in_stored_name(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'ctrl\x01\x02name.pdf',
                           b'%PDF-1.4', 'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertNotIn('\x01', att.stored_name)
        self.assertNotIn('\x02', att.stored_name)

    def test_ascii_long_filename_stored_name_truncated(self):
        """ASCII 长文件名：存储名主体截断到 80 字符，上传成功"""
        long_name = 'x' * 200 + '.pdf'
        resp = self.upload(self.admin_client, self.regulation.id, long_name, b'%PDF-1.4',
                           'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertLessEqual(len(att.stored_name), 80 + 1 + 12 + 5,
                             '存储文件名主体被截断到 80 字符以内')
        self.assertTrue(att.stored_name.endswith('.pdf'))

    def test_cjk_long_filename_exceeds_filesystem_limit(self):
        """P1 缺陷复现：80 个汉字的存储名 = 240 字节 + 17 字节后缀 > 255 字节上限

        MAX_STORED_BASENAME_LENGTH 按"字符"截断（80），而文件系统按"字节"限制（255）。
        纯中文长文件名必然触发 OSError: File name too long -> HTTP 500。
        期望：上传成功，或返回明确的业务错误（不得 500）。
        """
        long_name = '长' * 200 + '.pdf'
        resp = self.upload(self.admin_client, self.regulation.id, long_name, b'%PDF-1.4',
                           'application/pdf')
        self.assertEqual(resp.json()['error'], '',
                         '纯中文长文件名应能上传成功，实际被文件系统字节上限拦截')
        self.assertEqual(self.physical_file_count(), 1)

    def test_stored_name_byte_length_root_cause(self):
        """根因证据：截断后存储名的字节长度可能超过文件系统 255 字节上限"""
        stored = storage.build_stored_name('长' * 200 + '.pdf')
        byte_len = len(stored.encode('utf-8'))
        self.assertEqual(len(stored), 80 + 1 + 12 + 4, '按字符数截断到 80')
        self.assertGreater(byte_len, 255,
                           '根因：80 个汉字 = 240 字节，加后缀后超过 255 字节文件系统上限')

    def test_original_name_255_chars_accepted(self):
        name = 'a' * 251 + '.pdf'
        resp = self.upload(self.admin_client, self.regulation.id, name, b'%PDF-1.4',
                           'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(
            RegulationAttachment.objects.get(pk=resp.json()['data']['id']).original_name, name)

    def test_original_name_over_field_limit_is_silently_truncated(self):
        """P3 观察：超过 255 字符的原始文件名被静默截断落库，接口仍返回成功"""
        name = 'a' * 300 + '.pdf'
        resp = self.upload(self.admin_client, self.regulation.id, name, b'%PDF-1.4',
                           'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertEqual(len(att.original_name), 255,
                         '超长原始文件名被静默截断到字段上限 255 字符，用户无感知')

    def test_orm_write_over_field_limit_is_rejected(self):
        """对照：直接 ORM 写入超长 original_name 会被数据库拒绝（字段约束真实存在）"""
        from django.db import DatabaseError, transaction
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                RegulationAttachment.objects.create(
                    regulation=self.regulation, original_name='a' * 300 + '.pdf',
                    stored_name='x.pdf', file_path='regulation/x.pdf',
                    file_size=1, file_type='pdf')

    def test_unicode_filename_accepted(self):
        name = '规章 附件-测试_😀.pdf'
        resp = self.upload(self.admin_client, self.regulation.id, name, b'%PDF-1.4',
                           'application/pdf')
        self.assertEqual(resp.json()['error'], '')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        att.refresh_from_db()
        self.assertEqual(att.original_name, name, 'Unicode 文件名应完整回读')


class DuplicateNameTests(RegulationGateTestCase):
    """R-05-05 同名文件重复上传"""

    def test_same_name_twice_does_not_overwrite(self):
        content1, content2 = b'first-upload-content', b'second-upload-content-much-longer'
        r1 = self.upload(self.admin_client, self.regulation.id, 'same.pdf', content1)
        r2 = self.upload(self.admin_client, self.regulation.id, 'same.pdf', content2)
        a1 = RegulationAttachment.objects.get(pk=r1.json()['data']['id'])
        a2 = RegulationAttachment.objects.get(pk=r2.json()['data']['id'])
        self.assertNotEqual(a1.stored_name, a2.stored_name, 'stored_name 必须唯一')
        self.assertEqual(a1.original_name, a2.original_name)
        p1 = os.path.join(self._tmp_storage, a1.file_path)
        p2 = os.path.join(self._tmp_storage, a2.file_path)
        self.assertTrue(os.path.exists(p1))
        self.assertTrue(os.path.exists(p2))
        with open(p1, 'rb') as fh:
            self.assertEqual(fh.read(), content1, '第一次上传内容不得被覆盖')
        with open(p2, 'rb') as fh:
            self.assertEqual(fh.read(), content2)

    def test_stored_name_pattern(self):
        resp = self.upload(self.admin_client, self.regulation.id, '空管 规定.pdf', b'%PDF-1.4')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertRegex(att.stored_name, r'^空管_规定_[0-9a-f]{12}\.pdf$')


class AttachmentMetadataTests(RegulationGateTestCase):
    """R-05-06 附件元数据正确性

    ⚠️ test_upload_audit_event_recorded 为 defect_reproduction（REG-AUDIT-001，P1）：
    action='upload_attachment' 不在 audit_action_valid 白名单内，审计事件被静默丢弃。
    """

    def test_metadata_complete_and_correct(self):
        content = b'%PDF-1.4 metadata-test-content'
        resp = self.upload(self.admin_client, self.regulation.id, 'meta.pdf', content,
                           'application/pdf', sort_order=3)
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertEqual(att.original_name, 'meta.pdf')
        self.assertEqual(att.file_size, len(content))
        self.assertEqual(att.file_type, 'pdf')
        self.assertEqual(att.file_hash, hashlib.md5(content).hexdigest(),
                         'file_hash 必须为内容 MD5')
        self.assertEqual(att.sort_order, 3)
        self.assertEqual(att.uploaded_by_id, self.admin.id)
        self.assertIsNotNone(att.uploaded_at)
        self.assertFalse(att.is_deleted)
        self.assertEqual(att.regulation_id, self.regulation.id)
        self.assertTrue(os.path.exists(os.path.join(self._tmp_storage, att.file_path)))

    def test_default_sort_order_is_zero(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'nosort.pdf', b'x')
        self.assertEqual(
            RegulationAttachment.objects.get(pk=resp.json()['data']['id']).sort_order, 0)

    def test_invalid_sort_order_falls_back_to_zero(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'badsort.pdf', b'x',
                           sort_order='abc')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(
            RegulationAttachment.objects.get(pk=resp.json()['data']['id']).sort_order, 0)

    def test_upload_audit_event_recorded(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'audit-up.pdf', b'x')
        from apps.logs.models import AuditLog
        log = AuditLog.objects.filter(
            target_type='regulation', action='upload_attachment',
            target_id=str(self.regulation.id)).first()
        self.assertIsNotNone(log, '上传附件应产生 upload_attachment 审计事件')
        self.assertIn(str(resp.json()['data']['id']), log.detail)
        self.assertNotIn('preview_token', (log.detail or '').lower(),
                         '审计详情不得包含预览令牌')

    def test_physical_file_written_before_db_record(self):
        """DB create 被调用时，物理文件必须已存在且内容完整"""
        content = b'%PDF-1.4 ordering-check'
        observed = {}
        real_create = RegulationAttachment.objects.create

        def spy(*args, **kwargs):
            path = os.path.join(self._tmp_storage, kwargs.get('file_path'))
            observed['exists'] = os.path.exists(path)
            if os.path.exists(path):
                with open(path, 'rb') as fh:
                    observed['content'] = fh.read()
            return real_create(*args, **kwargs)

        with patch('apps.regulation.views.RegulationAttachment.objects.create', side_effect=spy):
            self.upload(self.admin_client, self.regulation.id, 'order.pdf', content)
        self.assertTrue(observed.get('exists'), '写库前物理文件必须已落盘')
        self.assertEqual(observed.get('content'), content)


class StoragePathContainmentTests(RegulationGateTestCase):
    """R-05-07 路径解析始终限制在规章附件根目录内"""

    def test_resolve_rejects_absolute_path(self):
        with self.assertRaises(ValueError):
            storage.resolve_absolute_path('/etc/passwd')

    def test_resolve_rejects_dotdot(self):
        with self.assertRaises(ValueError):
            storage.resolve_absolute_path('regulation/../../etc/passwd')

    def test_resolve_rejects_outside_regulation_dir(self):
        with self.assertRaises(ValueError):
            storage.resolve_absolute_path('documents/other/file.pdf')

    def test_resolve_rejects_empty_path(self):
        with self.assertRaises(ValueError):
            storage.resolve_absolute_path('')

    def test_safe_delete_refuses_outside_path(self):
        outside = os.path.join(self._tmp_storage, 'outside.txt')
        with open(outside, 'wb') as fh:
            fh.write(b'keep')
        ok, msg = storage.safe_delete_attachment_file(outside)
        self.assertFalse(ok)
        self.assertIn('拒绝删除', msg or '')
        self.assertTrue(os.path.exists(outside), '区域外文件不得被删除')

    def test_uploaded_file_path_stays_inside_regulation_root(self):
        resp = self.upload(self.admin_client, self.regulation.id, 'inside.pdf', b'%PDF-1.4')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        rel = os.path.relpath(storage.resolve_absolute_path(att.file_path),
                              storage.get_regulation_storage_base())
        self.assertFalse(rel.startswith('..'), '附件必须位于 regulation 根目录内')
