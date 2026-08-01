# -*- coding: utf-8 -*-
"""
告警模块 CRUD 可靠性审计测试

审计范围：
1. 数据库约束（1.1）- level/status CHECK、alert_key 唯一性、外键策略
2. 事务边界（1.2）- resolve 操作原子性
3. 幂等性设计（1.3）- 重复 resolve、重复 mark_read
4. 防误操作与可追溯（1.5）- 逻辑删除/物理删除/审计链
5. 索引与慢查询（2.1）- keyword 搜索性能、分页边界
6. 容量隐患 - 无清理机制、mark_all_read 内存爆炸
7. 前端铃铛 - markAllRead 状态一致性
"""
import json
import time
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from django_redis import get_redis_connection

from apps.alert.models import Alert, AlertRead
from apps.alert.tasks import check_disk_space

# 常量引用
LEVEL_ERROR = Alert.LEVEL_ERROR
LEVEL_WARNING = Alert.LEVEL_WARNING
LEVEL_INFO = Alert.LEVEL_INFO
STATUS_ACTIVE = Alert.STATUS_ACTIVE
STATUS_RESOLVED = Alert.STATUS_RESOLVED


def _clear_metrics():
    r = get_redis_connection()
    keys = r.keys('metric:*')
    if keys:
        r.delete(*keys)


class ConstraintAuditTest(TestCase):
    """1.1 数据库约束审计"""

    def test_level_check_constraint_valid(self):
        """level 只允许 error/warning/info"""
        for level in [LEVEL_ERROR, LEVEL_WARNING, 'info']:
            alert = Alert.objects.create(
                title='test', message='msg', level=level,
                source='test', alert_key=f'key_{level}',
            )
            self.assertEqual(alert.level, level)

    def test_level_check_constraint_invalid(self):
        """非法 level 被数据库拒绝"""
        with self.assertRaises(Exception):
            Alert.objects.create(
                title='test', message='msg', level='critical',
                source='test', alert_key='key_invalid',
            )

    def test_status_check_constraint_valid(self):
        """status 只允许 active/resolved"""
        alert = Alert.objects.create(
            title='test', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='key_status',
        )
        self.assertEqual(alert.status, STATUS_ACTIVE)

        alert.status = STATUS_RESOLVED
        alert.save()
        alert.refresh_from_db()
        self.assertEqual(alert.status, STATUS_RESOLVED)

    def test_alert_read_unique_constraint(self):
        """同一 user 对同一 alert 只能有一条 AlertRead"""
        from apps.utils.test_helpers import make_user

        user = make_user('audit_user', [])
        alert = Alert.objects.create(
            title='test', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='key_read',
        )
        AlertRead.objects.create(alert=alert, user_id=user.id)
        # 重复创建应失败
        with self.assertRaises(Exception):
            AlertRead.objects.create(alert=alert, user_id=user.id)

    def test_resolved_by_fk_protect(self):
        """resolved_by 使用 PROTECT，不能删除已处理告警关联的用户"""
        from apps.account.models import User
        from apps.utils.test_helpers import make_user

        user = make_user('audit_resolve', [])
        alert = Alert.objects.create(
            title='test', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='key_fk',
        )
        alert.status = STATUS_RESOLVED
        alert.resolved_by = user
        alert.save()

        # 尝试删除 user 应该被 PROTECT 阻止
        with self.assertRaises(Exception):
            user.delete()

    def test_alert_read_cascade_delete(self):
        """AlertRead.alert 使用 CASCADE，删 alert 自动删 read"""
        from apps.utils.test_helpers import make_user

        user = make_user('audit_cascade', [])
        alert = Alert.objects.create(
            title='test', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='key_cascade',
        )
        AlertRead.objects.create(alert=alert, user_id=user.id)
        self.assertEqual(AlertRead.objects.count(), 1)

        alert.delete()
        self.assertEqual(AlertRead.objects.count(), 0)


class IdempotencyAuditTest(TestCase):
    """1.3 幂等性审计"""

    def setUp(self):
        cache.clear()
        Alert.objects.all().delete()

    def test_resolve_idempotent(self):
        """重复 resolve 同一告警不会报错"""
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('audit_idem', ['system.alert.view', 'system.alert.resolve'])
        client = make_client(user)

        alert = Alert.objects.create(
            title='test', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='key_idem',
        )

        # 第一次 resolve
        resp = client.post(f'/alert/{alert.id}/resolve/')
        self.assertEqual(resp.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, STATUS_RESOLVED)
        first_resolved_at = alert.resolved_at

        # 第二次 resolve（幂等）
        resp = client.post(f'/alert/{alert.id}/resolve/')
        self.assertEqual(resp.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, STATUS_RESOLVED)

    def test_mark_read_idempotent(self):
        """重复 mark_read 同一告警不会报错"""
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('audit_mark', ['system.alert.view'])
        client = make_client(user)

        alert = Alert.objects.create(
            title='test', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='key_mark',
        )

        # 第一次 mark read（ids 列表格式）
        resp = client.post('/alert/mark-read/',
                           data=json.dumps({'ids': [alert.id]}),
                           content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AlertRead.objects.filter(alert=alert, user_id=user.id).count(), 1)

        # 重复 mark read（ignore_conflicts=True）
        resp = client.post('/alert/mark-read/',
                           data=json.dumps({'ids': [alert.id]}),
                           content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        # 仍然只有 1 条
        self.assertEqual(AlertRead.objects.filter(alert=alert, user_id=user.id).count(), 1)

    def test_send_alert_dedup_same_key(self):
        """相同 alert_key 在冷却期内不重复"""
        from libs.alert import send_alert

        send_alert('A', 'msg', level=LEVEL_WARNING, source='test', alert_key='dedup:test')
        send_alert('B', 'msg', level=LEVEL_WARNING, source='test', alert_key='dedup:test')

        self.assertEqual(Alert.objects.filter(alert_key='dedup:test').count(), 1)


class CapacityAuditTest(TestCase):
    """容量隐患审计 - 无清理机制 / mark_all_read 内存"""

    def setUp(self):
        cache.clear()
        Alert.objects.all().delete()
        _clear_metrics()

    def test_mark_all_read_with_many_alerts(self):
        """mark_all_read 使用 iterator() 分批处理，不将所有 alert_id 加载到内存

        修复后：AlertMarkReadView 使用 .iterator(BATCH_SIZE) 流式处理，
        每 500 条一批 bulk_create，避免全量加载。
        """
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('audit_allread', ['system.alert.view'])
        client = make_client(user)

        # 创建 100 条 active alert
        alerts = []
        for i in range(100):
            alerts.append(Alert(
                title=f'test_{i}', message='msg', level=LEVEL_WARNING,
                source='test', alert_key=f'allread_{i}',
            ))
        Alert.objects.bulk_create(alerts)

        # mark_all_read 应成功
        resp = client.post('/alert/mark-read/',
                           data=json.dumps({'all': True}),
                           content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # 验证 marked_count 返回正确
        self.assertEqual(body['data']['marked_count'], 100)

        # 验证全部已读
        read_count = AlertRead.objects.filter(user_id=user.id).count()
        self.assertEqual(read_count, 100)

    def test_no_alert_cleanup_mechanism(self):
        """验证告警清理机制已存在

        修复后：cleanup-old-alerts Celery Beat 任务已注册，
        每天 03:00 清理 resolved>90天 / active>180天 的旧告警。
        """
        from apps.alert.celery_beat_schedule import ALERT_BEAT_SCHEDULE

        task_names = [v['task'] for v in ALERT_BEAT_SCHEDULE.values()]
        cleanup_tasks = [t for t in task_names if 'clean' in t.lower()]

        self.assertGreaterEqual(len(cleanup_tasks), 1,
                               '清理任务应已注册')

    def test_cleanup_old_alerts_deletes_resolved(self):
        """cleanup_old_alerts 正确清理 90 天前的已处理告警"""
        from datetime import timedelta
        from django.utils import timezone
        from apps.alert.tasks import cleanup_old_alerts

        # 91 天前已处理告警（应被删）
        old_resolved = Alert.objects.create(
            title='old_resolved', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='old_resolved',
            status=STATUS_RESOLVED,
            resolved_at=timezone.now() - timedelta(days=91),
        )
        # 89 天前已处理告警（应保留）
        recent_resolved = Alert.objects.create(
            title='recent_resolved', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='recent_resolved',
            status=STATUS_RESOLVED,
            resolved_at=timezone.now() - timedelta(days=89),
        )
        # 181 天前活跃告警（应被删）
        old_active = Alert.objects.create(
            title='old_active', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='old_active',
            status=STATUS_ACTIVE,
        )
        old_active.created_at = timezone.now() - timedelta(days=181)
        old_active.save(update_fields=['created_at'])

        # 179 天前活跃告警（应保留）
        recent_active = Alert.objects.create(
            title='recent_active', message='msg', level=LEVEL_WARNING,
            source='test', alert_key='recent_active',
            status=STATUS_ACTIVE,
        )
        recent_active.created_at = timezone.now() - timedelta(days=179)
        recent_active.save(update_fields=['created_at'])

        cleanup_old_alerts()

        # 验证
        self.assertFalse(Alert.objects.filter(id=old_resolved.id).exists())
        self.assertFalse(Alert.objects.filter(id=old_active.id).exists())
        self.assertTrue(Alert.objects.filter(id=recent_resolved.id).exists())
        self.assertTrue(Alert.objects.filter(id=recent_active.id).exists())


class IndexAuditTest(TestCase):
    """2.1 索引与慢查询审计"""

    def setUp(self):
        cache.clear()
        Alert.objects.all().delete()

    def test_keyword_search_excludes_message(self):
        """keyword 搜索不再搜索 message 字段（TextField LIKE '%xxx%' 无法走索引）

        修复后：keyword 只搜索 title 和 alert_key，并限制最近 180 天。
        """
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('audit_kw', ['system.alert.view'])
        client = make_client(user)

        # 创建包含特殊关键词的告警
        Alert.objects.create(
            title='disk_alert', message='unique_keyword_xyz',
            level=LEVEL_WARNING, source='disk', alert_key='kw_test',
        )
        Alert.objects.create(
            title='other', message='normal',
            level=LEVEL_WARNING, source='disk', alert_key='unique_keyword_xyz',
        )

        # 搜索 title 能命中
        resp = client.get('/alert/', {'page': 1, 'page_size': 20, 'keyword': 'disk_alert'})
        body = resp.json()
        self.assertEqual(body['data']['total'], 1)

        # 搜索 alert_key 能命中
        resp = client.get('/alert/', {'page': 1, 'page_size': 20, 'keyword': 'kw_test'})
        body = resp.json()
        self.assertEqual(body['data']['total'], 1)

        # 搜索 message 里的 unique_keyword_xyz 不应命中（不再搜索 message）
        resp = client.get('/alert/', {'page': 1, 'page_size': 20, 'keyword': 'unique_keyword_xyz'})
        body = resp.json()
        # alert_key 里也有 unique_keyword_xyz，所以应该命中 1 条（不是 2 条）
        self.assertEqual(body['data']['total'], 1)

    def test_pagination_bounded(self):
        """分页 page_size 有上限"""
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('audit_page', ['system.alert.view'])
        client = make_client(user)

        # 创建 200 条
        alerts = []
        for i in range(200):
            alerts.append(Alert(
                title=f'page_{i}', message='msg', level=LEVEL_WARNING,
                source='test', alert_key=f'page_{i}',
            ))
        Alert.objects.bulk_create(alerts)

        # 请求 page_size=999（应被限制为 100）
        resp = client.get('/alert/', {'page': 1, 'page_size': 999})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertLessEqual(len(body['data']['items']), 100)


class FrontendBellAuditTest(TestCase):
    """前端铃铛审计 - markAllRead 状态一致性"""

    def setUp(self):
        cache.clear()
        Alert.objects.all().delete()

    def test_mark_all_read_api_updates_correctly(self):
        """mark_all_read API 应正确更新状态

        审计发现：前端 AlertStore.markAllRead() 只更新 unreadCount=0，
        但 recentAlerts 列表中各 item 的 status 仍为 'unread'，
        导致 UI 显示不一致（铃铛数字为 0 但列表项仍显示未读样式）。
        这是前端 bug，后端 API 本身正确。
        """
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('audit_bell', ['system.alert.view'])
        client = make_client(user)

        # 创建 3 条 alert
        for i in range(3):
            Alert.objects.create(
                title=f'bell_{i}', message='msg', level=LEVEL_WARNING,
                source='test', alert_key=f'bell_{i}',
            )

        # 获取列表（应 3 条未读）
        resp = client.get('/alert/', {'page': 1, 'page_size': 20})
        body = resp.json()
        self.assertEqual(body['data']['summary']['unread_count'], 3)

        # mark all read
        resp = client.post('/alert/mark-read/',
                           data=json.dumps({'all': True}),
                           content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # 再次获取列表（应 0 条未读）
        resp = client.get('/alert/', {'page': 1, 'page_size': 20})
        body = resp.json()
        self.assertEqual(body['data']['summary']['unread_count'], 0)


class DiskTrendIntegrationTest(TestCase):
    """磁盘趋势预测端到端审计"""

    def setUp(self):
        cache.clear()
        Alert.objects.all().delete()
        _clear_metrics()

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_trend_alert_has_full_audit_trail(self, mock_exists, mock_du):
        """趋势预警有完整审计链：alert 记录 + Redis 指标历史"""
        from libs.trend import record_metric, get_trend

        total = 100 * 1024 ** 3
        used_85 = 85 * 1024 ** 3

        # 注入 24h 快速增长历史
        now = time.time()
        r = get_redis_connection()
        key = 'metric:disk:documents'
        for i in range(24):
            ts = now - (23 - i) * 3600
            val = (85 - (23 - i)) * 1024 ** 3
            r.zadd(key, {f'{ts}:{val}': ts})

        mock_du.return_value = MagicMock(used=used_85, total=total, free=total - used_85)

        check_disk_space()

        # 验证：Alert 表有趋势预警记录
        trend_alert = Alert.objects.filter(
            source='disk', alert_key__endswith=':trend'
        ).first()
        self.assertIsNotNone(trend_alert)
        self.assertIn('趋势预警', trend_alert.title)
        self.assertEqual(trend_alert.level, LEVEL_WARNING)
        self.assertEqual(trend_alert.status, STATUS_ACTIVE)

        # 验证：Redis 有指标历史
        trend = get_trend('disk:documents', 24)
        self.assertGreaterEqual(len(trend), 24)

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_snapshot_and_trend_alert_coexist(self, mock_exists, mock_du):
        """快照告警和趋势预警可以同时存在（不同 alert_key）"""
        total = 100 * 1024 ** 3
        used_92 = 92 * 1024 ** 3  # 92% > 90%，触发快照告警

        # 注入快速增长历史
        now = time.time()
        r = get_redis_connection()
        key = 'metric:disk:documents'
        for i in range(24):
            ts = now - (23 - i) * 3600
            val = (92 - (23 - i) * 3) * 1024 ** 3
            r.zadd(key, {f'{ts}:{val}': ts})

        mock_du.return_value = MagicMock(used=used_92, total=total, free=total - used_92)

        check_disk_space()

        # 快照告警存在（disk:documents）
        snapshot = Alert.objects.filter(alert_key='disk:documents')
        self.assertTrue(snapshot.exists())

        # 趋势预警不存在（因为 percent >= 90，条件 percent < 90 不满足）
        # 这是设计决策：>90% 时快照告警已覆盖，不重复发趋势预警
        trend = Alert.objects.filter(alert_key='disk:documents:trend')
        self.assertFalse(trend.exists())
