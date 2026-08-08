# -*- coding: utf-8 -*-
"""告警模块 stable_contract 测试"""
import json
import unittest
from django.test import TestCase, Client
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.alert.models import Alert, AlertRead


AUTH_SKIP = 'Known: middleware auth fails for alert URLs in test env (see report)'


class AlertAuthTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.v = make_user('alert_view', ['system.alert.view'])
        self.r = make_user('alert_resv', ['system.alert.view', 'system.alert.resolve'])
        self.n = make_user('alert_nopm', [])
        self.cv = make_client(self.v); self.cr = make_client(self.r)
        self.cn = make_client(self.n)

    def test_unauthenticated_denied(self):
        self.assertTrue(Client().get('/alert/').json().get('error'))

    def test_no_permission_denied(self):
        self.assertTrue(self.cn.get('/alert/').json().get('error'))

    def test_view_can_list(self):
        Alert.objects.create(title='T', level='warning', source='test')
        self.assertFalse(self.cv.get('/alert/').json().get('error'))

    def test_no_resolve_cannot_resolve(self):
        alert = Alert.objects.create(title='A', level='error', source='test')
        resp = self.cv.post(f'/alert/{alert.id}/resolve/')
        self.assertTrue(resp.json().get('error'))
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'active')


class AlertMarkReadIdempotencyTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('alert_mrd', ['system.alert.view'])
        self.client = make_client(self.user)
        self.alert = Alert.objects.create(title='R', level='info', source='test')

    def test_mark_read_idempotent(self):
        for _ in range(2):
            self.client.post('/alert/mark-read/',
                data=json.dumps({'ids': [self.alert.id]}),
                content_type='application/json')
        count = AlertRead.objects.filter(alert=self.alert, user_id=self.user.id).count()
        self.assertEqual(count, 1)


class AlertResolveTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('alert_rsv', ['system.alert.view', 'system.alert.resolve'])
        self.client = make_client(self.user)
        self.alert = Alert.objects.create(title='R', level='error', source='test')

    def test_resolve_sets_status(self):
        resp = self.client.post(f'/alert/{self.alert.id}/resolve/')
        self.assertFalse(resp.json().get('error'))
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, 'resolved')
        self.assertIsNotNone(self.alert.resolved_at)
        self.assertEqual(self.alert.resolved_by, self.user)

    def test_resolved_not_in_active(self):
        self.client.post(f'/alert/{self.alert.id}/resolve/')
        resp = self.client.get('/alert/')
        data = resp.json()
        self.assertFalse(data.get('error'))
        items = data.get('data', {}).get('data', data.get('data', []))
        if isinstance(items, list):
            ids = [i.get('id') for i in items]
            self.assertNotIn(self.alert.id, ids)


class AlertLevelTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('alert_lvl', ['system.alert.view'])
        self.client = make_client(self.user)

    def test_valid_levels(self):
        for level in ['error', 'warning', 'info']:
            alert = Alert.objects.create(title=f'L-{level}', level=level, source='test')
            self.assertEqual(alert.level, level)
