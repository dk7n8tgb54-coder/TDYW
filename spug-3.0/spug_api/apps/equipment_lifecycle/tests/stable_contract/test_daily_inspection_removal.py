# -*- coding: utf-8 -*-
"""日巡视（值班巡检）活跃功能下线（2026-10-11）稳定契约测试。

覆盖真实行为契约：
1. 巡检模板/巡检单（含导出、批量导出、提交、作废、退回）/候选人员
   全部 API 不再注册：认证用户真实请求一律 404，且不产生任何数据；
2. 历史数据保留：巡检五表仍在库、模型可读写（本下线只摘除活跃功能，
   不删表不清数据；彻底删表需另行评审存量数据/引用量/迁移与回滚方案）；
3. 旧巡检台账（ledger_type=inspection）历史兼容保护不受影响——
   由 test_legacy_inspection_removal.py 继续覆盖，本文件不重复。

（2026-10-11 合并改造追加说明：原第 3/4 项"历史故障兼容展示/历史履历
兼容展示"已随运行与故障记录合并改造退役——SystemFault 旧表与 SystemEvent
履历表由迁移 0013 删除，故障上的 source_inspection_record 外键随之消失，
巡检历史仅以巡检五表自身保留，相关契约断言同步移除。）
"""
from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    InspectionDutySheet,
    InspectionRecord,
    InspectionTemplate,
    InspectionTemplateDevice,
    InspectionTemplateItem,
)
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

INSPECTION_TABLES = (
    'tdyw_el_inspection_template',
    'tdyw_el_inspection_template_device',
    'tdyw_el_inspection_template_item',
    'tdyw_el_inspection_sheet',
    'tdyw_el_ins_sheet_person',
    'tdyw_el_inspection_record',
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
        """请求已删除端点不产生任何巡检/统一记录数据。"""
        for method, url in REMOVED_INSPECTION_ROUTES:
            getattr(self.client, method)(url, {}, content_type='application/json')
        self.assertEqual(InspectionTemplate.objects.count(), 0)
        self.assertEqual(InspectionDutySheet.objects.count(), 0)
        self.assertEqual(InspectionRecord.objects.count(), 0)
        self.assertEqual(SystemOperationRecord.objects.count(), 0)


class InspectionHistoryPreservedTest(TestCase):
    """契约 2：历史数据保留（表仍在库，模型可读写）。"""

    def test_inspection_tables_still_exist(self):
        """巡检五表不随活跃功能下线删表（历史数据保留）。"""
        with connection.cursor() as cursor:
            for table in INSPECTION_TABLES:
                cursor.execute("SHOW TABLES LIKE %s", [table])
                self.assertIsNotNone(cursor.fetchone(), table)

    def test_models_still_readable_and_writable(self):
        """历史巡检数据可正常读写（模型保留，服务层下线不影响 ORM 访问）。"""
        user = make_user('ins_hist_op', ['equipment_lifecycle.system.view'])
        template = InspectionTemplate.objects.create(
            name='历史模板', created_by=user, tenant_id='tenant_a')
        device = InspectionTemplateDevice.objects.create(
            template=template, device_name='发射机', created_by=user,
            tenant_id='tenant_a')
        item = InspectionTemplateItem.objects.create(
            device=device, name='面板指示灯', input_type='choice',
            tenant_id='tenant_a', created_by=user)
        self.assertEqual(
            InspectionTemplate.objects.get(pk=template.id).name, '历史模板')
        self.assertEqual(item.device.template_id, template.id)
