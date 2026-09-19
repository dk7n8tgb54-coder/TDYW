# -*- coding: utf-8 -*-
"""模块边界回归（步骤二）：device、upgrade 不受影响，旧 fault 保持移除。

以真实模型行为验证（非源码字符串匹配）：
- DeviceResume / UpgradeRecord 核心字段与表名不变；
- device / upgrade 没有产生新迁移；
- 旧 fault 应用不再注册、旧表不再存在；
- 新模块数据只落在 equipment_lifecycle 新表。
"""
from django.db import connection

from django.test import TestCase

from apps.device.models import DeviceResume
from apps.upgrade.models import UpgradeRecord
from apps.equipment_lifecycle.models import LifecycleSystem

from apps.equipment_lifecycle.tests.base import (
    make_client, make_system, make_user,
)


class ModuleIsolationTest(TestCase):
    DEVICE_SNAPSHOT_FIELDS = {
        'device_sn': 'CharField', 'device_name': 'CharField', 'device_model': 'CharField',
        'install_location': 'CharField', 'manufacturer': 'CharField',
        'use_unit': 'CharField', 'current_status': 'CharField',
    }
    UPGRADE_SNAPSHOT_FIELDS = {'id': 'AutoField'}

    def test_device_resume_structure_unchanged(self):
        field_map = {f.name: f.get_internal_type() for f in DeviceResume._meta.fields}
        for name, ftype in self.DEVICE_SNAPSHOT_FIELDS.items():
            self.assertIn(name, field_map, f'device.DeviceResume.{name} 缺失')
            self.assertEqual(field_map[name], ftype, f'device.DeviceResume.{name} 类型变化')
        self.assertEqual(DeviceResume._meta.db_table, 'tdyw_device_resume')

    def test_upgrade_record_structure_unchanged(self):
        self.assertIn('id', {f.name for f in UpgradeRecord._meta.fields})
        # 表名与关键查询字段保持
        field_names = {f.name for f in UpgradeRecord._meta.fields}
        self.assertIn('status', field_names)
        self.assertIn('system', field_names)
        self.assertIn('upgrade_type', field_names)
        self.assertEqual(UpgradeRecord._meta.db_table, 'tdyw_upgrade_records')

    def test_no_new_migrations_in_frozen_apps(self):
        """device/upgrade 迁移集合保持基线（步骤一清理后的现状），未因本步骤新增。"""
        import os
        import apps.device.models as device_models
        import apps.upgrade.models as upgrade_models
        device_dir = os.path.join(os.path.dirname(os.path.abspath(device_models.__file__)), 'migrations')
        upgrade_dir = os.path.join(os.path.dirname(os.path.abspath(upgrade_models.__file__)), 'migrations')
        device_files = sorted(f for f in os.listdir(device_dir)
                              if f.endswith('.py') and f != '__init__.py')
        upgrade_files = sorted(f for f in os.listdir(upgrade_dir)
                               if f.endswith('.py') and f != '__init__.py')
        self.assertEqual(
            device_files,
            sorted(['0001_initial.py', '0002_fix_responsible_user_id_null.py',
                    '0003_fix_related_user_id_null.py',
                    '0004_device_sn_tenant_unique_and_choices.py', '0005_evidence_fields.py',
                    '0006_alter_deviceresume_is_deleted.py',
                    '0007_alter_deviceevent_id_alter_deviceresume_id.py',
                    '0008_alter_deviceevent_corrected_at_and_more.py',
                    '0009_deviceevent_device_event_type_valid_and_more.py',
                    '0010_remove_null_from_string_fields.py']),
            'device 迁移集合发生变化')
        self.assertEqual(len(upgrade_files), 21, 'upgrade 迁移数量发生变化')

    def test_old_fault_app_removed(self):
        from django.apps import apps
        self.assertFalse(apps.is_installed('apps.fault'))
        with connection.cursor() as c:
            c.execute("SHOW TABLES LIKE 'tdyw\\_fault%'")
            self.assertEqual(list(c.fetchall()), [], '旧故障表仍存在')

    def test_new_data_only_in_equipment_lifecycle_tables(self):
        admin = make_user('iso_admin', tenant_id='iso_t', is_supper=True)
        system = make_system(admin, tenant_id='iso_t')
        with connection.cursor() as c:
            c.execute("SELECT COUNT(*) FROM tdyw_el_systems WHERE id=%s", [system.id])
            self.assertEqual(c.fetchone()[0], 1)
            c.execute("SELECT COUNT(*) FROM tdyw_device_resume WHERE device_sn=%s",
                      [system.system_code])
            self.assertEqual(c.fetchone()[0], 0)
