# -*- coding: utf-8 -*-
"""系统新增/编辑聚合提交稳定契约测试。

覆盖：一次提交（系统固定字段 + 内联自定义字段定义与值 +
配置组成项）、任一步失败整体回滚、字段编码由后端生成且 client_key 不落库、
必填/候选项校验、字段管理权限独立校验、编辑聚合与组成项全量同步、
详情基本信息合并展示动态字段、表单字段加载接口。

聚合创建载荷只含 system / custom_fields / components；
原模板字段相关用例已按等价语义改造为内联自定义字段用例。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.models import (
    ConfigFieldDefinition,
    LifecycleSystem,
    SystemConfigChange,
    SystemConfigComponent,
    SystemConfigValue,
)
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS, ALL_SYSTEM_PERMS,
    P_SYS_ADD, P_SYS_EDIT, P_SYS_VIEW,
    make_client, make_field, make_system, make_user,
)

URL = '/equipment-lifecycle/systems'


def aggregate_payload(**overrides):
    payload = {
        'system': {
            'name': '聚合提交系统',
            'system_model': 'MODEL-A',
            'install_location': '机房C',
            'geo_coordinate': '',
            'system_purpose': '',
            'manufacturer': '某厂',
            'install_unit': '安装单位A',
            'use_unit': '使用单位B',
            'install_time': '2026-03-01 08:00',
            'enable_time': '2026-03-10 09:30',
            'responsible_user_name': '王五',
            'health_status': 'normal',
            'remark': '',
        },
        'custom_fields': [],
        'components': [],
    }
    payload.update(overrides)
    return payload


class AggregateCreateTest(TestCase):
    def setUp(self):
        self.admin = make_user('agg_admin', ALL_SYSTEM_PERMS + ALL_CONFIG_PERMS,
                               tenant_id='t9')
        self.client = make_client(self.admin)

    def test_one_shot_submission(self):
        """系统+内联自定义字段定义与值+组成项一次提交全部落库。"""
        payload = aggregate_payload(custom_fields=[
            {'client_key': 'temp_field_1', 'name': '天线高度', 'field_type': 'number',
             'required': False, 'value': '12.5'},
        ], components=[
            {'name': '接入交换机', 'model_version': 'S5735', 'quantity': 4},
        ])
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 编号由后端自动生成，按返回值定位系统
        system = LifecycleSystem.objects.get(
            tenant_id='t9', system_code=resp.json()['data']['system_code'])
        # 自定义字段定义已创建，编码由后端生成，client_key 不落库
        custom = ConfigFieldDefinition.objects.get(
            tenant_id='t9', scope_type='custom', scope_owner_id=str(system.id))
        self.assertEqual(custom.display_name, '天线高度')
        self.assertEqual(custom.field_type, 'number')
        self.assertRegex(custom.field_code, r'^[a-z][a-z0-9_]{0,49}$')
        self.assertNotEqual(custom.field_code, 'temp_field_1')
        # 自定义字段值已保存
        self.assertTrue(SystemConfigValue.objects.filter(
            system=system, field=custom, value_number=12.5).exists())
        # 组成项已保存
        self.assertTrue(SystemConfigComponent.objects.filter(
            system=system, name='接入交换机', model_version='S5735', quantity=4).exists())
        # 变更历史：系统创建 + 字段定义 + 配置值 + 组成项
        self.assertTrue(SystemConfigChange.objects.filter(
            system=system, source='system', action='create').exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=system, source='field_definition', action='create').exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=system, source='config', action='create').exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=system, source='component', action='create').exists())
        # 审计日志
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='t9', action='create', target_type='el_system',
            target_id=str(system.id)).exists())

    def test_field_code_slug_for_ascii_name(self):
        """ASCII 名称生成可读稳定编码。"""
        payload = aggregate_payload(custom_fields=[
            {'client_key': 't1', 'name': 'antenna height', 'field_type': 'number', 'value': '3'},
        ])
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        custom = ConfigFieldDefinition.objects.get(
            scope_type='custom', display_name='antenna height')
        self.assertEqual(custom.field_code, 'antenna_height')

    def test_rollback_on_invalid_custom_field_value(self):
        """内联自定义字段值非法时整体回滚：无系统、无字段定义、无值、无组成项。"""
        payload = aggregate_payload(custom_fields=[
            {'client_key': 't1', 'name': '频段', 'field_type': 'choice',
             'choices': ['UHF', 'VHF'], 'value': 'SHF'},
        ], components=[{'name': '组成项甲'}])
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertIn('候选项', resp.json()['error'])
        self.assertEqual(
            LifecycleSystem.objects.filter(tenant_id='t9').count(), 0)
        self.assertEqual(
            ConfigFieldDefinition.objects.filter(tenant_id='t9', scope_type='custom').count(), 0)
        self.assertEqual(SystemConfigValue.objects.count(), 0)
        self.assertEqual(SystemConfigComponent.objects.count(), 0)

    def test_rollback_on_required_custom_field_without_value(self):
        payload = aggregate_payload(custom_fields=[
            {'client_key': 't1', 'name': '天线高度', 'field_type': 'number',
             'required': True, 'value': ''},
        ])
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertIn('必填', resp.json()['error'])
        self.assertFalse(
            LifecycleSystem.objects.filter(tenant_id='t9').exists())

    def test_rollback_on_duplicate_custom_field_name(self):
        payload = aggregate_payload(custom_fields=[
            {'client_key': 't1', 'name': '工作频率', 'field_type': 'text', 'value': 'x'},
            {'client_key': 't2', 'name': '工作频率', 'field_type': 'text', 'value': 'y'},
        ])
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertIn('重复', resp.json()['error'])
        self.assertFalse(
            LifecycleSystem.objects.filter(tenant_id='t9').exists())

    def test_rollback_on_duplicate_client_key(self):
        payload = aggregate_payload(custom_fields=[
            {'client_key': 't1', 'name': '字段甲', 'field_type': 'text', 'value': 'x'},
            {'client_key': 't1', 'name': '字段乙', 'field_type': 'text', 'value': 'y'},
        ])
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertIn('client_key', resp.json()['error'])
        self.assertFalse(
            LifecycleSystem.objects.filter(tenant_id='t9').exists())

    def test_rollback_on_secret_keyword_custom_field(self):
        payload = aggregate_payload(custom_fields=[
            {'client_key': 't1', 'name': '数据库密码', 'field_type': 'text', 'value': 'x'},
        ])
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertIn('关键词', resp.json()['error'])
        self.assertFalse(
            LifecycleSystem.objects.filter(tenant_id='t9').exists())

    def test_custom_field_requires_field_permission(self):
        """无字段管理权限的用户提交内联字段定义被整体拒绝。"""
        nofield = make_user('agg_nofield', [P_SYS_VIEW, P_SYS_ADD], tenant_id='t9')
        client = make_client(nofield)
        payload = aggregate_payload(custom_fields=[
            {'client_key': 't1', 'name': '天线高度', 'field_type': 'number', 'value': '1'},
        ])
        resp = client.post(URL + '/', payload, content_type='application/json')
        self.assertIn('权限', resp.json()['error'])
        self.assertFalse(
            LifecycleSystem.objects.filter(tenant_id='t9').exists())


class AggregateUpdateTest(TestCase):
    def setUp(self):
        self.admin = make_user('agu_admin', ALL_SYSTEM_PERMS + ALL_CONFIG_PERMS,
                               tenant_id='t8')
        self.client = make_client(self.admin)
        self.system = make_system(self.admin, tenant_id='t8', system_code='ED-001')
        self.template_field = make_field(self.system, self.admin, tenant_id='t8',
                                         field_code='frequency', display_name='工作频率')
        self.number_field = make_field(self.system, self.admin, tenant_id='t8',
                                       field_code='antenna_h', display_name='天线高度',
                                       field_type='number')
        SystemConfigValue.objects.create(tenant_id='t8', system=self.system,
                                         field=self.template_field, value_text='旧值',
                                         updated_by=self.admin)

    def _payload(self, **overrides):
        payload = {
            'system': {
                'name': '编辑后的系统',
                'system_model': 'HX-100',
                'install_location': '机房D',
                'geo_coordinate': '',
                'system_purpose': '',
                'manufacturer': '某通信设备厂',
                'install_unit': '安装一队',
                'use_unit': '运行一科',
                'install_time': '2026-01-01 08:00',
                'enable_time': '2026-02-01 09:00',
                'responsible_user_name': '张三',
                'health_status': 'normal',
                'remark': '',
            },
            'config_values': {},
            'custom_fields': [],
        }
        payload.update(overrides)
        return payload

    def test_edit_one_shot(self):
        """固定字段+已有字段值更新+新增自定义字段+组成项一次提交全部生效。"""
        payload = self._payload(config_values={
            str(self.template_field.id): '438.000MHz',
            str(self.number_field.id): '20',
        }, custom_fields=[
            {'client_key': 'temp_1', 'name': '特别说明', 'field_type': 'text',
             'required': False, 'value': '一次填好'},
        ], components=[
            {'name': '接入交换机', 'quantity': 2},
        ])
        resp = self.client.put(f'{URL}/{self.system.id}/', payload,
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.system.refresh_from_db()
        self.assertEqual(self.system.name, '编辑后的系统')
        value = SystemConfigValue.objects.get(system=self.system, field=self.template_field)
        self.assertEqual(value.value_text, '438.000MHz')
        self.assertEqual(SystemConfigValue.objects.get(
            system=self.system, field=self.number_field).value_number, 20.0)
        custom = ConfigFieldDefinition.objects.get(
            scope_type='custom', scope_owner_id=str(self.system.id),
            display_name='特别说明')
        self.assertTrue(SystemConfigValue.objects.filter(
            system=self.system, field=custom, value_text='一次填好').exists())
        self.assertTrue(SystemConfigComponent.objects.filter(
            system=self.system, name='接入交换机', quantity=2).exists())
        # 变更历史：固定字段 update + 配置值 update + 字段定义 create + 配置值 create
        self.assertTrue(SystemConfigChange.objects.filter(
            system=self.system, source='system', action='update').exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=self.system, source='config', action='update').exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=self.system, source='field_definition', action='create').exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=self.system, source='config', action='create').exists())
        # 编辑后无需再次补录：新字段值与本次编辑同时生效
        self.assertEqual(SystemConfigValue.objects.filter(system=self.system).count(), 3)

    def test_edit_rollback_on_invalid_value(self):
        """非法动态值整体回滚：固定字段与已有值保持原样。"""
        payload = self._payload(config_values={
            str(self.number_field.id): 'abc',
        })
        resp = self.client.put(f'{URL}/{self.system.id}/', payload,
                               content_type='application/json')
        self.assertIn('数字', resp.json().get('error', ''))
        self.system.refresh_from_db()
        self.assertEqual(self.system.name, '烟台中心站通信系统')
        value = SystemConfigValue.objects.get(system=self.system, field=self.template_field)
        self.assertEqual(value.value_text, '旧值')
        self.assertFalse(SystemConfigValue.objects.filter(
            system=self.system, field=self.number_field).exists())

    def test_edit_custom_field_requires_permission(self):
        """无字段管理权限的用户不能在编辑时创建字段定义；普通编辑不受影响。"""
        editor = make_user('agu_editor', [P_SYS_VIEW, P_SYS_EDIT], tenant_id='t8')
        client = make_client(editor)
        payload = self._payload(custom_fields=[
            {'client_key': 'temp_1', 'name': '天线高度乙', 'field_type': 'number', 'value': '1'},
        ])
        resp = client.put(f'{URL}/{self.system.id}/', payload, content_type='application/json')
        self.assertIn('权限', resp.json()['error'])
        self.assertFalse(ConfigFieldDefinition.objects.filter(
            scope_type='custom', scope_owner_id=str(self.system.id),
            display_name='天线高度乙').exists())
        payload = self._payload()
        resp = client.put(f'{URL}/{self.system.id}/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)

    def test_edit_rejects_deactivated_field_value(self):
        """停用字段提交新值被拒，历史值保留。"""
        self.template_field.is_active = False
        self.template_field.save()
        payload = self._payload(config_values={str(self.template_field.id): '新值'})
        resp = self.client.put(f'{URL}/{self.system.id}/', payload,
                               content_type='application/json')
        self.assertIn('不适用于当前系统', resp.json()['error'])
        value = SystemConfigValue.objects.get(system=self.system, field=self.template_field)
        self.assertEqual(value.value_text, '旧值')

    def test_edit_role_restricted_field_rejected(self):
        """普通用户只能编辑其有权限填写的字段（editable_roles）。"""
        self.template_field.editable_roles = json.dumps([999])
        self.template_field.save()
        payload = self._payload(config_values={str(self.template_field.id): '受限值'})
        resp = self.client.put(f'{URL}/{self.system.id}/', payload,
                               content_type='application/json')
        self.assertIn('不允许当前角色编辑', resp.json()['error'])

    def test_components_full_sync_on_edit(self):
        """components 键出现时按全量同步：更新、新增、删除。"""
        comp_a = SystemConfigComponent.objects.create(tenant_id='t8', system=self.system,
                                                      name='组成项甲', created_by=self.admin)
        comp_b = SystemConfigComponent.objects.create(tenant_id='t8', system=self.system,
                                                      name='组成项乙', created_by=self.admin)
        payload = self._payload(components=[
            {'id': comp_a.id, 'name': '组成项甲改', 'quantity': 3},
            {'name': '组成项丙'},
        ])
        resp = self.client.put(f'{URL}/{self.system.id}/', payload,
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        names = set(SystemConfigComponent.objects.filter(system=self.system)
                    .values_list('name', flat=True))
        self.assertEqual(names, {'组成项甲改', '组成项丙'})
        self.assertFalse(SystemConfigComponent.objects.filter(pk=comp_b.id).exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=self.system, source='component', action='update').exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=self.system, source='component', action='delete').exists())
        self.assertTrue(SystemConfigChange.objects.filter(
            system=self.system, source='component', action='create').exists())

    def test_components_untouched_when_key_absent(self):
        SystemConfigComponent.objects.create(tenant_id='t8', system=self.system,
                                             name='组成项甲', created_by=self.admin)
        resp = self.client.put(f'{URL}/{self.system.id}/', self._payload(),
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertTrue(SystemConfigComponent.objects.filter(name='组成项甲').exists())

    def test_components_unknown_id_rejected(self):
        payload = self._payload(components=[{'id': 99999, 'name': '幽灵组成项'}])
        resp = self.client.put(f'{URL}/{self.system.id}/', payload,
                               content_type='application/json')
        self.assertIn('不存在', resp.json()['error'])


class FormFieldsAndDetailTest(TestCase):
    def setUp(self):
        self.admin = make_user('ffa_admin', ALL_SYSTEM_PERMS + ALL_CONFIG_PERMS,
                               tenant_id='t7')
        self.client = make_client(self.admin)
        self.system = make_system(self.admin, tenant_id='t7', system_code='FF-001')
        self.active_field = make_field(self.system, self.admin, tenant_id='t7',
                                       field_code='frequency', display_name='工作频率')
        self.inactive_field = make_field(self.system, self.admin, tenant_id='t7',
                                         field_code='old_band', display_name='旧频段',
                                         is_active=False)
        SystemConfigValue.objects.create(tenant_id='t7', system=self.system,
                                         field=self.inactive_field, value_text='VHF',
                                         updated_by=self.admin)

    def test_form_fields_requires_system_param(self):
        """form-fields 接口只支持编辑模式：缺少 system 参数返回业务错误。"""
        resp = self.client.get(f'{URL}/form-fields/')
        self.assertEqual(resp.json().get('error'), '缺少 system 参数')

    def test_form_fields_by_system_returns_values_and_components(self):
        """编辑模式：返回适用字段（含停用）、当前值与已有组成项。"""
        SystemConfigComponent.objects.create(tenant_id='t7', system=self.system,
                                             name='组成项甲', created_by=self.admin)
        resp = self.client.get(f'{URL}/form-fields/?system={self.system.id}')
        self.assertFalse(resp.json().get('error'), resp.content)
        codes = {f['field_code'] for f in resp.json()['data']['data']}
        self.assertEqual(codes, {'frequency', 'old_band'})
        values = resp.json()['data']['values']
        self.assertEqual(values[str(self.inactive_field.id)]['display'], 'VHF')
        self.assertEqual([c['name'] for c in resp.json()['data']['components']], ['组成项甲'])
        self.assertEqual(resp.json()['data']['system']['system_code'], 'FF-001')

    def test_form_fields_hides_role_restricted_visibility(self):
        self.active_field.visible_roles = json.dumps([999])
        self.active_field.save()
        viewer = make_user('ffa_viewer', [P_SYS_VIEW], tenant_id='t7')
        client = make_client(viewer)
        resp = client.get(f'{URL}/form-fields/?system={self.system.id}')
        codes = {f['field_code'] for f in resp.json()['data']['data']}
        self.assertEqual(codes, {'old_band'})

    def test_detail_merges_dynamic_fields_into_basic_info(self):
        """详情接口合并固定+自定义字段（含停用字段历史值）。"""
        custom = make_field(self.system, self.admin, tenant_id='t7',
                            field_code='note_f', display_name='特别说明')
        SystemConfigValue.objects.create(tenant_id='t7', system=self.system,
                                         field=custom, value_text='备注值',
                                         updated_by=self.admin)
        resp = self.client.get(f'{URL}/{self.system.id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        config_fields = resp.json()['data']['config_fields']
        scopes = {f['field_code']: f['scope_type'] for f in config_fields}
        self.assertEqual(scopes['frequency'], 'custom')
        self.assertEqual(scopes['note_f'], 'custom')
        entry = [f for f in config_fields if f['field_code'] == 'old_band'][0]
        self.assertFalse(entry['is_active'])
        self.assertEqual(entry['display'], 'VHF')

    def test_detail_sensitive_view_audited(self):
        field = make_field(self.system, self.admin, tenant_id='t7',
                           field_code='freq_plan', display_name='频率规划', is_sensitive=True)
        SystemConfigValue.objects.create(tenant_id='t7', system=self.system,
                                         field=field, value_text='敏感内容',
                                         updated_by=self.admin)
        before = AuditLog.objects.filter(detail__contains='sensitive_view').count()
        self.client.get(f'{URL}/{self.system.id}/')
        after = AuditLog.objects.filter(detail__contains='sensitive_view').count()
        self.assertEqual(after, before + 1)
