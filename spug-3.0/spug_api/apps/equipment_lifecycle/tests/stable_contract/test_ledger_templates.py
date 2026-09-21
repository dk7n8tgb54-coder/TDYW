# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：台账模板与快照（提示词二十三 第 5-8、15-16 项）。"""
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

    def _make_inspection_template(self, **kw):
        template = make_ledger_template(
            self.user, ledger_type='inspection', applicable_systems=[self.system], **kw)
        item = make_template_item(template, self.user, standard='指示灯常亮绿色')
        return template, item

    def test_inspection_template_only_generates_inspection_ledger(self):
        """5. 巡检模板只能生成巡检台账。"""
        template, tpl_item = self._make_inspection_template()
        client = make_client(self.user)
        # 用巡检模板生成周月维护台账 → 拒绝
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            ledger_type='week_month', maintenance_cycle='week', created_from='template')
        resp = post_json(client, LEDGER_URL + '/', payload)
        self.assertTrue(resp.json().get('error'))
        # 用巡检模板生成季维护台账 → 拒绝
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            ledger_type='seasonal', maintenance_cycle='season', created_from='template')
        self.assertTrue(post_json(client, LEDGER_URL + '/', payload).json().get('error'))

    def test_week_month_template_filters_items_by_cycle(self):
        """6. 周月维护模板正确区分周、月和周月均执行项目。"""
        template = make_ledger_template(
            self.user, ledger_type='week_month',
            maintenance_cycle='week', name='周月维护模板', template_code='TPL-WM-001',
            applicable_systems=[self.system])
        make_template_item(
            template, self.user, item_code='WK-1', name='仅每周项',
            execution_scope='week_only')
        make_template_item(
            template, self.user, item_code='MO-1', name='仅每月项',
            execution_scope='month_only')
        both = make_template_item(
            template, self.user, item_code='BM-1', name='周月均执行项',
            execution_scope='all')
        client = make_client(self.user)
        # 周台账：只加载 all + week_only（须传模板项目 ID，仅周期匹配项目被快照）
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(both)], template_id=template.id)],
            ledger_type='week_month', maintenance_cycle='week', created_from='template')
        # 同时提交仅每月项 → 与周周期不匹配，整体拒绝
        bad = ledger_payload(
            [entry_payload(self.system.id, [
                _tpl_item_payload(both), _tpl_item_payload(make_template_item(
                    template, self.user, item_code='MO-1b', name='仅每月项B',
                    execution_scope='month_only'))], template_id=template.id)],
            ledger_type='week_month', maintenance_cycle='week', created_from='template')
        self.assertTrue(post_json(client, LEDGER_URL + '/', bad).json().get('error'))
        data = create_ledger_ok(client, payload)
        names = [i['item_name'] for i in data['items']]
        self.assertEqual(names, ['周月均执行项'])
        # 月台账：需要月周期模板，只加载 month_only 项目
        template_m = make_ledger_template(
            self.user, ledger_type='week_month',
            maintenance_cycle='month', name='月度维护模板', template_code='TPL-WM-002',
            applicable_systems=[self.system])
        month_item_m = make_template_item(template_m, self.user, item_code='MO-2', name='月检项目',
                                          execution_scope='month_only')
        make_template_item(template_m, self.user, item_code='WK-2', name='周检项目',
                           execution_scope='week_only')
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(month_item_m)], template_id=template_m.id)],
            ledger_type='week_month', maintenance_cycle='month', created_from='template')
        data = create_ledger_ok(client, payload)
        names = [i['item_name'] for i in data['items']]
        self.assertEqual(names, ['月检项目'])

    def test_seasonal_template_only_generates_seasonal_ledger(self):
        """7. 季维护模板只能生成季维护台账。"""
        template = make_ledger_template(
            self.user, ledger_type='seasonal',
            name='季维护模板', template_code='TPL-SE-001',
            applicable_systems=[self.system])
        tpl_item = make_template_item(template, self.user)
        client = make_client(self.user)
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            ledger_type='inspection', maintenance_cycle='', created_from='template')
        self.assertTrue(post_json(client, LEDGER_URL + '/', payload).json().get('error'))
        # 正确生成季维护台账
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            ledger_type='seasonal', maintenance_cycle='season', created_from='template')
        data = create_ledger_ok(client, payload)
        self.assertEqual(data['ledger_type'], 'seasonal')
        self.assertEqual(data['items'][0]['template_name'], '季维护模板')

    def test_quarter_maintenance_is_not_official_type(self):
        """8. “季度维护”不作为正式台账类型（非法类型被拒绝）。"""
        client = make_client(self.user)
        for bad in ('quarter', '季度维护', 'quarterly'):
            payload = ledger_payload(
                [entry_payload(self.system.id, [item_payload()])], ledger_type=bad)
            resp = post_json(client, LEDGER_URL + '/', payload)
            self.assertTrue(resp.json().get('error'), bad)
        self.assertNotIn('quarter', LEDGER_TYPE_VALUES)
        self.assertNotIn('季度维护', LEDGER_TYPE_VALUES)
        # 季维护正式类型存在
        self.assertIn('seasonal', LEDGER_TYPE_VALUES)

    def test_template_change_does_not_affect_generated_ledger(self):
        """15. 模板修改不影响已生成台账。"""
        template, tpl_item = self._make_inspection_template()
        client = make_client(self.user)
        payload = ledger_payload(
            [entry_payload(self.system.id, [_tpl_item_payload(tpl_item)], template_id=template.id)],
            created_from='template')
        data = create_ledger_ok(client, payload)
        old_standard = data['items'][0]['standard']
        # 修改模板项目标准与名称
        tpl_item.standard = '已变更标准文本'
        tpl_item.name = '已变更项目名'
        tpl_item.save()
        item = OperationLedgerItem.objects.get(ledger_id=data['id'])
        self.assertEqual(item.standard_snapshot, old_standard)
        self.assertNotEqual(item.standard_snapshot, '已变更标准文本')
        self.assertNotEqual(item.item_name_snapshot, '已变更项目名')

    def test_template_item_deactivate_keeps_history(self):
        """16. 模板项目停用不删除历史台账明细。"""
        template, tpl_item = self._make_inspection_template()
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
        self.assertEqual(item.standard_snapshot, '指示灯常亮绿色')
        self.assertIsNone(item.template_item_id)

    def test_template_cycle_combo_validated(self):
        """周月维护模板周期必须为周或月；季维护模板固定季（模板层校验）。"""
        client = make_client(self.user)
        resp = post_json(client, TEMPLATE_URL + '/', {
            'name': '非法周期模板', 'template_code': 'TPL-BAD-1',
            'ledger_type': 'week_month', 'maintenance_cycle': 'season',
            'applicable_systems': [self.system.id]})
        self.assertTrue(resp.json().get('error'))
        resp = post_json(client, TEMPLATE_URL + '/', {
            'name': '非法季模板', 'template_code': 'TPL-BAD-2',
            'ledger_type': 'seasonal', 'maintenance_cycle': 'week',
            'applicable_systems': [self.system.id]})
        self.assertTrue(resp.json().get('error'))

    def test_template_requires_applicable_systems(self):
        """模板头校验只认 applicable_systems：未选择适用系统被拒。"""
        client = make_client(self.user)
        resp = post_json(client, TEMPLATE_URL + '/', {
            'name': '无适用系统模板', 'template_code': 'TPL-BAD-3',
            'ledger_type': 'inspection', 'maintenance_cycle': ''})
        self.assertEqual(resp.json().get('error'), '请选择适用系统')
        self.assertFalse(
            OperationLedgerTemplate.objects.filter(template_code='TPL-BAD-3').exists())
        # 传不存在的系统 ID 同样被拒
        resp = post_json(client, TEMPLATE_URL + '/', {
            'name': '幽灵系统模板', 'template_code': 'TPL-BAD-4',
            'ledger_type': 'inspection', 'maintenance_cycle': '',
            'applicable_systems': [999999]})
        self.assertEqual(resp.json().get('error'), '适用系统不存在或无权限访问')


class LedgerTemplateAvailableContractTests(TestCase):
    """available 接口：system 参数可选，缺省时返回全部模板并附适用系统。"""

    def setUp(self):
        self.user = make_ledger_user('avail_op')
        self.system_a = make_system(self.user, system_code='SYS-A', name='通信系统A')
        self.system_b = make_system(self.user, system_code='SYS-B', name='通信系统B')
        self.template_a = make_ledger_template(
            self.user, name='A专用模板', template_code='TPL-AV-1',
            applicable_systems=[self.system_a])
        self.template_ab = make_ledger_template(
            self.user, name='全科模板', template_code='TPL-AV-2',
            applicable_systems=[self.system_a, self.system_b])
        make_ledger_template(
            self.user, name='停用模板', template_code='TPL-AV-3',
            applicable_systems=[self.system_a], is_active=False)

    def _get_available(self, query=''):
        client = make_client(self.user)
        return client.get(TEMPLATE_URL + '/available/?ledger_type=inspection' + query)

    def test_available_without_system_returns_all_with_applicable_systems(self):
        """不带 system：返回该类型全部启用模板，每个附 applicable_systems。"""
        resp = self._get_available()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']['data']
        codes = {t['template_code'] for t in data}
        self.assertEqual(codes, {'TPL-AV-1', 'TPL-AV-2'})
        by_code = {t['template_code']: t for t in data}
        self.assertEqual(
            {s['id'] for s in by_code['TPL-AV-2']['applicable_systems']},
            {self.system_a.id, self.system_b.id})
        self.assertEqual(
            {s['id'] for s in by_code['TPL-AV-1']['applicable_systems']},
            {self.system_a.id})
        # 每个适用系统带编号/名称，供前端展示"适用 N 套"
        first = by_code['TPL-AV-2']['applicable_systems'][0]
        self.assertIn('system_code', first)
        self.assertIn('name', first)

    def test_available_with_system_filters_as_before(self):
        """带 system：只返回适用于该系统的模板（原有行为不变）。"""
        resp = self._get_available('&system=%s' % self.system_a.id)
        codes = {t['template_code'] for t in resp.json()['data']['data']}
        self.assertEqual(codes, {'TPL-AV-1', 'TPL-AV-2'})
        resp = self._get_available('&system=%s' % self.system_b.id)
        codes = {t['template_code'] for t in resp.json()['data']['data']}
        self.assertEqual(codes, {'TPL-AV-2'})
        # 不存在的系统仍报错
        resp = self._get_available('&system=999999')
        self.assertEqual(resp.json().get('error'), '系统不存在')

    def test_available_week_month_items_count_respects_scope(self):
        """周月维护模板 items_count 按周期 scope 过滤。"""
        template = make_ledger_template(
            self.user, ledger_type='week_month', maintenance_cycle='week',
            name='周月模板', template_code='TPL-AV-4',
            applicable_systems=[self.system_a, self.system_b])
        make_template_item(
            template, self.user, item_code='WK-1', name='仅每周项', execution_scope='week_only')
        make_template_item(
            template, self.user, item_code='MO-1', name='仅每月项', execution_scope='month_only')
        make_template_item(
            template, self.user, item_code='BM-1', name='周月均执行项', execution_scope='all')
        client = make_client(self.user)
        resp = client.get(
            TEMPLATE_URL + '/available/?ledger_type=week_month&maintenance_cycle=week')
        by_code = {t['template_code']: t for t in resp.json()['data']['data']}
        self.assertEqual(by_code['TPL-AV-4']['items_count'], 2)
        resp = client.get(
            TEMPLATE_URL + '/available/?ledger_type=week_month&maintenance_cycle=month')
        by_code = {t['template_code']: t for t in resp.json()['data']['data']}
        self.assertEqual(by_code['TPL-AV-4']['items_count'], 2)
