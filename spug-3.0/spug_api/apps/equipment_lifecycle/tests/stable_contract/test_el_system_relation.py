# -*- coding: utf-8 -*-
"""设备生命周期第 2 步 stable_contract 测试：系统主数据 + 系统—设备关系。

固化以下业务不变量：
1. 权限边界：system.view/manage、relation.view/manage 四码独立，后端逐一校验。
2. 租户隔离：系统与关系的列表、详情、写操作全部租户隔离。
3. 时间约束：同一 (系统, 设备, 角色) 的关系时间段（半开区间）不可重叠，
   端点相接允许，历史时间段同样受保护。
4. 历史保留：退出关系只封存不删除；重新加入必须建立新时间段；
   已退出的关系不可编辑；关系无删除入口。
5. 并发冲突：同键关系的并发创建至多一条成功。
"""
import json
import threading

from django.db import connections
from django.test import TestCase, TransactionTestCase, Client

from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.equipment_lifecycle.models import LifecycleDevice
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.models import LifecycleSystem, SystemDeviceRelation

SYSTEM_URL = '/equipment-lifecycle/systems/'
SYSTEM_DETAIL_URL = '/equipment-lifecycle/systems/detail/'
RELATION_URL = '/equipment-lifecycle/system-relations/'
EXIT_URL = '/equipment-lifecycle/system-relations/exit/'

PERM_SYSTEM_VIEW = 'equipment_lifecycle.system.view'
PERM_SYSTEM_MANAGE = 'equipment_lifecycle.system.manage'
PERM_RELATION_VIEW = 'equipment_lifecycle.relation.view'
PERM_RELATION_MANAGE = 'equipment_lifecycle.relation.manage'


def _d(s):
    from datetime import datetime
    return datetime.strptime(s, '%Y-%m-%d').date()


def make_system_record(tenant_id, user, name, **overrides):
    data = dict(tenant_id=tenant_id, name=name, code='', description='', created_by=user)
    data.update(overrides)
    return LifecycleSystem.objects.create(**data)


def make_device_record(tenant_id, user, sn, **overrides):
    data = dict(
        tenant_id=tenant_id, device_sn=sn, device_name='设备-' + sn,
        device_model='Model-A', current_status='1', created_by=user,
    )
    data.update(overrides)
    return LifecycleDevice.objects.create(**data)


def make_relation_record(system, device, role='primary', valid_from='2026-01-01',
                         valid_to=None, status='active', **overrides):
    data = dict(
        tenant_id=system.tenant_id, system=system,
        device=device, device_sn=device.device_sn, device_name=device.device_name,
        role=role, is_primary=False, valid_from=_d(valid_from),
        valid_to=_d(valid_to) if valid_to else None, status=status,
        created_by=system.created_by,
    )
    data.update(overrides)
    return SystemDeviceRelation.objects.create(**data)


# ========================= 系统主数据 =========================

class ElSystemPermissionTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('el_sys_viewer', [PERM_SYSTEM_VIEW])
        self.manager = make_user('el_sys_mgr', [PERM_SYSTEM_VIEW, PERM_SYSTEM_MANAGE])
        self.no_perm = make_user('el_sys_noperm', [])
        self.c_viewer = make_client(self.viewer)
        self.c_mgr = make_client(self.manager)
        self.c_noperm = make_client(self.no_perm)

    def test_unauthenticated_denied(self):
        self.assertTrue(Client().get(SYSTEM_URL).json().get('error'))

    def test_view_perm_can_list_and_detail(self):
        system = make_system_record(self.viewer.tenant_id, self.viewer, '指挥信息系统')
        body = self.c_viewer.get(SYSTEM_URL).json()
        self.assertFalse(body.get('error'))
        self.assertIn('指挥信息系统', [i['name'] for i in body['data']['data']])

        body = self.c_viewer.get(SYSTEM_DETAIL_URL, {'id': system.id}).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['name'], '指挥信息系统')
        self.assertIn('active_device_count', body['data'])

    def test_relation_view_perm_can_read_system_detail(self):
        """关系维护需要读取系统详情：relation.view 也可访问详情端点"""
        system = make_system_record(self.viewer.tenant_id, self.viewer, '关系可读系统')
        body = self.c_viewer.get(SYSTEM_DETAIL_URL, {'id': system.id}).json()
        self.assertFalse(body.get('error'))

    def test_relation_view_perm_cannot_read_system_list(self):
        relation_only = make_user('el_sys_relview', [PERM_RELATION_VIEW])
        resp = make_client(relation_only).get(SYSTEM_URL)
        self.assertTrue(resp.json().get('error'))

    def test_no_perm_denied(self):
        self.assertTrue(self.c_noperm.get(SYSTEM_URL).json().get('error'))

    def test_view_only_cannot_write(self):
        payload = json.dumps({'name': '越权系统'})
        self.assertTrue(self.c_viewer.post(SYSTEM_URL, data=payload,
                                           content_type='application/json').json().get('error'))
        system = make_system_record(self.viewer.tenant_id, self.viewer, '已有系统')
        self.assertTrue(self.c_viewer.put(SYSTEM_URL, data=json.dumps(
            {'id': system.id, 'name': '改名'}), content_type='application/json').json().get('error'))
        self.assertTrue(self.c_viewer.delete(f'{SYSTEM_URL}?id={system.id}').json().get('error'))
        self.assertTrue(LifecycleSystem.objects.filter(pk=system.id).exists())

    def test_relation_perm_cannot_access_system_api(self):
        relation_only = make_user('el_sys_relonly', [PERM_RELATION_VIEW, PERM_RELATION_MANAGE])
        self.assertTrue(make_client(relation_only).get(SYSTEM_URL).json().get('error'))


class ElSystemTenantIsolationTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user_a = make_user('el_sys_ta', [PERM_SYSTEM_VIEW, PERM_SYSTEM_MANAGE])
        self.user_a.tenant_id = 'el_sys_tenant_a'
        self.user_a.save()
        self.user_b = make_user('el_sys_tb', [PERM_SYSTEM_VIEW, PERM_SYSTEM_MANAGE])
        self.user_b.tenant_id = 'el_sys_tenant_b'
        self.user_b.save()
        self.c_a = make_client(self.user_a)
        self.sys_a = make_system_record('el_sys_tenant_a', self.user_a, 'A租户系统')
        self.sys_b = make_system_record('el_sys_tenant_b', self.user_b, 'B租户系统')

    def test_list_isolated(self):
        names = [i['name'] for i in self.c_a.get(SYSTEM_URL).json()['data']['data']]
        self.assertIn('A租户系统', names)
        self.assertNotIn('B租户系统', names)

    def test_cross_tenant_detail_blocked(self):
        self.assertTrue(self.c_a.get(SYSTEM_DETAIL_URL, {'id': self.sys_b.id}).json().get('error'))

    def test_cross_tenant_update_blocked(self):
        resp = self.c_a.put(SYSTEM_URL, data=json.dumps(
            {'id': self.sys_b.id, 'name': '篡改'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.sys_b.refresh_from_db()
        self.assertEqual(self.sys_b.name, 'B租户系统')

    def test_cross_tenant_delete_blocked(self):
        self.assertTrue(self.c_a.delete(f'{SYSTEM_URL}?id={self.sys_b.id}').json().get('error'))
        self.assertTrue(LifecycleSystem.objects.filter(pk=self.sys_b.id).exists())

    def test_same_name_different_tenants_allowed(self):
        resp = self.c_a.post(SYSTEM_URL, data=json.dumps({'name': 'B租户系统'}),
                             content_type='application/json')
        self.assertFalse(resp.json().get('error'))


class ElSystemCrudTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_sys_crud', [PERM_SYSTEM_VIEW, PERM_SYSTEM_MANAGE])
        self.c = make_client(self.manager)
        self.device = make_device_record(self.manager.tenant_id, self.manager, 'EL-SYS-001')

    def test_create_returns_record_and_writes_audit(self):
        resp = self.c.post(SYSTEM_URL, data=json.dumps(
            {'name': '测控系统', 'code': 'CK-01', 'description': '描述'}),
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['name'], '测控系统')
        self.assertTrue(AuditLog.objects.filter(
            target_type='el_system', action='create', target_id=str(body['data']['id'])).exists())

    def test_duplicate_name_rejected(self):
        self.c.post(SYSTEM_URL, data=json.dumps({'name': '重名系统'}),
                    content_type='application/json')
        resp = self.c.post(SYSTEM_URL, data=json.dumps({'name': '重名系统'}),
                           content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(
            LifecycleSystem.objects.filter(tenant_id=self.manager.tenant_id, name='重名系统').count(), 1)

    def test_duplicate_code_rejected(self):
        self.c.post(SYSTEM_URL, data=json.dumps({'name': '系统一', 'code': 'C1'}),
                    content_type='application/json')
        resp = self.c.post(SYSTEM_URL, data=json.dumps({'name': '系统二', 'code': 'C1'}),
                           content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_update_success_and_rename_conflict(self):
        record = make_system_record(self.manager.tenant_id, self.manager, '旧名', code='OLD')
        other = make_system_record(self.manager.tenant_id, self.manager, '占用名')

        body = self.c.put(SYSTEM_URL, data=json.dumps(
            {'id': record.id, 'name': '新名', 'description': '新描述'}),
            content_type='application/json').json()
        self.assertFalse(body.get('error'))
        record.refresh_from_db()
        self.assertEqual(record.name, '新名')

        resp = self.c.put(SYSTEM_URL, data=json.dumps(
            {'id': record.id, 'name': other.name}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_delete_without_relations(self):
        record = make_system_record(self.manager.tenant_id, self.manager, '可删系统')
        self.assertFalse(self.c.delete(f'{SYSTEM_URL}?id={record.id}').json().get('error'))
        self.assertFalse(LifecycleSystem.objects.filter(pk=record.id).exists())

    def test_delete_blocked_when_relations_exist_including_history(self):
        record = make_system_record(self.manager.tenant_id, self.manager, '有历史系统')
        make_relation_record(record, self.device, status='ended', valid_to='2026-06-01')
        resp = self.c.delete(f'{SYSTEM_URL}?id={record.id}')
        self.assertTrue(resp.json().get('error'))
        self.assertTrue(LifecycleSystem.objects.filter(pk=record.id).exists())

    def test_list_keyword_and_active_count(self):
        system = make_system_record(self.manager.tenant_id, self.manager, '关键词系统')
        make_relation_record(system, self.device)
        body = self.c.get(SYSTEM_URL, {'keyword': '关键词'}).json()
        items = body['data']['data']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['active_device_count'], 1)


# ========================= 系统设备关系 =========================

class ElRelationPermissionTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('el_rel_viewer', [PERM_RELATION_VIEW])
        self.manager = make_user('el_rel_mgr', [PERM_RELATION_VIEW, PERM_RELATION_MANAGE])
        self.system_viewer = make_user('el_rel_sysview', [PERM_SYSTEM_VIEW])
        self.c_viewer = make_client(self.viewer)
        self.c_mgr = make_client(self.manager)
        self.system = make_system_record(self.manager.tenant_id, self.manager, '权限测试系统')
        self.device = make_device_record(self.manager.tenant_id, self.manager, 'EL-REL-001')
        self.payload = {
            'system_id': self.system.id, 'device_id': self.device.id,
            'role': 'primary', 'valid_from': '2026-01-01',
        }

    def test_unauthenticated_denied(self):
        self.assertTrue(Client().get(RELATION_URL).json().get('error'))

    def test_view_perm_can_list_and_options(self):
        make_relation_record(self.system, self.device)
        body = self.c_viewer.get(RELATION_URL, {'system_id': self.system.id}).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['total'], 1)

        body = self.c_viewer.get(RELATION_URL, {'system_options': 1}).json()
        self.assertFalse(body.get('error'))
        self.assertIn('权限测试系统', [i['name'] for i in body['data']])

        body = self.c_viewer.get(RELATION_URL, {'device_options': 1, 'keyword': 'EL-REL'}).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data'][0]['device_sn'], 'EL-REL-001')

    def test_view_only_cannot_write(self):
        resp = self.c_viewer.post(RELATION_URL, data=json.dumps(self.payload),
                                  content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(SystemDeviceRelation.objects.count(), 0)

    def test_system_view_only_cannot_access_relations(self):
        resp = make_client(self.system_viewer).get(RELATION_URL, {'system_id': self.system.id})
        self.assertTrue(resp.json().get('error'))

    def test_device_from_other_tenant_rejected(self):
        other_user = make_user('el_rel_other', [])
        other_user.tenant_id = 'el_rel_other_tenant'
        other_user.save()
        foreign_device = make_device_record('el_rel_other_tenant', other_user, 'EL-FR-001')
        payload = dict(self.payload, device_id=foreign_device.id)
        resp = self.c_mgr.post(RELATION_URL, data=json.dumps(payload),
                               content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(SystemDeviceRelation.objects.count(), 0)


class ElRelationTenantIsolationTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user_a = make_user('el_rel_ta', [PERM_RELATION_VIEW, PERM_RELATION_MANAGE])
        self.user_a.tenant_id = 'el_rel_tenant_a'
        self.user_a.save()
        self.user_b = make_user('el_rel_tb', [PERM_RELATION_VIEW, PERM_RELATION_MANAGE])
        self.user_b.tenant_id = 'el_rel_tenant_b'
        self.user_b.save()
        self.c_a = make_client(self.user_a)
        self.sys_a = make_system_record('el_rel_tenant_a', self.user_a, '关系A系统')
        self.sys_b = make_system_record('el_rel_tenant_b', self.user_b, '关系B系统')
        self.dev_a = make_device_record('el_rel_tenant_a', self.user_a, 'EL-TA-REL')
        self.dev_b = make_device_record('el_rel_tenant_b', self.user_b, 'EL-TB-REL')
        self.rel_b = make_relation_record(self.sys_b, self.dev_b)

    def test_list_isolated(self):
        body = self.c_a.get(RELATION_URL, {'system_id': self.sys_a.id}).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['total'], 0)
        body = self.c_a.get(RELATION_URL, {'system_options': 1}).json()
        self.assertEqual([i['name'] for i in body['data']], ['关系A系统'])

    def test_cross_tenant_relation_detail_blocked(self):
        self.assertTrue(self.c_a.get(RELATION_URL, {'id': self.rel_b.id}).json().get('error'))

    def test_cross_tenant_system_rejected_on_create(self):
        payload = {'system_id': self.sys_b.id, 'device_id': self.dev_a.id,
                   'role': 'primary', 'valid_from': '2026-01-01'}
        self.assertTrue(self.c_a.post(RELATION_URL, data=json.dumps(payload),
                                      content_type='application/json').json().get('error'))

    def test_cross_tenant_edit_and_exit_blocked(self):
        resp = self.c_a.put(RELATION_URL, data=json.dumps(
            {'id': self.rel_b.id, 'remark': '篡改'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        resp = self.c_a.post(EXIT_URL, data=json.dumps({'id': self.rel_b.id}),
                             content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.rel_b.refresh_from_db()
        self.assertEqual(self.rel_b.status, 'active')
        self.assertIsNone(self.rel_b.ended_at)


class ElRelationOverlapTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_overlap', [PERM_RELATION_VIEW, PERM_RELATION_MANAGE])
        self.c = make_client(self.manager)
        self.system = make_system_record(self.manager.tenant_id, self.manager, '重叠测试系统')
        self.device = make_device_record(self.manager.tenant_id, self.manager, 'EL-OV-001')

    def attempt(self, role='primary', valid_from='2026-06-01', valid_to=None,
                system=None, device=None):
        payload = {
            'system_id': (system or self.system).id,
            'device_id': (device or self.device).id,
            'role': role, 'valid_from': valid_from,
        }
        if valid_to:
            payload['valid_to'] = valid_to
        return self.c.post(RELATION_URL, data=json.dumps(payload),
                           content_type='application/json').json()

    def test_identical_period_rejected(self):
        make_relation_record(self.system, self.device, role='primary', valid_from='2026-01-01')
        body = self.attempt(valid_from='2026-01-01')
        self.assertTrue(body.get('error'))

    def test_contained_period_rejected(self):
        make_relation_record(self.system, self.device, role='primary',
                             valid_from='2026-01-01', valid_to='2026-12-31')
        self.assertTrue(self.attempt(valid_from='2026-03-01', valid_to='2026-06-01').get('error'))

    def test_partial_overlap_rejected(self):
        make_relation_record(self.system, self.device, role='primary',
                             valid_from='2026-01-01', valid_to='2026-06-01')
        self.assertTrue(self.attempt(valid_from='2026-05-01').get('error'))
        self.assertTrue(self.attempt(valid_from='2025-01-01', valid_to='2026-02-01').get('error'))

    def test_touching_endpoints_allowed(self):
        """半开区间语义：端点相接不算重叠"""
        make_relation_record(self.system, self.device, role='primary',
                             valid_from='2026-01-01', valid_to='2026-06-01')
        body = self.attempt(valid_from='2026-06-01')
        self.assertFalse(body.get('error'))
        self.assertEqual(SystemDeviceRelation.objects.count(), 2)

    def test_different_role_or_device_or_system_allowed(self):
        make_relation_record(self.system, self.device, role='primary', valid_from='2026-01-01')
        other_device = make_device_record(self.manager.tenant_id, self.manager, 'EL-OV-002')
        other_system = make_system_record(self.manager.tenant_id, self.manager, '另一系统')

        self.assertFalse(self.attempt(role='backup').get('error'))
        self.assertFalse(self.attempt(role='member', device=other_device).get('error'))
        self.assertFalse(self.attempt(role='primary', system=other_system).get('error'))
        self.assertEqual(SystemDeviceRelation.objects.count(), 4)

    def test_ended_period_still_protected(self):
        """历史时间段不能被新关系覆盖"""
        make_relation_record(self.system, self.device, role='primary',
                             valid_from='2026-01-01', valid_to='2026-06-01', status='ended')
        self.assertTrue(self.attempt(valid_from='2026-03-01', valid_to='2026-04-01').get('error'))
        self.assertEqual(SystemDeviceRelation.objects.count(), 1)

    def test_invalid_dates_rejected(self):
        self.assertTrue(self.attempt(valid_from='2026/01/01').get('error'))
        self.assertTrue(self.attempt(valid_from='2026-06-01', valid_to='2026-06-01').get('error'))
        self.assertTrue(self.attempt(valid_from='2026-12-01', valid_to='2026-06-01').get('error'))
        self.assertTrue(self.attempt(role='unknown').get('error'))
        self.assertEqual(SystemDeviceRelation.objects.count(), 0)


class ElRelationHistoryTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_history', [PERM_RELATION_VIEW, PERM_RELATION_MANAGE])
        self.c = make_client(self.manager)
        self.system = make_system_record(self.manager.tenant_id, self.manager, '历史测试系统')
        self.device = make_device_record(self.manager.tenant_id, self.manager, 'EL-HI-001')

    def _create_via_api(self, valid_from='2026-01-01', valid_to=None):
        payload = {'system_id': self.system.id, 'device_id': self.device.id,
                   'role': 'primary', 'valid_from': valid_from}
        if valid_to:
            payload['valid_to'] = valid_to
        return self.c.post(RELATION_URL, data=json.dumps(payload),
                           content_type='application/json').json()

    def test_exit_keeps_record_and_seals_period(self):
        body = self._create_via_api()
        relation_id = body['data']['id']
        before_created_at = body['data']['created_at']

        body = self.c.post(EXIT_URL, data=json.dumps({'id': relation_id}),
                           content_type='application/json').json()
        self.assertFalse(body.get('error'))
        record = SystemDeviceRelation.objects.get(pk=relation_id)
        self.assertEqual(record.status, 'ended')
        self.assertIsNotNone(record.valid_to)
        self.assertIsNotNone(record.ended_at)
        self.assertIsNotNone(record.ended_by)
        # 记录未被删除或重建（JSON 时间格式为秒级字符串）
        self.assertEqual(record.created_at.strftime('%Y-%m-%d %H:%M:%S'), before_created_at)
        self.assertTrue(AuditLog.objects.filter(
            target_type='el_relation_exit', target_id=str(relation_id)).exists())

    def test_exit_twice_rejected(self):
        record = make_relation_record(self.system, self.device)
        self.assertFalse(self.c.post(EXIT_URL, data=json.dumps({'id': record.id}),
                                     content_type='application/json').json().get('error'))
        self.assertTrue(self.c.post(EXIT_URL, data=json.dumps({'id': record.id}),
                                    content_type='application/json').json().get('error'))

    def test_exit_does_not_extend_recorded_end_date(self):
        record = make_relation_record(self.system, self.device,
                                      valid_from='2026-01-01', valid_to='2026-03-01')
        self.c.post(EXIT_URL, data=json.dumps({'id': record.id}),
                    content_type='application/json')
        record.refresh_from_db()
        self.assertEqual(str(record.valid_to), '2026-03-01')

    def test_ended_relation_not_editable(self):
        record = make_relation_record(self.system, self.device, status='ended',
                                      valid_to='2026-06-01')
        resp = self.c.put(RELATION_URL, data=json.dumps(
            {'id': record.id, 'remark': '篡改历史'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        record.refresh_from_db()
        self.assertEqual(record.remark, '')

    def test_rejoin_creates_new_period_and_keeps_history(self):
        body = self._create_via_api(valid_from='2026-01-01', valid_to='2026-06-01')
        relation_id = body['data']['id']
        self.c.post(EXIT_URL, data=json.dumps({'id': relation_id}),
                    content_type='application/json')

        body = self._create_via_api(valid_from='2030-01-01')
        self.assertFalse(body.get('error'))
        new_id = body['data']['id']
        self.assertNotEqual(new_id, relation_id)
        self.assertEqual(SystemDeviceRelation.objects.count(), 2)
        old = SystemDeviceRelation.objects.get(pk=relation_id)
        self.assertEqual(old.status, 'ended')
        self.assertEqual(SystemDeviceRelation.objects.get(pk=new_id).status, 'active')

    def test_rejoin_overlapping_ended_period_rejected(self):
        body = self._create_via_api(valid_from='2026-01-01', valid_to='2026-06-01')
        relation_id = body['data']['id']
        self.c.post(EXIT_URL, data=json.dumps({'id': relation_id}),
                    content_type='application/json')
        body = self._create_via_api(valid_from='2026-05-01', valid_to='2026-07-01')
        self.assertTrue(body.get('error'))
        self.assertEqual(SystemDeviceRelation.objects.count(), 1)

    def test_relation_delete_not_allowed(self):
        """关系历史只进不出：不提供删除能力"""
        record = make_relation_record(self.system, self.device)
        resp = self.c.delete(f'{RELATION_URL}?id={record.id}')
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(SystemDeviceRelation.objects.filter(pk=record.id).exists())

    def test_edit_active_relation_period(self):
        record = make_relation_record(self.system, self.device,
                                      valid_from='2026-01-01', valid_to='2026-06-01')
        body = self.c.put(RELATION_URL, data=json.dumps(
            {'id': record.id, 'valid_to': '2026-08-01', 'is_primary': True, 'remark': '调整'}),
            content_type='application/json').json()
        self.assertFalse(body.get('error'))
        record.refresh_from_db()
        self.assertEqual(str(record.valid_to), '2026-08-01')
        self.assertTrue(record.is_primary)
        self.assertEqual(record.remark, '调整')

    def test_edit_active_relation_keeps_valid_to_when_absent(self):
        """编辑时未提供 valid_to 不得误清空已记录的失效日期"""
        record = make_relation_record(self.system, self.device,
                                      valid_from='2026-01-01', valid_to='2026-06-01')
        self.c.put(RELATION_URL, data=json.dumps({'id': record.id, 'remark': '仅改备注'}),
                   content_type='application/json')
        record.refresh_from_db()
        self.assertEqual(str(record.valid_to), '2026-06-01')


class ElRelationConcurrencyTest(TransactionTestCase):
    """并发冲突：同一 (系统, 设备, 角色) 的重叠关系并发创建至多一条成功。

    依赖 REPEATABLE READ 下 select_for_update 的间隙锁 + 死锁回滚：
    两个事务同时锁定空键区间后并发插入必然构成死锁，InnoDB 回滚其一；
    若实际串行执行，后到者也会被重叠检查拒绝——两种时序下至多一条成功。
    """

    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_conc', [
            PERM_RELATION_VIEW, PERM_RELATION_MANAGE,
        ])
        self.system = make_system_record(self.manager.tenant_id, self.manager, '并发测试系统')
        self.device = make_device_record(self.manager.tenant_id, self.manager, 'EL-CONC-001')

    def test_concurrent_overlapping_create_only_one_wins(self):
        results = []
        barrier = threading.Barrier(2)

        def worker():
            client = Client()
            client.defaults['HTTP_X_TOKEN'] = self.manager.access_token
            client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
            payload = {
                'system_id': self.system.id,
                'device_id': self.device.id,
                'role': 'primary',
                'valid_from': '2026-06-01',
            }
            try:
                barrier.wait(timeout=15)
                resp = client.post(RELATION_URL, data=json.dumps(payload),
                                   content_type='application/json')
                try:
                    body = resp.json()
                except Exception:
                    body = {'_non_json_status': resp.status_code}
                results.append(body)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)

        self.assertEqual(len(results), 2, '两个并发请求都应返回结果')
        succeeded = [r for r in results if not r.get('error')]
        # 关键不变量：至多一条成功（绝不允许两条重叠关系同时落库）
        self.assertLessEqual(len(succeeded), 1, f'并发创建出现双成功: {results}')
        count = SystemDeviceRelation.objects.filter(
            system_id=self.system.id, device_id=self.device.id, role='primary').count()
        self.assertEqual(count, len(succeeded), f'落库数量与成功数不一致: {results}')


class RelationPrimaryUniquenessTest(TestCase):
    """主要归属唯一性：同一设备同一时间段（跨系统）最多一条主要归属关系"""

    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_primary', [PERM_RELATION_VIEW, PERM_RELATION_MANAGE])
        self.c = make_client(self.manager)
        self.system_a = make_system_record(self.manager.tenant_id, self.manager, '主归属系统A')
        self.system_b = make_system_record(self.manager.tenant_id, self.manager, '主归属系统B')
        self.device = make_device_record(self.manager.tenant_id, self.manager, 'EL-PRI-001')

    def _create(self, system, is_primary=False, valid_from='2026-01-01', valid_to=None, role='primary'):
        payload = {
            'system_id': system.id, 'device_id': self.device.id,
            'role': role, 'valid_from': valid_from, 'is_primary': is_primary,
        }
        if valid_to:
            payload['valid_to'] = valid_to
        return self.c.post(RELATION_URL, data=json.dumps(payload),
                           content_type='application/json').json()

    def test_overlapping_primary_in_other_system_rejected(self):
        self.assertFalse(self._create(self.system_a, is_primary=True).get('error'))
        body = self._create(self.system_b, is_primary=True, valid_from='2026-03-01', role='backup')
        self.assertIn('主要归属', body.get('error', ''))
        self.assertEqual(SystemDeviceRelation.objects.filter(system=self.system_b).count(), 0)

    def test_primary_after_previous_exit_allowed(self):
        self.assertFalse(self._create(self.system_a, is_primary=True,
                                      valid_from='2026-01-01', valid_to='2026-06-01').get('error'))
        rel_a = SystemDeviceRelation.objects.get(system=self.system_a)
        self.assertFalse(self.c.post(EXIT_URL, data=json.dumps({'id': rel_a.id}),
                                     content_type='application/json').json().get('error'))
        body = self._create(self.system_b, is_primary=True, valid_from='2026-06-01', role='member')
        self.assertFalse(body.get('error'))
        self.assertTrue(body['data']['is_primary'])

    def test_non_primary_unaffected(self):
        self.assertFalse(self._create(self.system_a, is_primary=True).get('error'))
        body = self._create(self.system_b, is_primary=False, valid_from='2026-03-01', role='backup')
        self.assertFalse(body.get('error'))
        self.assertFalse(body['data']['is_primary'])

    def test_edit_turn_on_primary_conflict(self):
        self.assertFalse(self._create(self.system_a, is_primary=True).get('error'))
        rel_b = make_relation_record(self.system_b, self.device, role='backup', valid_from='2026-03-01')
        resp = self.c.put(RELATION_URL, data=json.dumps(
            {'id': rel_b.id, 'is_primary': True}), content_type='application/json')
        self.assertIn('主要归属', resp.json().get('error', ''))
        rel_b.refresh_from_db()
        self.assertFalse(rel_b.is_primary)

    def test_edit_period_of_primary_conflict(self):
        self.assertFalse(self._create(self.system_a, is_primary=True,
                                      valid_from='2026-01-01', valid_to='2026-12-31').get('error'))
        rel_b = make_relation_record(self.system_b, self.device, is_primary=True,
                                     role='member', valid_from='2027-01-01', valid_to='2027-12-31')
        resp = self.c.put(RELATION_URL, data=json.dumps(
            {'id': rel_b.id, 'valid_from': '2026-06-01'}), content_type='application/json')
        self.assertIn('主要归属', resp.json().get('error', ''))
        rel_b.refresh_from_db()
        self.assertEqual(str(rel_b.valid_from), '2027-01-01')


class RelationGlobalListTest(TestCase):
    """关系全局列表（多对多两侧视图）：跨系统查看、system_name、关键字/状态/设备筛选、租户隔离"""

    def setUp(self):
        setup_test_env(self)
        self.user_a = make_user('el_gl_a', [PERM_RELATION_VIEW, PERM_RELATION_MANAGE])
        self.user_a.tenant_id = 'el_gl_tenant_a'
        self.user_a.save()
        self.c_a = make_client(self.user_a)
        self.sys_a1 = make_system_record('el_gl_tenant_a', self.user_a, '全局系统A1')
        self.sys_a2 = make_system_record('el_gl_tenant_a', self.user_a, '全局系统A2')
        self.dev_a1 = make_device_record('el_gl_tenant_a', self.user_a, 'EL-GL-D1')
        self.dev_a2 = make_device_record('el_gl_tenant_a', self.user_a, 'EL-GL-D2')
        make_relation_record(self.sys_a1, self.dev_a1, role='primary', is_primary=True)
        make_relation_record(self.sys_a2, self.dev_a1, role='backup')
        make_relation_record(self.sys_a2, self.dev_a2, role='member',
                             valid_from='2026-01-01', valid_to='2026-06-01', status='ended')

    def test_global_list_with_system_name(self):
        body = self.c_a.get(RELATION_URL).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['total'], 3)
        names = {i['system_name'] for i in body['data']['data']}
        self.assertEqual(names, {'全局系统A1', '全局系统A2'})

    def test_keyword_filter(self):
        body = self.c_a.get(RELATION_URL, {'keyword': 'EL-GL-D1'}).json()
        self.assertEqual(body['data']['total'], 2)

    def test_device_scope_returns_system_names(self):
        """设备侧视图：一台设备的全部系统关系（多对多的设备方向）"""
        body = self.c_a.get(RELATION_URL, {'device_id': self.dev_a1.id}).json()
        self.assertEqual(body['data']['total'], 2)
        names = {i['system_name'] for i in body['data']['data']}
        self.assertEqual(names, {'全局系统A1', '全局系统A2'})

    def test_status_filter(self):
        body = self.c_a.get(RELATION_URL, {'status': 'ended'}).json()
        self.assertEqual(body['data']['total'], 1)
        self.assertEqual(body['data']['data'][0]['status_text'], '已退出')

    def test_tenant_isolation(self):
        user_b = make_user('el_gl_b', [PERM_RELATION_VIEW])
        user_b.tenant_id = 'el_gl_tenant_b'
        user_b.save()
        sys_b = make_system_record('el_gl_tenant_b', user_b, '全局系统B')
        dev_b = make_device_record('el_gl_tenant_b', user_b, 'EL-GL-B1')
        make_relation_record(sys_b, dev_b)
        body = self.c_a.get(RELATION_URL).json()
        self.assertEqual(body['data']['total'], 3)
        names = {i['system_name'] for i in body['data']['data']}
        self.assertNotIn('全局系统B', names)
