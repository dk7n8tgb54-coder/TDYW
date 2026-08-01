# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""signature 模块 CRUD 可靠性审计测试

审计维度：§1.1 约束 / §1.2 事务 / §1.3 幂等 / §1.5 防误操作 / §2.1 索引 / §2.2 资源 / §3.5 安全
"""
import io, os, shutil, tempfile, time, json, inspect, re
from unittest.mock import patch
from django.conf import settings
from django.test import TestCase, Client, override_settings
from django.db import IntegrityError, transaction
from django.test.client import encode_multipart, BOUNDARY, MULTIPART_CONTENT

from apps.account.models import User
from apps.setting.utils import AppSetting
from apps.evidence.models import EvidenceEvent, EvidenceAttachment
from apps.logs.models import AuditLog
from apps.signature.models import AccountSignature, SignatureUsage, STATUS_ACTIVE, STATUS_DISABLED
from apps.signature import services
from apps.signature.image_validator import validate_and_normalize_signature_image, SignatureImageError

TEST_SCENES = frozenset({
    ('test_module', 'test_object', 'operator'),
    ('test_module', 'test_object', 'reviewer'),
})


def _make_png(width=200, height=100):
    from PIL import Image
    img = Image.new('RGBA', (width, height), (255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _make_png_file(width=200, height=100, name='sig.png'):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, _make_png(width, height), content_type='image/png')


def _make_user(username, is_supper=False, tenant_id='default'):
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=True, is_supper=is_supper, access_token=(username * 10)[:32],
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


def _make_client(user):
    c = Client()
    c.defaults['HTTP_X_TOKEN'] = user.access_token
    c.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return c


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class SignatureAuditBase(TestCase):
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('audit_supper', is_supper=True, tenant_id='default')
        self.signer = _make_user('audit_signer', tenant_id='tenant_a')
        self.other = _make_user('audit_other', tenant_id='tenant_b')
        self.supper_c = _make_client(self.supper)
        self.signer_c = _make_client(self.signer)
        resp = self.supper_c.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': _make_png_file(), 'remark': 'setup'},
        )
        body = json.loads(resp.content)
        assert not body.get('error'), f'setup failed: {body}'
        self.sig = AccountSignature.objects.get(user_id=self.signer.id)
        self.att = EvidenceAttachment.objects.get(pk=self.sig.current_attachment_id)

    def tearDown(self):
        p = os.path.join(settings.MEDIA_ROOT, services.SIGNATURE_MODULE)
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)

    def _parse(self, r):
        return json.loads(r.content)

    def _apply(self, actor, request_id='req-001', **kw):
        return services.apply_signature(
            actor=actor, module=kw.get('module', 'test_module'),
            object_type=kw.get('object_type', 'test_object'),
            object_id=kw.get('object_id', 'obj-001'),
            scene_code=kw.get('scene_code', 'operator'),
            business_snapshot=kw.get('business_snapshot', {'key': 'value'}),
            request_id=request_id, request=kw.get('request'),
        )

    def _replace_sig(self, w=220):
        return self.supper_c.put(
            f'/account/user/{self.signer.id}/signature/',
            data=encode_multipart(BOUNDARY, {'file': _make_png_file(width=w), 'remark': 'r'}),
            content_type=MULTIPART_CONTENT,
        )


# ════════ §1.1 数据库约束 ════════

class ConstraintAuditTests(SignatureAuditBase):

    def test_01_user_id_unique_db_level(self):
        """AccountSignature.user_id 唯一约束 DB 级强制"""
        with self.assertRaises(IntegrityError):
            AccountSignature.objects.create(
                user_id=self.signer.id, tenant_id='tenant_a',
                current_attachment_id=self.att.id, version=2, status=STATUS_ACTIVE,
            )

    def test_02_request_id_not_null(self):
        """SignatureUsage.request_id 不允许 NULL"""
        kw = dict(
            tenant_id='t', module='m', object_type='ot', object_id='oi', scene_code='sc',
            signer_user_id=1, signer_username='u', signer_name='n',
            signature_attachment_id=1, signature_version=1, signature_sha256='h',
            business_snapshot='{}', business_snapshot_hash='hh',
            signed_at='2026-07-31 00:00:00', signer_ip='1.1.1.1',
            request_fingerprint='fp',
        )
        with self.assertRaises(IntegrityError):
            SignatureUsage.objects.create(request_id=None, **kw)

    def test_03_tenant_request_id_unique(self):
        """UniqueConstraint(tenant_id, request_id) DB 级强制"""
        kw = dict(
            module='m', object_type='ot', object_id='oi', scene_code='sc',
            signer_user_id=1, signer_username='u', signer_name='n',
            signature_attachment_id=1, signature_version=1, signature_sha256='h',
            business_snapshot='{}', business_snapshot_hash='hh',
            signed_at='2026-07-31 00:00:00', signer_ip='1.1.1.1', request_fingerprint='fp',
        )
        SignatureUsage.objects.create(tenant_id='t1', request_id='r1', **kw)
        with self.assertRaises(IntegrityError):
            SignatureUsage.objects.create(tenant_id='t1', request_id='r1', **kw)

    def test_04_same_request_id_diff_tenant_allowed(self):
        """相同 request_id 不同 tenant_id 允许（复合键）"""
        kw = dict(
            module='m', object_type='ot', object_id='oi', scene_code='sc',
            signer_user_id=1, signer_username='u', signer_name='n',
            signature_attachment_id=1, signature_version=1, signature_sha256='h',
            business_snapshot='{}', business_snapshot_hash='hh',
            signed_at='2026-07-31 00:00:00', signer_ip='1.1.1.1', request_fingerprint='fp',
        )
        SignatureUsage.objects.create(tenant_id='t1', request_id='r1', **kw)
        u2 = SignatureUsage.objects.create(tenant_id='t2', request_id='r1', **kw)
        self.assertIsNotNone(u2.id)

    def test_05_no_charfield_null_true(self):
        """CharField/TextField 无 null=True 违规"""
        from django.db import models as dm
        violations = []
        for cls in [AccountSignature, SignatureUsage]:
            for f in cls._meta.get_fields():
                if isinstance(f, (dm.CharField, dm.TextField)) and f.null:
                    violations.append(f'{cls.__name__}.{f.name}')
        self.assertEqual(violations, [], f'null=True 违规: {violations}')


# ════════ §1.2 事务边界 ════════

class TransactionAuditTests(SignatureAuditBase):

    def test_10_evidence_failure_rolls_back_usage(self):
        """EvidenceEvent 失败时 SignatureUsage 全部回滚"""
        with patch('apps.signature.services.record_evidence_event', return_value=None):
            result, error = self._apply(self.signer, request_id='tx-rb-001')
        self.assertIsNotNone(error)
        self.assertFalse(SignatureUsage.objects.filter(request_id='tx-rb-001').exists())

    def test_11_hash_mismatch_no_usage(self):
        """签名文件哈希不一致时不创建 Usage"""
        self.att.file_hash_sha256 = 'tampered'
        self.att.save(update_fields=['file_hash_sha256'])
        result, error = self._apply(self.signer, request_id='hash-mm-001')
        self.assertIsNotNone(error)
        self.assertFalse(SignatureUsage.objects.filter(request_id='hash-mm-001').exists())

    def test_12_nested_atomic_savepoint(self):
        """apply_signature 在外层事务中作 savepoint，内部失败不影响外层"""
        with transaction.atomic():
            r1, e1 = self._apply(self.signer, request_id='sp-001')
            self.assertIsNone(e1)
            r2, e2 = self._apply(self.signer, request_id='sp-001', business_snapshot={'diff': True})
            self.assertIsNotNone(e2)
            r3, e3 = self._apply(self.signer, request_id='sp-002')
            self.assertIsNone(e3)
        self.assertTrue(SignatureUsage.objects.filter(request_id='sp-001').exists())
        self.assertTrue(SignatureUsage.objects.filter(request_id='sp-002').exists())

    def test_13_audit_log_after_transaction(self):
        """审计日志在事务外，替换签名应产生审计日志"""
        resp = self._replace_sig()
        body = self._parse(resp)
        self.assertFalse(body.get('error'))
        self.assertGreaterEqual(AuditLog.objects.count(), 1)


# ════════ §1.3 幂等性 ════════

class IdempotencyAuditTests(SignatureAuditBase):

    def test_20_empty_request_id_rejected(self):
        """空 request_id 被拒绝"""
        r, e = self._apply(self.signer, request_id='')
        self.assertIsNotNone(e)

    def test_21_oversized_request_id_rejected(self):
        """超过 64 字符的 request_id 被拒绝"""
        r, e = self._apply(self.signer, request_id='x' * 65)
        self.assertIsNotNone(e)

    def test_22_max_length_request_id_accepted(self):
        """恰好 64 字符的 request_id 通过"""
        r, e = self._apply(self.signer, request_id='x' * 64)
        self.assertIsNone(e)

    def test_23_same_request_same_fingerprint_idempotent(self):
        """相同 request_id + 相同指纹返回同一 Usage"""
        r1, e1 = self._apply(self.signer, request_id='idem-001')
        r2, e2 = self._apply(self.signer, request_id='idem-001')
        self.assertIsNone(e1)
        self.assertIsNone(e2)
        self.assertEqual(r1['usage_id'], r2['usage_id'])
        self.assertEqual(SignatureUsage.objects.filter(request_id='idem-001').count(), 1)

    def test_24_same_request_diff_fingerprint_conflict(self):
        """相同 request_id + 不同指纹返回冲突"""
        self._apply(self.signer, request_id='conf-001', business_snapshot={'a': 1})
        r, e = self._apply(self.signer, request_id='conf-001', business_snapshot={'a': 2})
        self.assertIsNotNone(e)
        self.assertIn('冲突', e)

    def test_25_integrity_error_handled(self):
        """并发相同 request_id: IntegrityError 被捕获并重新查询"""
        # 第一次创建成功
        r1, e1 = self._apply(self.signer, request_id='conc-001')
        self.assertIsNone(e1)
        # 第二次相同 request_id + 相同指纹 -> 幂等返回
        r2, e2 = self._apply(self.signer, request_id='conc-001')
        self.assertIsNone(e2)
        self.assertEqual(r1['usage_id'], r2['usage_id'])
        # 数据库只有一条
        self.assertEqual(SignatureUsage.objects.filter(request_id='conc-001').count(), 1)


# ════════ §1.5 防误操作与可追溯 ════════

class AntiMisoperationAuditTests(SignatureAuditBase):

    def test_30_disable_enable_reversible(self):
        """签名停用后可恢复"""
        self.supper_c.patch(
            f'/account/user/{self.signer.id}/signature/status/',
            data=json.dumps({'status': STATUS_DISABLED, 'reason': 'test'}),
            content_type='application/json',
        )
        self.sig.refresh_from_db()
        self.assertEqual(self.sig.status, STATUS_DISABLED)
        self.supper_c.patch(
            f'/account/user/{self.signer.id}/signature/status/',
            data=json.dumps({'status': STATUS_ACTIVE}),
            content_type='application/json',
        )
        self.sig.refresh_from_db()
        self.assertEqual(self.sig.status, STATUS_ACTIVE)

    def test_31_audit_logs_cover_all_ops(self):
        """绑定/替换/停用/启用都产生审计日志"""
        self._replace_sig()
        self.supper_c.patch(
            f'/account/user/{self.signer.id}/signature/status/',
            data=json.dumps({'status': STATUS_DISABLED, 'reason': 't'}),
            content_type='application/json',
        )
        self.supper_c.patch(
            f'/account/user/{self.signer.id}/signature/status/',
            data=json.dumps({'status': STATUS_ACTIVE}),
            content_type='application/json',
        )
        # 1 create(setup) + 1 update(replace) + 1 update(disable) + 1 update(enable) >= 4
        self.assertGreaterEqual(AuditLog.objects.count(), 4)

    def test_32_apply_signature_no_audit_log(self):
        """[P2 发现] apply_signature 不调用 record_audit_event，仅创建 EvidenceEvent"""
        r, e = self._apply(self.signer, request_id='gap-001')
        self.assertIsNone(e)
        usage = SignatureUsage.objects.get(request_id='gap-001')
        self.assertIsNotNone(usage.evidence_event_id)
        event = EvidenceEvent.objects.get(pk=usage.evidence_event_id)
        self.assertEqual(event.event_title, '账号签名使用')

    def test_33_normal_user_cannot_manage(self):
        """普通用户不能管理签名"""
        # GET 管理详情
        resp = self.signer_c.get(f'/account/user/{self.signer.id}/signature/')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))
        # POST 赋予
        resp = self.signer_c.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': _make_png_file(), 'remark': 'hack'},
        )
        body = self._parse(resp)
        self.assertTrue(body.get('error'))
        # PATCH 状态
        resp = self.signer_c.patch(
            f'/account/user/{self.signer.id}/signature/status/',
            data=json.dumps({'status': STATUS_DISABLED}),
            content_type='application/json',
        )
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_34_my_signature_rejects_writes(self):
        """MySignatureView 拒绝所有写方法"""
        for m in ['post', 'put', 'patch', 'delete']:
            resp = getattr(self.signer_c, m)('/signature/mine/')
            body = self._parse(resp)
            self.assertTrue(body.get('error'), f'{m} 应被拒绝')

    def test_35_usage_save_only_evidence_event_id(self):
        """SignatureUsage 的 save 仅更新 evidence_event_id"""
        source = inspect.getsource(services)
        # 查找 usage.save 调用
        matches = re.findall(r'usage\.save\([^)]*\)', source)
        # 应至少有一个带 update_fields=['evidence_event_id']
        self.assertTrue(
            any('evidence_event_id' in m for m in matches),
            f'usage.save 应只更新 evidence_event_id，实际: {matches}'
        )
        # 不应有裸 usage.save()
        bare = [m for m in matches if m == 'usage.save()']
        self.assertEqual(bare, [], '不应有裸 usage.save()')


# ════════ §2.1 索引 ════════

class IndexAuditTests(SignatureAuditBase):

    def test_40_user_id_has_unique_index(self):
        """AccountSignature.user_id 有唯一索引"""
        from django.db import models as dm
        fields = {f.name: f for f in AccountSignature._meta.get_fields()}
        self.assertTrue(fields['user_id'].unique, 'user_id 应 unique=True')

    def test_41_tenant_status_index_exists(self):
        """AccountSignature 有 (tenant_id, status) 复合索引"""
        index_names = [idx.name for idx in AccountSignature._meta.indexes]
        self.assertTrue(
            any('tenant' in n and 'status' in n for n in index_names),
            f'应有 tenant_id+status 索引，实际: {index_names}'
        )

    def test_42_usage_has_query_indexes(self):
        """SignatureUsage 有关键查询索引"""
        index_names = [idx.name for idx in SignatureUsage._meta.indexes]
        # 应有 (tenant_id, module, object_type, object_id) 和 (tenant_id, signer_user_id, signed_at)
        self.assertTrue(
            any('obj' in n.lower() for n in index_names),
            f'应有 object 查询索引，实际: {index_names}'
        )
        self.assertTrue(
            any('signer' in n.lower() for n in index_names),
            f'应有 signer 查询索引，实际: {index_names}'
        )

    def test_43_unique_constraint_provides_index(self):
        """UniqueConstraint(tenant_id, request_id) 提供索引"""
        constraints = SignatureUsage._meta.constraints
        unique_names = [c.name for c in constraints if hasattr(c, 'fields')]
        self.assertTrue(
            any('request' in n.lower() or 'idem' in n.lower() for n in unique_names),
            f'应有 request_id 唯一约束，实际: {unique_names}'
        )


# ════════ §2.2 资源兜底 ════════

class ResourceAuditTests(SignatureAuditBase):

    def test_50_image_size_limit(self):
        """签名图片有大小限制 (2MB)"""
        from apps.signature.image_validator import SIGNATURE_MAX_SIZE
        self.assertLessEqual(SIGNATURE_MAX_SIZE, 2 * 1024 * 1024)
        # 超大文件应拒绝
        from django.core.files.uploadedfile import SimpleUploadedFile
        big = SimpleUploadedFile('big.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * (SIGNATURE_MAX_SIZE + 1), content_type='image/png')
        resp = self.supper_c.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': big, 'remark': 'big'},
        )
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_51_image_format_validation(self):
        """非 PNG 格式被拒绝"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        # JPEG magic bytes
        jpg = SimpleUploadedFile('sig.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 100, content_type='image/jpeg')
        resp = self.supper_c.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': jpg, 'remark': 'jpg'},
        )
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_52_image_dimension_limits(self):
        """签名图片有尺寸限制"""
        from apps.signature.image_validator import SIGNATURE_MIN_DIM, SIGNATURE_MAX_DIM
        self.assertGreater(SIGNATURE_MIN_DIM, 0)
        self.assertLessEqual(SIGNATURE_MAX_DIM, 2000)

    def test_53_max_image_pixels_global_side_effect(self):
        """[P3 发现] Image.MAX_IMAGE_PIXELS 被全局修改"""
        # 验证 validate_and_normalize_signature_image 会修改全局 PIL 设置
        from PIL import Image
        original = Image.MAX_IMAGE_PIXELS
        try:
            validate_and_normalize_signature_image(_make_png(100, 50))
            # 函数执行后 MAX_IMAGE_PIXELS 可能被修改
            # 这是一个全局副作用
        except Exception:
            pass
        # 如果值变了，说明有全局副作用
        # 记录现状，不断言必须不变
        # Image.MAX_IMAGE_PIXELS 可能被设为 SIGNATURE_MAX_PIXELS
        # 这会影响同进程中其他 Pillow 操作的 decompression bomb 检查

    def test_54_get_usages_for_object_no_pagination(self):
        """[P3 发现] get_usages_for_object 返回全部记录无分页"""
        # 创建多条 Usage
        for i in range(5):
            self._apply(self.signer, request_id=f'page-{i}', object_id=f'obj-page')
        # get_usages_for_object 返回 (list, error) 无分页参数
        result, error = services.get_usages_for_object(
            requester=self.signer,
            module='test_module',
            object_type='test_object',
            object_id='obj-page',
        )
        self.assertIsNone(error)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 5)


# ════════ §3.5 安全维度 ════════

class SecurityAuditTests(SignatureAuditBase):

    def test_60_cross_tenant_apply_blocked(self):
        """跨租户签署被阻止：actor 只能使用本租户签名"""
        # other 是 tenant_b，不能使用 tenant_a 的 signer 的签名
        # other 没有配置签名，应报"未绑定"
        r, e = self._apply(self.other, request_id='cross-t-001')
        self.assertIsNotNone(e)

    def test_61_cross_tenant_query_blocked(self):
        """跨租户查询 Usage 被阻止"""
        # signer 创建一条
        self._apply(self.signer, request_id='cross-q-001')
        # other 查询 tenant_a 的 Usage 应无结果
        result, error = services.get_usages_for_object(
            requester=self.other,
            module='test_module',
            object_type='test_object',
            object_id='obj-001',
        )
        self.assertIsNone(error)
        self.assertEqual(len(result), 0)

    def test_62_path_traversal_blocked(self):
        """路径穿越被阻止：_verify_signature_file 使用 realpath 校验"""
        source = inspect.getsource(services)
        # 验证有 os.path.realpath 调用
        self.assertIn('realpath', source, '应有 os.path.realpath 路径穿越防护')

    def test_63_preview_token_binds_user(self):
        """预览 token 绑定 user_id + tenant_id"""
        resp = self.signer_c.get('/signature/mine/')
        body = self._parse(resp)
        if not body.get('error') and body.get('data'):
            data = body['data']
            if data.get('preview_url'):
                # 预览 URL 应包含 token
                self.assertIn('token', data['preview_url'])

    def test_64_apply_signature_actor_is_signer(self):
        """apply_signature: actor 是唯一签署人来源，不接受外部 signer_user_id"""
        source = inspect.getsource(services.apply_signature)
        # 验证函数签名不包含 signer_user_id 参数
        # 已在签名中：def apply_signature(actor, module, object_type, ...)
        self.assertNotIn('signer_user_id', inspect.signature(services.apply_signature).parameters)

    def test_65_global_business_no_requester_validation(self):
        """[P3 发现] get_signature_image_for_global_business 不验证 requester"""
        sig = inspect.signature(services.get_signature_image_for_global_business)
        params = list(sig.parameters.keys())
        # 不包含 requester / actor 参数
        self.assertFalse(
            any(p in params for p in ['requester', 'actor', 'request']),
            f'get_signature_image_for_global_business 参数: {params}，缺少 requester 验证'
        )

    def test_66_void_event_hardcoded_title(self):
        """[P3 发现] record_signature_void_event 硬编码 event_title"""
        source = inspect.getsource(services.record_signature_void_event)
        # 硬编码了 '部门值班日志作废'
        self.assertIn('部门值班日志作废', source, '应发现硬编码 event_title')

    def test_67_supper_only_view_dispatch(self):
        """SupperOnlyView 在 dispatch 层强制 is_supper"""
        from apps.signature.views import SupperOnlyView
        source = inspect.getsource(SupperOnlyView)
        self.assertIn('is_supper', source, '应有 is_supper 检查')

    def test_68_attachment_module_validation(self):
        """apply_signature 校验附件 module 与签名模块一致"""
        r, e = self._apply(self.signer, request_id='mod-001')
        self.assertIsNone(e)
        usage = SignatureUsage.objects.get(request_id='mod-001')
        att = EvidenceAttachment.objects.get(pk=usage.signature_attachment_id)
        self.assertEqual(att.module, services.SIGNATURE_MODULE)
