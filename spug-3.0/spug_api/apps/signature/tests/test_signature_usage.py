# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""账号签名第二阶段测试：SignatureUsage / apply_signature / 历史读取

覆盖：
- SignatureUsage 索引和唯一约束
- 生产场景注册表为空
- 未注册场景被拒绝；测试专用场景可调用
- actor 是唯一签署人来源；无法为其他账号代签
- 无签名 / 签名停用 / 账号停用 / 账号删除时拒绝
- 当前附件归属错误或跨租户时拒绝
- 文件丢失和文件哈希不一致时拒绝
- 客户端无法伪造附件、版本、哈希、IP 和签署时间
- 业务快照序列化和哈希稳定
- 相同 request_id 幂等返回同一 Usage
- 相同 request_id、不同上下文返回冲突
- 并发请求只创建一条 Usage 和一条 EvidenceEvent
- EvidenceEvent 失败时事务回滚
- 更换当前签名不改变既有 Usage
- 历史读取始终使用固定附件
- mine 只能查询本人
- 所有普通用户写方法不存在或被拒绝
- 本阶段没有修改任何业务模块
"""
import io
import os
import shutil
import tempfile
import time
import json
import hashlib
import threading
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, Client, override_settings
from django.db import IntegrityError, connection

from apps.account.models import User
from apps.setting.utils import AppSetting
from apps.evidence.models import EvidenceEvent, EvidenceAttachment
from apps.signature.models import AccountSignature, SignatureUsage, STATUS_ACTIVE, STATUS_DISABLED
from apps.signature import services


# 测试专用场景注册表（通过 override_settings 注入，不写入生产代码默认值）
TEST_SCENES = frozenset({
    ('test_module', 'test_object', 'operator'),
    ('test_module', 'test_object', 'reviewer'),
})


def _make_png(width=200, height=100, mode='RGBA'):
    from PIL import Image
    img = Image.new(mode, (width, height), (255, 0, 0, 128) if mode == 'RGBA' else (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _make_png_file(width=200, height=100, name='sig.png'):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, _make_png(width, height), content_type='image/png')


def _make_user(username, is_supper=False, tenant_id='default', is_active=True):
    token = (username * 10)[:32]
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=is_active, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return client


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SignatureUsageStage2Base(TestCase):
    """第二阶段测试基类：超管 + 签署人 + 已配置签名"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('supper_s2', is_supper=True, tenant_id='default')
        # 签署人（普通用户，tenant_a）
        self.signer = _make_user('signer_s2', tenant_id='tenant_a')
        self.signer_client = _make_client(self.signer)
        # 给 signer 配置签名（通过超管 HTTP 接口）
        self.supper_client = _make_client(self.supper)
        resp = self.supper_client.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': _make_png_file(), 'remark': 'stage2 setup'},
        )
        body = json.loads(resp.content)
        assert not body.get('error'), f'setup assign failed: {body.get("error")}'
        self.sig = AccountSignature.objects.get(user_id=self.signer.id)
        self.att_id = self.sig.current_attachment_id
        self.att = EvidenceAttachment.objects.get(pk=self.att_id)

    def tearDown(self):
        """清理测试产生的签名物理文件"""
        sig_base = os.path.join(settings.MEDIA_ROOT, services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _parse(self, response):
        return json.loads(response.content)


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class SignatureUsageConstraintTests(SignatureUsageStage2Base):
    """SignatureUsage 索引和唯一约束"""

    def test_tenant_request_id_unique_constraint(self):
        """(tenant_id, request_id) 唯一约束存在"""
        SignatureUsage.objects.create(
            tenant_id='tenant_a', module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator', signer_user_id=self.signer.id,
            signer_username='signer', signer_name='signer',
            signature_attachment_id=self.att_id, signature_version=1,
            signature_sha256='abc', business_snapshot_hash='def',
            signed_at='2026-07-17 10:00:00', signer_ip='1.1.1.1',
            request_id='req-001', request_fingerprint='fp-001',
        )
        with self.assertRaises(IntegrityError):
            SignatureUsage.objects.create(
                tenant_id='tenant_a', module='test_module', object_type='test_object',
                object_id='obj2', scene_code='reviewer', signer_user_id=self.signer.id,
                signer_username='signer', signer_name='signer',
                signature_attachment_id=self.att_id, signature_version=1,
                signature_sha256='abc', business_snapshot_hash='xyz',
                signed_at='2026-07-17 11:00:00', signer_ip='1.1.1.1',
                request_id='req-001', request_fingerprint='fp-002',
            )

    def test_different_tenant_same_request_id_allowed(self):
        """不同 tenant_id 允许相同 request_id（request_id 作用域为租户内）"""
        SignatureUsage.objects.create(
            tenant_id='tenant_a', module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator', signer_user_id=self.signer.id,
            signer_username='signer', signer_name='signer',
            signature_attachment_id=self.att_id, signature_version=1,
            signature_sha256='abc', business_snapshot_hash='def',
            signed_at='2026-07-17 10:00:00', signer_ip='1.1.1.1',
            request_id='req-shared', request_fingerprint='fp-1',
        )
        # 不同租户用相同 request_id 不应报错
        usage2 = SignatureUsage.objects.create(
            tenant_id='tenant_b', module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator', signer_user_id=self.signer.id,
            signer_username='signer', signer_name='signer',
            signature_attachment_id=self.att_id, signature_version=1,
            signature_sha256='abc', business_snapshot_hash='def',
            signed_at='2026-07-17 10:00:00', signer_ip='1.1.1.1',
            request_id='req-shared', request_fingerprint='fp-2',
        )
        self.assertIsNotNone(usage2.id)


class SceneRegistryTests(TestCase):
    """场景注册表测试"""

    def test_production_scenes_empty(self):
        """生产场景注册表必须精确等于已批准白名单"""
        expected = frozenset({
            services.DEPARTMENT_DUTY_LOG_SIGNATURE_SCENE,
        })
        self.assertEqual(services.SIGNATURE_SCENES, expected,
                         '生产场景注册表必须精确等于已批准白名单')

    def test_unregistered_scene_rejected(self):
        """未注册场景被 apply_signature 拒绝"""
        user = _make_user('u_scene')
        # 不注入 override_settings，使用生产空注册表
        result, err = services.apply_signature(
            actor=user, module='any_module', object_type='any_obj',
            object_id='o1', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-1')
        self.assertIsNotNone(err, '未注册场景应被拒绝')
        self.assertIn('未注册', err)
        self.assertIsNone(result)

    @override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
    def test_registered_scene_can_proceed(self):
        """注册场景可以通过场景校验（后续因无签名失败，但不是场景拒绝）"""
        user = _make_user('u_scene2')
        result, err = services.apply_signature(
            actor=user, module='test_module', object_type='test_object',
            object_id='o1', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-2')
        # 无签名 → 返回"未配置有效签名"，而非"未注册"
        self.assertIsNotNone(err)
        self.assertIn('未配置有效签名', err)


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class ApplySignatureActorTests(SignatureUsageStage2Base):
    """actor 是唯一签署人来源；无法代签"""

    def test_actor_is_signer(self):
        """apply_signature 返回的 signer_user_id == actor.id"""
        snapshot = {'doc_id': 'd1', 'title': '测试文档'}
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot=snapshot, request_id='req-actor-1',
            request=None)
        self.assertIsNone(err, err)
        self.assertEqual(result['signer_user_id'], self.signer.id)
        self.assertEqual(result['signer_username'], self.signer.username)

    def test_no_signer_user_id_param(self):
        """apply_signature 函数签名不接受 signer_user_id 参数"""
        import inspect
        sig = inspect.signature(services.apply_signature)
        self.assertNotIn('signer_user_id', sig.parameters)
        self.assertNotIn('signer_username', sig.parameters)

    def test_cannot_sign_for_other(self):
        """超管不能替 signer 签署（actor=超管 时签署人就是超管自己）"""
        # 超管尝试用自己 actor 身份"替" signer 签署
        # 但 actor=超管，超管没有签名 → 失败
        snapshot = {'doc_id': 'd2'}
        result, err = services.apply_signature(
            actor=self.supper, module='test_module', object_type='test_object',
            object_id='obj2', scene_code='operator',
            business_snapshot=snapshot, request_id='req-actor-2')
        self.assertIsNotNone(err)
        self.assertIn('未配置有效签名', err)

    def test_actor_deleted_rejected(self):
        """账号已逻辑删除时拒绝签署"""
        self.signer.deleted_by = self.supper
        self.signer.save()
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj3', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-actor-3')
        self.assertIsNotNone(err)
        self.assertIn('已删除', err)

    def test_actor_inactive_rejected(self):
        """账号停用时拒绝签署"""
        self.signer.is_active = False
        self.signer.save()
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj4', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-actor-4')
        self.assertIsNotNone(err)
        self.assertIn('已停用', err)

    def test_signature_disabled_rejected(self):
        """签名停用时拒绝签署"""
        services.disable_signature(self.supper, self.signer.id)
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj5', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-actor-5')
        self.assertIsNotNone(err)
        self.assertIn('未配置有效签名', err)


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class ApplySignatureAttachmentTests(SignatureUsageStage2Base):
    """附件归属和文件校验"""

    def test_attachment_owner_mismatch_rejected(self):
        """附件 object_id 与 actor 不一致时拒绝"""
        # 篡改 AccountSignature 指向另一个用户的附件
        other = _make_user('other_user', tenant_id='tenant_a')
        self.supper_client.post(
            f'/account/user/{other.id}/signature/',
            {'file': _make_png_file(width=210), 'remark': ''},
        )
        other_sig = AccountSignature.objects.get(user_id=other.id)
        other_att_id = other_sig.current_attachment_id

        # 把 signer 的绑定指向 other 的附件
        self.sig.current_attachment_id = other_att_id
        self.sig.save(update_fields=['current_attachment_id'])
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-att-1')
        self.assertIsNotNone(err)
        self.assertIn('归属', err)

    def test_attachment_tenant_mismatch_rejected(self):
        """附件租户与 actor 租户不一致时拒绝"""
        # 直接改附件租户模拟异常状态（正常流程不会出现）
        self.att.tenant_id = 'tenant_other'
        self.att.save(update_fields=['tenant_id'])
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-att-2')
        self.assertIsNotNone(err)
        self.assertIn('租户', err)

    def test_file_missing_rejected(self):
        """物理文件丢失时拒绝签署"""
        # 删除物理文件
        full_path = os.path.join(settings.MEDIA_ROOT, self.att.file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-att-3')
        self.assertIsNotNone(err)
        self.assertIn('文件不存在', err)

    def test_file_hash_mismatch_rejected(self):
        """文件实际哈希与数据库记录不一致时拒绝签署"""
        # 修改物理文件内容（但保持数据库 sha256 不变）
        full_path = os.path.join(settings.MEDIA_ROOT, self.att.file_path)
        with open(full_path, 'wb') as f:
            f.write(_make_png(width=300, height=150))
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-att-4')
        self.assertIsNotNone(err)
        self.assertIn('哈希不一致', err)

    def test_client_cannot_forge_attachment_id(self):
        """客户端无法伪造附件 ID：apply_signature 不接受 attachment_id 参数"""
        import inspect
        sig = inspect.signature(services.apply_signature)
        self.assertNotIn('attachment_id', sig.parameters)
        self.assertNotIn('signature_version', sig.parameters)
        self.assertNotIn('signature_sha256', sig.parameters)
        self.assertNotIn('tenant_id', sig.parameters)
        self.assertNotIn('signed_at', sig.parameters)
        self.assertNotIn('signer_ip', sig.parameters)

    def test_server_decides_signed_at_and_ip(self):
        """签署时间和 IP 由服务端决定"""
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'k': 'v'}, request_id='req-att-5',
            request=None)
        self.assertIsNone(err, err)
        self.assertTrue(result['signed_at'])  # 服务端生成
        # request=None 时 IP 为空串
        self.assertEqual(result['signer_ip'], '')


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class BusinessSnapshotTests(TestCase):
    """业务快照序列化和哈希稳定"""

    def test_canonicalize_stable_for_same_data(self):
        """相同逻辑数据产生相同字符串"""
        a = {'b': 2, 'a': 1, 'c': [1, 2, 3]}
        b = {'a': 1, 'b': 2, 'c': [1, 2, 3]}
        self.assertEqual(
            services.canonicalize_business_snapshot(a),
            services.canonicalize_business_snapshot(b))

    def test_canonicalize_field_order_independent(self):
        """字段顺序变化不改变输出"""
        a = {'z': 1, 'a': 2}
        b = {'a': 2, 'z': 1}
        self.assertEqual(
            services.canonicalize_business_snapshot(a),
            services.canonicalize_business_snapshot(b))

    def test_canonicalize_value_change_changes_output(self):
        """实际值变化必须改变输出"""
        a = {'a': 1}
        b = {'a': 2}
        self.assertNotEqual(
            services.canonicalize_business_snapshot(a),
            services.canonicalize_business_snapshot(b))

    def test_hash_stable(self):
        """相同数据哈希相同"""
        a = {'b': 2, 'a': 1}
        b = {'a': 1, 'b': 2}
        self.assertEqual(
            services.compute_business_snapshot_hash(a),
            services.compute_business_snapshot_hash(b))

    def test_hash_changes_on_value_change(self):
        """值变化哈希变化"""
        self.assertNotEqual(
            services.compute_business_snapshot_hash({'a': 1}),
            services.compute_business_snapshot_hash({'a': 2}))

    def test_rejects_datetime(self):
        """日期对象被拒绝"""
        import datetime
        with self.assertRaises(ValueError):
            services.canonicalize_business_snapshot({'d': datetime.datetime.now()})

    def test_rejects_decimal(self):
        """Decimal 被拒绝"""
        from decimal import Decimal
        with self.assertRaises(ValueError):
            services.canonicalize_business_snapshot({'d': Decimal('1.5')})

    def test_rejects_model_instance(self):
        """Model 实例被拒绝"""
        user = _make_user('snap_user')
        with self.assertRaises(ValueError):
            services.canonicalize_business_snapshot({'u': user})

    def test_rejects_nan(self):
        """NaN 被拒绝"""
        with self.assertRaises(ValueError):
            services.canonicalize_business_snapshot({'v': float('nan')})

    def test_accepts_none(self):
        """None 被接受（json null）"""
        s = services.canonicalize_business_snapshot(None)
        self.assertEqual(s, 'null')
        h = services.compute_business_snapshot_hash(None)
        self.assertEqual(len(h), 64)

    def test_bool_and_number_stable(self):
        """布尔值和数字表示稳定"""
        self.assertEqual(
            services.canonicalize_business_snapshot(True),
            services.canonicalize_business_snapshot(True))
        self.assertNotEqual(
            services.canonicalize_business_snapshot(True),
            services.canonicalize_business_snapshot(1))


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class ApplySignatureIdempotencyTests(SignatureUsageStage2Base):
    """幂等和冲突检测"""

    def test_same_request_id_returns_existing(self):
        """相同 request_id 重试返回同一 Usage"""
        snapshot = {'doc_id': 'd1', 'amount': 100}
        result1, err1 = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot=snapshot, request_id='req-idem-1',
            request=None)
        self.assertIsNone(err1, err1)
        result2, err2 = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot=snapshot, request_id='req-idem-1',
            request=None)
        self.assertIsNone(err2, err2)
        self.assertEqual(result1['usage_id'], result2['usage_id'])
        # 只有一条 Usage
        self.assertEqual(
            SignatureUsage.objects.filter(request_id='req-idem-1').count(), 1)
        # 只有一条 EvidenceEvent
        self.assertEqual(
            EvidenceEvent.objects.filter(
                module='test_module', object_type='test_object',
                object_id='obj1').count(), 1)

    def test_same_request_id_different_context_conflict(self):
        """相同 request_id、不同上下文返回冲突"""
        result1, err1 = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-idem-2',
            request=None)
        self.assertIsNone(err1, err1)
        # 改变 object_id，相同 request_id
        result2, err2 = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj2', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-idem-2',
            request=None)
        self.assertIsNotNone(err2)
        self.assertIn('冲突', err2)
        self.assertIsNone(result2)

    def test_same_request_id_different_snapshot_conflict(self):
        """相同 request_id、不同业务快照返回冲突"""
        result1, err1 = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-idem-3',
            request=None)
        self.assertIsNone(err1, err1)
        result2, err2 = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd2'}, request_id='req-idem-3',
            request=None)
        self.assertIsNotNone(err2)
        self.assertIn('冲突', err2)

    def test_concurrent_same_request_creates_one(self):
        """并发相同 (tenant_id, request_id) 只创建一条 Usage"""
        # Django TestCase 单事务内无法真正并发触发唯一约束竞争，
        # 此处通过 mock create 抛 IntegrityError 模拟并发胜者先创建，
        # 验证服务能正确回退到查询已有记录。
        snapshot = {'doc_id': 'd1'}
        # 预创建一条"对方胜出"的记录
        existing_usage = SignatureUsage.objects.create(
            tenant_id=self.signer.tenant_id, module='test_module',
            object_type='test_object', object_id='obj1', scene_code='operator',
            signer_user_id=self.signer.id, signer_username=self.signer.username,
            signer_name=self.signer.nickname,
            signature_attachment_id=self.att_id, signature_version=self.sig.version,
            signature_sha256=self.att.file_hash_sha256,
            business_snapshot=services.canonicalize_business_snapshot(snapshot),
            business_snapshot_hash=services.compute_business_snapshot_hash(snapshot),
            signed_at='2026-07-17 10:00:00', signer_ip='1.1.1.1',
            request_id='req-conc-1',
            request_fingerprint=services._compute_request_fingerprint(
                self.signer.tenant_id, self.signer.id, 'test_module',
                'test_object', 'obj1', 'operator',
                services.compute_business_snapshot_hash(snapshot)),
        )
        # mock create 抛 IntegrityError，模拟并发
        original_create = SignatureUsage.objects.create

        def fake_create(**kwargs):
            raise IntegrityError('Duplicate')

        with patch.object(SignatureUsage.objects, 'create', side_effect=fake_create):
            result, err = services.apply_signature(
                actor=self.signer, module='test_module', object_type='test_object',
                object_id='obj1', scene_code='operator',
                business_snapshot=snapshot, request_id='req-conc-1',
                request=None)
        self.assertIsNone(err, err)
        self.assertEqual(result['usage_id'], existing_usage.id)


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class ApplySignatureEvidenceEventTests(SignatureUsageStage2Base):
    """EvidenceEvent 接入和事务回滚"""

    def test_usage_and_event_created_together(self):
        """Usage 和 EvidenceEvent 在同一事务中创建"""
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-evt-1',
            request=None)
        self.assertIsNone(err, err)
        usage = SignatureUsage.objects.get(pk=result['usage_id'])
        self.assertIsNotNone(usage.evidence_event_id)
        event = EvidenceEvent.objects.get(pk=usage.evidence_event_id)
        # 证据快照包含 signature_usage_id
        snapshot = json.loads(event.object_snapshot)
        self.assertEqual(snapshot['signature_usage_id'], usage.id)
        self.assertEqual(snapshot['signature_sha256'], usage.signature_sha256)
        self.assertEqual(snapshot['business_snapshot_hash'], usage.business_snapshot_hash)
        self.assertEqual(snapshot['signer_user_id'], self.signer.id)
        self.assertEqual(snapshot['module'], 'test_module')
        # 不应包含图片 base64、绝对路径或预览令牌
        snap_str = event.object_snapshot
        self.assertNotIn('base64', snap_str.lower())
        self.assertNotIn(settings.MEDIA_ROOT, snap_str)
        self.assertNotIn('preview_token', snap_str)

    def test_evidence_event_failure_rolls_back_usage(self):
        """EvidenceEvent 失败时 Usage 回滚"""
        # mock record_evidence_event 返回 None 模拟失败
        with patch('apps.signature.services.record_evidence_event', return_value=None):
            result, err = services.apply_signature(
                actor=self.signer, module='test_module', object_type='test_object',
                object_id='obj1', scene_code='operator',
                business_snapshot={'doc_id': 'd1'}, request_id='req-evt-2',
                request=None)
        self.assertIsNotNone(err)
        self.assertIn('证据事件', err)
        self.assertIsNone(result)
        # Usage 不应存在
        self.assertFalse(
            SignatureUsage.objects.filter(request_id='req-evt-2').exists())
        # EvidenceEvent 也不应存在
        self.assertEqual(
            EvidenceEvent.objects.filter(
                module='test_module', object_type='test_object',
                object_id='obj1').count(), 0)

    def test_retry_does_not_duplicate_event(self):
        """相同 request_id 重试不重复创建 EvidenceEvent"""
        snapshot = {'doc_id': 'd1'}
        services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot=snapshot, request_id='req-evt-3', request=None)
        services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot=snapshot, request_id='req-evt-3', request=None)
        self.assertEqual(
            EvidenceEvent.objects.filter(
                module='test_module', object_type='test_object',
                object_id='obj1').count(), 1)


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class SignatureUsageImmutabilityTests(SignatureUsageStage2Base):
    """更换当前签名不改变既有 Usage；历史读取使用固定附件"""

    def test_replace_signature_keeps_existing_usage(self):
        """替换签名后既有 Usage 的附件和版本不变"""
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-immut-1',
            request=None)
        self.assertIsNone(err, err)
        old_usage_id = result['usage_id']
        old_att_id = result['signature_attachment_id']
        old_version = result['signature_version']
        old_sha = result['signature_sha256']

        # 替换签名
        from django.test.client import encode_multipart, BOUNDARY, MULTIPART_CONTENT
        body = encode_multipart(BOUNDARY, {'file': _make_png_file(width=220), 'remark': ''})
        self.supper_client.put(
            f'/account/user/{self.signer.id}/signature/',
            data=body, content_type=MULTIPART_CONTENT,
        )

        # 既有 Usage 不变
        usage = SignatureUsage.objects.get(pk=old_usage_id)
        self.assertEqual(usage.signature_attachment_id, old_att_id)
        self.assertEqual(usage.signature_version, old_version)
        self.assertEqual(usage.signature_sha256, old_sha)

        # 新签署使用新版本
        result2, err2 = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj2', scene_code='operator',
            business_snapshot={'doc_id': 'd2'}, request_id='req-immut-2',
            request=None)
        self.assertIsNone(err2, err2)
        self.assertEqual(result2['signature_version'], old_version + 1)
        self.assertNotEqual(result2['signature_attachment_id'], old_att_id)

    def test_render_uses_fixed_attachment(self):
        """get_signature_image_for_render 使用 Usage 固定的附件，不读当前签名"""
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-immut-3',
            request=None)
        self.assertIsNone(err, err)
        usage_id = result['usage_id']
        fixed_att_id = result['signature_attachment_id']

        # 替换签名
        from django.test.client import encode_multipart, BOUNDARY, MULTIPART_CONTENT
        body = encode_multipart(BOUNDARY, {'file': _make_png_file(width=230), 'remark': ''})
        self.supper_client.put(
            f'/account/user/{self.signer.id}/signature/',
            data=body, content_type=MULTIPART_CONTENT,
        )

        # 渲染读取的仍是旧附件
        info, err = services.get_signature_image_for_render(usage_id, self.signer)
        self.assertIsNone(err, err)
        self.assertEqual(info['attachment_id'], fixed_att_id)
        self.assertTrue(os.path.exists(info['file_path']))

    def test_render_no_fallback_to_current(self):
        """文件丢失时渲染报错，不回退到当前签名"""
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-immut-4',
            request=None)
        self.assertIsNone(err, err)
        usage_id = result['usage_id']

        # 删除 Usage 固定附件的物理文件
        usage = SignatureUsage.objects.get(pk=usage_id)
        att = EvidenceAttachment.objects.get(pk=usage.signature_attachment_id)
        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        os.remove(full_path)

        info, err = services.get_signature_image_for_render(usage_id, self.signer)
        self.assertIsNotNone(err)
        self.assertIn('不存在', err)
        self.assertIsNone(info)


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class HistoryReadTests(SignatureUsageStage2Base):
    """历史读取服务"""

    def test_get_usage_returns_dict(self):
        """get_usage 返回普通字典"""
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-read-1',
            request=None)
        self.assertIsNone(err, err)
        info, err = services.get_usage(result['usage_id'], self.signer)
        self.assertIsNone(err, err)
        self.assertIsInstance(info, dict)
        self.assertEqual(info['usage_id'], result['usage_id'])
        # 不返回 business_snapshot 全文
        self.assertNotIn('business_snapshot', info)
        self.assertIn('business_snapshot_hash', info)

    def test_get_usage_cross_tenant_rejected(self):
        """跨租户读取被拒绝"""
        result, err = services.apply_signature(
            actor=self.signer, module='test_module', object_type='test_object',
            object_id='obj1', scene_code='operator',
            business_snapshot={'doc_id': 'd1'}, request_id='req-read-2',
            request=None)
        self.assertIsNone(err, err)
        other = _make_user('other_tenant_reader', tenant_id='tenant_b')
        info, err = services.get_usage(result['usage_id'], other)
        self.assertIsNotNone(err)
        self.assertIn('无权限', err)

    def test_get_usages_for_object(self):
        """按业务对象查询历史列表"""
        for i in range(3):
            services.apply_signature(
                actor=self.signer, module='test_module', object_type='test_object',
                object_id='objX', scene_code='operator',
                business_snapshot={'i': i}, request_id=f'req-list-{i}',
                request=None)
        items, err = services.get_usages_for_object(
            self.signer, 'test_module', 'test_object', 'objX')
        self.assertIsNone(err, err)
        self.assertEqual(len(items), 3)

    def test_get_usage_not_authenticated_rejected(self):
        """未登录请求被拒绝"""
        info, err = services.get_usage(1, None)
        self.assertIsNotNone(err)


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class MySignatureWriteMethodTests(SignatureUsageStage2Base):
    """mine 接口只读，所有写方法被拒绝"""

    def test_mine_get_returns_self_signature(self):
        """mine 只查询本人"""
        resp = self.signer_client.get('/signature/mine/')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))
        self.assertTrue(body['data']['available'])
        self.assertEqual(body['data']['user_id'], self.signer.id)

    def test_mine_post_rejected(self):
        resp = self.signer_client.post('/signature/mine/', {})
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_mine_put_rejected(self):
        resp = self.signer_client.put('/signature/mine/', {})
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_mine_patch_rejected(self):
        resp = self.signer_client.patch(
            '/signature/mine/', data='{}', content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_mine_delete_rejected(self):
        resp = self.signer_client.delete('/signature/mine/')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_mine_no_user_id_param(self):
        """mine 不接受 user_id 参数（只查本人）"""
        # 即使传 user_id 也被忽略，仍返回本人
        resp = self.signer_client.get('/signature/mine/?user_id=999')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['user_id'], self.signer.id)


@override_settings(SIGNATURE_SCENES_OVERRIDE=TEST_SCENES)
class MySignatureAvailabilityTests(SignatureUsageStage2Base):
    """mine 在各种状态下返回 available=False"""

    def test_disabled_returns_unavailable(self):
        """签名停用时 available=False"""
        services.disable_signature(self.supper, self.signer.id)
        result = services.get_my_current_signature(self.signer)
        self.assertFalse(result['available'])

    def test_account_inactive_returns_unavailable(self):
        """账号停用时 available=False"""
        self.signer.is_active = False
        self.signer.save()
        result = services.get_my_current_signature(self.signer)
        self.assertFalse(result['available'])

    def test_account_deleted_returns_unavailable(self):
        """账号逻辑删除时 available=False"""
        self.signer.deleted_by = self.supper
        self.signer.save()
        result = services.get_my_current_signature(self.signer)
        self.assertFalse(result['available'])

    def test_no_config_returns_unavailable(self):
        """未配置时 available=False"""
        new_user = _make_user('no_sig_user', tenant_id='tenant_a')
        result = services.get_my_current_signature(new_user)
        self.assertFalse(result['available'])


class NoBusinessModuleModificationTests(TestCase):
    """验证本阶段没有修改任何业务模块"""

    def test_checksheet_not_touched(self):
        """部门日检查单没有任何改动"""
        # 检查 checksheet 模块没有 signature 相关字段
        try:
            from apps.checksheet import models as cs_models
            import inspect
            for name, cls in inspect.getmembers(cs_models, inspect.isclass):
                if hasattr(cls, '_meta') and issubclass(cls, __import__('django.db.models', fromlist=['Model']).Model):
                    for f in cls._meta.get_fields():
                        self.assertFalse(
                            'signature' in f.name.lower(),
                            f'checksheet 模型 {cls.__name__} 不应包含 signature 字段: {f.name}')
        except ImportError:
            self.skipTest('checksheet 模块不存在，跳过')

    def test_no_business_endpoint_registered(self):
        """没有为业务模块注册签署 HTTP 接口"""
        # apply_signature 是服务函数，不是 HTTP 视图
        from apps.signature import urls as sig_urls
        # 普通用户 URL 只有 mine 和 preview
        patterns = [str(p.pattern) for p in sig_urls.urlpatterns]
        self.assertTrue(any('mine' in p for p in patterns), patterns)
        self.assertTrue(any('preview' in p for p in patterns), patterns)
        # 不存在通用 apply 端点
        for p in patterns:
            self.assertNotIn('apply', p, '不应存在通用 apply HTTP 端点')
