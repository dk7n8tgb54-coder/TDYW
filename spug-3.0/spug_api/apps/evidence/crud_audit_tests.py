# -*- coding: utf-8 -*-
"""evidence 模块 CRUD 可靠性深度审计测试

参照 CRUD系统可靠性指南.md §1.1-§3.5 逐项排查。
R1_xxx = 风险确认（bug 存在时 FAIL）; P1_xxx = 优秀实践确认（应 PASS）
"""
import inspect, time, os
from datetime import datetime
from django.db import transaction, connection
from django.test import TestCase
from apps.evidence.models import EvidenceAttachment, EvidenceEvent
from apps.evidence.services import record_evidence_event
from apps.evidence.hash import compute_event_hash_from_values
from apps.evidence.attachment_service import AttachmentService
from apps.evidence.attachment_preview_token import (
    generate_attachment_preview_token, validate_attachment_preview_token,
    ATTACHMENT_PREVIEW_TOKEN_MAX_AGE,
)
from apps.account.models import User


def _make_user(username='ev_audit', is_supper=False, tenant_id='admin'):
    token = (username * 10)[:32]
    now_ts = int(time.time()) + 3600
    with connection.cursor() as cur:
        cur.execute("SET SESSION sql_mode=''")
        cur.execute(
            "INSERT INTO users (username,nickname,password_hash,is_active,is_supper,"
            "access_token,token_expired,last_login,last_ip,type,tenant_id,wx_token,"
            "created_at) VALUES (%s,%s,'x',1,%s,%s,%s,'2026-01-01','127.0.0.1',"
            "'default',%s,'',NOW())",
            [username, username, 1 if is_supper else 0, token, now_ts, tenant_id])
    return User.objects.get(username=username)


def _make_attachment(user, **kw):
    return EvidenceAttachment.objects.create(
        tenant_id=kw.get('tenant_id', 'admin'),
        module=kw.get('module', 'test_module'),
        object_type=kw.get('object_type', 'test_obj'),
        object_id=kw.get('object_id', 'obj-001'),
        file_name=kw.get('file_name', 'test.pdf'),
        file_path=kw.get('file_path', '/tmp/test.pdf'),
        file_size=kw.get('file_size', 1024),
        file_ext=kw.get('file_ext', '.pdf'),
        file_hash_sha256=kw.get('file_hash_sha256', 'a' * 64),
        uploaded_by_id=user.id, uploaded_by_name=user.nickname,
        is_deleted=kw.get('is_deleted', False),
    )


def _cleanup(*models):
    for m in reversed(models):
        m.objects.all().delete()


# ==================== §1.1 数据库约束 ====================

class R1_NoUniqueConstraint(TestCase):
    """R1(P1): EvidenceAttachment 无唯一约束，同文件可重复创建"""
    def test_r1a_no_unique(self):
        uc = [c for c in EvidenceAttachment._meta.constraints
              if c.__class__.__name__ == 'UniqueConstraint']
        self.assertEqual(len(uc), 0)

    def test_r1b_duplicate_allowed(self):
        u = _make_user('r1b')
        try:
            a1 = _make_attachment(u, file_hash_sha256='b'*64)
            a2 = _make_attachment(u, file_hash_sha256='b'*64)
            self.assertNotEqual(a1.id, a2.id)
        finally:
            _cleanup(EvidenceAttachment, User)


class R2_HashChainNoDBCheck(TestCase):
    """R2(P2): 哈希链 prev_hash/event_hash 无 DB 级 CHECK 约束"""
    def test_r2a_no_chain_check(self):
        checks = [c for c in EvidenceEvent._meta.constraints
                  if 'check' in c.__class__.__name__.lower()]
        chain_checks = [c for c in checks if 'hash' in str(getattr(c, 'name', '')).lower()]
        self.assertEqual(len(chain_checks), 0)

    def test_r2b_inconsistent_chain_allowed(self):
        u = _make_user('r2b')
        try:
            e1 = record_evidence_event('admin', 'test', 'obj', 'chain-001', 'submit',
                                       actor_user_id=u.id, actor_name=u.nickname)
            e2 = EvidenceEvent.objects.create(
                tenant_id='admin', module='test', object_type='obj', object_id='chain-001',
                event_type='correct', actor_user_id=u.id, actor_name=u.nickname,
                prev_hash='deadbeef'*8, event_hash='cafebabe'*8)
            self.assertNotEqual(e2.prev_hash, e1.event_hash)
        finally:
            _cleanup(EvidenceEvent, User)


class R3_LogicalFKOrphan(TestCase):
    """R3(P2): 逻辑外键（IntegerField）无 DB 引用完整性"""
    def test_r3a_all_logical_fks_are_integerfield(self):
        from django.db.models import IntegerField
        ev = {f.name: f for f in EvidenceEvent._meta.get_fields()}
        att = {f.name: f for f in EvidenceAttachment._meta.get_fields()}
        for n in ('actor_user_id', 'audit_log_id'):
            self.assertIsInstance(ev[n], IntegerField)
        for n in ('uploaded_by_id', 'deleted_by_id'):
            self.assertIsInstance(att[n], IntegerField)

    def test_r3b_orphan_allowed(self):
        u = _make_user('r3b')
        try:
            att = _make_attachment(u)
            uid = u.id
            u.delete()
            att.refresh_from_db()
            self.assertEqual(att.uploaded_by_id, uid)
        finally:
            _cleanup(EvidenceAttachment, User)


class P1_NoCharFieldNullTrue(TestCase):
    """P1: CharField/TextField 无 null=True 违规（应 PASS）"""
    def test_p1(self):
        from django.db.models import CharField, TextField
        violations = []
        for model in (EvidenceAttachment, EvidenceEvent):
            for f in model._meta.get_fields():
                if isinstance(f, (CharField, TextField)) and getattr(f, 'null', False):
                    violations.append(f"{model.__name__}.{f.name}")
        self.assertEqual(len(violations), 0, f"违规: {violations}")


class P2_HasEventTypeCheck(TestCase):
    """P2: EvidenceEvent 有 event_type CHECK 约束（应 PASS）"""
    def test_p2a_check_exists(self):
        checks = [c for c in EvidenceEvent._meta.constraints
                  if 'check' in c.__class__.__name__.lower()]
        self.assertGreaterEqual(len(checks), 1)

    def test_p2b_invalid_type_rejected(self):
        u = _make_user('p2b')
        try:
            with self.assertRaises(Exception):
                EvidenceEvent.objects.create(
                    tenant_id='admin', module='test', object_type='obj',
                    object_id='chk-001', event_type='INVALID', event_hash='x'*64)
        finally:
            _cleanup(User)


# ==================== §1.2 事务边界 ====================

class P9_HashChainUsesSelectForUpdate(TestCase):
    """P9(已修复): 哈希链写入使用 select_for_update，防止并发竞态"""
    def test_p9_select_for_update(self):
        src = inspect.getsource(record_evidence_event)
        self.assertIn('select_for_update', src)

    def test_r4b_orm_bypass_still_possible(self):
        """直接 ORM 创建仍可绕过锁（DB 层无 CHECK），但 record_evidence_event 已防护"""
        u = _make_user('r4b')
        try:
            e0 = record_evidence_event('admin', 'test', 'obj', 'race-001', 'submit',
                                       actor_user_id=u.id, actor_name=u.nickname)
            last = EvidenceEvent.objects.filter(
                tenant_id='admin', module='test', object_type='obj',
                object_id='race-001').order_by('-id').first()
            ph1 = ph2 = last.event_hash
            h1 = compute_event_hash_from_values(
                tenant_id='admin', module='test', object_type='obj', object_id='race-001',
                event_type='correct', actor_user_id=u.id, actor_username=u.username,
                actor_name=u.nickname, object_snapshot='', attachment_hashes='',
                prev_hash=ph1, created_at=datetime.now())
            e1 = EvidenceEvent.objects.create(
                tenant_id='admin', module='test', object_type='obj', object_id='race-001',
                event_type='correct', actor_user_id=u.id, actor_name=u.nickname,
                prev_hash=ph1, event_hash=h1, object_snapshot='')
            e2 = EvidenceEvent.objects.create(
                tenant_id='admin', module='test', object_type='obj', object_id='race-001',
                event_type='correct', actor_user_id=u.id, actor_name=u.nickname,
                prev_hash=ph2, event_hash=h1, object_snapshot='')
            self.assertEqual(e2.prev_hash, e1.prev_hash, "直接ORM创建可绕过锁（预期）")
        finally:
            _cleanup(EvidenceEvent, User)


class P10_SoftDeleteByObjectHasAtomic(TestCase):
    """P10(已修复): soft_delete_by_object 使用 transaction.atomic"""
    def test_p10(self):
        src = inspect.getsource(AttachmentService.soft_delete_by_object)
        self.assertIn('transaction.atomic', src)


class P3_UploadUsesAtomic(TestCase):
    """P3: upload 正确使用 transaction.atomic（应 PASS）"""
    def test_p3(self):
        src = inspect.getsource(AttachmentService.upload)
        self.assertIn('transaction.atomic', src)


# ==================== §1.3 幂等性 ====================

class R6_NoUploadDedup(TestCase):
    """R6(P2): 附件上传无去重，同 SHA256 可重复创建"""
    def test_r6a_no_dedup(self):
        src = inspect.getsource(AttachmentService.upload)
        self.assertNotIn('check_recent_duplicate', src)

    def test_r6b_duplicate_allowed(self):
        u = _make_user('r6b')
        try:
            a1 = _make_attachment(u, file_hash_sha256='c'*64)
            a2 = _make_attachment(u, file_hash_sha256='c'*64)
            self.assertNotEqual(a1.id, a2.id)
        finally:
            _cleanup(EvidenceAttachment, User)


class P11_HashChainHasIdempotency(TestCase):
    """P11(已修复): record_evidence_event 有 idempotency_key 参数"""
    def test_p11_has_idempotency(self):
        src = inspect.getsource(record_evidence_event)
        self.assertIn('idempotency_key', src)

    def test_p12_idempotency_prevents_duplicate(self):
        """相同 idempotency_key 的重复调用返回 None"""
        u = _make_user('r7b')
        try:
            e1 = record_evidence_event('admin', 'test', 'obj', 'idem-001', 'submit',
                                       actor_user_id=u.id, actor_name=u.nickname,
                                       object_snapshot='{"k":"v"}', idempotency_key='k1')
            e2 = record_evidence_event('admin', 'test', 'obj', 'idem-001', 'submit',
                                       actor_user_id=u.id, actor_name=u.nickname,
                                       object_snapshot='{"k":"v"}', idempotency_key='k1')
            self.assertIsNotNone(e1, "首次调用应返回事件")
            self.assertIsNone(e2, "相同 idempotency_key 应返回 None")
        finally:
            _cleanup(EvidenceEvent, User)


# ==================== §1.5 防误操作与可追溯 ====================

class P13_DownloadFiltersIsDeleted(TestCase):
    """P13(已修复): download_response 过滤 is_deleted"""
    def test_p13_has_is_deleted(self):
        src = inspect.getsource(AttachmentService.download_response)
        self.assertIn('is_deleted', src)

    def test_p14_soft_deleted_not_downloadable(self):
        """软删除附件不可下载"""
        u = _make_user('r8b')
        try:
            att = _make_attachment(u)
            att.is_deleted = True
            att.deleted_at = datetime.now()
            att.save()
            resp, err = AttachmentService.download_response(
                u, att.id, skip_tenant_filter=True)
            self.assertIsNotNone(err, "软删除附件应返回错误")
            self.assertTrue('不存在' in (err or '') or '已删除' in (err or ''),
                f"应提示不存在或已删除: {err}")
        finally:
            _cleanup(EvidenceAttachment, User)


class R9_NoAuditLog(TestCase):
    """R9(P3): 附件操作本身无审计日志"""
    def test_r9(self):
        for name in ('upload', 'soft_delete', 'soft_delete_by_object'):
            method = getattr(AttachmentService, name, None)
            if method:
                src = inspect.getsource(method)
                self.assertNotIn('record_audit_event', src)
                self.assertNotIn('AuditLog', src)


class P4_SoftDeletePreservesFile(TestCase):
    """P4: 软删除保留物理文件（应 PASS）"""
    def test_p4(self):
        src = inspect.getsource(AttachmentService.soft_delete)
        self.assertIn('delete_file', src)
        self.assertIn('False', src)


class P5_PreviewChecksIsDeleted(TestCase):
    """P5: preview_file_response 检查 is_deleted（应 PASS）"""
    def test_p5(self):
        src = inspect.getsource(AttachmentService.preview_file_response)
        self.assertIn('is_deleted', src)
        self.assertIn('附件已删除', src)


# ==================== §2.1 索引 ====================

class P6_AttachmentIndexes(TestCase):
    """P6: EvidenceAttachment 索引完备（应 PASS）"""
    def test_p6a_obj_index(self):
        names = [i.name for i in EvidenceAttachment._meta.indexes]
        self.assertTrue(any('obj' in n for n in names), f"索引: {names}")

    def test_p6b_sha256_index(self):
        names = [i.name for i in EvidenceAttachment._meta.indexes]
        self.assertTrue(any('sha256' in n.lower() for n in names), f"索引: {names}")

    def test_p6c_del_index(self):
        names = [i.name for i in EvidenceAttachment._meta.indexes]
        self.assertTrue(any('del' in n.lower() for n in names), f"索引: {names}")


class P7_EventIndexes(TestCase):
    """P7: EvidenceEvent 索引完备（应 PASS）"""
    def test_p7a_chain_index(self):
        names = [i.name for i in EvidenceEvent._meta.indexes]
        self.assertTrue(any('chain' in n.lower() for n in names), f"索引: {names}")

    def test_p7b_hash_index(self):
        names = [i.name for i in EvidenceEvent._meta.indexes]
        self.assertTrue(any('hash' in n.lower() for n in names), f"索引: {names}")


# ==================== §3.5 安全 - preview_token ====================

class P8_TokenBindsAllFields(TestCase):
    """P8: preview_token 绑定 6 维信息（应 PASS）"""
    def test_p8(self):
        u = _make_user('p8')
        try:
            att = _make_attachment(u)
            token = generate_attachment_preview_token(
                att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
            data = validate_attachment_preview_token(token)
            self.assertIsNotNone(data)
            self.assertEqual(data['attachment_id'], att.id)
            self.assertEqual(data['user_id'], u.id)
            self.assertEqual(data['tenant_id'], 'admin')
            self.assertEqual(data['module'], 'test_module')
            self.assertEqual(data['object_type'], 'test_obj')
            self.assertEqual(data['object_id'], 'obj-001')
        finally:
            _cleanup(EvidenceAttachment, User)


class R10_TokenCrossAttachment(TestCase):
    """R10(P0): 跨附件 token - preview_file_response 校验 attachment_id 一致性"""
    def test_r10(self):
        u = _make_user('r10')
        try:
            a1 = _make_attachment(u, file_name='a.pdf')
            a2 = _make_attachment(u, file_name='b.pdf')
            token = generate_attachment_preview_token(
                a1.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
            # preview_file_response(token, attachment_id)
            resp, err = AttachmentService.preview_file_response(token, a2.id)
            self.assertIsNotNone(err, "跨附件应被拒绝")
            self.assertIn('不匹配', err)
        finally:
            _cleanup(EvidenceAttachment, User)


class R11_TokenCrossTenant(TestCase):
    """R11(P0): 跨租户 token - preview_file_response 校验 tenant 一致性"""
    def test_r11(self):
        u = _make_user('r11')
        try:
            att = _make_attachment(u, tenant_id='admin')
            token = generate_attachment_preview_token(
                att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
            att.tenant_id = 'other'
            att.save()
            resp, err = AttachmentService.preview_file_response(token, att.id)
            self.assertIsNotNone(err, "跨租户应被拒绝")
            self.assertIn('无效', err)
        finally:
            _cleanup(EvidenceAttachment, User)


class R12_TokenCrossUser(TestCase):
    """R12(P0): 跨用户 token - token 中绑定 user_id"""
    def test_r12(self):
        u1 = _make_user('r12u1')
        u2 = _make_user('r12u2')
        try:
            att = _make_attachment(u1)
            token = generate_attachment_preview_token(
                att.id, u1.id, 'admin', 'test_module', 'test_obj', 'obj-001')
            data = validate_attachment_preview_token(token)
            self.assertEqual(data['user_id'], u1.id)
            self.assertNotEqual(data['user_id'], u2.id)
        finally:
            _cleanup(EvidenceAttachment, User)


class R13_TokenCrossObject(TestCase):
    """R13(P0): 跨业务对象 token - preview_file_response 校验 object_id"""
    def test_r13(self):
        u = _make_user('r13')
        try:
            att = _make_attachment(u, object_id='obj-A')
            token = generate_attachment_preview_token(
                att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-A')
            att.object_id = 'obj-B'
            att.save()
            resp, err = AttachmentService.preview_file_response(token, att.id)
            self.assertIsNotNone(err, "跨对象应被拒绝")
            self.assertIn('无效', err)
        finally:
            _cleanup(EvidenceAttachment, User)


class R14_TokenTampered(TestCase):
    """R14(P0): 篡改 token 应被拒绝"""
    def test_r14a_tampered(self):
        u = _make_user('r14a')
        try:
            att = _make_attachment(u)
            token = generate_attachment_preview_token(
                att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
            tampered = token[:-1] + ('a' if token[-1] != 'a' else 'b')
            data = validate_attachment_preview_token(tampered)
            self.assertIsNone(data, "篡改 token 应返回 None")
        finally:
            _cleanup(EvidenceAttachment, User)

    def test_r14b_fabricated(self):
        data = validate_attachment_preview_token("fake:token:value")
        self.assertIsNone(data, "伪造 token 应返回 None")


class R15_TokenExpired(TestCase):
    """R15(P1): 过期 token 应被拒绝"""
    def test_r15a_max_age_300(self):
        self.assertEqual(ATTACHMENT_PREVIEW_TOKEN_MAX_AGE, 300)

    def test_r15b_expired(self):
        u = _make_user('r15b')
        try:
            att = _make_attachment(u)
            token = generate_attachment_preview_token(
                att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
            data = validate_attachment_preview_token(token, max_age=0)
            self.assertIsNone(data, "过期 token 应返回 None")
        finally:
            _cleanup(EvidenceAttachment, User)


class R16_SoftDeletedPreviewInvalid(TestCase):
    """R16(P1): 软删除后 preview_file_response 应拒绝预览"""
    def test_r16(self):
        src = inspect.getsource(AttachmentService.preview_file_response)
        self.assertIn('is_deleted', src)
        self.assertIn('附件已删除', src)


class R17_ColonDelimiter(TestCase):
    """R17(P2): 冒号分隔符注入 - 含冒号的 module 导致 split 段数不对"""
    def test_r17(self):
        u = _make_user('r17')
        try:
            att = _make_attachment(u, module='test:module')
            token = generate_attachment_preview_token(
                att.id, u.id, 'admin', 'test:module', 'test_obj', 'obj-001')
            data = validate_attachment_preview_token(token)
            self.assertIsNone(data, "含冒号 module 应被拒绝")
        finally:
            _cleanup(EvidenceAttachment, User)


class R18_TwoTokenImplementations(TestCase):
    """R18(P3): 两套 preview_token 实现待收口"""
    def test_r18a_evidence_binds_business_object(self):
        from apps.evidence import attachment_preview_token as ev
        src = inspect.getsource(ev)
        self.assertIn('module', src)
        self.assertIn('object_type', src)

    def test_r18b_document_token_exists(self):
        # __file__ = apps/evidence/crud_audit_tests.py
        # dirname 1 level -> apps/evidence/
        # dirname 2 levels -> apps/
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        doc_path = os.path.join(base, 'document', 'libs', 'preview_token.py')
        self.assertTrue(os.path.exists(doc_path),
            f"document/libs/preview_token.py 应存在: {doc_path}")

    def test_r18c_different_binding(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        doc_path = os.path.join(base, 'document', 'libs', 'preview_token.py')
        if os.path.exists(doc_path):
            with open(doc_path, 'r') as f:
                doc_src = f.read()
            self.assertIn('is_public', doc_src.lower(),
                "document token 绑定 is_public（与 evidence 不同维度）")
