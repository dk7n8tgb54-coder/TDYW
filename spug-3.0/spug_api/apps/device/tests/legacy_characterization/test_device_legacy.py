# -*- coding: utf-8 -*-
"""设备模块 legacy_characterization 测试

记录当前旧架构行为，用于重构前后对照。
这些测试不应进入长期发布门禁，重构完成后应逐项删除或转化。

关键现状：
- DeviceResume 当前字段和职责（不等于未来设备主数据）
- DeviceEvent.device_resume_id 使用 IntegerField（非外键）
- DeviceEvent 冗余存储 device_name/device_sn（文本副本）
- 当前不存在资产编号字段
- 当前不存在正式系统关系
"""
import unittest
from django.test import TestCase
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.device.models import DeviceResume, DeviceEvent


class DeviceResumeLegacyFieldsTest(TestCase):
    """记录 DeviceResume 当前字段结构"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_dev', [
            'device.device_resume.view',
            'device.device_resume.add',
        ])
        self.client = make_client(self.user)

    def test_device_resume_has_text_responsible_user_name(self):
        """LEGACY: responsible_user_name 是文本字段，不是外键"""
        dev = DeviceResume.objects.create(
            tenant_id=self.user.tenant_id,
            device_sn='LEGACY-001',
            device_name='Legacy Device',
            device_model='Model-L',
            current_status='1',
            responsible_user_name='张三',
            created_by=self.user,
        )
        dev.refresh_from_db()
        self.assertEqual(dev.responsible_user_name, '张三')
        # 确认是文本，不是外键
        field = DeviceResume._meta.get_field('responsible_user_name')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_device_resume_current_status_is_charfield(self):
        """LEGACY: current_status 是 CharField（'1'-'5'），不是 IntegerField"""
        dev = DeviceResume.objects.create(
            tenant_id=self.user.tenant_id,
            device_sn='LEGACY-002',
            device_name='Status Device',
            device_model='Model-S',
            current_status='3',
            created_by=self.user,
        )
        dev.refresh_from_db()
        self.assertEqual(dev.current_status, '3')
        field = DeviceResume._meta.get_field('current_status')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_device_resume_no_asset_number_field(self):
        """LEGACY: DeviceResume 没有资产编号字段"""
        field_names = [f.name for f in DeviceResume._meta.get_fields()]
        asset_fields = [f for f in field_names if 'asset' in f.lower()]
        self.assertEqual(asset_fields, [],
                         'DeviceResume should not have asset number field in current architecture')

    def test_device_resume_no_system_relationship(self):
        """LEGACY: DeviceResume 没有正式系统关系外键"""
        fk_fields = [f for f in DeviceResume._meta.get_fields()
                     if f.get_internal_type() == 'ForeignKey']
        system_fks = [f for f in fk_fields
                      if 'system' in f.name.lower() or 'subsystem' in f.name.lower()]
        self.assertEqual(system_fks, [],
                         'DeviceResume should not have system FK in current architecture')


class DeviceEventLegacyRelationshipTest(TestCase):
    """记录 DeviceEvent 当前关联方式"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_evt', [
            'device.device_resume.view',
            'device.device_resume.history_view',
        ])
        self.client = make_client(self.user)

    def test_device_event_resume_id_is_integer_field(self):
        """LEGACY: DeviceEvent.device_resume_id 是 IntegerField，不是外键"""
        field = DeviceEvent._meta.get_field('device_resume_id')
        self.assertEqual(field.get_internal_type(), 'IntegerField')

    def test_device_event_has_redundant_text_fields(self):
        """LEGACY: DeviceEvent 冗余存储 device_name 和 device_sn 为文本"""
        dev = DeviceResume.objects.create(
            tenant_id=self.user.tenant_id,
            device_sn='LEGACY-EVT-001',
            device_name='Event Device',
            device_model='Model-E',
            current_status='1',
            created_by=self.user,
        )
        event = DeviceEvent.objects.create(
            tenant_id=self.user.tenant_id,
            device_resume_id=dev.id,
            device_name='Event Device',
            device_sn='LEGACY-EVT-001',
            event_type=2,
            event_title='Device Update',
            created_by=self.user,
        )
        event.refresh_from_db()
        self.assertEqual(event.device_name, 'Event Device')
        self.assertEqual(event.device_sn, 'LEGACY-EVT-001')
        # 确认是文本字段
        name_field = DeviceEvent._meta.get_field('device_name')
        sn_field = DeviceEvent._meta.get_field('device_sn')
        self.assertEqual(name_field.get_internal_type(), 'CharField')
        self.assertEqual(sn_field.get_internal_type(), 'CharField')

    def test_device_rename_doesnt_update_event_text(self):
        """LEGACY: 设备改名后事件记录中的旧名称不会自动更新"""
        dev = DeviceResume.objects.create(
            tenant_id=self.user.tenant_id,
            device_sn='LEGACY-RN-001',
            device_name='Old Name',
            device_model='Model-R',
            current_status='1',
            created_by=self.user,
        )
        event = DeviceEvent.objects.create(
            tenant_id=self.user.tenant_id,
            device_resume_id=dev.id,
            device_name='Old Name',
            device_sn='LEGACY-RN-001',
            event_type=2,
            event_title='Before Rename',
            created_by=self.user,
        )
        # 改设备名
        dev.device_name = 'New Name'
        dev.save()
        event.refresh_from_db()
        # 事件记录中的名称仍然是旧名称
        self.assertEqual(event.device_name, 'Old Name')

    @unittest.skip('DEF-001: DeviceResume CHECK 约束 device_delete_fields_valid 阻止手动软删除')
    def test_device_soft_delete_preserves_events(self):
        """LEGACY: 设备软删除后事件记录仍可查询"""
        dev = DeviceResume.objects.create(
            tenant_id=self.user.tenant_id,
            device_sn='LEGACY-SD-001',
            device_name='Soft Delete Device',
            device_model='Model-SD',
            current_status='1',
            created_by=self.user,
        )
        event = DeviceEvent.objects.create(
            tenant_id=self.user.tenant_id,
            device_resume_id=dev.id,
            device_name='Soft Delete Device',
            device_sn='LEGACY-SD-001',
            event_type=1,
            event_title='Fault Event',
            created_by=self.user,
        )
        # 软删除设备
        from django.utils import timezone
        dev.is_deleted = True
        dev.deleted_at = timezone.now()
        dev.deleted_by = self.user
        dev.delete_reason = '测试删除'
        dev.save()
        # 事件记录仍存在
        self.assertTrue(DeviceEvent.objects.filter(pk=event.id).exists())
        # 事件记录的 device_resume_id 仍指向已删除设备
        self.assertEqual(event.device_resume_id, dev.id)

    def test_events_are_manually_created(self):
        """LEGACY: 设备事件是手工创建的，不是自动生成"""
        dev = DeviceResume.objects.create(
            tenant_id=self.user.tenant_id,
            device_sn='LEGACY-MC-001',
            device_name='Manual Event Device',
            device_model='Model-MC',
            current_status='1',
            created_by=self.user,
        )
        # 创建设备后不会有自动事件
        events = DeviceEvent.objects.filter(device_resume_id=dev.id)
        self.assertEqual(events.count(), 0)
