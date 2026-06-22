# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
无线电台执照到期扫描单元测试

覆盖：
- calculate_license_status：60/0 天为 expiring，61 天为 normal，已过期为 expired
- scan_single_license：
  - expiring 状态为责任人生成 expiring_daily 提醒
  - 同一天重复扫描不重复生成
  - 不同天会生成新提醒（满足每日提醒）
  - is_handled=True 后不再生成新提醒
  - 已过期生成 expired 提醒
  - 责任人账号禁用时不生成提醒
"""
from datetime import date, timedelta
from django.test import TestCase

from apps.account.models import User
from apps.radio_license.models import (
    RadioLicense, RadioLicenseReminder,
    EXPIRING_DAILY_REMIND_TYPE, EXPIRED_REMIND_TYPE,
    EXPIRING_DAYS_THRESHOLD,
)
from apps.radio_license.tasks import (
    calculate_license_status, scan_single_license,
)


class CalculateLicenseStatusTests(TestCase):
    """状态判定：60 天阈值"""

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
        """常量保护：阈值必须为 60，防止误改"""
        self.assertEqual(EXPIRING_DAYS_THRESHOLD, 60)


class ScanSingleLicenseTests(TestCase):
    """单执照扫描逻辑"""

    def setUp(self):
        self.user = User.objects.create(
            username='test_responsible',
            nickname='测试责任人',
            password_hash='x',
            is_active=True,
            access_token='test_token_xxxxxxxx',
            tenant_id='test_tenant',
        )
        self.today = date(2026, 6, 22)
        # 30 天后到期 → expiring
        self.license = RadioLicense.objects.create(
            tenant_id='test_tenant',
            station_name='测试台站',
            purpose='测试用途',
            valid_from=self.today - timedelta(days=335),
            valid_to=self.today + timedelta(days=30),
            responsible_user_id=self.user.id,
            responsible_user_name=self.user.nickname,
            status='normal',
            created_by=self.user,
        )

    def test_expiring_generates_daily_reminder_to_responsible(self):
        """expiring 状态为责任人生成 expiring_daily 提醒"""
        result = scan_single_license(self.license, today=self.today)
        self.assertEqual(result['status'], 'expiring')
        self.assertEqual(result['new_reminders'], 1)
        reminder = RadioLicenseReminder.objects.get(license=self.license)
        self.assertEqual(reminder.remind_type, EXPIRING_DAILY_REMIND_TYPE)
        self.assertEqual(reminder.receiver_user_id, self.user.id)
        self.assertEqual(reminder.receiver_user_name, self.user.nickname)
        self.assertEqual(reminder.remind_date, self.today)
        self.assertFalse(reminder.is_handled)
        # 执照 status 应被更新为 expiring
        self.license.refresh_from_db()
        self.assertEqual(self.license.status, 'expiring')

    def test_same_day_rescan_does_not_duplicate(self):
        """同一天重复扫描不会重复生成"""
        scan_single_license(self.license, today=self.today)
        scan_single_license(self.license, today=self.today)
        scan_single_license(self.license, today=self.today)
        self.assertEqual(
            RadioLicenseReminder.objects.filter(
                license=self.license,
                remind_type=EXPIRING_DAILY_REMIND_TYPE,
                remind_date=self.today,
            ).count(),
            1,
        )

    def test_different_days_generate_new_reminders(self):
        """不同天生成新提醒（满足每日提醒需求）"""
        day1 = self.today
        day2 = self.today + timedelta(days=1)
        day3 = self.today + timedelta(days=2)

        scan_single_license(self.license, today=day1)
        scan_single_license(self.license, today=day2)
        scan_single_license(self.license, today=day3)

        reminders = RadioLicenseReminder.objects.filter(
            license=self.license,
            remind_type=EXPIRING_DAILY_REMIND_TYPE,
        ).order_by('remind_date')
        self.assertEqual(reminders.count(), 3)
        self.assertEqual(reminders[0].remind_date, day1)
        self.assertEqual(reminders[1].remind_date, day2)
        self.assertEqual(reminders[2].remind_date, day3)

    def test_handled_stops_new_reminders(self):
        """is_handled=True 后不再生成新提醒（同一 valid_to 周期）"""
        # 第一天生成提醒
        scan_single_license(self.license, today=self.today)
        self.assertEqual(
            RadioLicenseReminder.objects.filter(license=self.license).count(), 1
        )
        # 标记已处理
        reminder = RadioLicenseReminder.objects.get(license=self.license)
        reminder.is_handled = True
        reminder.is_read = True
        reminder.save()
        # 第二天再扫描，不应生成新提醒
        next_day = self.today + timedelta(days=1)
        result = scan_single_license(self.license, today=next_day)
        self.assertEqual(result['new_reminders'], 0)
        self.assertEqual(
            RadioLicenseReminder.objects.filter(license=self.license).count(), 1
        )

    def test_renewal_after_handled_allows_new_reminders(self):
        """续期后 valid_to 变化，旧 is_handled 记录不阻止新周期提醒"""
        # 第一天生成提醒并处理
        scan_single_license(self.license, today=self.today)
        reminder = RadioLicenseReminder.objects.get(license=self.license)
        reminder.is_handled = True
        reminder.is_read = True
        reminder.save()
        # 续期：valid_to 延后 100 天（重新进入 normal，再过 40 天才进入 expiring）
        new_valid_to = self.today + timedelta(days=100)
        RadioLicense.objects.filter(pk=self.license.id).update(valid_to=new_valid_to)
        self.license.refresh_from_db()
        # 把"今天"推进到续期后的 50 天（valid_to 前 50 天，处于 expiring）
        future_today = new_valid_to - timedelta(days=50)
        result = scan_single_license(self.license, today=future_today)
        self.assertEqual(result['status'], 'expiring')
        self.assertEqual(result['new_reminders'], 1)

    def test_expired_generates_expired_reminder(self):
        """已过期生成 expired 提醒"""
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today - timedelta(days=5)
        )
        self.license.refresh_from_db()
        result = scan_single_license(self.license, today=self.today)
        self.assertEqual(result['status'], 'expired')
        self.assertEqual(result['new_reminders'], 1)
        reminder = RadioLicenseReminder.objects.get(license=self.license)
        self.assertEqual(reminder.remind_type, EXPIRED_REMIND_TYPE)
        self.assertEqual(reminder.receiver_user_id, self.user.id)

    def test_expired_same_period_only_once(self):
        """同一过期周期 expired 提醒只生成一次"""
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today - timedelta(days=5)
        )
        self.license.refresh_from_db()
        scan_single_license(self.license, today=self.today)
        scan_single_license(self.license, today=self.today + timedelta(days=1))
        scan_single_license(self.license, today=self.today + timedelta(days=2))
        self.assertEqual(
            RadioLicenseReminder.objects.filter(
                license=self.license,
                remind_type=EXPIRED_REMIND_TYPE,
            ).count(),
            1,
        )

    def test_normal_status_no_reminder(self):
        """normal 状态不生成提醒"""
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today + timedelta(days=100)
        )
        self.license.refresh_from_db()
        result = scan_single_license(self.license, today=self.today)
        self.assertEqual(result['status'], 'normal')
        self.assertEqual(result['new_reminders'], 0)
        self.assertFalse(
            RadioLicenseReminder.objects.filter(license=self.license).exists()
        )

    def test_inactive_responsible_no_reminder(self):
        """责任人账号禁用时不生成提醒"""
        self.user.is_active = False
        self.user.save()
        result = scan_single_license(self.license, today=self.today)
        self.assertEqual(result['new_reminders'], 0)
        self.assertFalse(
            RadioLicenseReminder.objects.filter(license=self.license).exists()
        )

    def test_empty_responsible_no_reminder(self):
        """责任人为空时不生成提醒"""
        RadioLicense.objects.filter(pk=self.license.id).update(
            responsible_user_id=None,
            responsible_user_name='',
        )
        self.license.refresh_from_db()
        result = scan_single_license(self.license, today=self.today)
        self.assertEqual(result['new_reminders'], 0)
        self.assertFalse(
            RadioLicenseReminder.objects.filter(license=self.license).exists()
        )

    def test_dedup_ignores_handled_reminders(self):
        """去重查询忽略已处理的旧记录，允许当天生成新提醒

        场景：编辑执照把 valid_to 改了，旧提醒被作废（is_handled=True），
        同一天 scan_single_license 应能生成内容正确的新提醒。
        """
        # 第一天生成提醒（days_left=30）
        scan_single_license(self.license, today=self.today)
        old_reminder = RadioLicenseReminder.objects.get(license=self.license)
        self.assertEqual(old_reminder.days_left, 30)
        # 模拟编辑执照作废旧提醒 + 修改 valid_to（提前到 10 天后到期）
        RadioLicenseReminder.objects.filter(
            license=self.license, is_handled=False
        ).update(is_handled=True, is_read=True)
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today + timedelta(days=10)
        )
        self.license.refresh_from_db()
        # 同一天再扫描：应生成新提醒（days_left=10），旧已处理记录不阻止
        result = scan_single_license(self.license, today=self.today)
        self.assertEqual(result['new_reminders'], 1)
        new_reminder = RadioLicenseReminder.objects.filter(
            license=self.license, is_handled=False
        ).get()
        self.assertEqual(new_reminder.days_left, 10)
        self.assertIn('10 天后到期', new_reminder.content)
        # 旧提醒仍在，但已标记为已处理
        self.assertTrue(
            RadioLicenseReminder.objects.filter(
                license=self.license, is_handled=True
            ).exists()
        )

    def test_valid_to_change_invalidates_old_reminders(self):
        """valid_to 变化后旧未处理提醒内容不再展示（由 view 层作废）

        这里只验证 _generate_reminder 在旧记录被作废后能生成新内容提醒，
        view 层的作废逻辑通过 integration 验证。
        """
        # 生成旧提醒
        scan_single_license(self.license, today=self.today)
        self.assertEqual(
            RadioLicenseReminder.objects.filter(
                license=self.license, is_handled=False
            ).count(),
            1,
        )
        # 作废旧提醒（模拟 view 层 valid_to 变更时的处理）
        RadioLicenseReminder.objects.filter(
            license=self.license, is_handled=False
        ).update(is_handled=True, is_read=True)
        # 修改 valid_to 并重新扫描
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today + timedelta(days=5)
        )
        self.license.refresh_from_db()
        scan_single_license(self.license, today=self.today)
        # 新提醒内容应反映新的 days_left=5
        new_reminder = RadioLicenseReminder.objects.filter(
            license=self.license, is_handled=False
        ).get()
        self.assertEqual(new_reminder.days_left, 5)
        self.assertIn('5 天后到期', new_reminder.content)

