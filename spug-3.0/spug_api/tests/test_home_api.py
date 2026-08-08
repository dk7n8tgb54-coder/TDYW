# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase, Client
from apps.account.models import User
from apps.setting.utils import AppSetting
import json


class HomeAPITest(TestCase):
    """首页模块API测试"""

    def setUp(self):
        """测试前准备"""
        import time
        token = 'a' * 32

        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
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

    def test_navigation_removed(self):
        """Navigation 接口已删除，返回 404"""
        response = self.client.get('/home/navigation/')
        self.assertEqual(response.status_code, 404)

    def test_unauthorized_access(self):
        """测试未授权访问"""
        del self.client.defaults['HTTP_X_TOKEN']
        response = self.client.get('/home/statistic/')
        self.assertEqual(response.status_code, 401)
