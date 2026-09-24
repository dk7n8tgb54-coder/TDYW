# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：台账预览——系统必选、模板不绑定系统。

模板不再声明适用系统（2026-09-22 简化）：
- 条目形态 {system_id, template_id?}——系统必选，缺失即拒绝；
- 模板适用于任何系统，不再存在"只选模板按适用系统展开"分支。
"""
from django.test import TestCase

from apps.equipment_lifecycle.models import OperationLedger, OperationLedgerItem
from apps.equipment_lifecycle.tests.base import make_client, make_system, make_user
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    LEDGER_URL,
    create_ledger_ok,
    entry_payload,
    ledger_payload,
    make_ledger_template,
    make_ledger_user,
    make_template_item,
    post_json,
)

PREVIEW_URL = LEDGER_URL + '/preview/'


def _tpl_item_payload(tpl_item, **kw):
    """模板来源明细载荷：只传模板项目 ID 与填写值/结果。"""
    payload = {'template_item_id': tpl_item.id, 'value_text': '正常', 'result': 'normal'}
    payload.update(kw)
    return payload


def _preview_body(entries, ledger_type='week_month', maintenance_cycle='week'):
    return {
        'ledger_type': ledger_type,
        'maintenance_cycle': maintenance_cycle,
        'entries': entries,
    }


class LedgerPreviewContractTests(TestCase):
    def setUp(self):
        self.user = make_ledger_user('preview_op')
        self.system_a = make_system(self.user, system_code='SYS-A', name='通信系统A')
        self.system_b = make_system(self.user, system_code='SYS-B', name='通信系统B')

    def _make_template(self, **kw):
        template = make_ledger_template(self.user, **kw)
        item = make_template_item(template, self.user)
        return template, item

    def test_preview_requires_system_per_entry(self):
        """只选模板不选系统的条目被拒绝（模板先行展开已移除）。"""
        template, _ = self._make_template()
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body([{'template_id': template.id}]))
        self.assertEqual(resp.json().get('error'), '请选择系统')

    def test_preview_explicit_system_with_template(self):
        """显式 系统+模板 条目：每套系统展开该模板项目，模板可用于任何系统。"""
        template, tpl_item = self._make_template()
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body([
            {'system_id': self.system_a.id, 'template_id': template.id},
            {'system_id': self.system_b.id, 'template_id': template.id},
        ]))
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        entries = data['data']['data']
        self.assertEqual({e['system']['id'] for e in entries},
                         {self.system_a.id, self.system_b.id})
        for entry in entries:
            self.assertEqual(entry['template']['id'], template.id)
            self.assertEqual(len(entry['items']), 1)
            item = entry['items'][0]
            self.assertEqual(item['id'], tpl_item.id)
            self.assertTrue(item['client_key'].startswith('%s-' % entry['system']['id']))

    def test_preview_rejects_cross_tenant_template(self):
        """跨租户模板 ID 一律视为不存在（租户过滤）。"""
        other_user = make_user('other_owner2', tenant_id='other')
        other_template = make_ledger_template(
            other_user, tenant_id='other')
        client = make_client(self.user)
        resp = post_json(
            client, PREVIEW_URL, _preview_body(
                [{'system_id': self.system_a.id, 'template_id': other_template.id}]))
        self.assertEqual(resp.json().get('error'), '台账模板不存在')

    def test_preview_rejects_entry_without_system_and_template(self):
        """缺 system_id 的条目被拒；非 dict 条目按格式错误处理。"""
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body([{}]))
        self.assertEqual(resp.json().get('error'), '请选择系统')
        resp = post_json(client, PREVIEW_URL, _preview_body(['not-a-dict']))
        self.assertEqual(resp.json().get('error'), '台账系统条目格式不正确')

    def test_preview_explicit_week_month_cycle(self):
        """周月维护显式条目：按周期过滤项目，周期不匹配被拒。"""
        template = make_ledger_template(
            self.user, ledger_type='week_month', maintenance_cycle='week',
            name='周维护模板')
        make_template_item(template, self.user, name='仅每周项', execution_scope='week_only')
        make_template_item(template, self.user, name='仅每月项', execution_scope='month_only')
        make_template_item(template, self.user, name='周月均执行项', execution_scope='all')
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body(
            [{'system_id': self.system_a.id, 'template_id': template.id}],
            ledger_type='week_month', maintenance_cycle='week'))
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        names = {i['name'] for i in data['data']['data'][0]['items']}
        self.assertEqual(names, {'仅每周项', '周月均执行项'})
        # 周期与模板不一致 → 拒绝
        resp = post_json(client, PREVIEW_URL, _preview_body(
            [{'system_id': self.system_a.id, 'template_id': template.id}],
            ledger_type='week_month', maintenance_cycle='month'))
        self.assertIn('周期不一致', resp.json().get('error') or '')

    def test_preview_explicit_entry_without_template_still_supported(self):
        """显式系统条目不带模板（手动骨架）行为保持不变。"""
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body(
            [{'system_id': self.system_a.id}]))
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        self.assertEqual(len(data['data']['data']), 1)
        self.assertIsNone(data['data']['data'][0]['template'])
        self.assertEqual(data['data']['data'][0]['items'], [])


class LedgerTemplateProvenanceContractTests(TestCase):
    """明细模板来源落库：entry 带 template_id 时保存模板快照而非临时补录。"""

    def setUp(self):
        self.user = make_ledger_user('prov_op')
        self.system_a = make_system(self.user, system_code='SYS-A', name='通信系统A')

    def test_same_system_two_templates_create_ok(self):
        """同系统两条不同模板条目创建成功，各自明细带各自模板快照。"""
        template_a = make_ledger_template(
            self.user, name='模板A', ledger_type='week_month', maintenance_cycle='week')
        item_a = make_template_item(template_a, self.user, name='模板A项目')
        template_b = make_ledger_template(
            self.user, name='模板B', ledger_type='week_month', maintenance_cycle='week')
        item_b = make_template_item(template_b, self.user, name='模板B项目')
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system_a.id, [_tpl_item_payload(item_a)], template_id=template_a.id),
            entry_payload(self.system_a.id, [_tpl_item_payload(item_b)], template_id=template_b.id),
        ], created_from='template')
        data = create_ledger_ok(client, payload)
        self.assertEqual(len(data['items']), 2)
        by_template = {i['template_name'] for i in data['items']}
        self.assertEqual(by_template, {'模板A', '模板B'})
        ledger_items = OperationLedgerItem.objects.filter(ledger_id=data['id'])
        self.assertEqual(ledger_items.filter(is_temporary=False).count(), 2)
        self.assertEqual(
            set(ledger_items.values_list('template_item_id', flat=True)),
            {item_a.id, item_b.id})
        self.assertEqual(
            set(ledger_items.values_list('template_name_snapshot', flat=True)),
            {'模板A', '模板B'})

    def test_mixed_template_and_manual_items_same_system(self):
        """同系统模板明细与手动临时明细混合：手动项 is_temporary=True。"""
        template = make_ledger_template(
            self.user, name='混合模板', ledger_type='week_month', maintenance_cycle='week')
        tpl_item = make_template_item(template, self.user, name='模板项')
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system_a.id, [
                _tpl_item_payload(tpl_item),
                {'item_name': '临时加测项', 'input_type': 'text',
                 'value_text': '正常', 'result': 'normal'},
            ], template_id=template.id),
        ], created_from='template')
        data = create_ledger_ok(client, payload)
        ledger = OperationLedger.objects.get(pk=data['id'])
        template_item = ledger.items.get(template_item_id=tpl_item.id)
        manual_item = ledger.items.get(item_name_snapshot='临时加测项')
        self.assertFalse(template_item.is_temporary)
        self.assertTrue(manual_item.is_temporary)
        self.assertEqual(template_item.template_name_snapshot, '混合模板')
        self.assertEqual(manual_item.template_name_snapshot, '')
