# -*- coding: utf-8 -*-
"""系统配置变更（2026-10）真实行为测试。

覆盖任务要求的 15 项场景（HTTP 真实路径 + 数据库副作用断言，
不读取源码、不使用正则匹配冒充行为测试）：
1.  不同系统可以拥有不同配置参数；
2.  当前配置可以正确查询（适用/启用参数 + 类型化当前值）；
3.  配置变更保存前值和后值（后端生成快照，不信任前端）；
4.  应用变更后当前配置正确更新（类型化字段 + 生效来源）；
5.  变更前值不匹配（被并发覆盖）时拒绝应用；
6.  枚举、数字、布尔和日期校验真实生效（含文本正则与必填）；
7.  已生效记录不能被普通编辑静默覆盖；
8.  回退生成新的反向变更，原记录仍存在且内容不改写；
9.  普通配置变更不自动进入系统履历；
10. 重要配置变更进入履历且只生成一次（重复应用被状态机拒绝）；
11. 跨租户配置与附件互不可见；
12. 无权限用户后端真实拒绝操作；
13. 重复提交（client_token/窗口查重）不会生成重复配置变更；
14. 敏感配置（密码/令牌/密钥）在参数定义层被拒绝保存；
15. 附件访问必须先校验父对象与租户。
"""
import uuid
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.equipment_lifecycle.config_models import (
    ConfigChangeItem,
    ConfigChangeRecord,
    ConfigParamDefinition,
    SystemParamValue,
)
from apps.equipment_lifecycle.models import SystemEvent
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX,
    make_client, make_system, make_user,
)

P_VIEW = 'equipment_lifecycle.config.view'
P_ADD = 'equipment_lifecycle.config.add'
P_EDIT = 'equipment_lifecycle.config.edit'
P_APPLY = 'equipment_lifecycle.config.apply'
P_VERIFY = 'equipment_lifecycle.config.verify'
P_ROLLBACK = 'equipment_lifecycle.config.rollback'
P_TEMPLATE = 'equipment_lifecycle.config.template'
P_ATTACHMENT = 'equipment_lifecycle.config.attachment'

ALL_CONFIG_PERMS = [P_VIEW, P_ADD, P_EDIT, P_APPLY, P_VERIFY, P_ROLLBACK,
                    P_TEMPLATE, P_ATTACHMENT]

CONFIG_URL = URL_PREFIX + '/config-params'


def make_param(created_by, tenant_id='tenant_a', param_code=None, **kwargs):
    system_ids = kwargs.pop('system_ids', [])
    defaults = dict(
        param_code=param_code or ('p_%s' % uuid.uuid4().hex[:8]),
        param_name='发射功率',
        scope_type='all',
        data_type='number',
        unit='dB',
        is_required=False,
        enum_options='',
        validation_regex='',
        is_enabled=True,
        remark='',
        tenant_id=tenant_id,
        created_by=created_by,
    )
    defaults.update(kwargs)
    param = ConfigParamDefinition.objects.create(**defaults)
    if param.scope_type == 'specific' and system_ids:
        from apps.equipment_lifecycle.config_models import ConfigParamSystemScope
        ConfigParamSystemScope.objects.bulk_create([
            ConfigParamSystemScope(tenant_id=tenant_id, param=param, system=s)
            for s in system_ids
        ])
    return param


class ConfigTestBase:
    """公共夹具：全权限用户 + 无权限用户 + 双租户（client 必须在 setUp 创建）。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user(
            'cfg_admin_%s' % uuid.uuid4().hex[:8], ALL_CONFIG_PERMS, tenant_id='tenant_a')
        cls.noperm = make_user(
            'cfg_noperm_%s' % uuid.uuid4().hex[:8], [], tenant_id='tenant_a')
        cls.other_admin = make_user(
            'cfg_other_%s' % uuid.uuid4().hex[:8], ALL_CONFIG_PERMS, tenant_id='tenant_b')

    def setUp(self):
        self.client = make_client(self.admin)
        self.other_client = make_client(self.other_admin)
        self.noperm_client = make_client(self.noperm)
        self.system = make_system(self.admin, tenant_id='tenant_a',
                                  system_code='CFG-SYS-A-%s' % uuid.uuid4().hex[:6].upper())
        self.other_system = make_system(self.other_admin, tenant_id='tenant_b',
                                        system_code='CFG-SYS-B-%s' % uuid.uuid4().hex[:6].upper())

    def create_param(self, **kwargs):
        return make_param(self.admin, **kwargs)

    def create_change(self, client=None, system=None, items=None, **overrides):
        """创建草稿配置变更，返回响应 data（断言业务成功）。"""
        client = client or self.client
        system = system or self.system
        payload = {
            'system': system.id,
            'reason': overrides.pop('reason', '例行参数调整 %s' % uuid.uuid4().hex[:6]),
            'items': items or [],
            'include_in_history': False,
            'history_reason': '',
            'verify_note': '',
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }
        payload.update(overrides)
        resp = client.post(URL_PREFIX + '/config-changes/', payload,
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def apply_change(self, change_id, client=None):
        client = client or self.client
        resp = client.post(URL_PREFIX + '/config-changes/%s/apply/' % change_id, {},
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def get_current_config(self, system_id=None, client=None):
        client = client or self.client
        resp = client.get(URL_PREFIX + '/systems/%s/config/' % (system_id or self.system.id))
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']


class CurrentConfigTests(ConfigTestBase, TestCase):
    """场景 1/2：不同系统不同参数 + 当前配置查询。"""

    def test_specific_param_only_visible_to_scope_system(self):
        # 全局参数对同租户全部系统适用；specific 参数只出现在适用系统；
        # 参数定义租户私有，跨租户同名参数互不可见
        self.create_param(param_code='global_power', param_name='发射功率', data_type='number')
        self.create_param(param_code='only_sys_a', param_name='仅A系统参数',
                          data_type='text', scope_type='specific',
                          system_ids=[self.system])
        make_param(self.other_admin, tenant_id='tenant_b',
                   param_code='global_power', param_name='发射功率B', data_type='number')
        data_a = self.get_current_config(self.system.id)
        codes_a = [item['param_code'] for item in data_a['items']]
        self.assertIn('global_power', codes_a)
        self.assertIn('only_sys_a', codes_a)
        data_b = self.get_current_config(self.other_system.id, client=self.other_client)
        codes_b = [item['param_code'] for item in data_b['items']]
        self.assertIn('global_power', codes_b)
        self.assertNotIn('only_sys_a', codes_b)
        # 租户 B 只能查到自己的参数定义
        for item in data_b['items']:
            self.assertEqual(item['param_name'] != '仅A系统参数', True)

    def test_disabled_param_not_in_current_config(self):
        param = self.create_param()
        param.is_enabled = False
        param.save()
        data = self.get_current_config()
        self.assertNotIn(param.id, [item['param'] for item in data['items']])

    def test_current_config_query_with_values(self):
        param = self.create_param(param_code='tx_power', data_type='number', unit='dB')
        SystemParamValue.objects.create(
            tenant_id='tenant_a', system=self.system, param=param,
            value_number=42.5, effective_at='2026-10-01 08:00:00')
        data = self.get_current_config()
        row = [x for x in data['items'] if x['param_code'] == 'tx_power'][0]
        self.assertEqual(row['display_value'], '42.5')
        self.assertEqual(row['data_type_text'], '数字')
        self.assertEqual(row['unit'], 'dB')
        self.assertEqual(row['effective_at'], '2026-10-01 08:00:00')
        self.assertEqual(row['last_changed_by_name'], '')


class SnapshotAndApplyTests(ConfigTestBase, TestCase):
    """场景 3/4/5：前后值快照、应用生效、并发覆盖拒绝。"""

    def test_create_change_stores_snapshots_and_keeps_value(self):
        number_param = self.create_param(param_code='tx_power', data_type='number', unit='dB')
        choice_param = self.create_param(param_code='work_mode', data_type='choice',
                                         enum_options='["主用", "备用"]')
        SystemParamValue.objects.create(
            tenant_id='tenant_a', system=self.system, param=number_param,
            value_number=40, effective_at='2026-09-01 08:00:00')
        data = self.create_change(items=[
            {'param': number_param.id, 'new_value': '42.5', 'remark': '功率上调'},
            {'param': choice_param.id, 'new_value': '备用', 'remark': ''},
        ])
        self.assertRegex(data['change_no'], r'^PZ\d{8}-\d{4}$')
        self.assertEqual(data['status'], 'draft')
        detail_resp = self.client.get(URL_PREFIX + '/config-changes/%s/' % data['id'])
        detail = detail_resp.json()['data']
        by_code = {item['param_code']: item for item in detail['items']}
        # 前值由后端从数据库当前值生成（不信任前端传入的旧值）
        self.assertEqual(by_code['tx_power']['old_value'], '40')
        self.assertEqual(by_code['tx_power']['new_value'], '42.5')
        self.assertEqual(by_code['tx_power']['unit'], 'dB')
        # 此前未设置的参数前值为空串
        self.assertEqual(by_code['work_mode']['old_value'], '')
        self.assertEqual(by_code['work_mode']['new_value'], '备用')
        # 创建草稿不改当前值
        self.assertFalse(SystemParamValue.objects.filter(param=choice_param).exists())
        row = SystemParamValue.objects.get(param=number_param)
        self.assertEqual(row.value_number, Decimal('40'))

    def test_apply_updates_current_value_typed_fields(self):
        number_param = self.create_param(param_code='tx_power', data_type='number', unit='dB')
        bool_param = self.create_param(param_code='auto_switch', param_name='自动切换',
                                       data_type='bool')
        date_param = self.create_param(param_code='calib_date', param_name='校准日期',
                                       data_type='date')
        change = self.create_change(items=[
            {'param': number_param.id, 'new_value': '42.5', 'remark': ''},
            {'param': bool_param.id, 'new_value': 'true', 'remark': ''},
            {'param': date_param.id, 'new_value': '2026-10-02', 'remark': ''},
        ])
        self.apply_change(change['id'])
        row = SystemParamValue.objects.get(system=self.system, param=number_param)
        self.assertEqual(row.value_number, Decimal('42.5'))
        self.assertEqual(row.last_changed_by, self.admin)
        self.assertIsNotNone(row.last_change)
        bool_row = SystemParamValue.objects.get(system=self.system, param=bool_param)
        self.assertTrue(bool_row.value_bool)
        date_row = SystemParamValue.objects.get(system=self.system, param=date_param)
        self.assertEqual(str(date_row.value_date), '2026-10-02')
        detail = self.client.get(
            URL_PREFIX + '/config-changes/%s/' % change['id']).json()['data']
        self.assertEqual(detail['status'], 'applied')
        self.assertIsNotNone(detail['applied_at'])
        # 当前配置接口反映新值
        data = self.get_current_config()
        by_code = {item['param_code']: item for item in data['items']}
        self.assertEqual(by_code['tx_power']['display_value'], '42.5')
        self.assertEqual(by_code['auto_switch']['display_value'], 'true')
        self.assertEqual(by_code['calib_date']['display_value'], '2026-10-02')
        self.assertEqual(by_code['tx_power']['last_change_no'], detail['change_no'])
        self.assertEqual(by_code['tx_power']['last_changed_by_name'], self.admin.username)

    def test_apply_rejects_concurrently_overwritten_old_value(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        SystemParamValue.objects.create(
            tenant_id='tenant_a', system=self.system, param=param,
            value_number=40, effective_at='2026-09-01 08:00:00')
        # 两条变更都基于 old=40 创建
        first = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        second = self.create_change(items=[{'param': param.id, 'new_value': '42', 'remark': ''}])
        self.apply_change(first['id'])
        # 应用第二条时数据库当前值已变为 41 ≠ 快照 40 → 拒绝，状态保持草稿
        resp = self.client.post(URL_PREFIX + '/config-changes/%s/apply/' % second['id'], {},
                                content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'))
        self.assertIn('已被其他变更修改', body['error'])
        status = self.client.get(
            URL_PREFIX + '/config-changes/%s/' % second['id']).json()['data']['status']
        self.assertEqual(status, 'draft')
        row = SystemParamValue.objects.get(system=self.system, param=param)
        self.assertEqual(row.value_number, Decimal('41'))


class ValueValidationTests(ConfigTestBase, TestCase):
    """场景 6：枚举、数字、布尔、日期、正则与必填校验真实生效。"""

    def test_choice_rejects_option_not_allowed(self):
        param = self.create_param(param_code='work_mode', data_type='choice',
                                  enum_options='["主用", "备用"]')
        resp = self.client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': 'x',
            'items': [{'param': param.id, 'new_value': '应急'}],
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }, content_type='application/json')
        self.assertIn('只能提交允许的选项', resp.json()['error'])

    def test_number_rejects_non_numeric(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        resp = self.client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': 'x',
            'items': [{'param': param.id, 'new_value': 'abc'}],
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }, content_type='application/json')
        self.assertIn('必须是数字', resp.json()['error'])

    def test_bool_rejects_invalid_word(self):
        param = self.create_param(param_code='auto_switch', data_type='bool')
        resp = self.client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': 'x',
            'items': [{'param': param.id, 'new_value': 'yes'}],
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }, content_type='application/json')
        self.assertIn('必须是布尔值', resp.json()['error'])
        # 合法值（false）可以创建并正确存储
        data = self.create_change(items=[{'param': param.id, 'new_value': 'false', 'remark': ''}])
        item = ConfigChangeItem.objects.get(change_id=data['id'])
        self.assertEqual(item.new_value, 'false')

    def test_date_rejects_invalid_format(self):
        param = self.create_param(param_code='calib_date', data_type='date')
        resp = self.client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': 'x',
            'items': [{'param': param.id, 'new_value': '2026/10/02'}],
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }, content_type='application/json')
        self.assertIn('YYYY-MM-DD', resp.json()['error'])

    def test_text_regex_and_required(self):
        param = self.create_param(param_code='site_label', param_name='站点标识',
                                  data_type='text', validation_regex=r'^VHF-\d+$')
        resp = self.client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': 'x',
            'items': [{'param': param.id, 'new_value': 'abc'}],
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }, content_type='application/json')
        self.assertIn('不符合校验规则', resp.json()['error'])
        # 必填参数不允许提交空值
        required_param = self.create_param(param_code='must_set', param_name='必填参数',
                                           data_type='text', is_required=True)
        resp = self.client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': 'x',
            'items': [{'param': required_param.id, 'new_value': ''}],
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }, content_type='application/json')
        self.assertIn('必填项', resp.json()['error'])

    def test_same_value_rejected(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        SystemParamValue.objects.create(
            tenant_id='tenant_a', system=self.system, param=param,
            value_number=40, effective_at='2026-09-01 08:00:00')
        resp = self.client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': 'x',
            'items': [{'param': param.id, 'new_value': '40'}],
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }, content_type='application/json')
        self.assertIn('与当前值相同', resp.json()['error'])


class StateMachineTests(ConfigTestBase, TestCase):
    """场景 7/8：已生效不可普通编辑、回退生成反向变更、验证与取消。"""

    def _prepare_applied(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        SystemParamValue.objects.create(
            tenant_id='tenant_a', system=self.system, param=param,
            value_number=40, effective_at='2026-09-01 08:00:00')
        change = self.create_change(items=[{'param': param.id, 'new_value': '42', 'remark': ''}])
        self.apply_change(change['id'])
        return param, change

    def test_applied_change_cannot_be_edited(self):
        _, change = self._prepare_applied()
        resp = self.client.put(
            URL_PREFIX + '/config-changes/%s/' % change['id'],
            {'reason': '试图覆盖', 'items': [{'param': 1, 'new_value': '999'}]},
            content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'))
        self.assertIn('草稿', body['error'])
        detail = self.client.get(
            URL_PREFIX + '/config-changes/%s/' % change['id']).json()['data']
        self.assertIn('例行参数调整', detail['reason'])

    def test_rollback_creates_reverse_change(self):
        param, change = self._prepare_applied()
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/rollback/' % change['id'], {},
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        rollback = body['data']
        self.assertNotEqual(rollback['id'], change['id'])
        self.assertRegex(rollback['change_no'], r'^PZ\d{8}-\d{4}$')
        self.assertEqual(rollback['status'], 'applied')
        self.assertEqual(rollback['rollback_of_no'], change['change_no'])
        # 原记录仍存在，只流转状态，内容不改写
        original = ConfigChangeRecord.objects.get(pk=change['id'])
        self.assertEqual(original.status, 'rolled_back')
        self.assertIn('例行参数调整', original.reason)
        item = ConfigChangeItem.objects.get(change_id=rollback['id'])
        self.assertEqual(item.old_value, '42')
        self.assertEqual(item.new_value, '40')
        # 当前值已恢复
        row = SystemParamValue.objects.get(system=self.system, param=param)
        self.assertEqual(row.value_number, Decimal('40'))
        # 重复回退拒绝
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/rollback/' % change['id'], {},
            content_type='application/json')
        # 已回退的变更再次回退必须被拒绝（状态机拦截，且不会产生第二条反向变更）
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(ConfigChangeRecord.objects.filter(
            rollback_of_id=change['id']).count(), 1)

    def test_verify_pass_and_fail(self):
        _, change = self._prepare_applied()
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/verify/' % change['id'],
            {'verify_status': 'failed', 'verify_note': '现场测试未通过'},
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['verify_status'], 'failed')
        self.assertEqual(body['data']['status'], 'applied')
        # 失败后可补验通过 → 状态转 verified，明细单项验证同步
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/verify/' % change['id'],
            {'verify_status': 'passed', 'verify_note': '复测通过'},
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['status'], 'verified')
        self.assertEqual(body['data']['verified_by_name'], self.admin.username)
        item = ConfigChangeItem.objects.get(change_id=change['id'])
        self.assertEqual(item.verify_status, 'passed')
        # verified 不可重复验证
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/verify/' % change['id'],
            {'verify_status': 'failed'}, content_type='application/json')
        self.assertIn('不能重复验证', resp.json()['error'])

    def test_cancel_draft_only(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/cancel/' % change['id'], {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(resp.json()['data']['status'], 'cancelled')
        # 已取消不能应用
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/apply/' % change['id'], {},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))


class HistoryEventTests(ConfigTestBase, TestCase):
    """场景 9/10：普通变更不进履历；重要变更进履历且只生成一次。"""

    def test_normal_change_writes_no_history_event(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        self.apply_change(change['id'])
        self.assertFalse(SystemEvent.objects.filter(
            event_type='config', source_id=str(change['id'])).exists())

    def test_important_change_writes_event_once(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(
            items=[{'param': param.id, 'new_value': '45', 'remark': ''}],
            include_in_history=True, history_reason='影响覆盖范围的功率调整')
        self.apply_change(change['id'])
        events = SystemEvent.objects.filter(event_type='config', source_id=str(change['id']))
        self.assertEqual(events.count(), 1)
        event = events.first()
        self.assertEqual(event.source_type, 'config_change')
        self.assertEqual(event.source_no, change['change_no'])
        self.assertEqual(event.action, 'apply')
        self.assertIn('配置变更', event.title)
        detail = event.get_detail()
        self.assertEqual(detail['history_reason'], '影响覆盖范围的功率调整')
        self.assertEqual(detail['items'][0]['param_code'], 'tx_power')
        # 重复应用被状态机拒绝 → 事件不会重复生成
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/apply/' % change['id'], {},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(
            SystemEvent.objects.filter(event_type='config', source_id=str(change['id'])).count(), 1)

    def test_rollback_of_important_change_also_in_history(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(
            items=[{'param': param.id, 'new_value': '45', 'remark': ''}],
            include_in_history=True, history_reason='重要调整')
        self.apply_change(change['id'])
        resp = self.client.post(
            URL_PREFIX + '/config-changes/%s/rollback/' % change['id'], {},
            content_type='application/json')
        rollback = resp.json()['data']
        events = SystemEvent.objects.filter(event_type='config')
        self.assertEqual(events.count(), 2)
        rollback_event = events.filter(source_no=rollback['change_no']).first()
        self.assertIsNotNone(rollback_event)
        self.assertEqual(rollback_event.action, 'rollback')


class TenantIsolationTests(ConfigTestBase, TestCase):
    """场景 11/12：跨租户互不可见；无权限用户被真实拒绝。"""

    def test_cross_tenant_invisible(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        # 租户 B 用户查不到租户 A 的系统/配置/变更
        resp = self.other_client.get(URL_PREFIX + '/systems/%s/config/' % self.system.id)
        self.assertIn('不存在', resp.json()['error'])
        resp = self.other_client.get(URL_PREFIX + '/config-changes/%s/' % change['id'])
        self.assertIn('不存在', resp.json()['error'])
        resp = self.other_client.post(
            URL_PREFIX + '/config-changes/%s/apply/' % change['id'], {},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        # 租户 B 创建变更必须用 B 的系统，不能指到 A 的系统
        resp = self.other_client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': '越权',
            'items': [{'param': param.id, 'new_value': 'x'}],
        }, content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        # 参数定义也按租户隔离：B 的变更不能用 A 的参数
        resp = self.other_client.post(URL_PREFIX + '/config-changes/', {
            'system': self.other_system.id, 'reason': '越权',
            'items': [{'param': param.id, 'new_value': 'x'}],
        }, content_type='application/json')
        self.assertIn('不存在', resp.json()['error'])

    def test_noperm_user_rejected(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        base = URL_PREFIX
        cases = [
            ('get', base + '/systems/%s/config/' % self.system.id, None),
            ('get', base + '/systems/%s/config/changes/' % self.system.id, None),
            ('get', base + '/config-changes/%s/' % change['id'], None),
            ('get', base + '/config-params/', None),
            ('post', base + '/config-changes/', {'system': self.system.id, 'reason': 'x',
                                                 'items': [{'param': param.id, 'new_value': '1'}]}),
            ('post', base + '/config-changes/%s/apply/' % change['id'], {}),
            ('post', base + '/config-changes/%s/verify/' % change['id'], {'verify_status': 'passed'}),
            ('post', base + '/config-changes/%s/rollback/' % change['id'], {}),
            ('post', base + '/config-changes/%s/cancel/' % change['id'], {}),
            ('post', base + '/config-params/', {'param_code': 'ab_cd', 'param_name': 'x',
                                                'data_type': 'text', 'scope_type': 'all'}),
        ]
        for method, url, payload in cases:
            kwargs = {'content_type': 'application/json'} if payload is not None else {}
            resp = getattr(self.noperm_client, method)(url, payload, **kwargs) \
                if payload is not None else self.noperm_client.get(url)
            self.assertTrue(resp.json().get('error'), (method, url, resp.content))


class IdempotencyTests(ConfigTestBase, TestCase):
    """场景 13：重复提交不生成重复配置变更。"""

    def test_client_token_returns_existing_change(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        token = 'tok-%s' % uuid.uuid4().hex
        payload = {
            'system': self.system.id, 'reason': '幂等测试',
            'items': [{'param': param.id, 'new_value': '41', 'remark': ''}],
            'client_token': token,
        }
        first = self.client.post(URL_PREFIX + '/config-changes/', payload,
                                 content_type='application/json').json()
        second = self.client.post(URL_PREFIX + '/config-changes/', payload,
                                  content_type='application/json').json()
        self.assertFalse(first.get('error'))
        self.assertFalse(second.get('error'))
        self.assertEqual(first['data']['id'], second['data']['id'])
        self.assertEqual(ConfigChangeRecord.objects.filter(
            tenant_id='tenant_a', client_token=token).count(), 1)

    def test_window_dedup_rejects_same_system_reason(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        item = [{'param': param.id, 'new_value': '41', 'remark': ''}]
        self.create_change(items=item, reason='同样的原因')
        resp = self.client.post(URL_PREFIX + '/config-changes/', {
            'system': self.system.id, 'reason': '同样的原因',
            'items': item, 'client_token': 'tok-%s' % uuid.uuid4().hex,
        }, content_type='application/json')
        self.assertIn('请勿重复操作', resp.json()['error'])
        self.assertEqual(ConfigChangeRecord.objects.filter(
            tenant_id='tenant_a', reason='同样的原因').count(), 1)


class SensitiveParamTests(ConfigTestBase, TestCase):
    """场景 14：敏感配置在参数定义层被拒绝保存。"""

    def test_sensitive_code_rejected(self):
        for code in ('db_password', 'api_key', 'access_token'):
            resp = self.client.post(CONFIG_URL + '/', {
                'param_code': code, 'param_name': '密码配置', 'data_type': 'text',
                'scope_type': 'all'},
                content_type='application/json')
            self.assertIn('敏感配置', resp.json()['error'], code)
            self.assertFalse(ConfigParamDefinition.objects.filter(param_code=code).exists())

    def test_sensitive_name_rejected(self):
        resp = self.client.post(CONFIG_URL + '/', {
            'param_code': 'outer_ref', 'param_name': '访问令牌引用', 'data_type': 'text',
            'scope_type': 'all'},
            content_type='application/json')
        self.assertIn('敏感配置', resp.json()['error'])
        # 外部密钥系统引用编号作为普通文本参数可以保存
        resp = self.client.post(CONFIG_URL + '/', {
            'param_code': 'vault_ref', 'param_name': '保管库引用编号', 'data_type': 'text',
            'scope_type': 'all'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertTrue(resp.json()['data']['id'])

    def test_param_code_immutable_and_unique(self):
        param = self.create_param(param_code='tx_power')
        resp = self.client.post(CONFIG_URL + '/', {
            'param_code': 'tx_power', 'param_name': '重复编码', 'data_type': 'text',
            'scope_type': 'all'},
            content_type='application/json')
        self.assertIn('已存在', resp.json()['error'])
        # 编辑不允许改编码：其他字段更新成功，编码保持
        resp = self.client.put(CONFIG_URL + '/%s/' % param.id, {
            'param_name': '发射功率（改）', 'data_type': 'number', 'scope_type': 'all',
            'is_enabled': False},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        param.refresh_from_db()
        self.assertEqual(param.param_code, 'tx_power')
        self.assertFalse(param.is_enabled)


class AttachmentTests(ConfigTestBase, TestCase):
    """场景 15：附件访问必须校验父对象与租户。"""

    def _upload(self, change_id, client=None):
        client = client or self.client
        return client.post(
            URL_PREFIX + '/config-changes/%s/attachments/' % change_id,
            {'file': SimpleUploadedFile('记录附件.txt', b'config-attach-content')})

    def test_upload_list_delete_on_draft(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        resp = self._upload(change['id'])
        self.assertFalse(resp.json().get('error'), resp.json())
        att_id = resp.json()['data']['id']
        listing = self.client.get(
            URL_PREFIX + '/config-changes/%s/attachments/' % change['id']).json()
        self.assertEqual(len(listing['data']), 1)
        # 已生效后不能再上传/删除（留档完整），但列表/下载仍可用
        self.apply_change(change['id'])
        resp = self._upload(change['id'])
        self.assertIn('草稿', resp.json()['error'])
        resp = self.client.delete(
            URL_PREFIX + '/config-changes/%s/attachments/%s/' % (change['id'], att_id))
        self.assertTrue(resp.json().get('error'))

    def test_cross_tenant_attachment_access_denied(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        resp = self._upload(change['id'])
        att_id = resp.json()['data']['id']
        # 租户 B：父对象校验先行，不能列表/下载/删除租户 A 的变更附件
        resp = self.other_client.get(
            URL_PREFIX + '/config-changes/%s/attachments/' % change['id'])
        self.assertTrue(resp.json().get('error'))
        resp = self.other_client.get(
            URL_PREFIX + '/config-changes/%s/attachments/%s/download/' % (change['id'], att_id))
        self.assertTrue(resp.json().get('error'))
        resp = self.other_client.delete(
            URL_PREFIX + '/config-changes/%s/attachments/%s/' % (change['id'], att_id))
        self.assertTrue(resp.json().get('error'))

    def test_attachment_of_other_object_not_accessible(self):
        """同模块但挂在其他父对象下的附件不能通过本变更访问（归属校验）。"""
        from apps.evidence.models import EvidenceAttachment
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        other_change = self.create_change(
            items=[{'param': param.id, 'new_value': '42', 'remark': ''}])
        att = EvidenceAttachment.objects.create(
            tenant_id='tenant_a', module='equipment_lifecycle',
            object_type='el_config_change', object_id=str(other_change['id']),
            file_name='x.txt', file_path='x/x.txt', file_size=1, file_ext='txt',
            uploaded_by_id=self.admin.id)
        resp = self.client.get(
            URL_PREFIX + '/config-changes/%s/attachments/%s/download/'
            % (change['id'], att.id))
        self.assertIn('附件不存在或无权限访问', resp.json()['error'])

    def test_attachment_requires_permission(self):
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '41', 'remark': ''}])
        no_att_perm_user = make_user(
            'cfg_noatt_%s' % uuid.uuid4().hex[:8],
            [P_VIEW, P_ADD, P_EDIT, P_APPLY], tenant_id='tenant_a')
        no_att_client = make_client(no_att_perm_user)
        resp = no_att_client.post(
            URL_PREFIX + '/config-changes/%s/attachments/' % change['id'],
            {'file': SimpleUploadedFile('a.txt', b'x')})
        self.assertTrue(resp.json().get('error'))
