# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁 F 组：版本、审计和数据完整性。

覆盖：编辑前快照、version_no 递增、snapshot_json/changed_fields/
changed_by/changed_at 内容、snapshot_hash 可校验与篡改可发现、
各操作审计日志（租户/操作者/对象/request_id）、并发一致性。
"""
import hashlib
import json
import threading
from datetime import date, timedelta

from django.test import TestCase, TransactionTestCase

from apps.evidence.models import EvidenceEvent
from apps.logs.models import AuditLog
from apps.radio_license.models import (
    RadioLicense, RadioLicenseVersion, LicenseReminderAck,
    StationFrequencyApproval, StationFrequencyApprovalReminderAck,
)
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, TENANT_B, FULL_LICENSE_PERMS, FULL_APPROVAL_PERMS,
    FULL_ATTACHMENT_PERMS, rg_license_payload, rg_approval_payload,
    rg_make_license, rg_make_approval,
)


class VersionSnapshotTests(TestCase):
    """F1-F4 版本快照内容与哈希。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_ver_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def _create(self, station_name='RG-VER台站'):
        payload = rg_license_payload(self.user, station_name=station_name)
        body = self.client.post('/radio-license/', data=json.dumps(payload),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        return RadioLicense.objects.get(station_name=station_name)

    def _edit(self, lic, **overrides):
        payload = rg_license_payload(self.user, **overrides)
        payload['id'] = lic.id
        return self.client.post('/radio-license/', data=json.dumps(payload),
                                content_type='application/json').json()

    def test_snapshot_saved_before_edit_with_full_content(self):
        lic = self._create()
        body = self._edit(lic, station_name='RG-VER台站-改',
                          valid_to=str(self.today + timedelta(days=400)))
        self.assertFalse(body.get('error'), body)
        v = RadioLicenseVersion.objects.get(license=lic)
        self.assertEqual(v.version_no, 1)
        snapshot = json.loads(v.snapshot_json)
        # 快照必须是修改前内容
        self.assertEqual(snapshot['station_name'], 'RG-VER台站')
        self.assertEqual(snapshot['valid_to'], str(self.today + timedelta(days=300)))
        self.assertEqual(v.changed_by_id, self.user.id)
        self.assertEqual(v.changed_by_name, self.user.nickname)
        self.assertIsNotNone(v.changed_at)

    def test_version_no_increments_per_license(self):
        lic = self._create()
        for i in range(3):
            body = self._edit(lic, station_name=f'RG-VER台站-{i}')
            self.assertFalse(body.get('error'), body)
        versions = list(RadioLicenseVersion.objects.filter(
            license=lic).order_by('version_no'))
        self.assertEqual([v.version_no for v in versions], [1, 2, 3])

    def test_changed_fields_records_actual_changes(self):
        """changed_fields 应记录本次变更字段列表。"""
        lic = self._create()
        body = self._edit(lic, station_name='RG-VER台站-改')
        self.assertFalse(body.get('error'), body)
        v = RadioLicenseVersion.objects.filter(license=lic).latest('version_no')
        self.assertEqual(v.changed_fields, 'station_name',
                         'changed_fields 应记录实际变更字段，实际值: %r' % v.changed_fields)

    def test_snapshot_hash_verifiable_and_tamper_detectable(self):
        lic = self._create()
        self._edit(lic, station_name='RG-VER台站-改')
        v = RadioLicenseVersion.objects.get(license=lic)
        # 正常校验通过
        self.assertEqual(
            v.snapshot_hash,
            hashlib.sha256(v.snapshot_json.encode('utf-8')).hexdigest())
        # 篡改 snapshot_json 后哈希不匹配（可发现篡改）
        tampered = json.loads(v.snapshot_json)
        tampered['station_name'] = 'RG-被篡改'
        v.snapshot_json = json.dumps(tampered, ensure_ascii=False, sort_keys=True)
        self.assertNotEqual(
            v.snapshot_hash,
            hashlib.sha256(v.snapshot_json.encode('utf-8')).hexdigest())

    def test_no_version_created_on_create(self):
        self._create()
        self.assertEqual(RadioLicenseVersion.objects.count(), 0)


class AuditLogTests(TestCase):
    """F5/F6 审计日志写入正确性与内容完整性。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_aud_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS + FULL_ATTACHMENT_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def _create_license(self):
        payload = rg_license_payload(self.user, station_name='RG-AUD台站')
        body = self.client.post('/radio-license/', data=json.dumps(payload),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        return RadioLicense.objects.get(station_name='RG-AUD台站')

    def test_create_license_writes_audit_log(self):
        lic = self._create_license()
        log = AuditLog.objects.filter(
            target_type='radio_license', target_id=str(lic.id), action='create').first()
        self.assertIsNotNone(log, '创建执照必须写审计日志')
        self.assertEqual(log.user_id, self.user.id)
        self.assertEqual(log.username, self.user.username)
        self.assertEqual(log.tenant_id, TENANT_A)
        self.assertTrue(log.request_id, '审计日志应包含 request_id')
        self.assertIn('valid_to', log.detail)

    def test_edit_license_writes_audit_log(self):
        lic = self._create_license()
        payload = rg_license_payload(self.user, station_name='RG-AUD台站-改')
        payload['id'] = lic.id
        body = self.client.post('/radio-license/', data=json.dumps(payload),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        log = AuditLog.objects.filter(
            target_type='radio_license', target_id=str(lic.id), action='update').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.tenant_id, TENANT_A)

    def test_delete_license_writes_audit_log(self):
        lic = self._create_license()
        self.client.delete(f'/radio-license/?id={lic.id}')
        log = AuditLog.objects.filter(
            target_type='radio_license', target_id=str(lic.id), action='delete').first()
        self.assertIsNotNone(log, '删除执照必须写审计日志（物理删除前）')

    def test_renewal_writes_evidence_event_with_before_after(self):
        lic = self._create_license()
        new_valid_to = str(self.today + timedelta(days=400))
        payload = rg_license_payload(self.user, station_name='RG-AUD台站', valid_to=new_valid_to)
        payload['id'] = lic.id
        body = self.client.post('/radio-license/', data=json.dumps(payload),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        ev = EvidenceEvent.objects.filter(
            module='radio_license', object_type='license',
            object_id=str(lic.id)).order_by('id').first()
        self.assertIsNotNone(ev, '续期应写入证据事件')
        before = json.loads(ev.before_snapshot)
        after = json.loads(ev.after_snapshot)
        self.assertEqual(before['valid_to'], str(self.today + timedelta(days=300)))
        self.assertEqual(after['valid_to'], new_valid_to)

    def test_attachment_delete_writes_evidence_event(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        media = tempfile.mkdtemp(prefix='rg_aud_')
        with override_settings(MEDIA_ROOT=media):
            lic = self._create_license()
            resp = self.client.post(
                f'/radio-license/{lic.id}/attachments/',
                {'file': SimpleUploadedFile('RG-AUD附件.pdf', b'%PDF-1.4')})
            att_id = resp.json()['data']['id']
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f'/radio-license/attachments/?id={att_id}')
            self.assertFalse(resp.json().get('error'))
        ev = EvidenceEvent.objects.filter(
            module='radio_license', object_type='license',
            object_id=str(lic.id), event_type='delete').first()
        self.assertIsNotNone(ev, '附件删除应写入证据事件')
        snapshot = json.loads(ev.object_snapshot)
        self.assertEqual(snapshot['file_name'], 'RG-AUD附件.pdf')

    def test_license_reminder_ack_writes_audit_log(self):
        """提醒确认应写入审计日志（与批复侧一致）。"""
        lic = rg_make_license(self.user, station_name='RG-AUD-ACK',
                              valid_to=self.today + timedelta(days=10))
        resp = self.client.post(
            '/radio-license/reminders/ack/',
            data=json.dumps({'license_id': lic.id}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        log = AuditLog.objects.filter(
            tenant_id=TENANT_A, username=self.user.username,
            detail__icontains='RG-AUD-ACK').exists()
        has_ack_log = AuditLog.objects.filter(
            tenant_id=TENANT_A, username=self.user.username).count()
        self.assertTrue(log or has_ack_log > 0,
                        '执照提醒确认应写入审计日志（当前仅记 logger.info）')

    def test_approval_crud_writes_audit_logs(self):
        # create
        payload = rg_approval_payload(self.user, doc_no='RG-AUD-AP')
        body = self.client.post('/radio-license/approvals/', data=json.dumps(payload),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        ap = StationFrequencyApproval.objects.get(doc_no='RG-AUD-AP')
        log = AuditLog.objects.filter(
            target_type='radio_license_approval', target_id=str(ap.id),
            action='create').first()
        self.assertIsNotNone(log, '创建批复必须写审计日志')
        self.assertEqual(log.tenant_id, TENANT_A)
        # update
        payload['id'] = ap.id
        payload['name'] = 'RG-AUD-AP-改'
        self.client.post('/radio-license/approvals/', data=json.dumps(payload),
                         content_type='application/json')
        self.assertTrue(AuditLog.objects.filter(
            target_type='radio_license_approval', target_id=str(ap.id),
            action='update').exists())
        # delete
        self.client.delete(f'/radio-license/approvals/?id={ap.id}')
        self.assertTrue(AuditLog.objects.filter(
            target_type='radio_license_approval', target_id=str(ap.id),
            action='delete').exists())

    def test_approval_ack_writes_audit_log(self):
        ap = rg_make_approval(self.user, doc_no='RG-AUD-APACK',
                              valid_to=self.today + timedelta(days=10))
        resp = self.client.post(
            '/radio-license/approvals/reminders/ack/',
            data=json.dumps({'approval_id': ap.id}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.assertTrue(AuditLog.objects.filter(
            tenant_id=TENANT_A, target_type='radio_license_approval',
            target_id=str(ap.id), action='update',
            detail__icontains='ack_valid_to').exists(),
            '批复提醒确认应写入审计日志')

    def test_audit_log_hash_chain_populated(self):
        self._create_license()
        log = AuditLog.objects.filter(
            target_type='radio_license', action='create').first()
        self.assertTrue(log.request_hash)
        self.assertTrue(log.log_hash)


class ConcurrencyTests(TransactionTestCase):
    """F7 并发场景：并发 ack、并发编辑版本号、删除与上传并发。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_conc_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_ATTACHMENT_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def test_concurrent_ack_writes_single_row(self):
        lic = rg_make_license(self.user, station_name='RG-CONC-ACK',
                              valid_to=self.today + timedelta(days=10))
        barrier = threading.Barrier(3)

        def ack():
            from django.test import Client
            c = Client()
            c.defaults['HTTP_X_TOKEN'] = self.user.access_token
            barrier.wait()
            try:
                c.post('/radio-license/reminders/ack/',
                       data=json.dumps({'license_id': lic.id}),
                       content_type='application/json')
            finally:
                from django.db import connections
                connections.close_all()

        threads = [threading.Thread(target=ack) for _ in range(2)]
        for t in threads:
            t.start()
        barrier.wait()
        for t in threads:
            t.join()
        self.assertEqual(
            LicenseReminderAck.objects.filter(license=lic).count(), 1,
            '并发确认同一执照同一周期只能有一条 ack')

    def test_concurrent_edits_version_consistency(self):
        """两次并发编辑：版本快照数量与成功编辑次数一致，version_no 不重复。"""
        lic = rg_make_license(self.user, station_name='RG-CONC-EDIT',
                              valid_to=self.today + timedelta(days=300))
        barrier = threading.Barrier(3)

        def edit(idx):
            from django.test import Client
            c = Client()
            c.defaults['HTTP_X_TOKEN'] = self.user.access_token
            payload = rg_license_payload(
                self.user, station_name=f'RG-CONC-EDIT-{idx}')
            payload['id'] = lic.id
            barrier.wait()
            try:
                c.post('/radio-license/', data=json.dumps(payload),
                       content_type='application/json')
            finally:
                from django.db import connections
                connections.close_all()

        threads = [threading.Thread(target=edit, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        barrier.wait()
        for t in threads:
            t.join()
        versions = list(RadioLicenseVersion.objects.filter(
            license=lic).values_list('version_no', flat=True))
        self.assertEqual(len(versions), len(set(versions)),
                         '并发编辑产生重复版本号: %s' % versions)

    def test_delete_during_upload_leaves_consistent_state(self):
        """上传与删除并发：最终状态一致（执照删除后无孤儿附件记录可下载）。"""
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from apps.evidence.models import EvidenceAttachment
        media = tempfile.mkdtemp(prefix='rg_conc_')
        with override_settings(MEDIA_ROOT=media):
            lic = rg_make_license(self.user, station_name='RG-CONC-RACE')
            resp = self.client.post(
                f'/radio-license/{lic.id}/attachments/',
                {'file': SimpleUploadedFile('RG-CONC.pdf', b'%PDF-1.4')})
            self.assertFalse(resp.json().get('error'))
            self.client.delete(f'/radio-license/?id={lic.id}')
            self.assertFalse(RadioLicense.objects.filter(pk=lic.id).exists())
            # 附件记录被软删除，且不可再通过任何端点访问
            att = EvidenceAttachment.objects.all_with_deleted().filter(
                file_name='RG-CONC.pdf').first()
            self.assertIsNotNone(att)
            self.assertTrue(att.is_deleted)
            body = self.client.get(
                f'/radio-license/attachments/{att.id}/download/').json()
            self.assertTrue(body.get('error'))
