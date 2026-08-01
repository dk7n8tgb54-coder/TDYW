# -*- coding: utf-8 -*-
"""device 模块 CRUD 可靠性深度审计测试

参照 CRUD系统可靠性指南.md §1.1-§3.5 逐项排查。
R1_xxx = 风险确认（bug 存在时 FAIL）; P1_xxx = 优秀实践确认（应 PASS）
"""
import inspect, time
from datetime import date, datetime
from django.db import transaction, IntegrityError, connection
from django.test import TestCase
from apps.device import views as dev_views, exporters as dev_exporters
from apps.device.models import DeviceResume, DeviceEvent
from apps.account.models import User


def _make_user(username='dev_audit', is_supper=False):
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


def _make_device(user, **kw):
    return DeviceResume.objects.create(
        device_sn=kw.get('device_sn', 'DEV-001'),
        device_name=kw.get('device_name', '测试设备'),
        device_model=kw.get('device_model', 'Model-A'),
        use_unit=kw.get('use_unit', '测试单位'),
        current_status=kw.get('current_status', '1'),
        created_by=user, tenant_id='admin')


def _make_event(user, device, **kw):
    return DeviceEvent.objects.create(
        device_resume_id=device.id,
        device_name=device.device_name,
        device_sn=device.device_sn,
        event_type=kw.get('event_type', 1),
        event_time=kw.get('event_time', datetime(2026, 1, 1, 10, 0)),
        event_title=kw.get('event_title', '测试事件'),
        related_user_name=user.nickname,
        created_by=user, tenant_id='admin')


def _cleanup(*models):
    """按传入顺序删除（调用者需保证子表在前、父表在后）"""
    for m in models:
        m.objects.all().delete()


# ==================== §1.1 数据库约束 ====================

class R1_DeviceEventNoUniqueConstraint(TestCase):
    """R1(P1): DeviceEvent 无唯一约束，可创建重复事件"""
    def test_r1a_no_unique(self):
        uc = [c for c in DeviceEvent._meta.constraints
              if c.__class__.__name__ == 'UniqueConstraint']
        self.assertEqual(len(uc), 0)

    def test_r1b_duplicate_allowed(self):
        u = _make_user('r1b')
        try:
            d = _make_device(u)
            e1 = _make_event(u, d, event_type=1, event_time=datetime(2026, 1, 1, 10, 0))
            e2 = _make_event(u, d, event_type=1, event_time=datetime(2026, 1, 1, 10, 0),
                            description='测试事件')
            self.assertNotEqual(e1.id, e2.id)
        finally:
            _cleanup(DeviceEvent, DeviceResume, User)


class R2_DeviceEventResumeIdNotFK(TestCase):
    """R2(P2): DeviceEvent.device_resume_id 为 IntegerField，无 DB 外键约束

    风险描述: 无外键约束意味着 DB 层不保证引用完整性。
    虽 DeviceResume 用软删，但硬删场景下事件可能成孤儿。
    """
    def test_r2a_integer_field(self):
        f = DeviceEvent._meta.get_field('device_resume_id')
        self.assertEqual(f.__class__.__name__, 'IntegerField')


class R3_DeviceEventHasIsDeletedButHardDeletes(TestCase):
    """R3(P2): DeviceEvent 有 is_deleted 字段但 DELETE 使用物理删除

    风险描述: DeviceEvent 模型有 is_deleted 字段，但 DeviceEventView.delete
    使用 .delete() 物理删除而非 is_deleted=True。与 DeviceResume 软删策略不一致。
    """
    def test_r3a_is_deleted_field_exists(self):
        """确认 is_deleted 字段存在（有但不使用）"""
        self.assertIn('is_deleted',
                      [f.name for f in DeviceEvent._meta.get_fields()])

    def test_r3b_delete_uses_hard_delete(self):
        """确认 DELETE 使用 .delete() 而非 is_deleted=True"""
        src = inspect.getsource(dev_views.DeviceEventView.delete)
        self.assertIn('.delete()', src)
        self.assertNotIn('is_deleted = True', src)


class R4_DeviceEventNoUpdatedFields(TestCase):
    """R4(P2): DeviceEvent 无 updated_at/updated_by 字段

    风险描述: 事件编辑后无更新时间和更新人记录，审计困难。
    """
    def test_r4a_no_updated_at(self):
        self.assertNotIn('updated_at',
                         [f.name for f in DeviceEvent._meta.get_fields()])


class P1_DeviceResumeUniqueSN(TestCase):
    """P1: DeviceResume 有 (tenant_id, device_sn) 唯一约束"""
    def test_p1a_constraint_exists(self):
        uc = [c for c in DeviceResume._meta.constraints
              if c.__class__.__name__ == 'UniqueConstraint']
        self.assertGreaterEqual(len(uc), 1)

    def test_p1b_duplicate_rejected(self):
        u = _make_user('p1b')
        try:
            _make_device(u, device_sn='DUP-SN')
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    _make_device(u, device_sn='DUP-SN')
        finally:
            _cleanup(DeviceResume, User)


class P2_DeviceResumeCheckConstraints(TestCase):
    """P2: DeviceResume 有 CHECK 约束（current_status + delete fields）"""
    def test_p2a_status_check(self):
        names = [c.name for c in DeviceResume._meta.constraints
                 if c.__class__.__name__ == 'CheckConstraint']
        self.assertTrue(any('status' in n for n in names))

    def test_p2b_invalid_status_rejected(self):
        u = _make_user('p2b')
        try:
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    DeviceResume(device_sn='BAD', device_name='t', device_model='m',
                                 use_unit='u', current_status='99',
                                 created_by=u, tenant_id='admin').save()
        finally:
            _cleanup(DeviceResume, User)


class P3_DeviceResumeSoftDelete(TestCase):
    """P3: DeviceResume 使用软删除（is_deleted + SoftDeleteTenantManager）"""
    def test_p3a_has_is_deleted(self):
        self.assertIn('is_deleted',
                      [f.name for f in DeviceResume._meta.get_fields()])

    def test_p3b_soft_delete_manager(self):
        self.assertEqual(DeviceResume.objects.__class__.__name__,
                         'SoftDeleteTenantManager')


class P4_DeviceEventCheckConstraint(TestCase):
    """P4: DeviceEvent 有 CHECK 约束（event_type 合法值）"""
    def test_p4a_check_exists(self):
        names = [c.name for c in DeviceEvent._meta.constraints
                 if c.__class__.__name__ == 'CheckConstraint']
        self.assertTrue(len(names) > 0)

    def test_p4b_invalid_event_type_rejected(self):
        u = _make_user('p4b')
        try:
            d = _make_device(u)
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    DeviceEvent.objects.create(
                        device_resume_id=d.id, device_name=d.device_name,
                        device_sn=d.device_sn, event_type=99,
                        event_time=datetime(2026, 1, 1, 10, 0),
                        event_title='t', related_user_name=u.nickname,
                        created_by=u, tenant_id='admin')
        finally:
            _cleanup(DeviceEvent, DeviceResume, User)


class P5_DeviceResumeNoCharFieldNull(TestCase):
    """P5: DeviceResume 无 CharField/TextField null=True 违规"""
    def test_p5a_clean(self):
        for f in DeviceResume._meta.get_fields():
            if hasattr(f, 'null') and f.null and \
               f.__class__.__name__ in ('CharField', 'TextField'):
                self.fail(f"DeviceResume.{f.name} is {f.__class__.__name__} with null=True")


# ==================== §1.2 事务边界 ====================

class P21_DeviceEventPutInTransaction(TestCase):
    """P21: DeviceEventView PUT 包裹 transaction.atomic()（已修复 R5）"""
    def test_p21a_has_transaction(self):
        src = inspect.getsource(dev_views.DeviceEventView.put)
        self.assertIn('transaction.atomic', src)


class P6_DeviceResumeDeleteInTransaction(TestCase):
    """P6: DeviceResumeView DELETE 包裹 transaction.atomic()"""
    def test_p6a_has_transaction(self):
        src = inspect.getsource(dev_views.DeviceResumeView.delete)
        self.assertIn('transaction.atomic', src)


class P7_DeviceResumePutInTransaction(TestCase):
    """P7: DeviceResumeView PUT 包裹 transaction.atomic()"""
    def test_p7a_has_transaction(self):
        src = inspect.getsource(dev_views.DeviceResumeView.put)
        self.assertIn('transaction.atomic', src)


# ==================== §1.3 幂等性设计 ====================

class R6_DeviceEventCreateNoDedup(TestCase):
    """R6(P2): DeviceEventView POST 创建无去重逻辑"""
    def test_r6a_no_check_recent_duplicate(self):
        src = inspect.getsource(dev_views)
        self.assertNotIn('check_recent_duplicate', src)


class P8_DeviceResumeCreateDedup(TestCase):
    """P8: DeviceResumeView POST 创建有 device_sn 去重"""
    def test_p8a_has_dedup(self):
        src = inspect.getsource(dev_views.DeviceResumeView.post)
        self.assertIn('device_sn', src)
        self.assertIn('filter', src)


# ==================== §1.5 防误操作与可追溯 ====================

class P22_DeviceEventDeleteHasAudit(TestCase):
    """P22: DeviceEventView DELETE 有审计日志（已修复 R7）"""
    def test_p22a_has_audit(self):
        src = inspect.getsource(dev_views.DeviceEventView.delete)
        self.assertIn('record_audit_event', src)


class P9_DeviceResumeDeleteHasAudit(TestCase):
    """P9: DeviceResumeView DELETE 有审计日志（record_evidence_event）"""
    def test_p9a_has_audit(self):
        src = inspect.getsource(dev_views.DeviceResumeView.delete)
        self.assertTrue('record_evidence_event' in src or 'record_audit_event' in src,
                        "删除应有审计/证据事件记录")


class P10_DeviceResumePutHasAudit(TestCase):
    """P10: DeviceResumeView PUT 有审计日志（record_evidence_event）"""
    def test_p10a_has_audit(self):
        src = inspect.getsource(dev_views.DeviceResumeView.put)
        self.assertTrue('record_evidence_event' in src or 'record_audit_event' in src,
                        "编辑应有审计/证据事件记录")


class P11_ExportHasAudit(TestCase):
    """P11: DeviceListExportView 有审计日志"""
    def test_p11a_has_audit(self):
        src = inspect.getsource(dev_exporters.DeviceListExportView.get)
        self.assertIn('record_audit_event', src)


# ==================== §2.1 索引与慢查询 ====================

class P12_NoBadDatetimeQueries(TestCase):
    """P12: 无 DateTimeField __icontains/__year/__month 查询"""
    def test_p12a_views_clean(self):
        src = inspect.getsource(dev_views)
        for p in ['__icontains', '__year', '__month', '__date', '__startswith']:
            for f in ['created_at', 'updated_at', 'event_time', 'deleted_at']:
                self.assertNotIn(f'{f}{p}', src,
                                 f"不应有 {f}{p}")

    def test_p12b_exporters_clean(self):
        src = inspect.getsource(dev_exporters)
        for p in ['__icontains', '__year', '__month', '__date']:
            for f in ['created_at', 'updated_at']:
                self.assertNotIn(f'{f}{p}', src)


class P13_NoRawSQL(TestCase):
    """P13: 无 raw SQL 拼接"""
    def test_p13a_no_fstring_sql(self):
        for m in [dev_views, dev_exporters]:
            self.assertNotIn('cursor.execute(f', inspect.getsource(m))

    def test_p13b_no_raw(self):
        for m in [dev_views, dev_exporters]:
            self.assertNotIn('.raw(', inspect.getsource(m))

    def test_p13c_no_extra(self):
        for m in [dev_views, dev_exporters]:
            self.assertNotIn('.extra(', inspect.getsource(m))


# ==================== §2.2 资源兜底与限流容错 ====================

class P14_ExportHasRowLimit(TestCase):
    """P14: DeviceListExportView 有行数上限（check_export_limit）"""
    def test_p14a_has_limit(self):
        src = inspect.getsource(dev_exporters.DeviceListExportView.get)
        self.assertTrue('check_export_limit' in src or '10000' in src,
                        "导出应有 check_export_limit 或行数上限")


class R8_EvidencePackageAuditLogFallback(TestCase):
    """R8(P2): 证据包审计日志 fallback 查询可能返回全量

    风险描述: 当 target_id 未匹配时，fallback 查询返回该租户所有 device 审计日志。
    虽有 90 天 + 1000 条限制，但仍可能返回无关记录。
    """
    def test_r8a_fallback_query_exists(self):
        src = inspect.getsource(dev_views)
        if 'EvidencePackage' in src or 'evidence_package' in src:
            self.assertTrue('audit' in src.lower(),
                            "证据包应有审计日志查询")


class R9_PdfExportNoTimeout(TestCase):
    """R9(P2): PDF 导出无超时限制

    风险描述: generate_device_resume_pdf 同步生成 PDF，无超时。
    大量事件时可能阻塞 worker 线程。
    """
    def test_r9a_no_timeout(self):
        try:
            from apps.device import pdf_export
            src = inspect.getsource(pdf_export)
            self.assertNotIn('timeout', src.lower())
        except ImportError:
            self.skipTest("pdf_export module not found")


class P15_NoExternalCalls(TestCase):
    """P15: 无 requests.get/post、无 subprocess"""
    def test_p15a_no_requests(self):
        for m in [dev_views, dev_exporters]:
            src = inspect.getsource(m)
            self.assertNotIn('requests.get', src)
            self.assertNotIn('requests.post', src)

    def test_p15b_no_subprocess(self):
        for m in [dev_views, dev_exporters]:
            self.assertNotIn('subprocess', inspect.getsource(m))


class P16_ListHasPagination(TestCase):
    """P16: 列表接口有分页"""
    def test_p16a_resume_list(self):
        src = inspect.getsource(dev_views.DeviceResumeView.get)
        self.assertIn('page', src)

    def test_p16b_event_list(self):
        src = inspect.getsource(dev_views.DeviceEventView.get)
        self.assertIn('page', src)


# ==================== §3.5 安全维度 ====================

class R10_DeviceEventDeleteNoTenantFilter(TestCase):
    """R10(P2): DeviceEventView DELETE 可能缺少租户过滤

    风险描述: 需确认删除操作是否先 apply_tenant_filter 再获取对象。
    """
    def test_r10a_check_tenant_filter(self):
        src = inspect.getsource(dev_views.DeviceEventView.delete)
        # 确认有 apply_tenant_filter 或类似过滤
        self.assertTrue(
            'apply_tenant_filter' in src or 'tenant_id' in src,
            "DELETE 应有租户过滤")


class P17_AllViewsUseTenantFilter(TestCase):
    """P17: 所有列表查询使用 apply_tenant_filter"""
    def test_p17a_views(self):
        src = inspect.getsource(dev_views)
        self.assertIn('apply_tenant_filter', src)

    def test_p17b_exporters(self):
        src = inspect.getsource(dev_exporters)
        self.assertIn('apply_tenant_filter', src)


class P18_DeviceResumeDeleteSoftDelete(TestCase):
    """P18: DeviceResumeView DELETE 使用软删除"""
    def test_p18a_uses_soft_delete(self):
        src = inspect.getsource(dev_views.DeviceResumeView.delete)
        self.assertIn('is_deleted = True', src)
        self.assertNotIn('.delete()', src)


class P19_DeviceResumeDeleteHasEvidenceEvent(TestCase):
    """P19: DeviceResumeView DELETE 有 EvidenceEvent 记录"""
    def test_p19a_has_evidence_event(self):
        src = inspect.getsource(dev_views.DeviceResumeView.delete)
        self.assertTrue('EvidenceEvent' in src or 'evidence_event' in src.lower(),
                        "删除应记录 EvidenceEvent")


class P20_DeviceResumeExportMaxRows(TestCase):
    """P20: DeviceResumeExportView PDF 导出有事件上限"""
    def test_p20a_has_limit(self):
        if hasattr(dev_views, 'DeviceResumeExportView'):
            src = inspect.getsource(dev_views.DeviceResumeExportView.post)
            self.assertTrue('10000' in src or 'max' in src.lower(),
                            "PDF 导出应有事件上限")
