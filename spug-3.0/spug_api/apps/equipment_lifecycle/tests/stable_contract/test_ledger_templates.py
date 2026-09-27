# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：台账模板与快照（提示词二十三 第 5-8、15-16 项）。

2026-09-22 简化：模板不再声明适用系统，模板项目不再有 standard/normal_range/
number_min/number_max 字段，新建项目默认必填。

2026-09-27 模板可视化设计：模板新增行层级表头名称（row_headers），
矩阵台账创建时快照到台账（row_headers_snapshot），模板后续修改不影响历史。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LEDGER_TYPE_VALUES,
    OperationLedger,
    OperationLedgerItem,
    OperationLedgerRowTemplateNode,
    OperationLedgerTemplate,
    OperationLedgerTemplateItem,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    ALL_TEMPLATE_PERMS,
    LEDGER_URL,
    ROW_NODE_URL,
    TEMPLATE_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_template,
    make_ledger_user,
    make_matrix_template,
    make_template_item,
    matrix_payload,
    post_json,
    put_json,
)


def _tpl_item_payload(tpl_item, **kw):
    """模板来源明细载荷：只传模板项目 ID 与填写值/结果。"""
    payload = {'template_item_id': tpl_item.id, 'value_text': '正常', 'result': 'normal'}
    payload.update(kw)
    return payload


class LedgerTemplateContractTests(TestCase):
    def setUp(self):
        self.user = make_ledger_user(
            'tpl_op', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.system = make_system(self.user)

    def _make_week_month_template(self, **kw):
        kw.setdefault('ledger_type', 'week_month')
        template = make_ledger_template(self.user, **kw)
        item = make_template_item(template, self.user)
        return template, item

    def test_week_month_template_only_generates_week_month_ledger(self):
        """5. 周月维护模板只能生成周月维护台账（类型不匹配一律拒绝）。"""
        template, tpl_item = self._make_week_month_template()
        client = make_client(self.user)
        # 用周月维护模板生成季维护台账 → 拒绝
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            ledger_type='seasonal', created_from='template')
        resp = post_json(client, LEDGER_URL + '/', payload)
        self.assertTrue(resp.json().get('error'))
        # 旧巡检类型已删除：用维护模板生成旧巡检台账 → 明确类型错误
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            ledger_type='inspection', created_from='template')
        resp = post_json(client, LEDGER_URL + '/', payload)
        self.assertIn('已删除', resp.json().get('error') or '')

    def test_week_month_template_includes_all_active_items(self):
        """6. 周月维护不分周表/月表：全部启用项目一律参与，无周期过滤。"""
        template = make_ledger_template(
            self.user, ledger_type='week_month', name='周月维护模板')
        item_a = make_template_item(template, self.user, name='周检项目')
        item_b = make_template_item(template, self.user, name='月检项目')
        client = make_client(self.user)
        # 不再区分周/月：两张项目随同一张台账一并快照
        payload = ledger_payload(
            [entry_payload(self.system.id, [
                _tpl_item_payload(item_a), _tpl_item_payload(item_b)],
                template_id=template.id)],
            ledger_type='week_month', created_from='template')
        data = create_ledger_ok(client, payload)
        names = [i['item_name'] for i in data['items']]
        self.assertEqual(names, ['周检项目', '月检项目'])
        # 台账表头不再返回维护周期字段
        self.assertNotIn('maintenance_cycle', data)

    def test_seasonal_template_only_generates_seasonal_ledger(self):
        """7. 季维护模板只能生成季维护台账。"""
        template = make_ledger_template(
            self.user, ledger_type='seasonal',
            name='季维护模板')
        tpl_item = make_template_item(template, self.user)
        client = make_client(self.user)
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            ledger_type='week_month', created_from='template')
        self.assertTrue(post_json(client, LEDGER_URL + '/', payload).json().get('error'))
        # 正确生成季维护台账
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            ledger_type='seasonal', created_from='template')
        data = create_ledger_ok(client, payload)
        self.assertEqual(data['ledger_type'], 'seasonal')
        self.assertEqual(data['items'][0]['template_name'], '季维护模板')

    def test_quarter_maintenance_is_not_official_type(self):
        """8. "季度维护"不作为正式台账类型（非法类型被拒绝）。"""
        client = make_client(self.user)
        for bad in ('quarter', '季度维护', 'quarterly'):
            payload = ledger_payload(
                [entry_payload(self.system.id, [item_payload()])], ledger_type=bad)
            resp = post_json(client, LEDGER_URL + '/', payload)
            self.assertTrue(resp.json().get('error'), bad)
        self.assertNotIn('quarter', LEDGER_TYPE_VALUES)
        self.assertNotIn('季度维护', LEDGER_TYPE_VALUES)
        # 季维护正式类型存在；旧巡检类型已删除
        self.assertIn('seasonal', LEDGER_TYPE_VALUES)
        self.assertNotIn('inspection', LEDGER_TYPE_VALUES)

    def test_template_change_does_not_affect_generated_ledger(self):
        """15. 模板修改不影响已生成台账。"""
        template, tpl_item = self._make_week_month_template()
        client = make_client(self.user)
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            created_from='template')
        data = create_ledger_ok(client, payload)
        # 修改模板项目名称
        tpl_item.name = '已变更项目名'
        tpl_item.save()
        item = OperationLedgerItem.objects.get(ledger_id=data['id'])
        self.assertEqual(item.item_name_snapshot, '设备指示灯检查')
        self.assertNotEqual(item.item_name_snapshot, '已变更项目名')

    def test_template_item_deactivate_keeps_history(self):
        """16. 模板项目停用不删除历史台账明细。"""
        template, tpl_item = self._make_week_month_template()
        client = make_client(self.user)
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            created_from='template')
        data = create_ledger_ok(client, payload)
        # 停用再物理删除模板项目
        tpl_item.is_active = False
        tpl_item.save()
        tpl_item.delete()
        item = OperationLedgerItem.objects.filter(ledger_id=data['id']).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.item_name_snapshot, '设备指示灯检查')
        self.assertIsNone(item.template_item_id)

    def test_template_without_maintenance_cycle_created_ok(self):
        """周月维护不再拆分周表/月表：模板无维护周期概念，接口不返回该字段。"""
        client = make_client(self.user)
        resp = post_json(client, TEMPLATE_URL + '/', {
            'name': '无绑定模板',
            'ledger_type': 'week_month',
            'items': [{'name': '指示灯检查', 'input_type': 'text'}],
            'row_nodes': [{'name': '主电台', 'node_type': 'check'}]})
        data = resp.json()['data']
        self.assertNotIn('maintenance_cycle', data)
        template = OperationLedgerTemplate.objects.get(name='无绑定模板')
        self.assertFalse(
            template.items.filter(is_required=False).exists(),
            '新建模板项目应默认必填')


class LedgerTemplateAvailableContractTests(TestCase):
    """available 接口：按类型返回启用模板（模板不绑定系统）。"""

    def setUp(self):
        self.user = make_ledger_user('avail_op')
        self.system_a = make_system(self.user, system_code='SYS-A', name='通信系统A')
        self.system_b = make_system(self.user, system_code='SYS-B', name='通信系统B')
        make_ledger_template(self.user, name='模板一')
        make_ledger_template(self.user, name='模板二')
        make_ledger_template(self.user, name='停用模板', is_active=False)

    def test_available_returns_all_active_templates(self):
        """返回该类型全部启用模板，不再附带 applicable_systems/template_code。"""
        client = make_client(self.user)
        resp = client.get(TEMPLATE_URL + '/available/?ledger_type=week_month')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']['data']
        names = {t['name'] for t in data}
        self.assertEqual(names, {'模板一', '模板二'})
        for template in data:
            self.assertNotIn('applicable_systems', template)
            self.assertNotIn('template_code', template)

    def test_available_rejects_removed_inspection_type(self):
        """旧巡检类型已删除：available 请求返回明确的类型已删除错误。"""
        client = make_client(self.user)
        resp = client.get(TEMPLATE_URL + '/available/?ledger_type=inspection')
        self.assertIn('已删除', resp.json().get('error') or '')

    def test_available_week_month_items_count_includes_all_enabled(self):
        """周月维护不分周/月：items_count 即全部启用项目数。"""
        template = make_ledger_template(
            self.user, ledger_type='week_month', name='周月模板')
        make_template_item(template, self.user, name='项目一')
        make_template_item(template, self.user, name='项目二')
        make_template_item(template, self.user, name='停用项', is_active=False)
        client = make_client(self.user)
        resp = client.get(TEMPLATE_URL + '/available/?ledger_type=week_month')
        by_name = {t['name']: t for t in resp.json()['data']['data']}
        self.assertEqual(by_name['周月模板']['items_count'], 2)


class LedgerTemplateRowNodesCreationTests(TestCase):
    """模板创建一次性落库：检查项目 + 行结构（检查对象）同事务持久化。

    2026-09-27 修复：新建模板此前提交的 row_nodes 被视图丢弃（服务函数
    create_template_row_nodes 无调用方），行结构静默丢失；现要求
    检查项目与行结构随模板同事务写入，任一部分失败整体回滚不留半成品。
    """

    def setUp(self):
        self.user = make_ledger_user(
            'tpl_row_op', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.client = make_client(self.user)

    def _post(self, **kw):
        payload = {
            'name': '矩阵模板',
            'ledger_type': 'week_month',
            'items': [{'name': '外观检查', 'input_type': 'choice',
                       'choices': ['正常', '不正常']}],
            'row_nodes': [
                {'name': '信道', 'node_type': 'repeat_group', 'children': [
                    {'name': '主电台', 'node_type': 'check'},
                    {'name': '备电台', 'node_type': 'check'},
                ]},
            ],
        }
        payload.update(kw)
        return post_json(self.client, TEMPLATE_URL + '/', payload)

    def test_create_persists_row_nodes_with_items(self):
        """嵌套行节点树随模板一次性落库：父子关系/类型派生/编码自动补齐。"""
        resp = self._post()
        data = resp.json()['data']
        template = OperationLedgerTemplate.objects.get(pk=data['id'])
        self.assertEqual(template.row_nodes.count(), 3)
        root = template.row_nodes.get(parent__isnull=True)
        self.assertEqual(root.node_type, 'repeat_group')
        self.assertTrue(root.is_repeatable, '可重复分组类型应派生 is_repeatable')
        children = list(root.children.order_by('display_order', 'id'))
        self.assertEqual([c.name for c in children], ['主电台', '备电台'])
        self.assertTrue(all(c.node_type == 'check' for c in children))
        self.assertTrue(all(n.row_code for n in [root] + children),
                        '行节点缺省编码应自动生成')
        # 行节点树接口返回同一结构（重新打开模板可见）
        tree = self.client.get((ROW_NODE_URL % template.id) + '/').json()['data']['data']
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]['name'], '信道')
        self.assertEqual([c['name'] for c in tree[0]['children']], ['主电台', '备电台'])

    def test_create_without_row_nodes_rejected(self):
        """未提交行结构：拒绝创建且不留模板记录。"""
        resp = self._post(row_nodes=[])
        self.assertIn('请至少添加一个检查对象', resp.json().get('error') or '')
        self.assertEqual(OperationLedgerTemplate.objects.count(), 0)

    def test_create_without_check_node_rejected(self):
        """只有分组没有检查对象：分组不生成填写行，拒绝创建并整体回滚。"""
        resp = self._post(row_nodes=[
            {'name': '外层分组', 'node_type': 'group',
             'children': [{'name': '内层分组', 'node_type': 'group'}]}])
        self.assertIn('请至少添加一个检查对象', resp.json().get('error') or '')
        self.assertEqual(OperationLedgerTemplate.objects.count(), 0)
        self.assertEqual(OperationLedgerRowTemplateNode.objects.count(), 0)

    def test_create_without_items_rejected(self):
        """没有检查项目：拒绝创建且不留模板记录。"""
        resp = self._post(items=[])
        self.assertIn('请至少添加一个检查项目', resp.json().get('error') or '')
        self.assertEqual(OperationLedgerTemplate.objects.count(), 0)

    def test_invalid_row_node_rolls_back_whole_template(self):
        """行节点校验失败（空名称）：模板/项目/行节点整体回滚。"""
        resp = self._post(row_nodes=[
            {'name': '主电台', 'node_type': 'check'},
            {'name': '   ', 'node_type': 'check'},
        ])
        self.assertIn('行节点名称不能为空', resp.json().get('error') or '')
        self.assertEqual(OperationLedgerTemplate.objects.count(), 0)
        self.assertEqual(OperationLedgerTemplateItem.objects.count(), 0)
        self.assertEqual(OperationLedgerRowTemplateNode.objects.count(), 0)

    def test_check_node_with_children_rejected_and_rolled_back(self):
        """行对象带子节点：拒绝创建且整体回滚。"""
        resp = self._post(row_nodes=[
            {'name': '主电台', 'node_type': 'check',
             'children': [{'name': '子项', 'node_type': 'check'}]},
        ])
        self.assertIn('不能包含子节点', resp.json().get('error') or '')
        self.assertEqual(OperationLedgerTemplate.objects.count(), 0)
        self.assertEqual(OperationLedgerRowTemplateNode.objects.count(), 0)


class LedgerTemplateRowHeadersTests(TestCase):
    """行层级表头名称（2026-09-27 模板可视化设计第一阶段）。

    - 模板新建/编辑均可保存行层级表头（如"信道""电台"），层级由数组
      顺序派生，不信任前端提交的 level 编号；
    - 矩阵台账创建时快照到台账 row_headers_snapshot，模板后续修改
      层级表头不影响已生成台账的详情展示；
    - 非法输入（超 5 级/非字符串/空名）拒绝且不留模板记录。
    """

    def setUp(self):
        self.user = make_ledger_user(
            'tpl_header_op', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def _post(self, **kw):
        payload = {
            'name': '表头模板',
            'ledger_type': 'week_month',
            'row_headers': ['信道', '电台'],
            'items': [{'name': '外观检查', 'input_type': 'choice',
                       'choices': ['正常', '不正常']}],
            'row_nodes': [{'name': '主电台', 'node_type': 'check'}],
        }
        payload.update(kw)
        return post_json(self.client, TEMPLATE_URL + '/', payload)

    def test_create_persists_row_headers(self):
        """随模板创建行层级表头：创建响应与模板详情均返回。"""
        resp = self._post()
        self.assertFalse(resp.json().get('error'), resp.json())
        data = resp.json()['data']
        self.assertEqual(data['row_headers'], ['信道', '电台'])
        detail = self.client.get('%s/%s/' % (TEMPLATE_URL, data['id'])).json()['data']
        self.assertEqual(detail['row_headers'], ['信道', '电台'])

    def test_create_without_row_headers_defaults_empty(self):
        """未提交层级表头：缺省为空列表（展示端回退默认"第N级"）。"""
        data = self._post(row_headers=None).json()['data']
        self.assertEqual(data['row_headers'], [])

    def test_create_with_six_levels_rejected(self):
        """超过最大层级（6 个层级表头）：拒绝创建且整体回滚。"""
        resp = self._post(row_headers=['一', '二', '三', '四', '五', '六'])
        self.assertIn('最多支持 5 级', resp.json().get('error') or '')
        self.assertEqual(OperationLedgerTemplate.objects.count(), 0)

    def test_create_with_invalid_entries_rejected(self):
        """非数组/非字符串/空名称的层级表头一律拒绝且不留模板。"""
        for bad in ('信道', ['信道', ''], ['信道', '   '], ['信道', 2]):
            resp = self._post(row_headers=bad)
            self.assertIn('行层级表头', resp.json().get('error') or '',
                          'row_headers=%r 应被拒绝' % (bad,))
        self.assertEqual(OperationLedgerTemplate.objects.count(), 0)

    def test_update_row_headers(self):
        """编辑模板保存新的层级表头：以数组顺序派生层级。"""
        data = self._post().json()['data']
        resp = put_json(self.client, '%s/%s/' % (TEMPLATE_URL, data['id']),
                        {'name': '表头模板', 'ledger_type': 'week_month',
                         'description': '', 'row_headers': ['系统', '设备', '部件']})
        self.assertFalse(resp.json().get('error'), resp.json())
        template = OperationLedgerTemplate.objects.get(pk=data['id'])
        self.assertEqual(template.get_row_headers(), ['系统', '设备', '部件'])

    def test_matrix_ledger_snapshots_row_headers_and_detail_uses_snapshot(self):
        """矩阵台账创建时快照层级表头；模板后续修改不影响历史详情。"""
        template = make_matrix_template(self.user)
        template.row_headers = json.dumps(['信道', '电台'], ensure_ascii=False)
        template.save(update_fields=['row_headers'])
        channel = template.row_nodes.get(name='信道')
        detail = create_ledger_ok(self.client, matrix_payload(
            self.system.id, template.id,
            row_instances=[{'template_node': channel.id, 'name': '第1信道'}]))
        ledger = OperationLedger.objects.get(pk=detail['id'])
        self.assertEqual(ledger.get_row_headers(), ['信道', '电台'])
        resp = self.client.get('%s/%s/' % (LEDGER_URL, ledger.id)).json()['data']
        self.assertEqual(resp['row_headers'], ['信道', '电台'])
        # 模板层级表头后续修改：历史台账详情保持生成时快照
        template.row_headers = json.dumps(['频段', '机型'], ensure_ascii=False)
        template.save(update_fields=['row_headers'])
        resp = self.client.get('%s/%s/' % (LEDGER_URL, ledger.id)).json()['data']
        self.assertEqual(resp['row_headers'], ['信道', '电台'])

    def test_template_item_put_updates_active_flag(self):
        """编辑模板项目支持停用/启用（is_active 显式提交才更新）。"""
        template = make_ledger_template(self.user)
        item = make_template_item(template, self.user, name='外观检查')
        resp = put_json(
            self.client, '%s/%s/items/%s/' % (TEMPLATE_URL, template.id, item.id),
            {'name': '外观检查', 'input_type': 'choice',
             'choices': ['正常', '不正常'], 'is_active': False})
        self.assertFalse(resp.json().get('error'), resp.json())
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        # 不带 is_active 的更新保持原值（不会误启用）
        resp = put_json(
            self.client, '%s/%s/items/%s/' % (TEMPLATE_URL, template.id, item.id),
            {'name': '外观检查改名', 'input_type': 'choice',
             'choices': ['正常', '不正常']})
        self.assertFalse(resp.json().get('error'), resp.json())
        item.refresh_from_db()
        self.assertFalse(item.is_active)
