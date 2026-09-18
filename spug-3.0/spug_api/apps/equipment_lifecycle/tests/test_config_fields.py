# -*- coding: utf-8 -*-
"""配置档案字段与值（步骤二）稳定契约测试。

覆盖任务九要求：不同类型展示不同模板字段、自定义字段隔离、
必填/类型/候选项/范围校验、字段停用后历史值保留、
敏感关键词拦截、权限独立校验、字段定义删除不级联删除历史值。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.models import (
    ConfigFieldDefinition,
    LifecycleSystem,
    SystemConfigChange,
    SystemConfigValue,
)
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS, ALL_TYPE_PERMS,
    P_CFG_EDIT, P_CFG_FIELD, P_CFG_VIEW,
    make_client, make_field, make_system, make_type, make_user,
)


class TemplateFieldTest(TestCase):
    def setUp(self):
        self.admin = make_user('cfg_admin', ALL_CONFIG_PERMS + ALL_TYPE_PERMS, tenant_id='t1')
        self.client = make_client(self.admin)
        self.type_comm = make_type(self.admin, tenant_id='t1', name='通信系统')
        self.type_soft = make_type(self.admin, tenant_id='t1', name='软件系统')

    def _field_payload(self, **overrides):
        payload = {
            'field_code': 'frequency',
            'display_name': '工作频率',
            'field_type': 'text',
            'help_text': '单位 MHz',
            'display_order': 1,
            'is_required': False,
            'default_value': '',
            'choices': '',
            'is_searchable': True,
            'is_filterable': True,
            'is_exportable': True,
        }
        payload.update(overrides)
        return payload

    def test_template_field_crud(self):
        resp = self.client.post(
            f'/equipment-lifecycle/system-types/{self.type_comm.id}/fields/',
            self._field_payload(), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        field_id = resp.json()['data']['id']
        self.assertTrue(ConfigFieldDefinition.objects.filter(
            pk=field_id, scope_type='template', scope_owner_id=str(self.type_comm.id)).exists())
        # 重复编码/名称被拒
        resp = self.client.post(
            f'/equipment-lifecycle/system-types/{self.type_comm.id}/fields/',
            self._field_payload(), content_type='application/json')
        self.assertIn('重复', resp.json()['error'])
        # 与固定字段重名被拒
        resp = self.client.post(
            f'/equipment-lifecycle/system-types/{self.type_comm.id}/fields/',
            self._field_payload(field_code='install_location', display_name='安装地点'),
            content_type='application/json')
        self.assertIn('固定核心字段', resp.json()['error'])
        # 停用
        resp = self.client.put(
            f'/equipment-lifecycle/system-types/{self.type_comm.id}/fields/{field_id}/',
            self._field_payload(is_active=False), content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        field = ConfigFieldDefinition.objects.get(pk=field_id)
        self.assertFalse(field.is_active)

    def test_different_types_show_different_template_fields(self):
        make_field(self.type_comm, self.admin, tenant_id='t1', field_code='frequency',
                   display_name='工作频率')
        make_field(self.type_soft, self.admin, tenant_id='t1', field_code='db_version',
                   display_name='数据库版本')
        sys_comm = make_system(self.admin, system_type=self.type_comm, tenant_id='t1')
        sys_soft = make_system(self.admin, system_type=self.type_soft, tenant_id='t1',
                               system_code='SYS-SOFT')
        resp_comm = self.client.get(f'/equipment-lifecycle/systems/{sys_comm.id}/config/')
        resp_soft = self.client.get(f'/equipment-lifecycle/systems/{sys_soft.id}/config/')
        codes_comm = {f['field_code'] for f in resp_comm.json()['data']['fields']}
        codes_soft = {f['field_code'] for f in resp_soft.json()['data']['fields']}
        self.assertEqual(codes_comm, {'frequency'})
        self.assertEqual(codes_soft, {'db_version'})

    def test_sensitive_keyword_rejected(self):
        for bad_code, bad_name in (('password', '口令字段'), ('api_token', '接口字段'),
                                   ('frequency', '密码字段')):
            resp = self.client.post(
                f'/equipment-lifecycle/system-types/{self.type_comm.id}/fields/',
                self._field_payload(field_code=bad_code, display_name=bad_name),
                content_type='application/json')
            self.assertIn('关键词', resp.json()['error'])

    def test_choice_field_requires_options(self):
        resp = self.client.post(
            f'/equipment-lifecycle/system-types/{self.type_comm.id}/fields/',
            self._field_payload(field_code='band', display_name='频段',
                                field_type='choice', choices=''),
            content_type='application/json')
        self.assertIn('候选项', resp.json()['error'])
        resp = self.client.post(
            f'/equipment-lifecycle/system-types/{self.type_comm.id}/fields/',
            self._field_payload(field_code='band', display_name='频段', field_type='choice',
                                choices=json.dumps(['UHF', 'VHF'])),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)


class CustomFieldTest(TestCase):
    def setUp(self):
        self.admin = make_user('cf_admin', ALL_CONFIG_PERMS, tenant_id='t1')
        self.client = make_client(self.admin)
        self.system_type = make_type(self.admin, tenant_id='t1', name='通信系统')
        self.system = make_system(self.admin, system_type=self.system_type, tenant_id='t1')
        self.other_system = make_system(self.admin, system_type=self.system_type,
                                        tenant_id='t1', system_code='SYS-OTHER')

    def _payload(self, **overrides):
        payload = {
            'field_code': 'special_note',
            'display_name': '特别说明',
            'field_type': 'text',
            'display_order': 9,
        }
        payload.update(overrides)
        return payload

    def test_custom_field_isolated_between_systems(self):
        resp = self.client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
            self._payload(), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        field_id = resp.json()['data']['id']
        # 自己系统可见，其他系统不可见
        resp_own = self.client.get(f'/equipment-lifecycle/systems/{self.system.id}/config/')
        codes_own = {f['field_code'] for f in resp_own.json()['data']['fields']}
        self.assertIn('special_note', codes_own)
        resp_other = self.client.get(f'/equipment-lifecycle/systems/{self.other_system.id}/config/')
        codes_other = {f['field_code'] for f in resp_other.json()['data']['fields']}
        self.assertNotIn('special_note', codes_other)
        self.assertEqual(ConfigFieldDefinition.objects.get(pk=field_id).system_id,
                         self.system.id)

    def test_custom_field_cannot_duplicate_template_or_fixed(self):
        make_field(self.system_type, self.admin, tenant_id='t1', field_code='frequency',
                   display_name='工作频率')
        # 与模板字段同名编码
        resp = self.client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
            self._payload(field_code='frequency'), content_type='application/json')
        self.assertIn('重复', resp.json()['error'])
        # 与固定字段同名
        resp = self.client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
            self._payload(field_code='use_unit', display_name='使用单位'),
            content_type='application/json')
        self.assertIn('固定核心字段', resp.json()['error'])

    def test_deactivated_custom_field_keeps_value(self):
        """字段停用后不再用于新录入，但历史值必须保留可查。"""
        resp = self.client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
            self._payload(), content_type='application/json')
        field_id = resp.json()['data']['id']
        # 录入值
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(field_id): '天线偏移 2 米'}},
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 停用
        resp = self.client.put(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/{field_id}/',
            self._payload(is_active=False), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 配置视图中历史值仍显示（inactive 字段包含）
        resp = self.client.get(f'/equipment-lifecycle/systems/{self.system.id}/config/')
        data = resp.json()['data']
        field_entry = [f for f in data['fields'] if f['id'] == field_id][0]
        self.assertFalse(field_entry['is_active'])
        self.assertEqual(data['values'][str(field_id)]['display'], '天线偏移 2 米')
        # 停用字段提交新值被拒绝
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(field_id): '新值不允许'}},
                               content_type='application/json')
        self.assertIn('停用', resp.json()['error'])
        # 删除被拒（有历史值）
        resp = self.client.delete(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/{field_id}/')
        self.assertIn('历史值', resp.json()['error'])
        self.assertTrue(ConfigFieldDefinition.objects.filter(pk=field_id).exists())
        self.assertTrue(SystemConfigValue.objects.filter(field_id=field_id).exists())

    def test_delete_field_without_values_allowed_values_of_others_intact(self):
        resp = self.client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
            self._payload(field_code='unused_f', display_name='未用字段'),
            content_type='application/json')
        field_id = resp.json()['data']['id']
        # 另一字段有值
        resp2 = self.client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
            self._payload(field_code='used_f', display_name='有用字段'),
            content_type='application/json')
        used_id = resp2.json()['data']['id']
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(used_id): '保留值'}},
                        content_type='application/json')
        resp = self.client.delete(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/{field_id}/')
        self.assertFalse(resp.json().get('error'))
        self.assertFalse(ConfigFieldDefinition.objects.filter(pk=field_id).exists())
        # 有值字段未被级联删除
        self.assertTrue(SystemConfigValue.objects.filter(field_id=used_id).exists())

    def test_promote_custom_field_to_template(self):
        """同一含义复用时可提升为类型模板字段，值随迁移。"""
        resp = self.client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
            self._payload(), content_type='application/json')
        field_id = resp.json()['data']['id']
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(field_id): '提升前的值'}},
                        content_type='application/json')
        resp = self.client.post(
            f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/{field_id}/promote/')
        self.assertFalse(resp.json().get('error'), resp.content)
        promoted_id = resp.json()['data']['id']
        promoted = ConfigFieldDefinition.objects.get(pk=promoted_id)
        self.assertEqual(promoted.scope_type, 'template')
        self.assertEqual(promoted.system_type_id, self.system_type.id)
        self.assertFalse(ConfigFieldDefinition.objects.filter(pk=field_id).exists())
        # 值已迁移到新模板字段
        value = SystemConfigValue.objects.get(field_id=promoted_id)
        self.assertEqual(value.value_text, '提升前的值')
        self.assertEqual(value.system_id, self.system.id)
        # 提升动作进入变更历史
        self.assertTrue(SystemConfigChange.objects.filter(
            system=self.system, action='promote').exists())
        # 同类型下其他系统的配置视图现在能看到该模板字段
        resp = self.client.get(f'/equipment-lifecycle/systems/{self.other_system.id}/config/')
        codes = {f['field_code'] for f in resp.json()['data']['fields']}
        self.assertIn('special_note', codes)

    def test_field_permission_denied(self):
        viewer = make_user('cf_viewer', [P_CFG_VIEW], tenant_id='t1')
        client = make_client(viewer)
        resp = client.post(f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
                           self._payload(), content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        # 无 field 权限的 ALL_CONFIG_PERMS 用户已含 field；单独构造无 field 用户
        editor = make_user('cf_editor',
                           [P_CFG_VIEW, P_CFG_EDIT], tenant_id='t1')
        client2 = make_client(editor)
        resp = client2.post(f'/equipment-lifecycle/systems/{self.system.id}/custom-fields/',
                            self._payload(), content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')


class ConfigValueValidationTest(TestCase):
    def setUp(self):
        self.admin = make_user('val_admin', ALL_CONFIG_PERMS + ALL_TYPE_PERMS, tenant_id='t1')
        self.client = make_client(self.admin)
        self.system_type = make_type(self.admin, tenant_id='t1', name='通信系统')
        self.system = make_system(self.admin, system_type=self.system_type, tenant_id='t1')

    def _add_field(self, **kwargs):
        defaults = dict(tenant_id='t1', field_code='num_field', display_name='数字字段',
                        field_type='number')
        defaults.update(kwargs)
        return make_field(self.system_type, self.admin, **defaults)

    def test_number_range_validation(self):
        field = self._add_field(number_min=0, number_max=100)
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(field.id): '150'}},
                               content_type='application/json')
        self.assertIn('不能大于', resp.json()['error'])
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(field.id): 'abc'}},
                               content_type='application/json')
        self.assertIn('数字', resp.json()['error'])
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(field.id): '50'}},
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        value = SystemConfigValue.objects.get(system=self.system, field=field)
        self.assertEqual(value.value_number, 50.0)

    def test_choice_validation(self):
        field = self._add_field(field_code='band', display_name='频段', field_type='choice',
                                choices=json.dumps(['UHF', 'VHF']))
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(field.id): 'SHF'}},
                               content_type='application/json')
        self.assertIn('候选项', resp.json()['error'])
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(field.id): 'UHF'}},
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'))

    def test_multi_choice_and_boolean_and_date(self):
        multi = self._add_field(field_code='modes', display_name='工作模式',
                                field_type='multi_choice',
                                choices=json.dumps(['定频', '跳频', '自适应']))
        boolean = self._add_field(field_code='redundant', display_name='是否冗余',
                                  field_type='boolean')
        date_f = self._add_field(field_code='upgrade_date', display_name='升级日期',
                                 field_type='date')
        resp = self.client.put(
            f'/equipment-lifecycle/systems/{self.system.id}/config/',
            {'config_values': {str(multi.id): ['定频', '跳频'], str(boolean.id): True,
                        str(date_f.id): '2026-09-01'}},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(SystemConfigValue.objects.get(field=multi).value_text,
                         json.dumps(['定频', '跳频'], ensure_ascii=False))
        self.assertTrue(SystemConfigValue.objects.get(field=boolean).value_bool)
        self.assertEqual(str(SystemConfigValue.objects.get(field=date_f).value_date),
                         '2026-09-01')
        # 非法多选项被拒
        resp = self.client.put(
            f'/equipment-lifecycle/systems/{self.system.id}/config/',
            {'config_values': {str(multi.id): ['定频', '不存在的选项']}},
            content_type='application/json')
        self.assertIn('不在可选项内', resp.json()['error'])

    def test_required_field_enforced(self):
        field = self._add_field(field_code='antenna_h', display_name='天线高度',
                                field_type='text', is_required=True)
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {}}, content_type='application/json')
        self.assertIn('必填', resp.json()['error'])
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(field.id): '25米'}},
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)

    def test_foreign_field_rejected(self):
        """其他系统的自定义字段 / 其他类型的模板字段提交被拒。"""
        other_system = make_system(self.admin, system_type=self.system_type,
                                   tenant_id='t1', system_code='SYS-F')
        foreign_field = make_field(other_system, self.admin, tenant_id='t1',
                                   scope='custom', field_code='foreign_f',
                                   display_name='外部字段')
        resp = self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                               {'config_values': {str(foreign_field.id): 'x'}},
                               content_type='application/json')
        self.assertIn('不适用于当前系统', resp.json()['error'])

    def test_tenant_isolation_on_config(self):
        outsider = make_user('val_out', ALL_CONFIG_PERMS, tenant_id='t2')
        client = make_client(outsider)
        resp = client.get(f'/equipment-lifecycle/systems/{self.system.id}/config/')
        self.assertEqual(resp.json().get('error'), '系统不存在')

    def test_config_save_records_history(self):
        field = self._add_field(field_code='antenna_h', display_name='天线高度',
                                field_type='text')
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(field.id): '20米'}},
                        content_type='application/json')
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(field.id): '30米'}},
                        content_type='application/json')
        change = SystemConfigChange.objects.filter(
            system=self.system, source='config').latest('id')
        changes = json.loads(change.changes)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['old'], '20米')
        self.assertEqual(changes[0]['new'], '30米')
        self.assertEqual(changes[0]['label'], '天线高度')

    def test_sensitive_value_view_audited(self):
        field = self._add_field(field_code='freq_plan', display_name='频率规划',
                                field_type='text', is_sensitive=True)
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(field.id): '敏感内容'}},
                        content_type='application/json')
        before = AuditLog.objects.filter(detail__contains='sensitive_view').count()
        self.client.get(f'/equipment-lifecycle/systems/{self.system.id}/config/')
        after = AuditLog.objects.filter(detail__contains='sensitive_view').count()
        self.assertEqual(after, before + 1)

    def test_type_change_with_existing_values_blocked(self):
        field = self._add_field(field_code='antenna_h', display_name='天线高度',
                                field_type='text')
        self.client.put(f'/equipment-lifecycle/systems/{self.system.id}/config/',
                        {'config_values': {str(field.id): '20米'}},
                        content_type='application/json')
        resp = self.client.put(
            f'/equipment-lifecycle/system-types/{self.system_type.id}/fields/{field.id}/',
            {'field_code': 'antenna_h', 'display_name': '天线高度', 'field_type': 'number',
             'display_order': 0, 'is_active': True},
            content_type='application/json')
        self.assertIn('不能变更字段类型', resp.json()['error'])
