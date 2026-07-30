# -*- coding: utf-8 -*-
"""首页模块冒烟测试"""
import tempfile
import json
from django.test import TestCase, override_settings
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.alert.models import Alert, AlertRead


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class HomeSmokeTest(TestCase):
    URL = '/home/statistic/'
    PERMS = ['dashboard.dashboard.view']

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


class AlertApiTest(TestCase):
    URL = '/home/alert/'

    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('alert_viewer', ['system.alert.view'])
        self.other_viewer = make_user('alert_other', ['system.alert.view'])
        self.resolver = make_user(
            'alert_resolver', ['system.alert.view', 'system.alert.resolve']
        )
        self.no_perm = make_user('alert_denied', [])
        self.client_viewer = make_client(self.viewer)
        self.client_other = make_client(self.other_viewer)
        self.client_resolver = make_client(self.resolver)
        self.client_denied = make_client(self.no_perm)
        self.error_alert = Alert.objects.create(
            title='Celery task failed',
            message='task exception',
            level=Alert.LEVEL_ERROR,
            source='celery',
            alert_key='celery:test',
        )
        self.warning_alert = Alert.objects.create(
            title='Disk usage high',
            message='disk usage is 91%',
            level=Alert.LEVEL_WARNING,
            source='disk',
            alert_key='disk:documents',
        )

    def test_list_returns_items_and_unread_summary(self):
        response = self.client_viewer.get(self.URL, {'level': 'error'})
        body = response.json()

        self.assertFalse(body['error'])
        self.assertEqual(body['data']['total'], 1)
        self.assertEqual(body['data']['items'][0]['status'], 'unread')
        self.assertEqual(body['data']['summary']['unread_count'], 2)
        self.assertEqual(body['data']['summary']['error_count'], 1)
        self.assertEqual(body['data']['summary']['warning_count'], 1)

    def test_read_status_is_isolated_per_user(self):
        response = self.client_viewer.post(
            '/home/alert/mark-read/',
            data=json.dumps({'ids': [self.error_alert.id]}),
            content_type='application/json',
        )
        self.assertFalse(response.json()['error'])
        self.assertTrue(AlertRead.objects.filter(
            alert=self.error_alert, user_id=self.viewer.id
        ).exists())

        viewer_item = self.client_viewer.get(
            self.URL, {'status': 'read'}
        ).json()['data']['items'][0]
        other_item = self.client_other.get(
            self.URL, {'level': 'error'}
        ).json()['data']['items'][0]
        self.assertEqual(viewer_item['status'], 'read')
        self.assertEqual(other_item['status'], 'unread')

    def test_resolve_requires_resolve_permission_and_is_idempotent(self):
        url = f'/home/alert/{self.error_alert.id}/resolve/'
        denied = self.client_viewer.post(url)
        self.assertTrue(denied.json()['error'])
        self.error_alert.refresh_from_db()
        self.assertEqual(self.error_alert.status, Alert.STATUS_ACTIVE)

        resolved = self.client_resolver.post(url)
        self.assertFalse(resolved.json()['error'])
        self.error_alert.refresh_from_db()
        self.assertEqual(self.error_alert.status, Alert.STATUS_RESOLVED)
        self.assertEqual(self.error_alert.resolved_by_id, self.resolver.id)
        self.assertIsNotNone(self.error_alert.resolved_at)

        repeated = self.client_resolver.post(url)
        self.assertFalse(repeated.json()['error'])

    def test_list_requires_view_permission(self):
        response = self.client_denied.get(self.URL)
        self.assertTrue(response.json()['error'])
