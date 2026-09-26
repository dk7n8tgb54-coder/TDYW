# -*- coding: utf-8 -*-
"""第一阶段行对象树稳定契约：行模板节点 + 行实例 + 矩阵单元格。

覆盖提示词十三的 18 项场景（行方向多级、平面列项目复用、单元格生成与
结果规则、历史台账可读可导出、租户隔离），全部走真实 API / 服务代码路径。
"""
from django.test import TestCase

from apps.equipment_lifecycle.ledger_row_services import (
    LedgerValidationError,
    _validate_node_parent,
)
from apps.equipment_lifecycle.models import (
    OperationLedgerRowTemplateNode,  # noqa: F401  (模型导入确认字段存在)
)
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    ALL_TEMPLATE_PERMS,
    CELLS_URL,
    LEDGER_URL,
    MATRIX_COLUMN_NAMES,
    ROW_INSTANCE_URL,
    ROW_NODE_URL,
    TEMPLATE_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    make_matrix_template,
    make_row_node,
    matrix_cell_map,
    matrix_payload,
    post_json,
    put_json,
)


def delete_json(client, url):
    return client.delete(url)


def _flatten_instances(tree):
    rows = []
    for node in tree or []:
        rows.append(node)
        rows.extend(_flatten_instances(node.get('children') or []))
    return rows


def _data(resp):
    """成功响应解包：HTTP 200 + {'data': ..., 'error': ''} 契约。"""
    body = resp.json()
    assert not body.get('error'), body
    return body['data']


def _node_ids(template):
    return list(template.row_nodes.order_by('id').values_list('id', flat=True))


class RowNodeContractTests(TestCase):
    """行模板节点：创建/层级/自引用/循环/跨模板/类型规则（场景 1-7）。"""

    def setUp(self):
        self.user = make_ledger_user('row_op', perms=ALL_TEMPLATE_PERMS + ALL_LEDGER_PERMS)
        self.client = make_client(self.user)
        self.template = make_matrix_template(self.user, with_rows=False)

    def _url(self, template=None):
        return ROW_NODE_URL % (template or self.template).id + '/'

    def test_1_create_row_node(self):
        resp = post_json(self.client, self._url(), {'name': '信道', 'node_type': 'repeat_group'})
        data = _data(resp)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['node_type'], 'repeat_group')
        self.assertTrue(data['is_repeatable'])
        self.assertTrue(data['row_code'])
        # 平面列项目不受影响：模板列项目仍为根级
        self.assertEqual(self.template.items.filter(is_active=True).count(), 6)

    def test_2_five_level_tree_ok(self):
        parent = None
        for level in range(1, 6):
            resp = post_json(self.client, self._url(), {
                'name': 'L%d' % level, 'node_type': 'check' if level == 5 else 'group',
                **({'parent': parent} if parent else {})})
            self.assertFalse(resp.json().get('error'), resp.json())
            parent = _data(resp)['id']
        tree = self.client.get(self._url()).json()['data']['data']
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]['level'], 1)
        leaf = tree[0]['children'][0]['children'][0]['children'][0]['children'][0]
        self.assertEqual(leaf['level'], 5)
        self.assertEqual(len(leaf['path'].split(' / ')), 5)
        self.assertTrue(leaf['is_leaf'])
        self.assertEqual(tree[0]['children_count'], 1)

    def test_3_sixth_level_rejected(self):
        parent = None
        for level in range(1, 5):
            resp = post_json(self.client, self._url(), {
                'name': 'L%d' % level, 'node_type': 'group',
                **({'parent': parent} if parent else {})})
            parent = _data(resp)['id']
        resp = post_json(self.client, self._url(), {'name': 'L5', 'node_type': 'group', 'parent': parent})
        fifth = _data(resp)['id']
        resp = post_json(self.client, self._url(), {'name': 'L6', 'node_type': 'check', 'parent': fifth})
        self.assertIn('error', resp.json())
        self.assertIn('最多支持 5 级', resp.json()['error'])

    def test_4_self_reference_rejected(self):
        node = make_row_node(self.template, self.user, name='A', node_type='group')
        with self.assertRaises(LedgerValidationError):
            _validate_node_parent(self.template, node, node.id)
        # 经真实 API：编辑接口把父级设为自身同样拒绝
        resp = put_json(self.client, (ROW_NODE_URL % self.template.id) + '/%s/' % node.id,
                        {'name': 'A', 'node_type': 'group', 'parent': node.id})
        self.assertIn('error', resp.json())

    def test_5_cycle_reference_rejected(self):
        root = make_row_node(self.template, self.user, name='R', node_type='group')
        child = make_row_node(self.template, self.user, name='C', node_type='group',
                              parent=root, display_order=0)
        # 把根节点挂到其子节点之下形成环
        resp = put_json(self.client, (ROW_NODE_URL % self.template.id) + '/%s/' % root.id,
                        {'name': 'R', 'node_type': 'group', 'parent': child.id})
        self.assertIn('error', resp.json())
        self.assertIn('循环', resp.json()['error'])

    def test_6_cross_template_parent_rejected(self):
        other = make_matrix_template(self.user, with_rows=False)
        other_node = make_row_node(other, self.user, name='X', node_type='group')
        resp = post_json(self.client, self._url(), {
            'name': 'B', 'node_type': 'check', 'parent': other_node.id})
        self.assertIn('error', resp.json())
        self.assertIn('不属于当前模板', resp.json()['error'])

    def test_7_check_node_cannot_have_children_and_group_has_no_cells(self):
        check = post_json(self.client, self._url(), {'name': '主电台', 'node_type': 'check'}).json()['data']
        resp = post_json(self.client, self._url(), {
            'name': '子节点', 'node_type': 'check', 'parent': check['id']})
        self.assertIn('error', resp.json())
        self.assertIn('不能包含子节点', resp.json()['error'])
        # 编辑接口把有子节点的分组改为 check 同样拒绝
        group = post_json(self.client, self._url(), {'name': 'G', 'node_type': 'group'}).json()['data']
        post_json(self.client, self._url(), {'name': 'S', 'node_type': 'check', 'parent': group['id']})
        resp = put_json(self.client, (ROW_NODE_URL % self.template.id) + '/%s/' % group['id'],
                        {'name': 'G', 'node_type': 'check'})
        self.assertIn('error', resp.json())


class MatrixCellGenerationTests(TestCase):
    """矩阵单元格生成：行叶子实例 × 平面列项目（场景 8-13）。"""

    def setUp(self):
        self.user = make_ledger_user('mx_op', perms=ALL_TEMPLATE_PERMS + ALL_LEDGER_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.template = make_matrix_template(self.user)

    def _channel_node(self):
        return self.template.row_nodes.get(name='信道')

    def test_8_repeat_group_instances_and_shared_columns(self):
        # 场景 8/9/10：一个信道（主+备两个行叶子）× 6 列 = 12 单元格，
        # 列项目只配置一次即被主/备复用
        channel = self._channel_node()
        payload = matrix_payload(
            self.system.id, self.template.id,
            row_instances=[{'template_node': channel.id, 'name': '第1信道'}])
        detail = create_ledger_ok(self.client, payload)
        self.assertEqual(len(detail['items']), 12)
        flat = _flatten_instances(detail['row_instances'])
        self.assertEqual(len(flat), 3)  # 信道 + 主 + 备
        self.assertEqual([r['instance_name'] for r in flat].count('第1信道'), 1)
        paths = {c['row_path'] for c in detail['items']}
        self.assertEqual(paths, {'第1信道 / 主电台', '第1信道 / 备电台'})
        # 每个列项目在两个行叶子上各生成一条明细（复用而非重复配置）
        by_column = {}
        for cell in detail['items']:
            by_column.setdefault(cell['item_name'], []).append(cell)
        for name in MATRIX_COLUMN_NAMES:
            self.assertEqual(len(by_column[name]), 2, name)
        # 备注列为文本单元格（场景 12）
        remark = by_column['备注'][0]
        self.assertEqual(remark['input_type'], 'text')
        self.assertIn('row_code', remark)
        self.assertIn('cell_code', remark)
        # 明细单元格携带 row_headers 祖先链（前端按 row_headers[0..4] 渲染行层级列）
        mains = [c for c in detail['items'] if c['row_path'] == '第1信道 / 主电台']
        headers = mains[0]['row_headers']
        self.assertEqual([h['level'] for h in headers], [1, 2])
        self.assertEqual([h['name'] for h in headers], ['第1信道', '主电台'])
        self.assertTrue(all(h['code'] for h in headers))
        # 未填写不能自动转换为正常（场景 15）：生成即未填写
        self.assertTrue(all(c['result'] == '' for c in detail['items']))
        self.assertTrue(all(c['column_code'] for c in detail['items']))

    def test_11_two_channels_generate_24_cells(self):
        channel = self._channel_node()
        payload = matrix_payload(
            self.system.id, self.template.id,
            row_instances=[{'template_node': channel.id, 'name': '第1信道'},
                           {'template_node': channel.id, 'name': '第2信道'}])
        detail = create_ledger_ok(self.client, payload)
        self.assertEqual(len(detail['items']), 24)
        paths = {c['row_path'] for c in detail['items']}
        self.assertEqual(len(paths), 4)
        self.assertIn('第2信道 / 备电台', paths)
        # 祖先链按真实父子外键回溯：两个信道的单元格各挂各的链，互不串扰
        second = next(c for c in detail['items'] if c['row_path'] == '第2信道 / 备电台')
        self.assertEqual([h['name'] for h in second['row_headers']], ['第2信道', '备电台'])
        first = next(c for c in detail['items'] if c['row_path'] == '第1信道 / 备电台')
        self.assertEqual([h['name'] for h in first['row_headers']], ['第1信道', '备电台'])

    def test_13_seasonal_preview_and_create(self):
        template = make_matrix_template(self.user, ledger_type='seasonal')
        channel = template.row_nodes.get(name='信道')
        # 模板加载：季维护按 ledger_type 加载（维护周期已删除）
        resp = self.client.get(
            TEMPLATE_URL + '/available/?ledger_type=seasonal')
        self.assertFalse(resp.json().get('error'), resp.json())
        # 预览请求返回行树与列项目
        resp = post_json(self.client, LEDGER_URL + '/preview/', {
            'ledger_type': 'seasonal',
            'entries': [{'system_id': self.system.id, 'template_id': template.id}]})
        data = resp.json()['data']['data'][0]
        self.assertTrue(data['is_matrix'])
        self.assertEqual(data['row_nodes'][0]['name'], '信道')
        self.assertEqual(data['row_nodes'][0]['node_type'], 'repeat_group')
        self.assertEqual(len(data['items']), 6)
        # 季维护矩阵创建
        detail = create_ledger_ok(self.client, matrix_payload(
            self.system.id, template.id,
            row_instances=[{'template_node': channel.id, 'name': '第1信道'}],
            ledger_type='seasonal'))
        self.assertEqual(len(detail['items']), 12)


class MatrixWorkflowTests(TestCase):
    """矩阵台账工作流：实例增删/单元格编辑/提交/一键正常/快照稳定。"""

    def setUp(self):
        self.user = make_ledger_user('mx_wf', perms=ALL_TEMPLATE_PERMS + ALL_LEDGER_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.template = make_matrix_template(self.user)
        self.channel = self.template.row_nodes.get(name='信道')
        self.detail = create_ledger_ok(self.client, matrix_payload(
            self.system.id, self.template.id,
            row_instances=[{'template_node': self.channel.id, 'name': '第1信道'}]))
        self.ledger_id = self.detail['id']

    def _cells(self):
        return self.client.get(LEDGER_URL + '/%s/' % self.ledger_id).json()['data']

    def _post_instance(self, payload):
        return post_json(self.client, ROW_INSTANCE_URL % self.ledger_id + '/', payload)

    def test_add_and_delete_instance_syncs_cells(self):
        resp = self._post_instance({'template_node': self.channel.id, 'name': '第2信道'})
        detail = _data(resp)
        self.assertEqual(len(detail['items']), 24)
        paths = {c['row_path'] for c in detail['items']}
        self.assertIn('第2信道 / 主电台', paths)
        # 删除第2信道：其子树实例与 12 个单元格一并删除
        second = next(i for i in _flatten_instances(detail['row_instances']) if i['instance_name'] == '第2信道')
        self.assertEqual(second['row_path'], '第2信道')
        resp = delete_json(self.client, (ROW_INSTANCE_URL % self.ledger_id) + '/%s/' % second['id'])
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(len(_data(resp)['items']), 12)

    def test_delete_last_instance_rejected(self):
        first = self.detail['row_instances'][0]
        resp = delete_json(self.client, (ROW_INSTANCE_URL % self.ledger_id) + '/%s/' % first['id'])
        self.assertIn('error', resp.json())
        self.assertIn('至少保留一个实例', resp.json()['error'])

    def test_rename_instance_syncs_cell_paths(self):
        first = self.detail['row_instances'][0]
        resp = put_json(self.client, (ROW_INSTANCE_URL % self.ledger_id) + '/%s/' % first['id'],
                        {'instance_name': '主用信道'})
        detail = _data(resp)
        paths = {c['row_path'] for c in detail['items']}
        self.assertIn('主用信道 / 主电台', paths)
        self.assertNotIn('第1信道 / 主电台', paths)

    def test_14_required_cells_block_submit_and_editable_cells(self):
        cells = self._cells()['items']
        # 必填单元格未填写：提交返回业务错误
        resp = post_json(self.client, LEDGER_URL + '/%s/submit/' % self.ledger_id, {})
        self.assertIn('error', resp.json())
        self.assertIn('必填单元格未填写', resp.json()['error'])
        # 填写全部单元格后可提交；choice 填"不正常"派生异常
        values = []
        for cell in cells:
            row = {'id': cell['id']}
            if cell['input_type'] == 'choice':
                row['value_text'] = '正常'
            else:
                row['value_text'] = '备注已填'
            values.append(row)
        resp = put_json(self.client, CELLS_URL % self.ledger_id + '/',
                        {'version': self._cells()['version'], 'values': values})
        self.assertFalse(resp.json().get('error'), resp.json())
        # 单独把一个 choice 单元格改为"不正常" → 异常
        abnormal_cell = next(c for c in _data(resp)['items'] if c['input_type'] == 'choice')
        resp = put_json(self.client, CELLS_URL % self.ledger_id + '/', {
            'values': [{'id': abnormal_cell['id'], 'value_text': '不正常'}]})
        updated = matrix_cell_map(_data(resp))
        key = (abnormal_cell['row_path'], abnormal_cell['item_name'])
        self.assertEqual(updated[key]['result'], 'abnormal')
        self.assertEqual(_data(resp)['abnormal_count'], 1)
        resp = post_json(self.client, LEDGER_URL + '/%s/submit/' % self.ledger_id, {})
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_one_key_normal_only_unset_cells(self):
        cells = self._cells()['items']
        # 把第一个填成异常，其余保持未填写
        target = cells[0]
        put_json(self.client, CELLS_URL % self.ledger_id + '/', {
            'values': [{'id': target['id'], 'value_text': '不正常'}]})
        unset_ids = [c['id'] for c in cells[1:]]
        # 一键正常包含异常单元格 → 整体拒绝（不能修改已有异常结果）
        resp = post_json(self.client, LEDGER_URL + '/%s/confirm-normal/' % self.ledger_id,
                         {'item_ids': [target['id']] + unset_ids})
        self.assertIn('error', resp.json())
        self.assertIn('未填写', resp.json()['error'])
        # 仅未填写单元格可一键正常
        resp = post_json(self.client, LEDGER_URL + '/%s/confirm-normal/' % self.ledger_id,
                         {'item_ids': unset_ids})
        self.assertFalse(resp.json().get('error'), resp.json())
        results = {c['id']: c['result'] for c in _data(resp)['items']}
        self.assertEqual(results[target['id']], 'abnormal')
        self.assertTrue(all(results[i] == 'normal' for i in unset_ids))

    def test_16_template_column_edit_keeps_snapshots(self):
        item = self.template.items.first()
        old_name = item.name
        item.name = '改名列'
        item.save(update_fields=['name'])
        detail = self._cells()
        cell = detail['items'][0]
        self.assertEqual(cell['item_name'], old_name)
        self.assertEqual(cell['column_name'], old_name)

    def test_matrix_ledger_rejects_entries_put(self):
        resp = put_json(self.client, LEDGER_URL + '/%s/' % self.ledger_id, {
            'ledger_type': 'week_month',
            'executed_date': '2026-09-21',
            'entries': [entry_payload(self.system.id, [item_payload()])]})
        self.assertIn('error', resp.json())
        self.assertIn('矩阵台账', resp.json()['error'])

    def test_legacy_entries_reject_row_structured_template(self):
        # 已配置行结构的模板不能走旧 entries 模式生成明细
        payload = ledger_payload([entry_payload(
            self.system.id,
            [{'template_item_id': self.template.items.first().id, 'value_text': '正常'}],
            template_id=self.template.id)])
        resp = post_json(self.client, LEDGER_URL + '/', payload)
        self.assertIn('error', resp.json())
        self.assertIn('矩阵方式', resp.json()['error'])

    def test_17_legacy_ledger_still_readable_and_exportable(self):
        legacy = create_ledger_ok(self.client, ledger_payload(
            [entry_payload(self.system.id, [item_payload()])]))
        resp = self.client.get(LEDGER_URL + '/%s/' % legacy['id'])
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(resp.json()['data']['row_instances'], [])
        resp = self.client.get(LEDGER_URL + '/export/?ledger_type=week_month')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8-sig')
        self.assertIn(legacy['ledger_no'], content)
        self.assertIn('行路径', content)
        # 矩阵台账导出包含行路径与列项目名称
        self.assertIn('第1信道 / 主电台', content)

    def test_18_tenant_isolation(self):
        stranger = make_ledger_user('stranger_op', tenant_id='other',
                                    perms=ALL_TEMPLATE_PERMS + ALL_LEDGER_PERMS)
        stranger_client = make_client(stranger)
        # 行模板节点
        resp = stranger_client.get(ROW_NODE_URL % self.template.id + '/')
        self.assertIn('error', resp.json())
        node = self.template.row_nodes.first()
        resp = put_json(stranger_client, (ROW_NODE_URL % self.template.id) + '/%s/' % node.id,
                        {'name': '越权', 'node_type': 'group'})
        self.assertIn('error', resp.json())
        # 行实例与单元格
        resp = stranger_client.get(ROW_INSTANCE_URL % self.ledger_id + '/')
        self.assertIn('error', resp.json())
        resp = put_json(stranger_client, CELLS_URL % self.ledger_id + '/',
                        {'values': [{'id': self.detail['items'][0]['id'], 'value_text': '越权'}]})
        self.assertIn('error', resp.json())
        resp = stranger_client.get(LEDGER_URL + '/%s/' % self.ledger_id)
        self.assertIn('error', resp.json())


class MatrixHeaderAndGuardTests(TestCase):
    """矩阵台账表头编辑与幂等。"""

    def setUp(self):
        self.user = make_ledger_user('mx_hdr', perms=ALL_TEMPLATE_PERMS + ALL_LEDGER_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.template = make_matrix_template(self.user)
        self.channel = self.template.row_nodes.get(name='信道')

    def test_cells_put_updates_header_and_bumps_version(self):
        detail = create_ledger_ok(self.client, matrix_payload(
            self.system.id, self.template.id,
            row_instances=[{'template_node': self.channel.id, 'name': '第1信道'}]))
        version = detail['version']
        resp = put_json(self.client, CELLS_URL % detail['id'] + '/', {
            'version': version,
            'executed_date': '2026-09-22',
            'executor_names': '修改人',
            'values': [],
        })
        # 空 values 明确拒绝
        self.assertIn('error', resp.json())
        resp = put_json(self.client, CELLS_URL % detail['id'] + '/', {
            'version': version,
            'executed_date': '2026-09-22',
            'executor_names': '修改人',
            'values': [{'id': next(c['id'] for c in detail['items'] if c['input_type'] == 'text'),
                        'value_text': '已备注'}],
        })
        data = _data(resp)
        self.assertEqual(data['executed_date'], '2026-09-22')
        self.assertEqual(data['executor_names'], '修改人')
        self.assertEqual(data['version'], version + 1)

    def test_matrix_create_idempotent_by_client_token(self):
        payload = matrix_payload(
            self.system.id, self.template.id,
            row_instances=[{'template_node': self.channel.id, 'name': '第1信道'}],
            client_token='mx_token_1')
        first = create_ledger_ok(self.client, payload)
        second = create_ledger_ok(self.client, payload)
        self.assertEqual(first['id'], second['id'])
