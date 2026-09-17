# -*- coding: utf-8 -*-
"""长期有效合同（validity_type）稳定契约测试。

覆盖：期限类型创建/编辑转换、序列化、状态筛选、数据库检查约束、
迁移数据安全（回填 + 回滚保护）、Celery 扫描、提醒弹窗/角标/确认排除、
租户隔离与权限不变量。
"""
import importlib
from datetime import timedelta

from django.apps import apps as runtime_apps
from django.db import IntegrityError, transaction

from apps.contract_agreement.models import (
    ContractAgreement,
    ContractAgreementReminderAck,
)
from apps.contract_agreement.tasks import (
    resolve_agreement_status,
    scan_contract_agreement_expiration,
)
from .base import (
    ContractTestCase,
    build_payload,
    make_agreement,
    make_user,
    make_client,
    PERM_ADD,
    PERM_VIEW,
)

# 迁移文件名以数字开头，无法用普通 import 语句导入
MIGRATION_0008 = importlib.import_module(
    'apps.contract_agreement.migrations.0008_long_term_validity')

POPUP_URL = '/contract-agreement/reminders/popup/'
ACK_URL = '/contract-agreement/reminders/ack/'
BADGE_URL = '/contract-agreement/badge/'


def long_term_payload(responsible_user, **overrides):
    """构造长期有效合同请求载荷（无截止日期，除非测试显式传入矛盾截止日期）。"""
    payload = build_payload(responsible_user, **overrides)
    payload['validity_type'] = 'long_term'
    if 'valid_end_date' not in overrides:
        payload.pop('valid_end_date', None)
    return payload


class LongTermCreateTest(ContractTestCase):
    """创建：期限类型默认值、矛盾数据拒绝、数据库约束"""

    def test_create_long_term_without_end_date(self):
        body = self.post_json(long_term_payload(self.user, contract_name='长期-创建'))
        self.assertNoError(body)
        data = body['data']
        self.assertEqual(data['validity_type'], 'long_term')
        self.assertEqual(data['validity_type_display'], '长期有效')
        self.assertIsNone(data['valid_end_date'])
        self.assertEqual(data['status'], 'long_term')
        self.assertEqual(data['computed_status'], 'long_term')
        self.assertEqual(data['status_display'], '长期有效')
        self.assertIsNone(data['days_left'])
        obj = ContractAgreement.objects.get(pk=data['id'])
        self.assertIsNone(obj.valid_end_date, '长期合同截止日期必须为空')
        self.assertEqual(obj.status, 'long_term')

    def test_create_without_validity_type_defaults_fixed(self):
        """未提交 validity_type 时默认固定期限，兼容既有调用习惯。"""
        body = self.create_via_api(contract_name='默认固定期限')
        self.assertNoError(body)
        data = body['data']
        self.assertEqual(data['validity_type'], 'fixed')
        self.assertEqual(data['validity_type_display'], '固定期限')
        self.assertIsNotNone(data['valid_end_date'])
        obj = ContractAgreement.objects.get(pk=data['id'])
        self.assertEqual(obj.validity_type, 'fixed')
        self.assertIsNotNone(obj.valid_end_date)

    def test_create_long_term_with_end_date_rejected(self):
        """长期合同同时提交截止日期属于矛盾数据，必须拒绝而非静默清空。"""
        body = self.post_json(long_term_payload(
            self.user, contract_name='长期-矛盾截止日期',
            valid_end_date=str(self.today + timedelta(days=100))))
        self.assertBusinessError(body)
        self.assertIn('长期有效', body.get('error', ''))
        self.assertFalse(
            ContractAgreement.objects.filter(contract_name='长期-矛盾截止日期').exists(),
            '矛盾数据不得落库')

    def test_create_fixed_without_end_date_rejected(self):
        payload = build_payload(self.user, contract_name='固定-缺截止日期')
        payload.pop('valid_end_date')
        body = self.post_json(payload)
        self.assertBusinessError(body)
        self.assertIn('截止日期', body.get('error', ''))
        self.assertFalse(
            ContractAgreement.objects.filter(contract_name='固定-缺截止日期').exists())

    def test_create_fixed_end_before_start_rejected(self):
        body = self.create_via_api(
            contract_name='固定-日期倒挂',
            valid_start_date=str(self.today + timedelta(days=10)),
            valid_end_date=str(self.today))
        self.assertBusinessError(body)
        self.assertIn('起始日期不能晚于截止日期', body.get('error', ''))

    def test_create_unknown_validity_type_rejected(self):
        body = self.create_via_api(contract_name='未知期限类型', validity_type='forever')
        self.assertBusinessError(body)
        self.assertFalse(
            ContractAgreement.objects.filter(contract_name='未知期限类型').exists())

    def test_db_constraint_rejects_contradictions(self):
        """数据库检查约束兜底：绕过 API 直接写库时矛盾组合必须被拒绝。"""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_agreement(
                    self.user, validity_type='long_term',
                    valid_end_date=self.today + timedelta(days=10))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_agreement(
                    self.user, validity_type='fixed', valid_end_date=None)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_agreement(self.user, valid_end_date=self.today - timedelta(days=20))


class LongTermEditTest(ContractTestCase):
    """编辑：期限类型互相转换、字段未提交保持原值、旧提醒确认失效"""

    def _create_fixed(self, name):
        created = self.create_via_api(contract_name=name)
        self.assertNoError(created)
        return created['data']['id']

    def _create_long_term(self, name):
        body = self.post_json(long_term_payload(self.user, contract_name=name))
        self.assertNoError(body)
        return body['data']['id']

    def test_edit_fixed_to_long_term_clears_end_date(self):
        pk = self._create_fixed('转换-固定转长期')
        body = self.post_json({'id': pk, 'validity_type': 'long_term'})
        self.assertNoError(body)
        data = body['data']
        self.assertEqual(data['validity_type'], 'long_term')
        self.assertIsNone(data['valid_end_date'])
        self.assertEqual(data['computed_status'], 'long_term')
        self.assertIsNone(data['days_left'])
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertIsNone(obj.valid_end_date, '转长期后截止日期必须清空')
        self.assertEqual(obj.status, 'long_term')

    def test_edit_fixed_to_long_term_with_end_date_rejected(self):
        pk = self._create_fixed('转换-固定转长期矛盾')
        body = self.post_json({
            'id': pk, 'validity_type': 'long_term',
            'valid_end_date': str(self.today + timedelta(days=30)),
        })
        self.assertBusinessError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.validity_type, 'fixed', '拒绝后原值不得变化')
        self.assertIsNotNone(obj.valid_end_date)

    def test_edit_long_term_to_fixed_requires_end_date(self):
        pk = self._create_long_term('转换-长期转固定缺日期')
        body = self.post_json({'id': pk, 'validity_type': 'fixed'})
        self.assertBusinessError(body)
        self.assertIn('截止日期', body.get('error', ''))
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.validity_type, 'long_term', '拒绝后原值不得变化')
        self.assertIsNone(obj.valid_end_date)

    def test_edit_long_term_to_fixed_with_valid_end_date(self):
        pk = self._create_long_term('转换-长期转固定')
        body = self.post_json({
            'id': pk, 'validity_type': 'fixed',
            'valid_end_date': str(self.today + timedelta(days=100)),
        })
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.validity_type, 'fixed')
        self.assertEqual(obj.valid_end_date, self.today + timedelta(days=100))
        self.assertEqual(obj.status, 'normal')
        self.assertEqual(body['data']['computed_status'], 'normal')

    def test_edit_long_term_keeps_fields_when_absent(self):
        """编辑长期合同只改名称时，期限类型与空截止日期必须保持原值。"""
        pk = self._create_long_term('长期-局部编辑')
        body = self.post_json({'id': pk, 'contract_name': '长期-局部编辑后'})
        self.assertNoError(body)
        obj = ContractAgreement.objects.get(pk=pk)
        self.assertEqual(obj.contract_name, '长期-局部编辑后')
        self.assertEqual(obj.validity_type, 'long_term')
        self.assertIsNone(obj.valid_end_date)

    def test_edit_fixed_end_date_change_validates_order(self):
        pk = self._create_fixed('转换-固定改截止日期')
        body = self.post_json({
            'id': pk, 'valid_end_date': str(self.today - timedelta(days=200)),
        })
        self.assertBusinessError(body)
        self.assertIn('起始日期不能晚于截止日期', body.get('error', ''))

    # ---------- 旧提醒确认记录失效（审计可追踪） ----------
    def _create_fixed_in_reminder_window(self, name):
        """创建 60 天提醒窗口内的固定期限合同（可触发提醒与确认）。"""
        created = self.create_via_api(
            contract_name=name,
            valid_end_date=str(self.today + timedelta(days=15)))
        self.assertNoError(created)
        return created['data']['id']

    def _ack_via_api(self, pk):
        body = self.post_json({'agreement_id': pk}, url=ACK_URL)
        self.assertNoError(body)
        self.assertTrue(body['data']['acked'])
        return body

    def test_ack_records_reset_on_convert_to_long_term(self):
        pk = self._create_fixed_in_reminder_window('提醒失效-转长期')
        self._ack_via_api(pk)
        self.assertEqual(
            ContractAgreementReminderAck.objects.filter(agreement_id=pk).count(), 1)

        body = self.post_json({'id': pk, 'validity_type': 'long_term'})
        self.assertNoError(body)
        self.assertEqual(
            ContractAgreementReminderAck.objects.filter(agreement_id=pk).count(), 0,
            '转长期后旧确认记录必须清理，防止未来错误生效')

    def test_ack_records_reset_on_end_date_change(self):
        pk = self._create_fixed_in_reminder_window('提醒失效-改截止日期')
        self._ack_via_api(pk)
        body = self.post_json({
            'id': pk, 'valid_end_date': str(self.today + timedelta(days=30)),
        })
        self.assertNoError(body)
        self.assertEqual(
            ContractAgreementReminderAck.objects.filter(agreement_id=pk).count(), 0,
            '截止日期变化后旧确认记录必须清理')

    def test_ack_records_kept_when_no_term_change(self):
        """期限与截止日期都未变化时，确认记录必须保留。"""
        pk = self._create_fixed_in_reminder_window('提醒保留-只改名称')
        self._ack_via_api(pk)
        body = self.post_json({'id': pk, 'contract_name': '提醒保留-只改名称后'})
        self.assertNoError(body)
        self.assertEqual(
            ContractAgreementReminderAck.objects.filter(agreement_id=pk).count(), 1)

    def test_ack_reset_is_audit_traced(self):
        from apps.logs.models import AuditLog
        pk = self._create_fixed_in_reminder_window('提醒失效-审计')
        self._ack_via_api(pk)
        self.post_json({'id': pk, 'validity_type': 'long_term'})
        log = AuditLog.objects.filter(
            target_type='contract_agreement', action='update', target_id=pk,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertIn('reminder_acks_reset', log.detail,
                      '确认记录清理必须体现在审计日志中')


class LongTermListFilterTest(ContractTestCase):
    """列表序列化与状态筛选"""

    def setUp(self):
        super().setUp()
        self.a1 = make_agreement(
            self.user, contract_name='固定-30天',
            valid_end_date=self.today + timedelta(days=30))
        self.a2 = make_agreement(
            self.user, contract_name='固定-300天',
            valid_end_date=self.today + timedelta(days=300))
        self.a3 = make_agreement(
            self.user, contract_name='固定-已过期',
            valid_end_date=self.today - timedelta(days=5))
        self.lt = make_agreement(
            self.user, contract_name='长期-有效',
            validity_type='long_term', valid_end_date=None)
        # 同步一次到期状态（等价于每日 Celery 扫描）
        scan_contract_agreement_expiration.apply()

    def _ids(self, params):
        body = self.get_json(self.URL, params)
        self.assertNoError(body)
        return {r['id'] for r in body['data']['records']}

    def test_filter_long_term(self):
        self.assertEqual(self._ids({'status': 'long_term'}), {self.lt.id})

    def test_fixed_status_filters_exclude_long_term(self):
        self.assertEqual(self._ids({'status': 'normal'}), {self.a2.id})
        self.assertEqual(self._ids({'status': 'expiring'}), {self.a1.id})
        self.assertEqual(self._ids({'status': 'expired'}), {self.a3.id})

    def test_end_date_range_filter_excludes_long_term(self):
        body = self.get_json(self.URL, {
            'valid_end_from': '2020-01-01',
            'valid_end_to': '2099-12-31',
        })
        self.assertNoError(body)
        ids = {r['id'] for r in body['data']['records']}
        self.assertNotIn(self.lt.id, ids, '截止日期范围筛选不应命中长期合同')
        self.assertIn(self.a1.id, ids)

    def test_serialization_contains_validity_fields(self):
        body = self.get_json(f'{self.URL}{self.lt.id}/')
        self.assertNoError(body)
        data = body['data']
        self.assertEqual(data['validity_type'], 'long_term')
        self.assertEqual(data['validity_type_display'], '长期有效')
        self.assertIsNone(data['valid_end_date'])
        self.assertEqual(data['status'], 'long_term')
        self.assertEqual(data['computed_status'], 'long_term')
        self.assertEqual(data['status_display'], '长期有效')
        self.assertIsNone(data['days_left'])

        body = self.get_json(f'{self.URL}{self.a2.id}/')
        data = body['data']
        self.assertEqual(data['validity_type'], 'fixed')
        self.assertEqual(data['validity_type_display'], '固定期限')
        self.assertIn(data['status'], ('normal', 'expiring', 'expired'))
        self.assertIsNotNone(data['days_left'])


class LongTermReminderTest(ContractTestCase):
    """提醒弹窗、角标、确认接口与 Celery 扫描"""

    def test_popup_excludes_long_term(self):
        make_agreement(
            self.user, contract_name='弹窗-长期',
            validity_type='long_term', valid_end_date=None,
            responsible_user_id=self.user.id)
        expiring = make_agreement(
            self.user, contract_name='弹窗-即将到期',
            valid_end_date=self.today + timedelta(days=10),
            responsible_user_id=self.user.id)
        body = self.get_json(POPUP_URL)
        self.assertNoError(body)
        ids = [r['agreement_id'] for r in body['data']['records']]
        self.assertNotIn(
            ContractAgreement.objects.get(contract_name='弹窗-长期').id, ids,
            '长期合同不得进入到期提醒弹窗')
        self.assertIn(expiring.id, ids)

    def test_badge_excludes_long_term(self):
        make_agreement(
            self.user, contract_name='角标-长期',
            validity_type='long_term', valid_end_date=None)
        make_agreement(
            self.user, contract_name='角标-即将到期',
            valid_end_date=self.today + timedelta(days=30))
        body = self.get_json(BADGE_URL)
        self.assertNoError(body)
        data = body['data']
        self.assertEqual(data['expiring_count'], 1)
        self.assertEqual(data['expired_count'], 0)
        self.assertEqual(data['count'], 1, '角标不得统计长期合同')

    def test_ack_long_term_ignored(self):
        lt = make_agreement(
            self.user, contract_name='确认-长期',
            validity_type='long_term', valid_end_date=None,
            responsible_user_id=self.user.id)
        body = self.post_json({'agreement_id': lt.id}, url=ACK_URL)
        self.assertNoError(body)
        self.assertFalse(body['data']['acked'], '长期合同确认应被忽略（无需提醒）')
        self.assertEqual(
            ContractAgreementReminderAck.objects.filter(agreement=lt).count(), 0,
            '不得为长期合同创建确认记录')

    def test_scan_long_term_no_error_and_keeps_status(self):
        lt = make_agreement(
            self.user, contract_name='扫描-长期',
            validity_type='long_term', valid_end_date=None, status='normal')
        result = scan_contract_agreement_expiration.apply()
        self.assertTrue(result.successful(), f'Celery 扫描执行失败: {result.result}')
        lt.refresh_from_db()
        self.assertEqual(lt.status, 'long_term', '长期合同状态应更新为 long_term')
        self.assertIsNotNone(lt.last_remind_at)

        status, days_left = resolve_agreement_status(lt)
        self.assertEqual(status, 'long_term')
        self.assertIsNone(days_left, '长期合同剩余天数不适用')

    def test_scan_long_term_status_stable_on_repeat(self):
        make_agreement(
            self.user, contract_name='扫描-长期重复',
            validity_type='long_term', valid_end_date=None)
        first = scan_contract_agreement_expiration.apply().get()
        second = scan_contract_agreement_expiration.apply().get()
        self.assertEqual(first['updated'], 1)
        self.assertEqual(second['updated'], 0, '重复扫描不应产生重复变更')


class MigrationDataSafetyTest(ContractTestCase):
    """迁移数据安全：历史数据回填与回滚保护"""

    def test_backfill_marks_rows_fixed_and_keeps_end_date(self):
        """现有数据迁移后全部为 fixed，截止日期保持不变（任务规约六.1）。

        真实迁移场景：回填作用于「尚无 validity_type 列」的历史数据，
        AddField 默认值已填 fixed，且该步骤执行时新约束尚未添加、
        截止日期仍为非空——因此直接对当前数据执行回填函数，验证其
        覆盖全部行（幂等兜底）且对截止日期/起始日期零改动。
        """
        fixed = make_agreement(self.user, contract_name='迁移回填-固定',
                               valid_end_date=self.today + timedelta(days=100))
        expiring = make_agreement(self.user, contract_name='迁移回填-即将到期',
                                  valid_end_date=self.today + timedelta(days=10))
        expired = make_agreement(self.user, contract_name='迁移回填-已过期',
                                 valid_end_date=self.today - timedelta(days=5))
        ends = {a.pk: a.valid_end_date for a in (fixed, expiring, expired)}
        starts = {a.pk: a.valid_start_date for a in (fixed, expiring, expired)}

        MIGRATION_0008.backfill_validity_type(runtime_apps, None)

        for ag in (fixed, expiring, expired):
            ag.refresh_from_db()
            self.assertEqual(ag.validity_type, 'fixed', '历史行必须回填为 fixed')
            self.assertEqual(ag.valid_end_date, ends[ag.pk], '回填不得改动截止日期')
            self.assertEqual(ag.valid_start_date, starts[ag.pk])

    def test_rollback_guard_blocks_long_term(self):
        """存在长期合同时回滚被阻止（非空截止日期结构无法表示长期合同）。"""
        make_agreement(
            self.user, contract_name='回滚保护-长期',
            validity_type='long_term', valid_end_date=None)
        with self.assertRaises(RuntimeError):
            MIGRATION_0008.forbid_long_term_rollback(runtime_apps, None)

    def test_rollback_guard_allows_fixed_only(self):
        make_agreement(self.user, contract_name='回滚放行-固定')
        MIGRATION_0008.forbid_long_term_rollback(runtime_apps, None)  # 不应抛出


class LongTermTenantPermissionTest(ContractTestCase):
    """租户隔离与权限不变量（长期合同视角）"""

    def test_long_term_tenant_isolation(self):
        mine = make_agreement(
            self.user, contract_name='长期-本租户',
            validity_type='long_term', valid_end_date=None, tenant_id='admin')
        theirs_user = make_user('qa_lt_tenant_b', [PERM_VIEW], tenant_id='t_lt')
        theirs = make_agreement(
            theirs_user, contract_name='长期-他租户',
            validity_type='long_term', valid_end_date=None, tenant_id='t_lt')

        ids = {r['id'] for r in self.get_json(self.URL)['data']['records']}
        self.assertIn(mine.id, ids)
        self.assertNotIn(theirs.id, ids)

        ids_b = {
            r['id'] for r in self.get_json(self.URL, client=make_client(theirs_user))['data']['records']
        }
        self.assertIn(theirs.id, ids_b)
        self.assertNotIn(mine.id, ids_b)

        # 跨租户详情不可见
        body = self.get_json(f'{self.URL}{theirs.id}/')
        self.assertBusinessError(body)

    def test_long_term_create_requires_add_permission(self):
        viewer = make_user('qa_lt_viewer', [PERM_VIEW])
        body = self.post_json(
            long_term_payload(viewer, contract_name='长期-无权限'),
            client=make_client(viewer))
        self.assertBusinessError(body)
        self.assertFalse(
            ContractAgreement.objects.filter(contract_name='长期-无权限').exists())
