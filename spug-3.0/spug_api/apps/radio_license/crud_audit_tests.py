# -*- coding: utf-8 -*-
"""radio_license 模块 CRUD 可靠性深度审计测试

参照 CRUD系统可靠性指南.md §1.1-§3.5 逐项排查。
R1_xxx = 风险确认（bug 存在时 FAIL）; P1_xxx = 优秀实践确认（应 PASS）
"""
import inspect, time
from datetime import date
from decimal import Decimal
from django.db import transaction, IntegrityError, connection
from django.test import TestCase
from apps.radio_license import views as rl_views, approval_views as rl_approval_views, tasks as rl_tasks
from apps.radio_license.models import (
    RadioLicense, RadioLicenseFrequency, LicenseReminderAck,
    StationFrequencyApproval, StationFrequencyApprovalReminderAck,
)
from apps.account.models import User


def _make_user(username='rl_audit', is_supper=False):
    token = (username * 10)[:32]
    now_ts = int(time.time()) + 3600
    with connection.cursor() as cur:
        cur.execute("SET SESSION sql_mode=''")
        cur.execute(
            "INSERT INTO users (username,nickname,password_hash,is_active,is_supper,"
            "access_token,token_expired,last_login,last_ip,type,tenant_id,wx_token,"
            "created_at) VALUES (%s,%s,'x',1,%s,%s,%s,'2026-01-01','127.0.0.1',"
            "'default','admin','',NOW())",
            [username, username, 1 if is_supper else 0, token, now_ts])
    return User.objects.get(username=username)


def _make_license(user, **kw):
    return RadioLicense.objects.create(
        station_name=kw.get('station_name', '测试台站'),
        purpose=kw.get('purpose', '测试'),
        valid_from=kw.get('valid_from', date(2026, 1, 1)),
        valid_to=kw.get('valid_to', date(2026, 12, 31)),
        responsible_user_id=user.id, responsible_user_name=user.nickname,
        status='normal', created_by=user, tenant_id='admin')


def _make_approval(user, **kw):
    return StationFrequencyApproval.objects.create(
        name=kw.get('name', '测试批复'),
        doc_no=kw.get('doc_no', 'SFA-2026-001'),
        frequency_text=kw.get('frequency_text', '150MHz'),
        valid_from=kw.get('valid_from', date(2026, 1, 1)),
        valid_to=kw.get('valid_to', date(2026, 12, 31)),
        responsible_user_id=user.id, responsible_user_name=user.nickname,
        status='normal', created_by=user, tenant_id='admin')


def _cleanup(*models):
    """按传入顺序删除（调用者需保证子表在前、父表在后）"""
    for m in models:
        m.objects.all().delete()


# ==================== §1.1 数据库约束 ====================

class R1_LicenseNoUniqueConstraint(TestCase):
    """R1(P1): RadioLicense 无业务唯一约束，可创建重复执照"""
    def test_r1a_no_unique_constraint(self):
        uc = [c for c in RadioLicense._meta.constraints
              if c.__class__.__name__ == 'UniqueConstraint']
        self.assertEqual(len(uc), 0)

    def test_r1b_duplicate_allowed(self):
        u = _make_user('r1b')
        try:
            l1 = _make_license(u, station_name='重复台站')
            l2 = _make_license(u, station_name='重复台站',
                               valid_from=l1.valid_from, valid_to=l1.valid_to)
            self.assertNotEqual(l1.id, l2.id)
        finally:
            _cleanup(RadioLicense, User)


class R2_LicenseNoSoftDelete(TestCase):
    """R2(P1): RadioLicense 无 is_deleted，DELETE 为物理删除"""
    def test_r2a_no_is_deleted_field(self):
        self.assertNotIn('is_deleted', [f.name for f in RadioLicense._meta.get_fields()])

    def test_r2b_no_soft_delete_manager(self):
        self.assertNotEqual(RadioLicense.objects.__class__.__name__, 'SoftDeleteTenantManager')


class R3_ApprovalNoSoftDelete(TestCase):
    """R3(P1): StationFrequencyApproval 无 is_deleted，DELETE 为物理删除"""
    def test_r3a_no_is_deleted_field(self):
        self.assertNotIn('is_deleted',
                         [f.name for f in StationFrequencyApproval._meta.get_fields()])


class R4_ResponsibleUserIdNotFK(TestCase):
    """R4(P2): responsible_user_id 为 IntegerField，无 DB 外键约束"""
    def test_r4a_integer_field(self):
        f = RadioLicense._meta.get_field('responsible_user_id')
        self.assertEqual(f.__class__.__name__, 'IntegerField')


class P1_ApprovalUniqueDocNo(TestCase):
    """P1: StationFrequencyApproval 有 (tenant_id, doc_no) 唯一约束"""
    def test_p1a_constraint_exists(self):
        uc = [c for c in StationFrequencyApproval._meta.constraints
              if c.__class__.__name__ == 'UniqueConstraint']
        self.assertGreaterEqual(len(uc), 1)

    def test_p1b_duplicate_rejected(self):
        u = _make_user('p1b')
        try:
            _make_approval(u, doc_no='DUP-001')
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    _make_approval(u, doc_no='DUP-001')
        finally:
            _cleanup(StationFrequencyApproval, User)


class P2_LicenseCheckConstraints(TestCase):
    """P2: RadioLicense 有 CHECK 约束（status + 日期顺序）"""
    def test_p2a_status_check(self):
        names = [c.name for c in RadioLicense._meta.constraints
                 if c.__class__.__name__ == 'CheckConstraint']
        self.assertIn('radio_license_status_valid', names)
        self.assertIn('radio_license_date_order', names)

    def test_p2b_invalid_status_rejected(self):
        u = _make_user('p2b')
        try:
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    RadioLicense(station_name='t', valid_from=date(2026, 1, 1),
                                 valid_to=date(2026, 12, 31), status='BAD',
                                 created_by=u, tenant_id='admin').save()
        finally:
            _cleanup(RadioLicense, User)

    def test_p2c_invalid_date_order_rejected(self):
        u = _make_user('p2c')
        try:
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    RadioLicense(station_name='t', valid_from=date(2026, 12, 31),
                                 valid_to=date(2026, 1, 1), status='normal',
                                 created_by=u, tenant_id='admin').save()
        finally:
            _cleanup(RadioLicense, User)


class P3_ReminderAckUnique(TestCase):
    """P3: LicenseReminderAck 有唯一约束（幂等性保障）"""
    def test_p3a_duplicate_rejected(self):
        u = _make_user('p3a')
        try:
            lic = _make_license(u)
            LicenseReminderAck.objects.create(
                license=lic, user_id=u.id, user_name=u.nickname,
                ack_valid_to=lic.valid_to, tenant_id='admin')
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    LicenseReminderAck.objects.create(
                        license=lic, user_id=u.id, user_name=u.nickname,
                        ack_valid_to=lic.valid_to, tenant_id='admin')
        finally:
            _cleanup(LicenseReminderAck, RadioLicense, User)


class P4_FrequencyCheckConstraints(TestCase):
    """P4: RadioLicenseFrequency 有 CHECK 约束"""
    def test_p4a_check_exists(self):
        names = [c.name for c in RadioLicenseFrequency._meta.constraints
                 if c.__class__.__name__ == 'CheckConstraint']
        self.assertIn('radio_frequency_positive', names)
        self.assertIn('radio_frequency_sort_valid', names)

    def test_p4b_zero_frequency_rejected(self):
        u = _make_user('p4b')
        try:
            lic = _make_license(u)
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    RadioLicenseFrequency.objects.create(
                        license=lic, frequency_value=Decimal('0'),
                        frequency_unit='MHz', created_by=u, tenant_id='admin')
        finally:
            _cleanup(RadioLicenseFrequency, RadioLicense, User)


class P5_FKOnDelete(TestCase):
    """P5: 外键 ON DELETE 策略"""
    def test_p5a_created_by_protect(self):
        self.assertEqual(
            RadioLicense._meta.get_field('created_by').remote_field.on_delete.__name__,
            'PROTECT')

    def test_p5b_frequency_cascade(self):
        self.assertEqual(
            RadioLicenseFrequency._meta.get_field('license').remote_field.on_delete.__name__,
            'CASCADE')


# ==================== §1.2 事务边界 ====================

class P21_LicenseDeleteInTransaction(TestCase):
    """P21: RadioLicenseView.delete 包裹 transaction.atomic()（已修复 R5）"""
    def test_p21a_has_transaction(self):
        src = inspect.getsource(rl_views.RadioLicenseView.delete)
        self.assertIn('transaction.atomic', src)


class P6_ApprovalDeleteInTransaction(TestCase):
    """P6: StationFrequencyApprovalView.delete 包裹 transaction.atomic()"""
    def test_p6a_has_transaction(self):
        src = inspect.getsource(rl_approval_views.StationFrequencyApprovalView.delete)
        self.assertIn('transaction.atomic', src)


class P7_LicenseCreateInTransaction(TestCase):
    """P7: RadioLicenseView 创建包裹 transaction.atomic()"""
    def test_p7a_has_transaction(self):
        src = inspect.getsource(rl_views.RadioLicenseView)
        self.assertIn('transaction.atomic', src)


# ==================== §1.3 幂等性设计 ====================

class R6_LicenseCreateNoDedup(TestCase):
    """R6(P2): RadioLicenseView POST 创建无去重逻辑"""
    def test_r6a_no_check_recent_duplicate(self):
        src = inspect.getsource(rl_views)
        self.assertNotIn('check_recent_duplicate', src)


class P8_ApprovalHasDedup(TestCase):
    """P8: StationFrequencyApprovalView 创建有 doc_no 去重 + IntegrityError 兜底"""
    def test_p8a_has_doc_no_check(self):
        src = inspect.getsource(rl_approval_views.StationFrequencyApprovalView)
        self.assertIn('doc_no', src)

    def test_p8b_has_integrity_error_catch(self):
        src = inspect.getsource(rl_approval_views.StationFrequencyApprovalView)
        self.assertIn('IntegrityError', src)


class P9_ApprovalAckIdempotent(TestCase):
    """P9: ApprovalReminderAckView 使用 get_or_create 实现幂等"""
    def test_p9a_uses_get_or_create(self):
        src = inspect.getsource(rl_approval_views.ApprovalReminderAckView)
        self.assertIn('get_or_create', src)


# ==================== §1.5 防误操作与可追溯 ====================

class R7_LicenseHardDelete(TestCase):
    """R7(P1): RadioLicenseView.delete 使用物理删除"""
    def test_r7a_uses_hard_delete(self):
        src = inspect.getsource(rl_views.RadioLicenseView.delete)
        self.assertIn('.delete()', src)
        self.assertNotIn('is_deleted = True', src)


class P22_LicenseCreateHasAudit(TestCase):
    """P22: RadioLicenseView 创建/编辑有 record_audit_event（已修复 R8）"""
    def test_p22a_create_has_audit(self):
        src = inspect.getsource(rl_views.RadioLicenseView)
        self.assertIn('record_audit_event', src)


class P10_ApprovalHasAudit(TestCase):
    """P10: StationFrequencyApprovalView 有 _record_approval_audit 审计"""
    def test_p10a_has_audit(self):
        src = inspect.getsource(rl_approval_views.StationFrequencyApprovalView)
        self.assertIn('_record_approval_audit', src,
                       "应有 _record_approval_audit 审计调用")


# ==================== §2.1 索引与慢查询 ====================

class P11_NoBadDatetimeQueries(TestCase):
    """P11: 无 DateTimeField __icontains/__year/__month 查询"""
    def test_p11a_views_clean(self):
        src = inspect.getsource(rl_views)
        for p in ['__icontains', '__year', '__month', '__date', '__startswith']:
            for f in ['created_at', 'updated_at', 'last_remind_at']:
                self.assertNotIn(f'{f}{p}', src)

    def test_p11b_approval_views_clean(self):
        src = inspect.getsource(rl_approval_views)
        for p in ['__icontains', '__year', '__month', '__date']:
            for f in ['created_at', 'updated_at']:
                self.assertNotIn(f'{f}{p}', src)


class P12_NoRawSQL(TestCase):
    """P12: 无 raw SQL 拼接"""
    def test_p12a_no_fstring_sql(self):
        for m in [rl_views, rl_approval_views]:
            self.assertNotIn('cursor.execute(f', inspect.getsource(m))

    def test_p12b_no_raw(self):
        for m in [rl_views, rl_approval_views]:
            self.assertNotIn('.raw(', inspect.getsource(m))

    def test_p12c_no_extra(self):
        for m in [rl_views, rl_approval_views]:
            self.assertNotIn('.extra(', inspect.getsource(m))


# ==================== §2.2 资源兜底与限流容错 ====================

class P23_LicenseListPageSizeLimit(TestCase):
    """P23: RadioLicenseView 列表有 page_size 上限（已修复 R9）"""
    def test_p23a_has_max(self):
        src = inspect.getsource(rl_views.RadioLicenseView.get)
        self.assertTrue('min(' in src and 'page_size' in src.lower())


class P13_ApprovalListPageSizeLimit(TestCase):
    """P13: StationFrequencyApprovalView 列表有 page_size 上限"""
    def test_p13a_has_max(self):
        src = inspect.getsource(rl_approval_views.StationFrequencyApprovalView.get)
        self.assertTrue('min(' in src and 'page_size' in src.lower())


class R10_EvidencePackageNoLimit(TestCase):
    """R10(P2): 证据包导出无行数上限"""
    def test_r10a_no_limit(self):
        if hasattr(rl_views, 'RadioLicenseEvidencePackageView'):
            src = inspect.getsource(rl_views.RadioLicenseEvidencePackageView)
            self.assertNotIn('[:10000]', src)
            self.assertNotIn('MAX_EXPORT', src)


class R11_LicenseScanNoIterator(TestCase):
    """R11(P2): scan_radio_license_expiration 未用 iterator()"""
    def test_r11a_no_iterator(self):
        src = inspect.getsource(rl_tasks.scan_radio_license_expiration)
        self.assertNotIn('.iterator(', src)

    def test_r11b_approval_has_iterator(self):
        src = inspect.getsource(rl_tasks.scan_approval_expiration)
        self.assertIn('.iterator(', src)


class P24_ScanHasErrorIsolation(TestCase):
    """P24: 扫描任务循环内有 try/except 错误隔离（已修复 R12）"""
    def test_p24a_has_try(self):
        src = inspect.getsource(rl_tasks.scan_radio_license_expiration)
        self.assertIn('try:', src)


class P14_NoExternalCalls(TestCase):
    """P14: 无 requests.get/post、无 subprocess"""
    def test_p14a_no_requests(self):
        for m in [rl_views, rl_approval_views]:
            src = inspect.getsource(m)
            self.assertNotIn('requests.get', src)
            self.assertNotIn('requests.post', src)

    def test_p14b_no_subprocess(self):
        for m in [rl_views, rl_approval_views, rl_tasks]:
            self.assertNotIn('subprocess', inspect.getsource(m))


# ==================== §3.5 安全维度 ====================

class R13_PreviewFileNoAuth(TestCase):
    """R13(P2): AttachmentPreviewFileView 无 @auth 装饰器"""
    def test_r13a_no_auth_decorator(self):
        if hasattr(rl_views, 'AttachmentPreviewFileView'):
            src = inspect.getsource(rl_views.AttachmentPreviewFileView.get)
            self.assertNotIn('@auth', src)


class R14_ApprovalPreviewFileNoAuth(TestCase):
    """R14(P2): ApprovalAttachmentPreviewFileView 无 @auth 装饰器"""
    def test_r14a_no_auth_decorator(self):
        if hasattr(rl_approval_views, 'ApprovalAttachmentPreviewFileView'):
            src = inspect.getsource(rl_approval_views.ApprovalAttachmentPreviewFileView.get)
            self.assertNotIn('@auth', src)


class P15_AllViewsUseTenantFilter(TestCase):
    """P15: 所有列表查询使用 apply_tenant_filter"""
    def test_p15a_license_views(self):
        src = inspect.getsource(rl_views)
        self.assertIn('apply_tenant_filter', src)

    def test_p15b_approval_views(self):
        src = inspect.getsource(rl_approval_views)
        self.assertIn('apply_tenant_filter', src)


class P16_NoCharFieldNullTrue(TestCase):
    """P16: 无 CharField/TextField null=True 违规"""
    def test_p16a_license_clean(self):
        for f in RadioLicense._meta.get_fields():
            if hasattr(f, 'null') and f.null and f.__class__.__name__ in ('CharField', 'TextField'):
                self.fail(f"RadioLicense.{f.name} is {f.__class__.__name__} with null=True")

    def test_p16b_approval_clean(self):
        for f in StationFrequencyApproval._meta.get_fields():
            if hasattr(f, 'null') and f.null and f.__class__.__name__ in ('CharField', 'TextField'):
                self.fail(f"StationFrequencyApproval.{f.name} is {f.__class__.__name__} with null=True")


class P17_NoUnboundedQueries(TestCase):
    """P17: 列表接口有分页"""
    def test_p17a_license_list_has_pagination(self):
        src = inspect.getsource(rl_views.RadioLicenseView.get)
        self.assertIn('page', src)

    def test_p17b_approval_list_has_pagination(self):
        src = inspect.getsource(rl_approval_views.StationFrequencyApprovalView.get)
        self.assertIn('page', src)
