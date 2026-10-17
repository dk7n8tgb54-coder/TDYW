# -*- coding: utf-8 -*-
"""系统履历退役 + 旧故障/运行记录模块退役契约测试（2026-10-11 合并改造）。

覆盖真实行为契约（真实 HTTP + 隔离测试数据库 + 数据库结构断言）：
1. 旧模块路由全部不再注册：/faults/*、/runtime-records/*（含待办/统计/
   附件/转故障等）、/system-events/*、/system-event-groups/*、
   /systems/<pk>/system-events/、/systems/<pk>/faults/、
   /systems/<pk>/runtime-records/、/faults/<pk>/close/ 废弃端点——
   认证用户真实请求一律 404；
2. 退役模型与表：SystemEvent/SystemFault/SystemFaultHandlingRecord/
   SystemRuntimeRecord/SystemRuntimeRecordProgress 不再注册，
   对应五张旧表与状态归一备份表已由迁移删除，新统一表在位；
3. 履历不再产生新数据：设备故障创建、台账异常转故障、升级记录创建/
   完成回退、配置变更应用/回退后，无任何履历写入路径
   （SystemEvent 模型已不存在，无法写入——以路由与模型注册断言收口）；
4. 统一记录不写任何履历表（新表 only：写路径只落 tdyw_el_operation_record）；
5. 退役业务数据的附件数据库行已清理（el_fault_handling/el_runtime_record）。
"""
from django.apps import apps
from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, RECORDS_URL, URL_PREFIX,
    make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, make_full_ledger,
)

REMOVED_ROUTES = [
    # 旧故障处置模块
    ('get', URL_PREFIX + '/faults/'),
    ('post', URL_PREFIX + '/faults/'),
    ('get', URL_PREFIX + '/faults/export/'),
    ('get', URL_PREFIX + '/faults/candidate-systems/'),
    ('get', URL_PREFIX + '/faults/1/'),
    ('put', URL_PREFIX + '/faults/1/'),
    ('post', URL_PREFIX + '/faults/1/recover/'),
    ('post', URL_PREFIX + '/faults/1/close/'),
    ('put', URL_PREFIX + '/faults/1/reason-analysis/'),
    ('post', URL_PREFIX + '/faults/1/cancel/'),
    ('get', URL_PREFIX + '/faults/1/handling-records/'),
    ('post', URL_PREFIX + '/faults/1/handling-records/'),
    ('put', URL_PREFIX + '/faults/1/handling-records/2/'),
    ('get', URL_PREFIX + '/faults/1/handling-records/2/attachments/'),
    ('get', URL_PREFIX + '/systems/1/faults/'),
    # 旧运行记录模块
    ('get', URL_PREFIX + '/runtime-records/'),
    ('post', URL_PREFIX + '/runtime-records/'),
    ('get', URL_PREFIX + '/runtime-records/1/'),
    ('put', URL_PREFIX + '/runtime-records/1/'),
    ('delete', URL_PREFIX + '/runtime-records/1/'),
    ('get', URL_PREFIX + '/runtime-records/1/progress/'),
    ('post', URL_PREFIX + '/runtime-records/1/progress/'),
    ('put', URL_PREFIX + '/runtime-records/1/progress/2/'),
    ('post', URL_PREFIX + '/runtime-records/1/convert-to-fault/'),
    ('post', URL_PREFIX + '/runtime-records/1/resolve/'),
    ('get', URL_PREFIX + '/runtime-records/todo/'),
    ('get', URL_PREFIX + '/runtime-records/statistics/'),
    ('get', URL_PREFIX + '/runtime-records/1/attachments/'),
    ('post', URL_PREFIX + '/runtime-records/1/attachments/'),
    ('get', URL_PREFIX + '/systems/1/runtime-records/'),
    # 系统履历
    ('get', URL_PREFIX + '/system-events/'),
    ('get', URL_PREFIX + '/system-events/export/'),
    ('get', URL_PREFIX + '/systems/1/system-events/'),
    ('get', URL_PREFIX + '/system-event-groups/'),
    ('get', URL_PREFIX + '/system-event-groups/nodes/'),
    ('get', URL_PREFIX + '/system-event-groups/export/'),
]

RETIRED_MODELS = [
    'systemevent', 'systemfault', 'systemfaulthandlingrecord',
    'systemruntimerecord', 'systemruntimerecordprogress',
]

RETIRED_TABLES = [
    'tdyw_el_system_event',
    'tdyw_el_fault',
    'tdyw_el_fault_handling_record',
    'tdyw_el_runtime_record',
    'tdyw_el_runtime_record_progress',
    'tdyw_el_runtime_record_status_backfill',
]

NEW_TABLES = ['tdyw_el_operation_record', 'tdyw_el_operation_progress']


def _existing_tables(cursor):
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = DATABASE()")
    return {row[0] for row in cursor.fetchall()}


class RetiredRoutesTest(TestCase):
    """旧模块路由不再注册契约。"""

    def setUp(self):
        self.user = make_user('removal_user', perms=ALL_OPERATION_PERMS + ALL_LEDGER_PERMS)
        self.client = make_client(self.user)

    def test_retired_routes_not_registered(self):
        for method, url in REMOVED_ROUTES:
            res = getattr(self.client, method)(url)
            self.assertEqual(
                res.status_code, 404,
                f'{method.upper()} {url} 应已删除，实际 {res.status_code}')

    def test_retired_models_not_registered(self):
        app_models = {m.__name__.lower() for m in apps.get_app_config(
            'equipment_lifecycle').get_models()}
        for name in RETIRED_MODELS:
            self.assertNotIn(name, app_models)

    def test_new_tables_exist_and_retired_tables_dropped(self):
        with connection.cursor() as cursor:
            tables = _existing_tables(cursor)
        for table in RETIRED_TABLES:
            self.assertNotIn(table, tables, f'{table} 应已由迁移删除')
        for table in NEW_TABLES:
            self.assertIn(table, tables)

    def test_retired_attachment_object_types_cleaned(self):
        """退役业务数据的附件数据库行已清理（迁移 0013）。"""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM tdyw_evidence_attachments "
                "WHERE module='equipment_lifecycle' "
                "AND object_type IN ('el_fault_handling', 'el_runtime_record')")
            count = cursor.fetchone()[0]
        self.assertEqual(count, 0)


class NoEventWritesTest(TestCase):
    """履历不再产生新数据契约：各业务动作后无履历写入路径。

    SystemEvent 模型与写入服务已整体删除——本测试以"动作真实执行成功 +
    模型不再注册 + 履历路由不存在"三重收口；统一记录写路径只落新统一表。
    """

    def setUp(self):
        self.user = make_user(
            'no_event_user',
            perms=ALL_OPERATION_PERMS + ALL_LEDGER_PERMS + [
                'equipment_lifecycle.ledger.handle_exception',
                'upgrade.upgrade.view', 'upgrade.upgrade.add',
                'equipment_lifecycle.config.view',
                'equipment_lifecycle.config.add',
                'equipment_lifecycle.config.apply',
            ])
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def test_fault_create_writes_only_unified_tables(self):
        res = self.client.post(RECORDS_URL + '/', {
            'record_type': 'fault',
            'system': self.system.id,
            'occurred_at': '2026-10-11 08:00',
            'title': '故障登记',
            'description': '故障描述',
            'registrar_name': '张三',
            'affects_system_operation': False,
        }, content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        record = res.json()['data']
        # 记录真实落库
        self.assertTrue(SystemOperationRecordExists(record['id']))
        # 履历模型已删除（写入路径不存在）
        self.assertNotIn('systemevent', {
            m.__name__.lower()
            for m in apps.get_app_config('equipment_lifecycle').get_models()})

    def test_ledger_convert_writes_only_unified_tables(self):
        client = self.client
        detail, system = make_full_ledger(self.user, system=self.system)
        from apps.equipment_lifecycle.models import OperationLedger
        ledger = OperationLedger.objects.get(pk=detail['id'])
        client.post('/equipment-lifecycle/ledgers/%d/complete/' % ledger.id,
                    b'{}', content_type='application/json')
        item = ledger.items.filter(result='abnormal').first()
        res = client.post(
            '/equipment-lifecycle/ledgers/%d/items/%d/convert-to-fault/' % (
                ledger.id, item.id),
            b'{}', content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        # 转换产物为统一主表设备故障，履历模型不存在
        self.assertTrue(SystemOperationRecordExists(res.json()['data']['id']))
        self.assertNotIn('systemevent', {
            m.__name__.lower()
            for m in apps.get_app_config('equipment_lifecycle').get_models()})

    def test_event_write_modules_retired(self):
        """履历写入路径整体退役：旧服务模块不可导入、业务服务无写入函数。

        （运行时导入图断言，非源码文本匹配：模块删除后 import 必然失败，
        业务服务模块 globals 中不存在任何 record_*_event 写入函数。）
        """
        import importlib
        import sys
        for module_name in ('apps.equipment_lifecycle.event_services',
                            'apps.equipment_lifecycle.event_views',
                            'apps.equipment_lifecycle.event_group_services',
                            'apps.equipment_lifecycle.fault_services',
                            'apps.equipment_lifecycle.fault_views',
                            'apps.equipment_lifecycle.runtime_record_services',
                            'apps.equipment_lifecycle.runtime_record_views'):
            module_name in sys.modules and sys.modules.pop(module_name, None)
            try:
                importlib.import_module(module_name)
            except ModuleNotFoundError:
                pass
            else:
                self.fail(f'{module_name} 应已删除')
        from apps.equipment_lifecycle import config_services
        from apps.upgrade.services import record_service, status_log_service
        for module, names in (
                (config_services, ('maybe_record_config_history_event',)),
                (record_service, ('record_upgrade_lifecycle_events',)),
                (status_log_service, ('record_upgrade_lifecycle_events',))):
            for name in names:
                self.assertFalse(hasattr(module, name),
                                 f'{module.__name__}.{name} 应已删除')


def SystemOperationRecordExists(pk):
    from apps.equipment_lifecycle.operation_models import SystemOperationRecord
    return SystemOperationRecord.objects.filter(pk=pk).exists()
