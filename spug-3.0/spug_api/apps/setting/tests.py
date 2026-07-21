# -*- coding: utf-8 -*-
"""系统设置模块测试

覆盖：
- SettingView（系统设置，超管专用）：读/写设置
- UserSettingView（个人设置，登录即可）：读/写/用户隔离
- MFAView：权限校验 + wx_token 缺失提示
- email_test：权限校验 + 参数校验 + mock 发邮件
- get_about：版本信息返回
- AppSetting 工具类：get/get_default/set/delete + lru_cache 隔离
"""
import json
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.setting.models import Setting, UserSetting
from apps.setting.utils import AppSetting
from apps.utils.test_helpers import make_user, make_client, setup_test_env


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SettingViewTest(TestCase):
    """系统设置视图测试（超管专用，AdminView 无 PERM_MAP）"""

    def setUp(self):
        setup_test_env(self)
        # AppSetting.get 有 lru_cache，测试间需清缓存避免串读
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        self.supper = make_user('supper', is_supper=True)
        self.normal = make_user('normal', ['system.setting.view'])
        self.supper_client = make_client(self.supper)
        self.normal_client = make_client(self.normal)

    def test_get_returns_defaults_when_empty(self):
        """无任何设置时返回 KEYS_DEFAULT"""
        Setting.objects.all().delete()
        AppSetting.get.cache_clear()
        r = self.supper_client.get('/setting/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertIn('MFA', body['data'])
        self.assertIn('verify_ip', body['data'])

    def test_get_returns_stored_values(self):
        AppSetting.set('verify_ip', False)
        AppSetting.get.cache_clear()
        r = self.supper_client.get('/setting/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['verify_ip'], False)

    def test_post_updates_setting(self):
        r = self.supper_client.post(
            '/setting/',
            data=json.dumps({'data': [{'key': 'verify_ip', 'value': False}]}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        setting = Setting.objects.get(key='verify_ip')
        self.assertEqual(setting.real_val, False)

    def test_post_denied_for_non_supper(self):
        """AdminView 无 PERM_MAP，非超管被直接拒绝"""
        r = self.normal_client.post(
            '/setting/',
            data=json.dumps({'data': [{'key': 'verify_ip', 'value': False}]}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_get_denied_for_non_supper(self):
        r = self.normal_client.get('/setting/')
        self.assertTrue(r.json().get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UserSettingViewTest(TestCase):
    """个人设置视图测试（任何登录用户可访问自己的设置）"""

    def setUp(self):
        setup_test_env(self)
        self.user1 = make_user('user1', [])
        self.user2 = make_user('user2', [])
        self.client1 = make_client(self.user1)
        self.client2 = make_client(self.user2)

    def test_get_returns_empty_when_no_settings(self):
        r = self.client1.get('/setting/user/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data'], {})

    def test_post_creates_setting(self):
        r = self.client1.post(
            '/setting/user/',
            data=json.dumps({'key': 'theme', 'value': 'dark'}),
            content_type='application/json',
        )
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['theme'], 'dark')
        self.assertTrue(
            UserSetting.objects.filter(user=self.user1, key='theme').exists()
        )

    def test_post_updates_existing_setting(self):
        UserSetting.objects.create(user=self.user1, key='theme', value='light')
        self.client1.post(
            '/setting/user/',
            data=json.dumps({'key': 'theme', 'value': 'dark'}),
            content_type='application/json',
        )
        us = UserSetting.objects.get(user=self.user1, key='theme')
        self.assertEqual(us.value, 'dark')

    def test_user_isolation(self):
        """用户 A 的设置用户 B 看不到"""
        self.client1.post(
            '/setting/user/',
            data=json.dumps({'key': 'theme', 'value': 'dark'}),
            content_type='application/json',
        )
        r = self.client2.get('/setting/user/')
        self.assertEqual(r.json()['data'], {})

    def test_post_missing_key_returns_error(self):
        r = self.client1.post(
            '/setting/user/',
            data=json.dumps({'value': 'dark'}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AboutViewTest(TestCase):
    """get_about 接口测试（@auth('admin')）"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.normal = make_user('normal', [])
        self.supper_client = make_client(self.supper)
        self.normal_client = make_client(self.normal)

    def test_get_about_as_supper(self):
        r = self.supper_client.get('/setting/about/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertIn('python_version', body['data'])
        self.assertIn('django_version', body['data'])
        self.assertIn('spug_version', body['data'])

    def test_get_about_denied_for_non_supper(self):
        r = self.normal_client.get('/setting/about/')
        self.assertTrue(r.json().get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class EmailTestViewTest(TestCase):
    """email_test 接口测试（仅测权限和参数校验，不实际发邮件）"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.normal = make_user('normal', [])
        self.supper_client = make_client(self.supper)
        self.normal_client = make_client(self.normal)

    def test_denied_for_non_supper(self):
        r = self.normal_client.post(
            '/setting/email_test/',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_missing_params_returns_error(self):
        r = self.supper_client.post(
            '/setting/email_test/',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    @patch('apps.setting.views.Mail')
    def test_email_test_success(self, mock_mail_cls):
        """mock Mail 类，验证成功路径不报错"""
        mock_instance = mock_mail_cls.return_value
        mock_instance.get_server.return_value.quit.return_value = None

        r = self.supper_client.post(
            '/setting/email_test/',
            data=json.dumps({
                'server': 'smtp.test.com',
                'port': 465,
                'username': 'test@test.com',
                'password': 'pwd',
            }),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MFAViewTest(TestCase):
    """MFA 视图测试（AdminView 无 PERM_MAP，超管专用）"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.normal = make_user('normal', [])
        self.supper_client = make_client(self.supper)
        self.normal_client = make_client(self.normal)

    def test_get_denied_for_non_supper(self):
        r = self.normal_client.get('/setting/mfa/')
        self.assertTrue(r.json().get('error'))

    def test_get_no_wx_token(self):
        """超管未配置 wx_token 返回提示"""
        r = self.supper_client.get('/setting/mfa/')
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('推送标识', body['error'])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AppSettingUtilTest(TestCase):
    """AppSetting 工具类测试"""

    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

    def test_get_raises_keyerror_for_unknown_key(self):
        with self.assertRaises(KeyError):
            AppSetting.get('non_existent_key')

    def test_get_default_returns_fallback(self):
        result = AppSetting.get_default('non_existent_key', 'fallback')
        self.assertEqual(result, 'fallback')

    def test_set_and_get(self):
        AppSetting.set('verify_ip', False)
        AppSetting.get.cache_clear()  # set 不清 lru_cache，手动清
        self.assertEqual(AppSetting.get('verify_ip'), False)

    def test_set_invalid_key_raises(self):
        with self.assertRaises(KeyError):
            AppSetting.set('invalid_key', 'value')

    def test_delete(self):
        AppSetting.set('verify_ip', True)
        AppSetting.delete('verify_ip')
        self.assertFalse(Setting.objects.filter(key='verify_ip').exists())

    def test_set_serializes_dict_to_json(self):
        AppSetting.set('MFA', {'enable': True})
        setting = Setting.objects.get(key='MFA')
        self.assertEqual(setting.real_val, {'enable': True})
