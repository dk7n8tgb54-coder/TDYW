# -*- coding: utf-8 -*-
"""2026-09-19 设备全生命周期模块缺陷排查回归（稳定契约）。

本轮排查确认的四类后端缺陷及对应用例：
1. 台账三处列表接口分页切片错误：query[page-1: page*page_size] 少乘
   page_size，第 2 页起数据错乱且超出页长（LedgerView /
   LedgerAbnormalItemsView / SystemLedgerItemsView）；
2. 系统列表 health_status 筛选参数声明为 list，前端单选以标量字符串
   提交（axios 不做 JSON 编码），JsonParser 对字符串执行 json.loads
   必然失败，健康状态筛选永远报错；
3. 台账多选（multi_choice）填写值：前端 JSON.stringify 后提交字符串，
   validate_item_value 仅接受数组——非必填值被静默清空（创建与编辑）、
   必填项被误报"请选择候选项"；
4. 台账编辑 version 参数为非法字符串时 int() 抛 ValueError 未捕获，
   接口 500。

用例断言为期望正确行为：修复前运行应失败（证明缺陷存在），修复后
全部通过并作为发布门禁回归。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.models import OperationLedger
from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS,
    make_client,
    make_system,
    make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    LEDGER_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    put_json,
)

SYSTEM_URL = '/equipment-lifecycle/systems'
ABNORMAL_ITEMS_URL = LEDGER_URL + '/abnormal-items'


def make_abnormal_item(index):
    """手动判定为异常的明细（数值行）。"""
    return item_payload(
        item_name='电压测量%d' % index,
        input_type='number', value_text='', value_number=10,
        result='abnormal', abnormal_desc='电压超限')


class LedgerPaginationContractTests(TestCase):
    """缺陷 1：台账三处列表接口第 2 页起的分页偏移。"""

    def setUp(self):
        self.user = make_ledger_user('page_op')
        self.system = make_system(self.user)
        self.client = make_client(self.user)

    def _create_ledger(self, items, token):
        payload = ledger_payload(
            [entry_payload(self.system.id, items)], client_token=token)
        return create_ledger_ok(self.client, payload)

    def test_ledger_list_page2_offset(self):
        """台账列表第 2 页必须返回全局第 4-6 条（page_size=3）。"""
        ledger_ids = []
        for i in range(7):
            data = self._create_ledger(
                [item_payload(item_name='项目%d' % i)], 'tok-page-%d' % i)
            ledger_ids.append(data['id'])
        full = self.client.get(LEDGER_URL + '/', {'page': 1, 'page_size': 50}).json()
        all_ids = [row['id'] for row in full['data']['data']]
        self.assertEqual(len(all_ids), 7)

        resp = self.client.get(LEDGER_URL + '/', {'page': 2, 'page_size': 3})
        data = resp.json()['data']
        self.assertFalse(resp.json().get('error'))
        self.assertEqual(data['total'], 7)
        self.assertEqual(
            len(data['data']), 3, '第 2 页必须恰好返回 page_size 条记录')
        self.assertEqual(
            [row['id'] for row in data['data']], all_ids[3:6],
            '第 2 页必须返回全局第 4-6 条，不得与第 1 页重叠或错位')

    def test_system_ledger_items_page2_offset(self):
        """系统详情台账明细第 2 页偏移正确。"""
        self._create_ledger([make_abnormal_item(i) for i in range(7)], 'tok-sli')
        url = '%s/%d/ledger-items/' % (SYSTEM_URL, self.system.id)
        full = self.client.get(url, {'page': 1, 'page_size': 50}).json()
        all_ids = [row['id'] for row in full['data']['data']]
        self.assertEqual(len(all_ids), 7)

        resp = self.client.get(url, {'page': 2, 'page_size': 3})
        data = resp.json()['data']
        self.assertFalse(resp.json().get('error'))
        self.assertEqual(data['total'], 7)
        self.assertEqual(len(data['data']), 3)
        self.assertEqual([row['id'] for row in data['data']], all_ids[3:6])

    def test_abnormal_items_page2_offset(self):
        """异常明细查询第 2 页偏移正确。"""
        self._create_ledger([make_abnormal_item(i) for i in range(7)], 'tok-abn')
        full = self.client.get(ABNORMAL_ITEMS_URL + '/', {'page': 1, 'page_size': 50}).json()
        all_ids = [row['id'] for row in full['data']['data']]
        self.assertEqual(len(all_ids), 7)

        resp = self.client.get(ABNORMAL_ITEMS_URL + '/', {'page': 2, 'page_size': 3})
        data = resp.json()['data']
        self.assertFalse(resp.json().get('error'))
        self.assertEqual(data['total'], 7)
        self.assertEqual(len(data['data']), 3)
        self.assertEqual([row['id'] for row in data['data']], all_ids[3:6])


class SystemHealthStatusFilterContractTests(TestCase):
    """缺陷 2：系统列表 health_status 筛选必须接受前端标量字符串参数。

    前端单选提交 health_status=normal（普通字符串）；历史契约
    （test_list_filters）同时接受 JSON 数组字符串，两种形态都必须可用。
    """

    def setUp(self):
        self.user = make_user('filter_op', perms=ALL_SYSTEM_PERMS)
        self.client = make_client(self.user)
        self.normal_system = make_system(self.user)
        self.fault_system = make_system(
            self.user,
            system_code='SYS-FLT', name='故障系统', health_status='fault')

    def test_plain_string_filter(self):
        resp = self.client.get(SYSTEM_URL + '/', {'health_status': 'normal'})
        data = resp.json()
        self.assertFalse(data.get('error'), '标量字符串筛选不得报错: %s' % data.get('error'))
        self.assertEqual(data['data']['total'], 1)
        self.assertEqual(data['data']['data'][0]['id'], self.normal_system.id)

    def test_plain_string_filter_fault(self):
        resp = self.client.get(SYSTEM_URL + '/', {'health_status': 'fault'})
        data = resp.json()
        self.assertFalse(data.get('error'))
        self.assertEqual(data['data']['total'], 1)
        self.assertEqual(data['data']['data'][0]['id'], self.fault_system.id)

    def test_comma_separated_filter(self):
        resp = self.client.get(SYSTEM_URL + '/', {'health_status': 'normal,fault'})
        data = resp.json()
        self.assertFalse(data.get('error'))
        self.assertEqual(data['data']['total'], 2)

    def test_json_array_string_filter_still_supported(self):
        """历史契约：JSON 数组字符串（json.dumps 形态）继续可用。"""
        resp = self.client.get(SYSTEM_URL + '/', {'health_status': json.dumps(['fault'])})
        data = resp.json()
        self.assertFalse(data.get('error'))
        self.assertEqual(data['data']['total'], 1)
        self.assertEqual(data['data']['data'][0]['id'], self.fault_system.id)


class LedgerMultiChoiceContractTests(TestCase):
    """缺陷 3：多选填写值以 JSON 字符串提交（前端真实形态）必须可用。"""

    def setUp(self):
        self.user = make_ledger_user('mc_op')
        self.system = make_system(self.user)
        self.client = make_client(self.user)

    def test_create_with_json_string_value(self):
        """前端 JSON.stringify 形态：创建后值不得被清空。"""
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload(
                item_name='多选检查', input_type='multi_choice',
                choices=['A', 'B', 'C'], value_text='["A","B"]', result='normal')])],
            client_token='tok-mc-create')
        data = create_ledger_ok(self.client, payload)
        row = data['items'][0]
        self.assertEqual(
            json.loads(row['value_text']), ['A', 'B'],
            '多选填写值以 JSON 字符串提交时不得被清空')

    def test_create_required_with_json_string_value(self):
        """必填多选 + JSON 字符串值：不得误报"请选择候选项"。"""
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload(
                item_name='必填多选', input_type='multi_choice', is_required=True,
                choices=['A', 'B', 'C'], value_text='["A"]', result='normal')])],
            client_token='tok-mc-req')
        data = create_ledger_ok(self.client, payload)
        self.assertEqual(json.loads(data['items'][0]['value_text']), ['A'])

    def test_list_value_still_supported(self):
        """数组形态（历史测试写法）继续可用。"""
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload(
                item_name='多选检查', input_type='multi_choice',
                choices=['A', 'B', 'C'], value_text=['A', 'C'], result='normal')])],
            client_token='tok-mc-list')
        data = create_ledger_ok(self.client, payload)
        self.assertEqual(json.loads(data['items'][0]['value_text']), ['A', 'C'])

    def test_edit_with_json_string_value(self):
        """编辑草稿时多选值以 JSON 字符串提交：更新而非清空。"""
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload(
                item_name='多选检查', input_type='multi_choice',
                choices=['A', 'B', 'C'], value_text='["A","B"]', result='normal')])],
            client_token='tok-mc-edit')
        ledger = create_ledger_ok(self.client, payload)
        item_id = ledger['items'][0]['id']

        edit_payload = ledger_payload(
            [entry_payload(self.system.id, [
                {'id': item_id, 'value_text': '["B","C"]', 'result': 'normal'},
            ])],
            client_token='tok-mc-edit')
        edit_payload['version'] = ledger['version']
        resp = put_json(self.client, '%s/%d/' % (LEDGER_URL, ledger['id']), edit_payload)
        data = resp.json()
        self.assertFalse(data.get('error'), '编辑多选值失败: %s' % data.get('error'))
        row = [r for r in data['data']['items'] if r['id'] == item_id][0]
        self.assertEqual(json.loads(row['value_text']), ['B', 'C'])


class LedgerVersionParamContractTests(TestCase):
    """缺陷 4：台账编辑 version 参数非法字符串必须返回业务错误而非 500。"""

    def setUp(self):
        self.user = make_ledger_user('ver_op')
        self.system = make_system(self.user)
        self.client = make_client(self.user)
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload()])], client_token='tok-ver')
        self.ledger = create_ledger_ok(self.client, payload)

    def test_invalid_version_returns_business_error(self):
        edit_payload = ledger_payload(
            [entry_payload(self.system.id, [
                {'id': self.ledger['items'][0]['id'], 'value_text': '更新值',
                 'result': 'normal'},
            ])],
            client_token='tok-ver')
        edit_payload['version'] = 'not-a-number'
        resp = put_json(
            self.client, '%s/%d/' % (LEDGER_URL, self.ledger['id']), edit_payload)
        self.assertEqual(resp.status_code, 200, '非法 version 不得触发 500')
        data = resp.json()
        self.assertTrue(data.get('error'), '非法 version 必须返回业务错误')
        # 台账未被修改
        ledger = OperationLedger.objects.get(pk=self.ledger['id'])
        self.assertEqual(ledger.version, 1)
        self.assertEqual(ledger.items.first().value_text, '正常')

    def test_version_mismatch_still_rejected(self):
        """并发版本校验行为保持：版本不一致拒绝保存。"""
        edit_payload = ledger_payload(
            [entry_payload(self.system.id, [
                {'id': self.ledger['items'][0]['id'], 'value_text': '更新值',
                 'result': 'normal'},
            ])],
            client_token='tok-ver')
        edit_payload['version'] = 999
        resp = put_json(
            self.client, '%s/%d/' % (LEDGER_URL, self.ledger['id']), edit_payload)
        self.assertIn('已被他人修改', resp.json().get('error') or '')

    def test_valid_version_still_saves(self):
        """正常 version 继续可编辑并递增版本号。"""
        edit_payload = ledger_payload(
            [entry_payload(self.system.id, [
                {'id': self.ledger['items'][0]['id'], 'value_text': '更新值',
                 'result': 'normal'},
            ])],
            client_token='tok-ver')
        edit_payload['version'] = self.ledger['version']
        resp = put_json(
            self.client, '%s/%d/' % (LEDGER_URL, self.ledger['id']), edit_payload)
        data = resp.json()
        self.assertFalse(data.get('error'))
        self.assertEqual(data['data']['version'], self.ledger['version'] + 1)


