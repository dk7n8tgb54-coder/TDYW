# -*- coding: utf-8 -*-
"""费用字段文本化稳定契约测试（fee_amount: Decimal → 自由文本）。

覆盖任务规约 十一 后端稳定契约 1-16 项：数字/文本输入兼容、strip 归一化、
长度上限、无费用强制清空、局部编辑完整状态校验、负数限制退役、数据库约束。
租户隔离、权限与审计行为由 test_permission_tenant.py / test_audit_async.py 覆盖。
"""
from django.db import IntegrityError, transaction

from apps.contract_agreement.models import ContractAgreement
from .base import ContractTestCase, make_agreement


class FeeTextCreateTest(ContractTestCase):
    """创建：费用内容兼容数字与自由文本"""

    def test_numeric_string_saved_as_is(self):
        """1. 有费用合同可以保存纯数字字符串"""
        body = self.create_via_api(
            contract_name='纯数字费用', has_fee=True, fee_amount='12000')
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=body['data']['id'])
        self.assertEqual(obj.fee_amount, '12000')
        self.assertEqual(body['data']['fee_amount'], '12000')

    def test_chinese_description_saved(self):
        """2. 有费用合同可以保存中文费用说明"""
        body = self.create_via_api(
            contract_name='中文费用', has_fee=True, fee_amount='约30万元')
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '约30万元')

    def test_json_number_input_compat(self):
        """3. JSON 数字输入可以兼容并保存为字符串（十进制，无科学计数法）"""
        body = self.create_via_api(
            contract_name='数字输入-整数', has_fee=True, fee_amount=12000)
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '12000')

        body = self.create_via_api(
            contract_name='数字输入-小数', has_fee=True, fee_amount=8888.66)
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '8888.66')

        body = self.create_via_api(
            contract_name='数字输入-大数', has_fee=True, fee_amount=1000000000000)
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '1000000000000')

    def test_text_with_unit_preserved(self):
        """4. 「12000元/年」可以保存并原样返回"""
        body = self.create_via_api(
            contract_name='带单位费用', has_fee=True, fee_amount='12000元/年')
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '12000元/年')

    def test_settlement_text_preserved(self):
        """5. 「按实际使用量结算」可以保存并原样返回"""
        body = self.create_via_api(
            contract_name='按实结算费用', has_fee=True, fee_amount='按实际使用量结算')
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '按实际使用量结算')

    def test_other_free_text_preserved(self):
        """「美元 5,000」「免费」「以最终结算单为准」等自由文本均原样保存"""
        for text in ('美元 5,000', '免费', '以最终结算单为准'):
            body = self.create_via_api(
                contract_name=f'自由文本费用-{text}', has_fee=True, fee_amount=text)
            self.assertNoError(body, text)
            self.assertEqual(body['data']['fee_amount'], text, text)

    def test_whitespace_stripped(self):
        """字符串输入执行 strip()，仅去除首尾空白、保留内部空格"""
        body = self.create_via_api(
            contract_name='首尾空格费用', has_fee=True, fee_amount='  12000元/年  ')
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '12000元/年')

        body = self.create_via_api(
            contract_name='内部空格费用', has_fee=True, fee_amount='美元 5,000')
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '美元 5,000')

    def test_missing_fee_rejected(self):
        """7. has_fee=true 且费用缺失时失败"""
        body = self.create_via_api(contract_name='有费用缺内容', has_fee=True)
        self.assertBusinessError(body)
        self.assertIn('费用内容', body.get('error', ''))

    def test_empty_fee_rejected(self):
        """8. has_fee=true 且费用为空字符串时失败"""
        body = self.create_via_api(
            contract_name='有费用空串', has_fee=True, fee_amount='')
        self.assertBusinessError(body)

    def test_whitespace_only_fee_rejected(self):
        """9. has_fee=true 且费用全为空格时失败"""
        body = self.create_via_api(
            contract_name='有费用全空格', has_fee=True, fee_amount='   ')
        self.assertBusinessError(body)

    def test_overlong_fee_rejected(self):
        """10. 超过 200 字符时失败（201 字拒绝，200 字通过）"""
        body = self.create_via_api(
            contract_name='超长费用', has_fee=True, fee_amount='费' * 201)
        self.assertBusinessError(body)
        self.assertIn('200', body.get('error', ''))

        body = self.create_via_api(
            contract_name='边界费用', has_fee=True, fee_amount='费' * 200)
        self.assertNoError(body)

    def test_complex_type_rejected(self):
        """列表、字典等复杂类型输入拒绝"""
        body = self.create_via_api(
            contract_name='列表费用', has_fee=True, fee_amount=[12000, '元/年'])
        self.assertBusinessError(body)
        self.assertIn('费用内容格式不正确', body.get('error', ''))

        body = self.create_via_api(
            contract_name='布尔费用', has_fee=True, fee_amount=True)
        self.assertBusinessError(body)

    def test_no_fee_forced_empty_on_create(self):
        """11. has_fee=false 时费用内容和费用明细被清空（不信任客户端残留值）"""
        body = self.create_via_api(
            contract_name='无费用残留', has_fee=False,
            fee_amount='9999', fee_detail='应被清空的明细')
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=body['data']['id'])
        self.assertEqual(obj.fee_amount, '')
        self.assertEqual(obj.fee_detail, '')

    def test_fee_currency_retired(self):
        """6. 不再返回或依赖固定「人民币」：响应无 fee_currency，模型无该字段"""
        body = self.create_via_api(
            contract_name='币种退役', has_fee=True, fee_amount='12345.67元/年')
        self.assertNoError(body)
        self.assertNotIn('fee_currency', body['data'])
        model_fields = {f.name for f in ContractAgreement._meta.get_fields()}
        self.assertNotIn('fee_currency', model_fields)

    def test_response_fee_amount_always_string(self):
        """API 输出的 fee_amount 始终为字符串（含无费用时的空串）"""
        body = self.create_via_api(contract_name='无费用输出', has_fee=False)
        self.assertNoError(body)
        self.assertIsInstance(body['data']['fee_amount'], str)
        self.assertEqual(body['data']['fee_amount'], '')

        body = self.create_via_api(
            contract_name='有费用输出', has_fee=True, fee_amount='8888')
        self.assertIsInstance(body['data']['fee_amount'], str)

    def test_db_constraint_rejects_paid_empty_fee(self):
        """16. 数据库约束拒绝 has_fee=true 且 fee_amount=''"""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_agreement(self.user, contract_name='DB约束空费用',
                               has_fee=True, fee_amount='')

    def test_db_allows_no_fee_empty(self):
        """数据库层允许 has_fee=false 且 fee_amount=''（应用层负责清空的合法状态）"""
        obj = make_agreement(self.user, contract_name='DB约束无费用空串',
                             has_fee=False, fee_amount='')
        self.assertEqual(obj.fee_amount, '')


class FeeTextEditTest(ContractTestCase):
    """编辑：按编辑后的完整状态校验费用"""

    def _create_paid(self, name='费用编辑合同', fee='12000元/年', detail='分两期'):
        created = self.create_via_api(
            contract_name=name, has_fee=True, fee_amount=fee, fee_detail=detail)
        self.assertNoError(created)
        return created['data']['id']

    def test_partial_edit_keeps_fee(self):
        """12. 局部编辑其他字段不会清空已有费用"""
        pk = self._create_paid()
        body = self.post_json({'id': pk, 'remark': '只改备注'})
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertTrue(obj.has_fee)
        self.assertEqual(obj.fee_amount, '12000元/年')
        self.assertEqual(obj.fee_detail, '分两期')

    def test_switch_to_fee_without_content_rejected(self):
        """13. 从无费用切换到有费用但未填写内容时失败"""
        created = self.create_via_api(contract_name='无费用转有费用')
        pk = created['data']['id']
        body = self.post_json({'id': pk, 'has_fee': True})
        self.assertBusinessError(body)
        self.assertIn('费用内容', body.get('error', ''))
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertFalse(obj.has_fee, '校验失败时不得部分落库')

    def test_switch_to_no_fee_clears_both(self):
        """14. 从有费用切换到无费用时正确清空费用内容与明细"""
        pk = self._create_paid()
        body = self.post_json({'id': pk, 'has_fee': False})
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertFalse(obj.has_fee)
        self.assertEqual(obj.fee_amount, '')
        self.assertEqual(obj.fee_detail, '')

    def test_switch_to_no_fee_ignores_client_residual(self):
        """切回无费用时提交残留费用内容/明细，服务端仍强制清空"""
        pk = self._create_paid()
        body = self.post_json({
            'id': pk, 'has_fee': False,
            'fee_amount': '9999', 'fee_detail': '客户端残留明细'})
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.fee_amount, '')
        self.assertEqual(obj.fee_detail, '')

    def test_edit_fee_empty_string_rejected(self):
        """有费用状态下修改 fee_amount='' 应返回业务错误"""
        pk = self._create_paid()
        body = self.post_json({'id': pk, 'fee_amount': ''})
        self.assertBusinessError(body)

        body = self.post_json({'id': pk, 'fee_amount': '   '})
        self.assertBusinessError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.fee_amount, '12000元/年', '校验失败不得改写费用')

    def test_edit_fee_number_compat(self):
        """编辑时 JSON 数字输入同样兼容并保存为字符串"""
        pk = self._create_paid()
        body = self.post_json({'id': pk, 'fee_amount': 6666})
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '6666')

    def test_edit_fee_text_updated(self):
        """编辑时可更新为自由文本费用"""
        pk = self._create_paid()
        body = self.post_json({'id': pk, 'fee_amount': '按实际结算'})
        self.assertNoError(body)
        self.assertEqual(body['data']['fee_amount'], '按实际结算')

    def test_edit_fee_negative_text_accepted(self):
        """15. 负数费用限制不再作为业务规则：「-100元调整款」作为合法文本处理"""
        created = self.create_via_api(contract_name='负数文本编辑')
        pk = created['data']['id']
        body = self.post_json({'id': pk, 'has_fee': True, 'fee_amount': '-100元调整款'})
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.fee_amount, '-100元调整款')

    def test_edit_overlong_fee_rejected(self):
        pk = self._create_paid()
        body = self.post_json({'id': pk, 'fee_amount': '费' * 201})
        self.assertBusinessError(body)
        self.assertIn('200', body.get('error', ''))
