# -*- coding: utf-8 -*-
"""数字表单协议 v2 与发布检查行为测试（2026-10-23 P2）。

真实 HTTP 路径（django.test.Client + 隔离测试库），覆盖：
- 协议 v2：新键（rows/min/max/precision/require_desc_when_abnormal）保存与
  规范化回读、v1 输入显式保存升级为 v2、未来版本整体拒绝、各层未知键
  fail-closed 拒绝（错误含键名与对象位置）、不适用键与取值越界拒绝；
- 发布门禁：存量 v1 草稿直接发布明确拒绝（不静默升级）、publish-check
  无状态（errors/warnings + anchor 定位、不落库不产生预检标记）、
  检查通过后草稿被改坏发布仍在行锁内重新校验并阻断；
- 填写值规则：数字范围/小数位（v2 快照生效、v1 快照无键不限制）、
  异常说明必填终验（普通/明细/矩阵行三载体、v1 快照不启用）、
  异常说明键收紧为仅 normal_abnormal（明细行与矩阵单元格）；
- 历史兼容：v1 版本快照按创建时语义读取/填写/完成，不回写快照。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle import form_ledger_services, form_template_manage
from apps.equipment_lifecycle.form_models import (
    OperationLedgerFormRecord,
    OperationLedgerFormTemplate,
    OperationLedgerFormTemplateVersion,
)
from apps.equipment_lifecycle.tests.base import (
    make_client, make_system, make_user, URL_PREFIX,
)

P_TPL = [
    'equipment_lifecycle.ledger_template.view',
    'equipment_lifecycle.ledger_template.add',
    'equipment_lifecycle.ledger_template.edit',
]
P_LEDGER = [
    'equipment_lifecycle.ledger.view',
    'equipment_lifecycle.ledger.add',
    'equipment_lifecycle.ledger.edit',
    'equipment_lifecycle.ledger.submit',
    'equipment_lifecycle.ledger.export',
]
ALL_PERMS = P_TPL + P_LEDGER

TPL_URL = URL_PREFIX + '/form-templates'
LEDGER_URL = URL_PREFIX + '/form-ledgers'


def v2_form(groups=None):
    """合法 v2 表单夹具：覆盖三种分组与新属性载体。"""
    if groups is not None:
        return {'protocol_version': 2, 'groups': groups}
    return {
        'protocol_version': 2,
        'groups': [
            {'id': 'g_check001', 'name': '状态检查', 'description': '', 'kind': 'fields',
             'fields': [
                 {'id': 'f_na000001', 'name': '机壳外观', 'type': 'normal_abnormal',
                  'required': True, 'description': '有无锈蚀', 'unit': '', 'options': [],
                  'require_desc_when_abnormal': True},
                 {'id': 'f_num00001', 'name': '输出电压', 'type': 'number',
                  'required': False, 'description': '', 'unit': 'V', 'options': [],
                  'min': 0, 'max': 400, 'precision': 1},
                 {'id': 'f_text0001', 'name': '备注', 'type': 'textarea',
                  'required': False, 'description': '', 'unit': '', 'options': [],
                  'rows': 3},
             ]},
            {'id': 'g_repeat01', 'name': '测量', 'description': '', 'kind': 'repeat',
             'item_name': '测量项目', 'fields': [
                 {'id': 'f_rna00001', 'name': '判断', 'type': 'normal_abnormal',
                  'required': True, 'description': '', 'unit': '', 'options': [],
                  'require_desc_when_abnormal': True},
                 {'id': 'f_rnum0001', 'name': '读数', 'type': 'number',
                  'required': True, 'description': '', 'unit': '', 'options': []},
             ]},
            {'id': 'g_matrix01', 'name': '多机对比', 'description': '', 'kind': 'matrix',
             'columns': [{'id': 'c_ma00001', 'name': 'A 机'},
                         {'id': 'c_mb00001', 'name': 'B 机'}],
             'fields': [
                 {'id': 'r_na000001', 'name': '通讯状态', 'type': 'normal_abnormal',
                  'required': False, 'description': '', 'unit': '', 'options': [],
                  'require_desc_when_abnormal': True},
                 {'id': 'r_num0001', 'name': '电压', 'type': 'number',
                  'required': False, 'description': '', 'unit': 'V', 'options': [],
                  'min': 0, 'max': 300},
             ]},
        ],
    }


class ProtocolV2TestBase(TestCase):
    """公共夹具：双租户用户 + 系统 + 模板创建/保存/发布直达方法。"""

    @classmethod
    def setUpTestData(cls):
        seed = 'p2%s' % cls._seed()
        cls.owner = make_user('form_p2_owner_%s' % seed, perms=ALL_PERMS,
                              tenant_id='default')
        cls.other = make_user('form_p2_other_%s' % seed, perms=ALL_PERMS,
                              tenant_id='another')
        cls.owner_client = make_client(cls.owner)
        cls.other_client = make_client(cls.other)
        cls.system = make_system(cls.owner)

    @classmethod
    def _seed(cls):
        if not hasattr(cls, '_seed_value'):
            import uuid
            cls._seed_value = uuid.uuid4().hex[:8]
        return cls._seed_value

    def create_template(self, client=None, name='周维护数字表单'):
        client = client or self.owner_client
        response = client.post(TPL_URL + '/', json.dumps({
            'name': name, 'ledger_type': 'week_month'}),
            content_type='application/json')
        data = response.json()
        self.assertEqual(data.get('error', ''), '', data.get('error'))
        return data['data']

    def save_draft(self, template_id, form, client=None):
        client = client or self.owner_client
        return client.put('%s/%s/' % (TPL_URL, template_id),
                          json.dumps({'form': form}),
                          content_type='application/json')

    def publish(self, template_id, client=None):
        client = client or self.owner_client
        return client.post('%s/%s/publish/' % (TPL_URL, template_id),
                           content_type='application/json').json()

    def publish_v2(self, form=None):
        template = self.create_template()
        response = self.save_draft(template['id'], form or v2_form())
        self.assertEqual(response.json().get('error', ''), '')
        version = self.publish(template['id'])
        self.assertEqual(version.get('error', ''), '', version.get('error'))
        return template, version['data']

    def create_ledger(self, version_id):
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version_id}),
            content_type='application/json')
        data = response.json()
        self.assertEqual(data.get('error', ''), '', data.get('error'))
        return data['data']

    def save_values(self, ledger_id, values):
        return self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': values}),
            content_type='application/json').json()

    def complete(self, ledger_id):
        return self.owner_client.post('%s/%s/complete/' % (LEDGER_URL, ledger_id)).json()


class FormProtocolV2SchemaTests(ProtocolV2TestBase):
    """协议 v2 结构校验：新键、版本升级、未知键 fail-closed。"""

    def test_v2_new_keys_saved_and_normalized(self):
        """新键保存成功并规范化回读：适用键保留、缺省键补默认值。"""
        template = self.create_template()
        form = v2_form(groups=[{
            'id': 'g1', 'name': '组', 'kind': 'fields', 'fields': [
                {'id': 'f1', 'name': '备注', 'type': 'textarea', 'rows': 4},
                {'id': 'f2', 'name': '电压', 'type': 'number',
                 'min': 0, 'max': 400, 'precision': 2},
                {'id': 'f3', 'name': '外观', 'type': 'normal_abnormal',
                 'require_desc_when_abnormal': True},
            ]}])
        response = self.save_draft(template['id'], form)
        self.assertEqual(response.json().get('error', '', ), '')
        draft = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']['draft']['form']
        self.assertEqual(draft['protocol_version'], 2)
        by_id = {field['id']: field for field in draft['groups'][0]['fields']}
        self.assertEqual(by_id['f1']['rows'], 4)
        self.assertEqual(by_id['f2']['min'], 0)
        self.assertEqual(by_id['f2']['max'], 400)
        self.assertEqual(by_id['f2']['precision'], 2)
        self.assertIs(by_id['f3']['require_desc_when_abnormal'], True)
        # 适用键缺省时补默认值：textarea 无 rows → 2；number 无范围 → None
        form2 = v2_form(groups=[{
            'id': 'g1', 'name': '组', 'kind': 'fields', 'fields': [
                {'id': 'f1', 'name': '备注', 'type': 'textarea'},
                {'id': 'f2', 'name': '电压', 'type': 'number'},
                {'id': 'f3', 'name': '外观', 'type': 'normal_abnormal'},
            ]}])
        response = self.save_draft(template['id'], form2)
        self.assertEqual(response.json().get('error', ''), '')
        draft = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']['draft']['form']
        by_id = {field['id']: field for field in draft['groups'][0]['fields']}
        self.assertEqual(by_id['f1']['rows'], 2)
        self.assertIsNone(by_id['f2']['min'])
        self.assertIsNone(by_id['f2']['max'])
        self.assertIsNone(by_id['f2']['precision'])
        self.assertIs(by_id['f3']['require_desc_when_abnormal'], False)

    def test_v1_input_explicit_save_upgrades_to_v2(self):
        """v1 内容经显式保存升级为 v2：保存响应与回读均为 v2。"""
        template = self.create_template()
        form = v2_form(groups=[{
            'id': 'g1', 'name': '组', 'kind': 'fields', 'fields': [
                {'id': 'f1', 'name': '备注', 'type': 'text'}]}])
        form['protocol_version'] = 1
        response = self.save_draft(template['id'], form)
        self.assertEqual(response.json().get('error', ''), '')
        draft = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']['draft']['form']
        self.assertEqual(draft['protocol_version'], 2)

    def test_future_protocol_version_rejected(self):
        """未来协议版本整体拒绝（不静默降级丢属性）。"""
        template = self.create_template()
        form = v2_form(groups=[{'id': 'g1', 'name': '组', 'kind': 'fields',
                                'fields': [{'id': 'f1', 'name': '备注', 'type': 'text'}]}])
        form['protocol_version'] = 3
        response = self.save_draft(template['id'], form)
        self.assertIn('协议版本', response.json()['error'])

    def test_unknown_keys_rejected_per_layer(self):
        """顶层/分组/字段/矩阵列未知键均显式拒绝，错误含键名。"""
        template = self.create_template()
        cases = [
            # 顶层未知键
            ({'protocol_version': 2, 'groups': [
                {'id': 'g1', 'name': '组', 'kind': 'fields',
                 'fields': [{'id': 'f1', 'name': 'A', 'type': 'text'}]}],
              'theme': 'dark'}, '表单定义', 'theme'),
            # 分组未知键
            (v2_form(groups=[{'id': 'g1', 'name': '组', 'kind': 'fields',
                              'collapsed': True,
                              'fields': [{'id': 'f1', 'name': 'A', 'type': 'text'}]}]),
             '分组「组」', 'collapsed'),
            # 字段未知键（含拼写错误防护）
            (v2_form(groups=[{'id': 'g1', 'name': '组', 'kind': 'fields',
                              'fields': [{'id': 'f1', 'name': 'A', 'type': 'text',
                                          'reqired': True}]}]),
             '字段「A」', 'reqired'),
            # 矩阵列未知键
            (v2_form(groups=[{'id': 'g1', 'name': 'M', 'kind': 'matrix',
                              'columns': [{'id': 'c1', 'name': 'A 机', 'width': 80}],
                              'fields': [{'id': 'r1', 'name': '行', 'type': 'text'}]}]),
             '矩阵列「A 机」', 'width'),
        ]
        for form, scope, key in cases:
            response = self.save_draft(template['id'], form)
            error = response.json()['error']
            self.assertIn(scope, error, error)
            self.assertIn(key, error, '错误信息应包含未知键名 %s：%s' % (key, error))
            self.assertIn('未知属性', error)

    def test_inapplicable_type_attrs_rejected(self):
        """不适用键出现即拒绝（切换类型应清理属性，前后端约束一致）。"""
        template = self.create_template()
        cases = [
            ({'id': 'f1', 'name': '文本', 'type': 'text', 'rows': 3}, 'rows'),
            ({'id': 'f1', 'name': '单选', 'type': 'choice', 'options': ['a'], 'min': 1}, 'min'),
            ({'id': 'f1', 'name': '文本', 'type': 'text', 'precision': 2}, 'precision'),
            ({'id': 'f1', 'name': '文本', 'type': 'text',
              'require_desc_when_abnormal': True}, 'require_desc_when_abnormal'),
        ]
        for field, key in cases:
            form = v2_form(groups=[{'id': 'g1', 'name': '组', 'kind': 'fields',
                                    'fields': [field]}])
            response = self.save_draft(template['id'], form)
            self.assertIn(key, response.json()['error'],
                          '应拒绝不适用键 %s' % key)

    def test_attr_bounds_rejected(self):
        """新属性取值越界/类型错误拒绝；min>max 拒绝。"""
        template = self.create_template()
        cases = [
            {'id': 'f1', 'name': '备注', 'type': 'textarea', 'rows': 1},
            {'id': 'f1', 'name': '备注', 'type': 'textarea', 'rows': 9},
            {'id': 'f1', 'name': '备注', 'type': 'textarea', 'rows': '多'},
            {'id': 'f1', 'name': '电压', 'type': 'number', 'precision': 4},
            {'id': 'f1', 'name': '电压', 'type': 'number', 'min': 100, 'max': 50},
            {'id': 'f1', 'name': '电压', 'type': 'number', 'min': '低'},
        ]
        for field in cases:
            form = v2_form(groups=[{'id': 'g1', 'name': '组', 'kind': 'fields',
                                    'fields': [field]}])
            response = self.save_draft(template['id'], form)
            self.assertNotEqual(response.json().get('error', ''),
                                '应拒绝：%s' % field)

    def test_publish_rejects_stored_v1_draft(self):
        """存量 v1 草稿（部署前由旧代码保存）直接发布明确拒绝。"""
        template = self.create_template()
        legacy = {'protocol_version': 1, 'groups': [{
            'id': 'g1', 'name': '组', 'kind': 'fields',
            'fields': [{'id': 'f1', 'name': '备注', 'type': 'text'}]}]}
        stored = OperationLedgerFormTemplate.objects.get(pk=template['id'])
        stored.draft_form = json.dumps(legacy, ensure_ascii=False)
        stored.save(update_fields=['draft_form'])
        response = self.publish(template['id'])
        self.assertIn('重新编辑并保存', response['error'])
        self.assertFalse(OperationLedgerFormTemplateVersion.objects.filter(
            template_id=template['id']).exists())
        # 显式保存一次（v1 输入）后即可发布
        self.save_draft(template['id'], legacy)
        self.assertEqual(self.publish(template['id']).get('error', ''), '')


class PublishCheckTests(ProtocolV2TestBase):
    """publish-check：无状态、结构化、可定位、权限与租户隔离。"""

    def publish_check(self, template_id, form=None, client=None):
        client = client or self.owner_client
        body = {} if form is None else {'form': form}
        response = client.post('%s/%s/publish-check/' % (TPL_URL, template_id),
                               json.dumps(body), content_type='application/json')
        return response.json()['data']

    def test_valid_form_returns_warnings_with_anchor(self):
        """结构合法：非阻断提醒（默认条目名/宽矩阵/异常项无说明）可定位。"""
        template = self.create_template()
        columns = [{'id': 'c%d0000001' % i, 'name': '设备%d' % i} for i in range(6)]
        form = v2_form(groups=[
            {'id': 'g_r1', 'name': '测量', 'kind': 'repeat',
             'fields': [{'id': 'f_r1', 'name': '项目', 'type': 'text'}]},
            {'id': 'g_m1', 'name': '宽矩阵', 'kind': 'matrix', 'columns': columns,
             'fields': [{'id': 'r_m1', 'name': '电压', 'type': 'normal_abnormal'}]},
        ])
        result = self.publish_check(template['id'], form)
        self.assertEqual(result['errors'], [])
        codes = {item['code'] for item in result['warnings']}
        self.assertIn('default_item_name', codes)
        self.assertIn('matrix_landscape', codes)
        self.assertIn('abnormal_no_desc', codes)
        anchors = {item['code']: item['anchor'] for item in result['warnings']}
        self.assertEqual(anchors['default_item_name'],
                         {'type': 'group', 'groupId': 'g_r1'})
        self.assertEqual(anchors['matrix_landscape'],
                         {'type': 'group', 'groupId': 'g_m1'})
        self.assertEqual(anchors['abnormal_no_desc'],
                         {'type': 'matrixRow', 'groupId': 'g_m1', 'fieldId': 'r_m1'})

    def test_invalid_unsaved_form_returns_locatable_error(self):
        """非法未保存草稿也能得到结构化错误（含锚点），不必先保存成功。"""
        template = self.create_template()
        form = v2_form(groups=[{'id': 'g1', 'name': '组', 'kind': 'fields',
                                'fields': [{'id': 'f1', 'name': '单选',
                                            'type': 'choice', 'options': []}]}])
        result = self.publish_check(template['id'], form)
        self.assertEqual(len(result['errors']), 1)
        error = result['errors'][0]
        self.assertEqual(error['code'], 'schema_invalid')
        self.assertIn('至少配置一个选项', error['message'])
        self.assertEqual(error['anchor'],
                         {'type': 'field', 'groupId': 'g1', 'fieldId': 'f1'})

    def test_body_fallback_to_stored_draft_and_no_draft(self):
        """无 body 时检查已保存草稿；无草稿返回 no_draft 错误。"""
        empty = self.create_template(name='无草稿模板')
        result = self.publish_check(empty['id'])
        self.assertEqual(result['errors'][0]['code'], 'no_draft')
        # 保存草稿后按存储草稿检查通过
        stored = self.create_template(name='有草稿模板')
        self.save_draft(stored['id'], v2_form())
        result = self.publish_check(stored['id'])
        self.assertEqual(result['errors'], [])

    def test_v1_stored_draft_flagged_in_check(self):
        """存量 v1 草稿的检查结果与发布语义一致（提示重新保存升级）。"""
        template = self.create_template()
        stored = OperationLedgerFormTemplate.objects.get(pk=template['id'])
        stored.draft_form = json.dumps(
            {'protocol_version': 1, 'groups': [{
                'id': 'g1', 'name': '组', 'kind': 'fields',
                'fields': [{'id': 'f1', 'name': '备注', 'type': 'text'}]}]},
            ensure_ascii=False)
        stored.save(update_fields=['draft_form'])
        result = self.publish_check(template['id'])
        self.assertEqual(result['errors'][0]['code'], 'protocol_v1')

    def test_permission_and_tenant_isolation(self):
        """edit 权限独立校验（HTTP 200 + 权限拒绝）；跨租户按不存在处理。"""
        template = self.create_template()
        viewer = make_user('p2_viewer_%s' % self._seed(),
                           perms=['equipment_lifecycle.ledger_template.view'])
        response = make_client(viewer).post(
            '%s/%s/publish-check/' % (TPL_URL, template['id']),
            json.dumps({}), content_type='application/json')
        self.assertEqual(response.json()['error'], '权限拒绝')
        response = self.other_client.post(
            '%s/%s/publish-check/' % (TPL_URL, template['id']),
            json.dumps({}), content_type='application/json')
        self.assertEqual(response.json()['error'], '模板不存在')

    def test_stateless_no_side_effects(self):
        """无状态：不写草稿、不创建版本、不产生预检通过标记。"""
        template = self.create_template()
        self.save_draft(template['id'], v2_form())
        stored = OperationLedgerFormTemplate.objects.get(pk=template['id'])
        draft_before = stored.draft_form
        self.publish_check(template['id'], v2_form(groups=[{
            'id': 'g_x1', 'name': '其他内容', 'kind': 'fields',
            'fields': [{'id': 'f_x1', 'name': 'X', 'type': 'text'}]}]))
        stored.refresh_from_db()
        self.assertEqual(stored.draft_form, draft_before, '不得写草稿')
        self.assertFalse(OperationLedgerFormTemplateVersion.objects.filter(
            template_id=template['id']).exists(), '不得创建版本')

    def test_publish_revalidates_after_check_pass(self):
        """检查通过后草稿被改坏：发布仍在行锁内重新校验并阻断（check 非
        放行凭证）。"""
        template = self.create_template()
        self.save_draft(template['id'], v2_form())
        result = self.publish_check(template['id'])
        self.assertEqual(result['errors'], [])
        # 模拟 check 之后草稿被并发改坏（绕过保存接口的合法校验）
        stored = OperationLedgerFormTemplate.objects.get(pk=template['id'])
        stored.draft_form = json.dumps({
            'protocol_version': 2,
            'groups': [{'id': 'g1', 'name': '坏', 'kind': 'fields',
                        'fields': [{'id': 'f1', 'name': '单选',
                                    'type': 'choice', 'options': []}]}]},
            ensure_ascii=False)
        stored.save(update_fields=['draft_form'])
        response = self.publish(template['id'])
        self.assertIn('至少配置一个选项', response['error'])
        self.assertFalse(OperationLedgerFormTemplateVersion.objects.filter(
            template_id=template['id']).exists())


class FormValuesV2RuleTests(ProtocolV2TestBase):
    """填写值规则：数字范围/精度、异常说明必填终验、desc 键收紧。"""

    def _publish_and_create(self, form=None):
        template, version = self.publish_v2(form)
        return template, version, self.create_ledger(version['id'])

    def test_number_range_and_precision_enforced(self):
        _template, _version, ledger = self._publish_and_create()
        cases = [
            ({'f_num00001': -1}, '不能小于'),
            ({'f_num00001': 401}, '不能大于'),
            ({'f_num00001': 1.23}, '小数位'),
            ({'g_matrix01': {'r_num0001': {'c_ma00001': 350}}}, '不能大于'),
        ]
        for values, expected in cases:
            error = self.save_values(ledger['id'], values)['error']
            self.assertIn(expected, error, error)
        # 合法值（含整数值与一位小数、尾随零不计精度）
        error = self.save_values(ledger['id'], {
            'f_num00001': 220.5,
            'g_matrix01': {'r_num0001': {'c_ma00001': '300.0'}}})['error']
        self.assertEqual(error, '')
        detail = self.owner_client.get(
            '%s/%s/' % (LEDGER_URL, ledger['id'])).json()['data']
        self.assertEqual(detail['form']['values']['f_num00001'], 220.5)

    def test_abnormal_desc_required_terminal_validation(self):
        """异常说明必填终验覆盖普通字段/明细行内字段/矩阵行三载体。"""
        _template, _version, ledger = self._publish_and_create()
        values = {
            'f_na000001': 'abnormal',          # 普通字段：缺说明
            'f_num00001': 220,
            'g_repeat01': [{'_rid': 'r1', 'f_rnum0001': 1,
                            'f_rna00001': 'abnormal'}],   # 明细：缺说明
            'g_matrix01': {'r_na000001': {'c_ma00001': 'abnormal'}},  # 矩阵：缺说明
        }
        error = self.save_values(ledger['id'], values)['error']
        self.assertEqual(error, '')  # 草稿允许未填完，保存不拦
        response = self.complete(ledger['id'])
        error = response['error']
        self.assertIn('必填项未填写', error)
        self.assertIn('状态检查 / 机壳外观 异常说明未填写', error)
        self.assertIn('测量 第1条 / 判断 异常说明未填写', error)
        self.assertIn('多机对比 / 通讯状态（A 机）异常说明未填写', error)
        # 补齐说明后完成成功；值=正常时不要求说明
        values['f_na000001__desc'] = '外壳锈蚀'
        values['g_repeat01'][0]['f_rna00001__desc'] = '读数异常'
        values['g_matrix01']['r_na000001']['c_ma00001__desc'] = 'A 机中断'
        self.assertEqual(self.save_values(ledger['id'], values)['error'], '')
        response = self.complete(ledger['id'])
        self.assertEqual(response.get('error', ''), '')

    def test_desc_keys_rejected_for_non_normal_abnormal(self):
        """异常说明键仅 normal_abnormal 允许：明细行/矩阵单元格收紧。"""
        _template, _version, ledger = self._publish_and_create()
        error = self.save_values(ledger['id'], {
            'g_repeat01': [{'_rid': 'r1', 'f_rnum0001': 1,
                            'f_rnum0001__desc': '数字字段带说明'}]})['error']
        self.assertIn('不支持异常说明', error)
        error = self.save_values(ledger['id'], {
            'g_matrix01': {'r_num0001': {'c_ma00001': 220,
                                         'c_ma00001__desc': '数字行带说明'}}})['error']
        self.assertIn('不支持异常说明', error)

    def test_v1_version_snapshot_keeps_v1_semantics(self):
        """历史 v1 版本快照按创建时语义解释：无数字约束、无异常说明必填，
        填写/完成/PDF 结构读取正常，且不回写快照。"""
        template = self.create_template(name='历史v1模板')
        legacy_form = {
            'protocol_version': 1,
            'groups': [
                {'id': 'g_check001', 'name': '状态检查', 'kind': 'fields', 'fields': [
                    {'id': 'f_na000001', 'name': '机壳外观', 'type': 'normal_abnormal',
                     'required': False, 'description': '', 'unit': '', 'options': []},
                    {'id': 'f_num00001', 'name': '输出电压', 'type': 'number',
                     'required': False, 'description': '', 'unit': 'V', 'options': []}]},
            ],
        }
        version = OperationLedgerFormTemplateVersion.objects.create(
            tenant_id=self.owner.tenant_id,
            template_id=template['id'], version_no=1,
            template_name_snapshot='历史v1模板',
            form=json.dumps(legacy_form, ensure_ascii=False),
            field_count=2, published_by=self.owner)
        snapshot_before = version.form
        ledger = self.create_ledger(version.id)
        # v1 快照无 min/precision：越界值与多位小数均接受
        error = self.save_values(ledger['id'], {
            'f_na000001': 'abnormal', 'f_num00001': 99999.999})['error']
        self.assertEqual(error, '')
        # v1 快照无 require_desc_when_abnormal：异常无说明也能完成
        self.assertEqual(self.complete(ledger['id']).get('error', ''), '')
        version.refresh_from_db()
        self.assertEqual(version.form, snapshot_before, '不得回写历史版本快照')
        self.assertEqual(version.get_form()['protocol_version'], 1)
