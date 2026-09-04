# -*- coding: utf-8 -*-
"""设备生命周期设备档案 stable_contract 测试（独立主数据 + CRUD）。

固化以下业务不变量：
1. 权限边界：equipment_lifecycle.device.view / device.manage 独立，后端逐一校验。
2. 租户隔离：设备档案的列表、详情、写操作全部租户隔离，编号租户内唯一。
3. 数据独立：设备档案读写本应用独立表，与旧 device 模块（apps.device）数据互不穿透。
4. 删除守卫：设备存在关系记录（含历史）时禁止删除；物理删除 + 审计留痕。
"""
import json

from django.test import TestCase, Client

from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.models import LifecycleDevice, LifecycleSystem, SystemDeviceRelation

DEVICE_URL = '/equipment-lifecycle/devices/'
OLD_DEVICE_URL = '/device/device-resume/'

PERM_DEVICE_VIEW = 'equipment_lifecycle.device.view'
PERM_DEVICE_MANAGE = 'equipment_lifecycle.device.manage'


def make_device_record(tenant_id, user, sn, **overrides):
    data = dict(
        tenant_id=tenant_id, device_sn=sn, device_name='设备-' + sn,
        device_model='Model-A', current_status='1', created_by=user,
    )
    data.update(overrides)
    return LifecycleDevice.objects.create(**data)


def device_payload(sn='EL-CRUD-001', **overrides):
    data = {
        'device_sn': sn,
        'device_name': '测向仪',
        'device_model': 'Model-B',
        'current_status': '1',
        'install_time': '2026-01-01',
        'enable_time': '2026-02-01',
    }
    data.update(overrides)
    return data


class DeviceArchivePermissionTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('el_dev_viewer', [PERM_DEVICE_VIEW])
        self.manager = make_user('el_dev_mgr', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.no_perm = make_user('el_dev_noperm', [])
        self.c_viewer = make_client(self.viewer)
        self.c_mgr = make_client(self.manager)
        self.device = make_device_record(self.viewer.tenant_id, self.viewer, 'EL-P-001')

    def test_unauthenticated_denied(self):
        self.assertTrue(Client().get(DEVICE_URL).json().get('error'))

    def test_no_permission_denied(self):
        self.assertTrue(make_client(self.no_perm).get(DEVICE_URL).json().get('error'))

    def test_view_perm_can_list_and_detail(self):
        body = self.c_viewer.get(DEVICE_URL).json()
        self.assertFalse(body.get('error'))
        self.assertIn('EL-P-001', [i['device_sn'] for i in body['data']['data']])

        body = self.c_viewer.get(DEVICE_URL, {'id': self.device.id}).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['device_sn'], 'EL-P-001')
        self.assertEqual(body['data']['current_status_text'], '正常')

    def test_view_only_cannot_write(self):
        payload = json.dumps(device_payload(sn='EL-DENY-001'))
        self.assertTrue(self.c_viewer.post(DEVICE_URL, data=payload,
                                           content_type='application/json').json().get('error'))
        self.assertFalse(LifecycleDevice.objects.filter(device_sn='EL-DENY-001').exists())

        resp = self.c_viewer.put(DEVICE_URL, data=json.dumps(
            {'id': self.device.id, 'device_name': '篡改'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.device.refresh_from_db()
        self.assertNotEqual(self.device.device_name, '篡改')

        resp = self.c_viewer.delete(f'{DEVICE_URL}?id={self.device.id}')
        self.assertTrue(resp.json().get('error'))
        self.assertTrue(LifecycleDevice.objects.filter(pk=self.device.id).exists())

    def test_system_relation_perm_cannot_access_device_api(self):
        relation_only = make_user('el_dev_relonly', [
            'equipment_lifecycle.relation.view', 'equipment_lifecycle.relation.manage'])
        self.assertTrue(make_client(relation_only).get(DEVICE_URL).json().get('error'))

    def test_old_device_perm_cannot_access_new_device_api(self):
        old_only = make_user('el_dev_oldonly', ['device.device_resume.view'])
        self.assertTrue(make_client(old_only).get(DEVICE_URL).json().get('error'))


class DeviceArchiveTenantIsolationTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user_a = make_user('el_dev_ta', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.user_a.tenant_id = 'el_dev_tenant_a'
        self.user_a.save()
        self.user_b = make_user('el_dev_tb', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.user_b.tenant_id = 'el_dev_tenant_b'
        self.user_b.save()
        self.c_a = make_client(self.user_a)
        self.dev_a = make_device_record('el_dev_tenant_a', self.user_a, 'EL-TA-001')
        self.dev_b = make_device_record('el_dev_tenant_b', self.user_b, 'EL-TB-001')

    def test_list_isolated(self):
        body = self.c_a.get(DEVICE_URL).json()
        sns = [i['device_sn'] for i in body['data']['data']]
        self.assertIn('EL-TA-001', sns)
        self.assertNotIn('EL-TB-001', sns)
        self.assertEqual(body['data']['total'], 1)

    def test_cross_tenant_detail_blocked(self):
        self.assertTrue(self.c_a.get(DEVICE_URL, {'id': self.dev_b.id}).json().get('error'))

    def test_cross_tenant_update_blocked(self):
        resp = self.c_a.put(DEVICE_URL, data=json.dumps(
            {'id': self.dev_b.id, 'device_name': '篡改'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.dev_b.refresh_from_db()
        self.assertNotEqual(self.dev_b.device_name, '篡改')

    def test_cross_tenant_delete_blocked(self):
        self.assertTrue(self.c_a.delete(f'{DEVICE_URL}?id={self.dev_b.id}').json().get('error'))
        self.assertTrue(LifecycleDevice.objects.filter(pk=self.dev_b.id).exists())

    def test_same_sn_different_tenants_allowed(self):
        resp = self.c_a.post(DEVICE_URL, data=json.dumps(device_payload(sn='EL-TB-001')),
                             content_type='application/json')
        self.assertFalse(resp.json().get('error'))


class DeviceArchiveCrudTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_dev_crud', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.c = make_client(self.manager)

    def test_create_returns_record_and_writes_audit(self):
        resp = self.c.post(DEVICE_URL, data=json.dumps(device_payload()),
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['device_sn'], 'EL-CRUD-001')
        self.assertEqual(body['data']['current_status_text'], '正常')
        self.assertTrue(AuditLog.objects.filter(
            target_type='el_device', action='create', target_id=str(body['data']['id'])).exists())

    def test_duplicate_sn_rejected(self):
        self.c.post(DEVICE_URL, data=json.dumps(device_payload()), content_type='application/json')
        resp = self.c.post(DEVICE_URL, data=json.dumps(device_payload()),
                           content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(
            LifecycleDevice.objects.filter(tenant_id=self.manager.tenant_id, device_sn='EL-CRUD-001').count(), 1)

    def test_invalid_input_rejected(self):
        self.assertTrue(self.c.post(DEVICE_URL, data=json.dumps(device_payload(sn='EL-BAD-1', device_sn='')),
                                    content_type='application/json').json().get('error'))
        self.assertTrue(self.c.post(DEVICE_URL, data=json.dumps(device_payload(sn='EL-BAD-2', current_status='9')),
                                    content_type='application/json').json().get('error'))
        self.assertTrue(self.c.post(DEVICE_URL, data=json.dumps(device_payload(sn='EL-BAD-3', install_time='2026/01/01')),
                                    content_type='application/json').json().get('error'))
        self.assertEqual(LifecycleDevice.objects.count(), 0)

    def test_update_success(self):
        device = make_device_record(self.manager.tenant_id, self.manager, 'EL-UPD-001')
        resp = self.c.put(DEVICE_URL, data=json.dumps(
            {'id': device.id, 'device_name': '改名设备', 'current_status': '2'}),
            content_type='application/json').json()
        self.assertFalse(resp.get('error'))
        device.refresh_from_db()
        self.assertEqual(device.device_name, '改名设备')
        self.assertEqual(device.current_status, '2')

    def test_delete_without_relations(self):
        device = make_device_record(self.manager.tenant_id, self.manager, 'EL-DEL-001')
        self.assertFalse(self.c.delete(f'{DEVICE_URL}?id={device.id}').json().get('error'))
        self.assertFalse(LifecycleDevice.objects.filter(pk=device.id).exists())
        self.assertTrue(AuditLog.objects.filter(
            target_type='el_device', action='delete', target_id=str(device.id)).exists())

    def test_delete_blocked_when_relations_exist_including_history(self):
        system = LifecycleSystem.objects.create(
            tenant_id=self.manager.tenant_id, name='守卫系统', created_by=self.manager)
        device = make_device_record(self.manager.tenant_id, self.manager, 'EL-DEL-002')
        from datetime import date
        SystemDeviceRelation.objects.create(
            tenant_id=self.manager.tenant_id, system=system, device=device,
            device_sn=device.device_sn, device_name=device.device_name,
            role='primary', valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 1),
            status='ended', created_by=self.manager)
        resp = self.c.delete(f'{DEVICE_URL}?id={device.id}')
        self.assertTrue(resp.json().get('error'))
        self.assertTrue(LifecycleDevice.objects.filter(pk=device.id).exists())

    def test_list_filters(self):
        make_device_record(self.manager.tenant_id, self.manager, 'EL-FT-001')
        make_device_record(self.manager.tenant_id, self.manager, 'EL-FT-002', current_status='2')
        body = self.c.get(DEVICE_URL, {'keyword': 'EL-FT-001'}).json()
        self.assertEqual(body['data']['total'], 1)
        body = self.c.get(DEVICE_URL, {'device_model': 'Model-A'}).json()
        self.assertEqual(body['data']['total'], 2)
        # axios 数组带空括号格式
        body = self.c.get(DEVICE_URL, {'current_status[]': ['2']}).json()
        self.assertEqual([i['device_sn'] for i in body['data']['data']], ['EL-FT-002'])
        # JSON 串格式
        body = self.c.get(DEVICE_URL, {'current_status': json.dumps(['1'])}).json()
        self.assertEqual([i['device_sn'] for i in body['data']['data']], ['EL-FT-001'])


class ModuleIndependenceTest(TestCase):
    """新旧设备数据互不穿透：设备生命周期档案独立于旧 device 模块"""

    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_indep', [
            PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE, 'device.device_resume.view'])
        self.c = make_client(self.manager)
        self.tenant_id = self.manager.tenant_id

    def test_new_archive_write_does_not_leak_into_old_module(self):
        resp = self.c.post(DEVICE_URL, data=json.dumps(device_payload(sn='EL-IND-001')),
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.assertFalse(
            LifecycleDevice.objects.exclude(device_sn='EL-IND-001').exists())
        # 旧模块 API 中不出现新档案数据（旧模块查询的是自己的表）
        old_body = self.c.get(OLD_DEVICE_URL).json()
        self.assertFalse(old_body.get('error'))
        old_sns = [i['device_sn'] for i in old_body['data']['data']]
        self.assertNotIn('EL-IND-001', old_sns)

    def test_old_module_data_does_not_leak_into_new_archive(self):
        from apps.device.models import DeviceResume
        DeviceResume.objects.create(
            tenant_id=self.tenant_id, device_sn='OLD-DEV-001', device_name='旧模块设备',
            device_model='Old-M', install_location='旧地点', manufacturer='旧厂家',
            install_unit='旧单位', use_unit='旧单位', current_status='1',
            created_by=self.manager)

        body = self.c.get(DEVICE_URL).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['total'], 0)
        self.assertNotIn('OLD-DEV-001', [i['device_sn'] for i in body['data']['data']])

    def test_old_module_still_works_for_old_perm_user(self):
        old_user = make_user('el_indep_old', ['device.device_resume.view'])
        from apps.device.models import DeviceResume
        DeviceResume.objects.create(
            tenant_id=old_user.tenant_id, device_sn='OLD-DEV-002', device_name='旧设备',
            device_model='Old-M', install_location='旧地点', manufacturer='旧厂家',
            install_unit='旧单位', use_unit='旧单位', current_status='1',
            created_by=old_user)
        resp = make_client(old_user).get(OLD_DEVICE_URL)
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertIn('OLD-DEV-002', [i['device_sn'] for i in body['data']['data']])
