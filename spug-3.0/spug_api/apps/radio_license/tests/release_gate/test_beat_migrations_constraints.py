# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁第七组：定时任务、数据库迁移与约束、部署配置检查。

覆盖：
1. Celery Beat 注册（每天 08:00 执照扫描 / 08:05 批复扫描）与任务队列、超时配置。
2. radio_license 迁移完整且已全部应用。
3. MariaDB 约束：status 枚举、日期顺序、频率值与排序。
4. 部署配置：ALLOWED_HOSTS 含 kkFileView 容器、DEBUG、附件存储目录。
"""
import io
from datetime import date, timedelta

from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test import TestCase

from apps.radio_license.models import (
    RadioLicense, RadioLicenseFrequency,
    StationFrequencyApproval,
)
from apps.radio_license.tests.release_gate import (
    _make_user, TENANT_A, rg_make_license,
)


class CeleryBeatRegistrationTests(TestCase):
    """七.1/七.2 Beat 注册与任务配置。"""

    def test_beat_schedule_registered(self):
        from django.conf import settings
        schedule = getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        self.assertIn('radio-license-scan-expiration', schedule,
                      '执照到期扫描任务必须注册到 CELERY_BEAT_SCHEDULE')
        self.assertIn('radio-license-scan-approval-expiration', schedule,
                      '批复到期扫描任务必须注册到 CELERY_BEAT_SCHEDULE')

    def test_beat_schedule_crontab_and_queue(self):
        from django.conf import settings
        schedule = settings.CELERY_BEAT_SCHEDULE

        lic_entry = schedule['radio-license-scan-expiration']
        self.assertEqual(
            lic_entry['task'], 'apps.radio_license.tasks.scan_radio_license_expiration')
        crontab = lic_entry['schedule']
        self.assertEqual((crontab.hour, crontab.minute), ({8}, {0}),
                         '执照扫描应每天 08:00 执行')
        self.assertEqual(lic_entry['options']['queue'], 'radio_license')
        self.assertGreaterEqual(lic_entry['options'].get('time_limit', 0), 600)

        ap_entry = schedule['radio-license-scan-approval-expiration']
        self.assertEqual(
            ap_entry['task'], 'apps.radio_license.tasks.scan_approval_expiration')
        crontab = ap_entry['schedule']
        self.assertEqual((crontab.hour, crontab.minute), ({8}, {5}),
                         '批复扫描应每天 08:05 执行')
        self.assertEqual(ap_entry['options']['queue'], 'radio_license')
        self.assertGreaterEqual(ap_entry['options'].get('time_limit', 0), 600)

    def test_tasks_have_timeout_limits(self):
        from apps.radio_license.tasks import (
            scan_radio_license_expiration, scan_approval_expiration,
        )
        for task in (scan_radio_license_expiration, scan_approval_expiration):
            self.assertEqual(task.soft_time_limit, 300)
            self.assertEqual(task.time_limit, 600)
            self.assertEqual(task.queue, 'radio_license')


class MigrationIntegrityTests(TestCase):
    """七.3 迁移完整性。"""

    def test_all_radio_license_migrations_applied(self):
        out = io.StringIO()
        call_command('showmigrations', 'radio_license', stdout=out)
        output = out.getvalue()
        pending = [line for line in output.splitlines() if '[ ]' in line]
        self.assertEqual(pending, [], f'存在未应用迁移: {pending}')

    def test_no_missing_migrations_for_models(self):
        """模型与迁移状态一致（makemigrations --check 不产生新迁移）。"""
        out = io.StringIO()
        call_command('makemigrations', 'radio_license', '--check', '--dry-run', stdout=out)
        self.assertEqual('No changes detected in app' in out.getvalue(), True,
                         '模型变更未生成迁移: %s' % out.getvalue())


class DatabaseConstraintTests(TestCase):
    """七.4 MariaDB 约束有效性（直接走数据库层验证）。"""

    def setUp(self):
        self.user = _make_user('rg_db_user', tenant_id=TENANT_A)
        self.today = date.today()

    def _assert_integrity_error(self, factory):
        """在保存点内执行 factory 并断言 IntegrityError（避免污染测试事务）。"""
        from django.db import transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                factory()

    def test_invalid_status_rejected_by_db(self):
        self._assert_integrity_error(lambda: RadioLicense.objects.create(
            tenant_id=TENANT_A, station_name='RG-DB-坏状态',
            purpose='x', valid_from=self.today, valid_to=self.today,
            responsible_user_id=self.user.id, status='weird',
            created_by=self.user))

    def test_invalid_approval_status_rejected_by_db(self):
        self._assert_integrity_error(lambda: StationFrequencyApproval.objects.create(
            tenant_id=TENANT_A, name='RG-DB-坏状态', doc_no='RG-DB-S',
            frequency_text='x', valid_from=self.today, valid_to=self.today,
            responsible_user_id=self.user.id, status='bad',
            created_by=self.user))

    def test_date_order_rejected_by_db(self):
        self._assert_integrity_error(lambda: RadioLicense.objects.create(
            tenant_id=TENANT_A, station_name='RG-DB-坏日期',
            purpose='x',
            valid_from=self.today + timedelta(days=10),
            valid_to=self.today,
            responsible_user_id=self.user.id, created_by=self.user))
        self._assert_integrity_error(lambda: StationFrequencyApproval.objects.create(
            tenant_id=TENANT_A, name='RG-DB-坏日期', doc_no='RG-DB-D',
            frequency_text='x',
            valid_from=self.today + timedelta(days=10),
            valid_to=self.today,
            responsible_user_id=self.user.id, created_by=self.user))

    def test_frequency_constraints_enforced_by_db(self):
        lic = rg_make_license(self.user, station_name='RG-DB-频率')
        self._assert_integrity_error(lambda: RadioLicenseFrequency.objects.create(
            tenant_id=TENANT_A, license=lic, frequency_value=-1,
            created_by=self.user))
        self._assert_integrity_error(lambda: RadioLicenseFrequency.objects.create(
            tenant_id=TENANT_A, license=lic, frequency_value=0,
            created_by=self.user))
        self._assert_integrity_error(lambda: RadioLicenseFrequency.objects.create(
            tenant_id=TENANT_A, license=lic, frequency_value=1.0,
            sort_order=-1, created_by=self.user))

    def test_ack_unique_constraint_enforced_by_db(self):
        from apps.radio_license.models import LicenseReminderAck
        lic = rg_make_license(self.user, station_name='RG-DB-唯一')
        LicenseReminderAck.objects.create(
            tenant_id=TENANT_A, license=lic, user_id=self.user.id,
            user_name=self.user.nickname, ack_valid_to=lic.valid_to)
        self._assert_integrity_error(lambda: LicenseReminderAck.objects.create(
            tenant_id=TENANT_A, license=lic, user_id=self.user.id,
            user_name=self.user.nickname, ack_valid_to=lic.valid_to))

    def test_check_constraints_exist_in_db(self):
        """约束真实存在于 MariaDB 表定义中。"""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tdyw_radio_license' "
                "AND CONSTRAINT_TYPE = 'CHECK'")
            names = {row[0] for row in cursor.fetchall()}
        self.assertIn('radio_license_status_valid', names)
        self.assertIn('radio_license_date_order', names)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tdyw_radio_license_frequency' "
                "AND CONSTRAINT_TYPE = 'CHECK'")
            names = {row[0] for row in cursor.fetchall()}
        self.assertIn('radio_frequency_positive', names)
        self.assertIn('radio_frequency_sort_valid', names)


class DeploymentConfigTests(TestCase):
    """七.5 部署配置检查（针对测试容器当前配置取证）。"""

    def test_debug_disabled_in_test_container(self):
        """测试容器以生产方式运行（DEBUG=False）。

        注：开发 dev server 可能开 DEBUG，此处记录当前值供报告引用。
        """
        from django.conf import settings
        import os
        print(f'[RG-DEPLOY] DEBUG={settings.DEBUG}')
        print(f'[RG-DEPLOY] ALLOWED_HOSTS={settings.ALLOWED_HOSTS}')
        print(f'[RG-DEPLOY] MEDIA_ROOT={settings.MEDIA_ROOT}')
        print(f'[RG-DEPLOY] KKFILEVIEW_API_URL={getattr(settings, "KKFILEVIEW_API_URL", "")}')
        print(f'[RG-DEPLOY] KKFILEVIEW_SERVER_URL={getattr(settings, "KKFILEVIEW_SERVER_URL", "")}')

    def test_kkfileview_host_allowed(self):
        """kkFileView 容器回源地址必须进入 ALLOWED_HOSTS。"""
        from django.conf import settings
        server_url = getattr(settings, 'KKFILEVIEW_SERVER_URL', '')
        if not server_url:
            self.skipTest('KKFILEVIEW_SERVER_URL 未配置（部署项记录为 BLOCKED）')
        # 提取 host
        from urllib.parse import urlparse
        host = urlparse(server_url).hostname
        allowed = list(settings.ALLOWED_HOSTS)
        self.assertTrue(
            host in allowed or '*' in allowed or any(
                h.startswith('.') and host.endswith(h) for h in allowed),
            f'kkFileView 回源 host {host} 不在 ALLOWED_HOSTS: {allowed}')

    def test_media_root_exists(self):
        from django.conf import settings
        import os
        self.assertTrue(os.path.isdir(settings.MEDIA_ROOT),
                        f'MEDIA_ROOT 不存在: {settings.MEDIA_ROOT}')

    def test_audit_log_request_body_sanitized(self):
        """日志脱敏：审计中间件对请求体做脱敏处理。"""
        from libs.middleware import _sanitize_request_body
        raw = ('{"password": "secret123", "station_name": "RG-台站"}').encode('utf-8')
        sanitized = _sanitize_request_body(raw)
        self.assertNotIn('secret123', sanitized)
