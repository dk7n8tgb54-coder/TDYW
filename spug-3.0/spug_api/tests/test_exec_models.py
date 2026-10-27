# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.interference.models import InterferenceEvent
from apps.upgrade.models import UpgradeRecord
from apps.account.models import User
from apps.utils.test_helpers import make_upgrade_no
import json


class InterferenceModelTest(TestCase):
    """InterferenceEvent模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_interference(self):
        """测试创建干扰记录"""
        interference = InterferenceEvent.objects.create(
            tenant_id='test_tenant', datetime='2024-01-15 10:00:00',
            scene_code='unknown',
            interference_kind_code='intermittent', affected_system_code='other',
            source_type_code='unknown', phenomenon='信号波动',
            created_by=self.user
        )
        self.assertEqual(interference.phenomenon, '信号波动')
        self.assertEqual(interference.scene_code, 'unknown')


class UpgradeRecordModelTest(TestCase):
    """UpgradeRecord模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_upgrade_record(self):
        """测试创建升级记录"""
        upgrade = UpgradeRecord.objects.create(
            upgrade_no=make_upgrade_no(),
            tenant_id='test_tenant',
            system_name='系统A',
            upgrade_type='主版本升级',
            upgrade_time='2024-01-20',
            status='待处理',
            owner='张三',
            created_by=self.user
        )
        self.assertEqual(upgrade.status, '待处理')

