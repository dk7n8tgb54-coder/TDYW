# -*- coding: utf-8 -*-
"""日巡视（值班巡检）活跃功能下线（2026-10-11）稳定契约测试。

覆盖真实行为契约：
1. 巡检模板/巡检单（含导出、批量导出、提交、作废、退回）/候选人员
   全部 API 不再注册：认证用户真实请求一律 404，且不产生任何数据；
2. 历史数据保留：巡检五表仍在库、模型可读写（本下线只摘除活跃功能，
   不删表不清数据；彻底删表需另行评审存量数据/引用量/迁移与回滚方案）；
3. 历史故障兼容展示：以 ORM 构造历史巡检模板/单/明细，并以
   SystemFault.source_inspection_record 外键引用该明细的历史故障，
   故障详情接口仍返回巡检来源追溯字段（单号/值班日期/轮次/检查项）；
4. 历史履历兼容展示：event_type=inspection 的历史事件在按系统履历
   列表接口可查询，事项聚合接口仍接受 source_type=inspection_record
   筛选（不报"不合法"）；
5. 旧巡检台账（ledger_type=inspection）历史兼容保护不受影响——
   由 test_legacy_inspection_removal.py 继续覆盖，本文件不重复。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用；
不修改既有迁移文件、不新增迁移（模型零改动）。
"""
from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    InspectionDutySheet,
    InspectionRecord,
    InspectionTemplate,
    InspectionTemplateDevice,
    InspectionTemplateItem,
    SystemEvent,
    SystemFault,
)
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX, make_client, make_system, make_user,
)

FAULT_URL = URL_PREFIX + '/faults'
EVENTS_UNDER_SYSTEM_URL = URL_PREFIX + '/systems/%d/system-events/'
GROUPS_URL = URL_PREFIX + '/system-event-groups'

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
        """请求已删除端点不产生任何巡检/故障数据。"""
        for method, url in REMOVED_INSPECTION_ROUTES:
            getattr(self.client, method)(url, {}, content_type='application/json')
        self.assertEqual(InspectionTemplate.objects.count(), 0)
        self.assertEqual(InspectionDutySheet.objects.count(), 0)
        self.assertEqual(InspectionRecord.objects.count(), 0)
        self.assertEqual(SystemFault.objects.count(), 0)


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


class InspectionSourceFaultDisplayTest(TestCase):
    """契约 3：历史故障仍可展示巡检来源追溯（外键与快照字段保留）。"""

    def setUp(self):
        self.user = make_user(
            'ins_fault_op', ['equipment_lifecycle.system.view',
                             'equipment_lifecycle.fault.view'],
            tenant_id='tenant_a')
        self.client = make_client(self.user)
        self.system = make_system(self.user, tenant_id='tenant_a')
        # 历史巡检数据（模拟下线前产生的单据）
        template = InspectionTemplate.objects.create(
            name='值班巡检模板', created_by=self.user, tenant_id='tenant_a')
        device = InspectionTemplateDevice.objects.create(
            template=template, device_name='发射机', created_by=self.user,
            tenant_id='tenant_a')
        item = InspectionTemplateItem.objects.create(
            device=device, name='输出功率', input_type='choice',
            tenant_id='tenant_a', created_by=self.user)
        self.sheet = InspectionDutySheet.objects.create(
            sheet_no='XJ20261001-0001', duty_date='2026-10-01',
            template=template, status='submitted',
            uniq_key='2026-10-01|%d' % template.id,
            created_by=self.user, tenant_id='tenant_a')
        self.record = InspectionRecord.objects.create(
            sheet=self.sheet, round_no='r1', template_item=item,
            device_name_snapshot='发射机', item_name_snapshot='输出功率',
            input_type_snapshot='choice', value_text='不正常',
            result='abnormal', abnormal_desc='功率偏低',
            tenant_id='tenant_a')
        # 历史故障：来源巡检明细（外键双向追溯）
        self.fault = SystemFault.objects.create(
            tenant_id='tenant_a', fault_no='GZ20261001-0001',
            system=self.system, impact_status='degraded',
            system_code=self.system.system_code, system_name=self.system.name,
            system_location=self.system.install_location,
            occurred_at='2026-10-01 11:30:00',
            phenomenon='巡检发现输出功率偏低', status='handling',
            source_type='inspection_record', source_id=str(self.record.id),
            source_inspection_record=self.record, created_by=self.user)

    def test_fault_detail_keeps_inspection_trace(self):
        """故障详情仍返回巡检来源追溯字段（页面可继续展示历史来源）。"""
        body = self.client.get(f'{FAULT_URL}/{self.fault.id}/').json()
        self.assertFalse(body.get('error'), body)
        data = body['data']
        self.assertEqual(data['source_type'], 'inspection_record')
        self.assertEqual(data['source_inspection_record'], self.record.id)
        self.assertEqual(data['source_inspection_sheet'], self.sheet.id)
        self.assertEqual(data['source_inspection_sheet_no'], 'XJ20261001-0001')
        self.assertEqual(data['source_inspection_duty_date'], '2026-10-01')
        self.assertEqual(data['source_inspection_round_text'], '11:00-11:20')
        self.assertEqual(data['source_inspection_item_name'], '输出功率')

    def test_foreign_key_protects_history(self):
        """外键为 PROTECT：历史明细不可被误删（追溯链路受数据库约束保护）。"""
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.record.delete()


class InspectionHistoryEventDisplayTest(TestCase):
    """契约 4：历史巡检履历事件仍可查询展示。"""

    def setUp(self):
        self.user = make_user(
            'ins_event_op',
            ['equipment_lifecycle.system.view',
             'equipment_lifecycle.system_event.view'],
            tenant_id='tenant_a')
        self.client = make_client(self.user)
        self.system = make_system(self.user, tenant_id='tenant_a')
        SystemEvent.objects.create(
            tenant_id='tenant_a', system=self.system,
            event_type='inspection', action='convert_to_fault',
            source_type='inspection_record', source_id='99',
            source_no='XJ20260901-0001', title='巡检异常转故障',
            detail='{}', system_code=self.system.system_code,
            system_name=self.system.name, occurred_at='2026-09-01 11:00:00',
            created_by=self.user)

    def test_system_events_list_shows_inspection_history(self):
        """按系统履历列表接口仍返回 inspection 类型历史事件。"""
        body = self.client.get(EVENTS_UNDER_SYSTEM_URL % self.system.id).json()
        self.assertFalse(body.get('error'), body)
        rows = body['data']['data']
        inspection_rows = [r for r in rows if r['event_type'] == 'inspection']
        self.assertEqual(len(inspection_rows), 1)
        self.assertEqual(inspection_rows[0]['source_no'], 'XJ20260901-0001')

    def test_event_group_filter_accepts_inspection_source(self):
        """事项聚合接口仍接受 source_type=inspection_record 筛选（历史来源值域保留）。"""
        body = self.client.get(
            GROUPS_URL + '/', {'source_type': 'inspection_record'}).json()
        self.assertFalse(body.get('error'), body)
        # 全局分组接口以系统为行返回（json_response 双层 data 包装）；
        # 有巡检事件的系统出现在结果中
        groups = body['data']['data']
        system_ids = [row['system']['id'] for row in groups]
        self.assertIn(self.system.id, system_ids)
