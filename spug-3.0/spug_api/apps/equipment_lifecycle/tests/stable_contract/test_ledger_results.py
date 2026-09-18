# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：明细结果规则（提示词二十三 第 17-21 项）。"""
from django.test import TestCase

from apps.equipment_lifecycle.models import OperationLedgerItem
from apps.equipment_lifecycle.tests.base import make_client, make_system, make_type
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
        self.system_type = make_type(self.user)
        self.system = make_system(self.user, system_type=self.system_type)

    def test_batch_confirm_normal(self):
        """17. 正常项支持批量确认（独立动作接口，一次确认多条）。"""
        client = make_client(self.user)
        data = create_ledger_ok(client, ledger_payload(
            [entry_payload(self.system.id, [
                item_payload(item_name='项一', result='pending_review'),
                item_payload(item_name='项二', result='pending_review'),
                # 数值超限项：不允许通过批量确认改成正常
                item_payload(item_name='电压', input_type='number', value_number=99,
                             number_min=48, number_max=54, result='pending_review'),
            ])]))
        item_ids = [i['id'] for i in data['items']]
        resp = post_json(client, '%s/%s/confirm-normal/' % (LEDGER_URL, data['id']),
                         {'item_ids': item_ids})
        body = resp.json()
        self.assertFalse(body.get('error'))
        results = {i['item_name']: i['result'] for i in body['data']['items']}
        self.assertEqual(results['项一'], 'normal')
        self.assertEqual(results['项二'], 'normal')
        self.assertNotEqual(results['电压'], 'normal')

    def test_abnormal_requires_desc(self):
        """18. 异常项缺少异常说明时保存失败。"""
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system.id, [item_payload(result='abnormal', abnormal_desc='')])])
        resp = post_json(client, LEDGER_URL + '/', payload)
        self.assertTrue(resp.json().get('error'))
        self.assertIn('异常说明', resp.json()['error'])

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

    def test_number_range_auto_judgement(self):
        """20. 数值范围判定正确（范围内自动正常、超限自动异常）。"""
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system.id, [
                item_payload(item_name='电压正常', input_type='number', value_number=52,
                             number_min=48, number_max=54, value_text='', result=''),
                # 超限项自动判定异常：异常说明仍为必填
                item_payload(item_name='电压超限', input_type='number', value_number=60,
                             number_min=48, number_max=54, value_text='', result='',
                             abnormal_desc='超出上限'),
            ])])
        data = create_ledger_ok(client, payload)
        results = {i['item_name']: (i['result'], i['is_auto_judged']) for i in data['items']}
        self.assertEqual(results['电压正常'], ('normal', True))
        self.assertEqual(results['电压超限'], ('abnormal', True))

    def test_auto_judgement_correction_requires_reason(self):
        """21. 有权限用户修正自动判定时必须填写原因。"""
        client = make_client(self.user)
        # 自动判定为 normal，用户改为 abnormal 且未填原因 → 拒绝
        payload = ledger_payload([
            entry_payload(self.system.id, [
                item_payload(item_name='电压', input_type='number', value_number=52,
                             number_min=48, number_max=54, value_text='', result='abnormal')])])
        resp = post_json(client, LEDGER_URL + '/', payload)
        self.assertTrue(resp.json().get('error'))
        self.assertIn('修正原因', resp.json()['error'])
        # 填写原因后允许修正
        payload['entries'][0]['items'][0]['correction_reason'] = '现场电压表读数偏低'
        payload['entries'][0]['items'][0]['abnormal_desc'] = '波动异常'
        data = create_ledger_ok(client, payload)
        item = data['items'][0]
        self.assertEqual(item['result'], 'abnormal')
        self.assertFalse(item['is_auto_judged'])
        self.assertEqual(item['correction_reason'], '现场电压表读数偏低')
