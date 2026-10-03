# -*- coding: utf-8 -*-
"""模块边界回归（步骤二）：upgrade 不受影响，旧 fault / 旧 device 保持移除。

以真实模型行为验证（非源码字符串匹配）：
- UpgradeRecord 核心字段与表名不变；
- upgrade 没有产生新迁移；
- 旧 fault / 旧 device 应用不再注册、旧表不再存在；
- 新模块数据只落在 equipment_lifecycle 新表。
"""
from django.db import connection

from django.test import TestCase

from apps.upgrade.models import UpgradeRecord
from apps.equipment_lifecycle.models import LifecycleSystem

from apps.equipment_lifecycle.tests.base import (
    make_client, make_system, make_user,
)


class ModuleIsolationTest(TestCase):
    UPGRADE_SNAPSHOT_FIELDS = {'id': 'AutoField'}

    def test_upgrade_record_structure_unchanged(self):
        self.assertIn('id', {f.name for f in UpgradeRecord._meta.fields})
        # 表名与关键查询字段保持
        field_names = {f.name for f in UpgradeRecord._meta.fields}
        self.assertIn('status', field_names)
        self.assertIn('system', field_names)
        self.assertIn('upgrade_type', field_names)
        self.assertEqual(UpgradeRecord._meta.db_table, 'tdyw_upgrade_records')

    def test_no_new_migrations_in_frozen_apps(self):
        """upgrade 迁移集合保持基线，未因后续步骤新增。"""
        import os
        import apps.upgrade.models as upgrade_models
        upgrade_dir = os.path.join(os.path.dirname(os.path.abspath(upgrade_models.__file__)), 'migrations')
        upgrade_files = sorted(f for f in os.listdir(upgrade_dir)
                               if f.endswith('.py') and f != '__init__.py')
        # 2026-09 升级管理挂接系统档案新增 0022（UpgradeRecord/Template 挂
        # LifecycleSystem 外键并删除升级系统字典表），基线由 21 更新为 22；
        # 2026-10 升级编号回归新增 0023（upgrade_no 加列+历史回填+唯一约束），
        # 基线由 22 更新为 23
        self.assertEqual(len(upgrade_files), 23, 'upgrade 迁移数量发生变化')

    def test_old_fault_app_removed(self):
        from django.apps import apps
        self.assertFalse(apps.is_installed('apps.fault'))
        with connection.cursor() as c:
            c.execute("SHOW TABLES LIKE 'tdyw\\_fault%'")
            self.assertEqual(list(c.fetchall()), [], '旧故障表仍存在')

    def test_old_device_app_removed(self):
        """2026-09 设备管理模块下线：应用注销、旧表随 0037 迁移删除。"""
        from django.apps import apps
        self.assertFalse(apps.is_installed('apps.device'))
        with connection.cursor() as c:
            c.execute("SHOW TABLES LIKE 'tdyw\\_device%'")
            self.assertEqual(list(c.fetchall()), [], '旧设备表仍存在')

    def test_new_data_only_in_equipment_lifecycle_tables(self):
        admin = make_user('iso_admin', tenant_id='iso_t', is_supper=True)
        system = make_system(admin, tenant_id='iso_t')
        with connection.cursor() as c:
            c.execute("SELECT COUNT(*) FROM tdyw_el_systems WHERE id=%s", [system.id])
            self.assertEqual(c.fetchone()[0], 1)
