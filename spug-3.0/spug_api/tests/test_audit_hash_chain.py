# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
证据闭环第一阶段：全局操作审计哈希链测试

覆盖：
- hash_chain 工具函数：request_hash/response_hash/log_hash 计算、确定性、校验
- save_audit_log：写入 log_hash、request_hash 自动计算、按租户哈希链
- 篡改检测：单条字段篡改、链断裂
- 导出审计日志动作被记录
- 兼容性：旧调用方式（不传新参数）仍可工作；现有查询筛选不受影响
- 租户隔离：不同租户独立哈希链
"""
import json
from django.test import TestCase

from apps.logs.models import AuditLog
from apps.logs.audit import save_audit_log
from apps.logs.hash_chain import (
    compute_request_hash, compute_response_hash,
    compute_log_hash, build_log_hash_payload, build_log_hash_payload_from_values,
    compute_log_hash_from_values, verify_log_hash, verify_hash_chain,
)


def _make_log(**kwargs):
    """构造一条带默认值的 AuditLog 实例（不落库），用于纯函数测试

    未显式传入 log_hash 时自动按字段计算并回填（模拟 save_audit_log）；
    显式传入（含空串）时保留传入值，便于测试旧数据/篡改场景。
    """
    has_explicit_hash = 'log_hash' in kwargs
    defaults = dict(
        id=1, user_id=1, username='alice', action='create',
        target_type='device', target_id='5', target_name='发射机A',
        detail='{"name":"x"}', ip='10.0.0.1', is_success=True,
        tenant_id='t1', created_at='2026-06-27 10:00:00',
        request_hash='', response_hash='', prev_hash='',
        request_id='', user_agent='Mozilla/5.0',
    )
    defaults.update(kwargs)
    log = AuditLog(**defaults)
    if not has_explicit_hash:
        # 未显式指定 log_hash：按当前字段计算，模拟 save_audit_log 行为
        log.log_hash = compute_log_hash(build_log_hash_payload(log))
    return log


class HashChainUtilsTests(TestCase):
    """hash_chain 工具函数测试"""

    def test_compute_request_hash_deterministic(self):
        """相同 detail 多次计算结果一致"""
        h1 = compute_request_hash('{"a":1}')
        h2 = compute_request_hash('{"a":1}')
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_compute_request_hash_dict_sort_keys(self):
        """dict 输入按 sort_keys 序列化，键顺序不影响结果"""
        h1 = compute_request_hash({'a': 1, 'b': 2})
        h2 = compute_request_hash({'b': 2, 'a': 1})
        self.assertEqual(h1, h2)

    def test_compute_request_hash_none_empty(self):
        """None 与空串哈希相同（规范化为 ''）"""
        self.assertEqual(compute_request_hash(None), compute_request_hash(''))
        self.assertEqual(len(compute_request_hash(None)), 64)

    def test_compute_request_hash_differs_on_content(self):
        """不同内容产生不同哈希"""
        self.assertNotEqual(
            compute_request_hash('abc'), compute_request_hash('abd')
        )

    def test_compute_response_hash_bytes_str(self):
        """bytes 与同内容 str 结果一致"""
        self.assertEqual(
            compute_response_hash(b'hello'),
            compute_response_hash('hello'),
        )
        self.assertEqual(len(compute_response_hash(b'hello')), 64)

    def test_compute_response_hash_empty(self):
        """空内容返回空串（留空标识）"""
        self.assertEqual(compute_response_hash(None), '')
        self.assertEqual(compute_response_hash(b''), '')
        self.assertEqual(compute_response_hash(''), '')

    def test_compute_log_hash_deterministic_and_sorted(self):
        """log_hash 确定性 + sort_keys 保证字段顺序无关"""
        payload = build_log_hash_payload_from_values(
            tenant_id='t1', user_id=1, username='a', action='create',
            target_type='device', target_id='1', target_name='n',
            detail='d', ip='1.1.1.1', is_success=True,
            created_at='2026-06-27 10:00:00',
            request_hash='rh', response_hash='', request_id='rid',
            user_agent='ua', prev_hash='ph',
        )
        h1 = compute_log_hash(payload)
        # 打乱键顺序构造同样值的 dict（json sort_keys 后一致）
        payload2 = {k: payload[k] for k in reversed(list(payload.keys()))}
        h2 = compute_log_hash(payload2)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_compute_log_hash_changes_on_field_change(self):
        """任一字段变化，log_hash 必须变化"""
        base = dict(
            tenant_id='t1', user_id=1, username='a', action='create',
            target_type='device', target_id='1', target_name='n',
            detail='d', ip='1.1.1.1', is_success=True,
            created_at='2026-06-27 10:00:00',
            request_hash='rh', response_hash='', request_id='rid',
            user_agent='ua', prev_hash='ph',
        )
        h0 = compute_log_hash_from_values(**base)
        # 修改每个关键字段，hash 都应不同
        for field, new_val in [
            ('username', 'b'), ('action', 'update'), ('detail', 'dd'),
            ('ip', '2.2.2.2'), ('is_success', False),
            ('created_at', '2026-06-27 10:00:01'),
            ('request_hash', 'rh2'), ('prev_hash', 'ph2'),
            ('tenant_id', 't2'), ('user_agent', 'ua2'),
        ]:
            changed = dict(base)
            changed[field] = new_val
            self.assertNotEqual(
                compute_log_hash_from_values(**changed), h0,
                f'修改字段 {field} 后 log_hash 未变化',
            )

    def test_verify_log_hash_ok(self):
        """未篡改的日志 verify 返回 True"""
        log = _make_log()
        self.assertTrue(verify_log_hash(log))

    def test_verify_log_hash_detects_tamper(self):
        """篡改任一字段后 verify 返回 False"""
        log = _make_log()
        for field, new_val in [
            ('detail', 'tampered'), ('username', 'eve'),
            ('ip', '9.9.9.9'), ('is_success', False),
            ('prev_hash', 'fake'), ('target_id', '999'),
        ]:
            tampered = _make_log(**{field: new_val})
            # 篡改字段但不重算 log_hash
            tampered.log_hash = log.log_hash
            self.assertFalse(
                verify_log_hash(tampered),
                f'篡改字段 {field} 后未被检测到',
            )

    def test_verify_log_hash_empty_returns_false(self):
        """旧数据无 log_hash 返回 False（不可校验，不阻断业务）"""
        log = _make_log(log_hash='')
        self.assertFalse(verify_log_hash(log))

    def test_verify_hash_chain_continuous(self):
        """连续的哈希链校验通过"""
        logs = []
        prev = ''
        for i in range(5):
            log = _make_log(
                id=i + 1, prev_hash=prev,
                detail=f'event-{i}', created_at=f'2026-06-27 10:00:0{i}',
            )
            log.log_hash = compute_log_hash(build_log_hash_payload(log))
            logs.append(log)
            prev = log.log_hash
        result = verify_hash_chain(logs)
        self.assertTrue(result['valid'])
        self.assertEqual(result['checked'], 5)
        self.assertIsNone(result['broken_at'])
        self.assertEqual(result['errors'], [])

    def test_verify_hash_chain_detects_broken_link(self):
        """中间 prev_hash 不匹配被检测为断链"""
        logs = []
        prev = ''
        for i in range(3):
            log = _make_log(
                id=i + 1, prev_hash=prev, detail=f'e-{i}',
                created_at=f'2026-06-27 10:00:0{i}',
            )
            log.log_hash = compute_log_hash(build_log_hash_payload(log))
            logs.append(log)
            prev = log.log_hash
        # 篡改第二条的 prev_hash（与第一条 log_hash 不匹配）
        logs[1].prev_hash = 'wrong'
        result = verify_hash_chain(logs)
        self.assertFalse(result['valid'])
        self.assertEqual(result['broken_at'], 2)
        self.assertTrue(any('id=2' in e for e in result['errors']))

    def test_verify_hash_chain_detects_tamper(self):
        """中间字段被篡改（log_hash 不匹配）被检测"""
        logs = []
        prev = ''
        for i in range(3):
            log = _make_log(
                id=i + 1, prev_hash=prev, detail=f'e-{i}',
                created_at=f'2026-06-27 10:00:0{i}',
            )
            log.log_hash = compute_log_hash(build_log_hash_payload(log))
            logs.append(log)
            prev = log.log_hash
        # 篡改第二条 detail 但不改 log_hash
        logs[1].detail = 'tampered'
        result = verify_hash_chain(logs)
        self.assertFalse(result['valid'])
        self.assertEqual(result['broken_at'], 2)

    def test_verify_hash_chain_skips_legacy_empty_hash(self):
        """旧数据（无 log_hash）不阻断链校验"""
        legacy = _make_log(id=1, log_hash='', prev_hash='')
        # 旧数据 log_hash 为空，不参与链连续性校验
        result = verify_hash_chain([legacy])
        self.assertTrue(result['valid'])
        self.assertEqual(result['checked'], 1)


class SaveAuditLogHashTests(TestCase):
    """save_audit_log 哈希链写入测试"""

    def test_save_writes_log_hash_and_request_hash(self):
        """写入后 log_hash 与 request_hash 非空且可校验"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='device', target_id='5', target_name='发射机',
            detail={'name': 'x'}, ip='10.0.0.1', is_success=True,
            tenant_id='t1',
        )
        log = AuditLog.objects.get()
        self.assertTrue(log.log_hash)
        self.assertEqual(len(log.log_hash), 64)
        self.assertTrue(log.request_hash)
        self.assertEqual(log.prev_hash, '')  # 链首
        self.assertTrue(verify_log_hash(log))

    def test_request_hash_matches_detail(self):
        """request_hash 等于对存库 detail 重算的结果"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='device', detail={'k': 'v'},
            ip='1.1.1.1', tenant_id='t1',
        )
        log = AuditLog.objects.get()
        # detail 存库为 json 字符串
        self.assertEqual(log.request_hash, compute_request_hash(log.detail))

    def test_hash_chain_links_consecutive_logs(self):
        """连续写入：第二条 prev_hash == 第一条 log_hash"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='device', target_id='1', detail='first',
            ip='1.1.1.1', tenant_id='t1',
        )
        save_audit_log(
            user_id=2, username='bob', action='update',
            target_type='device', target_id='1', detail='second',
            ip='2.2.2.2', tenant_id='t1',
        )
        logs = list(AuditLog.objects.order_by('id'))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].prev_hash, '')  # 链首
        self.assertEqual(logs[1].prev_hash, logs[0].log_hash)
        # 整链校验通过
        result = verify_hash_chain(logs)
        self.assertTrue(result['valid'])

    def test_hash_chain_tenant_isolation(self):
        """不同租户独立哈希链：互不引用对方 log_hash"""
        save_audit_log(
            user_id=1, username='a', action='create',
            target_type='device', detail='t1-1',
            ip='1.1.1.1', tenant_id='t1',
        )
        save_audit_log(
            user_id=2, username='b', action='create',
            target_type='device', detail='t2-1',
            ip='2.2.2.2', tenant_id='t2',
        )
        save_audit_log(
            user_id=1, username='a', action='update',
            target_type='device', detail='t1-2',
            ip='1.1.1.1', tenant_id='t1',
        )
        t1_logs = list(AuditLog.objects.filter(tenant_id='t1').order_by('id'))
        t2_logs = list(AuditLog.objects.filter(tenant_id='t2').order_by('id'))
        # t1 链：第二条 prev_hash 引用 t1 第一条，不引用 t2
        self.assertEqual(t1_logs[0].prev_hash, '')
        self.assertEqual(t1_logs[1].prev_hash, t1_logs[0].log_hash)
        self.assertNotEqual(t1_logs[1].prev_hash, t2_logs[0].log_hash)
        # t2 链首
        self.assertEqual(t2_logs[0].prev_hash, '')
        # 各自链校验通过
        self.assertTrue(verify_hash_chain(t1_logs)['valid'])
        self.assertTrue(verify_hash_chain(t2_logs)['valid'])

    def test_save_backward_compatible_without_new_params(self):
        """旧调用方式（不传新参数）仍可工作，hash 字段自动填充"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='device', ip='1.1.1.1', tenant_id='t1',
        )
        log = AuditLog.objects.get()
        self.assertTrue(log.log_hash)
        self.assertTrue(log.request_hash)  # 自动计算
        self.assertEqual(log.response_hash, '')  # 默认空
        self.assertEqual(log.prev_hash, '')  # 链首
        self.assertIsNone(log.request_id)  # 默认 None
        self.assertIsNone(log.user_agent)  # 默认 None
        self.assertTrue(verify_log_hash(log))

    def test_save_with_explicit_hash_params(self):
        """显式传入 response_hash/request_id/user_agent 被正确落库"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='device', ip='1.1.1.1', tenant_id='t1',
            response_hash='a' * 64,
            request_id='req-uuid-1234',
            user_agent='Mozilla/5.0 TestAgent',
        )
        log = AuditLog.objects.get()
        self.assertEqual(log.response_hash, 'a' * 64)
        self.assertEqual(log.request_id, 'req-uuid-1234')
        self.assertEqual(log.user_agent, 'Mozilla/5.0 TestAgent')
        self.assertTrue(verify_log_hash(log))

    def test_save_detail_dict_serialized(self):
        """dict 形态 detail 被序列化为 JSON 字符串存库"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='device', detail={'a': 1, 'b': 2},
            ip='1.1.1.1', tenant_id='t1',
        )
        log = AuditLog.objects.get()
        self.assertIsInstance(log.detail, str)
        parsed = json.loads(log.detail)
        self.assertEqual(parsed, {'a': 1, 'b': 2})

    def test_save_failure_does_not_raise(self):
        """save_audit_log 内部异常不抛出（不影响主请求）"""
        # 传入非法 tenant_id 触发潜在异常也不应抛出
        save_audit_log(
            user_id=None, username='alice', action='create',
            target_type='device', ip='1.1.1.1', tenant_id='t1',
        )
        # user_id=None 会导致 IntegrityError，但被 save_audit_log 捕获
        # 不应抛出异常，测试本身能到达此处即通过


class AuditTamperDetectionTests(TestCase):
    """篡改检测：模拟数据库被直接修改后的校验"""

    def test_db_tamper_detail_detected(self):
        """直接更新 detail 后 verify_log_hash 返回 False"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='device', detail='original',
            ip='1.1.1.1', tenant_id='t1',
        )
        log = AuditLog.objects.get()
        original_hash = log.log_hash
        # 模拟绕过应用层直接改库
        AuditLog.objects.filter(id=log.id).update(detail='tampered')
        log.refresh_from_db()
        self.assertEqual(log.detail, 'tampered')
        self.assertEqual(log.log_hash, original_hash)  # hash 未变
        self.assertFalse(verify_log_hash(log))

    def test_db_tamper_breaks_chain(self):
        """篡改中间一条日志后，链校验在篡改处断裂"""
        for i in range(3):
            save_audit_log(
                user_id=1, username='alice', action='create',
                target_type='device', detail=f'e-{i}',
                ip='1.1.1.1', tenant_id='t1',
            )
        logs = list(AuditLog.objects.filter(tenant_id='t1').order_by('id'))
        # 篡改第二条 detail（不改 log_hash）
        AuditLog.objects.filter(id=logs[1].id).update(detail='hacked')
        logs = list(AuditLog.objects.filter(tenant_id='t1').order_by('id'))
        result = verify_hash_chain(logs)
        self.assertFalse(result['valid'])
        self.assertEqual(result['broken_at'], logs[1].id)


class AuditExportRecordingTests(TestCase):
    """导出审计日志动作被记录测试"""

    def test_export_action_recorded_by_save_audit_log(self):
        """通过 save_audit_log 记录导出动作，action=export, target_type=audit"""
        save_audit_log(
            user_id=1, username='alice', action='export',
            target_type='audit', target_name='操作审计日志',
            detail={'操作': '导出审计日志', '导出数量': 10},
            ip='1.1.1.1', is_success=True, tenant_id='t1',
        )
        log = AuditLog.objects.get()
        self.assertEqual(log.action, 'export')
        self.assertEqual(log.target_type, 'audit')
        self.assertTrue(log.log_hash)  # 导出动作也进入哈希链
        self.assertTrue(verify_log_hash(log))

    def test_export_log_joins_hash_chain(self):
        """导出记录与普通操作记录共同构成同租户哈希链"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='device', detail='create-event',
            ip='1.1.1.1', tenant_id='t1',
        )
        save_audit_log(
            user_id=1, username='alice', action='export',
            target_type='audit', target_name='操作审计日志',
            detail={'导出数量': 5}, ip='1.1.1.1', tenant_id='t1',
        )
        logs = list(AuditLog.objects.filter(tenant_id='t1').order_by('id'))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[1].prev_hash, logs[0].log_hash)
        self.assertTrue(verify_hash_chain(logs)['valid'])


class AuditQueryCompatibilityTests(TestCase):
    """兼容性：现有查询/筛选/导出不受 hash 字段影响"""

    def setUp(self):
        for i in range(5):
            save_audit_log(
                user_id=i + 1, username=f'user{i}',
                action='create' if i % 2 == 0 else 'update',
                target_type='device', target_id=str(i + 1),
                target_name=f'设备{i}', detail=f'detail-{i}',
                ip='10.0.0.%d' % (i + 1), tenant_id='t1',
            )

    def test_to_dict_includes_hash_fields(self):
        """to_dict 包含新增 hash 字段，前端可获取"""
        log = AuditLog.objects.first()
        data = log.to_dict()
        for field in ('request_hash', 'response_hash', 'prev_hash',
                      'log_hash', 'request_id', 'user_agent'):
            self.assertIn(field, data)

    def test_filter_by_action_still_works(self):
        """按 action 筛选仍正常"""
        creates = AuditLog.objects.filter(action='create', tenant_id='t1')
        updates = AuditLog.objects.filter(action='update', tenant_id='t1')
        self.assertEqual(creates.count(), 3)
        self.assertEqual(updates.count(), 2)

    def test_filter_by_target_type_still_works(self):
        """按 target_type 筛选仍正常"""
        self.assertEqual(
            AuditLog.objects.filter(target_type='device', tenant_id='t1').count(), 5
        )

    def test_all_logs_have_valid_hash_chain(self):
        """写入的全部日志构成有效哈希链"""
        logs = list(AuditLog.objects.filter(tenant_id='t1').order_by('id'))
        result = verify_hash_chain(logs)
        self.assertTrue(result['valid'])
        self.assertEqual(result['checked'], 5)
