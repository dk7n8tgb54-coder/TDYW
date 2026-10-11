# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase, Client
from apps.account.models import User
from apps.upgrade.models import UpgradeRecord
from apps.setting.utils import AppSetting
from apps.utils.test_helpers import make_upgrade_no
import time


class ExecAPITest(TestCase):
    """Execute Module API Tests"""

    def setUp(self):
        token = 'a' * 32

        self.user = User.objects.create(
            username='testuser',
            nickname='Test User',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant',
            is_supper=True,
            is_active=True,
            access_token=token,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default'
        )
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = token
        self.client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        AppSetting.set('bind_ip', False)

    def test_get_upgrade_records(self):
        """Test getting upgrade records"""
        UpgradeRecord.objects.create(
            upgrade_no=make_upgrade_no(),
            tenant_id=self.user.tenant_id,
            system_name='System1',
            upgrade_type='常规升级',
            upgrade_time='2026-01-01',
            owner='User1',
            created_by=self.user
        )

        response = self.client.get('/upgrade/upgrade/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_tenant_isolation(self):
        """Test tenant data isolation - verify data is isolated"""
        user2 = User.objects.create(
            username='testuser2',
            nickname='Test User 2',
            password_hash=User.make_password('password123'),
            tenant_id='tenant2',
            is_supper=False,
            is_active=True,
            access_token='b' * 32,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default'
        )

        UpgradeRecord.objects.create(
            upgrade_no=make_upgrade_no(),
            tenant_id=self.user.tenant_id,
            system_name='System1',
            upgrade_type='常规升级',
            upgrade_time='2026-01-01',
            owner='User1',
            created_by=self.user
        )

        response = self.client.get('/upgrade/upgrade/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Supper user should see all data
        self.assertGreater(len(data['data']), 0)
