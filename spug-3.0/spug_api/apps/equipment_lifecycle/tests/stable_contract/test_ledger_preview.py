# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：台账预览——模板先行展开、显式优先与租户边界。

preview_entries 条目两种形态：
- {system_id, template_id?}：显式指定系统（原有行为不变）；
- {template_id}：只选模板，按模板适用系统展开（用户可见且未停用，
  排除显式条目已包含的系统）。
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


def _preview_body(entries, ledger_type='inspection', maintenance_cycle=''):
    return {
        'ledger_type': ledger_type,
        'maintenance_cycle': maintenance_cycle,
        'entries': entries,
    }


class LedgerPreviewExpandContractTests(TestCase):
    def setUp(self):
        self.user = make_ledger_user('preview_op')
        self.system_a = make_system(self.user, system_code='SYS-A', name='通信系统A')
        self.system_b = make_system(self.user, system_code='SYS-B', name='通信系统B')

    def _make_template(self, systems, **kw):
        template = make_ledger_template(self.user, applicable_systems=systems, **kw)
        item = make_template_item(template, self.user)
        return template, item

    def test_preview_expands_template_only_entry_to_all_applicable_systems(self):
        """只选模板不选系统：按适用系统展开为多个系统条目，明细按系统归位。"""
        template, tpl_item = self._make_template([self.system_a, self.system_b])
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body([{'template_id': template.id}]))
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        entries = data['data']['data']
        self.assertEqual({e['system']['id'] for e in entries},
                         {self.system_a.id, self.system_b.id})
        for entry in entries:
            self.assertEqual(entry['template']['id'], template.id)
            self.assertEqual(entry['template']['name'], template.name)
            self.assertEqual(len(entry['items']), 1)
            item = entry['items'][0]
            self.assertEqual(item['id'], tpl_item.id)
            self.assertTrue(item['client_key'].startswith('%s-' % entry['system']['id']))
        # 展开顺序按系统编号稳定排序
        self.assertEqual([e['system']['system_code'] for e in entries], ['SYS-A', 'SYS-B'])

    def test_preview_expansion_excludes_explicitly_listed_systems(self):
        """显式条目优先：模板展开自动排除已在显式条目中指定的系统。"""
        template_all, item_all = self._make_template(
            [self.system_a, self.system_b], name='全科模板', template_code='TPL-ALL-1')
        template_a, item_a = self._make_template(
            [self.system_a], name='A专用模板', template_code='TPL-A-1')
        client = make_client(self.user)
        entries = [
            {'system_id': self.system_a.id, 'template_id': template_a.id},
            {'template_id': template_all.id},
        ]
        resp = post_json(client, PREVIEW_URL, _preview_body(entries))
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        by_system = {e['system']['id']: e['template']['id'] for e in data['data']['data']}
        self.assertEqual(by_system, {
            self.system_a.id: template_a.id,
            self.system_b.id: template_all.id,
        })

    def test_preview_expansion_skips_inactive_and_invisible_systems(self):
        """展开时跳过停用系统与跨租户系统，只保留当前用户可见且启用的系统。"""
        other_user = make_user('other_owner', tenant_id='other')
        system_inactive = make_system(
            self.user, system_code='SYS-C', name='停用系统', is_active=False)
        system_other = make_system(
            other_user, system_code='SYS-D', name='他租户系统', tenant_id='other')
        template, _ = self._make_template(
            [self.system_a, system_inactive, system_other])
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body([{'template_id': template.id}]))
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        self.assertEqual(
            {e['system']['id'] for e in data['data']['data']}, {self.system_a.id})

    def test_preview_template_without_available_systems_rejected(self):
        """模板无可用适用系统（未绑定或全部停用）→ 明确报错。"""
        template_none, _ = self._make_template(None)
        template_inactive, _ = self._make_template(None, name='模板B', template_code='TPL-INS-002')
        template_inactive.applicable_systems.set([make_system(
            self.user, system_code='SYS-E', name='停用系统E', is_active=False)])
        client = make_client(self.user)
        for template in (template_none, template_inactive):
            resp = post_json(
                client, PREVIEW_URL, _preview_body([{'template_id': template.id}]))
            data = resp.json()
            self.assertEqual(
                data.get('error'), '模板未包含可用的适用系统：%s' % template.name)

    def test_preview_rejects_cross_tenant_template(self):
        """跨租户模板 ID 一律视为不存在（租户过滤）。"""
        other_user = make_user('other_owner2', tenant_id='other')
        other_template = make_ledger_template(
            other_user, tenant_id='other', template_code='TPL-OTHER-1')
        client = make_client(self.user)
        resp = post_json(
            client, PREVIEW_URL, _preview_body([{'template_id': other_template.id}]))
        self.assertEqual(resp.json().get('error'), '台账模板不存在')

    def test_preview_rejects_entry_without_system_and_template(self):
        """既无 system_id 也无 template_id 的条目被拒绝。"""
        client = make_client(self.user)
        for entries in ([{}], ['not-a-dict']):
            resp = post_json(client, PREVIEW_URL, _preview_body(entries))
            self.assertEqual(resp.json().get('error'), '台账系统条目格式不正确', entries)

    def test_preview_template_only_respects_week_month_cycle(self):
        """周月维护模板先行展开：按周期过滤项目，周期不匹配被拒。"""
        template = make_ledger_template(
            self.user, ledger_type='week_month', maintenance_cycle='week',
            name='周维护模板', template_code='TPL-WM-P1',
            applicable_systems=[self.system_a, self.system_b])
        week_item = make_template_item(
            template, self.user, item_code='WK-1', name='仅每周项', execution_scope='week_only')
        month_item = make_template_item(
            template, self.user, item_code='MO-1', name='仅每月项', execution_scope='month_only')
        both_item = make_template_item(
            template, self.user, item_code='BM-1', name='周月均执行项', execution_scope='all')
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body(
            [{'template_id': template.id}],
            ledger_type='week_month', maintenance_cycle='week'))
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        for entry in data['data']['data']:
            names = {i['name'] for i in entry['items']}
            self.assertEqual(names, {'仅每周项', '周月均执行项'})
        # 周期与模板不一致 → 拒绝
        resp = post_json(client, PREVIEW_URL, _preview_body(
            [{'template_id': template.id}],
            ledger_type='week_month', maintenance_cycle='month'))
        self.assertIn('周期不一致', resp.json().get('error') or '')

    def test_preview_dedupes_repeated_template_entries(self):
        """同一模板条目重复出现只展开一次。"""
        template, _ = self._make_template([self.system_a, self.system_b])
        client = make_client(self.user)
        resp = post_json(client, PREVIEW_URL, _preview_body([
            {'template_id': template.id}, {'template_id': template.id}]))
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        self.assertEqual(len(data['data']['data']), 2)

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
            self.user, name='模板A', template_code='TPL-PA-1',
            applicable_systems=[self.system_a])
        item_a = make_template_item(template_a, self.user, name='模板A项目')
        template_b = make_ledger_template(
            self.user, name='模板B', template_code='TPL-PB-1',
            applicable_systems=[self.system_a])
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
            self.user, name='混合模板', template_code='TPL-MIX-1',
            applicable_systems=[self.system_a])
        tpl_item = make_template_item(template, self.user, name='模板项')
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system_a.id, [
                _tpl_item_payload(tpl_item),
                {'item_name': '临时加测项', 'standard': '', 'input_type': 'text',
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
