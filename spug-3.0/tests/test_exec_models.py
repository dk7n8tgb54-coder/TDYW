# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.exec.models import (
    RunLog, FaultRecord, FaultPart, Interference, UpgradeRecord,
    DutyRecord, HandoverRecord
)
from apps.schedule.models import (
    ScheduleStaff, ScheduleShift, ScheduleShiftTime, Schedule,
    ScheduleSwap, ScheduleSubstitute
)
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
            system_name='系统A',
            log_date='2024-01-15',
            detail_record='日志详情',
            handler='张三',
            recorder='李四',
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
            plan_time='2024-01-20',
            status='待处理',
            owner='张三',
            checklist='[]',
            dependencies='[]',
            issues='[]',
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
            plan_time='2024-01-20',
            owner='张三',
            checklist='[]',
            dependencies='[]',
            issues='[]',
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
                plan_time='2024-01-21',
                owner='李四',
                checklist='[]',
                dependencies='[]',
                issues='[]',
                created_by=self.user
            )

    def test_upgrade_no_can_be_same_across_tenants(self):
        """测试不同租户可以使用相同的升级单号"""
        # 租户1创建升级单
        UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            upgrade_no='UPG001',
            system='系统A',
            upgrade_type='主版本升级',
            version='2.0.0',
            plan_time='2024-01-20',
            owner='张三',
            created_by=self.user
        )
        # 不同租户可以使用相同的升级单号
        upgrade2 = UpgradeRecord.objects.create(
            tenant_id='test_tenant2',
            upgrade_no='UPG001',
            system='系统B',
            upgrade_type='主版本升级',
            version='3.0.0',
            plan_time='2024-01-21',
            owner='李四',
            created_by=self.user
        )
        self.assertEqual(upgrade2.upgrade_no, 'UPG001')
        self.assertEqual(upgrade2.tenant_id, 'test_tenant2')


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
            user_name='张三',
            duty_date='2024-01-15',
            log_content='值班日志',
            events='[]',
            attachments='[]',
            created_by=self.user
        )
        self.assertEqual(duty.user_name, '张三')
        self.assertEqual(duty.duty_date, '2024-01-15')


class HandoverRecordModelTest(TestCase):
    """HandoverRecord模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_handover_record(self):
        """测试创建交接班记录"""
        handover = HandoverRecord.objects.create(
            tenant_id='test_tenant',
            from_user_name='张三',
            to_user_name='李四',
            handover_time='2024-01-15 08:00:00',
            items='[]',
            notes='注意事项',
            confirmed=True,
            confirmed_at='2024-01-15 08:05:00',
            created_by=self.user
        )
        self.assertEqual(handover.from_user_name, '张三')
        self.assertEqual(handover.to_user_name, '李四')
        self.assertTrue(handover.confirmed)


class ScheduleStaffModelTest(TestCase):
    """ScheduleStaff模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_schedule_staff(self):
        """测试创建排班人员"""
        staff = ScheduleStaff.objects.create(
            tenant_id='test_tenant',
            user_id=1,
            user_name='张三',
            department='运维部',
            phone='13800138000',
            is_active=True,
            unavailable_dates='[]',
            created_by=self.user
        )
        self.assertEqual(staff.user_name, '张三')
        self.assertEqual(staff.department, '运维部')
        self.assertTrue(staff.is_active)


class ScheduleShiftModelTest(TestCase):
    """ScheduleShift模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_schedule_shift(self):
        """测试创建班次规则"""
        shift = ScheduleShift.objects.create(
            tenant_id='test_tenant',
            name='白班',
            work_days=5,
            rest_days=2,
            shift_type='work_rest',
            description='上5休2',
            color='#ff0000',
            is_default=True,
            created_by=self.user
        )
        self.assertEqual(shift.name, '白班')
        self.assertEqual(shift.work_days, 5)
        self.assertTrue(shift.is_default)


class ScheduleShiftTimeModelTest(TestCase):
    """ScheduleShiftTime模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_schedule_shift_time(self):
        """测试创建班次时间配置"""
        shift_time = ScheduleShiftTime.objects.create(
            tenant_id='test_tenant',
            shift_id=1,
            shift_name='白班',
            start_time='08:00',
            end_time='17:00',
            color='#ff0000',
            sort_order=1,
            created_by=self.user
        )
        self.assertEqual(shift_time.shift_name, '白班')
        self.assertEqual(shift_time.start_time, '08:00')
        self.assertEqual(shift_time.end_time, '17:00')


class ScheduleModelTest(TestCase):
    """Schedule模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_schedule(self):
        """测试创建排班表"""
        schedule = Schedule.objects.create(
            tenant_id='test_tenant',
            staff_id=1,
            staff_name='张三',
            schedule_date='2024-01-15',
            shift_id=1,
            shift_name='白班',
            shift_time_id=1,
            notes='备注',
            created_by=self.user
        )
        self.assertEqual(schedule.staff_name, '张三')
        self.assertEqual(schedule.schedule_date, '2024-01-15')
        self.assertEqual(schedule.shift_name, '白班')


class ScheduleSwapModelTest(TestCase):
    """ScheduleSwap模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_schedule_swap(self):
        """测试创建换班记录"""
        swap = ScheduleSwap.objects.create(
            tenant_id='test_tenant',
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
            reason='个人原因',
            status='pending',
            created_by=self.user
        )
        self.assertEqual(swap.from_staff_name, '张三')
        self.assertEqual(swap.to_staff_name, '李四')
        self.assertEqual(swap.status, 'pending')
    
    def test_schedule_swap_approve(self):
        """测试换班审批"""
        swap = ScheduleSwap.objects.create(
            tenant_id='test_tenant',
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
            created_by=self.user
        )
        
        admin = User.objects.create(
            username='admin',
            nickname='管理员',
            password_hash=User.make_password('admin123'),
            tenant_id='test_tenant'
        )
        
        swap.status = 'approved'
        swap.approved_by = admin
        swap.approved_by_name = '管理员'
        swap.approved_at = '2024-01-15 10:00:00'
        swap.save()
        
        swap.refresh_from_db()
        self.assertEqual(swap.status, 'approved')
        self.assertEqual(swap.approved_by_name, '管理员')


class ScheduleSubstituteModelTest(TestCase):
    """ScheduleSubstitute模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_schedule_substitute(self):
        """测试创建替班记录"""
        substitute = ScheduleSubstitute.objects.create(
            tenant_id='test_tenant',
            original_staff_id=1,
            original_staff_name='张三',
            substitute_staff_id=2,
            substitute_staff_name='李四',
            schedule_date='2024-01-15',
            shift_id=1,
            shift_name='白班',
            reason='张三有事',
            status='pending',
            created_by=self.user
        )
        self.assertEqual(substitute.original_staff_name, '张三')
        self.assertEqual(substitute.substitute_staff_name, '李四')
        self.assertEqual(substitute.status, 'pending')
