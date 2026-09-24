# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：状态流转、幂等与并发（提示词二十三 第 25-28、31-32 项）。"""
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_REVIEWED,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_SUBMITTED,
    LEDGER_STATUS_VOID,
    OperationLedger,
    OperationLedgerCorrection,
    OperationLedgerItem,
)
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


class LedgerWorkflowContractTests(TestCase):
    def setUp(self):
        self.user = make_ledger_user('flow_op')
        self.system = make_system(self.user)
        self.client_ = make_client(self.user)
        self.ledger = create_ledger_ok(self.client_, ledger_payload(
            [entry_payload(self.system.id, [item_payload()])],
            client_token='token-flow-1'))

    def _submit(self):
        resp = post_json(self.client_, '%s/%s/submit/' % (LEDGER_URL, self.ledger['id']), {})
        self.assertFalse(resp.json().get('error'))
        return resp.json()['data']

    def test_submitted_ledger_not_editable_by_filler(self):
        """25. 已提交台账不能由普通填写人直接修改。"""
        data = self._submit()
        self.assertEqual(data['status'], LEDGER_STATUS_SUBMITTED)
        payload = ledger_payload([entry_payload(self.system.id, [item_payload(item_name='试图修改')])],
                                 version=data['version'])
        resp = put_json(self.client_, '%s/%s/' % (LEDGER_URL, self.ledger['id']), payload)
        self.assertTrue(resp.json().get('error'))
        item = OperationLedgerItem.objects.filter(ledger_id=self.ledger['id']).first()
        self.assertNotEqual(item.item_name_snapshot, '试图修改')

    def test_return_requires_reason(self):
        """26. 退回必须填写原因。"""
        self._submit()
        resp = post_json(self.client_, '%s/%s/return/' % (LEDGER_URL, self.ledger['id']), {})
        self.assertTrue(resp.json().get('error'))
        resp = post_json(self.client_, '%s/%s/return/' % (LEDGER_URL, self.ledger['id']),
                         {'reason': '第三项数据存疑'})
        data = resp.json()['data']
        self.assertEqual(data['status'], LEDGER_STATUS_RETURNED)
        self.assertEqual(data['return_reason'], '第三项数据存疑')
        # 退回后可重新提交
        resp = post_json(self.client_, '%s/%s/submit/' % (LEDGER_URL, self.ledger['id']), {})
        self.assertEqual(resp.json()['data']['status'], LEDGER_STATUS_SUBMITTED)

    def test_reviewed_ledger_no_silent_modification(self):
        """27. 已复核台账不能静默修改；更正必须保存原因与前后值。"""
        self._submit()
        resp = post_json(self.client_, '%s/%s/review/' % (LEDGER_URL, self.ledger['id']), {})
        self.assertFalse(resp.json().get('error'))
        self.assertEqual(resp.json()['data']['status'], LEDGER_STATUS_REVIEWED)
        # PUT 编辑被拒绝
        payload = ledger_payload([entry_payload(self.system.id, [item_payload()])])
        self.assertTrue(put_json(
            self.client_, '%s/%s/' % (LEDGER_URL, self.ledger['id']), payload).json().get('error'))
        # 更正缺少原因被拒绝
        item = OperationLedgerItem.objects.filter(ledger_id=self.ledger['id']).first()
        resp = post_json(self.client_, '%s/%s/correct/' % (LEDGER_URL, self.ledger['id']),
                         {'item_id': item.id, 'result': 'abnormal', 'abnormal_desc': 'x'})
        self.assertTrue(resp.json().get('error'))
        # 带原因更正：保存前后值
        resp = post_json(self.client_, '%s/%s/correct/' % (LEDGER_URL, self.ledger['id']),
                         {'item_id': item.id, 'result': 'abnormal',
                          'abnormal_desc': '复核发现数据录入有误',
                          'reason': '复核更正'})
        self.assertFalse(resp.json().get('error'))
        correction = OperationLedgerCorrection.objects.filter(ledger_id=self.ledger['id']).first()
        self.assertIsNotNone(correction)
        self.assertEqual(correction.reason, '复核更正')
        changes = {c['field']: c for c in correction.get_corrections()}
        self.assertIn('result', changes)
        self.assertEqual(changes['result']['old'], 'normal')
        self.assertEqual(changes['result']['new'], 'abnormal')
        item.refresh_from_db()
        self.assertEqual(item.result, 'abnormal')

    def test_void_is_controlled_not_physical_delete(self):
        """28. 作废不执行物理删除（受控终态）。"""
        self._submit()
        resp = post_json(self.client_, '%s/%s/void/' % (LEDGER_URL, self.ledger['id']),
                         {'reason': '录入对象错误'})
        data = resp.json()['data']
        self.assertEqual(data['status'], LEDGER_STATUS_VOID)
        self.assertTrue(OperationLedger.objects.filter(pk=self.ledger['id']).exists())
        self.assertTrue(OperationLedgerItem.objects.filter(ledger_id=self.ledger['id']).exists())
        # 已作废不能再流转
        resp = post_json(self.client_, '%s/%s/submit/' % (LEDGER_URL, self.ledger['id']), {})
        self.assertTrue(resp.json().get('error'))

    def test_duplicate_request_creates_single_ledger(self):
        """31. 重复请求不会创建重复台账（client_token 幂等）。"""
        payload = ledger_payload(
            [entry_payload(self.system.id, [item_payload()])], client_token='idem-123')
        before = OperationLedger.objects.count()
        first = create_ledger_ok(self.client_, dict(payload))
        second = create_ledger_ok(self.client_, dict(payload))
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(OperationLedger.objects.count(), before + 1)

    def test_concurrent_edit_conflict_detected(self):
        """32. 并发编辑不会静默覆盖（version 冲突返回明确错误）。"""
        ledger_id = self.ledger['id']
        payload = ledger_payload([entry_payload(self.system.id, [item_payload(item_name='甲的修改')])],
                                 version=self.ledger['version'])
        resp = put_json(self.client_, '%s/%s/' % (LEDGER_URL, ledger_id), payload)
        self.assertFalse(resp.json().get('error'))
        new_version = resp.json()['data']['version']
        # 乙拿着旧 version 提交 → 冲突
        stale = ledger_payload([entry_payload(self.system.id, [item_payload(item_name='乙的覆盖')])],
                               version=self.ledger['version'])
        resp = put_json(self.client_, '%s/%s/' % (LEDGER_URL, ledger_id), stale)
        self.assertTrue(resp.json().get('error'))
        self.assertIn('已被他人修改', resp.json()['error'])
        item = OperationLedgerItem.objects.filter(ledger_id=ledger_id).first()
        self.assertEqual(item.item_name_snapshot, '甲的修改')
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).version, new_version)

    def test_review_permission_required(self):
        """复核/退回动作必须持有 review 权限（后端独立校验）。"""
        filler = make_ledger_user('plain_filler', perms=['equipment_lifecycle.ledger.view'])
        self._submit()
        client = make_client(filler)
        resp = post_json(client, '%s/%s/review/' % (LEDGER_URL, self.ledger['id']), {})
        self.assertTrue(resp.json().get('error'))
        ledger = OperationLedger.objects.get(pk=self.ledger['id'])
        self.assertEqual(ledger.status, LEDGER_STATUS_SUBMITTED)
