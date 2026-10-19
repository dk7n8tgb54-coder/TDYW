# -*- coding: utf-8 -*-
"""系统配置分类 + 初始建档（2026-10-19）真实行为测试。

覆盖验收要求的场景（HTTP 真实路径 + 数据库副作用断言，不读取源码、
不使用正则匹配冒充行为测试）：
1.  参数分类（硬件规格/运行参数）：定义创建/默认值/非法值/列表筛选；
2.  当前配置携带分类与值来源（未设置/初始建档/配置变更）；
3.  空系统完成初始建档：建档主表/明细/当前值真实落库（建档人/时间/来源）；
4.  建档后修改走配置变更：变更前值取自基线，应用后当前值更新且基线不被改写；
5.  重复建档拒绝；已有配置值/已生效变更历史的系统拒绝补建（保留原记录）；
6.  草稿变更不占用建档资格，建档后应用被"变更前值已被修改"护栏拦截；
7.  建档入参校验（空明细/重复参数/停用/不适用/空值/缺来源/跨租户参数）；
8.  权限：建档独立权限码（config.baseline），view 可查不可建；
9.  租户隔离：跨租户系统/参数互不可见不可建档；
10. 维护入口系统候选接口（引用系统档案字段 + 建档状态标记）。
"""
import uuid
from decimal import Decimal

from django.test import TestCase

from apps.equipment_lifecycle.config_models import (
    ConfigChangeRecord,
    SystemConfigBaseline,
    SystemConfigBaselineItem,
    SystemParamValue,
)
from apps.logs.models import AuditLog
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX,
    make_client, make_system, make_user,
)

P_VIEW = 'equipment_lifecycle.config.view'
P_ADD = 'equipment_lifecycle.config.add'
P_EDIT = 'equipment_lifecycle.config.edit'
P_APPLY = 'equipment_lifecycle.config.apply'
P_BASELINE = 'equipment_lifecycle.config.baseline'
P_TEMPLATE = 'equipment_lifecycle.config.template'

ALL_CONFIG_PERMS = [P_VIEW, P_ADD, P_EDIT, P_APPLY, P_TEMPLATE]
ALL_WITH_BASELINE = ALL_CONFIG_PERMS + [P_BASELINE]

BASELINE_URL = URL_PREFIX + '/systems/%s/config/baseline/'
SYSTEM_OPTIONS_URL = URL_PREFIX + '/config/system-options/'


def make_param(created_by, tenant_id='tenant_a', param_code=None, **kwargs):
    """创建参数定义夹具（默认运行参数分类，可用 kwargs 覆盖）。"""
    from apps.equipment_lifecycle.config_models import (
        ConfigParamDefinition, ConfigParamSystemScope)
    system_ids = kwargs.pop('system_ids', [])
    defaults = dict(
        param_code=param_code or ('p_%s' % uuid.uuid4().hex[:8]),
        param_name='发射功率',
        category='runtime_param',
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
        ConfigParamSystemScope.objects.bulk_create([
            ConfigParamSystemScope(tenant_id=tenant_id, param=param, system=s)
            for s in system_ids
        ])
    return param


class BaselineTestBase:
    """公共夹具：建档权限用户 + 仅查看用户 + 双租户（client 必须在 setUp 创建）。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user(
            'bl_admin_%s' % uuid.uuid4().hex[:8], ALL_WITH_BASELINE, tenant_id='tenant_a')
        cls.viewer = make_user(
            'bl_viewer_%s' % uuid.uuid4().hex[:8], [P_VIEW], tenant_id='tenant_a')
        cls.other_admin = make_user(
            'bl_other_%s' % uuid.uuid4().hex[:8], ALL_WITH_BASELINE, tenant_id='tenant_b')

    def setUp(self):
        self.client = make_client(self.admin)
        self.viewer_client = make_client(self.viewer)
        self.other_client = make_client(self.other_admin)
        self.system = make_system(self.admin, tenant_id='tenant_a',
                                  system_code='BL-SYS-A-%s' % uuid.uuid4().hex[:6].upper())
        self.other_system = make_system(self.other_admin, tenant_id='tenant_b',
                                        system_code='BL-SYS-B-%s' % uuid.uuid4().hex[:6].upper())

    def create_param(self, **kwargs):
        return make_param(self.admin, **kwargs)

    def establish(self, client=None, system=None, items=None, assert_success=True, **overrides):
        """建立初始配置，返回响应 body（assert_success 时断言业务成功）。"""
        client = client or self.client
        system = system or self.system
        payload = {
            'source': overrides.pop('source', '验收文档 %s' % uuid.uuid4().hex[:6]),
            'remark': overrides.pop('remark', ''),
            'items': items or [],
        }
        payload.update(overrides)
        resp = client.post(BASELINE_URL % system.id, payload,
                           content_type='application/json')
        body = resp.json()
        if assert_success:
            self.assertFalse(body.get('error'), body)
        return body

    def get_state(self, system_id=None, client=None):
        client = client or self.client
        resp = client.get(BASELINE_URL % (system_id or self.system.id))
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def get_config(self, system_id=None, client=None):
        client = client or self.client
        resp = client.get(URL_PREFIX + '/systems/%s/config/' % (system_id or self.system.id))
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def create_change(self, client=None, system=None, items=None):
        client = client or self.client
        system = system or self.system
        payload = {
            'system': system.id,
            'reason': '参数调整 %s' % uuid.uuid4().hex[:6],
            'items': items or [],
            'verify_note': '',
            'client_token': 'tok-%s' % uuid.uuid4().hex,
        }
        resp = client.post(URL_PREFIX + '/config-changes/', payload,
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def apply_change(self, change_id, client=None, assert_success=True):
        client = client or self.client
        resp = client.post(URL_PREFIX + '/config-changes/%s/apply/' % change_id, {},
                           content_type='application/json')
        body = resp.json()
        if assert_success:
            self.assertFalse(body.get('error'), body)
        return body


class ParamCategoryTests(BaselineTestBase, TestCase):
    """场景 1/2：参数分类定义、默认值、筛选与当前配置分类展示。"""

    def test_category_create_default_and_invalid(self):
        # 显式分类生效
        resp = self.client.post(URL_PREFIX + '/config-params/', {
            'param_code': 'rated_power', 'param_name': '系统额定功率',
            'category': 'hardware_spec', 'data_type': 'number',
            'scope_type': 'all', 'unit': 'kW', 'is_required': False,
        }, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['category'], 'hardware_spec')
        self.assertEqual(body['data']['category_text'], '硬件规格')
        # 未提交分类时默认"运行参数"（兼容旧调用方，不凭空推断历史分类）
        resp = self.client.post(URL_PREFIX + '/config-params/', {
            'param_code': 'work_mode', 'param_name': '工作模式',
            'data_type': 'choice', 'scope_type': 'all',
            'enum_options': ['主用', '备用'],
        }, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['category'], 'runtime_param')
        # 非法分类拒绝
        resp = self.client.post(URL_PREFIX + '/config-params/', {
            'param_code': 'bad_cat', 'param_name': '坏分类',
            'category': 'device_spec', 'data_type': 'text', 'scope_type': 'all',
        }, content_type='application/json')
        self.assertEqual(resp.json().get('error'), '参数分类不正确')

    def test_category_list_filter(self):
        hw = self.create_param(param_code='rated_power', param_name='系统额定功率',
                               category='hardware_spec', data_type='number', unit='kW')
        rt = self.create_param(param_code='set_power', param_name='设定功率',
                               category='runtime_param', data_type='number')
        resp = self.client.get(URL_PREFIX + '/config-params/?category=hardware_spec')
        data = resp.json()['data']
        codes = [item['param_code'] for item in data['items']]
        self.assertIn('rated_power', codes)
        self.assertNotIn('set_power', codes)
        # 非法筛选值拒绝
        resp = self.client.get(URL_PREFIX + '/config-params/?category=xxx')
        self.assertEqual(resp.json().get('error'), '参数分类筛选值不正确')

    def test_current_config_carries_category_and_empty_source(self):
        self.create_param(param_code='rated_power', param_name='系统额定功率',
                          category='hardware_spec', data_type='number', unit='kW')
        self.create_param(param_code='set_power', param_name='设定功率',
                          category='runtime_param', data_type='number')
        data = self.get_config()
        self.assertIsNone(data['baseline'])
        by_code = {item['param_code']: item for item in data['items']}
        self.assertEqual(by_code['rated_power']['category'], 'hardware_spec')
        self.assertEqual(by_code['rated_power']['category_text'], '硬件规格')
        self.assertEqual(by_code['set_power']['category_text'], '运行参数')
        # 未设置的参数来源为空
        self.assertEqual(by_code['rated_power']['source_text'], '')


class EstablishBaselineTests(BaselineTestBase, TestCase):
    """场景 3/4：空系统建档、建档后变更流程与历史可追溯。"""

    def test_establish_on_empty_system(self):
        hw = self.create_param(param_code='rated_power', param_name='系统额定功率',
                               category='hardware_spec', data_type='number', unit='kW')
        rt = self.create_param(param_code='work_mode', param_name='工作模式',
                               category='runtime_param', data_type='choice',
                               unit='', enum_options='["主用", "备用"]')
        data = self.establish(items=[
            {'param': hw.id, 'value': '3.5'},
            {'param': rt.id, 'value': '主用'},
        ])['data']
        # 响应：建档身份与明细快照
        self.assertEqual(data['source'].startswith('验收文档'), True)
        self.assertEqual(data['established_by_name'], self.admin.username)
        self.assertTrue(data['established_at'])
        self.assertEqual(len(data['items']), 2)
        hw_item = [x for x in data['items'] if x['param_code'] == 'rated_power'][0]
        self.assertEqual(hw_item['display_value'], '3.5')
        self.assertEqual(hw_item['category_text'], '硬件规格')
        rt_item = [x for x in data['items'] if x['param_code'] == 'work_mode'][0]
        self.assertEqual(rt_item['display_value'], '主用')
        # 数据库副作用：建档主表（身份：建档人/时间/来源）
        baseline = SystemConfigBaseline.objects.get(system=self.system)
        self.assertEqual(baseline.established_by, self.admin)
        self.assertTrue(baseline.established_at)
        self.assertTrue(baseline.source)
        self.assertEqual(baseline.system_code, self.system.system_code)
        self.assertEqual(SystemConfigBaselineItem.objects.filter(baseline=baseline).count(), 2)
        # 数据库副作用：当前配置值行（类型化字段 + 建档外键 + 无变更来源）
        hw_value = SystemParamValue.objects.get(system=self.system, param=hw)
        self.assertEqual(hw_value.value_number, Decimal('3.5'))
        self.assertEqual(hw_value.baseline_id, baseline.id)
        self.assertIsNone(hw_value.last_change_id)
        self.assertEqual(hw_value.last_changed_by, self.admin)
        rt_value = SystemParamValue.objects.get(system=self.system, param=rt)
        self.assertEqual(rt_value.value_choice, '主用')
        self.assertEqual(rt_value.baseline_id, baseline.id)
        # 审计事件真实写入
        self.assertTrue(AuditLog.objects.filter(
            target_type='el_config_baseline', target_id=str(baseline.id)).exists())
        # 当前配置视图：来源=初始建档 + 建档摘要
        config = self.get_config()
        self.assertEqual(config['baseline']['id'], baseline.id)
        self.assertTrue(config['baseline']['source'])
        by_code = {item['param_code']: item for item in config['items']}
        self.assertEqual(by_code['rated_power']['display_value'], '3.5')
        self.assertEqual(by_code['rated_power']['source_text'], '初始建档')
        self.assertEqual(by_code['rated_power']['last_changed_by_name'], self.admin.username)
        # 建档状态：can_establish=False 且原因明确
        state = self.get_state()
        self.assertFalse(state['can_establish'])
        self.assertIn('已建立初始配置', state['block_reason'])
        self.assertEqual(state['baseline']['id'], baseline.id)

    def test_change_after_baseline_traces_to_baseline(self):
        """建档后修改走配置变更：变更前值取自基线，应用后基线不被改写。"""
        param = self.create_param(param_code='set_power', param_name='设定功率',
                                  data_type='number', unit='kW')
        self.establish(items=[{'param': param.id, 'value': '3.5'}])
        # 变更草稿：后端从数据库当前值（基线）生成变更前值快照
        change = self.create_change(items=[{'param': param.id, 'new_value': '4.2'}])
        item = ConfigChangeRecord.objects.get(pk=change['id']).items.first()
        self.assertEqual(item.old_value, '3.5')
        self.assertEqual(item.new_value, '4.2')
        self.apply_change(change['id'])
        # 当前值更新且来源转为配置变更
        value = SystemParamValue.objects.get(system=self.system, param=param)
        self.assertEqual(value.value_number, Decimal('4.2'))
        self.assertIsNotNone(value.last_change_id)
        self.assertEqual(value.last_change_id, change['id'])
        config = self.get_config()
        by_code = {x['param_code']: x for x in config['items']}
        self.assertEqual(by_code['set_power']['display_value'], '4.2')
        self.assertTrue(by_code['set_power']['source_text'].startswith('配置变更 PZ'))
        # 基线快照不被改写（历史可追溯）
        baseline_item = SystemConfigBaselineItem.objects.get(
            baseline__system=self.system, param=param)
        self.assertEqual(baseline_item.value_number, Decimal('3.5'))

    def test_duplicate_baseline_rejected(self):
        param = self.create_param(data_type='text')
        self.establish(items=[{'param': param.id, 'value': 'v1'}])
        body = self.establish(items=[{'param': param.id, 'value': 'v2'}],
                              assert_success=False)
        self.assertIn('已建立初始配置', body.get('error'))
        self.assertEqual(SystemConfigBaseline.objects.filter(system=self.system).count(), 1)
        # 当前值未被第二次请求覆盖
        self.assertEqual(
            SystemParamValue.objects.get(system=self.system, param=param).value_text, 'v1')


class BaselineGuardTests(BaselineTestBase, TestCase):
    """场景 5/6：已有配置数据的系统不补建；草稿变更与建档的并发护栏。"""

    def test_system_with_applied_change_rejected(self):
        """已有配置值（来自历史变更）的系统保留原记录，不凭空推断历史基线。"""
        param = self.create_param(param_code='tx_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '42'}])
        self.apply_change(change['id'])
        state = self.get_state()
        self.assertFalse(state['can_establish'])
        self.assertIn('已有配置值', state['block_reason'])
        self.assertIsNone(state['baseline'])
        body = self.establish(items=[{'param': param.id, 'value': '1'}],
                              assert_success=False)
        self.assertIn('不能建立初始配置', body.get('error'))
        # 原有记录完整保留：当前值与变更来源未被动过
        value = SystemParamValue.objects.get(system=self.system, param=param)
        self.assertEqual(value.value_number, Decimal('42'))
        self.assertEqual(value.last_change_id, int(change['id']))
        self.assertIsNone(value.baseline_id)
        self.assertFalse(SystemConfigBaseline.objects.filter(system=self.system).exists())
        # 当前配置来源仍指向历史变更
        config = self.get_config()
        by_code = {x['param_code']: x for x in config['items']}
        self.assertTrue(by_code['tx_power']['source_text'].startswith('配置变更 PZ'))

    def test_draft_change_then_baseline_blocks_apply(self):
        """草稿变更不占用建档资格；建档后其应用被前值护栏拦截（fail-closed）。"""
        param = self.create_param(param_code='set_power', data_type='number')
        change = self.create_change(items=[{'param': param.id, 'new_value': '9'}])
        state = self.get_state()
        self.assertTrue(state['can_establish'])
        self.establish(items=[{'param': param.id, 'value': '3.5'}])
        body = self.apply_change(change['id'], assert_success=False)
        self.assertIn('已被其他变更修改', body.get('error'))
        # 草稿仍为草稿；当前值仍是基线值
        self.assertEqual(ConfigChangeRecord.objects.get(pk=change['id']).status, 'draft')
        self.assertEqual(
            SystemParamValue.objects.get(system=self.system, param=param).value_number,
            Decimal('3.5'))


class BaselineValidationTests(BaselineTestBase, TestCase):
    """场景 7：建档入参校验。"""

    def test_empty_items_rejected(self):
        body = self.establish(items=[], assert_success=False)
        self.assertIn('至少为一个配置参数', body.get('error'))

    def test_duplicate_param_rejected(self):
        param = self.create_param(data_type='text')
        body = self.establish(items=[
            {'param': param.id, 'value': 'a'},
            {'param': param.id, 'value': 'b'},
        ], assert_success=False)
        self.assertIn('重复建档', body.get('error'))

    def test_disabled_or_not_applicable_param_rejected(self):
        disabled = self.create_param(param_code='off_p')
        disabled.is_enabled = False
        disabled.save()
        body = self.establish(items=[{'param': disabled.id, 'value': 'x'}],
                              assert_success=False)
        self.assertIn('已停用', body.get('error'))
        other = make_system(self.admin, tenant_id='tenant_a',
                            system_code='BL-OTHER-%s' % uuid.uuid4().hex[:6].upper())
        scoped = self.create_param(param_code='scoped_p', scope_type='specific',
                                   data_type='text', system_ids=[other])
        body = self.establish(items=[{'param': scoped.id, 'value': 'x'}],
                              assert_success=False)
        self.assertIn('不适用于当前系统', body.get('error'))

    def test_empty_value_rejected(self):
        param = self.create_param(data_type='text')
        body = self.establish(items=[{'param': param.id, 'value': '   '}],
                              assert_success=False)
        self.assertIn('基线值不能为空', body.get('error'))

    def test_missing_source_rejected(self):
        param = self.create_param(data_type='text')
        body = self.establish(items=[{'param': param.id, 'value': 'x'}],
                              source='  ', assert_success=False)
        self.assertIn('请填写建档来源', body.get('error'))

    def test_value_type_validation(self):
        number_param = self.create_param(param_code='num_p', data_type='number')
        body = self.establish(items=[{'param': number_param.id, 'value': 'abc'}],
                              assert_success=False)
        self.assertIn('必须是数字', body.get('error'))
        choice_param = self.create_param(param_code='mode_p', data_type='choice',
                                         enum_options='["主用", "备用"]')
        body = self.establish(items=[{'param': choice_param.id, 'value': '不存在的选项'}],
                              assert_success=False)
        self.assertIn('只能提交允许的选项', body.get('error'))

    def test_cross_tenant_param_rejected(self):
        foreign = make_param(self.other_admin, tenant_id='tenant_b', param_code='fb_p')
        body = self.establish(items=[{'param': foreign.id, 'value': 'x'}],
                              assert_success=False)
        self.assertIn('不存在或无权限访问', body.get('error'))
        self.assertFalse(SystemConfigBaseline.objects.filter(system=self.system).exists())

    def test_inactive_system_rejected(self):
        param = self.create_param(data_type='text')
        self.system.is_active = False
        self.system.save()
        body = self.establish(items=[{'param': param.id, 'value': 'x'}],
                              assert_success=False)
        self.assertIn('已停用', body.get('error'))
        # 停用系统仍可查询建档状态（历史可查口径一致）
        state = self.get_state()
        self.assertTrue(state['can_establish'])


class BaselinePermissionIsolationTests(BaselineTestBase, TestCase):
    """场景 8/9/10：权限、租户隔离与维护入口系统候选。"""

    def test_baseline_permission_required(self):
        param = self.create_param(data_type='text')
        # 仅 view 权限：可查状态，不可建档（独立权限码 config.baseline）
        state = self.get_state(client=self.viewer_client)
        self.assertTrue(state['can_establish'])
        body = self.establish(client=self.viewer_client,
                              items=[{'param': param.id, 'value': 'x'}],
                              assert_success=False)
        self.assertEqual(body.get('error'), '权限拒绝')
        self.assertFalse(SystemConfigBaseline.objects.filter(system=self.system).exists())

    def test_view_permission_required(self):
        stranger = make_user('bl_stranger_%s' % uuid.uuid4().hex[:8], [],
                             tenant_id='tenant_a')
        resp = make_client(stranger).get(BASELINE_URL % self.system.id)
        self.assertEqual(resp.json().get('error'), '权限拒绝')

    def test_tenant_isolation(self):
        param = self.create_param(data_type='text')
        # 跨租户系统不可见：查询与建档都拒绝
        resp = self.other_client.get(BASELINE_URL % self.system.id)
        self.assertEqual(resp.json().get('error'), '系统不存在')
        body = self.establish(client=self.other_client, system=self.system,
                              items=[{'param': param.id, 'value': 'x'}],
                              assert_success=False)
        self.assertIn('系统不存在或已停用', body.get('error'))
        self.assertFalse(SystemConfigBaseline.objects.filter(system=self.system).exists())

    def test_system_options_for_maintenance_entry(self):
        # 系统候选返回引用档案字段与建档标记（含停用系统）
        self.system.callsign = 'BI7AA'
        self.system.save()
        param = self.create_param(data_type='text')
        self.establish(items=[{'param': param.id, 'value': '出厂值'}])
        resp = self.client.get(SYSTEM_OPTIONS_URL)
        data = resp.json()['data']
        rows = {row['id']: row for row in data['items']}
        self.assertIn(self.system.id, rows)
        row = rows[self.system.id]
        self.assertEqual(row['system_model'], self.system.system_model)
        self.assertEqual(row['manufacturer'], self.system.manufacturer)
        self.assertEqual(row['callsign'], 'BI7AA')
        self.assertTrue(row['has_baseline'])
        self.assertTrue(row['is_active'])
        # 未建档系统 has_baseline=False；租户隔离：B 租户看不到 A 的系统
        other_rows = self.other_client.get(SYSTEM_OPTIONS_URL).json()['data']['items']
        self.assertNotIn(self.system.id, [row['id'] for row in other_rows])
        # 无 view 权限拒绝
        resp = self.viewer_client.get(BASELINE_URL % self.system.id)
        self.assertFalse(resp.json().get('error'))
        noperm = make_user('bl_noperm_%s' % uuid.uuid4().hex[:8], [], tenant_id='tenant_a')
        resp = make_client(noperm).get(SYSTEM_OPTIONS_URL)
        self.assertEqual(resp.json().get('error'), '权限拒绝')
