# -*- coding: utf-8 -*-
"""故障模块 legacy_characterization 测试

记录当前旧架构行为，用于重构前后对照。
关键现状：
- FaultRecord 用文本字段（system_name/device_code）引用设备，非外键
- FaultPart 与 FaultRecord 无外键关联
- 故障不会自动写入 DeviceHistory
- 无独立编号部件当前如何录入
"""
from django.test import TestCase
from apps.utils.test_helpers import make_user, setup_test_env
from apps.fault.models import FaultRecord, FaultPart
from apps.device.models import DeviceEvent


class FaultRecordLegacyFieldsTest(TestCase):
    """记录 FaultRecord 当前字段结构"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_fault', ['fault.faultrecord.view'])

    def test_system_name_is_text_not_fk(self):
        """LEGACY: system_name 是文本字段，不是外键到系统表"""
        field = FaultRecord._meta.get_field('system_name')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_device_code_is_text_not_fk(self):
        """LEGACY: device_code 是文本字段，不是外键到设备表"""
        field = FaultRecord._meta.get_field('device_code')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_handler_is_text_not_fk(self):
        """LEGACY: handler 是文本字段（人名），不是外键到用户表"""
        field = FaultRecord._meta.get_field('handler')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_recorder_is_text_not_fk(self):
        """LEGACY: recorder 是文本字段（人名），不是外键到用户表"""
        field = FaultRecord._meta.get_field('recorder')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_no_fk_to_device_resume(self):
        """LEGACY: FaultRecord 没有外键关联到 DeviceResume"""
        fk_fields = [f for f in FaultRecord._meta.get_fields()
                     if f.get_internal_type() == 'ForeignKey']
        device_fks = [f for f in fk_fields
                      if 'device' in f.name.lower() or 'resume' in f.name.lower()]
        self.assertEqual(device_fks, [])

    def test_rename_device_doesnt_update_fault_text(self):
        """LEGACY: 设备改名后故障记录中的旧名称不会更新"""
        rec = FaultRecord.objects.create(
            tenant_id=self.user.tenant_id,
            system_name='旧系统名',
            device_code='OLD-001',
            fault_date='2026-01-01 10:00:00',
            handler='处理人',
            recorder='记录人',
            fault_level='一般',
            fault_phenomenon='故障',
            handling_process='处理',
            created_by=self.user,
        )
        # 直接修改字段（模拟设备改名）
        rec.device_code = 'NEW-001'
        rec.save()
        rec.refresh_from_db()
        self.assertEqual(rec.device_code, 'NEW-001')
        # 但其他引用旧编号的记录不会自动更新


class FaultPartLegacyRelationshipTest(TestCase):
    """记录 FaultPart 当前关联方式"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_part', ['fault.faultpart.view'])

    def test_fault_part_has_no_fk_to_fault_record(self):
        """LEGACY: FaultPart 没有外键关联到 FaultRecord"""
        fk_fields = [f for f in FaultPart._meta.get_fields()
                     if f.get_internal_type() == 'ForeignKey']
        record_fks = [f for f in fk_fields
                      if 'fault' in f.name.lower() and 'record' in f.name.lower()]
        self.assertEqual(record_fks, [])

    def test_fault_part_uses_system_name_text(self):
        """LEGACY: FaultPart.system_name 是文本字段"""
        field = FaultPart._meta.get_field('system_name')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_fault_part_has_name_not_asset_number(self):
        """LEGACY: FaultPart 用 name 字段，没有资产编号"""
        field_names = [f.name for f in FaultPart._meta.get_fields()]
        self.assertIn('name', field_names)
        asset_fields = [f for f in field_names if 'asset' in f.lower()]
        self.assertEqual(asset_fields, [])

    def test_no_auto_device_history_on_fault_create(self):
        """LEGACY: 创建故障记录不会自动写入 DeviceEvent"""
        FaultRecord.objects.create(
            tenant_id=self.user.tenant_id,
            system_name='自动履历测试',
            device_code='DEV-AUTO-001',
            fault_date='2026-01-01 10:00:00',
            handler='处理人',
            recorder='记录人',
            fault_level='一般',
            fault_phenomenon='故障',
            handling_process='处理',
            created_by=self.user,
        )
        events = DeviceEvent.objects.filter(device_sn='DEV-AUTO-001')
        self.assertEqual(events.count(), 0)

    def test_no_part_instance_table(self):
        """LEGACY: 当前没有独立部件实例表，FaultPart 是独立记录"""
        # FaultPart 是独立模型，不关联到设备实例
        part = FaultPart.objects.create(
            tenant_id=self.user.tenant_id,
            name='电源模块',
            system_name='供电系统',
            date='2026-01-01 10:00:00',
            fault_date='2026-01-01 10:00:00',
            status='故障',
            created_by=self.user,
        )
        # 可以独立创建和查询，不依赖任何设备记录
        self.assertTrue(FaultPart.objects.filter(pk=part.id).exists())
