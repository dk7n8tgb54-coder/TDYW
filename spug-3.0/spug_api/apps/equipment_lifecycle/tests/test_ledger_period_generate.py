# -*- coding: utf-8 -*-
"""本期应填台账生成（2026-10-14 重构周期批量新增）行为测试。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）：
- 生成范围：显式配置 适用系统+生成周期 的启用 Excel 模板（一模板一系统，
  同系统可多模板）；未配置的历史模板标记待配置，不猜测、不改写；
- 期次键：每周=本周一日期（周一~周日一个自然周，跨月周归入周一所在月份）、
  每月=YYYY-MM、季维护=航季（夏秋/冬春边界）；本期=当前周/月/航季，
  不预建未来期次；
- 去重：同租户+模板+系统+期次仅一张台账（唯一约束+模板行锁；重复点击/
  并发请求/版本升级都不重复生成）；已作废台账不在一键生成中悄悄重建；
- 生成物：created_from=excel_template 的正式台账，固定引用最新发布版本
  快照，可直接进入 Excel 填写；不再生成无明细的手工草稿；
- 两个填写列表（周月维护/季维护）各自生成各自的模板，互不串扰。
"""
import json
import tempfile
import threading
import uuid
from datetime import datetime
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings

from apps.equipment_lifecycle import ledger_period_services
from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplateVersion,
)
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
GENERATE_URL = LEDGERS_URL + '/period-generate/'
GROUPS_URL = LEDGERS_URL + '/period-groups/'
EXCEL_LEDGERS_URL = URL_PREFIX + '/excel-ledgers'
TPL_URL = URL_PREFIX + '/excel-templates'

# 每次测试进程使用独立临时目录：样例 xlsx 字节含时间戳非确定性，固定目录
# 残留的版本文件会让 --keepdb 复用的模板 ID 在发布时报文件冲突
STORAGE_DIR = tempfile.mkdtemp(prefix='el_period_generate_')


def fake_today(year, month, day):
    """把生成口径的"今天"固定为指定日期（service 内 timezone.now）。"""
    return mock.patch.object(
        ledger_period_services.timezone, 'now',
        return_value=datetime(year, month, day, 10, 0, 0))


class PeriodGenerateTestBase(TestCase):
    """公共夹具：双系统 + 模板发布辅助（client 必须在 setUp 创建）。"""

    def setUp(self):
        self.user = make_user('pg_op', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.client = make_client(self.user)
        self.system_a = make_system(self.user, system_code='SYS-A', name='DVOR系统')
        self.system_b = make_system(self.user, system_code='SYS-B', name='ILS系统')
        self.other_user = make_user('pg_other', tenant_id='tenant-b',
                                    perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.other_client = make_client(self.other_user)
        self.other_system = make_system(
            self.other_user, tenant_id='tenant-b', system_code='SYS-B2', name='B租户系统')
        self._storage_override = override_settings(EL_EXCEL_TEMPLATE_BASE_DIR=STORAGE_DIR)
        self._storage_override.enable()
        self.addCleanup(self._storage_override.disable)

    # ---------- 模板夹具（全部走真实接口） ----------

    def _upload_bind_publish(self, name, ledger_type, client):
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
                          json.dumps({'field_bindings': bindings}),
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        return template

    def publish_template(self, name='信道Excel维护台账', ledger_type=LEDGER_TYPE_WEEK_MONTH,
                         system=None, generation_period='', client=None, publish=True):
        """上传→绑定→（发布）→配置生成属性，返回模板详情 dict。"""
        client = client or self.client
        template = self._upload_bind_publish(name, ledger_type, client)
        if publish:
            resp = client.post('%s/%s/publish/' % (TPL_URL, template['id']))
            self.assertFalse(resp.json().get('error'), resp.json())
        if system is not None or generation_period:
            resp = client.put(
                '%s/%s/generation-config/' % (TPL_URL, template['id']),
                json.dumps({'system': system.id if system else '',
                            'generation_period': generation_period}),
                content_type='application/json')
            self.assertFalse(resp.json().get('error'), resp.json())
        return template

    # ---------- 预览/生成辅助 ----------

    def preview(self, ledger_type=LEDGER_TYPE_WEEK_MONTH, client=None, today=None):
        client = client or self.client
        if today:
            with fake_today(*today):
                resp = client.get(GENERATE_URL, {'ledger_type': ledger_type})
        else:
            resp = client.get(GENERATE_URL, {'ledger_type': ledger_type})
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def generate(self, ledger_type=LEDGER_TYPE_WEEK_MONTH, client=None, today=None,
                 maintenance_cycles=None, template_ids=None, template_kinds=None):
        client = client or self.client
        # POST 确认生成要求显式选择维护周期与模板（服务层 required=True）；
        # 维护周期缺省按该类型的完整 allowed 集合、模板缺省取 setUp 发布的
        # self.template，保持原"全量生成"语义不变。
        if maintenance_cycles is None:
            maintenance_cycles = (['seasonal'] if ledger_type == LEDGER_TYPE_SEASONAL
                                  else ['weekly', 'monthly'])
        if template_ids is None:
            template = getattr(self, 'template', None)
            self.assertIsNotNone(
                template,
                'generate() 需要显式 template_ids 或在 setUp 中发布 self.template')
            template_ids = [template['id'] if isinstance(template, dict) else template.id]
        if template_kinds is None:
            template_kinds = ['excel'] * len(template_ids)
        payload = {'ledger_type': ledger_type,
                   'maintenance_cycles': maintenance_cycles,
                   'template_ids': template_ids,
                   'template_kinds': template_kinds}
        if today:
            with fake_today(*today):
                resp = post_json(client, GENERATE_URL, payload)
        else:
            resp = post_json(client, GENERATE_URL, payload)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    @staticmethod
    def entry_by_template(preview_data, template_id):
        for entry in preview_data['entries']:
            if entry['template_id'] == template_id:
                return entry
        return None


class WeeklyGenerationTests(PeriodGenerateTestBase):
    """每周模板：周一键期次、完整起止展示、一周一张、直接进入 Excel 填写。"""

    def setUp(self):
        super().setUp()
        self.template = self.publish_template(
            system=self.system_a, generation_period='weekly')

    def test_generates_monday_keyed_excel_ledger(self):
        data = self.generate(today=(2026, 10, 14))  # 周三
        self.assertEqual(len(data['created']), 1)
        row = data['created'][0]
        self.assertEqual(row['maintenance_period'], '2026-10-12')
        self.assertEqual(row['period_text'], '2026-10-12 ~ 2026-10-18')
        self.assertEqual(row['version_no'], 1)
        # 数据库真实状态：Excel 路线台账，固定版本快照，期次归属明确
        ledger = OperationLedger.objects.get(pk=row['id'])
        self.assertEqual(ledger.created_from, 'excel_template')
        self.assertEqual(ledger.maintenance_period, '2026-10-12')
        self.assertEqual(ledger.system_id, self.system_a.id)
        self.assertEqual(ledger.source_template_id, self.template['id'])
        self.assertEqual(ledger.status, 'draft')
        self.assertTrue(ledger.ledger_no.startswith('EL-WM-20261012-'))
        record = OperationLedgerExcelRecord.objects.get(ledger=ledger)
        self.assertEqual(record.version.version_no, 1)
        self.assertEqual(record.version.template_id, self.template['id'])

    def test_generated_ledger_directly_enterable_for_excel_fill(self):
        data = self.generate(today=(2026, 10, 14))
        ledger_id = data['created'][0]['id']
        # Excel 填写详情可打开：版本快照 + 绑定 + 可编辑
        resp = self.client.get('%s/%d/' % (EXCEL_LEDGERS_URL, ledger_id))
        self.assertFalse(resp.json().get('error'), resp.json())
        detail = resp.json()['data']['data']
        self.assertEqual(detail['excel']['version']['version_no'], 1)
        self.assertEqual(len(detail['excel']['version']['bindings']), 1)
        self.assertTrue(detail['excel']['editable'])
        # 统一列表显示为 Excel 来源并携带详情路由
        resp = self.client.get(LEDGERS_URL + '/', {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        row = resp.json()['data']['data'][0]
        self.assertEqual(row['source_type'], 'excel')
        self.assertEqual(row['source_template_name'], '信道Excel维护台账')
        self.assertIn('source=excel', row['detail_route'])

    def test_same_week_any_day_maps_to_one_period(self):
        first = self.generate(today=(2026, 10, 12))  # 周一
        self.assertEqual(len(first['created']), 1)
        second = self.generate(today=(2026, 10, 18))  # 同一周的周日
        self.assertEqual(second['created'], [])
        self.assertEqual(len(second['skipped']), 1)
        self.assertEqual(OperationLedger.objects.count(), 1)

    def test_cross_month_week_keyed_by_monday(self):
        # 2026-11-01 是周日，属于周一 2026-10-26 开始的自然周：跨月周只算
        # 一个期次，期次键与归属月份均为周一（10 月）
        data = self.generate(today=(2026, 11, 1))
        self.assertEqual(data['created'][0]['maintenance_period'], '2026-10-26')
        self.assertEqual(data['created'][0]['period_text'], '2026-10-26 ~ 2026-11-01')
        ledger = OperationLedger.objects.first()
        self.assertEqual(ledger.maintenance_period, '2026-10-26')
        # 分组归入周一所在月份（组键=2026-10-26）
        groups = self.client.get(
            GROUPS_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH}).json()['data']['data']
        self.assertEqual([g['maintenance_period'] for g in groups], ['2026-10-26'])
        self.assertEqual(groups[0]['period_text'], '每周｜2026-10-26 ~ 2026-11-01')

    def test_only_current_week_generated_no_future(self):
        self.generate(today=(2026, 10, 14))
        # 只生成当前周一期，未来周不预建
        self.assertEqual(OperationLedger.objects.count(), 1)
        # 基准推到下周才会生成下一期（且与本周互不占用）
        data = self.generate(today=(2026, 10, 19))
        self.assertEqual(len(data['created']), 1)
        self.assertEqual(data['created'][0]['maintenance_period'], '2026-10-19')
        self.assertEqual(OperationLedger.objects.count(), 2)


class MonthlyAndSeasonalTests(PeriodGenerateTestBase):
    """每月模板与季维护模板：期次口径、两个列表隔离。"""

    def test_monthly_template_generates_month_key(self):
        template = self.publish_template(system=self.system_a, generation_period='monthly')
        data = self.generate(today=(2026, 10, 14), template_ids=[template['id']])
        self.assertEqual(len(data['created']), 1)
        self.assertEqual(data['created'][0]['maintenance_period'], '2026-10')
        self.assertEqual(data['created'][0]['period_text'], '2026年10月')
        ledger = OperationLedger.objects.first()
        self.assertTrue(ledger.ledger_no.startswith('EL-WM-20261001-'))

    def test_seasonal_templates_follow_aviation_seasons(self):
        template = self.publish_template(
            name='季维护Excel台账', ledger_type=LEDGER_TYPE_SEASONAL,
            system=self.system_a, generation_period='seasonal')
        summer = self.generate(LEDGER_TYPE_SEASONAL, today=(2026, 8, 15),
                               template_ids=[template['id']])
        self.assertEqual(summer['created'][0]['maintenance_period'], '2026-夏秋')
        self.assertEqual(summer['created'][0]['period_text'], '2026年夏秋季')
        # 冬春季（新航季）另生成一张
        winter = self.generate(LEDGER_TYPE_SEASONAL, today=(2026, 11, 15),
                               template_ids=[template['id']])
        self.assertEqual(winter['created'][0]['maintenance_period'], '2026-冬春')
        self.assertEqual(winter['created'][0]['period_text'], '2026年冬春季')
        # 航季边界：10月最后一个周日（2026-10-25）当日已属冬春季，不重复生成
        boundary = self.generate(LEDGER_TYPE_SEASONAL, today=(2026, 10, 25),
                                 template_ids=[template['id']])
        self.assertEqual(boundary['created'], [])
        self.assertEqual(len(boundary['skipped']), 1)
        # 冬春季沿用现有边界：次年3月末周日（2027-03-28）前仍属 2026-冬春
        late_winter = self.generate(LEDGER_TYPE_SEASONAL, today=(2027, 3, 27),
                                    template_ids=[template['id']])
        self.assertEqual(late_winter['created'], [])
        self.assertEqual(OperationLedger.objects.count(), 2)
        self.assertEqual(OperationLedger.objects.filter(
            ledger_type=LEDGER_TYPE_SEASONAL,
            maintenance_period='2026-夏秋').count(), 1)
        self.assertEqual(OperationLedger.objects.filter(
            ledger_type=LEDGER_TYPE_SEASONAL,
            maintenance_period='2026-冬春').count(), 1)

    def test_two_lists_are_isolated(self):
        wm = self.publish_template(
            name='周月模板', system=self.system_a, generation_period='monthly')
        se = self.publish_template(
            name='季维护模板', ledger_type=LEDGER_TYPE_SEASONAL,
            system=self.system_a, generation_period='seasonal')
        wm_preview = self.preview(LEDGER_TYPE_WEEK_MONTH, today=(2026, 10, 14))
        se_preview = self.preview(LEDGER_TYPE_SEASONAL, today=(2026, 10, 14))
        self.assertEqual(
            [e['template_id'] for e in wm_preview['entries']], [wm['id']])
        self.assertEqual(
            [e['template_id'] for e in se_preview['entries']], [se['id']])
        wm_data = self.generate(LEDGER_TYPE_WEEK_MONTH, today=(2026, 10, 14),
                                template_ids=[wm['id']])
        self.assertEqual(len(wm_data['created']), 1)
        # 季维护列表未受影响：无台账生成，预览仍可新建
        self.assertEqual(OperationLedger.objects.count(), 1)
        se_data = self.generate(LEDGER_TYPE_SEASONAL, today=(2026, 10, 14),
                                template_ids=[se['id']])
        self.assertEqual(len(se_data['created']), 1)
        self.assertEqual(OperationLedger.objects.count(), 2)
        self.assertTrue(OperationLedger.objects.filter(
            ledger_type=LEDGER_TYPE_WEEK_MONTH).exists())
        self.assertTrue(OperationLedger.objects.filter(
            ledger_type=LEDGER_TYPE_SEASONAL).exists())

    def test_weekly_and_monthly_templates_coexist_in_week_month_list(self):
        weekly = self.publish_template(
            name='周模板', system=self.system_a, generation_period='weekly')
        monthly = self.publish_template(
            name='月模板', system=self.system_b, generation_period='monthly')
        data = self.generate(today=(2026, 10, 14),
                             template_ids=[weekly['id'], monthly['id']])
        periods = sorted(row['maintenance_period'] for row in data['created'])
        self.assertEqual(periods, ['2026-10', '2026-10-12'])
        self.assertEqual(OperationLedger.objects.count(), 2)


class DedupAndConflictTests(PeriodGenerateTestBase):
    """去重：重复点击、版本升级、已作废、历史手工壳与预览一致性。"""

    def setUp(self):
        super().setUp()
        self.template = self.publish_template(
            system=self.system_a, generation_period='monthly')

    def test_repeated_generate_skips_existing(self):
        first = self.generate(today=(2026, 10, 14))
        self.assertEqual(len(first['created']), 1)
        second = self.generate(today=(2026, 10, 15))
        self.assertEqual(second['created'], [])
        self.assertEqual(len(second['skipped']), 1)
        self.assertEqual(second['skipped'][0]['ledger']['ledger_no'],
                         first['created'][0]['ledger_no'])
        self.assertEqual(OperationLedger.objects.count(), 1)

    def test_version_upgrade_does_not_duplicate_and_keeps_old_snapshot(self):
        first = self.generate(today=(2026, 10, 14))
        ledger_id = first['created'][0]['id']
        # 模板发布新版本 v2
        resp = self.client.post('%s/%s/publish/' % (TPL_URL, self.template['id']))
        self.assertFalse(resp.json().get('error'), resp.json())
        # 预览：已存在跳过，不因新版本再生成
        data = self.preview(today=(2026, 10, 20))
        entry = self.entry_by_template(data, self.template['id'])
        self.assertEqual(entry['status'], 'exists')
        self.assertEqual(entry['version_no'], 2)  # 预览展示将使用的最新版本
        # 生成同样不重复
        result = self.generate(today=(2026, 10, 20))
        self.assertEqual(result['created'], [])
        self.assertEqual(len(result['skipped']), 1)
        self.assertEqual(OperationLedger.objects.count(), 1)
        # 历史台账仍固定引用创建时版本 v1
        record = OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)
        self.assertEqual(record.version.version_no, 1)

    def test_voided_ledger_blocks_silent_recreation(self):
        first = self.generate(today=(2026, 10, 14))
        ledger_id = first['created'][0]['id']
        resp = post_json(self.client, '%s/%d/void/' % (LEDGERS_URL, ledger_id),
                         {'reason': '误生成'})
        self.assertFalse(resp.json().get('error'), resp.json())
        # 预览明确展示需人工处理（不当作有效记录，也不悄悄重建）
        data = self.preview(today=(2026, 10, 20))
        entry = self.entry_by_template(data, self.template['id'])
        self.assertEqual(entry['status'], 'manual_needed')
        self.assertIn('已作废', entry['reason'])
        self.assertEqual(entry['existing_ledger']['ledger_no'],
                         first['created'][0]['ledger_no'])
        result = self.generate(today=(2026, 10, 20))
        self.assertEqual(result['created'], [])
        self.assertEqual(len(result['failed']), 1)
        self.assertIn('已作废', result['failed'][0]['reason'])
        self.assertEqual(OperationLedger.objects.count(), 1)

    def test_legacy_manual_shell_blocks_generation(self):
        # 旧周期批量新增的手工壳（manual + 表头系统 + 期次标记）不自动改写，
        # 同系统同期次存在时模板标记需人工处理
        OperationLedger.objects.create(
            tenant_id=self.user.tenant_id,
            ledger_no='EL-WM-20261001-9001',
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            status='draft',
            entry_channel='web',
            created_from='manual',
            system=self.system_a,
            maintenance_period='2026-10',
            created_by=self.user,
        )
        data = self.preview(today=(2026, 10, 14))
        entry = self.entry_by_template(data, self.template['id'])
        self.assertEqual(entry['status'], 'manual_needed')
        self.assertIn('历史草稿', entry['reason'])
        result = self.generate(today=(2026, 10, 14))
        self.assertEqual(result['created'], [])
        self.assertEqual(len(result['failed']), 1)

    def test_preview_matches_actual_generation(self):
        other = self.publish_template(
            name='ILS月模板', system=self.system_b, generation_period='monthly')
        preview = self.preview(today=(2026, 10, 14))
        self.assertEqual(preview['summary'],
                         {'create': 2, 'exists': 0, 'no_version': 0, 'manual_needed': 0})
        result = self.generate(today=(2026, 10, 14),
                               template_ids=[self.template['id'], other['id']])
        self.assertEqual(len(result['created']), preview['summary']['create'])
        self.assertEqual(
            {row['template_id'] for row in result['created']},
            {self.template['id'], other['id']})
        # 生成后预览口径翻转为已存在
        after = self.preview(today=(2026, 10, 14))
        self.assertEqual(after['summary'],
                         {'create': 0, 'exists': 2, 'no_version': 0, 'manual_needed': 0})

    def test_period_groups_reject_invalid_ledger_type(self):
        resp = self.client.get(GROUPS_URL, {'ledger_type': 'inspection'})
        self.assertIn('不再支持', resp.json()['error'])
        resp = self.client.get(GROUPS_URL, {})
        self.assertTrue(resp.json().get('error'), resp.json())

    def test_period_groups_contain_generated_ledgers_with_week_text(self):
        weekly = self.publish_template(
            name='周模板', system=self.system_b, generation_period='weekly')
        self.generate(today=(2026, 10, 14),
                      template_ids=[self.template['id'], weekly['id']])
        with fake_today(2026, 10, 14):
            groups = self.client.get(
                GROUPS_URL,
                {'ledger_type': LEDGER_TYPE_WEEK_MONTH}).json()['data']['data']
        by_period = {g['maintenance_period']: g for g in groups}
        # 2026-10-14 起分组标题为期次完整标签，统计区分五状态
        self.assertEqual(by_period['2026-10']['period_text'], '每月｜2026年10月')
        self.assertEqual(by_period['2026-10-12']['period_text'], '每周｜2026-10-12 ~ 2026-10-18')
        self.assertEqual(by_period['2026-10']['draft'], 1)
        self.assertEqual(by_period['2026-10-12']['draft'], 1)
        self.assertTrue(by_period['2026-10-12']['is_current'])
        row = by_period['2026-10-12']['ledgers'][0]
        self.assertEqual(row['period_label'], '每周｜2026-10-12 ~ 2026-10-18')
        self.assertFalse(row['period_is_derived'])
        rows = by_period['2026-10-12']['ledgers']
        self.assertEqual(rows[0]['source_type'], 'excel')


class ConcurrentGenerateTests(TransactionTestCase):
    """并发生成：模板行锁 + 唯一约束保证同槽位只创建一张。"""

    def setUp(self):
        self.user = make_user('pg_conc', perms=ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS)
        self.system = make_system(self.user, system_code='SYS-C', name='并发系统')
        self._storage_override = override_settings(EL_EXCEL_TEMPLATE_BASE_DIR=STORAGE_DIR)
        self._storage_override.enable()
        self.addCleanup(self._storage_override.disable)
        # 直连服务发布模板（避免请求级事务干扰线程模型）
        from apps.equipment_lifecycle import excel_template_manage
        template = excel_template_manage.create_template(
            self.user, 'channel.xlsx', build_acceptance_sample_xlsx(),
            {'name': '并发模板', 'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'description': ''})
        bindings = [{
            'field_id': str(uuid.uuid4()), 'sheet_name': '信道维护记录',
            'cell_coordinate': 'C4', 'field_name': 'PS模块', 'input_type': 'status',
            'is_required': True, 'unit': '', 'options': [],
        }]
        excel_template_manage.save_bindings(self.user, template, bindings)
        excel_template_manage.publish_version(self.user, template)
        excel_template_manage.save_generation_config(self.user, template, {
            'system': self.system.id, 'generation_period': 'monthly'})
        self.template = template

    def test_concurrent_generate_creates_only_one(self):
        barrier = threading.Barrier(2)
        results = {}

        def _runner(key):
            def run():
                try:
                    barrier.wait(timeout=15)
                except Exception:
                    pass
                try:
                    data, error = ledger_period_services.period_generate(
                        self.user, LEDGER_TYPE_WEEK_MONTH, ['monthly'],
                        [self.template.id], ['excel'])
                    results[key] = (error, data)
                finally:
                    from django.db import connections
                    connections.close_all()
            return run

        threads = [threading.Thread(target=_runner('a')),
                   threading.Thread(target=_runner('b'))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(set(results.keys()), {'a', 'b'})
        created_total = 0
        for error, data in results.values():
            self.assertIsNone(error, error)
            created_total += len(data['created'])
            self.assertEqual(data['failed'], [])
        self.assertEqual(created_total, 1, results)
        self.assertEqual(OperationLedger.objects.count(), 1)
        loser = [v for v in results.values() if not v[1]['created']][0]
        self.assertEqual(len(loser[1]['skipped']), 1, results)


class PermissionAndTenantTests(PeriodGenerateTestBase):
    """权限与租户隔离。"""

    def test_preview_requires_view_generate_requires_add(self):
        template = self.publish_template(system=self.system_a, generation_period='monthly')
        viewer = make_user('pg_viewer', perms=['equipment_lifecycle.ledger.view'])
        viewer_client = make_client(viewer)
        data = self.preview(client=viewer_client)
        self.assertEqual(data['summary']['create'], 1)
        # 参数完全合法但无 add 权限：确认拒绝来自鉴权而非参数校验
        resp = post_json(viewer_client, GENERATE_URL,
                         {'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                          'maintenance_cycles': ['weekly', 'monthly'],
                          'template_ids': [template['id']],
                          'template_kinds': ['excel']})
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertEqual(OperationLedger.objects.count(), 0)

    def test_tenant_isolation(self):
        wm = self.publish_template(system=self.system_a, generation_period='monthly')
        other_template = self.publish_template(
            name='B租户模板', system=self.other_system, generation_period='weekly',
            client=self.other_client)
        # A 租户预览只见 A 模板
        data_a = self.preview(today=(2026, 10, 14))
        self.assertEqual(
            [e['template_id'] for e in data_a['entries']], [wm['id']])
        # B 租户预览只见 B 模板；B 生成不影响 A
        data_b = self.preview(client=self.other_client, today=(2026, 10, 14))
        self.assertEqual(
            [e['template_id'] for e in data_b['entries']], [other_template['id']])
        result_b = self.generate(client=self.other_client, today=(2026, 10, 14),
                                 template_ids=[other_template['id']])
        self.assertEqual(len(result_b['created']), 1)
        self.assertEqual(OperationLedger.objects.filter(
            tenant_id='default').count(), 0)
        self.assertEqual(OperationLedger.objects.filter(
            tenant_id='tenant-b').count(), 1)


class ExecutionDateRemovedTests(PeriodGenerateTestBase):
    """表头"实际执行日期"已删除（2026-10-19）：执行日期由台账表格内容承载。

    - 单条新增不再要求日期，编号以录入当天为基准；
    - 旧客户端携带 executed_date 参数时被忽略（不报错、不落库），前端已同步
      移除该输入，此用例固化灰度兼容口径；
    - 完成填写不再校验执行日期（必填校验只看版本绑定）。
    """

    def setUp(self):
        super().setUp()
        self.template = self.publish_template(
            system=self.system_a, generation_period='monthly')

    def test_single_creation_without_executed_date(self):
        version = OperationLedgerExcelTemplateVersion.objects.filter(
            template_id=self.template['id']).first()
        resp = post_json(self.client, EXCEL_LEDGERS_URL + '/', {
            'version_id': version.id})
        self.assertFalse(resp.json().get('error'), resp.json())
        detail = resp.json()['data']['data']
        self.assertEqual(detail['status'], 'draft')
        # 编号基准=录入当天（period 生成仍以期次起始日期为基准，见生成用例）
        self.assertTrue(detail['ledger_no'].startswith('EL-WM-'))
        self.assertEqual(OperationLedger.objects.count(), 1)

    def test_legacy_executed_date_payload_is_ignored(self):
        version = OperationLedgerExcelTemplateVersion.objects.filter(
            template_id=self.template['id']).first()
        resp = post_json(self.client, EXCEL_LEDGERS_URL + '/', {
            'version_id': version.id, 'executed_date': '2026-10-16'})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(OperationLedger.objects.count(), 1)



class TemplateGenerationConfigTests(PeriodGenerateTestBase):
    """模板生成配置：适用系统 + 生成周期（显式配置，不推断）。"""

    def test_config_options_and_save(self):
        template = self.publish_template()
        resp = self.client.get('%s/%s/generation-config/' % (TPL_URL, template['id']))
        data = resp.json()['data']['data']
        self.assertEqual({s['name'] for s in data['systems']}, {'DVOR系统', 'ILS系统'})
        self.assertEqual(
            [p['value'] for p in data['periods']['week_month']], ['weekly', 'monthly'])
        self.assertEqual(
            [p['value'] for p in data['periods']['seasonal']], ['seasonal'])
        resp = self.client.put(
            '%s/%s/generation-config/' % (TPL_URL, template['id']),
            json.dumps({'system': self.system_a.id, 'generation_period': 'weekly'}),
            content_type='application/json')
        detail = resp.json()['data']['data']
        self.assertEqual(detail['system'], self.system_a.id)
        self.assertEqual(detail['system_name'], 'DVOR系统')
        self.assertEqual(detail['generation_period'], 'weekly')
        self.assertEqual(detail['generation_period_text'], '每周')

    def test_config_period_must_match_ledger_type(self):
        seasonal = self.publish_template(ledger_type=LEDGER_TYPE_SEASONAL)
        for period in ('weekly', 'monthly'):
            resp = self.client.put(
                '%s/%s/generation-config/' % (TPL_URL, seasonal['id']),
                json.dumps({'system': self.system_a.id, 'generation_period': period}),
                content_type='application/json')
            self.assertTrue(resp.json().get('error'), period)
        weekly = self.publish_template()
        resp = self.client.put(
            '%s/%s/generation-config/' % (TPL_URL, weekly['id']),
            json.dumps({'system': self.system_a.id, 'generation_period': 'seasonal'}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'), resp.json())

    def test_config_can_clear_back_to_unconfigured(self):
        template = self.publish_template(system=self.system_a, generation_period='weekly')
        resp = self.client.put(
            '%s/%s/generation-config/' % (TPL_URL, template['id']),
            json.dumps({'system': '', 'generation_period': ''}),
            content_type='application/json')
        detail = resp.json()['data']['data']
        self.assertIsNone(detail['system'])
        self.assertEqual(detail['generation_period'], '')
        self.assertEqual(detail['generation_period_text'], '待配置')

    def test_config_rejects_cross_tenant_system(self):
        template = self.publish_template()
        resp = self.client.put(
            '%s/%s/generation-config/' % (TPL_URL, template['id']),
            json.dumps({'system': self.other_system.id, 'generation_period': 'weekly'}),
            content_type='application/json')
        self.assertIn('不存在或无权限', resp.json()['error'])

    def test_config_edit_requires_edit_permission(self):
        template = self.publish_template()
        viewer = make_user('tpl_viewer', perms=['equipment_lifecycle.ledger_template.view'])
        resp = make_client(viewer).put(
            '%s/%s/generation-config/' % (TPL_URL, template['id']),
            json.dumps({'system': self.system_a.id, 'generation_period': 'weekly'}),
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_unconfigured_template_marked_in_preview(self):
        template = self.publish_template()  # 未配置
        data = self.preview(today=(2026, 10, 14))
        entry = self.entry_by_template(data, template['id'])
        self.assertEqual(entry['status'], 'manual_needed')
        self.assertIn('待配置', entry['reason'])
        self.assertEqual(entry['generation_period_text'], '待配置')
        self.assertEqual(entry['maintenance_period'], '')
        result = self.generate(today=(2026, 10, 14), template_ids=[template['id']])
        self.assertEqual(result['created'], [])
        self.assertIn('待配置', result['failed'][0]['reason'])

    def test_template_without_version_reported_missing(self):
        template = self.publish_template(
            system=self.system_a, generation_period='weekly', publish=False)
        data = self.preview(today=(2026, 10, 14))
        entry = self.entry_by_template(data, template['id'])
        self.assertEqual(entry['status'], 'no_version')
        self.assertIn('缺少可用版本', entry['reason'])
        result = self.generate(today=(2026, 10, 14), template_ids=[template['id']])
        self.assertEqual(result['created'], [])
        self.assertEqual(len(result['failed']), 1)

    def test_inactive_system_reported_manual_needed(self):
        template = self.publish_template(system=self.system_a, generation_period='weekly')
        self.system_a.is_active = False
        self.system_a.save()
        data = self.preview(today=(2026, 10, 14))
        entry = self.entry_by_template(data, template['id'])
        self.assertEqual(entry['status'], 'manual_needed')
        self.assertIn('已停用', entry['reason'])

    def test_stopped_template_excluded_from_generation(self):
        template = self.publish_template(system=self.system_a, generation_period='weekly')
        resp = self.client.delete('%s/%s/' % (TPL_URL, template['id']))
        self.assertFalse(resp.json().get('error'), resp.json())
        data = self.preview(today=(2026, 10, 14))
        self.assertEqual(data['entries'], [])
        # 显式选择已物理删除的模板被整体拒绝（fail-closed），不产生任何台账
        result_resp = post_json(self.client, GENERATE_URL, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH,
            'maintenance_cycles': ['weekly', 'monthly'],
            'template_ids': [template['id']],
            'template_kinds': ['excel']})
        self.assertIn('不存在', result_resp.json()['error'])
        self.assertEqual(OperationLedger.objects.count(), 0)

    def test_deactivated_template_excluded_from_generation(self):
        """停用（is_active=False，非物理删除）模板同样退出自动生成范围。"""
        template = self.publish_template(system=self.system_a, generation_period='weekly')
        resp = self.client.post('%s/%s/deactivate/' % (TPL_URL, template['id']))
        self.assertFalse(resp.json().get('error'), resp.json())
        data = self.preview(today=(2026, 10, 14))
        self.assertEqual(data['entries'], [])
        result = self.generate(today=(2026, 10, 14), template_ids=[template['id']])
        self.assertEqual(result['created'], [])

    def test_rebuild_rejects_deactivated_template(self):
        """补建入口后端独立校验：停用模板按"不存在或已停用"拒绝。"""
        template = self.publish_template(system=self.system_a, generation_period='weekly')
        resp = self.client.post('%s/%s/deactivate/' % (TPL_URL, template['id']))
        self.assertFalse(resp.json().get('error'), resp.json())
        with fake_today(2026, 10, 14):
            result, error = ledger_period_services.period_generate_rebuild(
                self.user, template['id'])
        self.assertIsNone(result)
        self.assertIn('已停用', error)
