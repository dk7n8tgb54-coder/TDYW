# -*- coding: utf-8 -*-
"""
告警监控模块测试

覆盖：
1. apps/alert/tasks.py check_disk_space 满盘快照告警逻辑
2. libs/alert.py send_alert 限流去重
"""
from unittest.mock import patch, MagicMock

from django.core.cache import cache
from django.test import TestCase

from apps.alert.models import Alert


class CheckDiskSpaceTaskTest(TestCase):
    """check_disk_space 任务测试：文件系统容量（shutil.disk_usage）满盘告警"""

    def setUp(self):
        cache.clear()
        Alert.objects.all().delete()

    def _make_disk_usage(self, used, total):
        """构造 shutil.disk_usage mock 对象"""
        usage = MagicMock()
        usage.used = used
        usage.total = total
        usage.free = total - used
        return usage

    @patch('shutil.disk_usage')
    def test_snapshot_alert_when_over_90(self, mock_du):
        """磁盘 >90% 触发快照告警"""
        from apps.alert.tasks import check_disk_space

        # 95% 使用率
        mock_du.return_value = self._make_disk_usage(used=95, total=100)

        check_disk_space()

        alerts = Alert.objects.filter(source='disk')
        self.assertTrue(alerts.exists())
        self.assertIn('磁盘空间告警', alerts.first().title)

    @patch('shutil.disk_usage')
    def test_error_level_when_over_95(self, mock_du):
        """磁盘 >95% 告警等级为 error"""
        from apps.alert.tasks import check_disk_space

        mock_du.return_value = self._make_disk_usage(used=96, total=100)

        check_disk_space()

        alert = Alert.objects.filter(source='disk').first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.level, 'error')

    @patch('shutil.disk_usage')
    def test_no_alert_when_healthy(self, mock_du):
        """磁盘 50% 无告警"""
        from apps.alert.tasks import check_disk_space

        mock_du.return_value = self._make_disk_usage(used=50, total=100)

        check_disk_space()

        self.assertFalse(Alert.objects.filter(source='disk').exists())


class SendAlertDedupTest(TestCase):
    """send_alert 限流去重"""

    def setUp(self):
        cache.clear()
        Alert.objects.all().delete()

    def test_dedup_same_alert_key(self):
        """相同 alert_key 在冷却期内不重复"""
        from libs.alert import send_alert

        send_alert('测试', 'msg1', level='warning', source='disk', alert_key='disk:test')
        send_alert('测试', 'msg2', level='warning', source='disk', alert_key='disk:test')

        # 只产生 1 条 Alert
        self.assertEqual(Alert.objects.filter(alert_key='disk:test').count(), 1)

    def test_different_alert_key_both_sent(self):
        """不同 alert_key 都会发送"""
        from libs.alert import send_alert

        send_alert('A', 'msg', level='warning', source='disk', alert_key='disk:a')
        send_alert('B', 'msg', level='warning', source='disk', alert_key='disk:b')

        self.assertEqual(Alert.objects.filter(source='disk').count(), 2)
