# -*- coding: utf-8 -*-
"""维护台账已作废可见性与列表筛选口径（2026-10-17）行为测试。

真实执行 HTTP → View → Service → ORM 链路（Docker + 隔离测试库），覆盖：
- 默认视图：统一列表 /ledgers/、周期分组 /ledgers/period-groups/、模板分组
  /ledgers/template-groups/（含组内列表）默认不展示已作废；组统计数量
  与可见行一致；
- 状态筛选：status=void 主动查看已作废；status=all（全部）明确包含已作废；
  显式单状态精确匹配不受影响；
- 明细 CSV 导出与列表同口径（默认不含已作废，void/all 显式调整），审计
  如实记录生效的状态筛选范围；
- 模板组批量 PDF 导出预览：status=all 包含草稿/已作废，默认范围不含二者；
- 已作废台账只读：编辑/完成/更正/删除/上传附件均被后端拒绝（查看/导出
  不受限），作废必须填写原因；无权限与跨租户作废被拒绝。
"""
import itertools
from unittest import mock

from django.test import TestCase

from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplate,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.models import (
    LEDGER_FROM_EXCEL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system, make_user
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    P_LED_DEL,
    post_json,
)

URL_PREFIX = '/equipment-lifecycle'
LEDGERS_URL = URL_PREFIX + '/ledgers'
GROUPS_URL = LEDGERS_URL + '/period-groups/'
TEMPLATE_GROUPS_URL = LEDGERS_URL + '/template-groups/'
EXPORT_URL = LEDGERS_URL + '/export/'

_ledger_no_seq = itertools.count(1)

# 批量 PDF 导出默认状态范围（与 ledger_template_group_services 一致）
DEFAULT_EXPORT_STATUSES = ['completed']


def csv_data_rows(body):
    """CSV 数据行（去表头、去空行）。"""
    text = body.decode('utf-8-sig')
    rows = [line for line in text.splitlines() if line.strip()]
    return rows[1:]


class LedgerVisibilityTestBase(TestCase):
    """公共夹具：全台账权限用户 + 手工/Excel 两类台账夹具。"""

    def setUp(self):
        self.user = make_user('void_vis_op', perms=ALL_LEDGER_PERMS)
        self.client = make_client(self.user)
        self.system_a = make_system(self.user, system_code='SYS-VIS', name='可见性系统')

    def make_manual_ledger(self, status, with_item=True, **overrides):
        """手工台账夹具（状态可直接指定为历史值；默认带一条明细供 CSV 导出）。"""
        defaults = dict(
            tenant_id=self.user.tenant_id,
            ledger_no='EL-WM-20261017-%04d' % next(_ledger_no_seq),
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            status=status,
            entry_channel='web',
            created_from='manual',
            system=self.system_a,
            maintenance_period='2026-10',
            slot_active=None if status == 'void' else True,
            created_by=self.user,
        )
        defaults.update(overrides)
        ledger = OperationLedger.objects.create(**defaults)
        if with_item:
            OperationLedgerItem.objects.create(
                ledger=ledger,
                tenant_id=ledger.tenant_id,
                system=ledger.system,
                system_code_snapshot=ledger.system.system_code,
                system_name_snapshot=ledger.system.name,
                item_name_snapshot='电源电压测量',
                input_type='text',
                value_text='正常',
                result='normal',
            )
        return ledger

    def make_excel_ledger(self, status, template=None):
        """Excel 路线台账夹具（模板+版本+填写记录，ORM 直建）。"""
        template = template or OperationLedgerExcelTemplate.objects.create(
            tenant_id=self.user.tenant_id,
            name='可见性Excel模板',
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            created_by=self.user,
        )
        version = OperationLedgerExcelTemplateVersion.objects.create(
            tenant_id=self.user.tenant_id,
            template=template,
            version_no=OperationLedgerExcelTemplateVersion.objects.filter(
                template_id=template.id).count() + 1,
            template_name_snapshot=template.name,
            source_filename='visibility.xlsx',
            source_hash='%064d' % template.id,
            bindings='[]',
            published_by=self.user,
        )
        ledger = self.make_manual_ledger(
            status, with_item=False, created_from=LEDGER_FROM_EXCEL,
            source_template=template,
            # 同模板同系统的有效台账受期次唯一约束约束，逐张错开期次
            maintenance_period='2026-%02d' % (
                OperationLedger.objects.filter(
                    source_template_id=template.id).count() + 1))
        OperationLedgerExcelRecord.objects.create(
            tenant_id=self.user.tenant_id, ledger=ledger, version=version, values='{}')
        return ledger

    def make_status_ledgers(self):
        """草稿/已完成/已作废 各一张（同系统同期次）。"""
        return {
            'draft': self.make_manual_ledger('draft'),
            'completed': self.make_manual_ledger('completed'),
            'void': self.make_manual_ledger('void'),
        }


class UnifiedListVisibilityTests(LedgerVisibilityTestBase):
    """统一列表 /ledgers/：默认不含已作废；void/all 显式调整。"""

    def _list_statuses(self, query):
        resp = self.client.get(LEDGERS_URL + '/', query)
        self.assertFalse(resp.json().get('error'), resp.json())
        payload = resp.json()['data']
        data = payload['data'] if isinstance(payload, dict) else payload
        return sorted(row['status'] for row in data), payload

    def test_default_view_excludes_void(self):
        """默认视图：草稿/已完成可见，已作废隐藏；total 与之一致。"""
        self.make_status_ledgers()
        statuses, payload = self._list_statuses({'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(statuses, ['completed', 'draft'])
        self.assertEqual(payload['total'], 2)

    def test_status_void_all_and_explicit(self):
        """status=void 只看已作废；status=all 包含全部；显式状态精确匹配。"""
        self.make_status_ledgers()
        statuses, payload = self._list_statuses(
            {'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'void'})
        self.assertEqual(statuses, ['void'])
        self.assertEqual(payload['total'], 1)

        statuses, payload = self._list_statuses(
            {'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'all'})
        self.assertEqual(statuses, ['completed', 'draft', 'void'])
        self.assertEqual(payload['total'], 3)

        statuses, payload = self._list_statuses(
            {'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'draft'})
        self.assertEqual(statuses, ['draft'])
        self.assertEqual(payload['total'], 1)


class PeriodGroupsVisibilityTests(LedgerVisibilityTestBase):
    """周期分组 /ledgers/period-groups/：默认不含已作废，组统计与可见行一致。"""

    def _groups(self, query):
        params = {'ledger_type': LEDGER_TYPE_WEEK_MONTH}
        params.update(query)
        resp = self.client.get(GROUPS_URL, params)
        self.assertFalse(resp.json().get('error'), resp.json())
        return resp.json()['data']

    def test_default_groups_exclude_void(self):
        """默认：分组内草稿/已完成可见（已作废隐藏），组统计同步。"""
        self.make_status_ledgers()
        payload = self._groups({})
        self.assertEqual(payload['total'], 1)
        group = payload['data'][0]
        self.assertEqual(group['total'], 2)
        self.assertEqual(group['draft'], 1)
        self.assertEqual(group['completed'], 1)
        self.assertEqual(group['void'], 0)
        self.assertEqual(
            sorted(row['status'] for row in group['ledgers']),
            ['completed', 'draft'])

    def test_void_filter_and_all_filter(self):
        """status=void 组内只见已作废；status=all 统计与行同步包含两类。"""
        self.make_status_ledgers()
        payload = self._groups({'status': 'void'})
        group = payload['data'][0]
        self.assertEqual(group['total'], 1)
        self.assertEqual(group['void'], 1)
        self.assertEqual(
            sorted(row['status'] for row in group['ledgers']), ['void'])

        payload = self._groups({'status': 'all'})
        group = payload['data'][0]
        self.assertEqual(group['total'], 3)
        self.assertEqual(group['draft'], 1)
        self.assertEqual(group['void'], 1)
        self.assertEqual(
            sorted(row['status'] for row in group['ledgers']),
            ['completed', 'draft', 'void'])


class TemplateGroupsVisibilityTests(LedgerVisibilityTestBase):
    """模板分组：组统计与组内列表默认不含已作废，void/all 显式调整。"""

    def setUp(self):
        super().setUp()
        self.template = OperationLedgerExcelTemplate.objects.create(
            tenant_id=self.user.tenant_id,
            name='模板组可见性模板',
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            created_by=self.user,
        )
        self.excel_draft = self.make_excel_ledger('draft', template=self.template)
        self.excel_void = self.make_excel_ledger('void', template=self.template)
        self.manual_draft = self.make_manual_ledger('draft')

    def _groups(self, query):
        params = {'ledger_type': LEDGER_TYPE_WEEK_MONTH}
        params.update(query)
        resp = self.client.get(TEMPLATE_GROUPS_URL, params)
        self.assertFalse(resp.json().get('error'), resp.json())
        payload = resp.json()['data']
        return {g['group_key']: g for g in (payload['data'] if isinstance(payload, dict) else payload)}

    def _group_ledgers(self, query):
        params = {'ledger_type': LEDGER_TYPE_WEEK_MONTH}
        params.update(query)
        resp = self.client.get(
            '%s%s/ledgers/' % (TEMPLATE_GROUPS_URL, self.template.id), params)
        self.assertFalse(resp.json().get('error'), resp.json())
        payload = resp.json()['data']
        return payload['data'] if isinstance(payload, dict) else payload

    def test_default_group_stats_exclude_void(self):
        """默认：模板组统计 total/draft 只算可见行（void=0），手工组不受影响。"""
        groups = self._groups({})
        self.assertIn(str(self.template.id), groups)
        excel_group = groups[str(self.template.id)]
        self.assertEqual(excel_group['total'], 1)
        self.assertEqual(excel_group['draft'], 1)
        self.assertEqual(excel_group['void'], 0)
        self.assertEqual(groups['manual']['total'], 1)

    def test_group_ledgers_default_void_all(self):
        """组内列表：默认无已作废行；status=void 仅已作废；status=all 两张并存。"""
        rows = self._group_ledgers({})
        self.assertEqual(sorted(r['status'] for r in rows), ['draft'])

        rows = self._group_ledgers({'status': 'void'})
        self.assertEqual(sorted(r['status'] for r in rows), ['void'])

        rows = self._group_ledgers({'status': 'all'})
        self.assertEqual(sorted(r['status'] for r in rows), ['draft', 'void'])

    def test_void_filter_group_stats(self):
        """status=void 时模板组统计 total=1、void=1（主动查看已作废）。"""
        groups = self._groups({'status': 'void'})
        excel_group = groups[str(self.template.id)]
        self.assertEqual(excel_group['total'], 1)
        self.assertEqual(excel_group['void'], 1)
        self.assertNotIn('manual', groups)


class LedgerExportVisibilityTests(LedgerVisibilityTestBase):
    """明细 CSV 导出与列表同口径；审计如实记录状态筛选。"""

    def setUp(self):
        super().setUp()
        self.make_status_ledgers()

    def _export(self, query):
        return self.client.get(EXPORT_URL, query)

    def test_default_export_excludes_void(self):
        """默认导出：草稿/已完成/历史状态明细可见，已作废明细不出现。"""
        response = self._export({'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8-sig')
        self.assertIn('EL-WM-20261017', content)
        rows = csv_data_rows(response.content)
        void_no = OperationLedger.objects.get(status='void').ledger_no
        self.assertNotIn(void_no, content)
        self.assertEqual(len(rows), 2, '仅草稿/已完成各一条明细')

    def test_void_and_all_export_scopes(self):
        """status=void 仅导出已作废明细；status=all 全量导出。"""
        void_no = OperationLedger.objects.get(status='void').ledger_no
        response = self._export({'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'void'})
        rows = csv_data_rows(response.content)
        self.assertEqual(len(rows), 1)
        self.assertIn(void_no, response.content.decode('utf-8-sig'))

        response = self._export({'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'all'})
        self.assertEqual(len(csv_data_rows(response.content)), 3)

    def test_audit_records_effective_status_scope(self):
        """审计 filters.status：默认口径与显式 all 均如实记录。"""
        with mock.patch('apps.equipment_lifecycle.ledger_views.'
                        'record_audit_event') as audit:
            self._export({'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        kwargs = audit.call_args[1]
        self.assertEqual(kwargs['after_value']['filters'],
                         {'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                          'status': '默认(不含已作废)'})

        with mock.patch('apps.equipment_lifecycle.ledger_views.'
                        'record_audit_event') as audit:
            self._export({'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'all'})
        kwargs = audit.call_args[1]
        self.assertEqual(kwargs['after_value']['filters'],
                         {'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'all'})


class BatchExportPreviewScopeTests(LedgerVisibilityTestBase):
    """模板组批量 PDF 导出预览：status=all 包含草稿/已作废；默认范围不含。"""

    def setUp(self):
        super().setUp()
        self.template = OperationLedgerExcelTemplate.objects.create(
            tenant_id=self.user.tenant_id,
            name='批量导出范围模板',
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            created_by=self.user,
        )
        self.make_excel_ledger('draft', template=self.template)
        self.make_excel_ledger('void', template=self.template)
        self.make_excel_ledger('completed', template=self.template)

    def _preview(self, query):
        params = {'ledger_type': LEDGER_TYPE_WEEK_MONTH}
        params.update(query)
        resp = self.client.get(
            '%s%s/export-pdf/' % (TEMPLATE_GROUPS_URL, self.template.id), params)
        self.assertFalse(resp.json().get('error'), resp.json())
        return resp.json()['data']['data']

    def test_default_preview_excludes_draft_and_void(self):
        """默认：状态范围为已完成及历史有效状态，草稿/已作废不计入。"""
        preview = self._preview({})
        self.assertEqual(preview['total'], 1)
        self.assertEqual(preview['status_scope'], DEFAULT_EXPORT_STATUSES)

    def test_all_preview_includes_draft_and_void(self):
        """status=all：明确包含草稿与已作废（用户显式选择）。"""
        preview = self._preview({'status': 'all'})
        self.assertEqual(preview['total'], 3)
        self.assertEqual(preview['status_scope'], ['all'])

    def test_void_preview_only_void(self):
        """status=void：仅已作废台账计入导出预览。"""
        preview = self._preview({'status': 'void'})
        self.assertEqual(preview['total'], 1)
        self.assertEqual(preview['status_scope'], ['void'])


class VoidGuardTests(LedgerVisibilityTestBase):
    """已作废台账只读边界与作废操作权限。"""

    def _void(self, ledger_id, client=None, reason='整单填错'):
        client = client or self.client
        return post_json(client, '%s/%s/void/' % (LEDGERS_URL, ledger_id),
                         {'reason': reason})

    def test_void_requires_reason(self):
        """作废必须填写原因（空原因拒绝，状态不变）。"""
        ledger = self.make_manual_ledger('completed')
        resp = self._void(ledger.id, reason='   ')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(OperationLedger.objects.get(pk=ledger.id).status, 'completed')

    def test_void_requires_del_permission(self):
        """无 ledger.del 权限：作废被拒绝（后端独立校验，不止隐藏按钮）。"""
        perms = [code for code in ALL_LEDGER_PERMS if code != P_LED_DEL]
        limited = make_user('void_no_del', perms=perms)
        ledger = self.make_manual_ledger('completed')
        resp = self._void(ledger.id, client=make_client(limited))
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(OperationLedger.objects.get(pk=ledger.id).status, 'completed')

    def test_cross_tenant_void_rejected(self):
        """跨租户作废：按台账不存在拒绝，租户隔离独立于筛选可见性。"""
        other = make_user('void_other_tenant', tenant_id='tenant_other',
                          perms=ALL_LEDGER_PERMS)
        ledger = self.make_manual_ledger('completed')
        resp = self._void(ledger.id, client=make_client(other))
        self.assertTrue(resp.json().get('error'))
        self.assertIn('不存在', resp.json()['error'])
        self.assertEqual(OperationLedger.objects.get(pk=ledger.id).status, 'completed')

    def test_voided_ledger_is_read_only(self):
        """已作废只读：编辑/完成/更正/删除/上传附件全被拒绝（查看与作废信息保留）。"""
        ledger = self.make_manual_ledger('completed')
        resp = self._void(ledger.id)
        self.assertFalse(resp.json().get('error'), resp.json())
        ledger_id = ledger.id

        # 编辑表头/明细
        resp = self.client.put('%s/%s/' % (LEDGERS_URL, ledger_id), {},
                               content_type='application/json')
        self.assertTrue(resp.json().get('error'), resp.json())
        # 再次完成填写
        resp = post_json(self.client, '%s/%s/complete/' % (LEDGERS_URL, ledger_id), {})
        self.assertTrue(resp.json().get('error'))
        # 更正（仅已完成可更正）
        resp = post_json(self.client, '%s/%s/correct/' % (LEDGERS_URL, ledger_id),
                         {'reason': '试改', 'value_text': '改'})
        self.assertTrue(resp.json().get('error'))
        self.assertIn('已完成', resp.json()['error'])
        # 物理删除（作废信息须保留）
        resp = self.client.delete('%s/%s/' % (LEDGERS_URL, ledger_id))
        self.assertTrue(resp.json().get('error'))
        # 上传附件（编辑类写操作）
        resp = self.client.post('%s/%s/attachments/' % (LEDGERS_URL, ledger_id))
        self.assertTrue(resp.json().get('error'))
        self.assertIn('当前状态不允许', resp.json()['error'])
        # 台账与作废信息仍在，详情可查看（只读可看）
        saved = OperationLedger.objects.get(pk=ledger_id)
        self.assertEqual(saved.status, 'void')
        self.assertEqual(saved.void_reason, '整单填错')
        self.assertIsNotNone(saved.voided_at)
        self.assertEqual(saved.voided_by_id, self.user.id)
        resp = self.client.get('%s/%s/' % (LEDGERS_URL, ledger_id))
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(resp.json()['data']['status'], 'void')
