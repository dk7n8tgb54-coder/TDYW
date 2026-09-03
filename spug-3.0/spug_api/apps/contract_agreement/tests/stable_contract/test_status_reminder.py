# -*- coding: utf-8 -*-
"""状态、到期提醒与角标稳定契约测试。"""
from datetime import timedelta

from apps.contract_agreement.models import ContractAgreement, ContractAgreementReminderAck
from apps.contract_agreement.tasks import (calculate_agreement_status,
                                           scan_single_contract_agreement,
                                           scan_contract_agreement_expiration)
from .base import ContractTestCase, make_agreement, make_user, make_client, PERM_VIEW

POPUP_URL = '/contract-agreement/reminders/popup/'
ACK_URL = '/contract-agreement/reminders/ack/'
BADGE_URL = '/contract-agreement/badge/'


class StatusCalculationTest(ContractTestCase):
    """状态计算与展示"""

    def test_expired_when_end_date_before_today(self):
        body = self.post_json({
            'contract_name': '已关闭合同', 'contract_type': 'device_purchase',
            'valid_start_date': str(self.today - timedelta(days=30)),
            'valid_end_date': str(self.today - timedelta(days=3)),
            'signing_party': 'X', 'responsible_user_id': self.user.id,
            'responsible_user_name': self.user.nickname, 'has_fee': False,
        })
        self.assertNoError(body)
        self.assertEqual(body['data']['status'], 'expired')
        self.assertEqual(body['data']['computed_status'], 'expired')
        self.assertEqual(body['data']['status_display'], '已关闭')
        self.assertEqual(body['data']['days_left'], -3)

    def test_status_boundaries(self):
        """截止日期 = 今天 / +1 / +60 / +61 天（三态：60 天窗口内为 expiring）"""
        cases = [
            (0, 'expiring', 0),
            (1, 'expiring', 1),
            (60, 'expiring', 60),
            (61, 'normal', 61),
            (-1, 'expired', -1),
        ]
        for offset, expected_status, expected_days in cases:
            end = self.today + timedelta(days=offset)
            status, days_left = calculate_agreement_status(end)
            self.assertEqual(status, expected_status, f'offset={offset}')
            self.assertEqual(days_left, expected_days, f'offset={offset}')

    def test_calculate_status_accepts_string_date(self):
        status, days = calculate_agreement_status(str(self.today + timedelta(days=5)))
        self.assertEqual(status, 'expiring')
        self.assertEqual(days, 5)

    def test_scan_single_updates_status_and_last_remind_at(self):
        ag = make_agreement(self.user, contract_name='单条扫描合同',
                            valid_end_date=self.today - timedelta(days=3))
        self.assertEqual(ag.status, 'normal')
        self.assertIsNone(ag.last_remind_at)

        result = scan_single_contract_agreement(ag)
        ag.refresh_from_db()
        self.assertEqual(result['status'], 'expired')
        self.assertTrue(result['updated'])
        self.assertEqual(ag.status, 'expired')
        self.assertIsNotNone(ag.last_remind_at, '扫描应更新 last_remind_at')

    def test_scan_single_no_change_when_status_same(self):
        ag = make_agreement(self.user, contract_name='无变化扫描合同',
                            valid_end_date=self.today + timedelta(days=30),
                            status='expiring')
        result = scan_single_contract_agreement(ag)
        self.assertEqual(result['status'], 'expiring')
        self.assertFalse(result['updated'])

    def test_scan_all_task_updates_all(self):
        expired = make_agreement(self.user, contract_name='批量-已过期',
                                 valid_end_date=self.today - timedelta(days=10))
        normal = make_agreement(self.user, contract_name='批量-正常',
                                valid_end_date=self.today + timedelta(days=100))
        border = make_agreement(self.user, contract_name='批量-今天到期',
                                valid_end_date=self.today)

        result = scan_contract_agreement_expiration.apply()
        self.assertTrue(result.successful(), f'Celery 任务执行失败: {result.result}')
        expired.refresh_from_db()
        normal.refresh_from_db()
        border.refresh_from_db()
        self.assertEqual(expired.status, 'expired')
        self.assertEqual(normal.status, 'normal')
        self.assertEqual(border.status, 'expiring', '60 天窗口内应更新为 expiring')
        self.assertEqual(result.get()['updated'], 2)

    def test_scan_all_task_is_repeatable(self):
        make_agreement(self.user, contract_name='重复扫描合同',
                       valid_end_date=self.today - timedelta(days=1))
        first = scan_contract_agreement_expiration.apply().get()
        second = scan_contract_agreement_expiration.apply().get()
        self.assertEqual(first['updated'], 1)
        self.assertEqual(second['updated'], 0, '重复扫描不应产生重复变更')
        self.assertEqual(ContractAgreement.objects.filter(contract_name='重复扫描合同').count(), 1)


class ReminderPopupTest(ContractTestCase):
    """提醒弹窗"""

    def test_popup_returns_only_current_responsible_user(self):
        mine = make_agreement(self.user, contract_name='我的到期合同',
                              valid_end_date=self.today + timedelta(days=10),
                              responsible_user_id=self.user.id)
        other = make_user('qa_popup_other', [PERM_VIEW])
        make_agreement(self.user, contract_name='他人的到期合同',
                       valid_end_date=self.today + timedelta(days=10),
                       responsible_user_id=other.id)

        other_ag = ContractAgreement.objects.filter(contract_name='他人的到期合同').first()
        body = self.get_json(POPUP_URL)
        self.assertNoError(body)
        ids = [r['agreement_id'] for r in body['data']['records']]
        self.assertIn(mine.id, ids)
        self.assertNotIn(other_ag.id, ids)

    def test_popup_excludes_out_of_window(self):
        make_agreement(self.user, contract_name='远端合同',
                       valid_end_date=self.today + timedelta(days=120),
                       responsible_user_id=self.user.id)
        body = self.get_json(POPUP_URL)
        self.assertEqual(body['data']['records'], [])

    def test_popup_includes_expired_and_expiring(self):
        make_agreement(self.user, contract_name='已过期提醒',
                       valid_end_date=self.today - timedelta(days=5),
                       responsible_user_id=self.user.id)
        make_agreement(self.user, contract_name='即将到期提醒',
                       valid_end_date=self.today + timedelta(days=10),
                       responsible_user_id=self.user.id)
        body = self.get_json(POPUP_URL)
        types = {r['remind_type'] for r in body['data']['records']}
        self.assertEqual(types, {'expired', 'expiring_daily'})

    def test_popup_excludes_acked(self):
        ag = make_agreement(self.user, contract_name='待确认合同',
                            valid_end_date=self.today - timedelta(days=2),
                            responsible_user_id=self.user.id)
        before = self.get_json(POPUP_URL)
        self.assertIn(ag.id, [r['agreement_id'] for r in before['data']['records']])

        ack = self.post_json({'agreement_id': ag.id}, url=ACK_URL)
        self.assertNoError(ack)
        self.assertTrue(ack['data']['acked'])

        after = self.get_json(POPUP_URL)
        self.assertNotIn(ag.id, [r['agreement_id'] for r in after['data']['records']],
                         '确认后不应重复弹出')

    def test_ack_is_idempotent(self):
        ag = make_agreement(self.user, contract_name='幂等确认合同',
                            valid_end_date=self.today - timedelta(days=2),
                            responsible_user_id=self.user.id)
        for _ in range(3):
            body = self.post_json({'agreement_id': ag.id}, url=ACK_URL)
            self.assertNoError(body)
            self.assertTrue(body['data']['acked'])
        self.assertEqual(
            ContractAgreementReminderAck.objects.filter(
                agreement=ag, user_id=self.user.id).count(), 1,
            '重复确认应幂等，只产生一条确认记录')

    def test_ack_expiring_contract_within_threshold(self):
        """到期窗口内（未过期，剩余 15 天）的合同必须可以被确认处理。

        弹窗按 valid_end_date <= today+60 返回（含 expiring_daily），
        但确认接口只在 computed status=expired 时才落确认记录，
        导致「即将到期」提醒点击「已处理」后仍会反复弹出。
        """
        ag = make_agreement(self.user, contract_name='即将到期确认',
                            valid_end_date=self.today + timedelta(days=15),
                            responsible_user_id=self.user.id)
        popup = self.get_json(POPUP_URL)
        self.assertIn(ag.id, [r['agreement_id'] for r in popup['data']['records']],
                      '到期窗口内合同应出现在弹窗')

        ack = self.post_json({'agreement_id': ag.id}, url=ACK_URL)
        self.assertNoError(ack)
        self.assertTrue(ack['data']['acked'],
                        '点击「已处理」必须落确认记录，否则提醒会反复弹出')

        after = self.get_json(POPUP_URL)
        self.assertNotIn(ag.id, [r['agreement_id'] for r in after['data']['records']],
                         '确认后不应重复弹出')

    def test_renewal_invalidates_old_ack(self):
        ag = make_agreement(self.user, contract_name='续期合同',
                            valid_end_date=self.today - timedelta(days=2),
                            responsible_user_id=self.user.id)
        self.post_json({'agreement_id': ag.id}, url=ACK_URL)
        self.assertEqual(self.get_json(POPUP_URL)['data']['records'], [])

        # 续期到 15 天后（仍在 60 天窗口内，三态应为 expiring）
        ContractAgreement.objects.filter(pk=ag.pk).update(
            valid_end_date=self.today + timedelta(days=15), status='expiring')
        after_renew = self.get_json(POPUP_URL)
        ids = [r['agreement_id'] for r in after_renew['data']['records']]
        self.assertIn(ag.id, ids, '续期后旧确认记录应失效并重新提醒')

    def test_ack_requires_agreement_id(self):
        body = self.post_json({}, url=ACK_URL)
        self.assertBusinessError(body)

    def test_ack_nonexistent_agreement(self):
        body = self.post_json({'agreement_id': 999999}, url=ACK_URL)
        self.assertBusinessError(body)


class BadgeTest(ContractTestCase):
    """角标统计"""

    def test_badge_counts(self):
        make_agreement(self.user, contract_name='角标-30天',
                       valid_end_date=self.today + timedelta(days=30))
        make_agreement(self.user, contract_name='角标-今天',
                       valid_end_date=self.today)
        make_agreement(self.user, contract_name='角标-已过期',
                       valid_end_date=self.today - timedelta(days=3))
        make_agreement(self.user, contract_name='角标-120天',
                       valid_end_date=self.today + timedelta(days=120))

        body = self.get_json(BADGE_URL)
        self.assertNoError(body)
        data = body['data']
        self.assertEqual(data['expiring_count'], 2)
        self.assertEqual(data['expired_count'], 1)
        self.assertEqual(data['count'], 3)

    def test_badge_not_reduced_by_ack(self):
        ag = make_agreement(self.user, contract_name='角标-确认后',
                            valid_end_date=self.today - timedelta(days=1),
                            responsible_user_id=self.user.id)
        before = self.get_json(BADGE_URL)['data']
        self.post_json({'agreement_id': ag.id}, url=ACK_URL)
        after = self.get_json(BADGE_URL)['data']
        self.assertEqual(after['expired_count'], before['expired_count'],
                         '角标统计不应因确认处理而减少')
        self.assertEqual(after['count'], before['count'])

    def test_badge_is_tenant_scoped(self):
        make_agreement(self.user, contract_name='角标-本租户',
                       valid_end_date=self.today + timedelta(days=5), tenant_id='admin')
        other_user = make_user('qa_badge_other', [PERM_VIEW], tenant_id='t_badge')
        make_agreement(other_user, contract_name='角标-他租户',
                       valid_end_date=self.today + timedelta(days=5), tenant_id='t_badge')
        mine = self.get_json(BADGE_URL)['data']
        theirs = self.get_json(BADGE_URL, client=make_client(other_user))['data']
        self.assertEqual(mine['count'], 1)
        self.assertEqual(theirs['count'], 1)
