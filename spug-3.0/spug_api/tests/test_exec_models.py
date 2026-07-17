# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.fault.models import (
    FaultRecord, FaultPart
)
from apps.interference.models import Interference
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


class FaultRecordModelTest(TestCase):
    """FaultRecord模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_fault_record(self):
        """测试创建故障记录"""
        fault = FaultRecord.objects.create(
            tenant_id='test_tenant',
            system_name='系统A',
            device_code='DEV001',
            fault_date='2024-01-15',
            handler='张三',
            recorder='李四',
            fault_level='高',
            fault_phenomenon='设备无法启动',
            handling_process='重启设备',
            created_by=self.user
        )
        self.assertEqual(fault.system_name, '系统A')
        self.assertEqual(fault.fault_level, '高')


class FaultPartModelTest(TestCase):
    """FaultPart模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_fault_part(self):
        """测试创建故障部件"""
        fault_part = FaultPart.objects.create(
            tenant_id='test_tenant',
            name='主板',
            system_name='系统A',
            date='2024-01-15',
            fault_date='2024-01-15',
            status='维修中',
            created_by=self.user
        )
        self.assertEqual(fault_part.name, '主板')
        self.assertEqual(fault_part.status, '维修中')


class InterferenceModelTest(TestCase):
    """Interference模型测试"""
    
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
        interference = Interference.objects.create(
            tenant_id='test_tenant',
            serial_number=1,
            frequency='100MHz',
            report_dept='运维部',
            datetime='2024-01-15 10:00:00',
            coordinates='E121.47 N31.23',
            interference_type='信号干扰',
            phenomenon='信号波动',
            created_by=self.user
        )
        self.assertEqual(interference.frequency, '100MHz')
        self.assertEqual(interference.is_reported, '否')


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
            upgrade_no='UPG001',
            system='系统A',
            upgrade_type='主版本升级',
            version='2.0.0',
            upgrade_time='2024-01-20',
            status='待处理',
            owner='张三',
            created_by=self.user
        )
        self.assertEqual(upgrade.upgrade_no, 'UPG001')
        self.assertEqual(upgrade.status, '待处理')
    
    def test_upgrade_unique_constraint(self):
        """测试升级单号唯一约束"""
        UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            upgrade_no='UPG001',
            system='系统A',
            upgrade_type='主版本升级',
            version='2.0.0',
            upgrade_time='2024-01-20',
            owner='张三',
            created_by=self.user
        )
        # 同一租户内不能重复
        with self.assertRaises(Exception):
            UpgradeRecord.objects.create(
                tenant_id='test_tenant',
                upgrade_no='UPG001',
                system='系统B',
                upgrade_type='主版本升级',
                version='3.0.0',
                upgrade_time='2024-01-21',
                owner='李四',
                created_by=self.user
            )


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

