# -*- coding: utf-8 -*-
"""原生路线维护台账流程测试（2026-10-18 接入）。

覆盖：从发布版本创建台账（client_token 幂等/类型校验）、填写值类型校验、
执行日期、完成填写（状态机+必填+执行日期，重复完成无副作用）、已完成
更正（原因必填/前后值留痕/无变化拒绝）、作废与删除沿用既有端点、统一
列表来源字段与详情路由、模板分组（native-<id> 组/组内列表/批量导出与
翻阅明确拒绝）、Excel 与原生路线互不串扰、跨租户拒绝。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplate,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.models import (
    LEDGER_FROM_EXCEL,
    OperationLedger,
    OperationLedgerCorrection,
)
from apps.equipment_lifecycle.native_models import OperationLedgerNativeRecord
from apps.equipment_lifecycle.tests.base import make_client, make_user
from apps.equipment_lifecycle.tests.native_fixtures import (
    make_binding,
    make_native_ledger,
    make_native_template,
    make_published_version,
)


def make_excel_ledger(user, status):
    """Excel 路线台账夹具（模板+版本+填写记录，ORM 直建；互不串扰测试用）。"""
    template = OperationLedgerExcelTemplate.objects.create(
        tenant_id=user.tenant_id,
        name='可见性Excel模板',
        ledger_type='week_month',
        created_by=user,
    )
    version = OperationLedgerExcelTemplateVersion.objects.create(
        tenant_id=user.tenant_id,
        template=template,
        version_no=1,
        template_name_snapshot=template.name,
        source_filename='visibility.xlsx',
        source_hash='%064d' % template.id,
        bindings='[]',
        published_by=user,
    )
    ledger = OperationLedger.objects.create(
        tenant_id=user.tenant_id,
        ledger_no='EL-WM-20261017-9001',
        ledger_type='week_month',
        executed_date='2026-10-17',
        status=status,
        created_from=LEDGER_FROM_EXCEL,
        source_template=template,
        created_by=user,
    )
    OperationLedgerExcelRecord.objects.create(
        tenant_id=user.tenant_id, ledger=ledger, version=version, values='{}')
    return ledger

TEMPLATE_URL = '/equipment-lifecycle/native-templates'
LEDGER_URL = '/equipment-lifecycle/native-ledgers'
UNIFIED_URL = '/equipment-lifecycle/ledgers'

LEDGER_PERMS = [
    'equipment_lifecycle.ledger.%s' % a
    for a in ('view', 'add', 'edit', 'submit', 'del', 'export')
]
TPL_PERMS = ['equipment_lifecycle.ledger_template.view']


class NativeLedgerFlowTests(TestCase):
    def setUp(self):
        self.user = make_user('native_ledger_user',
                              perms=LEDGER_PERMS + TPL_PERMS)
        self.client = make_client(self.user)
        self.template = make_native_template(self.user)
        self.bindings = [
            make_binding('conclusion', label='维护结论', cell_range='B2',
                         ftype='text', required=True),
            make_binding('temperature', label='环境温度', cell_range='B3',
                         ftype='number'),
            make_binding('inspect_date', label='维护日期', cell_range='B4',
                         ftype='date'),
            make_binding('verdict', label='判定', cell_range='B5',
                         ftype='status'),
            make_binding('note', label='备注', cell_range='B6',
                         ftype='textarea'),
        ]
        self.version = make_published_version(self.template, self.user,
                                              bindings=self.bindings)

    def _create(self, **overrides):
        payload = {
            'version_id': self.version.id,
            'executed_date': '2026-10-18',
            'client_token': 'tok_native_1',
        }
        payload.update(overrides)
        return self.client.post('%s/' % LEDGER_URL, payload,
                                content_type='application/json')

    def _values(self, **overrides):
        values = {
            'conclusion': '链路正常',
            'temperature': '25.5',
            'inspect_date': '2026-10-18',
            'verdict': '正常',
            'note': '无异常',
        }
        values.update(overrides)
        return values

    # ==================== 创建 ====================

    def test_create_ledger_and_prefill(self):
        res = self._create()
        self.assertEqual(res.json()['error'], '')
        detail = res.json()['data']['data']
        self.assertEqual(detail['created_from'], 'native_template')
        self.assertEqual(detail['status'], 'draft')
        self.assertTrue(detail['ledger_no'].startswith('EL-WM-20261018'))
        self.assertEqual(detail['native']['version']['id'], self.version.id)
        self.assertEqual(detail['native']['version']['version_no'], 1)
        # 预填骨架：全部绑定 key → 空串
        self.assertEqual(
            detail['native']['values'],
            {b['key']: '' for b in self.bindings})
        self.assertTrue(detail['native']['editable'])

    def test_create_client_token_idempotent(self):
        res1 = self._create()
        res2 = self._create()
        first = res1.json()['data']['data']['id']
        self.assertEqual(res2.json()['data']['data']['id'], first)
        self.assertEqual(
            OperationLedger.objects.filter(created_from='native_template').count(), 1)

    def test_create_type_mismatch_and_missing_fields(self):
        res = self._create(ledger_type='seasonal')
        self.assertIn('与所选台账类型不一致', res.json()['error'])
        res = self._create(executed_date='')
        self.assertIn('实际执行日期', res.json()['error'])
        res = self._create(version_id=999999)
        self.assertIn('不存在或未发布', res.json()['error'])

    # ==================== 填写值校验与保存 ====================

    def test_update_values_type_validation(self):
        ledger = make_native_ledger(self.user, self.version)
        url = '%s/%d/' % (LEDGER_URL, ledger.id)
        res = self.client.put(url, {'values': self._values()},
                              content_type='application/json')
        self.assertEqual(res.json()['error'], '')
        self.assertEqual(res.json()['data']['data']['native']['values']['temperature'], '25.5')

        cases = [
            ({'temperature': 'abc'}, '须填写数字'),
            ({'inspect_date': '2026/10/18'}, 'YYYY-MM-DD'),
            ({'verdict': '良好'}, '正常/不正常'),
            ({'unknown_key': 'x'}, '不存在的字段'),
        ]
        for bad, expect in cases:
            res = self.client.put(url, {'values': self._values(**bad)},
                                  content_type='application/json')
            self.assertIn(expect, res.json()['error'], bad)

    def test_update_header_executed_date(self):
        ledger = make_native_ledger(self.user, self.version,
                                    executed_date='2026-10-18')
        url = '%s/%d/' % (LEDGER_URL, ledger.id)
        res = self.client.put(url, {'header': {'executed_date': '2026-10-19'}},
                              content_type='application/json')
        self.assertEqual(res.json()['error'], '')
        ledger.refresh_from_db()
        self.assertEqual(str(ledger.executed_date), '2026-10-19')
        # 空串显式清空
        res = self.client.put(url, {'header': {'executed_date': ''}},
                              content_type='application/json')
        self.assertEqual(res.json()['error'], '')
        ledger.refresh_from_db()
        self.assertIsNone(ledger.executed_date)

    # ==================== 完成填写 ====================

    def test_complete_flow_and_state_machine(self):
        ledger = make_native_ledger(self.user, self.version,
                                    executed_date=None, status='draft')
        url = '%s/%d/complete/' % (LEDGER_URL, ledger.id)
        # 未填执行日期
        res = self.client.post(url)
        self.assertIn('实际执行日期', res.json()['error'])
        # 保存值 + 日期后完成
        self.client.put('%s/%d/' % (LEDGER_URL, ledger.id), {
            'values': self._values(),
            'header': {'executed_date': '2026-10-18'},
        }, content_type='application/json')
        res = self.client.post(url)
        self.assertEqual(res.json()['error'], '')
        self.assertEqual(res.json()['data']['data']['status'], 'completed')
        ledger.refresh_from_db()
        self.assertEqual(ledger.status, 'completed')
        self.assertIsNotNone(ledger.completed_at)
        # 重复完成被状态机拦截
        res = self.client.post(url)
        self.assertIn('不允许完成填写', res.json()['error'])
        self.assertEqual(
            OperationLedger.objects.filter(pk=ledger.id, status='completed').count(), 1)

    def test_complete_blocked_by_required(self):
        template = make_native_template(self.user, name='必填模板')
        version = make_published_version(template, self.user, bindings=[
            make_binding('must', label='必填结论', cell_range='B2', required=True),
        ])
        ledger = make_native_ledger(
            self.user, version, values={'must': ''}, executed_date='2026-10-18')
        res = self.client.post('%s/%d/complete/' % (LEDGER_URL, ledger.id))
        self.assertIn('必填字段未填写', res.json()['error'])
        self.assertIn('必填结论', res.json()['error'])

    def test_edit_after_complete_rejected(self):
        ledger = make_native_ledger(self.user, self.version,
                                    status='completed',
                                    values=self._values())
        res = self.client.put('%s/%d/' % (LEDGER_URL, ledger.id),
                              {'values': self._values(conclusion='改')},
                              content_type='application/json')
        self.assertIn('不允许修改填写值', res.json()['error'])

    # ==================== 更正 ====================

    def test_correct_completed_ledger(self):
        ledger = make_native_ledger(self.user, self.version,
                                    status='completed', values=self._values())
        url = '%s/%d/correct/' % (LEDGER_URL, ledger.id)
        # 缺原因
        res = self.client.post(url, {'values': self._values(conclusion='更正后')},
                               content_type='application/json')
        self.assertIn('必须填写原因', res.json()['error'])
        # 正常更正：值 + 执行日期
        res = self.client.post(url, {
            'reason': '复核发现结论有误',
            'values': self._values(conclusion='结论修正'),
            'header': {'executed_date': '2026-10-19'},
        }, content_type='application/json')
        self.assertEqual(res.json()['error'], '')
        ledger.refresh_from_db()
        self.assertEqual(str(ledger.executed_date), '2026-10-19')
        record = OperationLedgerCorrection.objects.get(ledger=ledger)
        self.assertEqual(record.reason, '复核发现结论有误')
        fields = {c['field']: c for c in json_changes(record.changes)}
        self.assertEqual(fields['conclusion']['old'], '链路正常')
        self.assertEqual(fields['conclusion']['new'], '结论修正')
        self.assertEqual(fields['executed_date']['new'], '2026-10-19')
        # 详情带更正记录
        res = self.client.get('%s/%d/' % (LEDGER_URL, ledger.id))
        self.assertEqual(len(res.json()['data']['data']['corrections']), 1)

    def test_correct_without_change_rejected(self):
        ledger = make_native_ledger(self.user, self.version,
                                    status='completed', values=self._values(),
                                    executed_date='2026-10-18')
        res = self.client.post('%s/%d/correct/' % (LEDGER_URL, ledger.id), {
            'reason': '无变化', 'values': self._values(),
            'header': {'executed_date': '2026-10-18'},
        }, content_type='application/json')
        self.assertIn('没有需要更正的内容', res.json()['error'])

    # ==================== 作废 / 删除（沿用既有端点） ====================

    def test_void_and_delete(self):
        ledger = make_native_ledger(self.user, self.version, status='completed')
        res = self.client.post('%s/%d/void/' % (UNIFIED_URL, ledger.id),
                               {'reason': '录入错误'}, content_type='application/json')
        self.assertEqual(res.json()['error'], '')
        ledger.refresh_from_db()
        self.assertEqual(ledger.status, 'void')
        # 作废后原生详情 voided 标记、不可再编辑
        res = self.client.get('%s/%d/' % (LEDGER_URL, ledger.id))
        self.assertTrue(res.json()['data']['data']['native']['voided'])
        self.assertFalse(res.json()['data']['data']['native']['editable'])

        draft = make_native_ledger(self.user, self.version, status='draft')
        res = self.client.delete('%s/%d/' % (UNIFIED_URL, draft.id))
        self.assertEqual(res.json()['error'], '')
        self.assertFalse(OperationLedger.objects.filter(pk=draft.id).exists())
        self.assertFalse(
            OperationLedgerNativeRecord.objects.filter(ledger_id=draft.id).exists())


def json_changes(raw):
    return json.loads(raw)


class NativeLedgerVisibilityTests(TestCase):
    """列表可见性与来源识别：统一列表 / Excel 列表 / 原生列表互不串扰。"""

    def setUp(self):
        self.user = make_user('native_vis_user',
                              perms=LEDGER_PERMS + TPL_PERMS)
        self.client = make_client(self.user)
        self.template = make_native_template(self.user, name='可见性原生模板')
        self.version = make_published_version(self.template, self.user)
        self.ledger = make_native_ledger(self.user, self.version,
                                         executed_date='2026-10-18')

    def test_unified_list_source_fields(self):
        res = self.client.get('%s/?ledger_type=week_month' % UNIFIED_URL)
        self.assertEqual(res.json()['error'], '')
        rows = res.json()['data']['data']
        row = next(r for r in rows if r['id'] == self.ledger.id)
        self.assertEqual(row['source_type'], 'native')
        self.assertEqual(row['source_template_name'], '可见性原生模板')
        self.assertEqual(row['source_version_no'], 1)
        self.assertIn('source=native', row['detail_route'])

    def test_native_and_excel_lists_are_isolated(self):
        excel_ledger = make_excel_ledger(self.user, 'draft')
        res = self.client.get('%s/' % LEDGER_URL)
        ids = [r['id'] for r in res.json()['data']['data']]
        self.assertIn(self.ledger.id, ids)
        self.assertNotIn(excel_ledger.id, ids)
        res = self.client.get('/equipment-lifecycle/excel-ledgers/')
        ids = [r['id'] for r in res.json()['data']['data']]
        self.assertIn(excel_ledger.id, ids)
        self.assertNotIn(self.ledger.id, ids)

    def test_cross_tenant_detail_denied(self):
        other = make_user('native_vis_other', tenant_id='tenant-other',
                          perms=LEDGER_PERMS)
        res = make_client(other).get('%s/%d/' % (LEDGER_URL, self.ledger.id))
        self.assertIn('台账不存在', res.json()['error'])
        # 越权写同样拒绝
        res = make_client(other).put('%s/%d/' % (LEDGER_URL, self.ledger.id),
                                     {'values': {}}, content_type='application/json')
        self.assertIn('台账不存在', res.json()['error'])

    def test_unified_detail_routes_native(self):
        res = self.client.get('%s/%d/' % (UNIFIED_URL, self.ledger.id))
        self.assertEqual(res.json()['error'], '')
        self.assertIn('native', res.json()['data'])
        self.assertEqual(res.json()['data']['native']['version']['version_no'], 1)


class NativeTemplateGroupTests(TestCase):
    """按模板查看：原生模板组聚合与组内列表；批量导出/翻阅明确拒绝。"""

    def setUp(self):
        self.user = make_user('native_group_user',
                              perms=LEDGER_PERMS + TPL_PERMS)
        self.client = make_client(self.user)
        self.template = make_native_template(self.user, name='分组原生模板')
        self.version = make_published_version(self.template, self.user)
        self.ledger = make_native_ledger(self.user, self.version,
                                         executed_date='2026-10-18')

    def test_group_list_contains_native_group(self):
        res = self.client.get(
            '/equipment-lifecycle/ledgers/template-groups/?ledger_type=week_month')
        self.assertEqual(res.json()['error'], '')
        groups = res.json()['data']['data']
        group = next(g for g in groups if g['source_type'] == 'native')
        self.assertEqual(group['group_key'], 'native-%d' % self.template.id)
        self.assertEqual(group['template_name'], '分组原生模板')
        self.assertEqual(group['total'], 1)

    def test_group_ledgers(self):
        key = 'native-%d' % self.template.id
        res = self.client.get(
            '/equipment-lifecycle/ledgers/template-groups/%s/ledgers/'
            '?ledger_type=week_month' % key)
        self.assertEqual(res.json()['error'], '')
        self.assertEqual(res.json()['data']['group_name'], '分组原生模板')
        self.assertEqual(len(res.json()['data']['data']), 1)
        row = res.json()['data']['data'][0]
        self.assertEqual(row['source_type'], 'native')
        self.assertEqual(row['source_version_no'], 1)

    def test_group_batch_export_and_browse_rejected(self):
        key = 'native-%d' % self.template.id
        res = self.client.get(
            '/equipment-lifecycle/ledgers/template-groups/%s/export-pdf/' % key)
        self.assertIn('暂不支持批量导出', res.json()['error'])
        res = self.client.post(
            '/equipment-lifecycle/ledgers/template-groups/%s/export-pdf/' % key)
        self.assertIn('暂不支持批量导出', res.json()['error'])
        res = self.client.get(
            '/equipment-lifecycle/ledgers/template-groups/%s/browse/' % key)
        self.assertIn('暂不支持连续翻阅', res.json()['error'])
