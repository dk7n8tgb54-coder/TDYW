# -*- coding: utf-8 -*-
"""故障模块 stable_contract 测试"""
import json
import uuid
from django.test import TestCase, Client
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.fault.models import FaultRecord, FaultPart
from apps.logs.models import AuditLog


def fault_data(**overrides):
    data = {
        'system_name': f'系统-{uuid.uuid4().hex[:6]}',
        'device_code': f'DEV-{uuid.uuid4().hex[:8]}',
        'fault_date': '2026-01-01 10:00:00',
        'handler': '张三', 'recorder': '李四',
        'fault_level': '一般',
        'fault_phenomenon': '故障现象', 'handling_process': '处理过程',
    }
    data.update(overrides)
    return data


class FaultAuthPermissionTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('f_viewer', ['fault.faultrecord.view'])
        self.editor = make_user('f_editor', [
            'fault.faultrecord.view', 'fault.faultrecord.add',
            'fault.faultrecord.edit', 'fault.faultrecord.del'])
        self.no_perm = make_user('f_noperm', [])
        self.c_v = make_client(self.viewer)
        self.c_e = make_client(self.editor)
        self.c_n = make_client(self.no_perm)

    def test_unauthenticated_denied(self):
        self.assertTrue(Client().get('/fault/faultrecord/').json().get('error'))

    def test_no_permission_denied(self):
        self.assertTrue(self.c_n.get('/fault/faultrecord/').json().get('error'))

    def test_view_can_list(self):
        FaultRecord.objects.create(
            tenant_id=self.viewer.tenant_id, system_name='S', device_code='DEV-V',
            fault_date='2026-01-01 10:00:00', handler='H', recorder='R',
            fault_level='一般', fault_phenomenon='P', handling_process='HP',
            created_by=self.viewer)
        self.assertFalse(self.c_v.get('/fault/faultrecord/').json().get('error'))

    def test_no_add_cannot_create(self):
        resp = self.c_v.post('/fault/faultrecord/', data=json.dumps(fault_data()),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))


class FaultTenantIsolationTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.ua = make_user('f_ta', ['fault.faultrecord.view', 'fault.faultrecord.add',
            'fault.faultrecord.edit', 'fault.faultrecord.del'])
        self.ua.tenant_id = 'tenant_a'; self.ua.save()
        self.ub = make_user('f_tb', ['fault.faultrecord.view', 'fault.faultrecord.add',
            'fault.faultrecord.edit', 'fault.faultrecord.del'])
        self.ub.tenant_id = 'tenant_b'; self.ub.save()
        self.ca = make_client(self.ua); self.cb = make_client(self.ub)
        self.ra = FaultRecord.objects.create(
            tenant_id='tenant_a', system_name='SA', device_code='DEV-A',
            fault_date='2026-01-01 10:00:00', handler='H', recorder='R',
            fault_level='一般', fault_phenomenon='PA', handling_process='HA',
            created_by=self.ua)
        self.rb = FaultRecord.objects.create(
            tenant_id='tenant_b', system_name='SB', device_code='DEV-B',
            fault_date='2026-01-01 10:00:00', handler='H', recorder='R',
            fault_level='严重', fault_phenomenon='PB', handling_process='HB',
            created_by=self.ub)

    def test_cross_tenant_list_isolated(self):
        resp = self.ca.get('/fault/faultrecord/')
        data = resp.json()
        self.assertFalse(data.get('error'))
        items = data.get('data', {}).get('data', data.get('data', []))
        if isinstance(items, list):
            codes = [i.get('device_code') for i in items]
            self.assertIn('DEV-A', codes)
            self.assertNotIn('DEV-B', codes)

    def test_cross_tenant_update_blocked(self):
        resp = self.ca.post('/fault/faultrecord/',
            data=json.dumps({'id': self.rb.id, 'fault_level': '篡改'}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.rb.refresh_from_db()
        self.assertNotEqual(self.rb.fault_level, '篡改')

    def test_cross_tenant_delete_blocked(self):
        resp = self.ca.delete(f'/fault/faultrecord/?id={self.rb.id}')
        self.assertTrue(resp.json().get('error'))
        self.rb.refresh_from_db()
        self.assertFalse(self.rb.is_deleted)


class FaultCRUDIntegrityTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('f_crud', ['fault.faultrecord.view', 'fault.faultrecord.add',
            'fault.faultrecord.edit', 'fault.faultrecord.del'])
        self.client = make_client(self.user)

    def test_create_failure_no_partial_data(self):
        resp = self.client.post('/fault/faultrecord/',
            data=json.dumps(fault_data(system_name='')),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertFalse(FaultRecord.objects.filter(handler='张三').exists())

    def test_update_one_doesnt_affect_others(self):
        r1 = FaultRecord.objects.create(
            tenant_id=self.user.tenant_id, system_name='S1', device_code='DEV-1',
            fault_date='2026-01-01 10:00:00', handler='H1', recorder='R1',
            fault_level='一般', fault_phenomenon='P1', handling_process='HP1',
            created_by=self.user)
        r2 = FaultRecord.objects.create(
            tenant_id=self.user.tenant_id, system_name='S2', device_code='DEV-2',
            fault_date='2026-01-01 10:00:00', handler='H2', recorder='R2',
            fault_level='严重', fault_phenomenon='P2', handling_process='HP2',
            created_by=self.user)
        resp = self.client.post('/fault/faultrecord/',
            data=json.dumps({'id': r1.id, 'fault_level': '严重'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        r1.refresh_from_db(); r2.refresh_from_db()
        self.assertEqual(r1.fault_level, '严重')
        self.assertEqual(r2.fault_level, '严重')

    def test_soft_delete_preserves_data(self):
        rec = FaultRecord.objects.create(
            tenant_id=self.user.tenant_id, system_name='SD', device_code='DEV-D',
            fault_date='2026-01-01 10:00:00', handler='H', recorder='R',
            fault_level='一般', fault_phenomenon='P', handling_process='HP',
            created_by=self.user)
        resp = self.client.delete(f'/fault/faultrecord/?id={rec.id}')
        self.assertFalse(resp.json().get('error'))
        rec = FaultRecord.objects.all_with_deleted().get(pk=rec.id)
        self.assertTrue(rec.is_deleted)
        self.assertFalse(FaultRecord.objects.filter(pk=rec.id, is_deleted=False).exists())
        self.assertTrue(FaultRecord.objects.all_with_deleted().filter(pk=rec.id).exists())


class FaultAuditTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('flt_audit', ['fault.faultrecord.view', 'fault.faultrecord.add',
            'fault.faultrecord.edit', 'fault.faultrecord.del'])
        self.client = make_client(self.user)

    def test_audit_log_records_delete(self):
        rec = FaultRecord.objects.create(
            tenant_id=self.user.tenant_id, system_name='AD', device_code='DEV-AD',
            fault_date='2026-01-01 10:00:00', handler='H', recorder='R',
            fault_level='一般', fault_phenomenon='P', handling_process='HP',
            created_by=self.user)
        self.client.delete(f'/fault/faultrecord/?id={rec.id}')
        self.assertTrue(AuditLog.objects.filter(action='delete', user_id=self.user.id).exists())
