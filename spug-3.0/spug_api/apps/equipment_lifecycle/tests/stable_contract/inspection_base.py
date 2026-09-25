# -*- coding: utf-8 -*-
"""值班巡检 stable_contract 公共夹具（今日巡检改造）。

提供巡检权限码、URL、用户/模板/巡检单构造器与载荷助手；
测试一律走真实 HTTP 路径（真实代码路径 + 隔离测试数据库）。
"""
from apps.equipment_lifecycle.models import (
    InspectionDutySheet,
    InspectionTemplate,
    InspectionTemplateDevice,
    InspectionTemplateItem,
    INSPECTION_DEFAULT_CHOICES,
)
from apps.equipment_lifecycle.tests.base import make_client, make_user

INS_URL = '/equipment-lifecycle/inspection-sheets'
ITPL_URL = '/equipment-lifecycle/inspection-templates'

P_INS_VIEW = 'equipment_lifecycle.inspection.view'
P_INS_ADD = 'equipment_lifecycle.inspection.add'
P_INS_EDIT = 'equipment_lifecycle.inspection.edit'
P_INS_SUBMIT = 'equipment_lifecycle.inspection.submit'
P_INS_DEL = 'equipment_lifecycle.inspection.del'
# 旧处置权限码 equipment_lifecycle.inspection.handle_exception 已随巡检转故障/
# 转工单功能下线（无视图引用），不再纳入测试夹具。
ALL_INSPECTION_PERMS = [P_INS_VIEW, P_INS_ADD, P_INS_EDIT, P_INS_SUBMIT,
                        P_INS_DEL]

P_ITPL_VIEW = 'equipment_lifecycle.inspection_template.view'
P_ITPL_ADD = 'equipment_lifecycle.inspection_template.add'
P_ITPL_EDIT = 'equipment_lifecycle.inspection_template.edit'
P_ITPL_DEL = 'equipment_lifecycle.inspection_template.del'
ALL_INSPECTION_TPL_PERMS = [P_ITPL_VIEW, P_ITPL_ADD, P_ITPL_EDIT, P_ITPL_DEL]


def make_inspection_user(username, tenant_id='tenant_a', extra_perms=None):
    perms = list(ALL_INSPECTION_PERMS) + list(ALL_INSPECTION_TPL_PERMS)
    if extra_perms:
        perms += list(extra_perms)
    return make_user(username, perms, tenant_id=tenant_id)


def make_inspection_template(tenant_id='tenant_a', created_by=None, name='机房巡检模板',
                             **kwargs):
    """ORM 造模板：设备A 两项（choice + text），设备B 一项（choice）。"""
    defaults = dict(name=name, description='', is_active=True, tenant_id=tenant_id)
    defaults.update(kwargs)
    template = InspectionTemplate.objects.create(
        created_by=created_by, **defaults)
    device_a = InspectionTemplateDevice.objects.create(
        tenant_id=tenant_id, template=template, device_name='1号收发信机',
        display_order=0, created_by=created_by)
    device_b = InspectionTemplateDevice.objects.create(
        tenant_id=tenant_id, template=template, device_name='2号天馈系统',
        display_order=1, created_by=created_by)
    InspectionTemplateItem.objects.create(
        tenant_id=tenant_id, device=device_a, name='面板指示灯',
        input_type='choice', choices='["正常", "不正常"]', is_required=True,
        display_order=0, created_by=created_by)
    InspectionTemplateItem.objects.create(
        tenant_id=tenant_id, device=device_a, name='输出功率读数',
        input_type='text', is_required=True,
        display_order=1, created_by=created_by)
    InspectionTemplateItem.objects.create(
        tenant_id=tenant_id, device=device_b, name='驻波比检查',
        input_type='choice', choices='["正常", "不正常"]', is_required=True,
        display_order=0, created_by=created_by)
    return template


def template_payload(devices=None, **overrides):
    """聚合创建载荷：默认两个设备（一个多项、一个单项）。"""
    if devices is None:
        devices = [
            {'device_name': '1号收发信机', 'items': [
                {'name': '面板指示灯', 'input_type': 'choice', 'is_required': True},
                {'name': '输出功率读数', 'input_type': 'text',
                 'is_required': True},
            ]},
            {'device_name': '2号天馈系统', 'items': [
                {'name': '驻波比检查', 'input_type': 'choice', 'is_required': True},
            ]},
        ]
    payload = {'name': '机房巡检模板', 'description': '', 'devices': devices}
    payload.update(overrides)
    return payload


def sheet_payload(template_id, **overrides):
    payload = {
        'template_id': template_id,
        'duty_date': '2026-09-23',
        'persons': [{'user': None, 'person_name': '值班员甲'}],
        'client_token': f'tok-sheet-{template_id}',
    }
    payload.update(overrides)
    return payload


def record_spec(template_item_id, round_no, value_text='', **overrides):
    spec = {'template_item_id': template_item_id, 'round_no': round_no,
            'value_text': value_text}
    spec.update(overrides)
    return spec


def get_template_items(template):
    """按模板取检查内容，返回 {name: item}（含跨设备）。"""
    return {item.name: item for item in InspectionTemplateItem.objects.filter(
        device__template=template)}


def create_sheet_ok(client, payload):
    """创建巡检单并返回详情载荷（断言无错误；json_response 载荷在 data 键下）。"""
    resp = client.post(f'{INS_URL}/', payload, content_type='application/json')
    body = resp.json()
    assert not body.get('error'), body
    return body['data']


def put_records_ok(client, sheet_id, version, records=None, persons=None):
    payload = {'version': version, 'records': records or []}
    if persons is not None:
        payload['persons'] = persons
    resp = client.put(f'{INS_URL}/{sheet_id}/', payload,
                      content_type='application/json')
    body = resp.json()
    assert not body.get('error'), body
    return body['data']


def submit_sheet_ok(client, sheet_id):
    resp = client.post(f'{INS_URL}/{sheet_id}/submit/', {},
                       content_type='application/json')
    body = resp.json()
    assert not body.get('error'), body
    return body['data']


def get_sheet_detail(client, sheet_id):
    resp = client.get(f'{INS_URL}/{sheet_id}/')
    body = resp.json()
    assert not body.get('error'), body
    return body['data']


def get_abnormal_record_ids(detail_body):
    return [r['id'] for r in detail_body['records'] if r['result'] == 'abnormal']
