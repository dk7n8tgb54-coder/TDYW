# -*- coding: utf-8 -*-
"""维护台账"翻阅台账"（2026-10-18）行为测试。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）：
- 翻阅清单 = 模板组内符合筛选的台账按翻阅顺序一次性返回（网页内连续翻阅，
  不以下载 PDF 代替）；筛选口径与组内列表一致（默认不含已作废，
  status=void 仅已作废，status=all 全部，keyword 编号模糊，执行日期范围）；
- 排序以计划维护期次为主（期次起始日期升序），无期次标记的历史台账回退
  按实际执行日期，两者皆缺排最后；同键内 ID 兜底保证顺序稳定；
- 同一期次多张台账（作废后补建并存）全部保留、相邻排列，逐张可翻不漏；
- 清单量级为组内全部条目：组内列表分页（20 条）只是展示形态，翻页必须
  能跨过分页边界覆盖全部条目；
- 每条条目携带该台账创建时引用的版本号（版本快照随台账，不随模板当前
  版本漂移）；manual 组无模板版式不支持翻阅；跨租户组键一律拒绝。
"""
from datetime import date

from django.test import TestCase

from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplate,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.models import (
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_MANUAL,
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
)
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_user
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import ALL_LEDGER_PERMS

GROUPS_URL = URL_PREFIX + '/ledgers/template-groups'


def browse_url(group_key):
    return '%s/%s/browse/' % (GROUPS_URL, group_key)


class TemplateGroupBrowseTestBase(TestCase):
    """公共夹具：双租户用户 + 模板/版本/台账辅助（client 必须在 setUp 创建）。"""

    def setUp(self):
        self.user = make_user('tg_browse_op', perms=ALL_LEDGER_PERMS)
        self.client = make_client(self.user)
        self.other_user = make_user('tg_browse_other', tenant_id='tenant-b',
                                    perms=ALL_LEDGER_PERMS)
        self.other_client = make_client(self.other_user)
        self._ledger_seq = 0

    def make_template(self, name, ledger_type=LEDGER_TYPE_WEEK_MONTH, user=None, **kwargs):
        defaults = dict(
            name=name, ledger_type=ledger_type, is_active=True,
            created_by=user or self.user, tenant_id=(user or self.user).tenant_id)
        defaults.update(kwargs)
        return OperationLedgerExcelTemplate.objects.create(**defaults)

    def make_version(self, template, version_no, user=None):
        return OperationLedgerExcelTemplateVersion.objects.create(
            template=template, version_no=version_no,
            template_name_snapshot=template.name,
            source_filename='t%s.xlsx' % version_no, source_hash='hash-%s' % version_no,
            layout='', bindings='', field_count=0,
            published_by=user or self.user, tenant_id=template.tenant_id)

    def make_excel_ledger(self, version, executed_date='2026-10-01',
                          status=LEDGER_STATUS_DRAFT, maintenance_period='',
                          user=None):
        self._ledger_seq += 1
        user = user or self.user
        ledger = OperationLedger.objects.create(
            ledger_no='EL-TB-%04d' % self._ledger_seq,
            ledger_type=version.template.ledger_type,
            executed_date=executed_date, status=status,
            maintenance_period=maintenance_period,
            created_from=LEDGER_FROM_EXCEL, created_by=user, tenant_id=user.tenant_id)
        OperationLedgerExcelRecord.objects.create(
            ledger=ledger, version=version, tenant_id=user.tenant_id)
        return ledger

    @staticmethod
    def ok_data(resp):
        """json_response 成功体为 {data: <payload>, error: ''}，取业务载荷。"""
        body = resp.json()
        assert not body.get('error'), body
        return body['data']

    def browse(self, group_key, client=None, **params):
        return self.ok_data((client or self.client).get(browse_url(group_key), params))

    @staticmethod
    def entry_ids(data):
        return [entry['id'] for entry in data['entries']]


class BrowseOrderingTests(TemplateGroupBrowseTestBase):
    """翻阅顺序：期次为主、历史回退、ID 兜底稳定、同期多张相邻。"""

    def test_order_by_period_then_executed_date_then_id(self):
        template = self.make_template('信道维护台账')
        version = self.make_version(template, 1)
        # A：9 月期次标记（期次起始 2026-09-01，执行日期空）
        ledger_a = self.make_excel_ledger(
            version, executed_date=None, maintenance_period='2026-09')
        # C：无期次标记，执行日期 2026-09-15 → 按执行日期推导归入 9 月期次
        ledger_c = self.make_excel_ledger(
            version, executed_date='2026-09-15', maintenance_period='')
        # B/E：同周期次标记（10 月第一周），B 先建 E 后建（ID 兜底稳定）
        ledger_b = self.make_excel_ledger(
            version, executed_date='2026-10-08', maintenance_period='2026-10-05')
        ledger_e = self.make_excel_ledger(
            version, executed_date='2026-10-09', maintenance_period='2026-10-05')
        # D：无期次标记也无执行日期 → 排最后
        ledger_d = self.make_excel_ledger(
            version, executed_date=None, maintenance_period='')
        data = self.browse(template.id)
        self.assertEqual(data['total'], 5)
        self.assertEqual(
            self.entry_ids(data),
            [ledger_a.id, ledger_c.id, ledger_b.id, ledger_e.id, ledger_d.id])
        # 期次标签随条目下发：标记期次完整展示，历史台账标注归档来源
        by_id = {entry['id']: entry for entry in data['entries']}
        self.assertEqual(by_id[ledger_b.id]['period_label'],
                         '每周｜2026-10-05 ~ 2026-10-11')
        self.assertFalse(by_id[ledger_b.id]['period_is_derived'])
        self.assertEqual(by_id[ledger_c.id]['period_label'], '每月｜2026年9月')
        self.assertTrue(by_id[ledger_c.id]['period_is_derived'])
        self.assertEqual(by_id[ledger_d.id]['period_label'], '未标注期次')
        self.assertEqual(by_id[ledger_d.id]['period_key'], '')

    def test_rebuilt_same_period_ledgers_all_browsable_adjacent(self):
        """作废后补建产生的同一期多张台账全部保留、相邻排列，逐张可翻。"""
        template = self.make_template('月度维护台账')
        version = self.make_version(template, 1)
        # 同一期次三张（作废→补建场景）：有效与补建并存，作废默认隐藏
        first = self.make_excel_ledger(
            version, executed_date='2026-10-03', status=LEDGER_STATUS_COMPLETED,
            maintenance_period='2026-10')
        rebuilt = self.make_excel_ledger(
            version, executed_date=None, status=LEDGER_STATUS_DRAFT,
            maintenance_period='2026-10')
        voided = self.make_excel_ledger(
            version, executed_date='2026-10-02', status=LEDGER_STATUS_VOID,
            maintenance_period='2026-10')
        # 默认范围（不含已作废）：两张有效相邻、按创建顺序（ID）稳定排序
        data = self.browse(template.id)
        self.assertEqual(self.entry_ids(data), [first.id, rebuilt.id])
        # 显式筛选"全部"：三张全部出现（作废的不漏，仍按期次相邻、ID 稳定）
        data_all = self.browse(template.id, status='all')
        self.assertEqual(
            self.entry_ids(data_all), [first.id, rebuilt.id, voided.id])
        self.assertEqual(data_all['total'], 3)

    def test_seasonal_period_ordering(self):
        template = self.make_template('季维护台账', ledger_type=LEDGER_TYPE_SEASONAL)
        version = self.make_version(template, 1)
        winter = self.make_excel_ledger(
            version, executed_date='2026-11-10', maintenance_period='2026-冬春')
        summer = self.make_excel_ledger(
            version, executed_date='2026-08-10', maintenance_period='2026-夏秋')
        data = self.browse(template.id)
        # 夏秋航季在前（3 月末~10 月末），冬春在后；航季标签含起止日期
        self.assertEqual(self.entry_ids(data), [summer.id, winter.id])
        labels = [entry['period_label'] for entry in data['entries']]
        self.assertEqual(
            labels,
            ['2026年夏秋季（2026-03-29 ~ 2026-10-24）',
             '2026年冬春季（2026-10-25 ~ 2027-03-27）'])


class BrowseFilterScopeTests(TemplateGroupBrowseTestBase):
    """翻阅范围与组内列表同口径：状态（默认不含已作废）/编号/日期范围。"""

    def setUp(self):
        super().setUp()
        self.template = self.make_template('信道维护台账')
        self.version = self.make_version(self.template, 1)
        self.draft = self.make_excel_ledger(
            self.version, executed_date='2026-10-08', status=LEDGER_STATUS_DRAFT)
        self.completed = self.make_excel_ledger(
            self.version, executed_date='2026-10-12', status=LEDGER_STATUS_COMPLETED)
        self.voided = self.make_excel_ledger(
            self.version, executed_date='2026-10-15', status=LEDGER_STATUS_VOID)

    def test_default_scope_excludes_void(self):
        data = self.browse(self.template.id)
        self.assertEqual(
            self.entry_ids(data), [self.draft.id, self.completed.id])

    def test_void_scope_and_all_scope(self):
        data_void = self.browse(self.template.id, status='void')
        self.assertEqual(self.entry_ids(data_void), [self.voided.id])
        data_all = self.browse(self.template.id, status='all')
        self.assertEqual(
            self.entry_ids(data_all),
            [self.draft.id, self.completed.id, self.voided.id])

    def test_keyword_filters_by_ledger_no(self):
        data = self.browse(self.template.id, keyword=self.completed.ledger_no)
        self.assertEqual(self.entry_ids(data), [self.completed.id])

    def test_executed_date_range_filters(self):
        data = self.browse(
            self.template.id, executed_from='2026-10-10', executed_to='2026-10-12')
        # 草稿（10-08）出范围；已作废（10-15）出范围且默认被排除
        self.assertEqual(self.entry_ids(data), [self.completed.id])
        # 日期命中的已作废台账在默认范围仍隐藏，显式"全部"才进入翻阅
        empty = self.browse(self.template.id, executed_from='2026-10-13')
        self.assertEqual(empty['entries'], [])
        void_in_range = self.browse(
            self.template.id, status='all', executed_from='2026-10-13')
        self.assertEqual(self.entry_ids(void_in_range), [self.voided.id])

    def test_browse_list_covers_beyond_group_list_pagination(self):
        """组内列表分页（20 条）不限制翻阅：夹具 3 张 + 25 张全部进入翻阅清单。"""
        for _ in range(25):
            self.make_excel_ledger(
                self.version, executed_date='2026-09-%02d' % (self._ledger_seq % 28 + 1))
        group_rows = self.ok_data(
            self.client.get(
                '%s/%s/ledgers/' % (GROUPS_URL, self.template.id),
                {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        # 组内列表默认页 20 条（分页只是展示形态）；已作废不在默认范围
        self.assertEqual(group_rows['total'], 27)
        self.assertEqual(len(group_rows['data']), 20)
        data = self.browse(self.template.id)
        self.assertEqual(data['total'], 27)
        self.assertEqual(len(data['entries']), 27)
        # 清单覆盖全量（跨过分页边界），无重复无遗漏
        ids = self.entry_ids(data)
        self.assertEqual(len(set(ids)), 27)


class BrowseSnapshotAndGuardTests(TemplateGroupBrowseTestBase):
    """版本快照随台账、manual 组拒绝、类型不匹配拒绝、租户隔离与权限。"""

    def test_entries_carry_own_version_snapshot_no(self):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        v2 = self.make_version(template, 2)
        old = self.make_excel_ledger(v1, executed_date='2026-09-05')
        new = self.make_excel_ledger(v2, executed_date='2026-10-05')
        data = self.browse(template.id)
        by_id = {entry['id']: entry for entry in data['entries']}
        self.assertEqual(by_id[old.id]['source_version_no'], 1)
        self.assertEqual(by_id[new.id]['source_version_no'], 2)

    def test_template_rename_keeps_group_and_snapshot(self):
        template = self.make_template('旧名称台账')
        version = self.make_version(template, 1)
        self.make_excel_ledger(version, executed_date='2026-09-05')
        template.name = '新名称台账'
        template.save()
        data = self.browse(template.id)
        self.assertEqual(data['group_name'], '新名称台账')
        self.assertEqual(data['total'], 1)

    def test_manual_group_rejected(self):
        self.make_template('模板A')
        resp = self.client.get('%s/manual/browse/' % GROUPS_URL)
        self.assertEqual(
            resp.json()['error'], '无模板/临时补录台账没有模板版式，不支持翻阅')

    def test_unknown_group_key_rejected(self):
        resp = self.client.get('%s/99999/browse/' % GROUPS_URL)
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')
        resp = self.client.get('%s/abc/browse/' % GROUPS_URL)
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')

    def test_ledger_type_mismatch_rejected(self):
        template = self.make_template('季维护模板', ledger_type=LEDGER_TYPE_SEASONAL)
        resp = self.client.get(
            '%s/%s/browse/' % (GROUPS_URL, template.id),
            {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(resp.json()['error'], '台账类型与模板不匹配')

    def test_tenant_isolation(self):
        template = self.make_template('信道维护台账')
        version = self.make_version(template, 1)
        self.make_excel_ledger(version, executed_date='2026-09-05')
        other_template = self.make_template(
            'B租户模板', user=self.other_user)
        other_version = self.make_version(other_template, 1, user=self.other_user)
        self.make_excel_ledger(other_version, executed_date='2026-09-06',
                               user=self.other_user)
        # B 租户访问 A 租户组键：一律拒绝（不泄露存在性）
        resp = self.other_client.get('%s/%s/browse/' % (GROUPS_URL, template.id))
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')
        # A 租户清单只含 A 租户台账
        data = self.browse(template.id)
        self.assertEqual(data['total'], 1)
        # B 租户自己的组正常翻阅
        data_b = self.browse(other_template.id, client=self.other_client)
        self.assertEqual(data_b['total'], 1)

    def test_requires_view_permission(self):
        template = self.make_template('信道维护台账')
        version = self.make_version(template, 1)
        self.make_excel_ledger(version, executed_date='2026-09-05')
        viewer = make_user('tg_browse_view', perms=['equipment_lifecycle.ledger.view'])
        data = self.browse(template.id, client=make_client(viewer))
        self.assertEqual(data['total'], 1)
        no_perm = make_user('tg_browse_none', perms=[])
        resp = make_client(no_perm).get('%s/%s/browse/' % (GROUPS_URL, template.id))
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_manual_ledgers_never_in_template_browse(self):
        """手工补录台账不属于任何模板组：不混入模板翻阅清单。"""
        template = self.make_template('信道维护台账')
        version = self.make_version(template, 1)
        self.make_excel_ledger(version, executed_date='2026-09-05')
        self._ledger_seq += 1
        OperationLedger.objects.create(
            ledger_no='EL-TB-M%04d' % self._ledger_seq,
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            executed_date=date(2026, 9, 6), status=LEDGER_STATUS_DRAFT,
            created_from=LEDGER_FROM_MANUAL, created_by=self.user,
            tenant_id=self.user.tenant_id)
        data = self.browse(template.id)
        self.assertEqual(data['total'], 1)
