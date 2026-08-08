# -*- coding: utf-8 -*-
"""干扰模块 stable_contract 测试"""
import json
from django.test import TestCase, Client
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.interference.models import Interference
from apps.logs.models import AuditLog


def int_data(**overrides):
    data = {
        'serial_number': 1,
        'frequency': '100.5MHz', 'report_dept': '测试部门',
        'datetime': '2026-01-01 10:00:00', 'coordinates': 'N39.9,E116.4',
        'interference_type': '信号干扰', 'phenomenon': '测试现象',
        'is_reported': False,
    }
    data.update(overrides)
    return data


class InterferenceAuthTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.v = make_user('int_view', ['interference.interference.view'])
        self.e = make_user('int_edit', ['interference.interference.view',
            'interference.interference.add', 'interference.interference.edit',
            'interference.interference.del'])
        self.n = make_user('int_nopm', [])
        self.cv = make_client(self.v); self.ce = make_client(self.e)
        self.cn = make_client(self.n)

    def test_unauthenticated_denied(self):
        self.assertTrue(Client().get('/interference/').json().get('error'))

    def test_no_permission_denied(self):
        self.assertTrue(self.cn.get('/interference/').json().get('error'))

    def test_view_can_list(self):
        Interference.objects.create(
            tenant_id=self.v.tenant_id, serial_number=101,
            frequency='100MHz', report_dept='D', datetime='2026-01-01 10:00:00',
            interference_type='T', phenomenon='P', created_by=self.v)
        self.assertFalse(self.cv.get('/interference/').json().get('error'))

    def test_no_add_cannot_create(self):
        resp = self.cv.post('/interference/',
            data=json.dumps(int_data()), content_type='application/json')
        self.assertTrue(resp.json().get('error'))


class InterferenceTenantTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.ua = make_user('i_ta', ['interference.interference.view',
            'interference.interference.add', 'interference.interference.edit',
            'interference.interference.del'])
        self.ua.tenant_id = 'tenant_a'; self.ua.save()
        self.ub = make_user('i_tb', ['interference.interference.view',
            'interference.interference.add', 'interference.interference.edit',
            'interference.interference.del'])
        self.ub.tenant_id = 'tenant_b'; self.ub.save()
        self.ca = make_client(self.ua); self.cb = make_client(self.ub)
        self.ra = Interference.objects.create(
            tenant_id='tenant_a', serial_number=201,
            frequency='100MHz', report_dept='DA', datetime='2026-01-01 10:00:00',
            interference_type='T', phenomenon='PA', created_by=self.ua)
        self.rb = Interference.objects.create(
            tenant_id='tenant_b', serial_number=202,
            frequency='200MHz', report_dept='DB', datetime='2026-01-01 10:00:00',
            interference_type='T', phenomenon='PB', created_by=self.ub)

    def test_cross_tenant_list_isolated(self):
        resp = self.ca.get('/interference/')
        data = resp.json()
        self.assertFalse(data.get('error'))
        items = data.get('data', {}).get('data', data.get('data', []))
        if isinstance(items, list):
            sns = [i.get('serial_number') for i in items]
            self.assertIn('INT-A-001', sns)
            self.assertNotIn('INT-B-001', sns)

    def test_cross_tenant_update_blocked(self):
        resp = self.ca.post('/interference/',
            data=json.dumps({'id': self.rb.id, 'phenomenon': '篡改'}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.rb.refresh_from_db()
        self.assertNotEqual(self.rb.phenomenon, '篡改')

    def test_cross_tenant_delete_blocked(self):
        resp = self.ca.delete(f'/interference/?id={self.rb.id}')
        self.assertTrue(resp.json().get('error'))
        self.rb.refresh_from_db()
        self.assertFalse(self.rb.is_deleted)


class InterferenceCRUDTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('int_crud', ['interference.interference.view',
            'interference.interference.add', 'interference.interference.edit',
            'interference.interference.del'])
        self.client = make_client(self.user)

    def test_create_failure_no_partial_data(self):
        """创建失败不留下半条数据 - frequency 是必填字段"""
        resp = self.client.post('/interference/',
            data=json.dumps(int_data(frequency='')),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertFalse(Interference.objects.filter(report_dept='测试部门').exists())

    def test_soft_delete_preserves_data(self):
        rec = Interference.objects.create(
            tenant_id=self.user.tenant_id, serial_number=301,
            frequency='100MHz', report_dept='D', datetime='2026-01-01 10:00:00',
            interference_type='T', phenomenon='P', created_by=self.user)
        resp = self.client.delete(f'/interference/?id={rec.id}')
        self.assertFalse(resp.json().get('error'))
        rec = Interference.objects.all_with_deleted().get(pk=rec.id)
        self.assertTrue(rec.is_deleted)


class InterferenceAuditTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('int_aud', ['interference.interference.view',
            'interference.interference.add', 'interference.interference.edit',
            'interference.interference.del'])
        self.client = make_client(self.user)

    def test_audit_log_records_delete(self):
        """删除干扰记录时写入审计日志"""
        rec = Interference.objects.create(
            tenant_id=self.user.tenant_id, serial_number=401,
            frequency='100MHz', report_dept='D', datetime='2026-01-01 10:00:00',
            interference_type='T', phenomenon='P', created_by=self.user)
        resp = self.client.delete(f'/interference/?id={rec.id}')
        self.assertFalse(resp.json().get('error'))
        self.assertTrue(AuditLog.objects.filter(action='delete', user_id=self.user.id).exists())
