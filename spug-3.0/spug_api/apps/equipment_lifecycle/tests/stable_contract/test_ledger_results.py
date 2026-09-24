# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：明细结果规则（提示词二十三 第 17-21 项）。

2026-09-22 简化：数值上下限与自动判定已移除；随后结果列从录入界面移除，
结果不再强制选择（未提交时按填写值派生：单选"不正常"记 abnormal，
其余 normal），异常说明改为选填。
"""
from django.test import TestCase

from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    LEDGER_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    post_json,
    put_json,
)


class LedgerResultContractTests(TestCase):
    def setUp(self):
        self.user = make_ledger_user('result_op')
        self.system = make_system(self.user)

    def test_batch_confirm_normal(self):
        """17. 正常项支持批量确认（独立动作接口，一次确认多条）。"""
        client = make_client(self.user)
        data = create_ledger_ok(client, ledger_payload(
            [entry_payload(self.system.id, [
                item_payload(item_name='项一', result='pending_review'),
                item_payload(item_name='项二', result='pending_review'),
                # 已确认异常且填说明的明细：不通过批量确认改成正常
                item_payload(item_name='项三', result='abnormal', abnormal_desc='电压偏低'),
            ])]))
        item_ids = [i['id'] for i in data['items']]
        resp = post_json(client, '%s/%s/confirm-normal/' % (LEDGER_URL, data['id']),
                         {'item_ids': item_ids})
        body = resp.json()
        self.assertFalse(body.get('error'))
        results = {i['item_name']: i['result'] for i in body['data']['items']}
        self.assertEqual(results['项一'], 'normal')
        self.assertEqual(results['项二'], 'normal')
        self.assertEqual(results['项三'], 'abnormal')

    def test_abnormal_desc_optional(self):
        """18. 异常说明改为选填：异常项不带说明可正常创建。"""
        client = make_client(self.user)
        data = create_ledger_ok(client, ledger_payload([
            entry_payload(self.system.id, [
                item_payload(item_name='电源电压测量', input_type='number', value_text='',
                             value_number=52, result='abnormal', abnormal_desc='')])]))
        item = data['items'][0]
        self.assertEqual(item['result'], 'abnormal')
        self.assertEqual(item['abnormal_desc'], '')

    def test_not_applicable_allows_reason(self):
        """19. 不适用项可以填写原因。"""
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system.id, [
                item_payload(result='not_applicable', value_text='', na_reason='当日停机检修')])])
        data = create_ledger_ok(client, payload)
        item = data['items'][0]
        self.assertEqual(item['result'], 'not_applicable')
        self.assertEqual(item['na_reason'], '当日停机检修')

    def test_result_derived_from_value(self):
        """20. 结果不再强制选择：未提交时按填写值派生——
        正常/不正常单选填"不正常"记 abnormal，其余一律 normal。"""
        client = make_client(self.user)
        data = create_ledger_ok(client, ledger_payload([
            entry_payload(self.system.id, [
                item_payload(item_name='外观检查', input_type='choice',
                             value_text='不正常', choices=['正常', '不正常'], result=''),
                item_payload(item_name='温度抄录', input_type='text',
                             value_text='25.6', result=''),
            ])]))
        by_name = {i['item_name']: i for i in data['items']}
        self.assertEqual(by_name['外观检查']['result'], 'abnormal')
        self.assertEqual(by_name['温度抄录']['result'], 'normal')

    def test_edit_without_result_keeps_existing(self):
        """20a. 编辑不提交结果且填写值未变时保留原结果与说明（结果列已移除）。"""
        client = make_client(self.user)
        data = create_ledger_ok(client, ledger_payload([
            entry_payload(self.system.id, [
                item_payload(item_name='电源电压测量', input_type='number', value_text='',
                             value_number=52, result='abnormal', abnormal_desc='电压偏低')])]))
        item = data['items'][0]
        payload = ledger_payload([
            entry_payload(self.system.id, [{
                'id': item['id'],
                'item_name': '电源电压测量',
                'input_type': 'number',
                'value_text': '',
                'value_number': 52,
            }])])
        payload['version'] = data['version']
        resp = put_json(client, '%s/%s/' % (LEDGER_URL, data['id']), payload)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        edited = body['data']['items'][0]
        self.assertEqual(edited['result'], 'abnormal')
        self.assertEqual(edited['abnormal_desc'], '电压偏低')

    def test_free_text_numeric_value_stored(self):
        """21. 数字/文本行纯数字填写值落 value_number（仅存储，无判定）。"""
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system.id, [
                item_payload(item_name='温度', input_type='text', value_text='25.6',
                             value_number=25.6, result='normal'),
                item_payload(item_name='外观描述', input_type='text',
                             value_text='机柜清洁无渗油', result='normal'),
            ])])
        data = create_ledger_ok(client, payload)
        by_name = {i['item_name']: i for i in data['items']}
        self.assertEqual(by_name['温度']['value_number'], 25.6)
        self.assertEqual(by_name['温度']['value_text'], '25.6')
        self.assertIsNone(by_name['外观描述']['value_number'])
        self.assertNotIn('is_auto_judged', by_name['温度'])
