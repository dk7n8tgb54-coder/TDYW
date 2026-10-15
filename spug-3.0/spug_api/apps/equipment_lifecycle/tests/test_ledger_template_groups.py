# -*- coding: utf-8 -*-
"""维护台账"按模板查看"分组（2026-10-11）行为测试。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）：
- 分组身份 = 创建来源 + 来源模板主键：同模板 v1/v2 台账归同一组，同名不同
  ID 模板分别成组，手工补录单独成组不混入；
- 组统计（总数/各状态/最近执行日期）由后端聚合，不受组内与组列表分页影响；
- 模板改名/停用后历史台账仍可在原组查到（组名取当前名，行内为创建时版本
  快照）；模板为逻辑删除，无物理删除路径；
- 台账类型以模板为准：模板 ledger_type 创建后不可修改，组内类型一致；
- 租户隔离：组列表、组内列表均按租户过滤，跨租户组键一律拒绝。
"""
from django.test import TestCase

from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplate,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.models import (
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_MANUAL,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_REVIEWED,
    LEDGER_STATUS_SUBMITTED,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
)
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_user
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import ALL_LEDGER_PERMS

GROUPS_URL = URL_PREFIX + '/ledgers/template-groups/'


def group_ledgers_url(group_key):
    return '%s%s/ledgers/' % (GROUPS_URL, group_key)


class TemplateGroupTestBase(TestCase):
    """公共夹具：双租户用户（client 必须在 setUp 创建）。"""

    def setUp(self):
        self.user = make_user('tpl_group_op', perms=ALL_LEDGER_PERMS)
        self.client = make_client(self.user)
        self.other_user = make_user('tpl_group_other', tenant_id='tenant-b',
                                    perms=ALL_LEDGER_PERMS)
        self.other_client = make_client(self.other_user)
        self._ledger_seq = 0

    def make_template(self, name, ledger_type=LEDGER_TYPE_WEEK_MONTH, user=None, **kwargs):
        defaults = dict(
            name=name, ledger_type=ledger_type, is_active=True,
            created_by=user or self.user, tenant_id=(user or self.user).tenant_id)
        defaults.update(kwargs)
        return OperationLedgerExcelTemplate.objects.create(**defaults)

    def make_version(self, template, version_no, name_snapshot=None, user=None):
        return OperationLedgerExcelTemplateVersion.objects.create(
            template=template, version_no=version_no,
            template_name_snapshot=name_snapshot if name_snapshot is not None else template.name,
            source_filename='t%s.xlsx' % version_no, source_hash='hash-%s' % version_no,
            layout='', bindings='', field_count=0,
            published_by=user or self.user, tenant_id=template.tenant_id)

    def make_excel_ledger(self, version, executed_date='2026-10-01',
                          status=LEDGER_STATUS_DRAFT, user=None):
        self._ledger_seq += 1
        user = user or self.user
        ledger = OperationLedger.objects.create(
            ledger_no='EL-TG-%04d' % self._ledger_seq,
            ledger_type=version.template.ledger_type,
            executed_date=executed_date, status=status,
            created_from=LEDGER_FROM_EXCEL, created_by=user, tenant_id=user.tenant_id)
        OperationLedgerExcelRecord.objects.create(
            ledger=ledger, version=version, tenant_id=user.tenant_id)
        return ledger

    def make_manual_ledger(self, executed_date='2026-10-02',
                           status=LEDGER_STATUS_DRAFT, ledger_type=LEDGER_TYPE_WEEK_MONTH,
                           user=None):
        self._ledger_seq += 1
        user = user or self.user
        return OperationLedger.objects.create(
            ledger_no='EL-TG-%04d' % self._ledger_seq,
            ledger_type=ledger_type, executed_date=executed_date, status=status,
            created_from=LEDGER_FROM_MANUAL, created_by=user, tenant_id=user.tenant_id)

    @staticmethod
    def ok_data(resp):
        """json_response 成功体为 {data: <payload>, error: ''}，取业务载荷。"""
        body = resp.json()
        assert not body.get('error'), body
        return body['data']

    def fetch_group_rows(self, client=None, **params):
        """组列表业务载荷：分页 dict 再取 data 数组。"""
        return self.ok_data((client or self.client).get(GROUPS_URL, params))['data']

    def fetch_groups(self, client=None, **params):
        return (client or self.client).get(GROUPS_URL, params)


class TemplateGroupingTests(TemplateGroupTestBase):
    """分组身份：版本归组、同名分组、手工单独成组。"""

    def test_same_template_versions_grouped_together(self):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        v2 = self.make_version(template, 2)
        self.make_excel_ledger(v1, executed_date='2026-10-05')
        self.make_excel_ledger(v2, executed_date='2026-10-08')
        data = self.fetch_group_rows(ledger_type=LEDGER_TYPE_WEEK_MONTH)
        self.assertEqual(len(data), 1)
        group = data[0]
        self.assertEqual(group['group_key'], str(template.id))
        self.assertEqual(group['template_id'], template.id)
        self.assertEqual(group['template_name'], '信道维护台账')
        self.assertEqual(group['total'], 2)

    def test_same_name_templates_form_separate_groups(self):
        t1 = self.make_template('同名模板')
        t2 = self.make_template('同名模板')
        self.make_excel_ledger(self.make_version(t1, 1))
        self.make_excel_ledger(self.make_version(t2, 1))
        data = self.fetch_group_rows(ledger_type=LEDGER_TYPE_WEEK_MONTH)
        self.assertEqual(len(data), 2)
        self.assertEqual({g['template_id'] for g in data}, {t1.id, t2.id})
        self.assertEqual([g['total'] for g in data], [1, 1])

    def test_manual_ledgers_in_own_group_not_in_excel_groups(self):
        template = self.make_template('信道维护台账')
        self.make_excel_ledger(self.make_version(template, 1))
        manual = self.make_manual_ledger()
        data = self.fetch_group_rows(ledger_type=LEDGER_TYPE_WEEK_MONTH)
        self.assertEqual(len(data), 2)
        manual_groups = [g for g in data if g['group_key'] == 'manual']
        self.assertEqual(len(manual_groups), 1)
        self.assertEqual(manual_groups[0]['template_name'], '无模板/临时补录')
        self.assertIsNone(manual_groups[0]['template_id'])
        self.assertEqual(manual_groups[0]['total'], 1)
        excel_group = [g for g in data if g['group_key'] == str(template.id)][0]
        self.assertEqual(excel_group['total'], 1)
        # 组内列表同样互不混入
        rows = self.ok_data(
            self.client.get(group_ledgers_url('manual'),
                            {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))['data']
        self.assertEqual([r['id'] for r in rows], [manual.id])
        self.assertTrue(all(r['source_type'] == 'manual' for r in rows))

    def test_status_counts_and_last_executed_date(self):
        template = self.make_template('状态统计模板')
        v1 = self.make_version(template, 1)
        self.make_excel_ledger(v1, '2026-10-01', status=LEDGER_STATUS_DRAFT)
        self.make_excel_ledger(v1, '2026-10-05', status=LEDGER_STATUS_SUBMITTED)
        self.make_excel_ledger(v1, '2026-10-08', status=LEDGER_STATUS_REVIEWED)
        self.make_excel_ledger(v1, '2026-10-03', status=LEDGER_STATUS_VOID)
        group = self.fetch_group_rows(ledger_type=LEDGER_TYPE_WEEK_MONTH)[0]
        self.assertEqual(group['total'], 4)
        self.assertEqual(group['draft'], 1)
        self.assertEqual(group['submitted'], 1)
        self.assertEqual(group['reviewed'], 1)
        self.assertEqual(group['void'], 1)
        self.assertEqual(group['returned'], 0)
        self.assertEqual(str(group['last_executed_date']), '2026-10-08')


class TemplateGroupHistoryTests(TemplateGroupTestBase):
    """历史可追溯：改名/停用后组仍在，行内为创建时版本快照。"""

    def test_rename_and_deactivate_keep_group_queryable(self):
        template = self.make_template('旧模板名')
        v1 = self.make_version(template, 1, name_snapshot='旧模板名')
        ledger = self.make_excel_ledger(v1)
        template.name = '新模板名'
        template.is_active = False
        template.save(update_fields=['name', 'is_active'])
        group = self.fetch_group_rows(ledger_type=LEDGER_TYPE_WEEK_MONTH)[0]
        self.assertEqual(group['group_key'], str(template.id))
        self.assertEqual(group['template_name'], '新模板名')
        self.assertFalse(group['is_active'])
        body = self.ok_data(self.client.get(
            group_ledgers_url(template.id),
            {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        self.assertEqual(body['group_name'], '新模板名')
        self.assertEqual([r['id'] for r in body['data']], [ledger.id])
        # 行内模板名称为创建时版本快照（不回写新名）
        self.assertEqual(body['data'][0]['source_template_name'], '旧模板名')
        self.assertEqual(body['data'][0]['source_version_no'], 1)

    def test_group_rows_show_version_used_at_creation(self):
        template = self.make_template('版本展示模板')
        v1 = self.make_version(template, 1)
        v2 = self.make_version(template, 2)
        self.make_excel_ledger(v1, '2026-10-01')
        self.make_excel_ledger(v2, '2026-10-02')
        body = self.ok_data(self.client.get(
            group_ledgers_url(template.id), {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        by_version = {r['source_version_no']: r for r in body['data']}
        self.assertEqual(set(by_version), {1, 2})
        self.assertEqual(by_version[1]['source_template_name'], '版本展示模板')
        self.assertEqual(by_version[2]['source_template_name'], '版本展示模板')

    def test_type_mismatch_rejected(self):
        template = self.make_template('周月模板')
        self.make_excel_ledger(self.make_version(template, 1))
        resp = self.client.get(
            group_ledgers_url(template.id), {'ledger_type': LEDGER_TYPE_SEASONAL})
        self.assertEqual(resp.json()['error'], '台账类型与模板不匹配')


class TemplateGroupFilterTests(TemplateGroupTestBase):
    """类型筛选、统计与分页互不影响。"""

    def setUp(self):
        super().setUp()
        self.week_template = self.make_template('周月模板')
        self.season_template = self.make_template('季维护模板', ledger_type=LEDGER_TYPE_SEASONAL)
        self.make_excel_ledger(self.make_version(self.week_template, 1), '2026-10-05')
        self.make_excel_ledger(self.make_version(self.season_template, 1), '2026-10-06')
        self.make_manual_ledger('2026-10-07')

    def test_ledger_type_filter(self):
        data = self.fetch_group_rows(ledger_type=LEDGER_TYPE_WEEK_MONTH)
        self.assertEqual({g['group_key'] for g in data},
                         {str(self.week_template.id), 'manual'})
        data = self.fetch_group_rows(ledger_type=LEDGER_TYPE_SEASONAL)
        self.assertEqual([g['group_key'] for g in data], [str(self.season_template.id)])
        resp = self.fetch_groups(ledger_type='inspection')
        self.assertIn('不再支持', resp.json()['error'])
        resp = self.fetch_groups()
        self.assertTrue(resp.json().get('error'))

    def test_group_statistics_not_affected_by_pagination(self):
        # page_size=1 强制分页：每页组统计仍完整，total 为组数
        body = self.ok_data(self.fetch_groups(
            ledger_type=LEDGER_TYPE_WEEK_MONTH, page=1, page_size=1))
        self.assertEqual(body['total'], 2)
        self.assertEqual(len(body['data']), 1)
        first = body['data'][0]
        self.assertEqual(first['total'], 1)
        body2 = self.ok_data(self.fetch_groups(
            ledger_type=LEDGER_TYPE_WEEK_MONTH, page=2, page_size=1))
        self.assertEqual(len(body2['data']), 1)
        self.assertNotEqual(body2['data'][0]['group_key'], first['group_key'])

    def test_filters_apply_to_group_statistics_and_rows(self):
        ledger = self.make_excel_ledger(
            self.make_version(self.week_template, 2), '2026-10-09')
        data = self.fetch_group_rows(
            ledger_type=LEDGER_TYPE_WEEK_MONTH, status=LEDGER_STATUS_SUBMITTED)
        # 状态筛选下仅剩提交态台账所在组，统计只计提交态
        week_group = [g for g in data if g['group_key'] == str(self.week_template.id)]
        self.assertEqual(week_group, [])
        ledger.status = LEDGER_STATUS_SUBMITTED
        ledger.save(update_fields=['status'])
        data = self.fetch_group_rows(
            ledger_type=LEDGER_TYPE_WEEK_MONTH, status=LEDGER_STATUS_SUBMITTED)
        week_group = [g for g in data if g['group_key'] == str(self.week_template.id)][0]
        self.assertEqual(week_group['total'], 1)
        # 组内列表：状态/编号关键词/日期范围筛选
        body = self.ok_data(self.client.get(
            group_ledgers_url(self.week_template.id), {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': LEDGER_STATUS_SUBMITTED}))
        self.assertEqual([r['id'] for r in body['data']], [ledger.id])
        body = self.ok_data(self.client.get(
            group_ledgers_url(self.week_template.id), {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'keyword': 'TG'}))
        self.assertEqual(body['total'], 2)
        body = self.ok_data(self.client.get(
            group_ledgers_url(self.week_template.id), {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                'executed_from': '2026-10-06', 'executed_to': '2026-10-09'}))
        self.assertEqual([r['id'] for r in body['data']], [ledger.id])

    def test_group_ledgers_pagination_and_order(self):
        v1 = self.make_version(self.week_template, 2)
        # setUp 已有 2026-10-05 一张；新造三张更晚日期，组内共 4 张
        ledgers = [self.make_excel_ledger(v1, '2026-10-2%d' % (i + 1)) for i in range(3)]
        body = self.ok_data(self.client.get(
            group_ledgers_url(self.week_template.id),
            {'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'page': 1, 'page_size': 2}))
        self.assertEqual(body['total'], 4)
        self.assertEqual(len(body['data']), 2)
        # 执行日期倒序
        self.assertEqual([r['id'] for r in body['data']],
                         [ledgers[2].id, ledgers[1].id])
        body = self.ok_data(self.client.get(
            group_ledgers_url(self.week_template.id),
            {'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'page': 2, 'page_size': 2}))
        # 第 2 页剩新造最早一张 + setUp 的 2026-10-05 台账
        self.assertEqual([r['id'] for r in body['data']][0], ledgers[0].id)
        self.assertEqual(len(body['data']), 2)
        self.assertEqual(body['data'][1]['executed_date'], '2026-10-05')

    def test_invalid_group_key_rejected(self):
        resp = self.client.get(group_ledgers_url('abc'),
                               {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')
        resp = self.client.get(group_ledgers_url('999999'),
                               {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')
        resp = self.client.get(group_ledgers_url('manual'), {})
        self.assertTrue(resp.json().get('error'))


class TemplateGroupTenantAndPermissionTests(TemplateGroupTestBase):
    """租户隔离与权限。"""

    def test_groups_are_tenant_scoped(self):
        template = self.make_template('A租户模板')
        self.make_excel_ledger(self.make_version(template, 1))
        self.make_manual_ledger()
        data = self.fetch_group_rows(
            client=self.other_client, ledger_type=LEDGER_TYPE_WEEK_MONTH)
        self.assertEqual(data, [])

    def test_cross_tenant_group_ledgers_rejected(self):
        template = self.make_template('A租户模板')
        self.make_excel_ledger(self.make_version(template, 1))
        resp = self.other_client.get(
            group_ledgers_url(template.id), {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')

    def test_permission_denied_without_view_perm(self):
        template = self.make_template('无权限模板')
        self.make_excel_ledger(self.make_version(template, 1))
        viewer = make_user('tpl_viewer', tenant_id='viewer-tenant', perms=[])
        viewer_client = make_client(viewer)
        resp = viewer_client.get(GROUPS_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(resp.json()['error'], '权限拒绝')
        resp = viewer_client.get(
            group_ledgers_url(template.id), {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(resp.json()['error'], '权限拒绝')


class TemplateGroupRegressionTests(TemplateGroupTestBase):
    """既有视图回归哨兵：新增端点不改变按周期视图与统一列表行为。"""

    def test_period_groups_and_unified_list_still_work(self):
        template = self.make_template('周月模板')
        self.make_excel_ledger(self.make_version(template, 1), '2026-10-05')
        self.make_manual_ledger('2026-10-06')
        period_groups = self.client.get(
            URL_PREFIX + '/ledgers/period-groups/',
            {'ledger_type': LEDGER_TYPE_WEEK_MONTH}).json()['data']['data']
        self.assertEqual(period_groups[0]['total'], 2)
        unified = self.client.get(URL_PREFIX + '/ledgers/', {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH}).json()['data']
        self.assertEqual(unified['total'], 2)
        sources = {r['source_type'] for r in unified['data']}
        self.assertEqual(sources, {'excel', 'manual'})
