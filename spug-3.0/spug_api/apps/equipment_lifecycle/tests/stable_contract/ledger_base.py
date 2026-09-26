# -*- coding: utf-8 -*-
"""步骤 3.2 运维台账测试公共夹具（在步骤二 base 之上扩展）。"""
import time

from apps.account.models import User  # noqa: F401  (保持与 base 一致的导入习惯)
from apps.equipment_lifecycle.models import (
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
    OperationLedgerRowTemplateNode,
    OperationLedgerTemplate,
    OperationLedgerTemplateItem,
)
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_system, make_user

# ===== 步骤 3.2 权限码（与 ledger_views/@auth、前端 routes/codes 一致） =====
P_TPL_VIEW = 'equipment_lifecycle.ledger_template.view'
P_TPL_ADD = 'equipment_lifecycle.ledger_template.add'
P_TPL_EDIT = 'equipment_lifecycle.ledger_template.edit'
P_TPL_DEL = 'equipment_lifecycle.ledger_template.del'
P_LED_VIEW = 'equipment_lifecycle.ledger.view'
P_LED_ADD = 'equipment_lifecycle.ledger.add'
P_LED_EDIT = 'equipment_lifecycle.ledger.edit'
P_LED_SUBMIT = 'equipment_lifecycle.ledger.submit'
P_LED_REVIEW = 'equipment_lifecycle.ledger.review'
P_LED_DEL = 'equipment_lifecycle.ledger.del'
P_LED_EXPORT = 'equipment_lifecycle.ledger.export'

ALL_TEMPLATE_PERMS = [P_TPL_VIEW, P_TPL_ADD, P_TPL_EDIT, P_TPL_DEL]
ALL_LEDGER_PERMS = [P_LED_VIEW, P_LED_ADD, P_LED_EDIT, P_LED_SUBMIT, P_LED_REVIEW, P_LED_DEL, P_LED_EXPORT]

LEDGER_URL = URL_PREFIX + '/ledgers'
TEMPLATE_URL = URL_PREFIX + '/ledger-templates'


def make_ledger_template(created_by, tenant_id='default',
                         ledger_type=LEDGER_TYPE_WEEK_MONTH, **kwargs):
    defaults = dict(
        name='维护模板A',
        ledger_type=ledger_type,
        description='',
        is_active=True,
        tenant_id=tenant_id,
        created_by=created_by,
    )
    defaults.update(kwargs)
    return OperationLedgerTemplate.objects.create(**defaults)


def make_template_item(template, created_by, tenant_id='default', **kwargs):
    defaults = dict(
        template=template,
        name='设备指示灯检查',
        input_type='text',
        unit='',
        choices='',
        default_value='',
        is_required=True,
        abnormal_rule='',
        operation_guide='',
        display_order=0,
        is_active=True,
        tenant_id=tenant_id,
        created_by=created_by,
    )
    defaults.update(kwargs)
    return OperationLedgerTemplateItem.objects.create(**defaults)


def item_payload(**kwargs):
    """明细载荷：手动/临时项最小集。"""
    payload = {
        'item_name': '设备指示灯检查',
        'input_type': 'text',
        'value_text': '正常',
        'result': 'normal',
    }
    payload.update(kwargs)
    return payload


def entry_payload(system_id, items, template_id=None):
    entry = {'system_id': system_id, 'items': items}
    if template_id:
        entry['template_id'] = template_id
    return entry


def ledger_payload(entries, **kwargs):
    """台账载荷：默认周月维护（值班巡检改造后旧巡检台账只读，
    写路径契约测试一律落在仍活跃的周月/季维护台账上）。"""
    payload = {
        'ledger_type': LEDGER_TYPE_WEEK_MONTH,
        'executed_date': '2026-09-10',
        'executed_start': '2026-09-10 09:00',
        'executed_end': '2026-09-10 11:00',
        'executor_names': '王五、赵六',
        'created_from': 'manual',
        'client_token': '',
        'entries': entries,
    }
    payload.update(kwargs)
    return payload


def make_ledger_user(username='ledger_op', tenant_id='default', perms=None, is_supper=False):
    """创建具备全部台账权限的测试用户。"""
    if perms is None:
        perms = ALL_LEDGER_PERMS
    return make_user(username, perms=perms, tenant_id=tenant_id, is_supper=is_supper)


def post_json(client, url, payload):
    import json as _json
    return client.post(url, _json.dumps(payload), content_type='application/json')


def put_json(client, url, payload):
    import json as _json
    return client.put(url, _json.dumps(payload), content_type='application/json')


def create_ledger_ok(client, payload):
    """通过 API 创建台账并断言成功，返回台账详情 dict。"""
    resp = post_json(client, LEDGER_URL + '/', payload)
    data = resp.json()
    assert resp.status_code == 200 and not data.get('error'), data
    return data['data']


def make_full_ledger(created_by, tenant_id='default', system=None, **kwargs):
    """直接经 API 创建一张最小可用台账（手动两项：正常+异常）。"""
    system = system or make_system(created_by, tenant_id=tenant_id)
    user = created_by
    client = make_client(user)
    payload = ledger_payload(
        [entry_payload(system.id, [
            item_payload(),
            item_payload(item_name='电源电压测量', input_type='number', value_text='',
                         value_number=52,
                         result='abnormal', abnormal_desc='电压偏低'),
        ])],
        **kwargs)
    ledger = create_ledger_ok(client, payload)
    return ledger, system


# ======================================================================
# 第一阶段行对象树（行方向多级 + 平面列项目）夹具
# ======================================================================

ROW_NODE_URL = TEMPLATE_URL + '/%s/row-nodes'
ROW_NODE_DETAIL_URL = TEMPLATE_URL + '/%s/row-nodes/%s'
ROW_INSTANCE_URL = LEDGER_URL + '/%s/row-instances'
CELLS_URL = LEDGER_URL + '/%s/cells'

# 纸质台账示例列：PS/TX/RX/BB/显示模块 + 备注（文本）
MATRIX_COLUMN_NAMES = ['PS模块', 'TX模块', 'RX模块', 'BB模块', '显示模块', '备注']


def row_node_payload(name='主电台', node_type='check', parent=None, **kwargs):
    payload = {'name': name, 'node_type': node_type, 'display_order': 0}
    if parent is not None:
        payload['parent'] = parent
    payload.update(kwargs)
    return payload


def make_row_node(template, created_by, tenant_id='default', **kwargs):
    defaults = dict(
        parent=None,
        node_type='check',
        name='主电台',
        row_code='',
        display_order=0,
        is_repeatable=False,
        is_active=True,
        tenant_id=tenant_id,
        created_by=created_by,
    )
    defaults.update(kwargs)
    node_type = defaults['node_type']
    defaults.setdefault('is_repeatable', node_type == 'repeat_group')
    return OperationLedgerRowTemplateNode.objects.create(template=template, **defaults)


def make_matrix_template(created_by, tenant_id='default',
                         ledger_type=LEDGER_TYPE_WEEK_MONTH,
                         column_names=None, with_rows=True):
    """信道(可重复)→主电台/备电台(行对象) + 平面列项目的矩阵模板。"""
    template = make_ledger_template(created_by, tenant_id=tenant_id,
                                    ledger_type=ledger_type)
    for index, name in enumerate(column_names or MATRIX_COLUMN_NAMES):
        make_template_item(template, created_by, tenant_id=tenant_id,
                           name=name, input_type='choice' if index < 5 else 'text',
                           choices='["正常", "不正常"]' if index < 5 else '',
                           display_order=index)
    if with_rows:
        channel = make_row_node(template, created_by, tenant_id=tenant_id,
                                name='信道', node_type='repeat_group', is_repeatable=True)
        make_row_node(template, created_by, tenant_id=tenant_id,
                      name='主电台', node_type='check', parent=channel, display_order=0)
        make_row_node(template, created_by, tenant_id=tenant_id,
                      name='备电台', node_type='check', parent=channel, display_order=1)
    return template


def matrix_payload(system_id, template_id, row_instances=None, **kwargs):
    """矩阵台账载荷：表头 + 单系统 + 模板 + 行实例规格。"""
    payload = {
        'ledger_type': LEDGER_TYPE_WEEK_MONTH,
        'executed_date': '2026-09-20',
        'executor_names': '甲、乙',
        'created_from': 'template',
        'client_token': '',
        'system_id': system_id,
        'template_id': template_id,
    }
    if row_instances is not None:
        payload['row_instances'] = row_instances
    payload.update(kwargs)
    return payload


def matrix_cell_map(detail):
    """台账详情 → {(row_path, 列项目名): cell} 映射。"""
    return {(c.get('row_path') or '', c['item_name']): c for c in detail['items']}
