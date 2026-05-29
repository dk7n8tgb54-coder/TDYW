# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.fault.models import FaultRecord
from apps.upgrade.models import UpgradeRecord
from apps.duty.models import DutyRecord
from apps.schedule.models import ScheduleSwap
from apps.runlog.models import RunLog
from apps.account.models import User
from libs.tenant_utils import apply_tenant_filter
import json


class TenantFilterTest(TestCase):
    """多租户过滤测试"""
    
    def setUp(self):
        """测试前准备"""
        # 创建不同租户的用户
        self.user1 = User.objects.create(
            username='user1',
            nickname='用户1',
            password_hash=User.make_password('password123'),
            tenant_id='tenant1'
        )
        
        self.user2 = User.objects.create(
            username='user2',
            nickname='用户2',
            password_hash=User.make_password('password123'),
            tenant_id='tenant2'
        )
        
        self.global_admin = User.objects.create(
            username='admin',
            nickname='全局管理员',
            password_hash=User.make_password('admin123'),
            tenant_id='admin',
            is_supper=True
        )
    
    def test_run_log_tenant_filter(self):
        """测试运行日志的租户过滤"""
        # 创建不同租户的运行日志
        RunLog.objects.create(
            tenant_id='tenant1',
            system_name='系统A',
            log_date='2024-01-15',
            detail_record='日志1',
            created_by=self.user1
        )
        
        RunLog.objects.create(
            tenant_id='tenant2',
            system_name='系统B',
            log_date='2024-01-16',
            detail_record='日志2',
            created_by=self.user2
        )
        
        RunLog.objects.create(
            tenant_id='tenant1',
            system_name='系统C',
            log_date='2024-01-17',
            detail_record='日志3',
            created_by=self.user1
        )
        
        # 用户1只能看到tenant1的数据
        queryset = RunLog.objects.all()
        filtered = apply_tenant_filter(queryset, self.user1)
        self.assertEqual(filtered.count(), 2)
        
        # 用户2只能看到tenant2的数据
        filtered = apply_tenant_filter(queryset, self.user2)
        self.assertEqual(filtered.count(), 1)
    
    def test_fault_record_tenant_filter(self):
        """测试故障记录的租户过滤"""
        FaultRecord.objects.create(
            tenant_id='tenant1',
            system_name='系统A',
            device_code='DEV001',
            fault_date='2024-01-15',
            handler='张三',
            recorder='李四',
            fault_level='高',
            fault_phenomenon='故障1',
            handling_process='处理1',
            created_by=self.user1
        )
        
        FaultRecord.objects.create(
            tenant_id='tenant2',
            system_name='系统B',
            device_code='DEV002',
            fault_date='2024-01-16',
            handler='王五',
            recorder='赵六',
            fault_level='中',
            fault_phenomenon='故障2',
            handling_process='处理2',
            created_by=self.user2
        )
        
        queryset = FaultRecord.objects.all()
        
        # 用户1只能看到tenant1的数据
        filtered = apply_tenant_filter(queryset, self.user1)
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(filtered.first().tenant_id, 'tenant1')
        
        # 用户2只能看到tenant2的数据
        filtered = apply_tenant_filter(queryset, self.user2)
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(filtered.first().tenant_id, 'tenant2')
    
    def test_upgrade_record_tenant_filter(self):
        """测试升级记录的租户过滤"""
        # 创建不同租户的升级记录
        for i in range(3):
            UpgradeRecord.objects.create(
                tenant_id='tenant1',
                upgrade_no=f'UPG{i}',
                system=f'系统{i}',
                upgrade_type='升级',
                version='1.0.0',
                plan_time='2024-01-15',
                owner='张三',
                created_by=self.user1
            )
        
        for i in range(2):
            UpgradeRecord.objects.create(
                tenant_id='tenant2',
                upgrade_no=f'UPG{i+3}',
                system=f'系统{i+3}',
                upgrade_type='升级',
                version='1.0.0',
                plan_time='2024-01-15',
                owner='李四',
                created_by=self.user2
            )
        
        queryset = UpgradeRecord.objects.all()
        
        # 用户1只能看到tenant1的数据
        filtered = apply_tenant_filter(queryset, self.user1)
        self.assertEqual(filtered.count(), 3)
        
        # 用户2只能看到tenant2的数据
        filtered = apply_tenant_filter(queryset, self.user2)
        self.assertEqual(filtered.count(), 2)
    
    def test_global_admin_no_filter(self):
        """测试全局管理员不过滤"""
        # 创建不同租户的数据
        RunLog.objects.create(
            tenant_id='tenant1',
            system_name='系统A',
            log_date='2024-01-15',
            detail_record='日志1',
            created_by=self.user1
        )
        
        RunLog.objects.create(
            tenant_id='tenant2',
            system_name='系统B',
            log_date='2024-01-16',
            detail_record='日志2',
            created_by=self.user2
        )
        
        queryset = RunLog.objects.all()
        
        # 全局管理员应该能看到所有数据
        from apps.account.models import Role
        global_role = Role.objects.create(
            name='全局管理员',
            is_global_admin=True,
            created_by=self.global_admin
        )
        self.global_admin.roles.add(global_role)
        
        filtered = apply_tenant_filter(queryset, self.global_admin)
        self.assertEqual(filtered.count(), 2)
    
    def test_schedule_swap_tenant_filter(self):
        """测试换班记录的租户过滤"""
        ScheduleSwap.objects.create(
            tenant_id='tenant1',
            from_staff_id=1,
            from_staff_name='张三',
            to_staff_id=2,
            to_staff_name='李四',
            from_date='2024-01-15',
            to_date='2024-01-16',
            from_shift_id=1,
            from_shift_name='白班',
            to_shift_id=1,
            to_shift_name='白班',
            created_by=self.user1
        )
        
        ScheduleSwap.objects.create(
            tenant_id='tenant2',
            from_staff_id=3,
            from_staff_name='王五',
            to_staff_id=4,
            to_staff_name='赵六',
            from_date='2024-01-17',
            to_date='2024-01-18',
            from_shift_id=1,
            from_shift_name='夜班',
            to_shift_id=1,
            to_shift_name='夜班',
            created_by=self.user2
        )
        
        queryset = ScheduleSwap.objects.all()
        
        # 用户1只能看到tenant1的数据
        filtered = apply_tenant_filter(queryset, self.user1)
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(filtered.first().from_staff_name, '张三')
        
        # 用户2只能看到tenant2的数据
        filtered = apply_tenant_filter(queryset, self.user2)
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(filtered.first().from_staff_name, '王五')
