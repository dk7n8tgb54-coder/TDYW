# -*- coding: utf-8 -*-
"""审计日志与异步任务稳定契约测试。"""
from datetime import timedelta

from django.conf import settings

from apps.contract_agreement.models import ContractAgreement
from apps.contract_agreement.tasks import scan_contract_agreement_expiration
from apps.logs.models import AuditLog
from .base import ContractTestCase, make_agreement, build_payload

ACK_URL = '/contract-agreement/reminders/ack/'


class AuditLogTest(ContractTestCase):
    """写操作必须产生审计记录（操作者 / 租户 / 目标对象 / 动作 / 关键字段）"""

    def _latest(self, action):
        return AuditLog.objects.filter(
            target_type='contract_agreement', action=action).order_by('-id').first()

    def test_create_audit(self):
        body = self.post_json(build_payload(self.user, contract_name='审计新增合同'))
        self.assertNoError(body)
        log = self._latest('create')
        self.assertIsNotNone(log, '新增必须写审计日志')
        self.assertEqual(log.username, self.user.username)
        self.assertEqual(log.tenant_id, 'admin')
        self.assertEqual(log.target_name, '审计新增合同')
        self.assertEqual(int(log.target_id), body['data']['id'])
        self.assertIn('contract_type', log.detail)
        self.assertIn('valid_end_date', log.detail)
        self.assertTrue(log.is_success)
        self.assertTrue(log.log_hash, '审计日志应写入哈希链')

    def test_update_audit(self):
        created = self.post_json(build_payload(self.user, contract_name='审计编辑合同'))
        pk = created['data']['id']
        self.post_json({'id': pk, 'contract_name': '审计编辑合同-改'})
        log = self._latest('update')
        self.assertIsNotNone(log, '编辑必须写审计日志')
        self.assertEqual(int(log.target_id), pk)
        self.assertEqual(log.username, self.user.username)
        self.assertIn('contract_type', log.detail)

    def test_delete_audit(self):
        created = self.post_json(build_payload(self.user, contract_name='审计删除合同'))
        pk = created['data']['id']
        self.delete_json({'id': pk})
        log = self._latest('delete')
        self.assertIsNotNone(log, '删除必须写审计日志')
        self.assertEqual(int(log.target_id), pk)
        self.assertEqual(log.username, self.user.username)

    def test_reminder_ack_audit(self):
        ag = make_agreement(self.user, contract_name='审计提醒合同',
                            valid_end_date=self.today - timedelta(days=2),
                            responsible_user_id=self.user.id)
        self.post_json({'agreement_id': ag.id}, url=ACK_URL)
        log = AuditLog.objects.filter(
            target_type='contract_agreement', action='other').order_by('-id').first()
        self.assertIsNotNone(log, '提醒确认必须写审计日志')
        self.assertIn('reminder_ack', log.detail)
        self.assertEqual(log.username, self.user.username)

    def test_failed_operation_does_not_write_success_audit(self):
        """校验失败的操作必须被审计为失败，不能记为成功。"""
        self.post_json(build_payload(self.user, contract_name=''))
        self.post_json(build_payload(self.user, contract_type='bad_type'))
        success_logs = AuditLog.objects.filter(
            target_type='contract_agreement', action='create', is_success=True)
        self.assertEqual(success_logs.count(), 0, '校验失败不应写「成功」审计记录')
        failed_logs = AuditLog.objects.filter(
            target_type='contract_agreement', action='create', is_success=False)
        self.assertEqual(failed_logs.count(), 2, '校验失败应被审计为失败')
        self.assertFalse(
            ContractAgreement.objects.filter(contract_name='').exists())

    def test_failed_edit_does_not_write_success_audit(self):
        created = self.post_json(build_payload(self.user, contract_name='失败编辑合同'))
        pk = created['data']['id']
        before = AuditLog.objects.filter(
            target_type='contract_agreement', action='update', is_success=True).count()
        self.post_json({'id': pk, 'contract_name': '失败编辑合同',
                        'contract_type': 'service_guarantee',
                        'valid_start_date': str(self.today),
                        'valid_end_date': str(self.today - timedelta(days=1)),
                        'has_fee': False, 'signing_party': 'X',
                        'responsible_user_id': self.user.id,
                        'responsible_user_name': self.user.nickname})
        after = AuditLog.objects.filter(
            target_type='contract_agreement', action='update', is_success=True).count()
        self.assertEqual(after, before, '编辑校验失败不应写「成功」审计记录')


class CeleryTaskConfigTest(ContractTestCase):
    """Celery 任务与 Beat 调度配置"""

    def test_beat_schedule_registered(self):
        entry = settings.CELERY_BEAT_SCHEDULE.get('contract-agreement-scan-expiration')
        self.assertIsNotNone(entry, 'CONTRACT_AGREEMENT_BEAT_SCHEDULE 必须注册到 settings')
        self.assertEqual(
            entry['task'],
            'apps.contract_agreement.tasks.scan_contract_agreement_expiration')

    def test_beat_schedule_queue_and_time_limit(self):
        entry = settings.CELERY_BEAT_SCHEDULE['contract-agreement-scan-expiration']
        self.assertEqual(entry['options']['queue'], 'contract_agreement')
        self.assertEqual(entry['options']['time_limit'], 600)

    def test_beat_schedule_cron(self):
        entry = settings.CELERY_BEAT_SCHEDULE['contract-agreement-scan-expiration']
        schedule = entry['schedule']
        hour = schedule._orig_hour
        minute = schedule._orig_minute
        hour_set = hour if isinstance(hour, (set, frozenset)) else {hour}
        minute_set = minute if isinstance(minute, (set, frozenset)) else {minute}
        self.assertEqual(hour_set, {8}, '扫描任务应在每天 8 点触发')
        self.assertEqual(minute_set, {10}, '扫描任务应在 8:10 触发')

    def test_task_routing(self):
        self.assertEqual(scan_contract_agreement_expiration.queue, 'contract_agreement')
        self.assertEqual(scan_contract_agreement_expiration.time_limit, 600)
        self.assertEqual(scan_contract_agreement_expiration.soft_time_limit, 300)

    def test_scan_task_is_scoped_to_all_tenants(self):
        """到期扫描是全局任务，必须覆盖所有租户的合同。"""
        other = make_agreement(self.user, contract_name='他租户扫描合同',
                               tenant_id='t_scan',
                               valid_end_date=self.today - timedelta(days=3))
        result = scan_contract_agreement_expiration.apply().get()
        other.refresh_from_db()
        self.assertEqual(other.status, 'expired')
        self.assertGreaterEqual(result['total'], 1)

    def test_scan_task_repeat_does_not_duplicate_data(self):
        before = ContractAgreement.objects.count()
        scan_contract_agreement_expiration.apply()
        scan_contract_agreement_expiration.apply()
        self.assertEqual(ContractAgreement.objects.count(), before)

    def test_scan_task_audit_written_on_change(self):
        make_agreement(self.user, contract_name='扫描审计合同',
                       valid_end_date=self.today - timedelta(days=3))
        scan_contract_agreement_expiration.apply()
        log = AuditLog.objects.filter(
            target_type='contract_agreement', username='system').order_by('-id').first()
        self.assertIsNotNone(log, 'Celery 扫描产生状态变更时应写审计日志')
        self.assertIn('updated', log.detail)

    def test_scan_task_no_audit_when_nothing_changed(self):
        make_agreement(self.user, contract_name='无变更扫描审计',
                       valid_end_date=self.today - timedelta(days=3))
        scan_contract_agreement_expiration.apply()
        before = AuditLog.objects.filter(username='system').count()
        scan_contract_agreement_expiration.apply()
        after = AuditLog.objects.filter(username='system').count()
        self.assertEqual(after, before, '无变更的重复扫描不应重复写审计日志')
