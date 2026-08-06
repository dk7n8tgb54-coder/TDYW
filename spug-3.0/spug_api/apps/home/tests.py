# -*- coding: utf-8 -*-
"""首页模块冒烟测试"""
import tempfile
import json
from datetime import timedelta
from django.test import TestCase, override_settings
from django.core.cache import cache
from django.utils import timezone
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.alert.models import Alert, AlertRead
from apps.fault.models import FaultRecord
from apps.upgrade.models import UpgradeRecord
from apps.upgrade.constants import UpgradeStatus


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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class StatisticFaultUpgradeTest(TestCase):
    """首页统计接口：最近故障 + 进行中升级"""
    URL = '/home/statistic/'
    PERMS = ['dashboard.dashboard.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('stat_viewer', self.PERMS)
        self.c_auth = make_client(self.user)

    def _clear_cache(self):
        """只清除 dashboard 缓存，保留权限缓存"""
        cache.delete(f'dashboard:{self.user.tenant_id}')

    def _make_fault(self, **kwargs):
        defaults = dict(
            tenant_id='admin',
            system_name='测试系统',
            device_code='DEV001',
            fault_date=timezone.now(),
            handler='张三',
            recorder='李四',
            fault_level='A',
            fault_phenomenon='测试故障现象',
            handling_process='处理过程',
            created_by=self.user,
        )
        defaults.update(kwargs)
        return FaultRecord.objects.create(**defaults)

    def _make_upgrade(self, **kwargs):
        defaults = dict(
            tenant_id='admin',
            title='测试升级',
            system='运维管理平台',
            upgrade_type='功能升级',
            upgrade_time=timezone.now(),
            status=UpgradeStatus.IN_PROGRESS,
            owner='王五',
            created_by=self.user,
        )
        defaults.update(kwargs)
        return UpgradeRecord.objects.create(**defaults)

    def _get_statistic(self):
        self._clear_cache()
        r = self.c_auth.get(self.URL)
        self.assertEqual(r.status_code, 200)
        return r.json()['data']

    # --- 最近故障 ---

    def test_fault_recent_ordered_by_fault_date_desc(self):
        """1. 最近故障按 fault_date 倒序返回"""
        now = timezone.now()
        self._make_fault(fault_date=now - timedelta(days=3), system_name='旧故障')
        self._make_fault(fault_date=now - timedelta(days=1), system_name='新故障')
        self._make_fault(fault_date=now - timedelta(days=2), system_name='中故障')
        data = self._get_statistic()
        recent = data['fault']['recent']
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[0]['system_name'], '新故障')
        self.assertEqual(recent[1]['system_name'], '中故障')
        self.assertEqual(recent[2]['system_name'], '旧故障')

    def test_fault_recent_ordered_by_id_when_same_date(self):
        """1b. fault_date 相同时按 id 倒序"""
        same_date = timezone.now()
        f1 = self._make_fault(fault_date=same_date, system_name='先创建')
        f2 = self._make_fault(fault_date=same_date, system_name='后创建')
        data = self._get_statistic()
        recent = data['fault']['recent']
        self.assertEqual(recent[0]['id'], f2.id)
        self.assertEqual(recent[1]['id'], f1.id)

    def test_fault_recent_max_5(self):
        """2. 最多返回5条故障"""
        now = timezone.now()
        for i in range(6):
            self._make_fault(fault_date=now - timedelta(days=i), system_name=f'故障{i}')
        data = self._get_statistic()
        self.assertEqual(len(data['fault']['recent']), 5)

    def test_fault_soft_deleted_excluded(self):
        """3. 软删除故障不参与总数和最近记录"""
        self._make_fault(system_name='正常故障')
        self._make_fault(system_name='已删除故障', is_deleted=True)
        data = self._get_statistic()
        self.assertEqual(data['fault']['total_all'], 1)
        self.assertEqual(len(data['fault']['recent']), 1)
        self.assertEqual(data['fault']['recent'][0]['system_name'], '正常故障')

    def test_fault_tenant_isolation(self):
        """4. 其他租户故障不可见"""
        self._make_fault(system_name='本租户故障', tenant_id='admin')
        self._make_fault(system_name='其他租户故障', tenant_id='other_tenant')
        data = self._get_statistic()
        self.assertEqual(data['fault']['total_all'], 1)
        self.assertEqual(data['fault']['recent'][0]['system_name'], '本租户故障')

    # --- 进行中升级 ---

    def test_upgrade_only_in_progress(self):
        """5+6. 进行中的升级只包含 IN_PROGRESS，已完成和已回退不返回"""
        self._make_upgrade(title='进行中', status=UpgradeStatus.IN_PROGRESS)
        self._make_upgrade(title='已完成', status=UpgradeStatus.COMPLETED)
        self._make_upgrade(title='已回退', status=UpgradeStatus.ROLLED_BACK)
        data = self._get_statistic()
        self.assertEqual(data['upgrade']['in_progress_total'], 1)
        self.assertEqual(len(data['upgrade']['in_progress']), 1)
        self.assertEqual(data['upgrade']['in_progress'][0]['title'], '进行中')

    def test_upgrade_soft_deleted_excluded(self):
        """7. 软删除升级不返回"""
        self._make_upgrade(title='正常升级')
        self._make_upgrade(title='已删除升级', is_deleted=True)
        data = self._get_statistic()
        self.assertEqual(data['upgrade']['in_progress_total'], 1)
        self.assertEqual(len(data['upgrade']['in_progress']), 1)
        self.assertEqual(data['upgrade']['in_progress'][0]['title'], '正常升级')

    def test_upgrade_tenant_isolation(self):
        """8. 其他租户升级不可见"""
        self._make_upgrade(title='本租户升级', tenant_id='admin')
        self._make_upgrade(title='其他租户升级', tenant_id='other_tenant')
        data = self._get_statistic()
        self.assertEqual(data['upgrade']['in_progress_total'], 1)
        self.assertEqual(data['upgrade']['in_progress'][0]['title'], '本租户升级')

    def test_upgrade_in_progress_max_5(self):
        """9. 进行中升级最多返回5条"""
        now = timezone.now()
        for i in range(6):
            self._make_upgrade(title=f'升级{i}', updated_at=now - timedelta(hours=i))
        data = self._get_statistic()
        self.assertEqual(len(data['upgrade']['in_progress']), 5)

    def test_upgrade_in_progress_total_not_limited(self):
        """10. in_progress_total 返回完整数量，不受5条展示限制"""
        now = timezone.now()
        for i in range(6):
            self._make_upgrade(title=f'升级{i}', updated_at=now - timedelta(hours=i))
        data = self._get_statistic()
        self.assertEqual(data['upgrade']['in_progress_total'], 6)
        self.assertEqual(len(data['upgrade']['in_progress']), 5)

    def test_empty_data_returns_empty_arrays(self):
        """11. 空数据时返回空数组和0，而不是缺失字段"""
        data = self._get_statistic()
        self.assertIn('fault', data)
        self.assertEqual(data['fault']['total_all'], 0)
        self.assertEqual(data['fault']['recent'], [])
        self.assertIn('upgrade', data)
        self.assertEqual(data['upgrade']['in_progress_total'], 0)
        self.assertEqual(data['upgrade']['in_progress'], [])

    def test_dashboard_cache_cleared_between_calls(self):
        """12. 测试中处理 dashboard 缓存，避免不同用例互相污染"""
        self._make_fault(system_name='故障A')
        data1 = self._get_statistic()
        self.assertEqual(data1['fault']['total_all'], 1)

        self._make_fault(system_name='故障B')
        data2 = self._get_statistic()
        self.assertEqual(data2['fault']['total_all'], 2)
