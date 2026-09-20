# -*- coding: utf-8 -*-
"""步骤 3.2 运维台账测试公共夹具（在步骤二 base 之上扩展）。"""
import time

from apps.account.models import User  # noqa: F401  (保持与 base 一致的导入习惯)
from apps.equipment_lifecycle.models import (
    LEDGER_TYPE_INSPECTION,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
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


def make_ledger_template(created_by, tenant_id='default', applicable_systems=None,
                         ledger_type=LEDGER_TYPE_INSPECTION, **kwargs):
    cycle_default = {
        LEDGER_TYPE_INSPECTION: '',
        LEDGER_TYPE_WEEK_MONTH: 'week',
        LEDGER_TYPE_SEASONAL: 'season',
    }[ledger_type]
    defaults = dict(
        name='巡检模板A' if ledger_type == LEDGER_TYPE_INSPECTION else '维护模板A',
        template_code='TPL-INS-001',
        ledger_type=ledger_type,
        maintenance_cycle=cycle_default,
        description='',
        is_active=True,
        tenant_id=tenant_id,
        created_by=created_by,
    )
    defaults.update(kwargs)
    template = OperationLedgerTemplate.objects.create(**defaults)
    if applicable_systems:
        template.applicable_systems.set(applicable_systems)
    return template


def make_template_item(template, created_by, tenant_id='default', **kwargs):
    defaults = dict(
        template=template,
        item_code='CHK-001',
        name='设备指示灯检查',
        standard='指示灯常亮绿色',
        input_type='text',
        unit='',
        normal_range='',
        number_min=None,
        number_max=None,
        choices='',
        default_value='',
        is_required=False,
        execution_scope='all',
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
        'standard': '指示灯常亮绿色',
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
    payload = {
        'ledger_type': LEDGER_TYPE_INSPECTION,
        'maintenance_cycle': '',
        'executed_date': '2026-09-10',
        'executed_start': '2026-09-10 09:00',
        'executed_end': '2026-09-10 11:00',
        'shift': '白班',
        'location_scope': '中心机房',
        'executor_names': '王五、赵六',
        'collaborator_names': '钱七',
        'summary': '整体正常',
        'entry_note': '事后补录',
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
                         value_number=52, number_min=48, number_max=54,
                         result='abnormal', abnormal_desc='电压偏低'),
        ])],
        **kwargs)
    ledger = create_ledger_ok(client, payload)
    return ledger, system
