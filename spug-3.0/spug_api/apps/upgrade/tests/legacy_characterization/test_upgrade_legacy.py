# -*- coding: utf-8 -*-
"""系统升级模块 legacy_characterization 测试

2026-09 升级管理挂接系统档案（upgrade 0022）后更新：
- 原"system 是文本字段不是外键""UpgradeSystem 字典表结构"等固化旧现状的
  测试已随业务规则有意变更而改写为新契约（FK 关联 LifecycleSystem + 快照）；
- 字典表 UpgradeSystem 已删除，相关测试移除。
"""
from django.test import TestCase
from django.db.models import ProtectedError
from apps.utils.test_helpers import make_user, setup_test_env
from apps.upgrade.models import UpgradeRecord
from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.tests.base import make_system


class UpgradeRecordLinkageFieldsTest(TestCase):
    """记录 UpgradeRecord 挂接系统档案后的字段结构"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_upg', ['upgrade.upgrade.view'])

    def test_system_field_is_fk_to_lifecycle_system(self):
        """NEW: system 是指向系统档案 LifecycleSystem 的外键（可空，兼容历史未匹配记录）"""
        field = UpgradeRecord._meta.get_field('system')
        self.assertEqual(field.get_internal_type(), 'ForeignKey')
        self.assertEqual(field.related_model, LifecycleSystem)
        self.assertTrue(field.null)

    def test_system_snapshot_fields_exist(self):
        """NEW: 存在编号/名称/安装地点快照字段"""
        for name in ('system_code', 'system_name', 'system_location'):
            field = UpgradeRecord._meta.get_field(name)
            self.assertEqual(field.get_internal_type(), 'CharField', name)

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

    def test_rename_system_doesnt_update_record_snapshot(self):
        """NEW: 系统档案改名后，已保存记录的名称快照不随动（快照仅用于历史展示）"""
        system = make_system(self.user, tenant_id=self.user.tenant_id, name='旧名')
        rec = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='升级',
            system=system, system_name=system.name,
            upgrade_type='软件升级', created_by=self.user)
        system.name = '新名'
        system.save()
        rec.refresh_from_db()
        self.assertEqual(rec.system_name, '旧名')
        # 正式外键仍指向同一系统
        self.assertEqual(rec.system_id, system.id)

    def test_delete_linked_system_protected(self):
        """NEW: 存在升级记录引用的系统不可物理删除（PROTECT）"""
        system = make_system(self.user, tenant_id=self.user.tenant_id)
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='升级',
            system=system, system_name=system.name,
            upgrade_type='软件升级', created_by=self.user)
        with self.assertRaises(ProtectedError):
            system.delete()

    def test_unlinked_legacy_record_allowed(self):
        """NEW: 历史未匹配记录允许 system 外键为空，仅保留名称快照"""
        rec = UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, title='历史遗留',
            system_name='无法匹配的旧系统名',
            upgrade_type='软件升级', created_by=self.user)
        rec.refresh_from_db()
        self.assertIsNone(rec.system_id)
        self.assertEqual(rec.system_name, '无法匹配的旧系统名')
