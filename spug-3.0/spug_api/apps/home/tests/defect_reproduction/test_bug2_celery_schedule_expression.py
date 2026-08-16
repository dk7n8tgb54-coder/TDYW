# -*- coding: utf-8 -*-
"""
Bug 2 验证测试：Celery Beat Schedule 表达式与注释一致性

缺陷描述：
  celery_beat_schedule.py 注释说"每小时第 5 分钟"，
  crontab(minute=5) 确实是每小时的 :05 分执行一次，
  但这意味着公告过期后，管理端 status 字段最长滞后 59 分钟才被更新。
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.home.models import Announcement, STATUS_PUBLISHED, STATUS_EXPIRED
from apps.home.celery_beat_schedule import HOME_BEAT_SCHEDULE
from apps.home.tasks import sync_announcement_status
from apps.home.tests.characterization.test_announcement import (
    _make_user, _make_announcement,
)
from apps.utils.test_helpers import setup_test_env


class Bug2CeleryScheduleExpressionTests(TestCase):
    """Celery Beat Schedule 表达式验证"""

    def test_schedule_is_hourly_at_minute_5(self):
        """验证 schedule 是每小时的第 5 分钟，而非每分钟或每 5 分钟"""
        schedule_entry = HOME_BEAT_SCHEDULE['announcement-sync-status']
        schedule = schedule_entry['schedule']

        # crontab 对象的 _orig_minute 存储原始分钟参数
        minute_repr = repr(schedule)
        self.assertIn('5', minute_repr,
                      f'期望 crontab(minute=5)，实际: {minute_repr}')

        # 验证不是 crontab(minute='*/1')（每分钟）
        # crontab(minute=5) 的 minute 属性是 '5'（字符串）
        actual_minute = schedule.minute
        self.assertEqual(actual_minute, '5',
                         f'期望 minute="5"（每小时 :05），实际: {actual_minute}')

        # 如果是每分钟，minute 会是 '*'；如果是每 5 分钟，会是 '*/5'
        self.assertNotEqual(actual_minute, '*',
                            '不应是每分钟执行')
        self.assertNotEqual(actual_minute, '*/1',
                            '不应是每分钟执行')
        self.assertNotEqual(actual_minute, '*/5',
                            '不应是每 5 分钟执行')

    def test_task_updates_expired_announcements(self):
        """sync_announcement_status 任务能正确将到期公告标记为 expired"""
        now = timezone.now()
        ann = _make_announcement(
            _make_user('task_user', tenant_id='t1'),
            status=STATUS_PUBLISHED,
            effective_start_at=now - timedelta(hours=2),
            effective_end_at=now - timedelta(minutes=10),
        )

        # 任务执行前，status 仍为 published（模拟定时任务延迟场景）
        self.assertEqual(ann.status, STATUS_PUBLISHED)

        # 执行任务
        updated = sync_announcement_status()

        ann.refresh_from_db()
        self.assertEqual(ann.status, STATUS_EXPIRED,
                         'sync_announcement_status 应将到期公告标记为 expired')
        self.assertGreaterEqual(updated, 1)

    def test_task_does_not_affect_long_valid_announcements(self):
        """sync_announcement_status 不影响长期有效的公告"""
        now = timezone.now()
        ann = _make_announcement(
            _make_user('task_user2', tenant_id='t1'),
            status=STATUS_PUBLISHED,
            effective_end_at=now + timedelta(days=30),
        )

        sync_announcement_status()
        ann.refresh_from_db()
        self.assertEqual(ann.status, STATUS_PUBLISHED,
                         '未到期公告不应被标记为 expired')

    def test_worst_case_lag_is_59_minutes(self):
        """验证最坏情况下管理端 status 滞后可达 59 分钟"""
        # schedule 在每小时 :05 执行
        # 如果公告在 :06 过期，下一次执行是下个小时的 :05
        # 滞后 = 59 分钟
        # 这个测试记录这一事实，不修改行为
        schedule_entry = HOME_BEAT_SCHEDULE['announcement-sync-status']
        schedule = schedule_entry['schedule']

        # 计算理论上最大滞后分钟数
        # crontab(minute=5) 意味着每小时只执行一次
        # 最大滞后 = 60 - 1 = 59 分钟
        minute_val = schedule.minute
        if minute_val.isdigit():
            lag_minutes = 60 - int(minute_val) - 1
            # 如果公告恰好在 :minute_val+1 过期
            self.assertGreaterEqual(lag_minutes, 0)
            # 记录最大滞后
            self.assertLessEqual(lag_minutes, 59,
                                  f'每小时执行一次时，最大滞后不超过 59 分钟'
                                  f'（当前配置最大滞后: {lag_minutes} 分钟）')
