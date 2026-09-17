# -*- coding: utf-8 -*-
"""费用字段文本化迁移（0009）真实行为测试。

在隔离测试库上真实执行 0008 ↔ 0009 迁移（非源码字符串断言），覆盖任务规约
十一 迁移验证 1-6 项：整数/小数金额转换、无费用记录清空、无「人民币」前缀、
非数字文本回滚被明确阻止、迁移前后记录数量一致、异常 NULL 数据阻断迁移。
每个用例结束时把测试库恢复到最新迁移状态，不影响其他测试。
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase

from apps.account.models import User
from apps.contract_agreement.models import ContractAgreement
from apps.utils.test_helpers import make_user

LATEST_MIGRATION = '0009_fee_amount_text'


class FeeAmountTextMigrationTest(TransactionTestCase):
    """0009 费用文本化迁移行为验证。"""

    def setUp(self):
        self.actor = make_user('fee_mig_actor', is_supper=True)

    def _migrate_to(self, target):
        call_command('migrate', 'contract_agreement', target,
                     verbosity=0, interactive=False)

    def _migrate_latest(self):
        call_command('migrate', 'contract_agreement',
                     verbosity=0, interactive=False)

    def _seed_at_0008(self, rows):
        """在 0008 结构（Decimal 列 + fee_currency 列）上按旧系统行为造数。

        必须走原生 SQL：0008 的 fee_currency 列无数据库级默认值（Django 的
        default 在 ORM 层生效），而运行时模型已不含该字段，经 ORM 插入会缺列。
        fee_amount 传 Decimal/None/整数，等价旧系统写入路径。
        """
        sql = (
            'INSERT INTO tdyw_contract_agreement '
            '(tenant_id, contract_name, contract_no, contract_type, '
            'valid_start_date, validity_type, valid_end_date, has_fee, '
            'fee_amount, fee_currency, fee_detail, signing_party, '
            'responsible_user_id, responsible_user_name, status, remark, '
            'created_at, created_by_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)'
        )
        defaults = dict(
            contract_name='迁移测试合同',
            contract_no='',
            valid_start_date=date.today() - timedelta(days=5),
            valid_end_date=date.today() + timedelta(days=200),
            validity_type='fixed',
            has_fee=False,
            fee_amount=None,
            fee_currency='人民币',
            fee_detail='',
            signing_party='迁移测试签约方',
            responsible_user_id=self.actor.id,
            responsible_user_name=self.actor.nickname,
            status='normal',
            remark='',
        )
        with connection.cursor() as cursor:
            for overrides in rows:
                params = dict(defaults)
                params.update(overrides)
                cursor.execute(sql, [
                    'admin', params['contract_name'], params['contract_no'],
                    'service_guarantee', params['valid_start_date'],
                    params['validity_type'], params['valid_end_date'],
                    params['has_fee'], params['fee_amount'],
                    params['fee_currency'], params['fee_detail'],
                    params['signing_party'], params['responsible_user_id'],
                    params['responsible_user_name'], params['status'],
                    params['remark'], self.actor.id,
                ])

    def _restore_old_fee_constraint(self):
        """手动移除的旧约束需原样恢复，保证 0009 重放时 RemoveConstraint 可执行。"""
        with connection.cursor() as cursor:
            cursor.execute(
                'ALTER TABLE tdyw_contract_agreement ADD CONSTRAINT contract_fee_valid '
                'CHECK (has_fee = FALSE OR (fee_amount IS NOT NULL AND fee_amount >= 0))')

    def test_forward_migration_converts_decimal_to_text(self):
        """整数/小数金额转字符串且数值含义不变；无费用记录清空；无人民币前缀；记录数一致"""
        self._migrate_to('0008')
        self._seed_at_0008([
            dict(contract_name='迁移-整数金额', has_fee=True, fee_amount=Decimal('1000')),
            dict(contract_name='迁移-小数金额', has_fee=True, fee_amount=Decimal('8888.66')),
            dict(contract_name='迁移-有费用正常', has_fee=True,
                 fee_amount=Decimal('12000.50'), fee_detail='分两期'),
            dict(contract_name='迁移-无费用零值', has_fee=False,
                 fee_amount=Decimal('0'), fee_detail='应被清空的明细'),
            dict(contract_name='迁移-无费用NULL', has_fee=False,
                 fee_amount=None, fee_detail='残留明细'),
        ])
        before = ContractAgreement.objects.count()

        self._migrate_latest()
        self.assertEqual(
            ContractAgreement.objects.count(), before, '迁移前后记录数量保持一致')

        rows = {c.contract_name: c for c in ContractAgreement.objects.all()}

        # 整数金额：转为普通十进制字符串，数值含义不变，无科学计数法
        integer_fee = rows['迁移-整数金额'].fee_amount
        self.assertIsInstance(integer_fee, str)
        self.assertEqual(Decimal(integer_fee), Decimal('1000'))
        self.assertRegex(integer_fee, r'^\d+(\.\d+)?$')

        # 小数金额：数值含义不变
        self.assertEqual(Decimal(rows['迁移-小数金额'].fee_amount), Decimal('8888.66'))
        self.assertEqual(
            Decimal(rows['迁移-有费用正常'].fee_amount), Decimal('12000.50'))
        self.assertEqual(rows['迁移-有费用正常'].fee_detail, '分两期')

        # 无费用记录（零值与 NULL）统一转换为空字符串，残留明细清空
        self.assertEqual(rows['迁移-无费用零值'].fee_amount, '')
        self.assertEqual(rows['迁移-无费用零值'].fee_detail, '')
        self.assertEqual(rows['迁移-无费用NULL'].fee_amount, '')
        self.assertEqual(rows['迁移-无费用NULL'].fee_detail, '')

        # 不产生「人民币」前缀、不添加货币符号
        for agreement in ContractAgreement.objects.all():
            self.assertFalse(agreement.fee_amount.startswith('人民币'))
            self.assertFalse(agreement.fee_amount.startswith('¥'))

    def test_rollback_blocked_on_non_numeric_fee(self):
        """非数字文本存在时回滚被明确阻止，且用户费用文本不被改写"""
        # 确保测试库停在最新迁移（0009），再造一条文本费用合同
        self._migrate_latest()
        obj = ContractAgreement.objects.create(
            contract_name='迁移-回滚保护', contract_type='service_guarantee',
            signing_party='甲方', valid_start_date=date.today() - timedelta(days=5),
            valid_end_date=date.today() + timedelta(days=200),
            validity_type='fixed', status='normal',
            has_fee=True, fee_amount='按实际结算',
            responsible_user_id=self.actor.id,
            responsible_user_name=self.actor.nickname,
            created_by=self.actor, tenant_id='admin')

        with self.assertRaises(RuntimeError) as ctx:
            self._migrate_to('0008')
        self.assertIn('回滚被阻止', str(ctx.exception))

        # 回滚被阻断后数据保持原样，不得静默改成 0、NULL 或删除
        obj.refresh_from_db()
        self.assertEqual(obj.fee_amount, '按实际结算')
        self.assertTrue(obj.has_fee)

    def test_forward_blocked_on_paid_null_fee(self):
        """has_fee=true 且 fee_amount=NULL 的异常数据阻断迁移，不静默生成虚假内容"""
        self._migrate_to('0008')
        # 0008 的旧约束 contract_fee_valid 会拦截 has_fee=true 且 NULL 的写入，
        # 先移除该约束模拟约束被绕过的异常存量数据
        with connection.cursor() as cursor:
            cursor.execute(
                'ALTER TABLE tdyw_contract_agreement DROP CONSTRAINT contract_fee_valid')
        self._seed_at_0008([dict(contract_name='迁移-异常NULL', has_fee=True, fee_amount=None)])

        with self.assertRaises(RuntimeError) as ctx:
            self._migrate_latest()
        self.assertIn('迁移被阻止', str(ctx.exception))
        self.assertIn('NULL', str(ctx.exception))

        # 恢复测试库到最新迁移状态：清除异常数据、原样恢复手动移除的旧约束后重放
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tdyw_contract_agreement WHERE contract_name = '迁移-异常NULL'")
        self._restore_old_fee_constraint()
        self._migrate_latest()
        self.assertFalse(
            ContractAgreement.objects.filter(contract_name='迁移-异常NULL').exists())
