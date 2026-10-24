# -*- coding: utf-8 -*-
"""数字表单路线模板管理与台账闭环行为测试（2026-10-21）。

真实 HTTP 路径（django.test.Client + 隔离测试库），覆盖：
- 模板创建/草稿校验（结构非法显式拒绝）/发布不可变版本/available/sample/
  停用启用/删除保护与租户隔离；
- 台账创建（当前在用版本复核、client_token 幂等、类型一致性）、填写值
  校验（未知键拒绝、类型规范化）、完成填写必填终验（普通字段 + 明细组
  行内字段，矩阵不做必填）、详情按 created_from 分支；
- 统一列表/详情来源标记（source_type=form）与两条路线互不串数据；
- 手工接口对 form_template 台账的显式拦截（编辑/完成/误带路线标记创建）；
- 权限与租户隔离由后端独立校验。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.form_models import (
    OperationLedgerFormRecord,
    OperationLedgerFormTemplate,
    OperationLedgerFormTemplateVersion,
)
from apps.equipment_lifecycle.models import OperationLedger
from apps.equipment_lifecycle.tests.base import (
    make_client, make_system, make_user, URL_PREFIX,
)

P_TPL = [
    'equipment_lifecycle.ledger_template.view',
    'equipment_lifecycle.ledger_template.add',
    'equipment_lifecycle.ledger_template.edit',
    'equipment_lifecycle.ledger_template.del',
]
P_LEDGER = [
    'equipment_lifecycle.ledger.view',
    'equipment_lifecycle.ledger.add',
    'equipment_lifecycle.ledger.edit',
    'equipment_lifecycle.ledger.submit',
    'equipment_lifecycle.ledger.del',
    'equipment_lifecycle.ledger.export',
]
ALL_PERMS = P_TPL + P_LEDGER

TPL_URL = URL_PREFIX + '/form-templates'
LEDGER_URL = URL_PREFIX + '/form-ledgers'
UNIFIED_URL = URL_PREFIX + '/ledgers'


def make_form(groups=None):
    """合法表单定义夹具（覆盖 字段/明细组/矩阵 三类分组）。"""
    if groups is not None:
        return {'protocol_version': 1, 'groups': groups}
    return {
        'protocol_version': 1,
        'groups': [
            {'id': 'g_base0001', 'name': '基本信息', 'description': '', 'kind': 'fields',
             'item_name': '', 'columns': [], 'fields': [
                 {'id': 'f_date0001', 'name': '维护日期', 'type': 'date', 'required': True,
                  'description': '', 'unit': '', 'options': []},
                 {'id': 'f_look0001', 'name': '外观', 'type': 'normal_abnormal', 'required': True,
                  'description': '', 'unit': '', 'options': []},
             ]},
            {'id': 'g_measure1', 'name': '测量', 'description': '', 'kind': 'repeat',
             'item_name': '测量项目', 'columns': [], 'fields': [
                 {'id': 'f_item0001', 'name': '项目名称', 'type': 'text', 'required': True,
                  'description': '', 'unit': '', 'options': []},
                 {'id': 'f_valu0001', 'name': '测量值', 'type': 'number', 'required': True,
                  'description': '', 'unit': 'V', 'options': []},
             ]},
            {'id': 'g_matrix01', 'name': '多机对比', 'description': '', 'kind': 'matrix',
             'item_name': '',
             'columns': [{'id': 'c_ma00001', 'name': 'A 机'}, {'id': 'c_mb00001', 'name': 'B 机'}],
             'fields': [
                 {'id': 'r_volt0001', 'name': '电压', 'type': 'number', 'required': False,
                  'description': '', 'unit': 'V', 'options': []},
                 {'id': 'r_link0001', 'name': '通讯', 'type': 'normal_abnormal', 'required': False,
                  'description': '', 'unit': '', 'options': []},
             ]},
        ],
    }


class FormRouteTestBase(TestCase):
    """公共夹具：双租户用户 + 系统。"""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(
            'form_owner_%s' % cls._seed(), perms=ALL_PERMS, tenant_id='default')
        cls.other = make_user(
            'form_other_%s' % cls._seed(), perms=ALL_PERMS, tenant_id='another')
        cls.owner_client = make_client(cls.owner)
        cls.other_client = make_client(cls.other)
        cls.system = make_system(cls.owner)

    @classmethod
    def _seed(cls):
        if not hasattr(cls, '_seed_value'):
            import uuid
            cls._seed_value = uuid.uuid4().hex[:8]
        return cls._seed_value

    def create_template(self, client=None, ledger_type='week_month', **overrides):
        client = client or self.owner_client
        body = {
            'name': overrides.pop('name', '周维护数字表单'),
            'ledger_type': ledger_type,
            'description': overrides.pop('description', ''),
            'system': overrides.pop('system', None),
            'generation_period': overrides.pop('generation_period', ''),
        }
        body.update(overrides)
        response = client.post(TPL_URL + '/', json.dumps(body),
                               content_type='application/json')
        data = response.json()
        self.assertEqual(data.get('error', ''), '',
                         data.get('error', '创建模板失败但未返回错误'))
        return data['data']

    def save_draft(self, template_id, form=None, client=None):
        client = client or self.owner_client
        return client.put(
            '%s/%s/' % (TPL_URL, template_id),
            json.dumps({'form': form if form is not None else make_form()}),
            content_type='application/json')

    def publish(self, template_id, client=None):
        client = client or self.owner_client
        response = client.post('%s/%s/publish/' % (TPL_URL, template_id),
                               content_type='application/json')
        return response.json()

    def create_published_version(self, client=None, ledger_type='week_month',
                                 form=None, name=None):
        """直达夹具：创建模板 → 保存草稿 → 发布，返回 (template, version)。"""
        template = self.create_template(client=client, ledger_type=ledger_type,
                                        **({'name': name} if name else {}))
        response = self.save_draft(template['id'], form=form, client=client)
        self.assertEqual(response.json().get('error', ''), '')
        version = self.publish(template['id'], client=client)
        self.assertEqual(version.get('error', ''), '')
        return template, version['data']


class FormTemplateManageTests(FormRouteTestBase):
    """模板创建/草稿校验/发布/版本不可变/available/sample/停用删除。"""

    def test_create_and_detail_roundtrip(self):
        template = self.create_template(
            system=self.system.id, generation_period='weekly',
            description='测试说明')
        self.assertEqual(template['template_kind'], 'form')
        self.assertEqual(template['ledger_type'], 'week_month')
        self.assertEqual(template['status'], 'draft')
        detail = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']
        self.assertEqual(detail['draft'], None)
        self.assertEqual(detail['draft_state']['relation'], 'no_draft')

    def test_create_with_invalid_period_rejected(self):
        response = self.owner_client.post(TPL_URL + '/', json.dumps({
            'name': '坏周期模板', 'ledger_type': 'seasonal',
            'generation_period': 'weekly'}), content_type='application/json')
        self.assertIn('生成周期', response.json()['error'])

    def test_draft_schema_rejections(self):
        template = self.create_template()
        bad_forms = [
            ({'protocol_version': 1, 'groups': []}, '至少配置一个分组'),
            # 2026-10-23 P2 起协议当前版本为 2，未来版本整体拒绝
            ({'protocol_version': 3, 'groups': make_form()['groups']}, '协议版本'),
            (make_form(groups=[
                {'id': 'g1', 'name': '重复', 'kind': 'fields', 'fields': [
                    {'id': 'same', 'name': 'a', 'type': 'text'},
                    {'id': 'same', 'name': 'b', 'type': 'text'}]}]), '标识符重复'),
            (make_form(groups=[
                {'id': 'g1', 'name': '无选项单选', 'kind': 'fields', 'fields': [
                    {'id': 'f1', 'name': '单选', 'type': 'choice', 'options': []}]}]),
             '至少配置一个选项'),
            (make_form(groups=[
                {'id': 'g1', 'name': '坏类型', 'kind': 'fields', 'fields': [
                    {'id': 'f1', 'name': '字段', 'type': 'slider'}]}]), '类型不合法'),
            (make_form(groups=[
                {'id': 'g1', 'name': '矩阵', 'kind': 'matrix',
                 'columns': [{'id': 'c1', 'name': 'A'}], 'fields': [
                     {'id': 'r1', 'name': '行', 'type': 'textarea'}]}]), '类型不合法'),
            (make_form(groups=[
                {'id': 'g1', 'name': '坏id', 'kind': 'fields', 'fields': [
                    {'id': 'f__bad', 'name': '字段', 'type': 'text'}]}]), '标识符不合法'),
        ]
        for form, expected in bad_forms:
            response = self.save_draft(template['id'], form=form)
            self.assertIn(expected, response.json()['error'],
                          '应拒绝：%s' % expected)
        # 合法草稿保存成功，详情回读一致
        response = self.save_draft(template['id'])
        self.assertEqual(response.json().get('error', ''), '')
        detail = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']
        self.assertEqual(len(detail['draft']['form']['groups']), 3)
        self.assertEqual(detail['draft_state']['relation'], 'no_versions')
        self.assertEqual(detail['draft_state']['field_count'], 8)

    def test_publish_requires_draft_and_version_immutable(self):
        template = self.create_template()
        # 无草稿发布拒绝
        response = self.publish(template['id'])
        self.assertIn('草稿', response['error'])
        self.save_draft(template['id'])
        version = self.publish(template['id'])
        self.assertEqual(version['data']['version_no'], 1)
        self.assertEqual(version['data']['field_count'], 8)
        # 版本无写路径（PUT/DELETE/POST → 405）
        version_url = '%s/%s/versions/1/' % (TPL_URL, template['id'])
        self.assertEqual(
            self.owner_client.put(version_url, json.dumps({}),
                                  content_type='application/json').status_code, 405)
        self.assertEqual(self.owner_client.delete(version_url).status_code, 405)
        # 版本内容快照可读且与草稿一致
        content = self.owner_client.get(version_url).json()['data']
        self.assertEqual(len(content['form']['groups']), 3)
        # 草稿修改并发布 v2；v1 快照不变
        form_v2 = make_form(groups=make_form()['groups'][:1])
        self.save_draft(template['id'], form=form_v2)
        version2 = self.publish(template['id'])
        self.assertEqual(version2['data']['version_no'], 2)
        content_v1 = self.owner_client.get(version_url).json()['data']
        self.assertEqual(len(content_v1['form']['groups']), 3)

    def test_available_only_active_with_published_version(self):
        published, _ = self.create_published_version(ledger_type='week_month')
        seasonal, _ = self.create_published_version(
            ledger_type='seasonal', name='季维护数字表单')
        draft_only = self.create_template(name='仅有草稿')
        self.save_draft(draft_only['id'])
        data = self.owner_client.get(
            TPL_URL + '/available/?ledger_type=week_month').json()['data']['data']
        names = [item['name'] for item in data]
        self.assertIn(published['name'], names)
        self.assertNotIn(seasonal['name'], names)
        self.assertNotIn(draft_only['name'], names)
        # 停用后不再出现在创建入口
        self.owner_client.post('%s/%s/deactivate/' % (TPL_URL, published['id']))
        data = self.owner_client.get(
            TPL_URL + '/available/?ledger_type=week_month').json()['data']['data']
        self.assertEqual(
            [item['name'] for item in data if item['name'] == published['name']], [])

    def test_sample_form_endpoint(self):
        data = self.owner_client.get(TPL_URL + '/sample/').json()['data']
        # 2026-10-23 P2：示例升级为协议 v2（含 rows/范围/异常说明必填示例）
        self.assertEqual(data['protocol_version'], 2)
        self.assertEqual(
            [group['kind'] for group in data['groups']],
            ['fields', 'fields', 'repeat', 'matrix'])

    def test_destroy_protection_and_tenant_isolation(self):
        template, version = self.create_published_version()
        # 有台账引用时删除拒绝（先建一张台账）
        ledger_response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id']}),
            content_type='application/json')
        self.assertEqual(ledger_response.json().get('error', ''), '')
        response = self.owner_client.delete('%s/%s/' % (TPL_URL, template['id']))
        self.assertIn('引用', response.json()['error'])
        # 跨租户不可见/不可操作（按不存在处理，避免探测）
        response = self.other_client.get('%s/%s/' % (TPL_URL, template['id']))
        self.assertEqual(response.json()['error'], '模板不存在')
        response = self.other_client.post(
            '%s/%s/publish/' % (TPL_URL, template['id']))
        self.assertEqual(response.json()['error'], '模板不存在')
        self.assertFalse(OperationLedgerFormTemplate.objects.filter(
            tenant_id='another').exists())


class FormLedgerClosedLoopTests(FormRouteTestBase):
    """台账创建/填写/完成/详情/列表与两条路线隔离。"""

    def test_create_ledger_and_version_recheck(self):
        template, version = self.create_published_version()
        token = 'form_case_%s' % self._seed()
        response = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id'], 'ledger_type': 'week_month',
            'client_token': token}), content_type='application/json')
        data = response.json()['data']
        self.assertEqual(data['created_from'], 'form_template')
        self.assertTrue(data['ledger_no'].startswith('EL-WM-'))
        self.assertEqual(data['form']['version']['version_no'], 1)
        self.assertTrue(data['form']['editable'])
        ledger = OperationLedger.objects.get(pk=data['id'])
        self.assertEqual(ledger.source_form_template_id, template['id'])
        self.assertIsNotNone(ledger.form_record)
        # client_token 幂等：重复提交返回同一台账
        repeat = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id'], 'client_token': token}),
            content_type='application/json').json()['data']
        self.assertEqual(repeat['id'], data['id'])
        # 类型不一致拒绝
        response = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id'], 'ledger_type': 'seasonal'}),
            content_type='application/json')
        self.assertIn('不一致', response.json()['error'])
        # 发布 v2 后旧版本拒绝创建（行锁复核当前在用版本）
        self.save_draft(template['id'], form=make_form(
            groups=make_form()['groups'][:1]))
        self.publish(template['id'])
        response = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}), content_type='application/json')
        self.assertIn('当前在用版本', response.json()['error'])

    def test_values_validation_and_unknown_keys_rejected(self):
        template, version = self.create_published_version()
        ledger = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}),
            content_type='application/json').json()['data']
        url = '%s/%s/' % (LEDGER_URL, ledger['id'])
        valid = {
            'f_date0001': '2026-10-21', 'f_look0001': 'abnormal',
            'f_look0001__desc': '外壳裂纹',
            'g_measure1': [{'_rid': 'r1', 'f_item0001': '驻波比',
                            'f_valu0001': 1.5}],
            'g_matrix01': {'r_volt0001': {'c_ma00001': 3.2},
                           'r_link0001': {'c_mb00001': 'abnormal',
                                          'c_mb00001__desc': 'B 机中断'}},
        }
        response = self.owner_client.put(
            url, json.dumps({'values': valid}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        detail = self.owner_client.get(url).json()['data']
        self.assertEqual(detail['form']['values']['f_look0001__desc'], '外壳裂纹')
        self.assertEqual(detail['form']['values']['g_matrix01']['r_volt0001']['c_ma00001'], 3.2)
        # 未知键拒绝（防结构漂移）
        response = self.owner_client.put(
            url, json.dumps({'values': {'unknown_key': 1}}),
            content_type='application/json')
        self.assertIn('未知', response.json()['error'])
        # 类型错误拒绝（日期格式/枚举值）
        response = self.owner_client.put(
            url, json.dumps({'values': {'f_date0001': '不是日期'}}),
            content_type='application/json')
        self.assertIn('日期', response.json()['error'])
        response = self.owner_client.put(
            url, json.dumps({'values': {'f_look0001': 'ok'}}),
            content_type='application/json')
        self.assertIn('正常 或 异常', response.json()['error'])
        # 矩阵未知行/列拒绝
        response = self.owner_client.put(
            url, json.dumps({'values': {'g_matrix01': {'r_ghost': {}}}}),
            content_type='application/json')
        self.assertIn('未知矩阵行', response.json()['error'])

    def test_complete_required_validation_and_status_flow(self):
        template, version = self.create_published_version()
        ledger_id = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}),
            content_type='application/json').json()['data']['id']
        url = '%s/%s/' % (LEDGER_URL, ledger_id)
        # 必填未填：普通字段与明细行内字段都拦截（矩阵不做必填）
        response = self.owner_client.post(url + 'complete/')
        error = response.json()['error']
        self.assertIn('必填项未填写', error)
        self.assertIn('基本信息 / 维护日期', error)
        # 填齐必填（明细组留空不拦）后完成成功
        values = {
            'f_date0001': '2026-10-21', 'f_look0001': 'abnormal',
            'f_look0001__desc': '风扇异响',
            'g_measure1': [{'_rid': 'r1', 'f_item0001': '驻波比',
                            'f_valu0001': 1.5}],
        }
        response = self.owner_client.put(
            url, json.dumps({'values': values}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        # 明细行内缺必填（测量值未填）时完成被拒
        partial = dict(values)
        partial['g_measure1'] = [{'_rid': 'r1', 'f_item0001': '驻波比'}]
        self.owner_client.put(
            url, json.dumps({'values': partial}), content_type='application/json')
        response = self.owner_client.post(url + 'complete/')
        self.assertIn('测量', response.json()['error'])
        # 补齐后完成
        self.owner_client.put(
            url, json.dumps({'values': values}), content_type='application/json')
        response = self.owner_client.post(url + 'complete/')
        self.assertEqual(response.json().get('error', ''), '')
        self.assertEqual(response.json()['data']['status'], 'completed')
        # 重复完成被状态机拦截；完成态不允许再改填写值
        response = self.owner_client.post(url + 'complete/')
        self.assertIn('不允许完成填写', response.json()['error'])
        response = self.owner_client.put(
            url, json.dumps({'values': {}}), content_type='application/json')
        self.assertIn('不允许修改填写值', response.json()['error'])

    def test_unified_list_and_detail_source_type_form(self):
        template, version = self.create_published_version()
        ledger = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}),
            content_type='application/json').json()['data']
        # 统一列表：来源 form + 模板名/版本
        rows = self.owner_client.get(
            UNIFIED_URL + '/?ledger_type=week_month').json()['data']['data']
        row = next(item for item in rows if item['id'] == ledger['id'])
        self.assertEqual(row['source_type'], 'form')
        self.assertEqual(row['source_template_name'], template['name'])
        self.assertEqual(row['source_version_no'], 1)
        self.assertIn('source=form', row['detail_route'])
        # 统一详情按 created_from 分支返回表单详情
        detail = self.owner_client.get(
            '%s/%s/' % (UNIFIED_URL, ledger['id'])).json()['data']
        self.assertIn('form', detail)
        self.assertNotIn('excel', detail)
        self.assertEqual(detail['form']['version']['template_name'], template['name'])

    def test_manual_endpoints_reject_form_ledger(self):
        """form 台账误走手工明细接口被显式拦截（编辑/完成/错误创建方式）。"""
        template, version = self.create_published_version()
        ledger = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}),
            content_type='application/json').json()['data']
        # 手工编辑拒绝
        response = self.owner_client.put(
            '%s/%s/' % (UNIFIED_URL, ledger['id']),
            json.dumps({'ledger_type': 'week_month',
                        'entries': []}), content_type='application/json')
        self.assertIn('数字表单', response.json()['error'])
        # 手工创建入口携带 form_template 标记显式拒绝
        response = self.owner_client.post(UNIFIED_URL + '/', json.dumps({
            'ledger_type': 'week_month', 'created_from': 'form_template',
            'entries': []}), content_type='application/json')
        self.assertIn('不支持', response.json()['error'])
        self.assertFalse(OperationLedger.objects.filter(
            created_from='form_template', items__isnull=False).exists())

    def test_unified_complete_endpoint_delegates_to_form_route(self):
        """统一完成端点按路线委派：form 台账走数字表单必填终验并成功完成。"""
        template, version = self.create_published_version()
        ledger_id = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}),
            content_type='application/json').json()['data']['id']
        # 未填写时统一完成端点返回的是数字表单路线的必填文案（委派生效）
        response = self.owner_client.post(
            '%s/%s/complete/' % (UNIFIED_URL, ledger_id))
        self.assertIn('必填项未填写', response.json()['error'])
        self.assertIn('基本信息 / 维护日期', response.json()['error'])
        # 填齐必填后经统一端点完成成功
        self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': {
                'f_date0001': '2026-10-21', 'f_look0001': 'normal',
                'g_measure1': [{'_rid': 'r1', 'f_item0001': 'x',
                                'f_valu0001': 1}]}}),
            content_type='application/json')
        response = self.owner_client.post(
            '%s/%s/complete/' % (UNIFIED_URL, ledger_id))
        self.assertEqual(response.json().get('error', ''), '')
        self.assertEqual(response.json()['data']['status'], 'completed')

    def test_draft_delete_and_void_flow(self):
        template, version = self.create_published_version()
        ledger_id = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}),
            content_type='application/json').json()['data']['id']
        # 草稿可物理删除（填写记录随级联清理）
        response = self.owner_client.delete('%s/%s/' % (UNIFIED_URL, ledger_id))
        self.assertEqual(response.json().get('error', ''), '')
        self.assertFalse(OperationLedger.objects.filter(pk=ledger_id).exists())
        self.assertFalse(OperationLedgerFormRecord.objects.filter(
            ledger_id=ledger_id).exists())
        # 再建一张：完成后作废（受控终态，槽位释放）
        ledger_id = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}),
            content_type='application/json').json()['data']['id']
        url = '%s/%s/' % (LEDGER_URL, ledger_id)
        self.owner_client.put(url, json.dumps({'values': {
            'f_date0001': '2026-10-21', 'f_look0001': 'normal',
            'g_measure1': [{'_rid': 'r1', 'f_item0001': 'x', 'f_valu0001': 1}],
        }}), content_type='application/json')
        self.owner_client.post(url + 'complete/')
        response = self.owner_client.post(
            '%s/%s/void/' % (UNIFIED_URL, ledger_id),
            json.dumps({'reason': '填写错误'}), content_type='application/json')
        self.assertEqual(response.json()['data']['status'], 'void')
        # 默认列表不含已作废；status=void 显式可见
        rows = self.owner_client.get(
            UNIFIED_URL + '/?ledger_type=week_month').json()['data']['data']
        self.assertFalse(any(item['id'] == ledger_id for item in rows))
        rows = self.owner_client.get(
            UNIFIED_URL + '/?ledger_type=week_month&status=void').json()['data']['data']
        self.assertTrue(any(item['id'] == ledger_id for item in rows))

    def test_ledger_tenant_isolation(self):
        template, version = self.create_published_version()
        ledger = self.owner_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}),
            content_type='application/json').json()['data']
        # B 租户按不存在处理（详情/填写/完成）
        self.assertEqual(
            self.other_client.get('%s/%s/' % (LEDGER_URL, ledger['id'])).json()['error'],
            '台账不存在')
        self.assertEqual(
            self.other_client.put(
                '%s/%s/' % (LEDGER_URL, ledger['id']), json.dumps({'values': {}}),
                content_type='application/json').json()['error'],
            '台账不存在')
        # B 租户创建同 ID 模板被拒绝（跨租户按不存在）
        response = self.other_client.post(LEDGER_URL + '/', json.dumps({
            'version_id': version['id']}), content_type='application/json')
        self.assertIn('不存在', response.json()['error'])

    def test_permission_required_for_write(self):
        template, version = self.create_published_version()
        viewer = make_user('form_viewer_%s' % self._seed(),
                           perms=['equipment_lifecycle.ledger.view'])
        response = make_client(viewer).post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id']}),
            content_type='application/json')
        self.assertEqual(response.json()['error'], '权限拒绝')
        self.assertFalse(OperationLedgerFormRecord.objects.exists())
