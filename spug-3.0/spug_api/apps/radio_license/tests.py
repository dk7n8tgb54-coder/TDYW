# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
Radio license expiration scan tests.

The reminder history table has been removed. The scanner only maintains
RadioLicense.status; popup reminders are queried in real time and acknowledged
through LicenseReminderAck.
"""
from datetime import date, timedelta

from django.test import TestCase

from apps.account.models import User
from apps.radio_license.models import RadioLicense, EXPIRING_DAYS_THRESHOLD
from apps.radio_license.tasks import calculate_license_status, scan_single_license


class CalculateLicenseStatusTests(TestCase):
    """Status calculation uses the shared 60-day threshold."""

    def test_60_days_is_expiring(self):
        today = date(2026, 6, 22)
        status, days_left = calculate_license_status(today + timedelta(days=60), today)
        self.assertEqual(status, 'expiring')
        self.assertEqual(days_left, 60)

    def test_0_days_is_expiring(self):
        today = date(2026, 6, 22)
        status, days_left = calculate_license_status(today, today)
        self.assertEqual(status, 'expiring')
        self.assertEqual(days_left, 0)

    def test_61_days_is_normal(self):
        today = date(2026, 6, 22)
        status, days_left = calculate_license_status(today + timedelta(days=61), today)
        self.assertEqual(status, 'normal')
        self.assertEqual(days_left, 61)

    def test_expired(self):
        today = date(2026, 6, 22)
        status, days_left = calculate_license_status(today - timedelta(days=1), today)
        self.assertEqual(status, 'expired')
        self.assertEqual(days_left, -1)

    def test_threshold_is_60(self):
        self.assertEqual(EXPIRING_DAYS_THRESHOLD, 60)


class ScanSingleLicenseTests(TestCase):
    """Single-license scan updates status without creating reminder logs."""

    def setUp(self):
        self.user = User.objects.create(
            username='test_responsible',
            nickname='test_responsible',
            password_hash='x',
            is_active=True,
            access_token='test_token_xxxxxxxx',
            tenant_id='test_tenant',
        )
        self.today = date(2026, 6, 22)
        self.license = RadioLicense.objects.create(
            tenant_id='test_tenant',
            station_name='test_station',
            purpose='test',
            valid_from=self.today - timedelta(days=335),
            valid_to=self.today + timedelta(days=30),
            responsible_user_id=self.user.id,
            responsible_user_name=self.user.nickname,
            status='normal',
            created_by=self.user,
        )

    def test_expiring_updates_status(self):
        result = scan_single_license(self.license, today=self.today)

        self.assertEqual(result, {
            'status': 'expiring',
            'days_left': 30,
            'updated': True,
        })
        self.license.refresh_from_db()
        self.assertEqual(self.license.status, 'expiring')

    def test_same_status_rescan_is_not_updated(self):
        scan_single_license(self.license, today=self.today)
        result = scan_single_license(self.license, today=self.today)

        self.assertEqual(result['status'], 'expiring')
        self.assertEqual(result['days_left'], 30)
        self.assertFalse(result['updated'])

    def test_expired_updates_status(self):
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today - timedelta(days=5)
        )
        self.license.refresh_from_db()

        result = scan_single_license(self.license, today=self.today)

        self.assertEqual(result, {
            'status': 'expired',
            'days_left': -5,
            'updated': True,
        })
        self.license.refresh_from_db()
        self.assertEqual(self.license.status, 'expired')

    def test_normal_status_does_not_change_when_already_normal(self):
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today + timedelta(days=100),
            status='normal',
        )
        self.license.refresh_from_db()

        result = scan_single_license(self.license, today=self.today)

        self.assertEqual(result, {
            'status': 'normal',
            'days_left': 100,
            'updated': False,
        })
        self.license.refresh_from_db()
        self.assertEqual(self.license.status, 'normal')
