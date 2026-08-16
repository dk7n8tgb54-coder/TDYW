# -*- coding: utf-8 -*-
"""
Bug 2 回归测试：公告状态同步定时任务（已修复）

原缺陷：
  tasks.py 的查询过滤器 effective_end_at__gt='' 将 DateTimeField 与空字符串比较，
  在 MariaDB/MySQL 后端抛 ValidationError，任务每次调度都崩溃，
  到期公告的存储 status 永远不会被置为 expired。

修复：
  过滤器改为 effective_end_at__isnull=False（与原意图等价：排除长期有效）。

本文件验证修复后行为：
  1. 任务正常执行，到期公告被置为 expired
  2. 长期有效（end 为空）与未到期公告不受影响
  3. schedule 频率保持每小时 :05（与代码注释一致）
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.home.models import STATUS_PUBLISHED, STATUS_EXPIRED
from apps.home.celery_beat_schedule import HOME_BEAT_SCHEDULE
from apps.home.tasks import sync_announcement_status
from apps.home.tests.characterization.test_announcement import (
    _make_user, _make_announcement,
)
from apps.utils.test_helpers import setup_test_env


class Bug2CeleryScheduleExpressionTests(TestCase):
    """公告状态同步定时任务修复回归"""

    def setUp(self):
        setup_test_env(self)
        self.task_user = _make_user('task_user', tenant_id='t1')

    def test_schedule_is_hourly_at_minute_5(self):
        """schedule 为每小时 :05 执行一次（celery 解析后 minute 是 {5} 的集合）"""
        schedule_entry = HOME_BEAT_SCHEDULE['announcement-sync-status']
        schedule = schedule_entry['schedule']

        # celery crontab 将 minute=5 解析为集合 {5}，表示仅在第 5 分钟匹配
        self.assertEqual(schedule.minute, {5},
                         '期望 crontab(minute=5) 即每小时 :05 一次，'
                         f'实际: {schedule.minute}')

        # 排除每分钟（60 个分钟位全匹配）与每 5 分钟（12 个分钟位）
        every_minute = set(range(60))
        every_5_minutes = set(range(0, 60, 5))
        self.assertNotEqual(schedule.minute, every_minute, '不应是每分钟执行')
        self.assertNotEqual(schedule.minute, every_5_minutes, '不应是每 5 分钟执行')

    def test_task_runs_and_expires_due_announcements(self):
        """修复后任务正常执行：到期公告被置为 expired"""
        now = timezone.now()
        ann = _make_announcement(
            self.task_user,
            status=STATUS_PUBLISHED,
            effective_start_at=now - timedelta(hours=2),
            effective_end_at=now - timedelta(minutes=10),
        )
        self.assertEqual(ann.status, STATUS_PUBLISHED)

        updated = sync_announcement_status()

        ann.refresh_from_db()
        self.assertEqual(ann.status, STATUS_EXPIRED,
                         '到期公告的存储 status 应被任务置为 expired')
        self.assertGreaterEqual(updated, 1)

    def test_task_skips_long_valid_and_future_end(self):
        """长期有效（end 为 NULL）与未到期公告不受影响"""
        now = timezone.now()
        ann_long = _make_announcement(
            self.task_user, title='长期有效',
            status=STATUS_PUBLISHED,
            effective_end_at=None,
        )
        ann_future = _make_announcement(
            self.task_user, title='未到期',
            status=STATUS_PUBLISHED,
            effective_end_at=now + timedelta(days=1),
        )

        sync_announcement_status()

        ann_long.refresh_from_db()
        ann_future.refresh_from_db()
        self.assertEqual(ann_long.status, STATUS_PUBLISHED, '长期有效公告不应被改动')
        self.assertEqual(ann_future.status, STATUS_PUBLISHED, '未到期公告不应被改动')
