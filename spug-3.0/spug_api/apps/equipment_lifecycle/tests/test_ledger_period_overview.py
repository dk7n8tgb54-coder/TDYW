# -*- coding: utf-8 -*-
"""填写列表"本期工作"优化（2026-10-14）行为测试。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）：
- 本期工作概览 /ledgers/period-overview/：周月维护给 本周+本月 两块、季维护
  给本航季一块；应填/待生成按模板生成规则计算（不统计已有台账冒充），
  待填写/已完成为本期台账真实状态数量；待生成生成后归零；
- 周期分组 /ledgers/period-groups/ 修复与增强：台账编号 keyword 筛选真实
  生效（此前前端已发送但视图未读取）；分页按期次组切片；组内五状态统计
  与可见行一致；is_current 标记本期组；分组标题为期次完整标签；
- 行级期次展示：明确期次直接展示；历史台账（无期次标记）按执行日期归档
  并标注来源，不改写历史记录；两者皆缺显示"未标注期次"；
- 跨月周归属周一所在月份；一周内多张周台账可按周一日期辨认；
- 两个填写列表（周月维护/季维护）概览互不串扰；租户隔离。
"""
import tempfile
from datetime import datetime

from django.test import TestCase, override_settings

from apps.equipment_lifecycle import ledger_period_services
from apps.equipment_lifecycle.excel_sample_template import build_acceptance_sample_xlsx
from apps.equipment_lifecycle.models import (
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
)
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_system, make_user
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    ALL_TEMPLATE_PERMS,
    post_json,
)

LEDGERS_URL = URL_PREFIX + '/ledgers'
OVERVIEW_URL = LEDGERS_URL + '/period-overview/'
GROUPS_URL = LEDGERS_URL + '/period-groups/'
GENERATE_URL = LEDGERS_URL + '/period-generate/'
TPL_URL = URL_PREFIX + '/excel-templates'

# 每次测试进程使用独立临时目录：样例 xlsx 字节含时间戳非确定性，
# 复用固定目录会让 --keepdb 复用的模板 ID 撞上旧版本文件哈希（发布冲突）
STORAGE_DIR = tempfile.mkdtemp(prefix='el_period_overview_')


def fake_today(year, month, day):
    """把"今天"固定为指定日期（service 内 timezone.now）。"""
    return mock_timezone_now(year, month, day)


def mock_timezone_now(year, month, day):
    from unittest import mock
    return mock.patch.object(
        ledger_period_services.timezone, 'now',
        return_value=datetime(year, month, day, 10, 0, 0))


class OverviewTestBase(TestCase):
    """公共夹具：双系统 + 模板发布辅助（client 必须在 setUp 创建）。"""

    def setUp(self):
        self.user = make_user('ov_op', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.client = make_client(self.user)
        self.system_a = make_system(self.user, system_code='SYS-A', name='DVOR系统')
        self.system_b = make_system(self.user, system_code='SYS-B', name='ILS系统')
        self.other_user = make_user('ov_other', tenant_id='tenant-b',
                                    perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.other_client = make_client(self.other_user)
        self.other_system = make_system(
            self.other_user, tenant_id='tenant-b', system_code='SYS-B2', name='B租户系统')
        self._storage_override = override_settings(EL_EXCEL_TEMPLATE_BASE_DIR=STORAGE_DIR)
        self._storage_override.enable()
        self.addCleanup(self._storage_override.disable)

    def publish_template(self, name='信道Excel维护台账', ledger_type=LEDGER_TYPE_WEEK_MONTH,
                         system=None, generation_period='', client=None, publish=True):
        """上传→绑定→（发布）→配置生成属性，返回模板详情 dict（全部走真实接口）。"""
        client = client or self.client
        from django.core.files.uploadedfile import SimpleUploadedFile
        import json as _json
        import uuid
        resp = client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx()),
            'name': name, 'ledger_type': ledger_type,
        })
        template = resp.json()['data']['data']
        bindings = [{
            'field_id': str(uuid.uuid4()), 'sheet_name': '信道维护记录',
            'cell_coordinate': 'C4', 'field_name': 'PS模块', 'input_type': 'status',
            'is_required': True, 'unit': '', 'options': [],
        }]
        resp = client.put('%s/%s/bindings/' % (TPL_URL, template['id']),
                          _json.dumps({'field_bindings': bindings}),
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        if publish:
            resp = client.post('%s/%s/publish/' % (TPL_URL, template['id']))
            self.assertFalse(resp.json().get('error'), resp.json())
        if system is not None or generation_period:
            resp = client.put(
                '%s/%s/generation-config/' % (TPL_URL, template['id']),
                _json.dumps({'system': system.id if system else '',
                             'generation_period': generation_period}),
                content_type='application/json')
            self.assertFalse(resp.json().get('error'), resp.json())
        return template

    def overview(self, ledger_type=LEDGER_TYPE_WEEK_MONTH, client=None, today=None):
        client = client or self.client
        if today:
            with fake_today(*today):
                resp = client.get(OVERVIEW_URL, {'ledger_type': ledger_type})
        else:
            resp = client.get(OVERVIEW_URL, {'ledger_type': ledger_type})
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    @staticmethod
    def block(data, key):
        for item in data['blocks']:
            if item['key'] == key:
                return item
        return None

    def make_ledger(self, ledger_no, status='draft', executed_date=None,
                    maintenance_period='', ledger_type=LEDGER_TYPE_WEEK_MONTH,
                    system=None, tenant_id='default', created_by=None):
        """直接造台账行（状态统计的真实数据源）。"""
        return OperationLedger.objects.create(
            tenant_id=tenant_id,
            ledger_no=ledger_no,
            ledger_type=ledger_type,
            executed_date=executed_date,
            status=status,
            entry_channel='web',
            created_from='manual',
            system=system,
            maintenance_period=maintenance_period,
            created_by=created_by or self.user,
        )


class PeriodGroupsEnhancementTests(OverviewTestBase):
    """周期分组：keyword 修复、分页、三状态统计、本期标记、期次标签。"""

    def setUp(self):
        super().setUp()
        self.make_ledger(
            'EL-WM-20261012-0001', status='draft', executed_date=None,
            maintenance_period='2026-10-12', system=self.system_a)
        self.make_ledger(
            'EL-WM-20261012-0002', status='draft', executed_date=None,
            maintenance_period='2026-10-12', system=self.system_b)
        self.make_ledger(
            'EL-WM-20261001-0003', status='draft', executed_date=None,
            maintenance_period='2026-10', system=self.system_a)
        self.make_ledger(
            'EL-WM-20261001-0004', status='completed', executed_date=None,
            maintenance_period='2026-10', system=self.system_b)
        self.make_ledger(
            'EL-WM-20261001-0005', status='void', executed_date=None,
            maintenance_period='2026-10', system=self.system_a)

    def groups(self, params=None, today=None):
        if today:
            with fake_today(*today):
                resp = self.client.get(GROUPS_URL, params or {})
        else:
            resp = self.client.get(GROUPS_URL, params or {})
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def test_keyword_filter_takes_effect_on_groups(self):
        # 回归：此前前端已发送 keyword 但视图未读取，搜索无效
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                            'keyword': '20261012'})['data']
        self.assertEqual([g['maintenance_period'] for g in data], ['2026-10-12'])
        self.assertEqual(data[0]['total'], 2)
        # 无匹配时不返回任何组
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                            'keyword': 'NOT-EXIST'})['data']
        self.assertEqual(data, [])

    def test_group_status_counts_match_visible_rows(self):
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH})['data']
        by_period = {g['maintenance_period']: g for g in data}
        week = by_period['2026-10-12']
        self.assertEqual(
            {k: week[k] for k in ('total', 'draft', 'completed', 'void')},
            {'total': 2, 'draft': 2, 'completed': 0, 'void': 0})
        month = by_period['2026-10']
        # 默认视图不含已作废（2026-10-17）：组统计与可见行一致
        self.assertEqual(
            {k: month[k] for k in ('total', 'draft', 'completed', 'void')},
            {'total': 2, 'draft': 1, 'completed': 1, 'void': 0})
        # status=void 主动查看已作废；status=all 明确包含已作废
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                            'status': 'all'})['data']
        month_all = {g['maintenance_period']: g for g in data}['2026-10']
        self.assertEqual(
            {k: month_all[k] for k in ('total', 'draft', 'completed', 'void')},
            {'total': 3, 'draft': 1, 'completed': 1, 'void': 1})
        void_only = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                                 'status': 'void'})['data']
        self.assertEqual(
            {k: void_only[0][k] for k in ('total', 'draft', 'completed', 'void')},
            {'total': 1, 'draft': 0, 'completed': 0, 'void': 1})
        # 状态筛选后组内统计与可见行一致
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                            'status': 'completed'})['data']
        self.assertEqual([g['maintenance_period'] for g in data], ['2026-10'])
        self.assertEqual(data[0]['total'], 1)
        self.assertEqual(data[0]['completed'], 1)
        self.assertEqual(data[0]['draft'], 0)

    def test_group_pagination_by_period(self):
        # 再造 2026-08/2026-09 两个月组 → 共 4 个期次组
        self.make_ledger('EL-WM-20260801-0006', status='draft', executed_date=None,
                         maintenance_period='2026-08', system=self.system_a)
        self.make_ledger('EL-WM-20260901-0007', status='draft', executed_date=None,
                         maintenance_period='2026-09', system=self.system_a)
        page = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                            'page': 1, 'page_size': 2}, today=(2026, 10, 14))
        self.assertEqual(page['total'], 4)
        self.assertEqual(page['page'], 1)
        self.assertEqual(page['page_size'], 2)
        # 期次起始日期倒序（周组按周一日期参与排序）；跨页不重复
        self.assertEqual([g['maintenance_period'] for g in page['data']],
                         ['2026-10-12', '2026-10'])
        page2 = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                             'page': 2, 'page_size': 2}, today=(2026, 10, 14))
        self.assertEqual([g['maintenance_period'] for g in page2['data']],
                         ['2026-09', '2026-08'])

    def test_current_period_marked_and_label_format(self):
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH},
                           today=(2026, 10, 14))['data']
        by_period = {g['maintenance_period']: g for g in data}
        self.assertTrue(by_period['2026-10-12']['is_current'])
        self.assertTrue(by_period['2026-10']['is_current'])
        self.assertEqual(by_period['2026-10-12']['period_text'],
                         '每周｜2026-10-12 ~ 2026-10-18')
        self.assertEqual(by_period['2026-10']['period_text'], '每月｜2026年10月')

    def test_cross_month_week_grouped_by_monday_month(self):
        self.make_ledger('EL-WM-20261026-0008', status='draft', executed_date=None,
                         maintenance_period='2026-10-26', system=self.system_a)
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH})['data']
        self.assertIn('2026-10-26', [g['maintenance_period'] for g in data])
        week_group = [g for g in data if g['maintenance_period'] == '2026-10-26'][0]
        self.assertEqual(week_group['period_text'],
                         '每周｜2026-10-26 ~ 2026-11-01')

    def test_row_period_display_for_generated_and_legacy(self):
        # 生成路线：明确期次（用独立系统，避免 setUp 手工壳占位拦截生成）
        gen_system = make_system(self.user, system_code='SYS-G', name='生成系统')
        self.publish_template(system=gen_system, generation_period='weekly')
        with fake_today(2026, 10, 14):
            resp = post_json(self.client, GENERATE_URL,
                             {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertFalse(resp.json().get('error'), resp.json())
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH})['data']
        week = [g for g in data if g['maintenance_period'] == '2026-10-12'][0]
        generated_row = [r for r in week['ledgers'] if r['source_type'] == 'excel'][0]
        self.assertEqual(generated_row['period_label'],
                         '每周｜2026-10-12 ~ 2026-10-18')
        self.assertFalse(generated_row['period_is_derived'])
        self.assertEqual(generated_row['period_source_text'], '')
        # 历史台账：无期次标记、有执行日期 → 按执行日期归档并标注来源
        self.make_ledger('EL-WM-20260920-0009', status='draft',
                         executed_date=datetime(2026, 9, 20).date(),
                         maintenance_period='', system=self.system_a)
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH})['data']
        sep = [g for g in data if g['maintenance_period'] == '2026-09'][0]
        legacy_row = sep['ledgers'][0]
        self.assertEqual(legacy_row['period_label'], '每月｜2026年9月')
        self.assertTrue(legacy_row['period_is_derived'])
        self.assertEqual(legacy_row['period_source_text'], '按实际执行日期归档')

    def test_ledger_without_period_and_date_shows_unmarked(self):
        self.make_ledger('EL-WM-20260101-0099', status='draft', executed_date=None,
                         maintenance_period='')
        data = self.groups({'ledger_type': LEDGER_TYPE_WEEK_MONTH})['data']
        unmarked = [g for g in data if not g['maintenance_period']]
        self.assertEqual(len(unmarked), 1)
        self.assertEqual(unmarked[0]['period_text'], '未标注期次')
        self.assertFalse(unmarked[0]['is_current'])


class WeekMonthOverviewTests(OverviewTestBase):
    """周月维护本期工作概览：本周/本月两块，待生成按生成规则计算。"""

    def test_week_and_month_blocks_with_generate_rule_counts(self):
        weekly = self.publish_template(name='周模板', system=self.system_a,
                                       generation_period='weekly')
        monthly = self.publish_template(name='月模板', system=self.system_b,
                                        generation_period='monthly')
        data = self.overview(today=(2026, 10, 14))  # 周三
        self.assertEqual(data['ledger_type'], 'week_month')
        week = self.block(data, 'week')
        month = self.block(data, 'month')
        self.assertEqual(week['maintenance_period'], '2026-10-12')
        self.assertEqual(week['period_label'], '每周｜2026-10-12 ~ 2026-10-18')
        self.assertEqual(week['period_start'], '2026-10-12')
        self.assertEqual(week['period_end'], '2026-10-18')
        # 待生成依据模板生成规则计算（非统计已有台账）：生成前均为 1
        self.assertEqual(week['expected'], 1)
        self.assertEqual(week['to_generate'], 1)
        self.assertEqual(month['maintenance_period'], '2026-10')
        self.assertEqual(month['period_label'], '每月｜2026年10月')
        self.assertEqual(month['expected'], 1)
        self.assertEqual(month['to_generate'], 1)
        # 生成后：待生成归零、待填写出现
        with fake_today(2026, 10, 14):
            resp = post_json(self.client, GENERATE_URL,
                             {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertFalse(resp.json().get('error'), resp.json())
        data = self.overview(today=(2026, 10, 14))
        week = self.block(data, 'week')
        month = self.block(data, 'month')
        self.assertEqual(week['to_generate'], 0)
        self.assertEqual(week['drafting'], 1)
        self.assertEqual(month['to_generate'], 0)
        self.assertEqual(month['drafting'], 1)

    def test_week_key_is_monday_of_current_week(self):
        self.publish_template(system=self.system_a, generation_period='weekly')
        data = self.overview(today=(2026, 10, 18))  # 同一周的周日
        self.assertEqual(self.block(data, 'week')['maintenance_period'], '2026-10-12')

    def test_status_counts_use_real_ledgers_including_legacy_fallback(self):
        # 本期月组：生成的应填台账（draft）+ 历史台账（无期次标记按执行日期归档）
        self.publish_template(system=self.system_a, generation_period='monthly')
        with fake_today(2026, 10, 14):
            post_json(self.client, GENERATE_URL,
                      {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.make_ledger('EL-WM-20261005-0010', status='draft',
                         executed_date=datetime(2026, 10, 5).date(),
                         maintenance_period='', system=self.system_b)
        self.make_ledger('EL-WM-20261006-0011', status='completed',
                         executed_date=datetime(2026, 10, 6).date(),
                         maintenance_period='', system=self.system_b)
        self.make_ledger('EL-WM-20261007-0012', status='completed',
                         executed_date=datetime(2026, 10, 7).date(),
                         maintenance_period='', system=self.system_b)
        self.make_ledger('EL-WM-20261008-0013', status='void',
                         executed_date=datetime(2026, 10, 8).date(),
                         maintenance_period='', system=self.system_b)
        data = self.overview(today=(2026, 10, 14))
        month = self.block(data, 'month')
        self.assertEqual(month['drafting'], 2)
        self.assertEqual(month['completed'], 2)
        self.assertEqual(month['voided'], 1)
        # 历史台账不串到周块（周块无执行日期推导路径）
        self.assertEqual(self.block(data, 'week')['drafting'], 0)

    def test_attention_counts_blocked_slots(self):
        # 未发布版本模板：不占应填（无法填写），计入需处理
        self.publish_template(system=self.system_a, generation_period='weekly',
                              publish=False)
        data = self.overview(today=(2026, 10, 14))
        week = self.block(data, 'week')
        self.assertEqual(week['expected'], 0)
        self.assertEqual(week['to_generate'], 0)
        self.assertEqual(week['attention'], 1)


class SeasonalOverviewTests(OverviewTestBase):
    """季维护本期工作概览：本航季一块，与周月列表隔离。"""

    def test_season_block_and_list_isolation(self):
        seasonal = self.publish_template(
            name='季维护模板', ledger_type=LEDGER_TYPE_SEASONAL,
            system=self.system_a, generation_period='seasonal')
        self.publish_template(name='周月模板', system=self.system_b,
                              generation_period='monthly')
        data = self.overview(LEDGER_TYPE_SEASONAL, today=(2026, 10, 14))
        self.assertEqual(len(data['blocks']), 1)
        season = self.block(data, 'season')
        self.assertEqual(season['title'], '本航季')
        self.assertEqual(season['maintenance_period'], '2026-夏秋')
        # 航季标签带起止日期（2026 夏秋：3月末周日 ~ 10月末周日）
        self.assertEqual(season['period_start'], '2026-03-29')
        self.assertEqual(season['period_end'], '2026-10-24')
        self.assertEqual(season['expected'], 1)
        self.assertEqual(season['to_generate'], 1)
        # 周月列表的概览不含季维护模板
        wm = self.overview(today=(2026, 10, 14))
        self.assertEqual(self.block(wm, 'week')['expected'], 0)
        self.assertEqual(self.block(wm, 'month')['expected'], 1)

    def test_season_counts_after_generate(self):
        self.publish_template(ledger_type=LEDGER_TYPE_SEASONAL,
                              system=self.system_a, generation_period='seasonal')
        with fake_today(2026, 8, 15):
            resp = post_json(self.client, GENERATE_URL,
                             {'ledger_type': LEDGER_TYPE_SEASONAL})
        self.assertFalse(resp.json().get('error'), resp.json())
        data = self.overview(LEDGER_TYPE_SEASONAL, today=(2026, 8, 15))
        season = self.block(data, 'season')
        self.assertEqual(season['to_generate'], 0)
        self.assertEqual(season['drafting'], 1)


class OverviewPermissionAndTenantTests(OverviewTestBase):
    """概览权限与租户隔离。"""

    def test_overview_requires_view_permission(self):
        viewer = make_user('ov_viewer', perms=['equipment_lifecycle.ledger.view'])
        client = make_client(viewer)
        data = self.overview(client=client, today=(2026, 10, 14))
        self.assertEqual(data['blocks'][0]['expected'], 0)
        # 无任何权限的用户被认证层拒绝（401/错误），不泄露数据
        nobody = make_user('ov_nobody', perms=[])
        resp = make_client(nobody).get(OVERVIEW_URL,
                                       {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertTrue(resp.json().get('error') or resp.status_code != 200)

    def test_tenant_isolation(self):
        self.publish_template(system=self.system_a, generation_period='weekly')
        self.publish_template(name='B租户模板', system=self.other_system,
                              generation_period='monthly', client=self.other_client)
        data_a = self.overview(today=(2026, 10, 14))
        self.assertEqual(self.block(data_a, 'week')['expected'], 1)
        self.assertEqual(self.block(data_a, 'month')['expected'], 0)
        data_b = self.overview(client=self.other_client, today=(2026, 10, 14))
        self.assertEqual(self.block(data_b, 'week')['expected'], 0)
        self.assertEqual(self.block(data_b, 'month')['expected'], 1)
        # B 租户生成不影响 A 租户概览
        with fake_today(2026, 10, 14):
            post_json(self.other_client, GENERATE_URL,
                      {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        data_a = self.overview(today=(2026, 10, 14))
        self.assertEqual(self.block(data_a, 'month')['drafting'], 0)

    def test_unconfigured_templates_reported(self):
        self.publish_template()  # 未配置适用系统/生成周期
        data = self.overview(today=(2026, 10, 14))
        self.assertEqual(data['unconfigured_templates'], 1)
        self.assertEqual(self.block(data, 'week')['expected'], 0)
