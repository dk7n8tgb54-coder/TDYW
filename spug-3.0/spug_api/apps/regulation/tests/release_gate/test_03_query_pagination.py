"""R-03 查询、筛选、分页与 N+1（stable_contract）。

覆盖用户要求：
- 关键字按规章名称或编号查询
- 业务类型、发文单位、状态、分类组合筛选
- page / page_size 边界值和非法值
- 空结果、总数、页码越界
- 预取附件时不存在明显 N+1
- 列表中只返回未软删除附件，附件顺序稳定
"""
import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.regulation.models import Regulation, RegulationAttachment
from .base import RegulationGateTestCase


class RegulationFilterTests(RegulationGateTestCase):
    """R-03-01 关键字与组合筛选"""

    def setUp(self):
        super().setUp()
        Regulation.objects.all().delete()
        self.r1 = Regulation.objects.create(
            title='民用航空空中交通管理规则', rule_no='CCAR-93',
            biz_type='空管', issuing_authority='民航局',
            category=self.leaf_cat, status=Regulation.STATUS_ACTIVE,
            publish_date=datetime.date(2026, 1, 1),
            effective_date=datetime.date(2026, 3, 1))
        self.r2 = Regulation.objects.create(
            title='无线电管理规定', rule_no='SRRC-2026-01',
            biz_type='无线电', issuing_authority='工信部',
            status=Regulation.STATUS_RETIRED,
            publish_date=datetime.date(2026, 2, 1),
            effective_date=datetime.date(2026, 6, 1))

    def test_keyword_matches_title_contains(self):
        resp = self.viewer_client.get('/regulation/', {'keyword': '空中交通'})
        ids = [it['id'] for it in resp.json()['data']['items']]
        self.assertEqual(ids, [self.r1.id])

    def test_keyword_matches_rule_no_prefix_only(self):
        """rule_no 走 startswith：前缀命中，中段不命中"""
        hit = self.viewer_client.get('/regulation/', {'keyword': 'CCAR'})
        self.assertEqual([it['id'] for it in hit.json()['data']['items']], [self.r1.id])
        miss = self.viewer_client.get('/regulation/', {'keyword': '93'})
        self.assertEqual(miss.json()['data']['total'], 0,
                         'rule_no 仅按前缀匹配，中段关键字不命中')

    def test_filter_by_status(self):
        resp = self.viewer_client.get('/regulation/', {'status': 'retired'})
        self.assertEqual([it['id'] for it in resp.json()['data']['items']], [self.r2.id])

    def test_filter_by_biz_type_prefix(self):
        resp = self.viewer_client.get('/regulation/', {'biz_type': '无线'})
        self.assertEqual([it['id'] for it in resp.json()['data']['items']], [self.r2.id])

    def test_filter_by_issuing_authority_prefix(self):
        resp = self.viewer_client.get('/regulation/', {'issuing_authority': '民航'})
        self.assertEqual([it['id'] for it in resp.json()['data']['items']], [self.r1.id])

    def test_filter_by_category(self):
        resp = self.viewer_client.get('/regulation/', {'category_id': self.leaf_cat.id})
        self.assertEqual([it['id'] for it in resp.json()['data']['items']], [self.r1.id])
        empty = self.viewer_client.get('/regulation/', {'category_id': 999999})
        self.assertEqual(empty.json()['data']['total'], 0)

    def test_combined_filters(self):
        resp = self.viewer_client.get('/regulation/', {
            'status': 'active', 'biz_type': '空管', 'issuing_authority': '民航',
            'category_id': self.leaf_cat.id, 'keyword': '空中交通'})
        self.assertEqual([it['id'] for it in resp.json()['data']['items']], [self.r1.id])

    def test_effective_date_range_filter(self):
        resp = self.viewer_client.get('/regulation/', {
            'effective_start': '2026-05-01', 'effective_end': '2026-12-31'})
        self.assertEqual([it['id'] for it in resp.json()['data']['items']], [self.r2.id])

    def test_empty_result_returns_zero_total(self):
        resp = self.viewer_client.get('/regulation/', {'keyword': '不存在的规章关键字'})
        data = resp.json()['data']
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['items'], [])

    def test_list_default_sort_is_effective_date_desc(self):
        resp = self.viewer_client.get('/regulation/')
        ids = [it['id'] for it in resp.json()['data']['items']]
        self.assertEqual(ids, [self.r2.id, self.r1.id])


class RegulationPaginationTests(RegulationGateTestCase):
    """R-03-02 分页边界与非法值"""

    def setUp(self):
        super().setUp()
        Regulation.objects.all().delete()
        for i in range(25):
            Regulation.objects.create(
                title=f'分页规章{i:02d}', rule_no=f'RG-PG-{i:02d}',
                status=Regulation.STATUS_ACTIVE)

    def test_default_page_size_is_20(self):
        resp = self.viewer_client.get('/regulation/')
        data = resp.json()['data']
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['page_size'], 20)
        self.assertEqual(data['total'], 25)
        self.assertEqual(len(data['items']), 20)

    def test_second_page_returns_remainder(self):
        resp = self.viewer_client.get('/regulation/', {'page': 2})
        data = resp.json()['data']
        self.assertEqual(len(data['items']), 5)

    def test_page_size_max_is_capped_at_100(self):
        resp = self.viewer_client.get('/regulation/', {'page_size': 99999})
        self.assertEqual(resp.json()['data']['page_size'], 100)

    def test_page_size_zero_normalized_to_one(self):
        resp = self.viewer_client.get('/regulation/', {'page_size': 0})
        data = resp.json()['data']
        self.assertEqual(data['page_size'], 1)
        self.assertEqual(len(data['items']), 1)

    def test_negative_page_size_normalized_to_one(self):
        resp = self.viewer_client.get('/regulation/', {'page_size': -5})
        self.assertEqual(resp.json()['data']['page_size'], 1)

    def test_page_zero_and_negative_normalized_to_one(self):
        for page in ('0', '-3'):
            resp = self.viewer_client.get('/regulation/', {'page': page})
            self.assertEqual(resp.json()['data']['page'], 1, f'page={page} 应归一为 1')

    def test_non_numeric_page_and_page_size_fall_back_to_defaults(self):
        resp = self.viewer_client.get('/regulation/', {'page': 'abc', 'page_size': 'xyz'})
        data = resp.json()['data']
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['page_size'], 20)

    def test_page_beyond_range_returns_empty_items_with_correct_total(self):
        resp = self.viewer_client.get('/regulation/', {'page': 999})
        data = resp.json()['data']
        self.assertEqual(data['total'], 25)
        self.assertEqual(data['items'], [])

    def test_pagination_does_not_leak_rows(self):
        seen = set()
        for page in (1, 2):
            resp = self.viewer_client.get('/regulation/', {'page': page})
            for it in resp.json()['data']['items']:
                self.assertNotIn(it['id'], seen, '分页不应出现重复行')
                seen.add(it['id'])
        self.assertEqual(len(seen), 25)


class RegulationListAttachmentTests(RegulationGateTestCase):
    """R-03-03 列表附件：过滤、顺序、N+1"""

    def test_soft_deleted_attachment_hidden_from_list(self):
        live = self.make_attachment_record(self.regulation, 'live.pdf')
        dead = self.make_attachment_record(self.regulation, 'dead.pdf')
        RegulationAttachment.objects.filter(pk=dead.pk).update(is_deleted=True)

        resp = self.viewer_client.get('/regulation/', {'page_size': 100})
        target = next(it for it in resp.json()['data']['items']
                      if it['id'] == self.regulation.id)
        self.assertEqual([a['file_name'] for a in target['attachments']], ['live.pdf'])
        self.assertEqual(target['attachments'][0]['id'], live.id)

    def test_attachment_order_is_stable_sort_order_then_id_desc(self):
        base = self.regulation
        a1 = self.make_attachment_record(base, 'a1.pdf')
        a2 = self.make_attachment_record(base, 'a2.pdf')
        a3 = self.make_attachment_record(base, 'a3.pdf')
        RegulationAttachment.objects.filter(pk=a3.pk).update(sort_order=-1)

        resp = self.viewer_client.get('/regulation/', {'page_size': 100})
        target = next(it for it in resp.json()['data']['items'] if it['id'] == base.id)
        ids = [a['id'] for a in target['attachments']]
        self.assertEqual(ids, [a3.id, a2.id, a1.id],
                         'sort_order 升序，同序时 id 倒序')

    def test_no_n_plus_one_on_attachment_prefetch(self):
        regs = [self.regulation, self.regulation2]
        for i in range(8):
            regs.append(Regulation.objects.create(
                title=f'N1规章{i}', rule_no=f'RG-N1-{i}', status=Regulation.STATUS_ACTIVE))
        for reg in regs:
            self.make_attachment_record(reg, f'att_{reg.id}.pdf')

        with CaptureQueriesContext(connection) as ctx:
            resp = self.viewer_client.get('/regulation/', {'page_size': 100})
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(resp.json()['data']['total'], 10)
        att_queries = [q for q in ctx.captured_queries
                       if 'tdyw_regulation_attachment' in q['sql']]
        self.assertLessEqual(len(att_queries), 2,
                             f'10 行规章触发 {len(att_queries)} 次附件表查询，存在 N+1')

    def test_detail_view_returns_only_live_attachments(self):
        self.make_attachment_record(self.regulation, 'live2.pdf')
        dead = self.make_attachment_record(self.regulation, 'dead2.pdf')
        RegulationAttachment.objects.filter(pk=dead.pk).update(is_deleted=True)
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/')
        self.assertEqual([a['file_name'] for a in resp.json()['data']['attachments']],
                         ['live2.pdf'])
