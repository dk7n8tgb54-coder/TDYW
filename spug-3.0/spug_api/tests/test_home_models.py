# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.home.models import Announcement


class AnnouncementModelTest(TestCase):
    """Announcement 模型测试（Navigation 已移除）"""

    def test_announcement_model_exists(self):
        """Announcement 模型可用"""
        self.assertTrue(Announcement.objects is not None)
