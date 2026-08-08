# -*- coding: utf-8 -*-
"""系统升级模块 legacy_characterization 测试"""
from django.test import TestCase
from apps.utils.test_helpers import make_user, setup_test_env
from apps.upgrade.models import UpgradeRecord, UpgradeSystem
from apps.device.models import DeviceEvent


class UpgradeRecordLegacyFieldsTest(TestCase):
    """记录 UpgradeRecord 当前字段结构"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_upg', ['upgrade.upgrade.view'])

    def test_system_field_is_text_not_fk(self):
        """LEGACY: system 是文本字段，不是外键"""
        field = UpgradeRecord._meta.get_field('system')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_owner_is_text_not_fk(self):
        """LEGACY: owner 是文本字段"""
        field = UpgradeRecord._meta.get_field('owner')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_no_fk_to_device(self):
        """LEGACY: 没有外键关联到设备表"""
        fk_fields = [f for f in UpgradeRecord._meta.get_fields()
                     if f.get_internal_type() == 'ForeignKey']
        device_fks = [f for f in fk_fields if 'device' in f.name.lower()]
        self.assertEqual(device_fks, [])

    def test_rename_system_doesnt_update_record(self):
        """LEGACY: 改系统名称后旧记录中的文本不会更新"""
        sys = UpgradeSystem.objects.create(
            tenant_id=self.user.tenant_id, name='旧名',
            is_active=True, sort_order=1, created_by=self.user)
        rec = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='升级', system='旧名',
            upgrade_type='软件升级', created_by=self.user)
        sys.name = '新名'
        sys.save()
        rec.refresh_from_db()
        self.assertEqual(rec.system, '旧名')

    def test_delete_system_doesnt_delete_records(self):
        """LEGACY: 删除候选项后升级记录仍存在"""
        sys = UpgradeSystem.objects.create(
            tenant_id=self.user.tenant_id, name='待删系统',
            is_active=True, sort_order=1, created_by=self.user)
        rec = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='升级', system='待删系统',
            upgrade_type='软件升级', created_by=self.user)
        sys.delete()
        self.assertTrue(UpgradeRecord.objects.filter(pk=rec.id).exists())

    def test_no_auto_device_history(self):
        """LEGACY: 创建升级记录不会自动写入 DeviceEvent"""
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='自动履历测试',
            system='测试', upgrade_type='软件升级', created_by=self.user)
        self.assertEqual(DeviceEvent.objects.filter(event_title='自动履历测试').count(), 0)


class UpgradeSystemLegacyFieldsTest(TestCase):
    """记录 UpgradeSystem 当前字段结构"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_sys', ['upgrade.upgrade.view'])

    def test_upgrade_system_is_dictionary_table(self):
        """LEGACY: UpgradeSystem 是字典表（候选项），不是全局系统主数据"""
        # UpgradeSystem 有 tenant_id，是租户级别的字典
        field = UpgradeSystem._meta.get_field('tenant_id')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_upgrade_system_has_sort_order(self):
        """LEGACY: UpgradeSystem 有排序字段"""
        field = UpgradeSystem._meta.get_field('sort_order')
        self.assertEqual(field.get_internal_type(), 'IntegerField')

    def test_upgrade_system_has_is_active(self):
        """LEGACY: UpgradeSystem 有启用/停用标志"""
        field = UpgradeSystem._meta.get_field('is_active')
        self.assertEqual(field.get_internal_type(), 'BooleanField')
