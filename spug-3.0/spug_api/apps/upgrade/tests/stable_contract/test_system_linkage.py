# -*- coding: utf-8 -*-
"""升级管理挂接系统档案（upgrade 0022）stable_contract 测试

覆盖：系统外键 + 快照写入、可用性校验、迁移数据回填、系统履历事件、
候选系统/筛选选项、按系统查询端点、系统删除保护、升级方案挂接。
"""
import json
import uuid

from django.test import TestCase
from django.apps import apps as current_apps

from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.upgrade.models import UpgradeRecord
from apps.upgrade.models_template import UpgradeTemplate
from apps.equipment_lifecycle.models import LifecycleSystem, SystemEvent
from apps.equipment_lifecycle.tests.base import make_system

UPGRADE_PERMS = ['upgrade.upgrade.view', 'upgrade.upgrade.add',
                 'upgrade.upgrade.edit', 'upgrade.upgrade.del']


def make_linked_system(user, **kwargs):
    if 'system_code' not in kwargs:
        kwargs['system_code'] = f'SYS-{uuid.uuid4().hex[:8]}'
    return make_system(user, tenant_id=user.tenant_id, **kwargs)


def _backfill_func():
    """按路径加载 0022 迁移模块中的回填函数（迁移文件名为数字开头，须用 importlib）。"""
    import importlib
    mod = importlib.import_module(
        'apps.upgrade.migrations.0022_upgrade_record_template_link_lifecycle_system')
    return mod.backfill_system_link


class RecordSystemLinkageTest(TestCase):
    """创建/编辑升级记录时的系统校验与快照"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_link', UPGRADE_PERMS)
        self.client = make_client(self.user)
        self.system = make_linked_system(self.user, name='短波通信系统')

    def _create_payload(self, **overrides):
        payload = {
            'title': f'升级-{uuid.uuid4().hex[:6]}',
            'system': self.system.id,
            'upgrade_type': '功能升级',
            'upgrade_time': '2026-01-01 10:00:00',
            'owner': '负责人',
            'upgrade_content': '升级内容',
        }
        payload.update(overrides)
        return payload

    def test_create_writes_fk_and_snapshots(self):
        resp = self.client.post('/upgrade/records/create/',
            data=json.dumps(self._create_payload()), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        record = UpgradeRecord.objects.get(system_id=self.system.id)
        self.assertEqual(record.system_code, self.system.system_code)
        self.assertEqual(record.system_name, self.system.name)
        self.assertEqual(record.system_location, self.system.install_location)

    def test_create_writes_system_event(self):
        resp = self.client.post('/upgrade/records/create/',
            data=json.dumps(self._create_payload()), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        record = UpgradeRecord.objects.get(system_id=self.system.id)
        event = SystemEvent.objects.filter(
            event_type='upgrade', source_type='upgrade',
            source_id=str(record.id)).first()
        self.assertIsNotNone(event, '创建升级记录应写系统履历事件')
        self.assertEqual(event.action, 'create')
        self.assertEqual(event.system_id, self.system.id)

    def test_create_rejects_inactive_system(self):
        self.system.is_active = False
        self.system.save()
        resp = self.client.post('/upgrade/records/create/',
            data=json.dumps(self._create_payload()), content_type='application/json')
        self.assertIn('停用', resp.json().get('error', ''))
        self.assertFalse(UpgradeRecord.objects.filter(system_id=self.system.id).exists())

    def test_create_rejects_unknown_system(self):
        resp = self.client.post('/upgrade/records/create/',
            data=json.dumps(self._create_payload(system=999999)),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_create_rejects_missing_system(self):
        payload = self._create_payload()
        del payload['system']
        resp = self.client.post('/upgrade/records/create/',
            data=json.dumps(payload), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_update_rebind_rewrites_snapshots(self):
        record = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='换绑',
            system=self.system, system_name=self.system.name,
            upgrade_type='功能升级', created_by=self.user)
        other = make_linked_system(self.user, name='卫星通信系统')
        resp = self.client.put(f'/upgrade/records/{record.id}/update/',
            data=json.dumps({'system': other.id}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        record.refresh_from_db()
        self.assertEqual(record.system_id, other.id)
        self.assertEqual(record.system_code, other.system_code)
        self.assertEqual(record.system_name, other.name)
        self.assertEqual(record.system_location, other.install_location)

    def test_update_rebind_rejects_inactive_system(self):
        record = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='换绑停用',
            system=self.system, system_name=self.system.name,
            upgrade_type='功能升级', created_by=self.user)
        other = make_linked_system(self.user, name='停用系统', is_active=False)
        resp = self.client.put(f'/upgrade/records/{record.id}/update/',
            data=json.dumps({'system': other.id}), content_type='application/json')
        self.assertIn('停用', resp.json().get('error', ''))
        record.refresh_from_db()
        self.assertEqual(record.system_id, self.system.id)

    def test_update_unchanged_keeps_inactive_system(self):
        """编辑未变更系统关联时，允许保留已停用系统（历史单据继续可查）"""
        record = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='停用保留',
            system=self.system, system_name=self.system.name,
            upgrade_type='功能升级', created_by=self.user)
        self.system.is_active = False
        self.system.save()
        resp = self.client.put(f'/upgrade/records/{record.id}/update/',
            data=json.dumps({'title': '停用保留-改'}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        record.refresh_from_db()
        self.assertEqual(record.system_id, self.system.id)

    def test_update_unlinked_legacy_record_adopts_system(self):
        """历史未匹配记录（system 为空）可通过编辑补挂系统档案"""
        record = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='历史遗留',
            system_name='无法匹配的旧名', upgrade_type='功能升级',
            created_by=self.user)
        resp = self.client.put(f'/upgrade/records/{record.id}/update/',
            data=json.dumps({'system': self.system.id}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        record.refresh_from_db()
        self.assertEqual(record.system_id, self.system.id)
        self.assertEqual(record.system_name, self.system.name)


class SystemEventOnStatusFlowTest(TestCase):
    """升级完成/回退写系统履历事件"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_flow', UPGRADE_PERMS)
        self.client = make_client(self.user)
        self.system = make_linked_system(self.user, name='状态流系统')
        self.record = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='状态流验证单',
            system=self.system, system_name=self.system.name,
            upgrade_type='功能升级', status='处理中', created_by=self.user)

    def _events(self, action):
        return SystemEvent.objects.filter(
            event_type='upgrade', source_type='upgrade',
            source_id=str(self.record.id), action=action)

    def test_complete_writes_event(self):
        resp = self.client.post(f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'complete', 'remark': '完成'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(self._events('complete').count(), 1)

    def test_rollback_writes_event(self):
        resp = self.client.post(f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'rollback', 'remark': '回退',
                             'target_action': '开始'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(self._events('rollback').count(), 1)

    def test_unlinked_record_writes_no_event(self):
        self.record.system = None
        self.record.save()
        resp = self.client.post(f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'complete', 'remark': '完成'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(
            SystemEvent.objects.filter(source_id=str(self.record.id)).count(), 0)


class MigrationBackfillTest(TestCase):
    """0022 数据回填：按租户内名称匹配系统档案"""

    def test_backfill_matches_by_name_and_writes_snapshots(self):
        system = make_linked_system(make_user('bf_sys', []), name='回填匹配系统')
        tenant = system.tenant_id
        matched = UpgradeRecord.objects.create(
            tenant_id=tenant, title='可匹配', system_name='回填匹配系统',
            upgrade_type='功能升级', created_by=system.created_by)
        unmatched = UpgradeRecord.objects.create(
            tenant_id=tenant, title='不可匹配', system_name='字典里的旧名字',
            upgrade_type='功能升级', created_by=system.created_by)
        template = UpgradeTemplate.objects.create(
            tenant_id=tenant, name='回填方案', system_name='回填匹配系统',
            created_by=system.created_by)

        _backfill_func()(current_apps, None)

        matched.refresh_from_db()
        self.assertEqual(matched.system_id, system.id)
        self.assertEqual(matched.system_code, system.system_code)
        self.assertEqual(matched.system_location, system.install_location)
        unmatched.refresh_from_db()
        self.assertIsNone(unmatched.system_id)
        self.assertEqual(unmatched.system_name, '字典里的旧名字')
        template.refresh_from_db()
        self.assertEqual(template.system_id, system.id)


class CandidateSystemsAndFilterOptionsTest(TestCase):
    """候选系统与筛选选项来自系统档案"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_cand', UPGRADE_PERMS)
        self.client = make_client(self.user)
        self.system = make_linked_system(self.user, name='候选系统A')

    def test_candidate_systems_returns_active_only(self):
        inactive = make_linked_system(self.user, name='候选系统B', is_active=False)
        resp = self.client.get('/upgrade/candidate-systems/')
        payload = resp.json()['data']
        ids = [s['id'] for s in payload['data']]
        self.assertIn(self.system.id, ids)
        self.assertNotIn(inactive.id, ids)
        item = next(s for s in payload['data'] if s['id'] == self.system.id)
        for key in ('system_code', 'name', 'install_location'):
            self.assertIn(key, item)

    def test_filter_options_systems_from_lifecycle(self):
        resp = self.client.get('/upgrade/filter-options/')
        data = resp.json()
        self.assertFalse(data.get('error'))
        systems = data['data']['systems']
        self.assertTrue(any(s['id'] == self.system.id for s in systems))
        # 输出为对象列表（含编号/名称），不再是历史文本列表
        self.assertIn('system_code', systems[0])

    def test_record_list_filter_by_system_id(self):
        other = make_linked_system(self.user, name='候选系统C')
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='命中',
            system=self.system, system_name=self.system.name,
            upgrade_type='功能升级', created_by=self.user)
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='不命中',
            system=other, system_name=other.name,
            upgrade_type='功能升级', created_by=self.user)
        resp = self.client.get(f'/upgrade/records/?system={self.system.id}')
        items = resp.json()['data']['records']
        titles = [i.get('title') for i in items]
        self.assertIn('命中', titles)
        self.assertNotIn('不命中', titles)


class SystemUpgradeRecordsEndpointTest(TestCase):
    """按系统查询升级记录（系统详情页签）"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_sysq', UPGRADE_PERMS)
        self.client = make_client(self.user)
        self.system = make_linked_system(self.user, name='按系统查询')
        self.record = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='本系统记录',
            system=self.system, system_name=self.system.name,
            upgrade_type='功能升级', created_by=self.user)

    def test_returns_only_this_system_records(self):
        other = make_linked_system(self.user, name='别的系统')
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='别的记录',
            system=other, system_name=other.name,
            upgrade_type='功能升级', created_by=self.user)
        resp = self.client.get(
            f'/equipment-lifecycle/systems/{self.system.id}/upgrade-records/')
        payload = resp.json()['data']
        titles = [r['title'] for r in payload['data']]
        self.assertIn('本系统记录', titles)
        self.assertNotIn('别的记录', titles)
        self.assertEqual(payload['total'], 1)

    def test_excludes_soft_deleted(self):
        self.record.is_deleted = True
        self.record.save()
        resp = self.client.get(
            f'/equipment-lifecycle/systems/{self.system.id}/upgrade-records/')
        self.assertEqual(resp.json()['data']['total'], 0)

    def test_cross_tenant_system_denied(self):
        outsider = make_user('upg_sysq_out', UPGRADE_PERMS)
        outsider.tenant_id = 'other_tenant'; outsider.save()
        client = make_client(outsider)
        resp = client.get(
            f'/equipment-lifecycle/systems/{self.system.id}/upgrade-records/')
        self.assertTrue(resp.json().get('error'))

    def test_no_permission_denied(self):
        nobody = make_user('upg_sysq_np', [])
        client = make_client(nobody)
        resp = client.get(
            f'/equipment-lifecycle/systems/{self.system.id}/upgrade-records/')
        self.assertTrue(resp.json().get('error'))


class SystemDeleteProtectionTest(TestCase):
    """系统删除保护：存在升级记录时禁止删除"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_delprot', UPGRADE_PERMS + [
            'equipment_lifecycle.system.view', 'equipment_lifecycle.system.del'])
        self.client = make_client(self.user)
        self.system = make_linked_system(self.user, name='删除保护系统')

    def test_delete_blocked_with_upgrade_records(self):
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='引用记录',
            system=self.system, system_name=self.system.name,
            upgrade_type='功能升级', created_by=self.user)
        resp = self.client.delete(f'/equipment-lifecycle/systems/{self.system.id}/')
        self.assertIn('升级记录', resp.json().get('error', ''))

    def test_delete_allowed_without_upgrade_records(self):
        resp = self.client.delete(f'/equipment-lifecycle/systems/{self.system.id}/')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertFalse(
            LifecycleSystem.objects.filter(pk=self.system.id).exists())


class PlanSystemLinkageTest(TestCase):
    """升级方案挂接系统档案"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_plan', UPGRADE_PERMS)
        self.client = make_client(self.user)
        self.system = make_linked_system(self.user, name='方案挂接系统')

    def test_create_plan_with_system(self):
        resp = self.client.post('/upgrade/plans/create/',
            data=json.dumps({'name': f'方案-{uuid.uuid4().hex[:6]}',
                             'system': self.system.id,
                             'steps': [{'title': '备份', 'sequence': 1}]}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        plan = UpgradeTemplate.objects.get(system_id=self.system.id)
        self.assertEqual(plan.system_name, self.system.name)

    def test_create_plan_rejects_unknown_system(self):
        resp = self.client.post('/upgrade/plans/create/',
            data=json.dumps({'name': f'方案-{uuid.uuid4().hex[:6]}',
                             'system': 999999, 'steps': []}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_plan_detail_returns_system_fields(self):
        plan = UpgradeTemplate.objects.create(
            tenant_id=self.user.tenant_id, name='详情方案',
            system=self.system, system_name=self.system.name,
            created_by=self.user)
        resp = self.client.get(f'/upgrade/plans/{plan.id}/')
        data = resp.json().get('data', {})
        self.assertEqual(data.get('system_id'), self.system.id)
        self.assertEqual(data.get('system_name'), self.system.name)
