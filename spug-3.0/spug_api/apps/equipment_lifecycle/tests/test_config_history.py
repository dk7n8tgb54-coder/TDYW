# -*- coding: utf-8 -*-
"""配置组成项、变更历史与快照（步骤二）稳定契约测试。

覆盖任务九要求：组成项可按类型汇总且不依赖设备档案、
配置修改生成准确前后值历史、快照生成与差异比较、权限独立校验。
"""
import hashlib
import json

from django.test import TestCase

from apps.equipment_lifecycle.models import (
    SystemConfigChange,
    SystemConfigComponent,
    SystemConfigSnapshot,
)
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS, ALL_SYSTEM_PERMS,
    P_CFG_EDIT, P_CFG_SNAPSHOT, P_CFG_VIEW,
    make_client, make_field, make_system, make_type, make_user,
)


class ComponentTest(TestCase):
    def setUp(self):
        self.admin = make_user('cmp_admin', ALL_CONFIG_PERMS, tenant_id='t1')
        self.client = make_client(self.admin)
        self.system_type = make_type(self.admin, tenant_id='t1', name='通信系统')
        self.system = make_system(self.admin, system_type=self.system_type, tenant_id='t1')

    def _payload(self, **overrides):
        payload = {
            'name': '接入交换机',
            'category': '网络设备',
            'model_version': 'S5735-L24',
            'quantity': 4,
            'purpose': '机房内接入',
            'asset_sn': '',
            'external_ref': '',
            'remark': '',
            'display_order': 0,
        }
        payload.update(overrides)
        return payload

    def test_component_crud_and_history(self):
        resp = self.client.post(f'/equipment-lifecycle/systems/{self.system.id}/components/',
                                self._payload(), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        comp_id = resp.json()['data']['id']
        self.assertEqual(resp.json()['data']['quantity'], 4)

        resp = self.client.put(
            f'/equipment-lifecycle/systems/{self.system.id}/components/{comp_id}/',
            self._payload(quantity=6), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['quantity'], 6)

        resp = self.client.delete(
            f'/equipment-lifecycle/systems/{self.system.id}/components/{comp_id}/')
        self.assertFalse(resp.json().get('error'))
        self.assertFalse(SystemConfigComponent.objects.filter(pk=comp_id).exists())

        actions = list(SystemConfigChange.objects.filter(
            system=self.system, source='component').order_by('id')
            .values_list('action', flat=True))
        self.assertEqual(actions, ['create', 'update', 'delete'])

    def test_component_aggregate_without_device(self):
        """允许按类型汇总（4 台），不要求关联任何单台设备档案。"""
        resp = self.client.post(f'/equipment-lifecycle/systems/{self.system.id}/components/',
                                self._payload(asset_sn='SN-0001'), content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        data = resp.json()['data']
        self.assertEqual(data['quantity'], 4)
        self.assertEqual(data['asset_sn'], 'SN-0001')
        # 组成项模型与设备台账无任何外键关系
        field_names = {f.name for f in SystemConfigComponent._meta.get_fields()}
        self.assertNotIn('device_resume', field_names)
        self.assertNotIn('device', field_names)

    def test_negative_quantity_rejected(self):
        resp = self.client.post(f'/equipment-lifecycle/systems/{self.system.id}/components/',
                                self._payload(quantity=-1), content_type='application/json')
        self.assertIn('负数', resp.json()['error'])

    def test_component_permission(self):
        viewer = make_user('cmp_viewer', [P_CFG_VIEW], tenant_id='t1')
        client = make_client(viewer)
        resp = client.post(f'/equipment-lifecycle/systems/{self.system.id}/components/',
                           self._payload(), content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')


class HistoryAndSnapshotTest(TestCase):
    def setUp(self):
        self.admin = make_user('his_admin', ALL_SYSTEM_PERMS + ALL_CONFIG_PERMS, tenant_id='t1')
        self.client = make_client(self.admin)
        self.system_type = make_type(self.admin, tenant_id='t1', name='通信系统')
        self.system = make_system(self.admin, system_type=self.system_type, tenant_id='t1')
        self.field = make_field(self.system_type, self.admin, tenant_id='t1',
                                field_code='antenna_h', display_name='天线高度')

    def test_mixed_changes_traceable(self):
        """固定字段、动态字段和组成项变更均可追溯。"""
        # 固定字段
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/',
                        {'name': '改名系统', 'system_model': 'HX-100',
                         'install_location': '烟台中心站机房A', 'manufacturer': '某通信设备厂',
                         'install_unit': '安装一队', 'use_unit': '运行一科',
                         'install_time': '2026-01-01 08:00', 'enable_time': '2026-02-01 09:00',
                         'responsible_user_name': '张三', 'health_status': 'normal'},
                        content_type='application/json')
        # 动态字段
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(self.field.id): '25米'}},
                        content_type='application/json')
        # 组成项
        self.client.post(f'/equipment-lifecycle/systems/{self.system.id}/components/',
                         {'name': '主控板', 'category': '板卡'}, content_type='application/json')

        resp = self.client.get(f'/equipment-lifecycle/systems/{self.system.id}/changes/')
        data = resp.json()['data']
        self.assertFalse(resp.json().get('error'))
        sources = [row['source'] for row in data['data']]
        self.assertIn('system', sources)
        self.assertIn('config', sources)
        self.assertIn('component', sources)
        row_names = [row['changed_by_name'] for row in data['data']]
        self.assertTrue(all(name == 'his_admin' for name in row_names))

    def test_snapshot_create_and_diff_current(self):
        # 录入初始值并生成快照
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(self.field.id): '25米'}},
                        content_type='application/json')
        resp = self.client.post(f'/equipment-lifecycle/systems/{self.system.id}/snapshots/',
                                {'name': '改造前快照', 'remark': '技术改造前'},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        snapshot_id = resp.json()['data']['id']
        snapshot = SystemConfigSnapshot.objects.get(pk=snapshot_id)
        content = json.loads(snapshot.content)
        self.assertIn('fixed', content)
        self.assertIn('values', content)
        self.assertIn('components', content)
        expect_hash = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True).encode('utf-8')
        ).hexdigest()
        self.assertEqual(snapshot.content_hash, expect_hash)

        # 变更当前配置
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(self.field.id): '40米'}},
                        content_type='application/json')
        resp = self.client.get(
            f'/equipment-lifecycle/systems/{self.system.id}/snapshots/{snapshot_id}/?target=current')
        data = resp.json()['data']
        self.assertFalse(resp.json().get('error'))
        diffs = data['diffs']
        antenna = [d for d in diffs if d['label'] == '天线高度']
        self.assertEqual(len(antenna), 1)
        self.assertEqual(antenna[0]['old'], '25米')
        self.assertEqual(antenna[0]['new'], '40米')

    def test_snapshot_diff_between_snapshots(self):
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(self.field.id): '25米'}},
                        content_type='application/json')
        resp1 = self.client.post(f'/equipment-lifecycle/systems/{self.system.id}/snapshots/',
                                 {'name': '阶段一'}, content_type='application/json')
        snap1 = resp1.json()['data']['id']
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(self.field.id): '40米'}},
                        content_type='application/json')
        resp2 = self.client.post(f'/equipment-lifecycle/systems/{self.system.id}/snapshots/',
                                 {'name': '阶段二'}, content_type='application/json')
        snap2 = resp2.json()['data']['id']
        resp = self.client.get(
            f'/equipment-lifecycle/systems/{self.system.id}/snapshots/{snap1}/?target={snap2}')
        diffs = resp.json()['data']['diffs']
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]['old'], '25米')
        self.assertEqual(diffs[0]['new'], '40米')

    def test_snapshot_permission(self):
        viewer = make_user('his_viewer', [P_CFG_VIEW], tenant_id='t1')
        client = make_client(viewer)
        resp = client.post(f'/equipment-lifecycle/systems/{self.system.id}/snapshots/',
                           {'name': '无权快照'}, content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        # 有 view 无 snapshot 权限不能生成快照；有 view 可以查看
        resp = client.get(f'/equipment-lifecycle/systems/{self.system.id}/snapshots/')
        self.assertFalse(resp.json().get('error'))

    def test_audit_on_snapshot_and_edit(self):
        self.client.post(f'/equipment-lifecycle/systems/{self.system.id}/snapshots/',
                         {'name': '审计快照'}, content_type='application/json')
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='t1', action='create', target_type='el_system_config').exists())
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(self.field.id): '30米'}},
                        content_type='application/json')
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='t1', action='update', target_type='el_system_config').exists())
