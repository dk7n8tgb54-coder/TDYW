# -*- coding: utf-8 -*-
"""原生维护台账路线下线契约测试（2026-10-20 整体移除；2026-10-24 基线重建改版）。

覆盖真实行为契约（真实 HTTP + 隔离测试数据库 + 数据库结构断言）：
1. 原生 API 路由不再注册：/native-templates/*、/native-ledgers/* 全部端点
   ——URLconf 真实解析抛 Resolver404，认证用户真实请求一律 404；
2. 退役模型与表：OperationLedgerNativeTemplate/Version/Record 不再注册，
   三张原生业务表在新迁移基线下从不创建（introspection 实查）；
3. created_from 值域收窄 CHECK 生效：直写 native_template 被数据库拒绝，
   manual 正常写入（真实 INSERT 行为，非源码断言）；
4. Excel / 手工台账不受影响：手工补录真实创建后统一列表可见。

历史说明：2026-10-20 版本曾直接执行旧迁移 0026 模块的清数/权限清理函数
（MigrationExecutor 时间点播种）验证退役过程；2026-10-24 迁移基线重建后
0002-0029 已删除（EL 未上线，历史数据逻辑不入基线），同类契约改由
test_migration_baseline.py 以"基线从不创建退役对象"的更强断言承载。
"""
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import Resolver404, resolve

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
        """三张原生业务表在新基线库中不存在（introspection 实查）。"""
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