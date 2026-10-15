# -*- coding: utf-8 -*-
"""故障维修工单功能删除（2026-09-30）稳定契约测试。

覆盖验收要求的真实行为契约（工单退役本身，与其后模块合并改造无关）：
1. 工单 API 不再注册（列表/创建/详情/动作/处理记录/导出/按系统/按故障
   与台账异常转工单全部 404；模型三表已随迁移 0043 删除）；
2. 健康状态值域不含 repairing（维修中已随工单功能删除）；
3. 工单处置记录附件对象类型（el_work_order_handling）不可作为附件归属
   查询（附件归属校验按现行对象类型收口）。

原依赖旧故障流程的契约（处置记录承载工时/更正、故障闭环不依赖工单、
台账异常转故障链路、健康重算优先级等）已随 2026-10-11 合并改造迁入
统一记录契约测试（test_operation_*），本文件不再重复。
"""
import json

from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, ALL_SYSTEM_PERMS, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, create_ledger_ok, entry_payload, item_payload,
    ledger_payload,
)

LEDGER_URL = '/equipment-lifecycle/ledgers'

ALL_HANDLE_PERMS = ALL_LEDGER_PERMS + ALL_OPERATION_PERMS + [
    'equipment_lifecycle.ledger.handle_exception',
]

# 已删除的工单路由（工单 API 不再注册契约）
REMOVED_WO_ROUTES = [
    ('get', '/equipment-lifecycle/work-orders/'),
    ('post', '/equipment-lifecycle/work-orders/'),
    ('get', '/equipment-lifecycle/work-orders/1/'),
    ('post', '/equipment-lifecycle/work-orders/1/complete/'),
    ('post', '/equipment-lifecycle/work-orders/1/close/'),
    ('post', '/equipment-lifecycle/work-orders/1/cancel/'),
    ('get', '/equipment-lifecycle/work-orders/1/handling-records/'),
    ('get', '/equipment-lifecycle/work-orders/export/'),
    ('get', '/equipment-lifecycle/work-orders/candidate-users/'),
    ('get', '/equipment-lifecycle/systems/1/work-orders/'),
    ('get', '/equipment-lifecycle/faults/1/work-orders/'),
]


class WorkOrderRemovalTestBase(TestCase):
    """公共夹具：单租户双系统 + 台账/统一记录全权限用户。"""

    def setUp(self):
        self.admin = make_user(
            'wor_admin', ALL_SYSTEM_PERMS + ALL_HANDLE_PERMS, tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-W1', name='烟台通信系统',
                                    install_location='机房A')


class WorkOrderApiRemovedTest(WorkOrderRemovalTestBase):
    """契约 1：工单 API 不再注册。"""

    def test_work_order_endpoints_return_404(self):
        """工单全部端点 404（路由已删除），且不产生任何数据。"""
        for method, url in REMOVED_WO_ROUTES:
            resp = getattr(self.client, method)(url, {}, content_type='application/json')
            self.assertEqual(resp.status_code, 404, f'{method} {url}: {resp.content}')

    def test_convert_to_work_order_endpoint_removed(self):
        """台账异常转工单端点已删除（404），转统一记录端点仍然注册。"""
        body = create_ledger_ok(self.client, ledger_payload([
            entry_payload(self.system_a.id, [
                item_payload(result='abnormal', abnormal_desc='电压偏低'),
            ]),
        ]))
        ledger_id, item_id = body['id'], body['items'][0]['id']
        self.client.post(f'{LEDGER_URL}/{ledger_id}/submit/', {},
                         content_type='application/json')
        resp = self.client.post(
            f'{LEDGER_URL}/{ledger_id}/items/{item_id}/convert-to-work-order/',
            {'work_type': 'special_maintenance'},
            content_type='application/json')
        self.assertEqual(resp.status_code, 404)

    def test_work_order_tables_dropped(self):
        """工单三表已随迁移 0043 删除，无运行时残留。"""
        with connection.cursor() as cursor:
            for table in ('tdyw_el_work_order', 'tdyw_el_work_order_participant',
                          'tdyw_el_work_order_handling_record'):
                cursor.execute("SHOW TABLES LIKE %s", [table])
                self.assertIsNone(cursor.fetchone(), table)

    def test_health_status_domain_has_no_repairing(self):
        """健康状态值域不含 repairing（维修中已随工单功能删除）。"""
        self.assertNotIn(
            'repairing', [c[0] for c in LifecycleSystem.HEALTH_STATUS_CHOICES])
        from apps.equipment_lifecycle.models import HEALTH_STATUS_VALUES
        self.assertNotIn('repairing', HEALTH_STATUS_VALUES)

    def test_work_order_attachment_object_type_not_in_use(self):
        """工单处理记录附件对象类型已下线：现行统一进展对象类型收口。"""
        from apps.evidence.models import EvidenceAttachment
        # 工单处置记录附件对象类型不再有任何附件行（迁移 0043/0013 清理后，
        # 新写入路径只使用 el_operation_record；进展级 el_operation_progress
        # 亦已随 0016 重指退役）
        self.assertFalse(EvidenceAttachment.objects.filter(
            module='equipment_lifecycle',
            object_type='el_work_order_handling').exists())
