"""contract_agreement 模块 CRUD 可靠性审计测试

命名规则：
  R1_xxx — 风险确认（FAIL 表示 bug 存在）
  P1_xxx — 优秀实践确认（PASS）

运行：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.contract_agreement.crud_audit_tests --noinput
"""
import inspect

from django.db import models
from django.test import SimpleTestCase

from apps.contract_agreement.models import (
    ContractAgreement,
    ContractAgreementReminderAck,
)
from apps.contract_agreement import views as ca_views
from apps.contract_agreement import tasks as ca_tasks


# ──────────────────────────────────────────────
#  §1.1  数据库约束
# ──────────────────────────────────────────────

class TestSection11_DatabaseConstraints(SimpleTestCase):
    """§1.1 数据库约束审计"""

    # -------- PASS --------

    def test_P1_01_has_4_check_constraints(self):
        """P1-01: ContractAgreement 有 4 个 CheckConstraint"""
        names = {c.name for c in ContractAgreement._meta.constraints}
        expected = {
            'contract_type_valid',
            'contract_status_valid',
            'contract_date_order_valid',
            'contract_fee_valid',
        }
        self.assertTrue(
            expected.issubset(names),
            f'缺少 CheckConstraint: 期望 {expected}，实际 {names}',
        )

    def test_P1_02_date_order_check_constraint(self):
        """P1-02: valid_end_date >= valid_start_date 约束存在"""
        constraint = next(
            (c for c in ContractAgreement._meta.constraints
             if c.name == 'contract_date_order_valid'), None,
        )
        self.assertIsNotNone(constraint, '缺少 contract_date_order_valid 约束')
        # 验证约束表达式包含 F('valid_start_date')
        source = str(constraint.check)
        self.assertIn('valid_start_date', source)

    def test_P1_03_fee_valid_check_constraint(self):
        """P1-03: has_fee=False 或 fee_amount>=0 约束存在"""
        constraint = next(
            (c for c in ContractAgreement._meta.constraints
             if c.name == 'contract_fee_valid'), None,
        )
        self.assertIsNotNone(constraint, '缺少 contract_fee_valid 约束')

    def test_P1_04_no_charfield_null_true(self):
        """P1-04: 无 CharField/TextField null=True 违规"""
        violations = []
        for f in ContractAgreement._meta.get_fields():
            if isinstance(f, (models.CharField, models.TextField)):
                if f.null:
                    violations.append(f.name)
        self.assertEqual(violations, [], f'CharField/TextField 禁止 null=True: {violations}')

    def test_P1_05_reminder_ack_unique_constraint_not_null(self):
        """P1-05: ReminderAck 的 UniqueConstraint 中 ack_valid_to 是 NOT NULL DateField"""
        ack_valid_to = ContractAgreementReminderAck._meta.get_field('ack_valid_to')
        self.assertFalse(
            ack_valid_to.null,
            'ack_valid_to 为 NOT NULL，不会因 NULL 导致唯一约束失效',
        )

    def test_P1_06_reminder_ack_unique_constraint_exists(self):
        """P1-06: ReminderAck 有 UniqueConstraint 防重复确认"""
        names = {c.name for c in ContractAgreementReminderAck._meta.constraints}
        self.assertIn('uniq_contract_user_valid_end', names)

    def test_P1_07_has_indexes_covering_queries(self):
        """P1-07: 有 5 个复合索引覆盖常用查询路径"""
        index_names = {idx.name for idx in ContractAgreement._meta.indexes}
        self.assertGreaterEqual(len(index_names), 5, f'索引数量不足: {index_names}')

    def test_P1_08_fk_on_delete_strategy(self):
        """P1-08: created_by/updated_by PROTECT, agreement CASCADE"""
        created_by = ContractAgreement._meta.get_field('created_by')
        self.assertEqual(created_by.remote_field.on_delete, models.PROTECT)
        updated_by = ContractAgreement._meta.get_field('updated_by')
        self.assertEqual(updated_by.remote_field.on_delete, models.PROTECT)
        agreement_fk = ContractAgreementReminderAck._meta.get_field('agreement')
        self.assertEqual(agreement_fk.remote_field.on_delete, models.CASCADE)

    # -------- RISK --------

    def test_R1_01_no_business_unique_key(self):
        """R1-01: ContractAgreement 主表无业务唯一键，重复创建无 DB 层防护"""
        names = {c.name for c in ContractAgreement._meta.constraints}
        unique_constraints = [
            c for c in ContractAgreement._meta.constraints
            if hasattr(c, 'fields') and c.fields
        ]
        self.assertEqual(
            len(unique_constraints), 0,
            f'合同主表无 UniqueConstraint，重复创建仅靠应用层。'
            f'现有 constraints: {names}',
        )

    def test_R1_02_responsible_user_id_is_not_fk(self):
        """R1-02: responsible_user_id 是 IntegerField 非 FK，无引用完整性"""
        field = ContractAgreement._meta.get_field('responsible_user_id')
        self.assertIsInstance(
            field, models.IntegerField,
            'responsible_user_id 应为 IntegerField（当前设计如此），'
            '无 DB 级引用完整性保障，但应用层有 _validate_and_fill_responsible_user 校验',
        )

    def test_R1_03_no_is_deleted_physical_delete(self):
        """R1-03: ContractAgreement 无 is_deleted 字段，使用物理删除"""
        field_names = {f.name for f in ContractAgreement._meta.get_fields()}
        self.assertNotIn(
            'is_deleted', field_names,
            '合同主表无 is_deleted，delete() 是物理删除。'
            '审计日志有记录但数据不可恢复',
        )

    def test_R1_04_reminder_ack_user_id_is_not_fk(self):
        """R1-04: ReminderAck.user_id 是 IntegerField 非 FK"""
        field = ContractAgreementReminderAck._meta.get_field('user_id')
        self.assertIsInstance(
            field, models.IntegerField,
            'user_id 为 IntegerField，用户删除后 reminder_acks 成为孤儿记录',
        )


# ──────────────────────────────────────────────
#  §1.2  事务边界
# ──────────────────────────────────────────────

class TestSection12_TransactionBoundary(SimpleTestCase):
    """§1.2 事务边界审计"""

    # -------- PASS --------

    def test_P2_01_post_create_has_transaction_atomic(self):
        """P2-01: _post_create 内有 transaction.atomic"""
        source = inspect.getsource(ca_views.ContractAgreementView._post_create)
        self.assertIn('transaction.atomic()', source)

    def test_P2_02_post_edit_has_transaction_atomic(self):
        """P2-02: _post_edit 内有 transaction.atomic"""
        source = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        self.assertIn('transaction.atomic()', source)

    def test_P2_03_delete_has_transaction_atomic(self):
        """P2-03: delete 内有 transaction.atomic（附件软删 + 审计 + 合同删除原子）"""
        source = inspect.getsource(ca_views.ContractAgreementView.delete)
        self.assertIn('transaction.atomic()', source)

    def test_P2_04_delete_soft_delete_attachments_inside_transaction(self):
        """P2-04: 合同删除时附件软删除在事务内"""
        source = inspect.getsource(ca_views.ContractAgreementView.delete)
        self.assertIn('soft_delete_by_object', source)
        self.assertIn('transaction.atomic()', source)
        # 验证 soft_delete_by_object 在 atomic 块内
        atomic_start = source.index('transaction.atomic()')
        soft_delete_pos = source.index('soft_delete_by_object')
        self.assertGreater(soft_delete_pos, atomic_start, 'soft_delete_by_object 应在 atomic 块内')

    def test_P2_05_delete_audit_log_inside_transaction(self):
        """P2-05: 合同删除审计日志在事务内"""
        source = inspect.getsource(ca_views.ContractAgreementView.delete)
        atomic_start = source.index('transaction.atomic()')
        audit_pos = source.index('record_audit_event')
        self.assertGreater(audit_pos, atomic_start, 'record_audit_event 应在 atomic 块内')

    def test_P2_06_create_audit_log_inside_transaction(self):
        """P2-06: 创建合同审计日志在事务内"""
        source = inspect.getsource(ca_views.ContractAgreementView._post_create)
        atomic_start = source.index('transaction.atomic()')
        audit_pos = source.index('record_audit_event')
        self.assertGreater(audit_pos, atomic_start, 'record_audit_event 应在 atomic 块内')

    def test_P2_07_edit_audit_log_inside_transaction(self):
        """P2-07: 编辑合同审计日志在事务内"""
        source = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        atomic_start = source.index('transaction.atomic()')
        audit_pos = source.index('record_audit_event')
        self.assertGreater(audit_pos, atomic_start, 'record_audit_event 应在 atomic 块内')

    # -------- RISK --------

    def test_P2_08_attachment_delete_has_transaction_atomic(self):
        """P2-08: AttachmentDeleteView.delete 有 transaction.atomic 包裹（已修复）"""
        source = inspect.getsource(ca_views.AttachmentDeleteView.delete)
        self.assertIn(
            'transaction.atomic()', source,
            '附件删除应有事务包裹：soft_delete + audit_log 原子',
        )

    def test_R2_02_celery_task_loop_no_transaction(self):
        """R2-02: Celery 任务循环内无 transaction.atomic（每条独立 update，风险低）"""
        source = inspect.getsource(ca_tasks.scan_contract_agreement_expiration)
        self.assertNotIn(
            'transaction.atomic', source,
            'Celery 扫描任务循环无事务包裹，但每条 filter(pk=).update() 独立，'
            '重试安全（幂等）。风险低',
        )


# ──────────────────────────────────────────────
#  §1.3  幂等性
# ──────────────────────────────────────────────

class TestSection13_Idempotency(SimpleTestCase):
    """§1.3 幂等性审计"""

    # -------- PASS --------

    def test_P3_01_reminder_ack_idempotent_with_unique_constraint(self):
        """P3-01: ReminderAck 有 UniqueConstraint + IntegrityError 捕获（幂等）"""
        source = inspect.getsource(ca_views.ReminderAckView.post)
        self.assertIn('IntegrityError', source, '应捕获 IntegrityError 实现幂等')
        # 确认 UniqueConstraint 存在
        has_unique = any(
            hasattr(c, 'fields') and 'ack_valid_to' in (c.fields or [])
            for c in ContractAgreementReminderAck._meta.constraints
        )
        self.assertTrue(has_unique, '应有包含 ack_valid_to 的 UniqueConstraint')

    def test_P3_02_celery_task_uses_filter_update_idempotent(self):
        """P3-02: Celery 任务用 filter(pk=).update()（重试幂等）"""
        source = inspect.getsource(ca_tasks.scan_single_contract_agreement)
        self.assertIn(
            'filter(pk=agreement.id).update', source,
            '应使用 filter(pk=).update() 而非 save()，保证重试幂等',
        )

    # -------- RISK --------

    def test_P3_03_post_create_has_dedup(self):
        """P3-03: POST 创建合同有 check_recent_duplicate 去重（已修复）"""
        source = inspect.getsource(ca_views.ContractAgreementView._post_create)
        self.assertIn(
            'check_recent_duplicate', source,
            '创建合同应有 check_recent_duplicate 去重机制',
        )

    def test_R3_02_attachment_upload_no_dedup(self):
        """R3-02: 附件上传无去重（同一文件可重复上传）"""
        source = inspect.getsource(ca_views.AttachmentListView.post)
        self.assertNotIn(
            'check_recent_duplicate', source,
            '附件上传无去重，同一文件可重复上传产生多条附件记录',
        )

    def test_R3_03_no_select_for_update(self):
        """R3-03: 无 select_for_update，编辑并发有竞态风险"""
        views_source = inspect.getsource(ca_views)
        self.assertNotIn(
            'select_for_update', views_source,
            '无悲观锁，两个用户同时编辑同一合同可能后写覆盖先写',
        )


# ──────────────────────────────────────────────
#  §1.5  防误操作与可追溯
# ──────────────────────────────────────────────

class TestSection15_AntiMistake(SimpleTestCase):
    """§1.5 防误操作与可追溯审计"""

    # -------- PASS --------

    def test_P4_01_delete_soft_deletes_attachments_first(self):
        """P4-01: 合同删除时先软删除附件"""
        source = inspect.getsource(ca_views.ContractAgreementView.delete)
        soft_delete_pos = source.index('soft_delete_by_object')
        agreement_delete_pos = source.index('agreement.delete()')
        self.assertGreater(
            agreement_delete_pos, soft_delete_pos,
            '应先软删除附件再物理删除合同',
        )

    def test_P4_02_crud_has_audit_logs(self):
        """P4-02: CRUD 操作有审计日志（create/update/delete）"""
        create_src = inspect.getsource(ca_views.ContractAgreementView._post_create)
        edit_src = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        delete_src = inspect.getsource(ca_views.ContractAgreementView.delete)
        self.assertIn('record_audit_event', create_src, '创建无审计日志')
        self.assertIn('record_audit_event', edit_src, '编辑无审计日志')
        self.assertIn('record_audit_event', delete_src, '删除无审计日志')

    def test_P4_03_reminder_ack_has_audit_log(self):
        """P4-03: 到期提醒确认有审计日志"""
        source = inspect.getsource(ca_views.ReminderAckView.post)
        self.assertIn('record_audit_event', source)

    def test_P4_04_celery_task_has_audit_log(self):
        """P4-04: Celery 批量扫描有审计日志"""
        source = inspect.getsource(ca_tasks.scan_contract_agreement_expiration)
        self.assertIn('log_celery_audit', source)

    def test_P4_05_attachment_delete_has_audit_log(self):
        """P4-05: 附件删除有审计日志"""
        source = inspect.getsource(ca_views.AttachmentDeleteView.delete)
        self.assertIn('record_audit_event', source)

    # -------- RISK --------

    def test_R4_01_physical_delete_no_recovery(self):
        """R4-01: 合同删除是物理删除，数据不可恢复"""
        field_names = {f.name for f in ContractAgreement._meta.get_fields()}
        self.assertNotIn('is_deleted', field_names, '合同主表无逻辑删除，delete() 后数据不可恢复')

    def test_P4_06_attachment_download_has_audit_log(self):
        """P4-06: 附件下载有审计日志（已修复，action='other' + detail.action='download'）"""
        source = inspect.getsource(ca_views.AttachmentDownloadView.get)
        self.assertIn(
            'record_audit_event', source,
            '附件下载应有审计日志，追溯谁下载了附件',
        )
        self.assertIn("'other'", source, 'action 应为 other（CheckConstraint 不允许 download）')

    def test_P4_07_attachment_delete_audit_inside_transaction(self):
        """P4-07: 附件删除审计日志在 transaction.atomic 内（已修复）"""
        source = inspect.getsource(ca_views.AttachmentDeleteView.delete)
        self.assertIn(
            'transaction.atomic()', source,
            '附件删除应有事务包裹，soft_delete + audit_log 原子',
        )

    def test_R4_04_no_batch_delete_endpoint(self):
        """R4-04: 无批量删除端点（单条删除，风险可控）"""
        views_source = inspect.getsource(ca_views)
        # 检查没有批量删除的 URL 模式
        self.assertNotIn(
            'bulk_delete', views_source.lower(),
            '无批量删除端点，单条删除风险较低',
        )


# ──────────────────────────────────────────────
#  §2.1  索引与慢查询
# ──────────────────────────────────────────────

class TestSection21_IndexAndSlowQuery(SimpleTestCase):
    """§2.1 索引与慢查询审计"""

    # -------- PASS --------

    def test_P5_01_list_has_pagination(self):
        """P5-01: 列表查询有分页"""
        source = inspect.getsource(ca_views.ContractAgreementView.get)
        self.assertIn('paginate', source)
        self.assertIn('max_page_size', source)

    def test_P5_02_no_date_year_month_filters(self):
        """P5-02: 无 __date/__year/__month 等绕过索引的查询"""
        source = inspect.getsource(ca_views.ContractAgreementView.get)
        self.assertNotIn('__date', source, '__date 绕过索引')
        self.assertNotIn('__year', source, '__year 绕过索引')
        self.assertNotIn('__month', source, '__month 绕过索引')

    def test_P5_03_no_raw_sql_or_extra(self):
        """P5-03: 无 raw SQL / .extra()"""
        views_source = inspect.getsource(ca_views)
        self.assertNotIn('.raw(', views_source, '不应使用 raw SQL')
        self.assertNotIn('.extra(', views_source, '不应使用 .extra()')

    def test_P5_04_valid_end_date_has_index(self):
        """P5-04: valid_end_date 有索引（到期提醒查询用）"""
        index_fields = []
        for idx in ContractAgreement._meta.indexes:
            index_fields.extend(idx.fields)
        self.assertIn(
            'valid_end_date', index_fields,
            'valid_end_date 应有索引以支持到期提醒范围查询',
        )

    def test_P5_05_date_range_queries_use_gte_lte(self):
        """P5-05: 日期范围查询用 __gte/__lte（可走索引）"""
        source = inspect.getsource(ca_views.ContractAgreementView.get)
        self.assertIn('valid_start_date__gte', source)
        self.assertIn('valid_start_date__lte', source)
        self.assertIn('valid_end_date__gte', source)
        self.assertIn('valid_end_date__lte', source)

    def test_P5_06_reminder_queries_use_range_not_date(self):
        """P5-06: 到期提醒查询用 __lte/__gte 而非 __date"""
        popup_src = inspect.getsource(ca_views.ReminderPopupView.get)
        badge_src = inspect.getsource(ca_views.ContractAgreementBadgeView.get)
        self.assertIn('valid_end_date__lte', popup_src)
        self.assertIn('valid_end_date__lte', badge_src)
        self.assertIn('valid_end_date__gte', badge_src)

    def test_P5_07_select_related_optimization(self):
        """P5-07: 列表用 select_related 避免 N+1 查询"""
        source = inspect.getsource(ca_views.ContractAgreementView.get)
        self.assertIn('select_related', source)

    # -------- RISK --------

    def test_R5_01_contract_name_icontains_cannot_use_index(self):
        """R5-01: contract_name__icontains 生成 LIKE '%xxx%' 无法走 B-Tree 索引"""
        source = inspect.getsource(ca_views.ContractAgreementView.get)
        self.assertIn(
            'contract_name__icontains', source,
            'contract_name__icontains 生成 LIKE "%xxx%"，'
            '前缀通配符无法走 B-Tree 索引。数据量大时需考虑全文搜索',
        )

    def test_R5_02_signing_party_icontains_cannot_use_index(self):
        """R5-02: signing_party__icontains 生成 LIKE '%xxx%' 无法走索引"""
        source = inspect.getsource(ca_views.ContractAgreementView.get)
        self.assertIn(
            'signing_party__icontains', source,
            'signing_party__icontains 生成 LIKE "%xxx%"，'
            'signing_party 无索引，全表扫描',
        )

    def test_R5_03_signing_party_no_index(self):
        """R5-03: signing_party 字段无独立索引"""
        index_fields = []
        for idx in ContractAgreement._meta.indexes:
            index_fields.extend(idx.fields)
        self.assertNotIn(
            'signing_party', index_fields,
            'signing_party 无索引，icontains 查询全表扫描',
        )


# ──────────────────────────────────────────────
#  §2.2  资源兜底
# ──────────────────────────────────────────────

class TestSection22_ResourceLimits(SimpleTestCase):
    """§2.2 资源兜底审计"""

    # -------- PASS --------

    def test_P6_01_celery_soft_time_limit_reasonable(self):
        """P6-01: Celery soft_time_limit=300 合理（5 分钟超时）"""
        source = inspect.getsource(ca_tasks.scan_contract_agreement_expiration)
        self.assertIn('soft_time_limit=300', source)
        self.assertIn('time_limit=600', source)

    def test_P6_02_no_external_http_in_views(self):
        """P6-02: views 中无外部 HTTP 调用"""
        views_source = inspect.getsource(ca_views)
        self.assertNotIn('requests.get', views_source)
        self.assertNotIn('requests.post', views_source)
        self.assertNotIn('urllib.request', views_source)

    def test_P6_03_attachment_config_has_size_limit(self):
        """P6-03: 附件上传有大小限制（50MB）"""
        source = inspect.getsource(ca_views)
        self.assertIn('max_size_mb=50', source)

    def test_P6_04_attachment_config_has_ext_whitelist(self):
        """P6-04: 附件上传有扩展名白名单"""
        source = inspect.getsource(ca_views)
        self.assertIn('allowed_extensions', source)

    # -------- RISK --------

    def test_R6_01_no_concurrency_limit_on_download(self):
        """R6-01: 附件下载无并发限制"""
        source = inspect.getsource(ca_views.AttachmentDownloadView.get)
        self.assertNotIn(
            'semaphore', source.lower(),
            '附件下载无并发限制，大量并发下载可能耗尽带宽',
        )


# ──────────────────────────────────────────────
#  §3.5  安全维度
# ──────────────────────────────────────────────

class TestSection35_Security(SimpleTestCase):
    """§3.5 安全维度审计"""

    # -------- PASS --------

    def test_P7_01_all_views_have_auth_decorator(self):
        """P7-01: 除 PreviewFileView 外所有 View 有 @auth 装饰器"""
        view_classes = [
            ca_views.ContractAgreementView,
            ca_views.ContractAgreementDetailView,
            ca_views.AttachmentListView,
            ca_views.AttachmentDownloadView,
            ca_views.AttachmentPreviewUrlView,
            ca_views.AttachmentDeleteView,
            ca_views.ReminderPopupView,
            ca_views.ReminderAckView,
            ca_views.ContractAgreementBadgeView,
            ca_views.ResponsibleUserListView,
        ]
        for cls in view_classes:
            for method_name in ('get', 'post', 'put', 'delete'):
                method = getattr(cls, method_name, None)
                if method is None:
                    continue
                source = inspect.getsource(method)
                self.assertIn(
                    '@auth', source,
                    f'{cls.__name__}.{method_name} 缺少 @auth 装饰器',
                )

    def test_P7_02_preview_file_view_uses_token_not_auth(self):
        """P7-02: AttachmentPreviewFileView 无 @auth 但用 preview_token 验证"""
        source = inspect.getsource(ca_views.AttachmentPreviewFileView.get)
        self.assertNotIn('@auth', source)
        self.assertIn('preview_token', source, '应使用 preview_token 鉴权')

    def test_P7_03_apply_tenant_filter_on_all_list_queries(self):
        """P7-03: 所有列表/详情查询都有 apply_tenant_filter"""
        views_source = inspect.getsource(ca_views)
        # 统计 apply_tenant_filter 出现次数
        count = views_source.count('apply_tenant_filter')
        self.assertGreaterEqual(
            count, 9,
            f'apply_tenant_filter 出现 {count} 次，应覆盖所有查询入口',
        )

    def test_P7_04_contract_view_get_has_tenant_filter(self):
        """P7-04: ContractAgreementView.get 有 apply_tenant_filter"""
        source = inspect.getsource(ca_views.ContractAgreementView.get)
        self.assertIn('apply_tenant_filter', source)

    def test_P7_05_contract_view_delete_has_tenant_filter(self):
        """P7-05: ContractAgreementView.delete 有 apply_tenant_filter"""
        source = inspect.getsource(ca_views.ContractAgreementView.delete)
        self.assertIn('apply_tenant_filter', source)

    def test_P7_06_contract_view_edit_has_tenant_filter(self):
        """P7-06: ContractAgreementView._post_edit 有 apply_tenant_filter"""
        source = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        self.assertIn('apply_tenant_filter', source)

    def test_P7_07_attachment_list_has_tenant_filter(self):
        """P7-07: AttachmentListView 有 apply_tenant_filter"""
        get_src = inspect.getsource(ca_views.AttachmentListView.get)
        post_src = inspect.getsource(ca_views.AttachmentListView.post)
        self.assertIn('apply_tenant_filter', get_src)
        self.assertIn('apply_tenant_filter', post_src)

    def test_P7_08_reminder_ack_has_tenant_filter(self):
        """P7-08: ReminderAckView 有 apply_tenant_filter"""
        source = inspect.getsource(ca_views.ReminderAckView.post)
        self.assertIn('apply_tenant_filter', source)

    def test_P7_09_reminder_popup_has_tenant_filter(self):
        """P7-09: ReminderPopupView 有 apply_tenant_filter"""
        source = inspect.getsource(ca_views.ReminderPopupView.get)
        self.assertIn('apply_tenant_filter', source)

    def test_P7_10_responsible_user_list_has_tenant_filter(self):
        """P7-10: ResponsibleUserListView 有租户隔离"""
        source = inspect.getsource(ca_views.ResponsibleUserListView.get)
        self.assertIn('tenant_id', source, '非超管应按 tenant_id 过滤')

    def test_P7_11_preview_url_view_has_auth(self):
        """P7-11: AttachmentPreviewUrlView 有 @auth（生成 token 前鉴权）"""
        source = inspect.getsource(ca_views.AttachmentPreviewUrlView.get)
        self.assertIn('@auth', source)

    def test_P7_12_celery_task_scans_all_tenants_appropriate(self):
        """P7-12: Celery 任务无租户过滤（全局扫描，合理）"""
        source = inspect.getsource(ca_tasks.scan_contract_agreement_expiration)
        self.assertIn(
            'ContractAgreement.objects.all()',
            source,
            '全局扫描任务不应过滤租户，应扫描所有租户的合同',
        )

    # -------- RISK --------

    def test_R7_01_attachment_delete_gets_att_without_tenant_filter(self):
        """R7-01: AttachmentDeleteView 先用无租户 filter 获取 att（但 soft_delete 内部有 filter）"""
        source = inspect.getsource(ca_views.AttachmentDeleteView.delete)
        self.assertIn(
            'EvidenceAttachment.objects.filter(pk=form.id).first()',
            source,
            '附件删除先获取 att 记录（无 apply_tenant_filter），'
            '但 AttachmentService.soft_delete 内部有 apply_tenant_filter，'
            '跨租户删除会被 soft_delete 拦截返回错误。'
            '风险：audit_log 可能记录到不存在的 att（已通过 if att 判断规避）',
        )

    def test_R7_02_no_select_for_update_on_edit(self):
        """R7-02: 编辑合同无 select_for_update，并发编辑有竞态"""
        source = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        self.assertNotIn(
            'select_for_update', source,
            '无悲观锁，两个用户同时编辑同一合同可能后写覆盖先写',
        )


# ════════════════════════════════════════════════════════════
#  行为级测试（需要数据库，使用 --keepdb 运行）
#  运行：
#    docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
#      python manage.py test apps.contract_agreement.crud_audit_tests \
#      --keepdb --noinput
# ════════════════════════════════════════════════════════════

import json
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase, override_settings

from apps.contract_agreement.models import (
    ContractAgreement,
    ContractAgreementReminderAck,
)
from apps.evidence.models import EvidenceAttachment
from apps.logs.models import AuditLog
from apps.utils.test_helpers import make_user, make_client, setup_test_env

JSON_CT = 'application/json'


def _valid_contract_data(**overrides):
    """生成合法的合同创建数据（responsible_user_id 需调用时传入）"""
    data = {
        'contract_name': '测试合同',
        'contract_type': 'device_purchase',
        'valid_start_date': '2026-01-01',
        'valid_end_date': '2026-12-31',
        'signing_party': '测试乙方',
        'responsible_user_name': 'placeholder',
        'has_fee': True,
        'fee_amount': '10000.00',
    }
    data.update(overrides)
    return data


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TestSection11_Behavioral(TestCase):
    """§1.1 数据库约束 - 行为级验证"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('admin', is_supper=True)
        self.client = make_client(self.user)

    def test_R1_01_B_duplicate_contract_name_allowed_at_db_level(self):
        """R1-01-B: DB 层无唯一约束，相同名称合同可共存（应用层有 30s 去重）"""
        from datetime import date as _date
        kwargs = dict(
            tenant_id='admin', contract_name='同名合同', contract_type='device_purchase',
            status='normal', valid_start_date=_date(2026, 1, 1), valid_end_date=_date(2026, 12, 31),
            signing_party='乙方', responsible_user_id=self.user.id, responsible_user_name='admin',
            has_fee=False, created_by=self.user,
        )
        ContractAgreement.objects.create(**kwargs)
        ContractAgreement.objects.create(**kwargs)
        count = ContractAgreement.objects.filter(contract_name='同名合同').count()
        self.assertEqual(count, 2, 'DB 层无唯一约束，应允许同名合同')

    def test_P1_02_B_date_order_violated_raises_integrity_error(self):
        """P1-02-B: valid_end < valid_start 触发 CheckConstraint IntegrityError"""
        with self.assertRaises(IntegrityError):
            ContractAgreement.objects.create(
                tenant_id='admin',
                contract_name='日期倒序合同',
                contract_type='device_purchase',
                status='normal',
                valid_start_date=date(2026, 12, 1),
                valid_end_date=date(2026, 1, 1),
                signing_party='乙方',
                responsible_user_id=1,
                responsible_user_name='张三',
                has_fee=False,
                created_by=self.user,
            )

    def test_P1_03_B_fee_required_but_amount_none_raises_integrity_error(self):
        """P1-03-B: has_fee=True 但 fee_amount=None 触发 CheckConstraint"""
        with self.assertRaises(IntegrityError):
            ContractAgreement.objects.create(
                tenant_id='admin',
                contract_name='费用缺失合同',
                contract_type='device_purchase',
                status='normal',
                valid_start_date=date(2026, 1, 1),
                valid_end_date=date(2026, 12, 31),
                signing_party='乙方',
                responsible_user_id=1,
                responsible_user_name='张三',
                has_fee=True,
                fee_amount=None,
                created_by=self.user,
            )

    def test_P1_03_B_negative_fee_amount_raises_integrity_error(self):
        """P1-03-B: fee_amount < 0 触发 CheckConstraint"""
        with self.assertRaises(IntegrityError):
            ContractAgreement.objects.create(
                tenant_id='admin',
                contract_name='负费用合同',
                contract_type='device_purchase',
                status='normal',
                valid_start_date=date(2026, 1, 1),
                valid_end_date=date(2026, 12, 31),
                signing_party='乙方',
                responsible_user_id=1,
                responsible_user_name='张三',
                has_fee=True,
                fee_amount=Decimal('-100.00'),
                created_by=self.user,
            )

    def test_P1_06_B_duplicate_reminder_ack_raises_integrity_error(self):
        """P1-06-B: 重复 ReminderAck 触发 UniqueConstraint"""
        agreement = ContractAgreement.objects.create(
            tenant_id='admin',
            contract_name='提醒测试合同',
            contract_type='device_purchase',
            status='expired',
            valid_start_date=date(2025, 1, 1),
            valid_end_date=date(2026, 1, 1),
            signing_party='乙方',
            responsible_user_id=self.user.id,
            responsible_user_name='admin',
            has_fee=False,
            created_by=self.user,
        )
        # 第一次创建成功
        ContractAgreementReminderAck.objects.create(
            tenant_id='admin',
            agreement=agreement,
            user_id=self.user.id,
            user_name='admin',
            ack_valid_to=agreement.valid_end_date,
        )
        # 第二次创建相同记录应触发 UniqueConstraint
        with self.assertRaises(IntegrityError):
            ContractAgreementReminderAck.objects.create(
                tenant_id='admin',
                agreement=agreement,
                user_id=self.user.id,
                user_name='admin',
                ack_valid_to=agreement.valid_end_date,
            )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TestSection12_Behavioral(TestCase):
    """§1.2 事务边界 - 行为级验证"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('admin', is_supper=True)
        self.client = make_client(self.user)

    def test_P2_01_B_create_contract_and_audit_log_atomic(self):
        """P2-01-B: 创建合同后合同记录和审计日志都存在（事务原子性）"""
        r = self.client.post('/contract-agreement/', _valid_contract_data(responsible_user_id=self.user.id), content_type=JSON_CT)
        self.assertFalse(r.json().get('error'))
        agreement_id = r.json()['data']['id']

        # 合同记录存在
        self.assertTrue(ContractAgreement.objects.filter(pk=agreement_id).exists())
        # 审计日志存在
        audit = AuditLog.objects.filter(
            action='create',
            target_type='contract_agreement',
            target_id=str(agreement_id),
        )
        self.assertTrue(audit.exists(), '创建审计日志应存在')

    def test_P2_03_B_delete_contract_and_audit_log_atomic(self):
        """P2-03-B: 删除合同后审计日志存在（事务内记录）"""
        # 先创建合同
        r = self.client.post('/contract-agreement/', _valid_contract_data(responsible_user_id=self.user.id), content_type=JSON_CT)
        agreement_id = r.json()['data']['id']

        # 删除合同
        r = self.client.delete(f'/contract-agreement/?id={agreement_id}')
        self.assertFalse(r.json().get('error'))

        # 合同已删除
        self.assertFalse(ContractAgreement.objects.filter(pk=agreement_id).exists())
        # 审计日志存在
        audit = AuditLog.objects.filter(
            action='delete',
            target_type='contract_agreement',
            target_id=str(agreement_id),
        )
        self.assertTrue(audit.exists(), '删除审计日志应存在')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TestSection13_Behavioral(TestCase):
    """§1.3 幂等性 - 行为级验证"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('admin', is_supper=True)
        self.client = make_client(self.user)

    def test_P3_03_B_duplicate_post_rejected_by_dedup(self):
        """P3-03-B: 相同数据 POST 两次，第二次被 check_recent_duplicate 拦截（已修复）"""
        data = _valid_contract_data(contract_name='重复提交测试', responsible_user_id=self.user.id)
        r1 = self.client.post('/contract-agreement/', data, content_type=JSON_CT)
        self.assertFalse(r1.json().get('error'))
        r2 = self.client.post('/contract-agreement/', data, content_type=JSON_CT)
        self.assertTrue(r2.json().get('error'), '第二次相同合同应被去重拦截')

        count = ContractAgreement.objects.filter(contract_name='重复提交测试').count()
        self.assertEqual(count, 1, '去重机制应只保留一条记录')

    def test_P3_01_B_duplicate_reminder_ack_is_idempotent(self):
        """P3-01-B: 重复 ack 请求返回成功（IntegrityError 被捕获，幂等）"""
        # 创建一个已过期的合同
        agreement = ContractAgreement.objects.create(
            tenant_id='admin',
            contract_name='到期合同',
            contract_type='device_purchase',
            status='expired',
            valid_start_date=date(2025, 1, 1),
            valid_end_date=date(2026, 1, 1),
            signing_party='乙方',
            responsible_user_id=self.user.id,
            responsible_user_name='admin',
            has_fee=False,
            created_by=self.user,
        )
        # 第一次 ack
        r1 = self.client.post('/contract-agreement/reminders/ack/', {'agreement_id': agreement.id}, content_type=JSON_CT)
        self.assertFalse(r1.json().get('error'))
        self.assertTrue(r1.json()['data']['acked'])

        # 第二次 ack（应幂等返回成功，不报错）
        r2 = self.client.post('/contract-agreement/reminders/ack/', {'agreement_id': agreement.id}, content_type=JSON_CT)
        self.assertFalse(r2.json().get('error'))
        self.assertTrue(r2.json()['data']['acked'])

        # 数据库中只有一条 ack 记录
        count = ContractAgreementReminderAck.objects.filter(agreement_id=agreement.id).count()
        self.assertEqual(count, 1, '重复 ack 应只产生一条记录')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TestSection15_Behavioral(TestCase):
    """§1.5 防误操作与可追溯 - 行为级验证"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('admin', is_supper=True)
        self.client = make_client(self.user)

    def _create_contract(self, **overrides):
        data = _valid_contract_data(responsible_user_id=self.user.id, **overrides)
        r = self.client.post('/contract-agreement/', data, content_type=JSON_CT)
        self.assertFalse(r.json().get('error'))
        return r.json()['data']['id']

    def test_P4_06_B_attachment_download_has_audit_log(self):
        """P4-06-B: 附件下载产生审计日志（已修复）"""
        import os
        from django.conf import settings
        agreement_id = self._create_contract()
        # 创建一个真实的附件文件
        rel_path = 'contract_agreement/test_download_audit.txt'
        abs_dir = os.path.join(settings.MEDIA_ROOT, 'contract_agreement')
        os.makedirs(abs_dir, exist_ok=True)
        abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
        with open(abs_path, 'w') as f:
            f.write('test content')
        # 创建附件记录
        att = EvidenceAttachment.objects.create(
            tenant_id='admin',
            module='contract_agreement',
            object_type='agreement',
            object_id=str(agreement_id),
            file_name='test_download_audit.txt',
            file_size=12,
            file_path=rel_path,
            uploaded_by_id=self.user.id,
            uploaded_by_name='admin',
            is_deleted=False,
        )
        # 下载附件
        r = self.client.get(f'/contract-agreement/attachments/{att.id}/download/')
        # 调试：检查下载是否成功
        if r.status_code != 200:
            import json as _json
            try:
                err_msg = _json.loads(r.content)
            except Exception:
                err_msg = r.content[:200]
            self.fail(f'下载失败 status={r.status_code}: {err_msg}')
        # 验证审计日志已创建（action='other'，detail 含 download）
        download_audits = AuditLog.objects.filter(
            action='other',
            target_type='contract_agreement_attachment',
            target_id=str(agreement_id),
        )
        self.assertTrue(download_audits.exists(), '附件下载应产生审计日志')

    def test_P4_01_B_delete_contract_soft_deletes_attachments(self):
        """P4-01-B: 删除合同时附件被软删除"""
        agreement_id = self._create_contract()
        # 手动创建一条附件记录
        att = EvidenceAttachment.objects.create(
            tenant_id='admin',
            module='contract_agreement',
            object_type='agreement',
            object_id=str(agreement_id),
            file_name='test.pdf',
            file_size=1024,
            file_path='contract_agreement/test.pdf',
            uploaded_by_id=self.user.id,
            uploaded_by_name='admin',
            is_deleted=False,
        )
        # 删除合同
        r = self.client.delete(f'/contract-agreement/?id={agreement_id}')
        self.assertFalse(r.json().get('error'))
        # 附件应被软删除
        att.refresh_from_db()
        self.assertTrue(att.is_deleted, '合同删除时附件应被软删除')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TestSection35_Behavioral(TestCase):
    """§3.5 安全维度 - 行为级验证"""

    _PERMS = [
        'contract_agreement.agreement.view',
        'contract_agreement.agreement.add',
        'contract_agreement.agreement.edit',
        'contract_agreement.agreement.del',
    ]

    def setUp(self):
        setup_test_env(self)
        self.user_a = make_user('user_a', perms=self._PERMS)
        User = type(self.user_a)
        User.objects.filter(pk=self.user_a.pk).update(tenant_id='tenant_a')
        self.user_a.refresh_from_db()
        self.client_a = make_client(self.user_a)

        self.user_b = make_user('user_b', perms=self._PERMS)
        User.objects.filter(pk=self.user_b.pk).update(tenant_id='tenant_b')
        self.user_b.refresh_from_db()
        self.client_b = make_client(self.user_b)

    def test_P7_03_B_cross_tenant_isolation(self):
        """P7-03-B: 租户 A 的用户看不到租户 B 的合同"""
        # 租户 A 创建合同
        r = self.client_a.post('/contract-agreement/', _valid_contract_data(contract_name='租户A合同', responsible_user_id=self.user_a.id), content_type=JSON_CT)
        self.assertFalse(r.json().get('error'))
        agreement_id = r.json()['data']['id']

        # 租户 B 列表中看不到租户 A 的合同
        r = self.client_b.get('/contract-agreement/')
        records = r.json()['data']['records']
        ids = [rec['id'] for rec in records]
        self.assertNotIn(agreement_id, ids, '租户 B 不应看到租户 A 的合同')

    def test_P7_03_B_cross_tenant_delete_denied(self):
        """P7-03-B: 租户 B 的用户不能删除租户 A 的合同"""
        r = self.client_a.post('/contract-agreement/', _valid_contract_data(contract_name='租户A合同', responsible_user_id=self.user_a.id), content_type=JSON_CT)
        agreement_id = r.json()['data']['id']

        r = self.client_b.delete(f'/contract-agreement/?id={agreement_id}')
        self.assertTrue(r.json().get('error'), '跨租户删除应被拒绝')
        # 合同仍然存在
        self.assertTrue(ContractAgreement.objects.filter(pk=agreement_id).exists())

    def test_P7_03_B_cross_tenant_edit_denied(self):
        """P7-03-B: 租户 B 的用户不能编辑租户 A 的合同"""
        r = self.client_a.post('/contract-agreement/', _valid_contract_data(contract_name='租户A合同', responsible_user_id=self.user_a.id), content_type=JSON_CT)
        agreement_id = r.json()['data']['id']

        r = self.client_b.post('/contract-agreement/', {
            'id': agreement_id,
            'contract_name': '被篡改的名称',
        }, content_type=JSON_CT)
        self.assertTrue(r.json().get('error'), '跨租户编辑应被拒绝')
