# -*- coding: utf-8 -*-
"""日巡视（值班巡检）功能下线（2026-10-11）与历史表退役（2026-10-14）稳定契约测试。

覆盖真实行为契约：
1. 巡检模板/巡检单（含导出、批量导出、提交、作废、退回）/候选人员
   全部 API 不再注册：认证用户真实请求一律 404，且不产生任何数据；
2. 历史表与模型已退役（迁移 0017，2026-10-14，经存量数据/引用量/
   备份与回滚方案评审后授权执行）：巡检六表与旧设计器两表不再存在于
   数据库，八个模型类不再注册；
3. 旧巡检台账（ledger_type=inspection）历史兼容保护不受影响——
   由 test_legacy_inspection_removal.py 继续覆盖，本文件不重复。

（2026-10-11 合并改造追加说明：原第 3/4 项"历史故障兼容展示/历史履历
兼容展示"已随运行处置记录合并改造退役——SystemFault 旧表与 SystemEvent
履历表由迁移 0013 删除，故障上的 source_inspection_record 外键随之消失，
巡检历史仅以巡检五表自身保留，相关契约断言同步移除。）
"""
from django.apps import apps
from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle.operation_models import SystemOperationRecord
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX, make_client, make_system, make_user,
)

# 已删除的日巡视路由（活跃 API 不再注册契约）
REMOVED_INSPECTION_ROUTES = [
    ('get', '/equipment-lifecycle/inspection-templates/'),
    ('post', '/equipment-lifecycle/inspection-templates/'),
    ('get', '/equipment-lifecycle/inspection-templates/available/'),
    ('get', '/equipment-lifecycle/inspection-templates/1/'),
    ('put', '/equipment-lifecycle/inspection-templates/1/'),
    ('post', '/equipment-lifecycle/inspection-templates/1/active/'),
    ('get', '/equipment-lifecycle/inspection-sheets/'),
    ('post', '/equipment-lifecycle/inspection-sheets/'),
    ('get', '/equipment-lifecycle/inspection-sheets/export/'),
    ('get', '/equipment-lifecycle/inspection-sheets/batch-export/xlsx/'),
    ('get', '/equipment-lifecycle/inspection-sheets/batch-export/pdf/'),
    ('get', '/equipment-lifecycle/inspection-sheets/1/'),
    ('get', '/equipment-lifecycle/inspection-sheets/1/export/xlsx/'),
    ('get', '/equipment-lifecycle/inspection-sheets/1/export/pdf/'),
    ('post', '/equipment-lifecycle/inspection-sheets/1/submit/'),
    ('post', '/equipment-lifecycle/inspection-sheets/1/void/'),
    ('post', '/equipment-lifecycle/inspection-sheets/1/return/'),
    # 候选人员端点（原服务今日巡检值班人员登记，工单下线后无其他调用方）
    ('get', '/equipment-lifecycle/candidate-users/'),
]

# 已退役的历史表（巡检六表 + 旧台账设计器两表，迁移 0017 DeleteModel）
RETIRED_TABLES = (
    'tdyw_el_inspection_template',
    'tdyw_el_inspection_template_device',
    'tdyw_el_inspection_template_item',
    'tdyw_el_inspection_sheet',
    'tdyw_el_ins_sheet_person',
    'tdyw_el_inspection_record',
    'tdyw_el_ledger_layout_template',
    'tdyw_el_ledger_layout_version',
)

# 已退役的模型类（与 RETIRED_TABLES 一一对应，不再注册）
RETIRED_MODELS = (
    'InspectionTemplate', 'InspectionTemplateDevice', 'InspectionTemplateItem',
    'InspectionDutySheet', 'InspectionDutyPerson', 'InspectionRecord',
    'OperationLedgerLayoutTemplate', 'OperationLedgerLayoutVersion',
)


class InspectionApiRemovedTest(TestCase):
    """契约 1：日巡视全部 API 不再注册。"""

    def setUp(self):
        # 授予原日巡视专属权限也无济于事：路由已注销，URL 解析即 404
        self.user = make_user(
            'ins_removed_op',
            ['equipment_lifecycle.inspection.view',
             'equipment_lifecycle.inspection_template.view',
             'equipment_lifecycle.inspection.export',
             'equipment_lifecycle.system.view'])
        self.client = make_client(self.user)

    def test_inspection_endpoints_return_404(self):
        """巡检模板/巡检单/导出/候选人员端点 404（路由已删除）。"""
        for method, url in REMOVED_INSPECTION_ROUTES:
            resp = getattr(self.client, method)(url, {}, content_type='application/json')
            self.assertEqual(resp.status_code, 404, f'{method} {url}: {resp.content}')

    def test_removal_creates_no_data(self):
        """请求已删除端点不产生任何统一记录数据。"""
        for method, url in REMOVED_INSPECTION_ROUTES:
            getattr(self.client, method)(url, {}, content_type='application/json')
        self.assertEqual(SystemOperationRecord.objects.count(), 0)


class InspectionLayoutTablesRetiredTest(TestCase):
    """契约 2：巡检六表与旧设计器两表已随迁移 0017 物理退役。"""

    def test_retired_tables_no_longer_exist(self):
        """八张退役表不再存在于数据库（迁移 0017 DeleteModel 已应用）。"""
        with connection.cursor() as cursor:
            for table in RETIRED_TABLES:
                cursor.execute("SHOW TABLES LIKE %s", [table])
                self.assertIsNone(cursor.fetchone(), table)

    def test_retired_models_no_longer_registered(self):
        """八个退役模型类不再注册（业务代码不存在任何访问路径）。"""
        app_config = apps.get_app_config('equipment_lifecycle')
        for model_name in RETIRED_MODELS:
            with self.assertRaises(LookupError, msg=model_name):
                app_config.get_model(model_name)
