# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""规章管理缺陷复现测试（defect_reproduction）

候选缺陷清单（审查 views.py 得出，断言一律指向期望的正确行为，
修复前失败即证明缺陷真实存在，修复后必须全部通过）：

B1  生效日期早于发布日期：
    模型有 DB 级 CheckConstraint reg_effective_after_publish，
    但创建/编辑视图未做业务校验，直接触发 IntegrityError -> HTTP 500。
    前端 Form.js 两个 DatePicker 未做先后关系校验，正常用户即可触发。
    期望：返回 json_response(error='生效日期不能早于发布日期')，不落库。

B2  规章名称缺失校验不对称：
    创建时 title 必填，但编辑 PUT 时 title 传空字符串/纯空白可直接把
    名称清空入库；创建时纯空白字符串（' '）也能通过 JsonParser 空值判断。
    期望：创建与编辑均拒绝空/纯空白名称。

B3  category_id 传 0 或空字符串：
    _validate_category 将 falsy 值放行为"无分类"，随后
    create(category_id=0) / save(category_id='') 触发数据库层错误 -> 500。
    期望：创建时按 None 处理；编辑时视为"清空分类"（置 None）。

B4  列表页附件 N+1 查询：
    RegulationListView 使用 prefetch_related('attachments')，
    但 _serialize_regulation 内再 .filter(is_deleted=False)，
    过滤操作绕过 prefetch 缓存，每行规章额外执行一次附件查询。
    期望：附件查询次数不随行数增长（每页固定 1 次）。
"""
import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.regulation.models import Regulation, RegulationAttachment
from apps.regulation.tests.test_smoke import RegulationBaseTestCase


class DateOrderConstraintTests(RegulationBaseTestCase):
    """B1：生效日期早于发布日期应返回业务错误而非 500"""

    def test_create_effective_before_publish_returns_json_error(self):
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '日期倒置规章',
            'rule_no': 'B1-001',
            'publish_date': '2026-08-01',
            'effective_date': '2026-07-01',
        }, content_type='application/json')
        data = resp.json()
        self.assertIn('生效日期', data['error'])
        self.assertFalse(Regulation.objects.filter(rule_no='B1-001').exists())

    def test_create_effective_equal_publish_allowed(self):
        """生效日期等于发布日期应允许（约束为 >=）"""
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '同日生效规章',
            'rule_no': 'B1-002',
            'publish_date': '2026-08-01',
            'effective_date': '2026-08-01',
        }, content_type='application/json')
        self.assertEqual(resp.json().get('error', ''), '')

    def test_edit_effective_before_publish_returns_json_error(self):
        """编辑时把生效日期改到发布日期之前应返回业务错误，且不落库"""
        self.regulation.publish_date = datetime.date(2026, 8, 1)
        self.regulation.save(update_fields=['publish_date'])
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'effective_date': '2026-07-01'},
            content_type='application/json',
        )
        data = resp.json()
        self.assertIn('生效日期', data['error'])
        self.regulation.refresh_from_db()
        self.assertIsNone(self.regulation.effective_date)

    def test_edit_publish_after_effective_returns_json_error(self):
        """编辑时把发布日期改到生效日期之后同样应返回业务错误"""
        self.regulation.effective_date = datetime.date(2026, 7, 1)
        self.regulation.save(update_fields=['effective_date'])
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'publish_date': '2026-08-01'},
            content_type='application/json',
        )
        data = resp.json()
        self.assertIn('生效日期', data['error'])
        self.regulation.refresh_from_db()
        self.assertIsNone(self.regulation.publish_date)

    def test_edit_clear_publish_date_allowed_when_effective_exists(self):
        """清空发布日期不应触发日期先后校验"""
        self.regulation.publish_date = datetime.date(2026, 8, 1)
        self.regulation.effective_date = datetime.date(2026, 9, 1)
        self.regulation.save(update_fields=['publish_date', 'effective_date'])
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'publish_date': ''},
            content_type='application/json',
        )
        self.assertEqual(resp.json().get('error', ''), '')
        self.regulation.refresh_from_db()
        self.assertIsNone(self.regulation.publish_date)


class TitleValidationTests(RegulationBaseTestCase):
    """B2：规章名称空值/纯空白校验（创建与编辑对称）"""

    def test_create_whitespace_title_rejected(self):
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '   ',
            'rule_no': 'B2-001',
        }, content_type='application/json')
        data = resp.json()
        self.assertIn('规章名称', data['error'])
        self.assertFalse(Regulation.objects.filter(rule_no='B2-001').exists())

    def test_edit_empty_title_rejected(self):
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'title': ''},
            content_type='application/json',
        )
        data = resp.json()
        self.assertIn('规章名称', data['error'])
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.title, '测试规章')

    def test_edit_whitespace_title_rejected(self):
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'title': '   '},
            content_type='application/json',
        )
        data = resp.json()
        self.assertIn('规章名称', data['error'])
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.title, '测试规章')

    def test_edit_normal_title_still_works(self):
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'title': '新名称'},
            content_type='application/json',
        )
        self.assertEqual(resp.json().get('error', ''), '')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.title, '新名称')


class CategoryIdFalsyTests(RegulationBaseTestCase):
    """B3：category_id 传 0 / 空字符串不应触发 500"""

    def test_create_category_id_zero_treated_as_none(self):
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '零分类规章',
            'rule_no': 'B3-001',
            'category_id': 0,
        }, content_type='application/json')
        self.assertEqual(resp.json().get('error', ''), '')
        reg = Regulation.objects.get(rule_no='B3-001')
        self.assertIsNone(reg.category_id)

    def test_create_category_id_empty_string_treated_as_none(self):
        resp = self.uploader_client.post('/regulation/create/', {
            'title': '空串分类规章',
            'rule_no': 'B3-002',
            'category_id': '',
        }, content_type='application/json')
        self.assertEqual(resp.json().get('error', ''), '')
        reg = Regulation.objects.get(rule_no='B3-002')
        self.assertIsNone(reg.category_id)

    def test_edit_category_id_zero_clears_category(self):
        """编辑时 category_id 传 0 视为清空分类"""
        self.assertEqual(self.regulation.category_id, self.leaf_cat.id)
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'category_id': 0},
            content_type='application/json',
        )
        self.assertEqual(resp.json().get('error', ''), '')
        self.regulation.refresh_from_db()
        self.assertIsNone(self.regulation.category_id)

    def test_edit_category_id_empty_string_clears_category(self):
        """编辑时 category_id 传空字符串视为清空分类（前端清空下拉的契约值）"""
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'category_id': ''},
            content_type='application/json',
        )
        self.assertEqual(resp.json().get('error', ''), '')
        self.regulation.refresh_from_db()
        self.assertIsNone(self.regulation.category_id)

    def test_edit_category_id_not_provided_keeps_category(self):
        """编辑时不传 category_id 保持原分类不变"""
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/',
            {'title': '仅改名'},
            content_type='application/json',
        )
        self.assertEqual(resp.json().get('error', ''), '')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.category_id, self.leaf_cat.id)


class ListAttachmentQueryCountTests(RegulationBaseTestCase):
    """B4：列表页附件序列化不得随行数产生 N+1 查询"""

    def _make_attachment(self, reg, name='a.pdf'):
        return RegulationAttachment.objects.create(
            regulation=reg,
            original_name=name,
            stored_name=name,
            file_path=f'regulation/{reg.id}/2026/08/{name}',
            file_size=1,
            file_type='pdf',
        )

    def test_list_attachments_query_count_constant(self):
        """5 行规章（各带附件）的列表请求，附件表查询应 ≤2 次"""
        regs = [self.regulation, self.regulation2]
        for i in range(3):
            regs.append(Regulation.objects.create(
                title=f'翻页规章{i}', rule_no=f'B4-00{i}',
                status=Regulation.STATUS_ACTIVE,
            ))
        for reg in regs:
            self._make_attachment(reg)

        with CaptureQueriesContext(connection) as ctx:
            resp = self.viewer_client.get('/regulation/', {'page_size': '100'})
        self.assertEqual(resp.json().get('error', ''), '')
        self.assertEqual(resp.json()['data']['total'], 5)

        att_queries = [
            q for q in ctx.captured_queries
            if 'tdyw_regulation_attachment' in q['sql']
        ]
        self.assertLessEqual(
            len(att_queries), 2,
            f'5 行规章产生了 {len(att_queries)} 次附件表查询，'
            '存在 N+1：prefetch_related 被 .filter(is_deleted=False) 击穿。'
        )

    def test_list_attachments_content_correct(self):
        """修复查询方式后列表附件内容仍正确（过滤软删除、按序返回）"""
        reg = self.regulation
        att1 = self._make_attachment(reg, 'a.pdf')
        att2 = self._make_attachment(reg, 'b.pdf')
        RegulationAttachment.objects.filter(pk=att2.pk).update(is_deleted=True)

        resp = self.viewer_client.get('/regulation/', {'page_size': '100'})
        items = resp.json()['data']['items']
        target = next(it for it in items if it['id'] == reg.id)
        att_files = [a['file_name'] for a in target['attachments']]
        self.assertEqual(att_files, ['a.pdf'])
        self.assertTrue(att1.file_path)
