# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""部门值班日志 - 风险点验证测试

审查发现以下风险点，逐一验证真伪：
─────────────────────────────────────────────────────────────────
P0 Risk 1: _parse_list_date_range MAX_QUERY_DAYS 单日期绕过（已修复：移除限制）
P0 Risk 2: _parse_export_filters 无日期范围限制（确认：保留，数据量小无需限制）
P0 Risk 3: _get_export_queryset 未使用 get_visible_department_duty_logs（维护风险）
P1 Risk 4: update_draft 无 select_for_update -> 并发碰撞（低风险，乐观锁足够）
P1 Risk 5: return_signed_record void 事件失败 -> 全事务回滚（正确设计）
─────────────────────────────────────────────────────────────────
"""
import json
import time
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase, Client, override_settings

from apps.account.models import User
from apps.setting.utils import AppSetting
from apps.department_duty_log.models import DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED
from apps.department_duty_log import services


# ============================================================
# 测试辅助
# ============================================================

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


def _make_record(user, **kwargs):
    defaults = {
        'duty_date': date.today(),
        'duty_person': user,
        'duty_person_name': user.nickname or user.username,
        'weather': '晴',
        'duty_record': '值班正常',
        'remark': '',
        'status': STATUS_DRAFT,
        'version': 1,
        'created_by': user,
    }
    defaults.update(kwargs)
    if defaults['status'] in (STATUS_SIGNED):
        signed_defaults = {
            'signature_usage_id': uuid.uuid4().int & ((1 << 63) - 1),
            'signed_by': user,
            'signed_by_name': user.nickname or user.username,
            'signed_at': '2026-01-01 00:00:00',
            'signature_version': 1,
            'signature_sha256': 'a' * 64,
            'business_snapshot_hash': 'b' * 64,
        }
        for field, value in signed_defaults.items():
            defaults.setdefault(field, value)
    return DepartmentDutyLog.objects.create(**defaults)


# ============================================================
# 测试基类
# ============================================================

@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class RiskTestBase(TestCase):
    """所有风险测试的基类，使用本地内存缓存避免 Redis 依赖。"""
    pass


# ============================================================
# P0 Risk 1: MAX_QUERY_DAYS 限制已移除（原限制过度设计）
# ============================================================

class MaxQueryDaysRemovedTests(RiskTestBase):
    """P0 Risk 1: MAX_QUERY_DAYS 限制已移除，验证无日期范围限制"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('user', is_supper=True)
        self.client = _make_client(self.user)

    def _parse(self, response):
        return json.loads(response.content)

    def test_p0_risk1_no_date_limit_single_start(self):
        """验证：只提供 start_date 时查询正常（无限制）"""
        resp = self.client.get('/department-duty-log/records/', {
            'start_date': '2020-01-01',
        })
        body = self._parse(resp)
        self.assertFalse(body.get('error'), '不应返回错误')
        print('[P0 Risk 1] 已修复：单日期查询正常，无 MAX_QUERY_DAYS 限制')

    def test_p0_risk1_no_date_limit_dual_wide_range(self):
        """验证：超宽日期范围查询正常（无限制）"""
        resp = self.client.get('/department-duty-log/records/', {
            'start_date': '2020-01-01',
            'end_date': '2026-08-01',
        })
        body = self._parse(resp)
        self.assertFalse(body.get('error'), '不应返回日期范围错误')
        print('[P0 Risk 1] 已修复：超宽日期范围（6 年）查询正常，无限制')

    def test_p0_risk1_no_date_limit_single_end(self):
        """验证：只提供 end_date 时查询正常（无限制）"""
        resp = self.client.get('/department-duty-log/records/', {
            'end_date': '2026-08-01',
        })
        body = self._parse(resp)
        self.assertFalse(body.get('error'), '不应返回错误')
        print('[P0 Risk 1] 已修复：单 end_date 查询正常')

    def test_p0_risk1_end_before_start_still_rejected(self):
        """验证：end_date 早于 start_date 仍被拒绝"""
        resp = self.client.get('/department-duty-log/records/', {
            'start_date': '2026-08-01',
            'end_date': '2020-01-01',
        })
        body = self._parse(resp)
        self.assertTrue(body.get('error'), '应返回错误')
        self.assertIn('早于', body.get('error', ''))
        print('[P0 Risk 1] 保留校验：end_date < start_date 仍被拒绝')


# ============================================================
# P0 Risk 2: 导出无日期范围限制（确认：保留，数据量小无需限制）
# ============================================================

class ExportNoDateLimitTests(RiskTestBase):
    """P0 Risk 2: _parse_export_filters 无日期范围限制（保留）"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('user', is_supper=True)
        self.client = _make_client(self.user)

    def test_p0_risk2_export_parse_filters_no_date_limit(self):
        """验证：_parse_export_filters 无日期范围限制"""
        filters, error = services._parse_export_filters({
            'start_date': '2020-01-01',
            'end_date': '2026-08-01',
        })
        self.assertIsNone(error, msg='应无错误')
        self.assertIsNotNone(filters, 'filters 不应为 None')
        self.assertIn('start_date', filters)
        self.assertIn('end_date', filters)
        print('[P0 Risk 2] 确认：导出无日期范围限制，保留 PDF_EXPORT_LIMIT=500 上限即可')


# ============================================================
# P0 Risk 3: _get_export_queryset 未使用 get_visible_department_duty_logs
# ============================================================

class ExportQuerySetVisibilityTests(RiskTestBase):
    """P0 Risk 3: _get_export_queryset 未使用 get_visible_department_duty_logs"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('user', is_supper=False)
        self.supper = _make_user('supper', is_supper=True)
        self.other = _make_user('other', is_supper=False)

        self.signed_self = _make_record(
            self.user, duty_date=date.today(), status=STATUS_SIGNED, version=2,
        )
        self.signed_other = _make_record(
            self.other, duty_date=date.today(), status=STATUS_SIGNED, version=2,
        )
        self.draft_self = _make_record(
            self.user, duty_date=date.today(), status=STATUS_DRAFT,
        )
        self.draft_other = _make_record(
            self.other, duty_date=date.today(), status=STATUS_DRAFT,
        )

    def test_p0_risk3_export_not_using_get_visible(self):
        """验证：导出路径不使用 get_visible_department_duty_logs"""
        visible_qs = services.get_visible_department_duty_logs(self.user)
        visible_ids = set(visible_qs.values_list('id', flat=True))

        export_qs = services._get_export_queryset(self.user, {})
        export_ids = set(export_qs.values_list('id', flat=True))

        self.assertIn(self.signed_self.id, visible_ids, '可见查询应包含本人已签')
        self.assertIn(self.signed_other.id, visible_ids, '可见查询应包含他人已签')
        self.assertIn(self.draft_self.id, visible_ids, '可见查询应包含本人草稿')
        self.assertNotIn(self.draft_other.id, visible_ids, '可见查询不应包含他人草稿')

        self.assertIn(self.signed_self.id, export_ids, '导出查询应包含本人已签')
        self.assertIn(self.signed_other.id, export_ids, '导出查询应包含他人已签')
        self.assertNotIn(self.draft_self.id, export_ids, '导出查询不应包含本人草稿')
        self.assertNotIn(self.draft_other.id, export_ids, '导出查询不应包含他人草稿')

        print('[P0 Risk 3] 确认：_get_export_queryset 未使用 get_visible_department_duty_logs')
        print(f'  visible_ids: {sorted(visible_ids)}')
        print(f'  export_ids: {sorted(export_ids)}')
        print('  当前结果一致（export 只取已签子集），维护风险')

    def test_p0_risk3_supper_export_ok(self):
        """验证：超级用户导出不受影响"""
        export_qs = services._get_export_queryset(self.supper, {})
        export_ids = set(export_qs.values_list('id', flat=True))
        self.assertIn(self.signed_self.id, export_ids)
        self.assertIn(self.signed_other.id, export_ids)
        self.assertNotIn(self.draft_self.id, export_ids)
        self.assertNotIn(self.draft_other.id, export_ids)
        print('[P0 Risk 3] 超级用户导出查询正常')


# ============================================================
# P1 Risk 4: update_draft 无 select_for_update -> 并发碰撞
# ============================================================

class UpdateDraftConcurrentTests(RiskTestBase):
    """P1 Risk 4: update_draft 使用乐观锁但无 select_for_update"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('user', is_supper=True)
        self.client = _make_client(self.user)

    def _parse(self, response):
        return json.loads(response.content)

    def test_p1_risk4_update_draft_concurrent_same_version(self):
        """验证：相同版本号更新，后一个失败"""
        record = _make_record(self.user, version=1)

        resp1 = self.client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(record.duty_date),
                'duty_record': '第一次更新',
                'weather': '晴',
                'version': 1,
            }),
            content_type='application/json',
        )
        body1 = self._parse(resp1)
        self.assertFalse(body1.get('error'), f'请求 1 应成功: {body1.get("error")}')

        resp2 = self.client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(record.duty_date),
                'duty_record': '第二次更新（使用旧版本号）',
                'weather': '大雨',
                'version': 1,
            }),
            content_type='application/json',
        )
        body2 = self._parse(resp2)
        self.assertTrue(body2.get('error'), '请求 2 应因版本冲突而失败')
        print(f'[P1 Risk 4] 确认：版本冲突导致更新失败，错误={body2.get("error")}')

    def test_p1_risk4_sequential_updates_ok(self):
        """验证：顺序更新（使用正确版本号）正常"""
        record = _make_record(self.user, version=1)

        resp1 = self.client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(record.duty_date),
                'duty_record': '第一次',
                'weather': '晴',
                'version': 1,
            }),
            content_type='application/json',
        )
        body1 = self._parse(resp1)
        self.assertFalse(body1.get('error'))
        record.refresh_from_db()
        v1 = record.version

        resp2 = self.client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(record.duty_date),
                'duty_record': '第二次',
                'weather': '多云',
                'version': v1,
            }),
            content_type='application/json',
        )
        body2 = self._parse(resp2)
        self.assertFalse(body2.get('error'), f'顺序更新应成功: {body2.get("error")}')
        record.refresh_from_db()
        self.assertEqual(record.version, v1 + 1)
        print(f'[P1 Risk 4] 顺序更新正常，版本: {v1} -> {v1 + 1}')


# ============================================================
# P1 Risk 5: return_signed_record void 事件失败 -> 全事务回滚
# ============================================================

class ReturnVoidEventRollbackTests(RiskTestBase):
    """P1 Risk 5: return_signed_record void 事件失败 -> 全事务回滚（正确设计）"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('user', is_supper=True)
        self.client = _make_client(self.user)

    @patch('apps.department_duty_log.services.signature_services.record_signature_void_event')
    def test_p1_risk5_void_event_failure_rollback(self, mock_void):
        """验证：void 事件失败时事务回滚，记录状态不变"""
        record = _make_record(self.user, status=STATUS_SIGNED, version=2,
                              signature_usage_id=12345)
        original_status = record.status
        original_version = record.version

        mock_void.return_value = '签名作废事件记录失败：网络错误'

        result, error = services.return_signed_record(record.id, self.user)

        self.assertIsNone(result, '退回应失败')
        self.assertIsNotNone(error, '应返回错误信息')
        self.assertIn('网络错误', error, f'错误信息应包含原因: {error}')

        record.refresh_from_db()
        self.assertEqual(record.status, original_status, '事务回滚后状态应不变')
        self.assertEqual(record.version, original_version, '事务回滚后版本应不变')

        print(f'[P1 Risk 5] 确认：void 事件失败触发事务回滚（失败安全设计）')
        print(f'  错误: {error}')
        print(f'  记录状态: {record.status}（未变，证明回滚了）')

    @patch('apps.department_duty_log.services.signature_services.record_signature_void_event')
    def test_p1_risk5_void_success_commits(self, mock_void):
        """验证：void 事件成功时事务正常提交"""
        record = _make_record(self.user, status=STATUS_SIGNED, version=2,
                              signature_usage_id=12345)

        mock_void.return_value = None

        result, error = services.return_signed_record(record.id, self.user)

        self.assertIsNone(error, f'退回应成功: {error}')
        self.assertIsNotNone(result)

        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_DRAFT, '退回后应为草稿状态')
        self.assertEqual(record.version, 3, '版本应递增')
        print(f'[P1 Risk 5] 对照验证：void 事件成功时事务正常提交')
        print(f'  记录状态: {record.status}, 版本: {record.version}')


# ============================================================
# 额外观察：sign_draft 使用 select_for_update 但 update_draft 不使用
# ============================================================

class ConcurrencyStrategyInconsistencyTests(RiskTestBase):
    """代码一致性观察：sign_draft 使用 select_for_update vs update_draft 不使用"""

    def test_observation_concurrency_strategy(self):
        """观察：sign_draft 和 update_draft 使用不同的并发控制策略"""
        import inspect
        from apps.department_duty_log import services as svc

        sign_source = inspect.getsource(svc.sign_draft)
        update_source = inspect.getsource(svc.update_draft)

        has_select_for_update_sign = 'select_for_update' in sign_source
        has_select_for_update_update = 'select_for_update' in update_source

        print(f'[观察] sign_draft 使用 select_for_update: {has_select_for_update_sign}')
        print(f'[观察] update_draft 使用 select_for_update: {has_select_for_update_update}')
        print('  sign_draft 使用 select_for_update + version 乐观锁（双重保险）')
        print('  update_draft 仅使用 version 乐观锁（无行锁保护）')
        print('  两者操作同一数据表但使用不同并发策略，属于代码不一致')
        print('  风险等级：低（乐观锁对 update_draft 场景足够）')

        self.assertTrue(has_select_for_update_sign)
        self.assertFalse(has_select_for_update_update)
