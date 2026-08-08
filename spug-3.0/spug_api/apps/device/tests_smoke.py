# -*- coding: utf-8 -*-
"""设备档案模块冒烟测试"""
import tempfile
from django.test import TestCase, override_settings
from apps.utils.test_helpers import make_user, make_client, setup_test_env


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DeviceSmokeTest(TestCase):
    URL = '/device/device-resume/'
    PERMS = ['device.device_resume.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('viewer', self.PERMS)
        self.noperm = make_user('noperm', [])
        self.c_auth = make_client(self.user)
        self.c_noperm = make_client(self.noperm)

    def test_list_ok(self):
        r = self.c_auth.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json().get('error'))

    def test_list_denied(self):
        r = self.c_noperm.get(self.URL)
        self.assertTrue(r.json().get('error'))
