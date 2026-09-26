# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：台账模板与快照（提示词二十三 第 5-8、15-16 项）。

2026-09-22 简化：模板不再声明适用系统，模板项目不再有 standard/normal_range/
number_min/number_max 字段，新建项目默认必填。
"""
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LEDGER_TYPE_VALUES,
    OperationLedgerItem,
    OperationLedgerTemplate,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    ALL_TEMPLATE_PERMS,
    LEDGER_URL,
    TEMPLATE_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    make_template_item,
    make_ledger_template,
    post_json,
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
            'items': [{'name': '指示灯检查', 'input_type': 'text'}]})
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
