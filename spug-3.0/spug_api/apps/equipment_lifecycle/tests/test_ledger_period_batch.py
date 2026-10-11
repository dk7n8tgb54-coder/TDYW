# -*- coding: utf-8 -*-
"""维护台账周期批量新增与周期分组（2026-10-11 最小实现）行为测试。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）：
- 一键新增：范围为本租户在用系统，一系统一张草稿台账，无明细不编造内容；
- 幂等：同类型+同周期+同系统重复执行不产生重复台账（作废不占名额，
  历史台账实际执行日期落在周期内保守判定为已存在）；
- 租户隔离与权限：跨租户互不可见、不占用周期名额，无权限后端真实拒绝；
- 周期分组：按 维护类型+周期 分组，历史台账按实际执行日期推导周期；
- 系统筛选：表头级系统（批量新增台账）与明细系统（历史台账）均命中。
"""
from django.utils import timezone
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
)
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX,
    make_client,
    make_system,
    make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    entry_payload,
    item_payload,
    ledger_payload,
    post_json,
)

LEDGERS_URL = URL_PREFIX + '/ledgers'
BATCH_URL = LEDGERS_URL + '/batch-create/'
GROUPS_URL = LEDGERS_URL + '/period-groups/'


class PeriodBatchTestBase(TestCase):
    """公共夹具：双系统 + 双租户（client 必须在 setUp 创建）。"""

    def setUp(self):
        self.user = make_user('batch_op', perms=ALL_LEDGER_PERMS)
        self.client = make_client(self.user)
        self.system_a = make_system(self.user, system_code='SYS-A', name='DVOR系统')
        self.system_b = make_system(self.user, system_code='SYS-B', name='ILS系统')
        self.other_user = make_user('other_op', tenant_id='tenant-b', perms=ALL_LEDGER_PERMS)
        self.other_client = make_client(self.other_user)
        self.other_system = make_system(
            self.other_user, tenant_id='tenant-b', system_code='SYS-B2', name='B租户系统')

    def batch_create(self, period='2026-10', ledger_type=LEDGER_TYPE_WEEK_MONTH, client=None):
        return post_json(client or self.client, BATCH_URL, {
            'ledger_type': ledger_type, 'period': period})

    @staticmethod
    def ok_data(resp):
        """json_response 成功体为 {data: <payload>, error: ''}，取业务载荷。"""
        body = resp.json()
        assert not body.get('error'), body
        return body['data']

    def make_manual_ledger(self, system, executed_date, client=None, **kwargs):
        """经既有手工补录入口创建一张历史台账（表头无 system，明细关联系统）。"""
        payload = ledger_payload(
            [entry_payload(system.id, [item_payload()])],
            executed_date=executed_date, **kwargs)
        resp = post_json(client or self.client, LEDGERS_URL + '/', payload)
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(body.get('error'), body)
        # POST /ledgers/ 返回台账详情（json_response 单层 data）
        return body['data']


class BatchCreateTests(PeriodBatchTestBase):
    """一键新增：范围、幂等、作废释放名额、历史台账保守判定。"""

    def test_batch_create_creates_one_draft_per_active_system(self):
        resp = self.batch_create()
        data = self.ok_data(resp)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['created'], 2)
        self.assertEqual(data['existed'], 0)
        self.assertEqual(data['period_text'], '2026年10月')
        # 数据库真实状态：一系统一张草稿台账，无明细、周期与表头系统落库
        ledgers = OperationLedger.objects.all()
        self.assertEqual(ledgers.count(), 2)
        for ledger in ledgers:
            self.assertEqual(ledger.ledger_type, LEDGER_TYPE_WEEK_MONTH)
            self.assertEqual(ledger.maintenance_period, '2026-10')
            self.assertEqual(ledger.status, 'draft')
            self.assertEqual(ledger.created_from, 'manual')
            self.assertEqual(ledger.executed_date, timezone.now().date())
            self.assertIsNotNone(ledger.system_id)
            self.assertTrue(ledger.ledger_no.startswith('EL-WM-'))
            self.assertEqual(ledger.items.count(), 0)
        created_names = {item['system_name'] for item in data['created_ledgers']}
        self.assertEqual(created_names, {'DVOR系统', 'ILS系统'})

    def test_scope_excludes_inactive_systems(self):
        make_system(self.user, system_code='SYS-C', name='退役系统', is_active=False)
        data = self.ok_data(self.batch_create())
        self.assertEqual(data['created'], 2)
        self.assertFalse(
            OperationLedger.objects.filter(system__name='退役系统').exists())

    def test_repeated_same_period_creates_no_duplicates(self):
        first = self.ok_data(self.batch_create())
        self.assertEqual(first['created'], 2)
        second = self.ok_data(self.batch_create())
        self.assertEqual(second['created'], 0)
        self.assertEqual(second['existed'], 2)
        self.assertEqual(sorted(second['existed_systems']), ['DVOR系统', 'ILS系统'])
        self.assertEqual(OperationLedger.objects.count(), 2)

    def test_voided_ledger_frees_period_slot(self):
        self.batch_create()
        ledger = OperationLedger.objects.filter(system=self.system_a).first()
        resp = post_json(self.client, '%s/%d/void/' % (LEDGERS_URL, ledger.id),
                         {'reason': '误建'})
        self.assertFalse(resp.json().get('error'), resp.json())
        again = self.ok_data(self.batch_create())
        self.assertEqual(again['created'], 1)
        self.assertEqual(again['existed'], 1)
        self.assertEqual(again['existed_systems'], ['ILS系统'])
        # 作废台账保留，新台账另建一张
        self.assertEqual(
            OperationLedger.objects.filter(system=self.system_a).count(), 2)
        self.assertTrue(
            OperationLedger.objects.filter(system=self.system_a, status='draft').exists())

    def test_legacy_ledger_executed_in_period_blocks_duplicate(self):
        # 历史台账无周期标记：实际执行日期落在 2026-10 内即视为该系统已有台账
        self.make_manual_ledger(self.system_a, '2026-10-15')
        data = self.ok_data(self.batch_create())
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['existed'], 1)
        self.assertEqual(data['existed_systems'], ['DVOR系统'])

    def test_seasonal_legacy_ledger_in_season_blocks_duplicate(self):
        # 季维护同口径：夏秋航季内已执行的历史台账占用该航季名额
        self.make_manual_ledger(self.system_a, '2026-08-15',
                                ledger_type=LEDGER_TYPE_SEASONAL)
        data = self.ok_data(
            self.batch_create(period='2026-夏秋', ledger_type=LEDGER_TYPE_SEASONAL))
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['existed'], 1)
        self.assertEqual(data['existed_systems'], ['DVOR系统'])

    def test_legacy_ledger_outside_period_does_not_block(self):
        self.make_manual_ledger(self.system_a, '2026-09-30')
        data = self.ok_data(self.batch_create(period='2026-10'))
        self.assertEqual(data['created'], 2)
        self.assertEqual(data['existed'], 0)

    def test_period_tagged_ledger_does_not_block_other_period_or_type(self):
        self.batch_create(period='2026-10')
        # 不同周期正常创建
        data_nov = self.ok_data(self.batch_create(period='2026-11'))
        self.assertEqual(data_nov['created'], 2)
        # 不同类型互不占用（周月维护按月、季维护按航季，周期独立）
        data_winter = self.ok_data(
            self.batch_create(period='2026-冬春', ledger_type=LEDGER_TYPE_SEASONAL))
        self.assertEqual(data_winter['created'], 2)
        self.assertEqual(data_winter['period_text'], '2026年冬春季')
        self.assertEqual(OperationLedger.objects.count(), 6)

    def test_invalid_period_rejected(self):
        for period in ('', '2026-13', '202610', 'abc', '2026-Q4'):
            resp = self.batch_create(period=period)
            self.assertTrue(resp.json().get('error'), period)
        # 季维护：Q1-Q4 口径已废弃，只接受夏秋/冬春航季
        for period in ('2026-Q1', '2026-春', '2026-夏秋x', '2026-夏秋季'):
            resp = self.batch_create(period=period, ledger_type=LEDGER_TYPE_SEASONAL)
            self.assertTrue(resp.json().get('error'), period)
        resp = self.batch_create(period='2026-10', ledger_type='inspection')
        self.assertIn('不再支持', resp.json()['error'])
        self.assertEqual(OperationLedger.objects.count(), 0)

    def test_no_active_systems_rejected(self):
        for system in (self.system_a, self.system_b):
            system.is_active = False
            system.save()
        resp = self.batch_create()
        self.assertIn('没有在用系统', resp.json()['error'])

    def test_permission_denied_without_add_perm(self):
        viewer = make_user('viewer_only', perms=['equipment_lifecycle.ledger.view'])
        viewer_client = make_client(viewer)
        resp = self.batch_create(client=viewer_client)
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertEqual(OperationLedger.objects.count(), 0)
        # GET 范围接口仅需 view 权限
        resp = viewer_client.get(BATCH_URL)
        self.assertFalse(resp.json().get('error'), resp.json())


class BatchCreateTenantTests(PeriodBatchTestBase):
    """租户隔离：范围、去重与分组互不跨租户。"""

    def test_other_tenant_scope_and_dedup_independent(self):
        data = self.ok_data(self.batch_create(client=self.other_client))
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['created_ledgers'][0]['system_name'], 'B租户系统')
        # A 租户未受影响，且同周期可独立创建
        data_a = self.ok_data(self.batch_create())
        self.assertEqual(data_a['created'], 2)
        self.assertEqual(OperationLedger.objects.count(), 3)

    def test_options_and_groups_are_tenant_scoped(self):
        self.batch_create()
        options = self.other_client.get(BATCH_URL).json()['data']['data']
        self.assertEqual([o['name'] for o in options], ['B租户系统'])
        groups = self.other_client.get(
            GROUPS_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH}).json()['data']['data']
        self.assertEqual(groups, [])


class PeriodGroupTests(PeriodBatchTestBase):
    """周期分组：分组键、推导、统计与筛选。"""

    def setUp(self):
        super().setUp()
        self.batch_create(period='2026-10')
        # 历史台账：明细关联 system_b，执行日期在 2026-10（推导同组）
        self.make_manual_ledger(self.system_b, '2026-10-20')

    def test_groups_by_type_and_period_with_fill_status(self):
        data = self.client.get(
            GROUPS_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH}).json()['data']['data']
        self.assertEqual(len(data), 1)
        group = data[0]
        self.assertEqual(group['maintenance_period'], '2026-10')
        self.assertEqual(group['period_text'], '2026年10月')
        self.assertEqual(group['total'], 3)
        # 批量新增的两张壳 + 历史手工台账均为草稿（待填写=草稿数）
        self.assertEqual(group['pending'], 3)
        self.assertEqual(group['filled'], 0)
        # 组内行包含表头级系统名（批量新增台账）与来源字段
        system_names = {row['system_name'] for row in group['ledgers'] if row['system_name']}
        self.assertEqual(system_names, {'DVOR系统', 'ILS系统'})
        self.assertTrue(all('source_type' in row for row in group['ledgers']))

    def test_seasonal_group_derived_from_executed_date(self):
        # 历史季维护台账按航季边界推导：夏秋=3月末周日~10月末周日；冬春跨年
        self.make_manual_ledger(self.system_a, '2026-08-15',
                                ledger_type=LEDGER_TYPE_SEASONAL)
        self.make_manual_ledger(self.system_b, '2026-11-15',
                                ledger_type=LEDGER_TYPE_SEASONAL)
        data = self.client.get(
            GROUPS_URL, {'ledger_type': LEDGER_TYPE_SEASONAL}).json()['data']['data']
        self.assertEqual(len(data), 2)
        by_period = {g['maintenance_period']: g for g in data}
        self.assertEqual(set(by_period), {'2026-夏秋', '2026-冬春'})
        self.assertEqual(by_period['2026-夏秋']['period_text'], '2026年夏秋季')
        self.assertEqual(by_period['2026-冬春']['period_text'], '2026年冬春季')
        # 航季边界：10月最后一个周日（2026-10-25）当日已属冬春季
        self.make_manual_ledger(self.system_a, '2026-10-25',
                                ledger_type=LEDGER_TYPE_SEASONAL)
        data = self.client.get(
            GROUPS_URL, {'ledger_type': LEDGER_TYPE_SEASONAL}).json()['data']['data']
        winter = [g for g in data if g['maintenance_period'] == '2026-冬春'][0]
        self.assertEqual(winter['total'], 2)
        # 次年1月仍属上一年10月末开始的冬春航季
        self.make_manual_ledger(self.system_b, '2026-01-15',
                                ledger_type=LEDGER_TYPE_SEASONAL)
        data = self.client.get(
            GROUPS_URL, {'ledger_type': LEDGER_TYPE_SEASONAL}).json()['data']['data']
        winter = [g for g in data if g['maintenance_period'] == '2025-冬春'][0]
        self.assertEqual(winter['total'], 1)

    def test_status_filter(self):
        # 历史手工台账真实提交后，draft 过滤只剩两张批量壳，reviewed 命中已复核
        ledger = OperationLedger.objects.exclude(system=self.system_a).first()
        resp = post_json(self.client, '%s/%d/submit/' % (LEDGERS_URL, ledger.id), {})
        self.assertFalse(resp.json().get('error'), resp.json())
        data = self.client.get(GROUPS_URL, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'draft'}).json()['data']['data']
        self.assertEqual(data[0]['total'], 2)
        data = self.client.get(GROUPS_URL, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'submitted'}).json()['data']['data']
        self.assertEqual(data[0]['total'], 1)
        data = self.client.get(GROUPS_URL, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'reviewed'}).json()['data']['data']
        self.assertEqual(data, [])

    def test_system_filter_hits_header_and_item_links(self):
        # 表头级系统命中（批量新增台账）
        data = self.client.get(GROUPS_URL, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'system': self.system_a.id}).json()['data']['data']
        self.assertEqual(data[0]['total'], 1)
        self.assertEqual(
            {row['system_name'] for row in data[0]['ledgers']}, {'DVOR系统'})
        # 明细系统命中（历史台账）
        data = self.client.get(GROUPS_URL, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'system': self.system_b.id}).json()['data']['data']
        self.assertEqual(data[0]['total'], 2)

    def test_invalid_ledger_type_rejected(self):
        resp = self.client.get(GROUPS_URL, {'ledger_type': 'inspection'})
        self.assertIn('不再支持', resp.json()['error'])
        resp = self.client.get(GROUPS_URL, {})
        self.assertTrue(resp.json().get('error'))

    def test_flat_list_system_filter_hits_header_system(self):
        # 统一列表的系统筛选同样命中表头级系统（此前仅按明细关联）
        resp = self.client.get(LEDGERS_URL + '/', {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'system': self.system_a.id})
        body = resp.json()['data']
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['data'][0]['system_name'], 'DVOR系统')

    def test_options_return_all_systems_active_first(self):
        make_system(self.user, system_code='SYS-C', name='退役系统', is_active=False)
        options = self.client.get(BATCH_URL).json()['data']['data']
        self.assertEqual(len(options), 3)
        self.assertTrue(options[0]['is_active'])
        self.assertFalse(options[-1]['is_active'])
        names = {o['name'] for o in options}
        self.assertIn('退役系统', names)
