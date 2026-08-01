# -*- coding: utf-8 -*-
"""
规章管理模块 CRUD 可靠性审计测试

审计范围：apps/regulation/ 全模块
审计维度：
  R1 (P0 BUG): check_recent_duplicate(Regulation) FieldError
  R2 (P1):     RegulationDetailView.put save() 无 update_fields
  R3 (P1):     CategoryDetailView.put save() 无 update_fields
  R4 (P1):     RegulationRetireView.post save() 无 update_fields
  R5 (P2):     Delete regulation: 软删除附件后 CASCADE 硬删除（冗余操作）
  R6 (P2):     RegulationListView __icontains 生成 LIKE '%xxx%' 绕过索引
  R7 (P2):     RegulationListView page/page_size 被重复解析（死代码）
  R8 (P2→已排除): ORDER BY -effective_date NULL 排序行为验证
  R9 (P2):     附件预览视图 is_deleted 检查一致性

运行方式（Docker 容器内）:
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.regulation.crud_audit_tests --noinput -v2
"""
import json
import time
import tempfile
import shutil
from unittest.mock import patch

from django.test import TestCase, Client
from django.utils import timezone
from django.db import connection

from apps.account.models import User
from apps.setting.utils import AppSetting
from apps.regulation.models import Regulation, RegulationCategory, RegulationAttachment
from libs.idempotency import check_recent_duplicate


def _make_user(username, perms=None, is_supper=False):
    """创建测试用户并设置权限缓存"""
    token = (username * 10)[:32]
    user = User.objects.create(
        username=username,
        nickname=username,
        password_hash='x',
        is_active=True,
        is_supper=is_supper,
        access_token=token,
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01',
        last_ip='127.0.0.1',
        type='default',
    )
    if not is_supper:
        user.set_perms_cache(set(perms or []), version=0)
    return user


ALL_REG_PERMS = [
    'document.regulation.view',
    'document.regulation.add',
    'document.regulation.edit',
    'document.regulation.delete',
    'document.regulation.upload',
    'document.regulation.download',
    'document.regulation.category_manage',
]


def _make_client(user):
    """创建带认证头的测试客户端"""
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


class RegulationAuditBase(TestCase):
    """审计测试基类"""

    def setUp(self):
        self._tmp_storage_base = tempfile.mkdtemp()
        self._patcher = patch(
            'apps.regulation.storage.get_document_storage_base',
            return_value=self._tmp_storage_base,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self._tmp_storage_base, ignore_errors=True))
        AppSetting.set('bind_ip', False)

        self.admin = _make_user('reg_audit_admin', ALL_REG_PERMS)
        self.client = _make_client(self.admin)

        self.root_cat = RegulationCategory.objects.create(
            name='审计根分类', created_by=self.admin
        )
        self.child_cat = RegulationCategory.objects.create(
            name='审计子分类', parent=self.root_cat, created_by=self.admin
        )
        self.leaf_cat = RegulationCategory.objects.create(
            name='审计叶分类', parent=self.child_cat, created_by=self.admin
        )

    def make_regulation(self, **overrides):
        defaults = {
            'title': '审计规章测试',
            'rule_no': 'AUDIT-001',
            'category': self.leaf_cat,
            'issuing_authority': '审计部门',
            'biz_type': '安全',
            'publish_date': '2026-01-01',
            'effective_date': '2026-02-01',
            'status': 'active',
            'updated_by': self.admin,
        }
        defaults.update(overrides)
        return Regulation.objects.create(**defaults)

    def make_attachment(self, reg, **overrides):
        defaults = {
            'regulation': reg,
            'original_name': 'test.pdf',
            'file_path': f'regulation/{reg.id}/2026/07/test.pdf',
            'file_size': 1024,
            'file_hash': 'dummy_hash',
            'uploaded_by': self.admin,
        }
        defaults.update(overrides)
        return RegulationAttachment.objects.create(**defaults)


# ══════════════════════════════════════════════
# R1 (P0 BUG): check_recent_duplicate(Regulation) FieldError
# ══════════════════════════════════════════════

class R1_CheckRecentDuplicateFieldError(RegulationAuditBase):
    """R1: Regulation 模型无 created_at，check_recent_duplicate 抛 FieldError

    根因：
      - Regulation 只有 updated_at，无 created_at（models.py 确认）
      - check_recent_duplicate 硬编码 created_at__gte（idempotency.py:40）
      - RegulationCreateView.post 调用 check_recent_duplicate(Regulation, {...})

    影响：
      - 创建规章时每次抛 FieldError -> 500 错误
      - 用户无法通过 API 创建规章
    """

    def test_regulation_model_has_no_created_at(self):
        """确认 Regulation 模型没有 created_at 字段"""
        field_names = {f.name for f in Regulation._meta.get_fields()}
        self.assertNotIn('created_at', field_names)
        self.assertIn('updated_at', field_names)

    def test_check_recent_duplicate_raises_field_error(self):
        """直接调用 check_recent_duplicate(Regulation) 抛 FieldError"""
        from django.core.exceptions import FieldError
        with self.assertRaises(FieldError) as ctx:
            check_recent_duplicate(Regulation, {
                'title': '测试规章',
                'rule_no': 'TEST-001',
            })
        self.assertIn('created_at', str(ctx.exception))

    def test_category_has_created_at_works(self):
        """对比：RegulationCategory 有 created_at，check_recent_duplicate 正常"""
        result = check_recent_duplicate(RegulationCategory, {
            'name': '不存在的分类',
        }, window_seconds=1)
        self.assertFalse(result)

    def test_create_regulation_api_blocked_by_field_error(self):
        """API 创建规章返回非 200（FieldError 被 spug 中间件捕获）"""
        resp = self.client.post(
            '/api/regulation/create/',
            data=json.dumps({
                'title': 'API 创建测试',
                'rule_no': 'API-001',
                'category_id': self.leaf_cat.id,
                'issuing_authority': '测试部门',
                'biz_type': '安全',
                'publish_date': '2026-01-01',
                'effective_date': '2026-02-01',
            }),
            content_type='application/json',
        )
        # spug 中间件捕获 FieldError 后返回 400 + error JSON
        self.assertNotEqual(
            resp.status_code, 200,
            f'创建规章应因 FieldError 失败，但返回 200（R1 可能已修复）'
        )


# ══════════════════════════════════════════════
# R2 (P1): RegulationDetailView.put save() 无 update_fields
# ══════════════════════════════════════════════

class R2_RegulationUpdateNoUpdateFields(RegulationAuditBase):
    """R2: RegulationDetailView.put save() 未指定 update_fields

    根因：
      - views.py: regulation.save()
      - changed dict 记录变更字段，但 save() 保存全部列
      - 并发场景 last-write-wins 覆盖其他字段

    验证方式：
      - ORM 直接模拟并发覆盖
      - connection.queries 检查 UPDATE 语句包含全部列
    """

    def test_concurrent_update_overwrite_risk(self):
        """模拟并发：A 改 title，B 改 rule_no，B 覆盖 A"""
        reg = self.make_regulation(title='并发原始', rule_no='CONC-001')

        reg_a = Regulation.objects.get(pk=reg.pk)
        reg_b = Regulation.objects.get(pk=reg.pk)

        reg_a.title = 'A修改的标题'
        reg_b.rule_no = 'CONC-002'

        reg_a.save()  # 不指定 update_fields -> 保存所有列
        reg_b.save()  # 不指定 update_fields -> 保存所有列，覆盖 A 的 title

        reg.refresh_from_db()
        # B 的 save 覆盖了 A 的 title（因为没指定 update_fields）
        self.assertEqual(
            reg.title, '并发原始',
            'B 的 save() 覆盖了 A 的 title -> 未使用 update_fields（R2 风险确认）'
        )
        self.assertEqual(reg.rule_no, 'CONC-002')

    def test_orm_save_without_update_fields_saves_all(self):
        """验证 ORM save() 不指定 update_fields 时 UPDATE 包含全部列"""
        reg = self.make_regulation()
        old_debug = connection.force_debug_cursor
        connection.force_debug_cursor = True
        try:
            connection.queries_log.clear()
            reg.title = '只改标题'
            reg.save()
            updates = [
                q for q in connection.queries
                if q['sql'].startswith('UPDATE') and 'regulation_regulation' in q['sql']
            ]
        finally:
            connection.force_debug_cursor = old_debug
        self.assertGreaterEqual(len(updates), 1)
        sql = updates[-1]['sql'].lower()
        self.assertIn('biz_type', sql, 'UPDATE 包含未变更的 biz_type 列（R2 风险确认）')


# ══════════════════════════════════════════════
# R3 (P1): CategoryDetailView.put save() 无 update_fields
# ══════════════════════════════════════════════

class R3_CategoryUpdateNoUpdateFields(RegulationAuditBase):
    """R3: CategoryDetailView.put cat.save() 未指定 update_fields"""

    def test_orm_save_without_update_fields_saves_all(self):
        """验证分类 save() 不指定 update_fields 时 UPDATE 包含全部列"""
        cat = self.leaf_cat
        old_debug = connection.force_debug_cursor
        connection.force_debug_cursor = True
        try:
            connection.queries_log.clear()
            cat.name = '只改名称'
            cat.save()
            updates = [
                q for q in connection.queries
                if q['sql'].startswith('UPDATE') and 'regulation_regulationcategory' in q['sql']
            ]
        finally:
            connection.force_debug_cursor = old_debug
        self.assertGreaterEqual(len(updates), 1)
        sql = updates[-1]['sql'].lower()
        self.assertIn('is_leaf', sql, 'UPDATE 包含未变更的 is_leaf 列（R3 风险确认）')


# ══════════════════════════════════════════════
# R4 (P1): RegulationRetireView.post save() 无 update_fields
# ══════════════════════════════════════════════

class R4_RegulationRetireNoUpdateFields(RegulationAuditBase):
    """R4: RegulationRetireView.post save() 未指定 update_fields

    根因：
      - views.py: regulation.save()（只改 status，但保存全部列）
      - 与 R2 相同的并发覆盖风险
    """

    def test_orm_retire_save_saves_all_columns(self):
        """验证废止时 save() UPDATE 包含全部列"""
        reg = self.make_regulation(status='active')
        old_debug = connection.force_debug_cursor
        connection.force_debug_cursor = True
        try:
            connection.queries_log.clear()
            reg.status = 'retired'
            reg.updated_at = timezone.now()
            reg.save()
            updates = [
                q for q in connection.queries
                if q['sql'].startswith('UPDATE') and 'regulation_regulation' in q['sql']
            ]
        finally:
            connection.force_debug_cursor = old_debug
        self.assertGreaterEqual(len(updates), 1)
        sql = updates[-1]['sql'].lower()
        self.assertIn('title', sql, 'UPDATE 包含未变更的 title 列（R4 风险确认）')


# ══════════════════════════════════════════════
# R5 (P2): Delete regulation: 软删除附件后 CASCADE 硬删除
# ══════════════════════════════════════════════

class R5_DeleteCascadeOverwriteSoftDelete(RegulationAuditBase):
    """R5: 删除规章时先软删除附件，然后 CASCADE 硬删除全部附件记录

    根因：
      - views.py RegulationDetailView.delete:
        1. regulation.attachments.update(is_deleted=True, ...)  # 软删除
        2. regulation.delete()  # CASCADE 硬删除所有附件记录
      - RegulationAttachment.regulation on_delete=CASCADE
      - 步骤 1 的软删除被步骤 2 的 CASCADE 硬删除覆盖

    影响：
      - 软删除是冗余操作（白做功）
      - deleted_by/deleted_at 审计信息随记录一起消失
    """

    def test_cascade_hard_deletes_attachment_records(self):
        """删除规章后，RegulationAttachment 记录被 CASCADE 硬删除"""
        reg = self.make_regulation()
        att = self.make_attachment(reg)

        reg.delete()

        self.assertFalse(
            RegulationAttachment.objects.filter(pk=att.pk).exists(),
            'CASCADE 应硬删除附件记录'
        )

    def test_soft_delete_before_cascade_is_redundant(self):
        """验证软删除 update 后 CASCADE 删除：update 是冗余操作"""
        reg = self.make_regulation()
        att = self.make_attachment(reg)

        # 模拟 views.py 的逻辑：先软删除
        reg.attachments.filter(is_deleted=False).update(
            is_deleted=True, deleted_by=self.admin, deleted_at=timezone.now()
        )

        att.refresh_from_db()
        self.assertTrue(att.is_deleted, '软删除已生效')

        # 然后 CASCADE 删除
        reg.delete()

        # 记录不存在了（CASCADE 硬删除覆盖了软删除）
        self.assertFalse(
            RegulationAttachment.objects.filter(pk=att.pk).exists(),
            'CASCADE 硬删除了记录 -> 软删除是冗余操作（R5 风险确认）'
        )


# ══════════════════════════════════════════════
# R6 (P2): RegulationListView __icontains LIKE '%xxx%'
# ══════════════════════════════════════════════

class R6_IcontainsLikePerformance(RegulationAuditBase):
    """R6: RegulationListView __icontains 生成 LIKE '%xxx%' 绕过索引

    根因：
      - views.py: title__icontains, rule_no__icontains 等
      - MariaDB 中 LIKE '%xxx%' 无法使用 B-Tree 索引
      - rule_no/biz_type/issuing_authority 有 db_index=True 但 icontains 无法使用

    影响：
      - 全表扫描，数据量大时性能下降
    """

    def test_icontains_generates_like_pattern(self):
        """验证 __icontains 生成 LIKE '%xxx%' SQL"""
        self.make_regulation(title='安全管理办法', rule_no='SEC-001')

        old_debug = connection.force_debug_cursor
        connection.force_debug_cursor = True
        try:
            connection.queries_log.clear()
            list(Regulation.objects.filter(title__icontains='安全').values_list('id', flat=True))
            selects = [
                q for q in connection.queries
                if q['sql'].startswith('SELECT') and 'regulation_regulation' in q['sql']
            ]
        finally:
            connection.force_debug_cursor = old_debug
        self.assertGreaterEqual(len(selects), 1)
        self.assertIn('LIKE', selects[0]['sql'].upper(), '__icontains 生成 LIKE 查询（R6 风险确认）')

    def test_rule_no_icontains_bypasses_index(self):
        """验证 rule_no__icontains 生成 LIKE '%xxx%' 绕过 db_index"""
        self.make_regulation(rule_no='SEC-001')

        old_debug = connection.force_debug_cursor
        connection.force_debug_cursor = True
        try:
            connection.queries_log.clear()
            list(Regulation.objects.filter(rule_no__icontains='SEC').values_list('id', flat=True))
            selects = [
                q for q in connection.queries
                if q['sql'].startswith('SELECT') and 'regulation_regulation' in q['sql']
            ]
        finally:
            connection.force_debug_cursor = old_debug
        self.assertGreaterEqual(len(selects), 1)
        self.assertIn('LIKE', selects[0]['sql'].upper(), 'rule_no__icontains 生成 LIKE（R6 风险确认）')


# ══════════════════════════════════════════════
# R7 (P2): page/page_size 被重复解析（死代码）
# ══════════════════════════════════════════════

class R7_DeadCodeDoubleParse(RegulationAuditBase):
    """R7: RegulationListView 中 page/page_size 被 JsonParser 和 paginate() 重复解析

    根因：
      - views.py:
        form = JsonParser(Argument('page', ...), Argument('page_size', ...)).parse(request.GET)
        # form.page / form.page_size 从未被使用
        page, page_size = paginate(request, ...)  # 重新从 request.GET 读取

    影响：
      - 死代码，无功能影响
    """

    def test_paginate_reads_from_request_get(self):
        """验证 paginate() 独立从 request.GET 读取"""
        from libs.pagination import paginate
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/regulation/list/?page=3&page_size=50')
        page, page_size = paginate(request, default_page_size=20, max_page_size=100)

        self.assertEqual(page, 3)
        self.assertEqual(page_size, 50)

    def test_max_page_size_enforced(self):
        """验证 paginate() 的 max_page_size 限制生效"""
        from libs.pagination import paginate
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/regulation/list/?page_size=9999')
        _, page_size = paginate(request, default_page_size=20, max_page_size=100)

        self.assertEqual(page_size, 100, 'page_size 应被限制为 max_page_size=100')


# ══════════════════════════════════════════════
# R8 (已排除): ORDER BY -effective_date NULL 排序行为
# ══════════════════════════════════════════════

class R8_NullEffectiveDateOrdering(RegulationAuditBase):
    """R8: 验证 ORDER BY -effective_date 的 NULL 排序行为

    初始假设：
      - MariaDB ORDER BY col DESC 时 NULL 排在最前

    实际测试结果：
      - MariaDB ORDER BY col DESC 时 NULL 排在**最后**（已排除风险）
      - 这是因为 MariaDB 视 NULL 为最低值，DESC 降序时排在末尾
      - 当前行为符合预期（有日期的规章排在前面，无日期的排在后面）

    结论：R8 风险已排除，当前 ordering 行为正确
    """

    def test_null_effective_date_sorts_last_in_desc(self):
        """验证 effective_date 为 NULL 的记录在 DESC 排序中排在最后"""
        reg_with_date = self.make_regulation(title='有日期', effective_date='2026-06-01')
        reg_null_date = self.make_regulation(title='无日期', effective_date=None)

        qs = Regulation.objects.filter(
            id__in=[reg_with_date.id, reg_null_date.id]
        ).order_by('-effective_date')

        # NULL 在 MariaDB DESC 排序中排在最后
        self.assertEqual(
            qs.first().id, reg_with_date.id,
            '有日期的规章排在前面（R8 已排除：当前行为正确）'
        )
        self.assertEqual(
            qs.last().id, reg_null_date.id,
            'NULL effective_date 排在最后（R8 已排除：当前行为正确）'
        )


# ══════════════════════════════════════════════
# R9 (P2): 附件预览视图 is_deleted 检查一致性
# ══════════════════════════════════════════════

class R9_AttachmentDeletedCheck(RegulationAuditBase):
    """R9: RegulationAttachmentPreviewFileView 未用 _get_attachment 而是直接 get(pk=...)

    根因：
      - views.py: att = regulation.attachments.get(pk=att_id)  # 不含 is_deleted filter
      - 对比：_get_attachment 先 filter(is_deleted=False)，返回 None 表示不存在

    影响：
      - 不一致模式，但功能正确（get 后检查 att.is_deleted）
      - 无安全风险，仅维护性问题
    """

    def test_soft_deleted_attachment_accessible_by_pk(self):
        """验证软删除附件仍可被 get(pk=...) 检索到"""
        reg = self.make_regulation()
        att = self.make_attachment(
            reg, original_name='deleted.pdf',
            is_deleted=True, deleted_by=self.admin, deleted_at=timezone.now(),
        )

        retrieved = reg.attachments.get(pk=att.pk)
        self.assertTrue(retrieved.is_deleted, '软删除附件仍可被 get(pk=) 检索')

    def test_filter_is_deleted_excludes_soft_deleted(self):
        """验证 filter(is_deleted=False) 排除软删除记录"""
        reg = self.make_regulation()
        att_deleted = self.make_attachment(
            reg, original_name='deleted.pdf',
            is_deleted=True, deleted_by=self.admin, deleted_at=timezone.now(),
        )
        att_active = self.make_attachment(reg, original_name='active.pdf')

        active = reg.attachments.filter(is_deleted=False)
        self.assertIn(att_active, active)
        self.assertNotIn(att_deleted, active)
