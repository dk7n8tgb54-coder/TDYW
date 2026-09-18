# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.interference.models import InterferenceEvent
from apps.upgrade.models import UpgradeRecord
from apps.duty.models import DutyRecord
from apps.runlog.models import RunLog
from apps.account.models import User
import json


class RunLogModelTest(TestCase):
    """RunLog模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_run_log(self):
        """测试创建运行日志"""
        run_log = RunLog.objects.create(
            tenant_id='test_tenant',
            event_title='测试运行日志',
            event_type='运行异常',
            system_name='系统A',
            severity='P2',
            status='in_progress',
            created_by=self.user
        )
        self.assertEqual(run_log.system_name, '系统A')
        self.assertEqual(run_log.tenant_id, 'test_tenant')


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
            scene_code='unknown', classification_status='pending',
            interference_kind_code='other', affected_system_code='other',
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
            tenant_id='test_tenant',
            system='系统A',
            upgrade_type='主版本升级',
            version='2.0.0',
            upgrade_time='2024-01-20',
            status='待处理',
            owner='张三',
            created_by=self.user
        )
        self.assertEqual(upgrade.status, '待处理')


class DutyRecordModelTest(TestCase):
    """DutyRecord模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_duty_record(self):
        """测试创建值班记录"""
        duty = DutyRecord.objects.create(
            tenant_id='test_tenant',
            duty_person='张三',
            reporter='李四',
            department='运维部',
            duty_date='2024-01-15',
            duty_situation='值班情况正常',
            created_by=self.user
        )
        self.assertEqual(duty.duty_person, '张三')
        self.assertEqual(duty.duty_date, '2024-01-15')

