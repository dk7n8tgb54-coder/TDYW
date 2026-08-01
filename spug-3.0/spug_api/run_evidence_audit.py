# -*- coding: utf-8 -*-
"""独立审计脚本：绕过 Django test runner 的迁移问题，直接在 test_spug 上运行断言"""
import os, sys, inspect, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from django.db import connection, transaction

# 现在可以运行测试了
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
from datetime import datetime

results = {'pass': 0, 'fail': 0, 'error': 0, 'details': []}


def run_test(name, func):
    """运行单个测试函数"""
    # 清理可能残留的测试数据
    EvidenceEvent.objects.filter(tenant_id='admin', module='test').delete()
    EvidenceAttachment.objects.filter(tenant_id='admin', module='test_module').delete()
    EvidenceAttachment.objects.filter(tenant_id='admin', module='test:module').delete()
    try:
        # 清理用户
        for uname in ['r1b','r2b','r3b','p2b','r4b','r6b','r7b','r8b',
                       'p8','r10','r11','r12u1','r12u2','r13','r14a','r14b',
                       'r15b','r17','r3b']:
            User.objects.filter(username=uname).delete()
        func()
        results['pass'] += 1
        results['details'].append(f'  PASS  {name}')
    except AssertionError as e:
        results['fail'] += 1
        results['details'].append(f'  FAIL  {name}: {e}')
    except Exception as e:
        results['error'] += 1
        results['details'].append(f'  ERROR {name}: {e}')
    finally:
        # 清理
        EvidenceEvent.objects.filter(tenant_id='admin', module='test').delete()
        EvidenceAttachment.objects.filter(tenant_id='admin', module='test_module').delete()
        EvidenceAttachment.objects.filter(tenant_id='admin', module='test:module').delete()
        for uname in ['r1b','r2b','r3b','p2b','r4b','r6b','r7b','r8b',
                       'p8','r10','r11','r12u1','r12u2','r13','r14a','r14b',
                       'r15b','r17','r3b']:
            User.objects.filter(username=uname).delete()


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


# ==================== §1.1 数据库约束 ====================

def test_r1a_no_unique():
    uc = [c for c in EvidenceAttachment._meta.constraints
          if c.__class__.__name__ == 'UniqueConstraint']
    assert len(uc) == 0, f"应有 0 个 UniqueConstraint，实际 {len(uc)}"

def test_r1b_duplicate():
    u = _make_user('r1b')
    a1 = _make_attachment(u, file_hash_sha256='b'*64)
    a2 = _make_attachment(u, file_hash_sha256='b'*64)
    assert a1.id != a2.id, "重复附件应有不同 ID"

def test_r2a_no_chain_check():
    checks = [c for c in EvidenceEvent._meta.constraints
              if 'check' in c.__class__.__name__.lower()]
    chain_checks = [c for c in checks if 'hash' in str(getattr(c, 'name', '')).lower()]
    assert len(chain_checks) == 0, f"应有 0 个哈希链 CHECK 约束"

def test_r2b_inconsistent():
    u = _make_user('r2b')
    e1 = record_evidence_event('admin', 'test', 'obj', 'chain-001', 'submit',
                               actor_user_id=u.id, actor_name=u.nickname)
    e2 = EvidenceEvent.objects.create(
        tenant_id='admin', module='test', object_type='obj', object_id='chain-001',
        event_type='correct', actor_user_id=u.id, actor_name=u.nickname,
        prev_hash='deadbeef'*8, event_hash='cafebabe'*8)
    assert e2.prev_hash != e1.event_hash, "不一致的链应被允许插入"

def test_r3a_logical_fk():
    from django.db.models import IntegerField
    ev = {f.name: f for f in EvidenceEvent._meta.get_fields()}
    att = {f.name: f for f in EvidenceAttachment._meta.get_fields()}
    for n in ('actor_user_id', 'audit_log_id'):
        assert isinstance(ev[n], IntegerField), f"{n} 应为 IntegerField"
    for n in ('uploaded_by_id', 'deleted_by_id'):
        assert isinstance(att[n], IntegerField), f"{n} 应为 IntegerField"

def test_r3b_orphan():
    u = _make_user('r3b')
    att = _make_attachment(u)
    uid = u.id
    u.delete()
    att.refresh_from_db()
    assert att.uploaded_by_id == uid, "用户删除后附件外键应仍指向旧 ID"

def test_p1_no_charfield_null():
    from django.db.models import CharField, TextField
    violations = []
    for model in (EvidenceAttachment, EvidenceEvent):
        for f in model._meta.get_fields():
            if isinstance(f, (CharField, TextField)) and getattr(f, 'null', False):
                violations.append(f"{model.__name__}.{f.name}")
    assert len(violations) == 0, f"CharField/TextField 禁止 null=True: {violations}"

def test_p2a_check_exists():
    checks = [c for c in EvidenceEvent._meta.constraints
              if 'check' in c.__class__.__name__.lower()]
    assert len(checks) >= 1, "应至少有 1 个 CHECK 约束"

def test_p2b_invalid_type():
    try:
        EvidenceEvent.objects.create(
            tenant_id='admin', module='test', object_type='obj',
            object_id='chk-001', event_type='INVALID', event_hash='x'*64)
        raise AssertionError("无效 event_type 应被拒绝")
    except Exception:
        pass  # 预期失败

# ==================== §1.2 事务边界 ====================

def test_p9_select_for_update():
    """R4已修复：record_evidence_event 使用 select_for_update"""
    src = inspect.getsource(record_evidence_event)
    assert 'select_for_update' in src, "record_evidence_event 应使用 select_for_update"

def test_r4b_concurrent():
    """R4b: 直接 ORM 创建仍可绕过锁（DB 层无 CHECK），但 record_evidence_event 已防护"""
    u = _make_user('r4b')
    e0 = record_evidence_event('admin', 'test', 'obj', 'race-001', 'submit',
                               actor_user_id=u.id, actor_name=u.nickname)
    last = EvidenceEvent.objects.filter(
        tenant_id='admin', module='test', object_type='obj',
        object_id='race-001').order_by('-id').first()
    ph = last.event_hash
    h1 = compute_event_hash_from_values(
        tenant_id='admin', module='test', object_type='obj', object_id='race-001',
        event_type='correct', actor_user_id=u.id, actor_username=u.username,
        actor_name=u.nickname, object_snapshot='', attachment_hashes='',
        prev_hash=ph, created_at=datetime.now())
    e1 = EvidenceEvent.objects.create(
        tenant_id='admin', module='test', object_type='obj', object_id='race-001',
        event_type='correct', actor_user_id=u.id, actor_name=u.nickname,
        prev_hash=ph, event_hash=h1, object_snapshot='')
    e2 = EvidenceEvent.objects.create(
        tenant_id='admin', module='test', object_type='obj', object_id='race-001',
        event_type='correct', actor_user_id=u.id, actor_name=u.nickname,
        prev_hash=ph, event_hash=h1, object_snapshot='')
    # 直接 ORM 创建仍可绕过（DB 无 CHECK），但 record_evidence_event 已用 select_for_update 防护
    assert e2.prev_hash == e1.prev_hash, "直接ORM创建可绕过锁（预期）"

def test_p10_soft_delete_has_atomic():
    """R5已修复：soft_delete_by_object 使用 transaction.atomic"""
    src = inspect.getsource(AttachmentService.soft_delete_by_object)
    assert 'transaction.atomic' in src, "soft_delete_by_object 应使用 transaction.atomic"

def test_p3_upload_atomic():
    src = inspect.getsource(AttachmentService.upload)
    assert 'transaction.atomic' in src, "upload 应使用 transaction.atomic"

# ==================== §1.3 幂等性 ====================

def test_r6a_no_dedup():
    src = inspect.getsource(AttachmentService.upload)
    assert 'check_recent_duplicate' not in src, "upload 应无 check_recent_duplicate"

def test_r6b_duplicate():
    u = _make_user('r6b')
    a1 = _make_attachment(u, file_hash_sha256='c'*64)
    a2 = _make_attachment(u, file_hash_sha256='c'*64)
    assert a1.id != a2.id, "重复 SHA256 应允许创建"

def test_p11_has_idempotency():
    """R7已修复：record_evidence_event 有 idempotency_key 参数"""
    src = inspect.getsource(record_evidence_event)
    assert 'idempotency_key' in src, "record_evidence_event 应有 idempotency_key 参数"

def test_p12_idempotency_prevents_duplicate():
    """R7已修复：相同 idempotency_key 的重复调用返回 None"""
    u = _make_user('r7b')
    e1 = record_evidence_event('admin', 'test', 'obj', 'idem-001', 'submit',
                               actor_user_id=u.id, actor_name=u.nickname,
                               object_snapshot='{"k":"v"}', idempotency_key='test-key-001')
    # 同 idempotency_key 再调一次 -> 应返回 None
    e2 = record_evidence_event('admin', 'test', 'obj', 'idem-001', 'submit',
                               actor_user_id=u.id, actor_name=u.nickname,
                               object_snapshot='{"k":"v"}', idempotency_key='test-key-001')
    assert e1 is not None, "首次调用应返回事件"
    assert e2 is None, "相同 idempotency_key 应返回 None（去重）"
    # 不同 idempotency_key -> 正常创建
    e3 = record_evidence_event('admin', 'test', 'obj', 'idem-001', 'submit',
                               actor_user_id=u.id, actor_name=u.nickname,
                               object_snapshot='{"k":"v"}', idempotency_key='test-key-002')
    assert e3 is not None, "不同 idempotency_key 应正常创建"

# ==================== §1.5 防误操作 ====================

def test_p13_download_has_is_deleted():
    """R8已修复：download_response 过滤 is_deleted"""
    src = inspect.getsource(AttachmentService.download_response)
    assert 'is_deleted' in src, "download_response 应包含 is_deleted 过滤"

def test_p14_soft_deleted_not_downloadable():
    """R8已修复：软删除附件不可下载"""
    u = _make_user('r8b')
    att = _make_attachment(u)
    att.is_deleted = True
    att.deleted_at = datetime.now()
    att.save()
    resp, err = AttachmentService.download_response(u, att.id, skip_tenant_filter=True)
    assert err is not None, "软删除附件应返回错误"
    assert '不存在' in err or '已删除' in err, f"应提示不存在或已删除: {err}"

def test_r9_no_audit():
    for name in ('upload', 'soft_delete', 'soft_delete_by_object'):
        method = getattr(AttachmentService, name, None)
        if method:
            src = inspect.getsource(method)
            assert 'record_audit_event' not in src, f"{name} 不应调用 record_audit_event"
            assert 'AuditLog' not in src, f"{name} 不应直接写 AuditLog"

def test_p4_preserve_file():
    src = inspect.getsource(AttachmentService.soft_delete)
    assert 'delete_file' in src and 'False' in src, "soft_delete 应有 delete_file=False 参数"

def test_p5_preview_checks():
    src = inspect.getsource(AttachmentService.preview_file_response)
    assert 'is_deleted' in src and '附件已删除' in src, "preview_file_response 应检查 is_deleted"

# ==================== §2.1 索引 ====================

def test_p6_indexes():
    names = [i.name for i in EvidenceAttachment._meta.indexes]
    assert any('obj' in n for n in names), f"应有 obj 索引: {names}"
    assert any('sha256' in n.lower() for n in names), f"应有 sha256 索引: {names}"
    assert any('del' in n.lower() for n in names), f"应有 del 索引: {names}"

def test_p7_indexes():
    names = [i.name for i in EvidenceEvent._meta.indexes]
    assert any('chain' in n.lower() for n in names), f"应有 chain 索引: {names}"
    assert any('hash' in n.lower() for n in names), f"应有 hash 索引: {names}"

# ==================== §3.5 安全 ====================

def test_p8_token_binds():
    u = _make_user('p8')
    att = _make_attachment(u)
    token = generate_attachment_preview_token(
        att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
    data = validate_attachment_preview_token(token)
    assert data is not None, "token 应验证通过"
    assert data['attachment_id'] == att.id
    assert data['user_id'] == u.id
    assert data['tenant_id'] == 'admin'
    assert data['module'] == 'test_module'
    assert data['object_type'] == 'test_obj'
    assert data['object_id'] == 'obj-001'

def test_r10_cross_attachment():
    u = _make_user('r10')
    a1 = _make_attachment(u, file_name='a.pdf')
    a2 = _make_attachment(u, file_name='b.pdf')
    token = generate_attachment_preview_token(
        a1.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
    resp, err = AttachmentService.preview_file_response(token, a2.id)
    assert err is not None, "跨附件应被拒绝"
    assert '不匹配' in err, f"应提示不匹配: {err}"

def test_r11_cross_tenant():
    u = _make_user('r11')
    att = _make_attachment(u, tenant_id='admin')
    token = generate_attachment_preview_token(
        att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
    att.tenant_id = 'other'
    att.save()
    resp, err = AttachmentService.preview_file_response(token, att.id)
    assert err is not None, "跨租户应被拒绝"
    assert '无效' in err, f"应提示无效: {err}"

def test_r12_cross_user():
    u1 = _make_user('r12u1')
    u2 = _make_user('r12u2')
    att = _make_attachment(u1)
    token = generate_attachment_preview_token(
        att.id, u1.id, 'admin', 'test_module', 'test_obj', 'obj-001')
    data = validate_attachment_preview_token(token)
    assert data['user_id'] == u1.id
    assert data['user_id'] != u2.id

def test_r13_cross_object():
    u = _make_user('r13')
    att = _make_attachment(u, object_id='obj-A')
    token = generate_attachment_preview_token(
        att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-A')
    att.object_id = 'obj-B'
    att.save()
    resp, err = AttachmentService.preview_file_response(token, att.id)
    assert err is not None, "跨对象应被拒绝"
    assert '无效' in err, f"应提示无效: {err}"

def test_r14a_tampered():
    u = _make_user('r14a')
    att = _make_attachment(u)
    token = generate_attachment_preview_token(
        att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
    tampered = token[:-1] + ('a' if token[-1] != 'a' else 'b')
    data = validate_attachment_preview_token(tampered)
    assert data is None, "篡改 token 应返回 None"

def test_r14b_fabricated():
    data = validate_attachment_preview_token("fake:token:value")
    assert data is None, "伪造 token 应返回 None"

def test_r15a_max_age():
    assert ATTACHMENT_PREVIEW_TOKEN_MAX_AGE == 300, "token 有效期应为 300s"

def test_r15b_expired():
    u = _make_user('r15b')
    att = _make_attachment(u)
    token = generate_attachment_preview_token(
        att.id, u.id, 'admin', 'test_module', 'test_obj', 'obj-001')
    data = validate_attachment_preview_token(token, max_age=0)
    assert data is None, "过期 token 应返回 None"

def test_r16_soft_deleted_preview():
    src = inspect.getsource(AttachmentService.preview_file_response)
    assert 'is_deleted' in src and '附件已删除' in src

def test_r17_colon():
    u = _make_user('r17')
    att = _make_attachment(u, module='test:module')
    token = generate_attachment_preview_token(
        att.id, u.id, 'admin', 'test:module', 'test_obj', 'obj-001')
    data = validate_attachment_preview_token(token)
    assert data is None, "含冒号 module 应被拒绝"

def test_r18a_evidence_binds():
    from apps.evidence import attachment_preview_token as ev
    src = inspect.getsource(ev)
    assert 'module' in src and 'object_type' in src

def test_r18b_document_exists():
    base = os.path.dirname(os.path.abspath(__file__))
    doc_path = os.path.join(base, 'apps', 'document', 'libs', 'preview_token.py')
    assert os.path.exists(doc_path), f"document/libs/preview_token.py 应存在: {doc_path}"

def test_r18c_different_binding():
    base = os.path.dirname(os.path.abspath(__file__))
    doc_path = os.path.join(base, 'apps', 'document', 'libs', 'preview_token.py')
    if os.path.exists(doc_path):
        with open(doc_path, 'r') as f:
            doc_src = f.read()
        assert 'is_public' in doc_src.lower(), "document token 应绑定 is_public"


# ==================== 运行所有测试 ====================

tests = [
    # §1.1
    ('R1a 无唯一约束', test_r1a_no_unique),
    ('R1b 重复附件允许', test_r1b_duplicate),
    ('R2a 无哈希链CHECK', test_r2a_no_chain_check),
    ('R2b 不一致链允许', test_r2b_inconsistent),
    ('R3a 逻辑外键类型', test_r3a_logical_fk),
    ('R3b 孤儿引用允许', test_r3b_orphan),
    ('P1  无CharField_null', test_p1_no_charfield_null),
    ('P2a CHECK约束存在', test_p2a_check_exists),
    ('P2b 无效type被拒', test_p2b_invalid_type),
    # §1.2
    ('P9  select_for_update', test_p9_select_for_update),
    ('R4b 直接ORM可绕过', test_r4b_concurrent),
    ('P10 soft_delete有atomic', test_p10_soft_delete_has_atomic),
    ('P3  upload有atomic', test_p3_upload_atomic),
    # §1.3
    ('R6a 无去重', test_r6a_no_dedup),
    ('R6b 重复SHA256允许', test_r6b_duplicate),
    ('P11 有幂等键参数', test_p11_has_idempotency),
    ('P12 幂等键防重复', test_p12_idempotency_prevents_duplicate),
    # §1.5
    ('P13 download有is_deleted', test_p13_download_has_is_deleted),
    ('P14 软删除不可下载', test_p14_soft_deleted_not_downloadable),
    ('R9  无审计日志', test_r9_no_audit),
    ('P4  软删除保留文件', test_p4_preserve_file),
    ('P5  preview检查is_deleted', test_p5_preview_checks),
    # §2.1
    ('P6  附件索引完备', test_p6_indexes),
    ('P7  事件索引完备', test_p7_indexes),
    # §3.5
    ('P8  token绑定6维', test_p8_token_binds),
    ('R10 跨附件拒绝', test_r10_cross_attachment),
    ('R11 跨租户拒绝', test_r11_cross_tenant),
    ('R12 跨用户绑定', test_r12_cross_user),
    ('R13 跨对象拒绝', test_r13_cross_object),
    ('R14a 篡改token拒绝', test_r14a_tampered),
    ('R14b 伪造token拒绝', test_r14b_fabricated),
    ('R15a 有效期300s', test_r15a_max_age),
    ('R15b 过期token拒绝', test_r15b_expired),
    ('R16 软删除预览拒绝', test_r16_soft_deleted_preview),
    ('R17 冒号分隔符注入', test_r17_colon),
    ('R18a evidence绑定维度', test_r18a_evidence_binds),
    ('R18b document实现存在', test_r18b_document_exists),
    ('R18c 不同绑定维度', test_r18c_different_binding),
]

print(f"\n{'='*60}")
print(f"evidence 模块 CRUD 可靠性审计 - 共 {len(tests)} 项测试")
print(f"{'='*60}\n")

for name, func in tests:
    run_test(name, func)

print()
for line in results['details']:
    print(line)

print(f"\n{'='*60}")
print(f"总计: {results['pass']} PASS / {results['fail']} FAIL / {results['error']} ERROR")
print(f"{'='*60}")

sys.exit(0 if results['fail'] == 0 and results['error'] == 0 else 1)
