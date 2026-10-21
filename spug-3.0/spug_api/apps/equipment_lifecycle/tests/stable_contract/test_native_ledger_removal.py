# -*- coding: utf-8 -*-
"""原生维护台账路线下线契约测试（2026-10-20 整体移除）。

覆盖真实行为契约（真实 HTTP + 隔离测试数据库 + 数据库结构断言）：
1. 原生 API 路由不再注册：/native-templates/*、/native-ledgers/* 全部端点
   ——URLconf 真实解析抛 Resolver404，认证用户真实请求一律 404；
2. 退役模型与表：OperationLedgerNativeTemplate/Version/Record 不再注册，
   三张原生业务表已由迁移 0026 从数据库删除（introspection 实查）；
3. created_from 值域收窄 CHECK 生效：直写 native_template 被数据库拒绝，
   manual 正常写入（真实 INSERT 行为，非源码断言）；
4. Excel / 手工台账不受影响：手工补录真实创建后统一列表可见；
5. 角色权限残留清理函数真实行为：lab.native_ledger 权限串被移除且
   perms_version 自增（直接执行迁移 0026 的清理函数）。
"""
import importlib.util
import json
import os

from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import Resolver404, resolve

from apps.account.models import Role
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX, make_client, make_system,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    LEDGER_URL, create_ledger_ok, entry_payload, item_payload, ledger_payload,
    make_ledger_user,
)

REMOVED_ROUTES = [
    # 原生模板
    URL_PREFIX + '/native-templates/',
    URL_PREFIX + '/native-templates/available/',
    URL_PREFIX + '/native-templates/1/',
    URL_PREFIX + '/native-templates/1/deactivate/',
    URL_PREFIX + '/native-templates/1/draft/',
    URL_PREFIX + '/native-templates/1/publish/',
    URL_PREFIX + '/native-templates/1/versions/',
    URL_PREFIX + '/native-templates/1/versions/1/',
    # 原生台账
    URL_PREFIX + '/native-ledgers/',
    URL_PREFIX + '/native-ledgers/1/',
    URL_PREFIX + '/native-ledgers/1/complete/',
    URL_PREFIX + '/native-ledgers/1/correct/',
    URL_PREFIX + '/native-ledgers/1/export/pdf/',
]

REMOVED_MODELS = [
    'OperationLedgerNativeTemplate',
    'OperationLedgerNativeTemplateVersion',
    'OperationLedgerNativeRecord',
]


def _load_migration_module():
    """按文件路径加载迁移 0026 模块（执行真实代码路径）。"""
    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'migrations', '0026_retire_native_ledger_route.py')
    spec = importlib.util.spec_from_file_location(
        'el_migration_0026_retire_native_ledger_route', migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeLedgerRemovalContractTest(TestCase):
    """原生路线下线后的路由/模型/表/约束契约。"""

    def setUp(self):
        self.user = make_ledger_user()
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def test_removed_routes_unresolved(self):
        """原生路由不再注册：URLconf 解析一律抛 Resolver404。"""
        for url in REMOVED_ROUTES:
            with self.assertRaises(Resolver404, msg=url):
                resolve(url)

    def test_removed_routes_http_404(self):
        """认证用户真实请求原生端点一律 404。"""
        for url in REMOVED_ROUTES:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, url)

    def test_native_models_unregistered(self):
        """三张原生模型不再注册。"""
        config = apps.get_app_config('equipment_lifecycle')
        for name in REMOVED_MODELS:
            with self.assertRaises(LookupError, msg=name):
                config.get_model(name)

    def test_native_tables_dropped(self):
        """三张原生业务表已从数据库删除（introspection 实查）。"""
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names(cursor)
        leftovers = [t for t in tables if t.startswith('tdyw_el_ledger_native')]
        self.assertEqual(leftovers, [])

    def test_created_from_check_narrowed(self):
        """created_from 收窄 CHECK 生效：native_template 直写被数据库拒绝。"""
        from apps.equipment_lifecycle.models import OperationLedger
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperationLedger.objects.create(
                    ledger_no='EL-WM-20261020-9999',
                    ledger_type='week_month',
                    created_from='native_template',
                    created_by=self.user,
                    tenant_id=self.user.tenant_id,
                )
        # manual 仍可正常写入（同一路径的对照行为）
        ledger = OperationLedger.objects.create(
            ledger_no='EL-WM-20261020-9998',
            ledger_type='week_month',
            created_from='manual',
            created_by=self.user,
            tenant_id=self.user.tenant_id,
        )
        self.assertEqual(ledger.created_from, 'manual')

    def test_manual_ledger_still_works(self):
        """Excel/手工台账不受影响：手工补录创建后统一列表真实可见。"""
        from apps.equipment_lifecycle.models import OperationLedger
        create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system.id, [item_payload()])]))
        self.assertEqual(
            OperationLedger.objects.filter(created_from='manual').count(), 1)
        response = self.client.get(LEDGER_URL + '/', {'ledger_type': 'week_month'})
        data = response.json()
        self.assertEqual(data['error'], '')
        self.assertEqual(data['data']['total'], 1)

    def test_role_perms_cleanup_function(self):
        """迁移 0026 权限清理函数真实行为：lab.native_ledger 被移除且版本自增。"""
        cleanup = _load_migration_module().cleanup_lab_native_ledger_perms
        # created_by 传入：全新重放的库上 roles.created_by_id 列存在与
        # users.created_by 同源的 NOT NULL 历史遗留（0012 仅修复了 users）
        role = Role.objects.create(
            name='退役前角色',
            created_by=self.user,
            page_perms='{"lab": {"native_ledger": ["view"]}, '
                       '"equipment_lifecycle": {"ledger": ["view"]}}',
            perms_version=3,
        )
        cleanup(apps, None)
        role.refresh_from_db()
        perms = json.loads(role.page_perms)
        self.assertNotIn('lab', perms)
        self.assertEqual(perms.get('equipment_lifecycle', {}).get('ledger'), ['view'])
        self.assertEqual(role.perms_version, 4)
        # 幂等：再次执行不再变化
        cleanup(apps, None)
        role.refresh_from_db()
        self.assertEqual(role.perms_version, 4)
        self.assertNotIn('lab', json.loads(role.page_perms))


class NativeLedgerRetireFunctionTest(TransactionTestCase):
    """迁移 0026 数据清理函数的真实行为（需要 DDL 播种，用事务外测试）。

    迁移执行时序中，清数函数运行于 三表删除之前、created_from 收窄之前。
    本测试以 schema_editor 按 0025 时刻的历史模型重建三张原生表（与迁移
    CreateModel 同一执行路径），播种存量数据后执行迁移模块中的同一清数
    函数，随后清表恢复迁移后 schema。DDL 会隐式提交，须用事务外测试。
    """

    def setUp(self):
        self.user = make_ledger_user()
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def _historical_apps(self):
        """渲染 0025 时刻（0026 之前）的迁移状态模型。"""
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        return executor.loader.project_state([
            ('account', '0014_remove_tenant_is_active'),
            ('equipment_lifecycle', '0025_config_category_and_baseline'),
        ]).apps

    def test_data_retire_function_cleans_only_native(self):
        """仅清理原生数据；Excel 模板与手工台账原样保留。"""
        module = _load_migration_module()
        from apps.equipment_lifecycle.excel_models import (
            OperationLedgerExcelTemplate,
        )
        from apps.equipment_lifecycle.models import OperationLedger

        # 手工台账（真实 API）
        create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system.id, [item_payload()])]))
        # Excel 模板行（清数函数不得波及）
        template = OperationLedgerExcelTemplate.objects.create(
            name='保留的Excel模板', ledger_type='week_month',
            created_by=self.user, tenant_id=self.user.tenant_id)

        historical = self._historical_apps()
        NativeTemplate = historical.get_model(
            'equipment_lifecycle', 'OperationLedgerNativeTemplate')
        NativeVersion = historical.get_model(
            'equipment_lifecycle', 'OperationLedgerNativeTemplateVersion')
        NativeRecord = historical.get_model(
            'equipment_lifecycle', 'OperationLedgerNativeRecord')
        historical_user = historical.get_model('account', 'User').objects.get(
            pk=self.user.id)

        def _drop_native_tables():
            with connection.schema_editor(atomic=False) as editor:
                editor.delete_model(NativeRecord)
                editor.delete_model(NativeVersion)
                editor.delete_model(NativeTemplate)

        # 按 0025 时刻历史模型重建三张原生表（外键方向：模板 → 版本 → 记录）
        with connection.schema_editor(atomic=False) as editor:
            editor.create_model(NativeTemplate)
            editor.create_model(NativeVersion)
            editor.create_model(NativeRecord)
        try:
            native_template = NativeTemplate.objects.create(
                name='待清理原生模板', ledger_type='week_month',
                created_by=historical_user, tenant_id=self.user.tenant_id)
            native_version = NativeVersion.objects.create(
                template=native_template, version_no=1,
                template_name_snapshot=native_template.name,
                snapshot='{}', bindings='[]', field_count=1,
                published_by=historical_user, tenant_id=self.user.tenant_id)
            # 摘除收窄 CHECK 还原"清数先于收窄"的迁移前置状态
            with connection.schema_editor(atomic=False) as editor:
                editor.remove_constraint(
                    OperationLedger, module.NARROWED_CREATED_FROM_CHECK)
            try:
                native_ledger = OperationLedger.objects.create(
                    ledger_no='EL-WM-20261020-9001',
                    ledger_type='week_month',
                    created_from='native_template',
                    created_by=self.user,
                    tenant_id=self.user.tenant_id)
                NativeRecord.objects.create(
                    ledger_id=native_ledger.id, version=native_version,
                    values='{}', tenant_id=self.user.tenant_id)
                # 更正记录（PROTECT 于台账，须先于台账清理）
                historical.get_model(
                    'equipment_lifecycle', 'OperationLedgerCorrection').objects.create(
                    ledger_id=native_ledger.id, reason='原生更正待清理',
                    corrected_by=historical_user, tenant_id=self.user.tenant_id)
                module.retire_native_ledger_data(historical, None)
            finally:
                with connection.schema_editor(atomic=False) as editor:
                    editor.add_constraint(
                        OperationLedger, module.NARROWED_CREATED_FROM_CHECK)
            # 原生数据四类均清零（表尚未物理删除的迁移中间态，行级断言）
            self.assertEqual(NativeTemplate.objects.count(), 0)
            self.assertEqual(NativeVersion.objects.count(), 0)
            self.assertEqual(NativeRecord.objects.count(), 0)
            self.assertEqual(
                historical.get_model(
                    'equipment_lifecycle', 'OperationLedgerCorrection'
                ).objects.filter(ledger_id=native_ledger.id).count(), 0)
        finally:
            _drop_native_tables()
        self.assertEqual(
            OperationLedger.objects.filter(created_from='native_template').count(), 0)
        self.assertEqual(
            OperationLedger.objects.filter(created_from='manual').count(), 1)
        self.assertEqual(
            OperationLedger.objects.filter(created_from='excel_template').count(), 0)
        # Excel 模板行不受清理影响
        self.assertTrue(
            OperationLedgerExcelTemplate.objects.filter(pk=template.pk).exists())
        # CHECK 已恢复：原生值仍被数据库拒绝（迁移后常态）
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OperationLedger.objects.create(
                    ledger_no='EL-WM-20261020-9002',
                    ledger_type='week_month',
                    created_from='native_template',
                    created_by=self.user,
                    tenant_id=self.user.tenant_id)