# -*- coding: utf-8 -*-
"""列表与查询稳定契约测试（分页 / 排序 / 过滤 / 组合条件 / 租户隔离）。"""
from datetime import date, datetime, timedelta

from apps.contract_agreement.models import ContractAgreement
from apps.contract_agreement.tasks import scan_contract_agreement_expiration
from .base import (ContractTestCase, make_agreement, make_user, make_client,
                   set_created_at, PERM_VIEW)


class ListPaginationTest(ContractTestCase):
    """分页、排序、空数据"""

    def test_empty_list(self):
        body = self.get_json(self.URL)
        self.assertNoError(body)
        self.assertEqual(body['data']['total'], 0)
        self.assertEqual(body['data']['records'], [])
        self.assertEqual(body['data']['page'], 1)
        self.assertEqual(body['data']['page_size'], 20)

    def test_pagination_default_and_slice(self):
        for i in range(25):
            make_agreement(self.user, contract_name=f'分页合同{i}', contract_no=f'NO{i:03d}')
        page1 = self.get_json(self.URL)
        self.assertNoError(page1)
        data = page1['data']
        self.assertEqual(data['total'], 25)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['page_size'], 20)
        self.assertEqual(len(data['records']), 20)

        page2 = self.get_json(self.URL, {'page': 2})
        self.assertEqual(len(page2['data']['records']), 5)
        self.assertEqual(page2['data']['page'], 2)

        ids_p1 = {r['id'] for r in data['records']}
        ids_p2 = {r['id'] for r in page2['data']['records']}
        self.assertFalse(ids_p1 & ids_p2, '两页数据不应重叠')

    def test_page_size_custom_and_capped(self):
        for i in range(5):
            make_agreement(self.user, contract_name=f'容量合同{i}')
        body = self.get_json(self.URL, {'page_size': 2})
        self.assertEqual(len(body['data']['records']), 2)
        self.assertEqual(body['data']['page_size'], 2)

        body = self.get_json(self.URL, {'page_size': 500})
        self.assertEqual(body['data']['page_size'], 100, 'page_size 应被限制在 100')

    def test_invalid_page_params_fallback(self):
        make_agreement(self.user, contract_name='参数兜底合同')
        body = self.get_json(self.URL, {'page': 'abc', 'page_size': 'xyz'})
        self.assertNoError(body)
        self.assertEqual(body['data']['page'], 1)
        self.assertEqual(body['data']['page_size'], 20)

    def test_default_sort_created_at_desc(self):
        a = make_agreement(self.user, contract_name='最早')
        b = make_agreement(self.user, contract_name='中间')
        c = make_agreement(self.user, contract_name='最新')
        set_created_at(a, datetime(2026, 1, 1, 8, 0, 0))
        set_created_at(c, datetime(2026, 3, 1, 8, 0, 0))
        set_created_at(b, datetime(2026, 2, 1, 8, 0, 0))
        body = self.get_json(self.URL)
        names = [r['contract_name'] for r in body['data']['records']]
        self.assertEqual(names, ['最新', '中间', '最早'])


class ListFilterTest(ContractTestCase):
    """单项过滤"""

    def setUp(self):
        super().setUp()
        self.base = dict(created_by=self.user)
        self.a1 = make_agreement(self.user, contract_name='设备采购合同A', contract_no='HT-2026-001',
                                 contract_type='device_purchase', signing_party='华为技术有限公司',
                                 has_fee=True, fee_amount=1000, fee_detail='首付500',
                                 valid_start_date=self.today - timedelta(days=10),
                                 valid_end_date=self.today + timedelta(days=30))
        self.a2 = make_agreement(self.user, contract_name='信息引接合同B', contract_no='HT-2026-002',
                                 contract_type='info_access', signing_party='中兴通讯股份有限公司',
                                 has_fee=False,
                                 valid_start_date=self.today - timedelta(days=100),
                                 valid_end_date=self.today + timedelta(days=300))
        self.a3 = make_agreement(self.user, contract_name='服务保障协议C', contract_no='HT-2026-003',
                                 contract_type='service_guarantee', signing_party='某某服务中心',
                                 has_fee=False,
                                 valid_start_date=self.today - timedelta(days=400),
                                 valid_end_date=self.today - timedelta(days=5))
        # 同步一次到期状态（等价于每日 Celery 扫描），使 DB status 与展示口径一致
        scan_contract_agreement_expiration.apply()

    def _ids(self, params):
        body = self.get_json(self.URL, params)
        self.assertNoError(body)
        return {r['id'] for r in body['data']['records']}

    def test_filter_contract_name(self):
        self.assertEqual(self._ids({'contract_name': '设备采购'}), {self.a1.id})
        self.assertEqual(self._ids({'contract_name': '合同'}), {self.a1.id, self.a2.id})

    def test_filter_contract_no(self):
        self.assertEqual(self._ids({'contract_no': 'HT-2026-002'}), {self.a2.id})

    def test_filter_contract_type(self):
        self.assertEqual(self._ids({'contract_type': 'info_access'}), {self.a2.id})
        self.assertEqual(self._ids({'contract_type': 'service_guarantee'}), {self.a3.id})

    def test_filter_signing_party(self):
        self.assertEqual(self._ids({'signing_party': '中兴'}), {self.a2.id})

    def test_filter_has_fee(self):
        self.assertEqual(self._ids({'has_fee': 'true'}), {self.a1.id})
        self.assertEqual(self._ids({'has_fee': 'false'}), {self.a2.id, self.a3.id})

    def test_filter_valid_end_range(self):
        body = self.get_json(self.URL, {
            'valid_end_from': str(self.today + timedelta(days=10)),
            'valid_end_to': str(self.today + timedelta(days=100)),
        })
        self.assertNoError(body)
        self.assertEqual({r['id'] for r in body['data']['records']}, {self.a1.id})

    def test_filter_valid_start_range(self):
        body = self.get_json(self.URL, {
            'valid_start_from': str(self.today - timedelta(days=50)),
            'valid_start_to': str(self.today),
        })
        self.assertNoError(body)
        self.assertEqual({r['id'] for r in body['data']['records']}, {self.a1.id})

    def test_filter_status_three_states(self):
        """三态筛选按 valid_to 实时范围过滤：a1(+30d)=expiring、a2(+300d)=normal、a3(-5d)=expired。"""
        self.assertEqual(self._ids({'status': 'normal'}), {self.a2.id})
        self.assertEqual(self._ids({'status': 'expiring'}), {self.a1.id})
        self.assertEqual(self._ids({'status': 'expired'}), {self.a3.id})

    def test_combined_filters(self):
        ids = self._ids({'contract_type': 'device_purchase', 'has_fee': 'true',
                         'contract_name': '设备采购'})
        self.assertEqual(ids, {self.a1.id})

    def test_combined_filters_no_match(self):
        ids = self._ids({'contract_type': 'info_access', 'has_fee': 'true'})
        self.assertEqual(ids, set())

    def test_clear_filters_returns_all(self):
        self.assertEqual(len(self._ids({})), 3)

    def test_filters_preserved_across_pages(self):
        body = self.get_json(self.URL, {'has_fee': 'false', 'page': 1, 'page_size': 1})
        self.assertNoError(body)
        self.assertEqual(body['data']['total'], 2)
        self.assertEqual(body['data']['page'], 1)

    def test_status_filter_matches_computed_status(self):
        """列表 status 过滤口径必须与展示的 computed_status 一致。

        场景：合同创建时截止日期在未来（DB status=normal），随后时间越过截止日期
        但 Celery 扫描尚未执行。此时列表展示应为 expired，
        用 status=expired 过滤也应命中该记录。
        """
        ContractAgreement.objects.filter(pk=self.a2.pk).update(
            valid_end_date=self.today - timedelta(days=1))
        body = self.get_json(self.URL, {'contract_name': '信息引接合同B'})
        self.assertNoError(body)
        self.assertEqual(body['data']['records'][0]['computed_status'], 'expired',
                         '展示状态应实时计算为 expired')
        self.assertEqual({r['id'] for r in self.get_json(self.URL, {'status': 'expired'})['data']['records']},
                         {self.a2.id, self.a3.id},
                         'status=expired 过滤应命中已到期的合同（含未扫描的）')


class ListTenantIsolationTest(ContractTestCase):
    """租户隔离"""

    def test_other_tenant_data_not_visible(self):
        mine = make_agreement(self.user, contract_name='本租户合同', tenant_id='admin')
        theirs_user = make_user('qa_tenant_b', [PERM_VIEW], tenant_id='t_b')
        theirs = make_agreement(theirs_user, contract_name='他租户合同', tenant_id='t_b')

        body = self.get_json(self.URL)
        ids = {r['id'] for r in body['data']['records']}
        self.assertIn(mine.id, ids)
        self.assertNotIn(theirs.id, ids)

        body_b = self.get_json(self.URL, client=make_client(theirs_user))
        ids_b = {r['id'] for r in body_b['data']['records']}
        self.assertIn(theirs.id, ids_b)
        self.assertNotIn(mine.id, ids_b)

    def test_filters_do_not_leak_other_tenant(self):
        theirs_user = make_user('qa_tenant_c', [PERM_VIEW], tenant_id='t_c')
        make_agreement(theirs_user, contract_name='跨租户泄漏探测合同', tenant_id='t_c')
        body = self.get_json(self.URL, {'contract_name': '跨租户泄漏探测合同'})
        self.assertEqual(body['data']['total'], 0)

    def test_superuser_sees_all_tenants(self):
        """超管跨租户可见为产品设计（apply_tenant_filter 放行）。"""
        theirs_user = make_user('qa_tenant_d', [PERM_VIEW], tenant_id='t_d')
        theirs = make_agreement(theirs_user, contract_name='超管可见合同', tenant_id='t_d')
        supper = make_user('qa_supper_list', is_supper=True)
        body = self.get_json(self.URL, client=make_client(supper))
        ids = {r['id'] for r in body['data']['records']}
        self.assertIn(theirs.id, ids)
