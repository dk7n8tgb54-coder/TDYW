# -*- coding: utf-8 -*-
"""巡检异常处置稳定契约（巡检转故障功能下线后）。

覆盖行为契约：
- 巡检单只负责记录巡检结果、异常内容和现场处理；巡检异常转故障接口
  与转单目标系统候选端点已下线，请求返回 404 且不产生任何故障记录；
- 故障统一在故障管理模块创建（正式创建服务真实可用），来源关系由该服务写入；
- 历史来源数据（已转故障）继续由来源关系动态推导、只读展示：
  巡检单详情返回处置状态与目标单据号/ID，未处置明细保持"未处置"；
- 巡检异常记录（结果/异常说明/现场处理）本身的记录与展示不受影响；
- 转工单链路已随故障维修工单功能整体删除（2026-09-30）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import (
    InspectionRecord,
    SystemFault,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.inspection_base import (
    INS_URL,
    create_sheet_ok,
    get_sheet_detail,
    get_template_items,
    make_inspection_template,
    make_inspection_user,
    put_records_ok,
    sheet_payload,
    submit_sheet_ok,
)


class InspectionDisposeTestBase(TestCase):
    """公共夹具：已提交巡检单 + 一条"不正常"明细 + 一条正常明细 + 目标系统。"""

    def setUp(self):
        self.admin = make_inspection_user('ins_disp_admin', tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.template = make_inspection_template(
            tenant_id='tenant_a', created_by=self.admin)
        self.items = get_template_items(self.template)
        self.system = make_system(
            self.admin, tenant_id='tenant_a',
            system_code='SYS-D1', name='处置目标系统', install_location='机房D')
        # 建单 → 填一条异常（choice 不正常 + 现场处理）+ 一条正常 → 提交
        body = create_sheet_ok(self.client, sheet_payload(
            self.template.id, duty_date='2026-09-23',
            persons=[{'person_name': '值班员甲'}]))
        put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': self.items['面板指示灯'].id,
             'round_no': 'r1', 'value_text': '不正常',
             'abnormal_desc': '告警灯红色', 'onsite_action': '已切换备用'},
            {'template_item_id': self.items['输出功率读数'].id,
             'round_no': 'r1', 'value_text': '480'},
        ])
        submit_sheet_ok(self.client, body['id'])
        detail = get_sheet_detail(self.client, body['id'])
        self.sheet_id = body['id']
        self.sheet_no = detail['sheet_no']
        self.abnormal_record_id = next(
            r['id'] for r in detail['records'] if r['result'] == 'abnormal')
        self.normal_record_id = next(
            r['id'] for r in detail['records'] if r['result'] == 'normal')

    def sheet_records(self):
        detail = get_sheet_detail(self.client, self.sheet_id)
        return {r['id']: r for r in detail['records']}

    def make_historical_fault(self):
        """构造历史"巡检异常转故障"来源数据（走正式故障创建服务同一代码路径）。"""
        record = InspectionRecord.objects.get(pk=self.abnormal_record_id)
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                return fault_services.create_fault_record(
                    tenant_id='tenant_a', created_by=self.admin,
                    system=self.system,
                    impact_status='',
                    occurred_at=timezone.now(),
                    phenomenon='历史巡检异常转入的故障',
                    source_type='inspection_record',
                    source_inspection_record=record)


class ConvertEndpointsRemovedTest(InspectionDisposeTestBase):
    """巡检转故障接口下线：请求不落任何业务数据。"""

    def test_convert_to_fault_endpoint_removed(self):
        """转故障端点已移除（404），不产生故障记录，明细保持未处置。"""
        resp = self.client.post(
            f'{INS_URL}/{self.sheet_id}/records/{self.abnormal_record_id}/'
            f'convert-to-fault/',
            {'system': self.system.id}, content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(SystemFault.objects.count(), 0)
        disposition = self.sheet_records()[self.abnormal_record_id]['disposition']
        self.assertEqual(disposition['status'], 'none')

    def test_candidate_systems_endpoint_removed(self):
        """转单目标系统候选端点已随转单功能下线（404）。"""
        resp = self.client.get(f'{INS_URL}/candidate-systems/')
        self.assertEqual(resp.status_code, 404)

    def test_abnormal_result_and_onsite_action_recording_unaffected(self):
        """巡检单仍完整记录异常结果、异常说明与现场处理内容。"""
        row = self.sheet_records()[self.abnormal_record_id]
        self.assertEqual(row['result'], 'abnormal')
        self.assertEqual(row['value_text'], '不正常')
        self.assertEqual(row['abnormal_desc'], '告警灯红色')
        self.assertEqual(row['onsite_action'], '已切换备用')


class HistoricalDispositionReadonlyTest(InspectionDisposeTestBase):
    """历史来源数据只读展示：处置状态由来源关系动态推导。"""

    def test_historical_fault_disposition_displayed(self):
        """历史已转故障的明细在详情中显示故障号/ID（已转故障）。"""
        fault = self.make_historical_fault()
        disposition = self.sheet_records()[self.abnormal_record_id]['disposition']
        self.assertEqual(disposition['status'], 'converted_fault')
        self.assertEqual(disposition['fault']['id'], fault.id)
        self.assertEqual(disposition['fault']['fault_no'], fault.fault_no)
        # 正常明细保持未处置
        normal = self.sheet_records()[self.normal_record_id]['disposition']
        self.assertEqual(normal['status'], 'none')
        # 工单处置槽位已随工单功能删除
        self.assertNotIn('work_order', disposition)

    def test_historical_disposition_is_readonly(self):
        """处置状态为推导结果：来源关系不因详情读取而变化，巡检明细本体不被修改。"""
        fault = self.make_historical_fault()
        before = InspectionRecord.objects.get(pk=self.abnormal_record_id)
        self.sheet_records()
        after = InspectionRecord.objects.get(pk=self.abnormal_record_id)
        self.assertEqual(before.result, after.result)
        self.assertEqual(before.abnormal_desc, after.abnormal_desc)
        self.assertEqual(before.onsite_action, after.onsite_action)
        # 来源关系只存在于目标侧（故障外键），明细无回写字段
        self.assertEqual(
            SystemFault.objects.get(pk=fault.id).source_inspection_record_id,
            self.abnormal_record_id)
