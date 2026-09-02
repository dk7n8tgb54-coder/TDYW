# -*- coding: utf-8 -*-
"""新增 / 详情 / 编辑 / 删除 稳定契约测试。"""
from datetime import date, timedelta
from decimal import Decimal

from unittest import mock

from django.db.utils import DataError, OperationalError

from apps.contract_agreement.models import ContractAgreement
from apps.evidence.models import EvidenceAttachment
from .base import (ContractTestCase, build_payload, make_agreement, make_user,
                   make_client, upload_file, CONTRACT_TYPES,
                   PERM_VIEW, PERM_ADD, PERM_EDIT, PERM_DEL)


class CreateValidationTest(ContractTestCase):
    """新增：必填、类型、边界、费用、幂等"""

    def test_create_all_contract_types(self):
        for ctype in CONTRACT_TYPES:
            body = self.post_json(build_payload(
                self.user, contract_name=f'类型覆盖-{ctype}', contract_type=ctype))
            self.assertNoError(body)
            self.assertEqual(body['data']['contract_type'], ctype)
            self.assertTrue(body['data']['contract_type_display'])

    def test_create_unknown_contract_type_rejected(self):
        body = self.post_json(build_payload(self.user, contract_type='unknown_type'))
        self.assertBusinessError(body)
        self.assertFalse(ContractAgreement.objects.filter(contract_type='unknown_type').exists())

    def test_required_fields(self):
        """必填字段：合同名称 / 类型 / 起始日期 / 截止日期 / 签约方 / 责任人"""
        required = {
            'contract_name': '合同名称',
            'contract_type': '类型',
            'valid_start_date': '起始日期',
            'valid_end_date': '截止日期',
            'signing_party': '签约方',
            'responsible_user_id': '责任人',
        }
        for field, label in required.items():
            payload = build_payload(self.user, contract_name=f'必填校验-{field}')
            payload.pop(field)
            body = self.post_json(payload)
            self.assertTrue(body.get('error'),
                            f'缺少 {field} 时应返回错误，实际: {body}')
            self.assertIn(label, body.get('error', ''),
                          f'缺少 {field} 的错误文案应包含「{label}」')

    def test_create_trims_whitespace(self):
        body = self.post_json(build_payload(
            self.user,
            contract_name='   前后空格合同   ',
            contract_no='  NO-001  ',
            signing_party='  签约方空格  ',
        ))
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=body['data']['id'])
        self.assertEqual(obj.contract_name, '前后空格合同')
        self.assertEqual(obj.contract_no, 'NO-001')
        self.assertEqual(obj.signing_party, '签约方空格')

    def test_create_special_characters(self):
        name = '特殊字符 <script>alert(1)</script> & "引号" \\ 100%'
        body = self.post_json(build_payload(self.user, contract_name=name))
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=body['data']['id'])
        self.assertEqual(obj.contract_name, name)

    def test_create_overlong_fields_rejected(self):
        """超长字符串应在服务端被校验并给出业务错误，而不是抛未处理异常（HTTP 500）。

        未处理异常会由 HandleExceptionMiddleware 转成 HTTP 200 + 通用错误文案，
        仅看 error 字段无法区分，因此同时断言异常告警未被触发。
        """
        cases = [
            ('contract_name', '合' * 201, 200),
            ('contract_no', 'N' * 101, 100),
            ('signing_party', '签' * 501, 500),
        ]
        for field, value, max_len in cases:
            payload = build_payload(self.user, contract_name=f'超长-{field}')
            payload[field] = value
            try:
                with mock.patch('libs.alert.send_alert') as mocked_alert:
                    body = self.post_json(payload)
            except (DataError, OperationalError) as exc:
                self.fail(f'{field} 超过 {max_len} 字符未被服务端校验，'
                          f'直接抛出数据库异常（HTTP 500）: {exc}')
            self.assertFalse(
                mocked_alert.called,
                f'{field} 超过 {max_len} 字符未被服务端校验，触发了未处理异常告警；'
                f'实际响应: {body}')
            error = body.get('error') or ''
            self.assertTrue(error, f'{field} 超过 {max_len} 字符应被拒绝，实际: {body}')
            self.assertNotIn('1406', error,
                            f'{field} 超长不应把数据库错误码暴露给前端: {error}')

    def test_create_null_and_empty_values(self):
        body = self.post_json(build_payload(self.user, contract_name=''))
        self.assertBusinessError(body, '空合同名称应被拒绝')

        body = self.post_json(build_payload(self.user, contract_name=None))
        self.assertBusinessError(body, 'null 合同名称应被拒绝')

    def test_create_invalid_date_format_rejected(self):
        body = self.post_json(build_payload(
            self.user, valid_start_date='2026/01/01', valid_end_date='2026/12/31'))
        self.assertBusinessError(body)

    def test_start_date_after_end_date_rejected(self):
        body = self.post_json(build_payload(
            self.user,
            valid_start_date=str(self.today + timedelta(days=10)),
            valid_end_date=str(self.today),
        ))
        self.assertBusinessError(body)
        self.assertIn('起始日期不能晚于截止日期', body.get('error', ''))

    def test_same_start_and_end_date_accepted(self):
        body = self.post_json(build_payload(
            self.user,
            valid_start_date=str(self.today),
            valid_end_date=str(self.today),
        ))
        self.assertNoError(body)
        self.assertEqual(body['data']['days_left'], 0)

    def test_boundary_dates(self):
        cases = [
            ('截止日期今天', self.today, 0),
            ('截止日期未来1天', self.today + timedelta(days=1), 1),
            ('截止日期未来60天', self.today + timedelta(days=60), 60),
            ('截止日期未来61天', self.today + timedelta(days=61), 61),
            ('截止日期已过', self.today - timedelta(days=1), -1),
        ]
        for label, end_date, expected_days in cases:
            body = self.post_json(build_payload(
                self.user, contract_name=label,
                valid_start_date=str(end_date - timedelta(days=30)),
                valid_end_date=str(end_date)))
            self.assertNoError(body, f'{label} 应创建成功')
            self.assertEqual(body['data']['days_left'], expected_days, label)
            self.assertEqual(body['data']['valid_end_date'], str(end_date), label)

    def test_cross_year_and_leap_year_dates(self):
        body = self.post_json(build_payload(
            self.user, contract_name='跨年合同',
            valid_start_date='2025-12-01', valid_end_date='2026-01-31'))
        self.assertNoError(body)
        self.assertEqual(body['data']['valid_start_date'], '2025-12-01')
        self.assertEqual(body['data']['valid_end_date'], '2026-01-31')

        body = self.post_json(build_payload(
            self.user, contract_name='闰年合同',
            valid_start_date='2024-02-29', valid_end_date='2024-12-31'))
        self.assertNoError(body)
        self.assertEqual(body['data']['valid_start_date'], '2024-02-29')

    def test_invalid_leap_date_rejected(self):
        body = self.post_json(build_payload(
            self.user, contract_name='非闰年2月29',
            valid_start_date='2025-02-01', valid_end_date='2025-02-29'))
        self.assertBusinessError(body)

    # ---------------- 费用 ----------------
    def test_fee_disabled_clears_amount_and_detail(self):
        body = self.post_json(build_payload(
            self.user, contract_name='无费用合同', has_fee=False,
            fee_amount=9999, fee_detail='应被清空的明细'))
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=body['data']['id'])
        self.assertFalse(obj.has_fee)
        self.assertIsNone(obj.fee_amount)
        self.assertEqual(obj.fee_detail, '')

    def test_fee_enabled_amount_required(self):
        body = self.post_json(build_payload(
            self.user, contract_name='有费用缺金额', has_fee=True))
        self.assertBusinessError(body)
        self.assertIn('费用金额', body.get('error', ''))

    def test_fee_enabled_zero_amount_accepted(self):
        body = self.post_json(build_payload(
            self.user, contract_name='零元合同', has_fee=True, fee_amount=0))
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=body['data']['id'])
        self.assertEqual(Decimal(str(obj.fee_amount)), Decimal('0'))
        self.assertEqual(Decimal(body['data']['fee_amount']), Decimal('0'))

    def test_fee_enabled_negative_amount_rejected(self):
        body = self.post_json(build_payload(
            self.user, contract_name='负数金额', has_fee=True, fee_amount=-100))
        self.assertBusinessError(body)
        self.assertIn('费用金额不能小于 0', body.get('error', ''))

    def test_fee_enabled_invalid_amount_rejected(self):
        body = self.post_json(build_payload(
            self.user, contract_name='非法金额', has_fee=True, fee_amount='abc'))
        self.assertBusinessError(body)
        self.assertIn('费用金额格式不正确', body.get('error', ''))

    def test_currency_always_rmb(self):
        body = self.post_json(build_payload(
            self.user, contract_name='币种固定', has_fee=True,
            fee_amount=12345.67, fee_detail='季度付款'))
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=body['data']['id'])
        self.assertEqual(obj.fee_currency, '人民币')
        self.assertEqual(body['data']['fee_currency'], '人民币')

    # ---------------- 幂等 ----------------
    def test_duplicate_submit_within_30s_rejected(self):
        first = self.post_json(build_payload(self.user, contract_name='重复提交合同'))
        self.assertNoError(first)
        second = self.post_json(build_payload(self.user, contract_name='重复提交合同'))
        self.assertBusinessError(second)
        self.assertIn('重复提交', second.get('error', ''))
        self.assertEqual(
            ContractAgreement.objects.filter(contract_name='重复提交合同').count(), 1)

    def test_same_name_different_tenant_allowed(self):
        first = self.post_json(build_payload(self.user, contract_name='同名跨租户'))
        self.assertNoError(first)
        other = make_user('qa_same_name_other', [PERM_VIEW, PERM_ADD], tenant_id='t_same')
        second = self.post_json(build_payload(other, contract_name='同名跨租户'),
                                client=make_client(other))
        self.assertNoError(second)

    def test_responsible_user_name_is_server_filled(self):
        resp_user = make_user('qa_resp_target', [PERM_VIEW], nickname='真实责任人')
        body = self.post_json(build_payload(
            self.user, responsible_user_id=resp_user.id,
            responsible_user_name='伪造的责任人姓名'))
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=body['data']['id'])
        self.assertEqual(obj.responsible_user_id, resp_user.id)
        self.assertEqual(obj.responsible_user_name, '真实责任人')


class DetailAndEditTest(ContractTestCase):
    """详情与编辑"""

    def test_detail(self):
        created = self.create_via_api(contract_name='详情合同', remark='详情备注')
        self.assertNoError(created)
        body = self.get_json(f"{self.URL}{created['data']['id']}/")
        self.assertNoError(body)
        data = body['data']
        self.assertEqual(data['contract_name'], '详情合同')
        self.assertEqual(data['remark'], '详情备注')
        self.assertEqual(data['created_by_name'], self.user.nickname)
        self.assertIn('status_display', data)
        self.assertIn('attachment_count', data)

    def test_detail_not_found(self):
        body = self.get_json(f'{self.URL}999999/')
        self.assertBusinessError(body)

    def test_edit_basic_fields(self):
        created = self.create_via_api(contract_name='编辑前名称')
        pk = created['data']['id']
        body = self.post_json({'id': pk, 'contract_name': '编辑后名称',
                               'remark': '编辑后备注'})
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.contract_name, '编辑后名称')
        self.assertEqual(obj.remark, '编辑后备注')
        self.assertIsNotNone(obj.updated_at)
        self.assertEqual(obj.updated_by_id, self.user.id)

    def test_edit_full_payload_preserves_fee(self):
        created = self.create_via_api(contract_name='费用合同', has_fee=True,
                                      fee_amount=8888, fee_detail='三期付款')
        pk = created['data']['id']
        body = self.post_json(build_payload(
            self.user, id=pk, contract_name='费用合同-改', has_fee=True,
            fee_amount=8888, fee_detail='三期付款'))
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertTrue(obj.has_fee)
        self.assertEqual(Decimal(str(obj.fee_amount)), Decimal('8888'))
        self.assertEqual(obj.fee_detail, '三期付款')

    def test_partial_edit_must_not_reset_fee_fields(self):
        """局部编辑（仅传部分字段）不得静默清空未传字段。

        产品规则：局部更新只更新传入字段，未传字段保持原值。
        """
        created = self.create_via_api(contract_name='局部编辑合同', has_fee=True,
                                      fee_amount=6666, fee_detail='原明细',
                                      remark='原备注')
        pk = created['data']['id']
        body = self.post_json({'id': pk, 'remark': '只改备注'})
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.remark, '只改备注')
        self.assertTrue(obj.has_fee, '局部编辑不应关闭费用开关')
        self.assertEqual(Decimal(str(obj.fee_amount)), Decimal('6666'),
                         '局部编辑不应清空费用金额')
        self.assertEqual(obj.fee_detail, '原明细', '局部编辑不应清空费用明细')

    def test_partial_edit_must_not_forge_responsible_user_name(self):
        """客户端单独传 responsible_user_name（不传 id）时服务端不得采信。"""
        created = self.create_via_api(contract_name='姓名伪造合同')
        pk = created['data']['id']
        original_name = created['data']['responsible_user_name']
        body = self.post_json({'id': pk, 'responsible_user_name': '伪造姓名'})
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.responsible_user_name, original_name,
                         'responsible_user_name 只能由服务端根据 responsible_user_id 回填')

    def test_edit_validates_date_order(self):
        created = self.create_via_api(contract_name='日期校验合同')
        pk = created['data']['id']
        body = self.post_json({'id': pk, 'contract_name': '日期校验合同',
                               'contract_type': 'service_guarantee',
                               'valid_start_date': str(self.today),
                               'valid_end_date': str(self.today - timedelta(days=5)),
                               'has_fee': False, 'signing_party': 'X',
                               'responsible_user_id': self.user.id,
                               'responsible_user_name': self.user.nickname})
        self.assertBusinessError(body)
        self.assertIn('起始日期不能晚于截止日期', body.get('error', ''))

    def test_edit_rejected_when_fee_enabled_without_amount(self):
        created = self.create_via_api(contract_name='费用校验合同', has_fee=False)
        pk = created['data']['id']
        body = self.post_json({'id': pk, 'has_fee': True, 'fee_amount': None})
        self.assertBusinessError(body)

    def test_edit_nonexistent(self):
        body = self.post_json({'id': 999999, 'contract_name': '不存在'})
        self.assertBusinessError(body)


class DeleteTest(ContractTestCase):
    """删除"""

    def test_delete_removes_from_list_and_detail(self):
        created = self.create_via_api(contract_name='删除合同')
        pk = created['data']['id']
        body = self.delete_json({'id': pk})
        self.assertNoError(body)
        listing = self.get_json(self.URL)
        self.assertNotIn(pk, {r['id'] for r in listing['data']['records']})
        self.assertBusinessError(self.get_json(f'{self.URL}{pk}/'))

    def test_delete_soft_deletes_related_attachments(self):
        created = self.create_via_api(contract_name='带附件删除合同')
        pk = created['data']['id']
        up = self.upload(pk, upload_file('del.pdf', b'content to delete'))
        self.assertNoError(up)
        att_id = up['data']['id']

        body = self.delete_json({'id': pk})
        self.assertNoError(body)

        att = EvidenceAttachment.objects.all_with_deleted().filter(pk=att_id).first()
        self.assertIsNotNone(att, '删除合同后附件记录应保留（软删除）作为证据痕迹')
        self.assertTrue(att.is_deleted)

    def test_delete_requires_id(self):
        body = self.delete_json({})
        self.assertBusinessError(body)

    def test_delete_nonexistent(self):
        body = self.delete_json({'id': 999999})
        self.assertBusinessError(body)

    def test_delete_is_physical_with_audit_trail(self):
        """合同协议删除为物理删除（回收站已按产品决策全项目移除），可追溯性由审计日志保证。

        依据：ContractAgreement 无 is_deleted 字段（characterization test_model_has_no_is_deleted
        已固化）；本模块删除语义对齐 radio_license（物理删除，git c5f5bb85），回收站功能
        移除见 git dc7ebf58 / c5e7d266。追溯不变量：物理删除必须留下审计记录
        （操作者/租户/目标对象/动作），否则数据将不可追溯。
        """
        from apps.logs.models import AuditLog
        created = self.create_via_api(contract_name='物理删除可追溯合同')
        pk = created['data']['id']
        self.assertNoError(self.delete_json({'id': pk}))
        self.assertFalse(
            ContractAgreement.objects.all_with_deleted().filter(pk=pk).exists(),
            '删除后记录应物理移除（本模块无回收站，不应残留软删除记录）')
        log = AuditLog.objects.filter(
            target_type='contract_agreement', action='delete', target_id=pk
        ).order_by('-id').first()
        self.assertIsNotNone(log, '物理删除必须写审计日志保证可追溯')
        self.assertEqual(log.username, self.user.username)
        self.assertEqual(log.tenant_id, 'admin')
        self.assertTrue(log.is_success)
