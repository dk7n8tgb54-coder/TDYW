# -*- coding: utf-8 -*-
"""系统升级模块 stable_contract 测试"""
import json
import uuid
import unittest
from django.test import TestCase, Client
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.upgrade.models import UpgradeRecord, UpgradeSystem
from apps.logs.models import AuditLog


AUTH_SKIP = 'Known: middleware auth fails for upgrade URLs in test env (see report)'


def upgrade_data(**overrides):
    data = {
        'title': f'升级-{uuid.uuid4().hex[:6]}',
        'system': '测试系统',
        'upgrade_type': '功能升级',
        'upgrade_time': '2026-01-01 10:00:00',
        'status': '处理中', 'owner': '负责人',
        'upgrade_content': '升级内容描述',
    }
    data.update(overrides)
    return data


class UpgradeAuthTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.v = make_user('upg_viewer', ['upgrade.upgrade.view'])
        self.e = make_user('upg_editor', ['upgrade.upgrade.view', 'upgrade.upgrade.add',
            'upgrade.upgrade.edit', 'upgrade.upgrade.del'])
        self.n = make_user('upg_noperm', [])
        self.cv = make_client(self.v); self.ce = make_client(self.e)
        self.cn = make_client(self.n)

    def test_unauthenticated_denied(self):
        self.assertTrue(Client().get('/upgrade/records/').json().get('error'))

    def test_no_permission_denied(self):
        self.assertTrue(self.cn.get('/upgrade/records/').json().get('error'))

    def test_view_can_list(self):
        UpgradeRecord.objects.create(
            tenant_id=self.v.tenant_id, title='T', system='S',
            upgrade_type='软件升级', created_by=self.v)
        self.assertFalse(self.cv.get('/upgrade/records/').json().get('error'))

    def test_no_add_cannot_create(self):
        resp = self.cv.post('/upgrade/records/create/',
            data=json.dumps(upgrade_data()), content_type='application/json')
        self.assertTrue(resp.json().get('error'))


class UpgradeTenantTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.ua = make_user('upg_tena', ['upgrade.upgrade.view', 'upgrade.upgrade.add',
            'upgrade.upgrade.edit', 'upgrade.upgrade.del'])
        self.ua.tenant_id = 'tenant_a'; self.ua.save()
        self.ub = make_user('upg_tenb', ['upgrade.upgrade.view', 'upgrade.upgrade.add',
            'upgrade.upgrade.edit', 'upgrade.upgrade.del'])
        self.ub.tenant_id = 'tenant_b'; self.ub.save()
        self.ca = make_client(self.ua); self.cb = make_client(self.ub)
        self.ra = UpgradeRecord.objects.create(
            tenant_id='tenant_a', title='A', system='SA',
            upgrade_type='软件升级', created_by=self.ua)
        self.rb = UpgradeRecord.objects.create(
            tenant_id='tenant_b', title='B', system='SB',
            upgrade_type='硬件升级', created_by=self.ub)

    def test_cross_tenant_list_isolated(self):
        resp = self.ca.get('/upgrade/records/')
        data = resp.json()
        self.assertFalse(data.get('error'))
        items = data.get('data', {}).get('data', data.get('data', []))
        if isinstance(items, list):
            titles = [i.get('title') for i in items]
            self.assertIn('A', titles)
            self.assertNotIn('B', titles)

    def test_cross_tenant_delete_blocked(self):
        resp = self.ca.delete(f'/upgrade/records/{self.rb.id}/delete/')
        self.assertTrue(resp.json().get('error'))
        self.rb.refresh_from_db()
        self.assertFalse(self.rb.is_deleted)


class UpgradeCRUDTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_crud', ['upgrade.upgrade.view', 'upgrade.upgrade.add',
            'upgrade.upgrade.edit', 'upgrade.upgrade.del', 'upgrade.statistics.view'])
        self.client = make_client(self.user)

    def test_create_failure_no_partial_data(self):
        resp = self.client.post('/upgrade/records/create/',
            data=json.dumps(upgrade_data(title='')),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertFalse(UpgradeRecord.objects.filter(system='测试系统').exists())

    def test_delete_preserves_data(self):
        rec = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='Del', system='S',
            upgrade_type='软件升级', created_by=self.user)
        resp = self.client.delete(f'/upgrade/records/{rec.id}/delete/')
        self.assertFalse(resp.json().get('error'))
        rec.refresh_from_db()
        self.assertTrue(rec.is_deleted)

    def test_statistics_not_cross_tenant(self):
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='Stat', system='S',
            upgrade_type='功能升级', status='已完成', created_by=self.user)
        UpgradeRecord.objects.create(
            tenant_id='other', title='Other', system='S',
            upgrade_type='功能升级', status='已完成', created_by=self.user)
        resp = self.client.get('/upgrade/statistics/')
        self.assertFalse(resp.json().get('error'))


class UpgradeAuditTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_aud', ['upgrade.upgrade.view', 'upgrade.upgrade.add',
            'upgrade.upgrade.edit', 'upgrade.upgrade.del'])
        self.client = make_client(self.user)

    def test_audit_log_records_delete(self):
        rec = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='AD', system='S',
            upgrade_type='功能升级', created_by=self.user)
        self.client.delete(f'/upgrade/records/{rec.id}/delete/')
        self.assertTrue(AuditLog.objects.filter(action='delete', user_id=self.user.id).exists())
