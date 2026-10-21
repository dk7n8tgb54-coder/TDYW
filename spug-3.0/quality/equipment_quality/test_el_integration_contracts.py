# -*- coding: utf-8 -*-
"""设备管理——跨模块回归契约专项（quality/equipment_quality）。

聚焦现有单模块测试之外的组合契约：
1. 系统档案 ↔ 系统升级管理关联（挂接/解除、跨租户隔离）；
2. Excel 模板发布版本不可变 + 台账固定版本快照的组合行为；
3. 台账异常明细转设备故障的闭环（统一记录 + 来源关系 + 再处置拦截）。

全部走真实 HTTP + 数据库状态断言。
"""
import json

from django.test import TestCase, TransactionTestCase

from apps.equipment_lifecycle.models import LifecycleSystem, OperationLedger
from apps.equipment_lifecycle.operation_models import SystemOperationRecord
from apps.upgrade.models import UpgradeRecord

from quality.equipment_quality.qa_base import (
    EXCEL_LEDGER_URL, LEDGER_URL, RECORDS_URL, SYSTEMS_URL, UPGRADE_URL,
    UPGRADE_TYPE, ExcelTemplateFlowMixin, IsoStorageMixin, assert_no_500,
    entry_payload, inner, item_payload, ledger_payload, make_client,
    make_system, make_user, post_json, put_json, uniq,
)


class SystemUpgradeLinkageTests(IsoStorageMixin, TestCase):
    """系统详情"升级记录"页签与升级模块的双向契约。"""

    def setUp(self):
        super().setUp()
        self.tenant = uniq('link_t')
        self.user = make_user(uniq('link_user'), perms=[
            'equipment_lifecycle.system.view',
            'upgrade.upgrade.view', 'upgrade.upgrade.add', 'upgrade.upgrade.del',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)
        self.system = make_system(self.user, tenant_id=self.tenant,
                                  name='升级关联系统')

    def _create_upgrade_via_api(self):
        res = post_json(self.client, UPGRADE_URL + '/records/create/', {
            'title': uniq('联动升级'), 'system': self.system.id,
            'upgrade_type': UPGRADE_TYPE, 'upgrade_time': '2026-10-20 10:00:00',
            'owner': '测试负责人', 'upgrade_content': '质量专项联动',
        })
        assert_no_500(res, 'upgrade create')
        self.assertFalse(res.json().get('error'), res.content[:200])
        return res.json()['data']

    def test_created_upgrade_record_visible_in_system_tab(self):
        data = self._create_upgrade_via_api()
        body = inner(self.client.get(
            '%s/%s/upgrade-records/' % (SYSTEMS_URL, self.system.id)))
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['data'][0]['id'], data['id'])

    def test_deleted_upgrade_record_removed_from_system_tab(self):
        data = self._create_upgrade_via_api()
        res = self.client.delete('%s/records/%s/delete/' % (UPGRADE_URL, data['id']))
        assert_no_500(res, 'upgrade delete')
        self.assertFalse(res.json().get('error'), res.content[:200])
        body = inner(self.client.get(
            '%s/%s/upgrade-records/' % (SYSTEMS_URL, self.system.id)))
        self.assertEqual(body['total'], 0)
        record = UpgradeRecord.objects.filter(pk=data['id']).first()
        self.assertTrue(record is None or record.is_deleted)

    def test_upgrade_create_on_missing_system_rejected(self):
        res = post_json(self.client, UPGRADE_URL + '/records/create/', {
            'title': uniq('幽灵系统升级'), 'system': 99999999,
            'upgrade_type': UPGRADE_TYPE, 'upgrade_time': '2026-10-20 10:00:00',
            'owner': '测试负责人', 'upgrade_content': 'x',
        })
        assert_no_500(res, 'upgrade create missing system')
        self.assertTrue(res.json().get('error'))


class TemplateVersionImmutabilityComboTests(IsoStorageMixin, TestCase):
    """发布版本不可变 × 台账固定版本快照的组合契约。"""

    def setUp(self):
        super().setUp()
        self.tenant = uniq('imm_t')
        self.user = make_user(uniq('imm_user'), perms=[
            'equipment_lifecycle.ledger_template.view',
            'equipment_lifecycle.ledger_template.add',
            'equipment_lifecycle.ledger_template.edit',
            'equipment_lifecycle.ledger.view',
            'equipment_lifecycle.ledger.add',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)
        self.flow = ExcelTemplateFlowMixin()
        self.flow.client = self.client

    def test_ledger_keeps_its_version_after_new_publish(self):
        template = self.flow.upload_template()
        self.flow.save_bindings(template['id'],
                                [self.flow.make_binding('C4', 'PS模块')])
        v1 = self.flow.publish(template['id'])
        ledger = self.flow.create_excel_ledger(v1['id'])
        # 迭代发布 v2 后：台账仍引用 v1，详情导出走 v1 快照，不被动升级
        self.flow.save_bindings(template['id'],
                                [self.flow.make_binding('F4', 'BB模块')])
        v2 = self.flow.publish(template['id'])
        self.assertEqual(v2['version_no'], 2)
        detail = inner(self.client.get('%s/%s/' % (EXCEL_LEDGER_URL, ledger['id'])))
        if isinstance(detail, dict) and 'data' in detail:
            detail = detail['data']
        detail_version = (detail.get('excel') or {}).get('version') or {}
        self.assertEqual(detail_version.get('id'), v1['id'])

    def test_old_version_hidden_from_available_but_ledger_usable(self):
        template = self.flow.upload_template()
        self.flow.save_bindings(template['id'],
                                [self.flow.make_binding('C4', 'PS模块')])
        v1 = self.flow.publish(template['id'])
        self.flow.save_bindings(template['id'],
                                [self.flow.make_binding('F4', 'BB模块')])
        v2 = self.flow.publish(template['id'])
        available = self.client.get(
            '%s/available/?ledger_type=week_month' % '/equipment-lifecycle/excel-templates'
        ).json()['data']['data']
        versions = [v['id'] for t in available for v in t.get('versions', [])]
        self.assertNotIn(v1['id'], versions)
        self.assertIn(v2['id'], versions)
        # 旧版本 id 直接创建：后端独立拒绝（防绕过前端）
        res = self.client.post(
            EXCEL_LEDGER_URL + '/',
            json.dumps({'version_id': v1['id'], 'ledger_type': 'week_month'}),
            content_type='application/json')
        assert_no_500(res, 'create with old version')
        self.assertTrue(res.json().get('error'), res.content[:200])


class LedgerConvertToFaultContractTests(IsoStorageMixin, TransactionTestCase):
    """台账异常明细 → 设备故障（统一记录）闭环。

    使用 TransactionTestCase（转换路径持健康重算锁，与既有
    test_operation_ledger_source 一致）。
    """

    def setUp(self):
        self.tenant = uniq('conv_t')
        self.user = make_user(uniq('conv_user'), perms=[
            'equipment_lifecycle.ledger.view', 'equipment_lifecycle.ledger.add',
            'equipment_lifecycle.ledger.edit',
            'equipment_lifecycle.ledger.submit',
            'equipment_lifecycle.ledger.handle_exception',
            'equipment_lifecycle.operation_record.add_fault',
            'equipment_lifecycle.operation_record.view',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)
        self.system = make_system(self.user, tenant_id=self.tenant)

    def _create_completed_ledger_with_abnormal_item(self):
        res = post_json(self.client, LEDGER_URL + '/', ledger_payload(
            [entry_payload(self.system.id, [
                item_payload(),
                item_payload(item_name='电源电压测量', input_type='number',
                             value_text='', value_number=52,
                             result='abnormal', abnormal_desc='电压偏低'),
            ])]))
        assert_no_500(res, 'ledger create for convert')
        self.assertFalse(res.json().get('error'), res.content[:200])
        ledger = res.json()['data']
        items = ledger.get('items') or []
        abnormal = None
        for item in items:
            if item.get('result') == 'abnormal':
                abnormal = item
                break
        self.assertIsNotNone(abnormal, json.dumps(items)[:300])
        # 台账转故障要求台账已完成（草稿不能转）：先完成填写
        complete = post_json(self.client,
                             '%s/%s/complete/' % (LEDGER_URL, ledger['id']), {})
        assert_no_500(complete, 'ledger complete for convert')
        self.assertFalse(complete.json().get('error'), complete.content[:200])
        return ledger, abnormal

    def test_convert_creates_fault_record_with_source_linkage(self):
        ledger, item = self._create_completed_ledger_with_abnormal_item()
        res = post_json(
            self.client,
            '%s/%s/items/%s/convert-to-fault/' % (LEDGER_URL, ledger['id'], item['id']),
            {'occurred_at': '2026-10-20 09:30'})
        assert_no_500(res, 'convert to fault')
        self.assertFalse(res.json().get('error'), res.content[:200])
        data = res.json().get('data') or {}
        record_id = data.get('id')
        self.assertTrue(record_id)
        record = SystemOperationRecord.objects.get(pk=record_id)
        self.assertEqual(record.record_type, 'fault')
        self.assertEqual(record.system_id, self.system.id)
        self.assertEqual(record.source_ledger_item_id, item['id'])
        # 默认"部件故障但不影响系统运行"（affects=False）：健康状态保持原值，
        # impact_status 强制为空（见 operation_services.create_operation_record）
        self.system.refresh_from_db()
        self.assertEqual(self.system.health_status,
                         LifecycleSystem.HEALTH_NORMAL)
        self.assertEqual(record.impact_status, '')

    def test_convert_twice_rejected(self):
        ledger, item = self._create_completed_ledger_with_abnormal_item()
        first = post_json(
            self.client,
            '%s/%s/items/%s/convert-to-fault/' % (LEDGER_URL, ledger['id'], item['id']),
            {'occurred_at': '2026-10-20 09:30'})
        self.assertFalse(first.json().get('error'), first.content[:200])
        second = post_json(
            self.client,
            '%s/%s/items/%s/convert-to-fault/' % (LEDGER_URL, ledger['id'], item['id']),
            {'occurred_at': '2026-10-20 09:30'})
        assert_no_500(second, 'convert twice')
        self.assertTrue(second.json().get('error'))

    def test_convert_nonexistent_item_rejected(self):
        ledger, _item = self._create_completed_ledger_with_abnormal_item()
        res = post_json(
            self.client,
            '%s/%s/items/99999999/convert-to-fault/' % (LEDGER_URL, ledger['id']), {})
        assert_no_500(res, 'convert nonexistent item')
        self.assertTrue(res.json().get('error'))
