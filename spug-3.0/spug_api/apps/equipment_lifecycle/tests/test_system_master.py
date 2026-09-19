# -*- coding: utf-8 -*-
"""系统主数据（步骤二）稳定契约测试。

覆盖任务九要求：系统编号租户内唯一、跨租户隔离、无父子层级、
停用/启用语义、删除保护基础能力、权限独立校验、审计留痕。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemConfigChange,
    SystemConfigComponent,
    SystemConfigSnapshot,
    SystemConfigValue,
    SystemType,
)
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS, ALL_SYSTEM_PERMS, ALL_TYPE_PERMS,
    P_SYS_ADD, P_SYS_DEACT, P_SYS_DEL, P_SYS_EDIT, P_SYS_VIEW,
    make_client, make_field, make_system, make_type, make_user, system_payload,
)


class SystemMasterTest(TestCase):
    def setUp(self):
        self.admin = make_user('el_admin', ALL_SYSTEM_PERMS + ALL_TYPE_PERMS + ALL_CONFIG_PERMS,
                               tenant_id='tenant_a')
        self.other_admin = make_user('el_admin_b', ALL_SYSTEM_PERMS, tenant_id='tenant_b')
        self.noview_user = make_user('el_noview', [], tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_type = make_type(self.admin, tenant_id='tenant_a', name='通信系统')

    def test_create_system_success(self):
        payload = system_payload(system_type=self.system_type.id)
        resp = self.client.post('/equipment-lifecycle/systems/', payload,
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        data = resp.json()['data']
        self.assertEqual(data['system_code'], 'SYS-NEW-01')
        self.assertEqual(data['system_type_name'], '通信系统')
        self.assertTrue(LifecycleSystem.objects.filter(
            tenant_id='tenant_a', system_code='SYS-NEW-01').exists())
        # 创建记录配置变更历史
        system = LifecycleSystem.objects.get(system_code='SYS-NEW-01', tenant_id='tenant_a')
        self.assertTrue(SystemConfigChange.objects.filter(
            system=system, source='system', action='create').exists())
        # 审计日志
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system', action='create',
            target_id=str(system.id)).exists())

    def test_system_code_unique_within_tenant(self):
        make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a',
                    system_code='DUP-01')
        payload = system_payload(system_type=self.system_type.id, system_code='DUP-01')
        resp = self.client.post('/equipment-lifecycle/systems/', payload,
                                content_type='application/json')
        self.assertIn('已存在', resp.json()['error'])
        self.assertEqual(LifecycleSystem.objects.filter(tenant_id='tenant_a').count(), 1)

    def test_same_code_across_tenants_isolated(self):
        make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a',
                    system_code='SHARE-01')
        type_b = make_type(self.other_admin, tenant_id='tenant_b', name='通信系统B')
        make_system(self.other_admin, system_type=type_b, tenant_id='tenant_b',
                    system_code='SHARE-01')
        self.assertEqual(LifecycleSystem.objects.filter(system_code='SHARE-01').count(), 2)
        # 租户A用户只能看到本租户记录
        resp = self.client.get('/equipment-lifecycle/systems/')
        codes = [r['system_code'] for r in resp.json()['data']['data']]
        self.assertEqual(codes, ['SHARE-01'])
        # 租户A用户不能访问租户B的系统详情
        other_system = LifecycleSystem.objects.get(tenant_id='tenant_b')
        resp = self.client.get(f'/equipment-lifecycle/systems/{other_system.id}/')
        self.assertEqual(resp.json().get('error'), '系统不存在')
        # 租户A用户不能删除租户B的系统
        resp = self.client.delete(f'/equipment-lifecycle/systems/{other_system.id}/')
        self.assertEqual(resp.json().get('error'), '系统不存在')
        self.assertTrue(LifecycleSystem.objects.filter(pk=other_system.id).exists())

    def test_no_hierarchy_design(self):
        """系统平级：模型不存在父子层级字段。"""
        field_names = {f.name for f in LifecycleSystem._meta.get_fields()}
        for forbidden in ('parent', 'parent_system', 'subsystem', 'children'):
            self.assertNotIn(forbidden, field_names)
        # 组成项不是设备资产：模型不存在指向设备台账的外键
        component_fields = {f.name for f in SystemConfigComponent._meta.get_fields()}
        self.assertNotIn('device_resume', component_fields)
        self.assertNotIn('device', component_fields)

    def test_system_code_immutable_on_edit(self):
        system = make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a')
        payload = system_payload(system_type=self.system_type.id, system_code='CHANGED-01')
        resp = self.client.put(f'/equipment-lifecycle/systems/{system.id}/', payload,
                               content_type='application/json')
        self.assertIn('不可修改', resp.json()['error'])
        system.refresh_from_db()
        self.assertEqual(system.system_code, 'SYS-001')

    def test_edit_records_before_after_history(self):
        system = make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a')
        payload = system_payload(system_type=self.system_type.id, system_code=system.system_code,
                                 name='改名字的系统', install_location='新机房Z')
        resp = self.client.put(f'/equipment-lifecycle/systems/{system.id}/', payload,
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        change = SystemConfigChange.objects.filter(
            system=system, source='system', action='update').latest('id')
        changes = json.loads(change.changes)
        labels = {c['label'] for c in changes}
        self.assertIn('系统名称', labels)
        self.assertIn('安装地点', labels)
        for c in changes:
            if c['label'] == '系统名称':
                self.assertEqual(c['old'], '烟台中心站通信系统')
                self.assertEqual(c['new'], '改名字的系统')

    def test_deactivate_and_activate(self):
        system = make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a')
        resp = self.client.post(f'/equipment-lifecycle/systems/{system.id}/active/',
                                {'is_active': False}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        system.refresh_from_db()
        self.assertFalse(system.is_active)
        # 停用后仍可查询、可编辑（is_active 只控制业务候选资格）
        resp = self.client.get(f'/equipment-lifecycle/systems/{system.id}/')
        self.assertFalse(resp.json().get('error'))
        # 重复停用报错
        resp = self.client.post(f'/equipment-lifecycle/systems/{system.id}/active/',
                                {'is_active': False}, content_type='application/json')
        self.assertIn('未发生变化', resp.json()['error'])
        # 重新启用
        resp = self.client.post(f'/equipment-lifecycle/systems/{system.id}/active/',
                                {'is_active': True}, content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        change = SystemConfigChange.objects.filter(
            system=system, source='system').latest('id')
        self.assertEqual(change.action, 'activate')

    def test_delete_removes_archive_and_audits(self):
        """未被引用的系统可物理删除，配置档案随主体清理并记录审计。"""
        system = make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a')
        field = make_field(self.system_type, self.admin, tenant_id='tenant_a')
        SystemConfigValue.objects.create(
            tenant_id='tenant_a', system=system, field=field,
            value_text='438.000MHz', updated_by=self.admin)
        SystemConfigComponent.objects.create(
            tenant_id='tenant_a', system=system, name='接入交换机',
            model_version='S5735', quantity=4, created_by=self.admin)
        SystemConfigSnapshot.objects.create(
            tenant_id='tenant_a', system=system, name='初始快照',
            content='{}', created_by=self.admin)
        resp = self.client.delete(f'/equipment-lifecycle/systems/{system.id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertFalse(LifecycleSystem.objects.filter(pk=system.id).exists())
        self.assertFalse(SystemConfigValue.objects.filter(system_id=system.id).exists())
        self.assertFalse(SystemConfigComponent.objects.filter(system_id=system.id).exists())
        self.assertFalse(SystemConfigSnapshot.objects.filter(system_id=system.id).exists())
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='tenant_a', action='delete', target_type='el_system').exists())

    def test_delete_protection_helper_blocks_when_referenced(self):
        """删除保护基础能力：引用检查非空时禁止物理删除（步骤三接入真实引用）。"""
        from apps.equipment_lifecycle.views import _collect_system_references
        system = make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a')
        # 步骤二当前无外部引用，返回空列表（fail-closed 扩展点）
        self.assertEqual(_collect_system_references(system), [])
        resp = self.client.delete(f'/equipment-lifecycle/systems/{system.id}/')
        self.assertFalse(resp.json().get('error'))

    def test_permission_denied_without_perm(self):
        """权限不足时后端独立拒绝，不依赖前端按钮隐藏。"""
        client = make_client(self.noview_user)
        system = make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a')
        payload = system_payload(system_type=self.system_type.id)
        cases = [
            ('get', '/equipment-lifecycle/systems/', None),
            ('post', '/equipment-lifecycle/systems/', payload),
            ('get', f'/equipment-lifecycle/systems/{system.id}/', None),
            ('put', f'/equipment-lifecycle/systems/{system.id}/', payload),
            ('delete', f'/equipment-lifecycle/systems/{system.id}/', None),
            ('post', f'/equipment-lifecycle/systems/{system.id}/active/', {'is_active': False}),
        ]
        for method, url, body in cases:
            resp = getattr(client, method)(url, body, content_type='application/json')
            self.assertEqual(resp.json().get('error'), '权限拒绝', f'{method} {url}: {resp.content}')

    def test_health_status_not_editable_via_system_form(self):
        """步骤 3.5 收口：健康状态由故障/工单统一计算，新增/编辑系统不能设置。

        - 提交中携带的 health_status 一律被忽略（不是表单字段）；
        - 新建系统健康状态初始化为 normal（无任何有效影响时的计算结果）；
        - 编辑系统不会改变健康状态。
        """
        payload = system_payload(system_type=self.system_type.id, health_status='fault',
                                 system_code='HS-01')
        resp = self.client.post('/equipment-lifecycle/systems/', payload,
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['health_status'], 'normal')

        system_id = resp.json()['data']['id']
        edit_payload = system_payload(system_type=self.system_type.id,
                                      health_status='interrupted', system_code='HS-01')
        resp = self.client.put(f'/equipment-lifecycle/systems/{system_id}/', edit_payload,
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['health_status'], 'normal')

    def test_geo_coordinate_validation(self):
        payload = system_payload(system_type=self.system_type.id, geo_coordinate='200,37')
        resp = self.client.post('/equipment-lifecycle/systems/', payload,
                                content_type='application/json')
        self.assertIn('经纬度', resp.json()['error'])

    def test_system_types_management(self):
        resp = self.client.get('/equipment-lifecycle/system-types/')
        self.assertFalse(resp.json().get('error'))
        # 新建
        resp = self.client.post('/equipment-lifecycle/system-types/',
                                {'name': '软件系统', 'description': '应用软件'},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        type_id = resp.json()['data']['id']
        # 租户内同名被拒
        resp = self.client.post('/equipment-lifecycle/system-types/',
                                {'name': '软件系统'}, content_type='application/json')
        self.assertIn('同名', resp.json()['error'])
        # 有系统引用的类型不能删除
        make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a')
        resp = self.client.delete(f'/equipment-lifecycle/system-types/{self.system_type.id}/')
        self.assertIn('不能删除', resp.json()['error'])
        # 空类型可删除
        resp = self.client.delete(f'/equipment-lifecycle/system-types/{type_id}/')
        self.assertFalse(resp.json().get('error'))
        self.assertFalse(SystemType.objects.filter(pk=type_id).exists())

    def test_list_filters(self):
        make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a',
                    system_code='F-01', name='过滤测试甲', health_status='fault',
                    use_unit='运行九科')
        make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a',
                    system_code='F-02', name='过滤测试乙', is_active=False)
        resp = self.client.get('/equipment-lifecycle/systems/?keyword=F-01')
        self.assertEqual(resp.json()['data']['total'], 1)
        resp = self.client.get('/equipment-lifecycle/systems/',
                               {'health_status': json.dumps(['fault'])})
        self.assertEqual(resp.json()['data']['total'], 1)
        resp = self.client.get('/equipment-lifecycle/systems/?is_active=false')
        self.assertEqual(resp.json()['data']['total'], 1)
        resp = self.client.get('/equipment-lifecycle/systems/?use_unit=运行九')
        self.assertEqual(resp.json()['data']['total'], 1)

    def test_export_csv(self):
        make_system(self.admin, system_type=self.system_type, tenant_id='tenant_a')
        resp = self.client.get('/equipment-lifecycle/systems/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        self.assertIn('系统编号'.encode('utf-8'), resp.content)
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='tenant_a', action='export', target_type='el_system').exists())
