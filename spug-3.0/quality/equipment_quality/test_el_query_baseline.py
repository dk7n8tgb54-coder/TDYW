# -*- coding: utf-8 -*-
"""设备管理——只读查询性能基线（quality/equipment_quality）。

在隔离测试库中播种确定性规模的数据，对现行菜单对应的只读端点测量
响应时间（3 次取中位）与 SQL 查询条数（最后一次请求捕获），
输出 JSON 基线（__BASELINE_JSON__ 标记后跟 JSON 数组）。

- 只读：除播种外不发任何写请求；播种在 TestCase 事务内，结束后回滚。
- 断言仅限"HTTP 200 且无业务 error"，不设脆阈值；阈值见
  quality/performance/thresholds.yml 与本次质量报告。
"""
import datetime
import json
import time

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.equipment_lifecycle.models import LifecycleSystem, OperationLedger
from apps.equipment_lifecycle.operation_models import (
    SystemOperationProgress, SystemOperationRecord,
)
from apps.upgrade.models import UpgradeRecord

from quality.equipment_quality.qa_base import (
    LEDGER_URL, RECORDS_URL, SYSTEMS_URL, TPL_URL, UPGRADE_URL,
    create_ledger_ok, entry_payload, item_payload, ledger_payload,
    make_client, make_record, make_system, make_user, post_json, uniq,
)

SYSTEM_COUNT = 30
RECORD_COUNT = 120
LEDGER_COUNT = 40
UPGRADE_COUNT = 24
PROGRESS_PER_RECORD = 2
REPEATS = 3


class QueryBaselineTests(TestCase):
    """只读端点基线测量（结果写入质量报告，不作通过/失败判定）。"""

    @staticmethod
    def _flush_tables():
        # 清空相关业务表获得确定规模（TestCase 事务内，结束后回滚）
        SystemOperationProgress.objects.all().delete()
        SystemOperationRecord.objects.all().delete()
        OperationLedger.objects.all().delete()
        LifecycleSystem.objects.all().delete()
        UpgradeRecord.objects.all().delete()

    def _seed(self):
        self.tenant = uniq('perf_t')
        self.user = make_user(uniq('perf_user'), perms=[
            'equipment_lifecycle.system.view',
            'equipment_lifecycle.operation_record.view',
            'equipment_lifecycle.ledger.view',
            'equipment_lifecycle.ledger.add',
            'equipment_lifecycle.ledger_template.view',
            'equipment_lifecycle.config.view',
            'upgrade.upgrade.view',
        ], tenant_id=self.tenant)
        self.client = make_client(self.user)

        self.systems = [
            make_system(self.user, tenant_id=self.tenant,
                        system_code='PERF-SYS-%03d' % i,
                        name='性能基线系统%03d' % i)
            for i in range(SYSTEM_COUNT)
        ]
        record_types = ['routine', 'abnormal', 'fault']
        statuses = ['recorded', 'following_up', 'completed', 'handling']
        for i in range(RECORD_COUNT):
            record = make_record(
                self.user, self.systems[i % len(self.systems)],
                record_type=record_types[i % 3],
                tenant_id=self.tenant,
                occurred_at='2026-10-%02d 08:00:00' % (i % 28 + 1),
                title='性能基线记录%03d' % i)
            if record.record_type == 'fault':
                record.status = statuses[3]
            else:
                record.status = statuses[i % 3]
            record.save(update_fields=['status'])
            for j in range(PROGRESS_PER_RECORD):
                SystemOperationProgress.objects.create(
                    record=record, handled_at=datetime.datetime(2026, 10, 20, 9, j),
                    handler=self.user, content='进展%d' % j,
                    tenant_id=self.tenant)
        for i in range(UPGRADE_COUNT):
            UpgradeRecord.objects.create(
                upgrade_no='SJ20261020-%04d' % i,
                tenant_id=self.tenant, title='性能基线升级%03d' % i,
                system=self.systems[i % len(self.systems)],
                system_name=self.systems[i % len(self.systems)].name,
                upgrade_type='软件升级', owner='性能测试',
                created_by=self.user)
        # 手工台账走真实 API（与生产路径一致）
        self.ledger_ids = []
        for i in range(LEDGER_COUNT):
            ledger = create_ledger_ok(self.client, ledger_payload(
                [entry_payload(self.systems[i % len(self.systems)].id,
                               [item_payload()])],
                executed_start='2026-10-%02d 09:00' % (i % 28 + 1),
                executed_end='2026-10-%02d 10:00' % (i % 28 + 1)))
            self.ledger_ids.append(ledger['id'])

    @staticmethod
    def _measure(client, url, repeats=REPEATS):
        """返回 (中位耗时ms, 查询条数, http_status, error)。"""
        durations = []
        queries = 0
        status = None
        error = None
        for attempt in range(repeats):
            with CaptureQueriesContext(connection) as ctx:
                start = time.perf_counter()
                response = client.get(url)
                elapsed = (time.perf_counter() - start) * 1000
            durations.append(elapsed)
            queries = len(ctx.captured_queries)
            status = response.status_code
            try:
                error = response.json().get('error')
            except (ValueError, AttributeError):
                error = '<non-json>'
            if response.status_code >= 500:
                break
        durations.sort()
        return round(durations[len(durations) // 2], 1), queries, status, error

    def test_read_endpoints_baseline(self):
        self._flush_tables()
        self._seed()
        record_detail_id = SystemOperationRecord.objects.filter(
            tenant_id=self.tenant).values_list('id', flat=True).first()
        system_detail_id = self.systems[0].id

        targets = [
            ('systems_list', SYSTEMS_URL + '/'),
            ('systems_detail', '%s/%s/' % (SYSTEMS_URL, system_detail_id)),
            ('records_list', RECORDS_URL + '/'),
            ('records_list_filtered', RECORDS_URL + '/?record_type=abnormal&status=recorded'),
            ('records_detail', '%s/%s/' % (RECORDS_URL, record_detail_id)),
            ('records_statistics', RECORDS_URL + '/statistics/'),
            ('records_todo', RECORDS_URL + '/todo/'),
            ('records_candidate_systems', RECORDS_URL + '/candidate-systems/'),
            ('ledger_list', LEDGER_URL + '/'),
            ('ledger_list_status_all', LEDGER_URL + '/?status=all'),
            ('ledger_period_groups', LEDGER_URL + '/period-groups/?ledger_type=week_month'),
            ('ledger_template_groups', LEDGER_URL + '/template-groups/?ledger_type=week_month'),
            ('excel_template_list', TPL_URL + '/'),
            ('excel_template_available', TPL_URL + '/available/?ledger_type=week_month'),
            ('upgrade_records_list', UPGRADE_URL + '/records/'),
            ('upgrade_filter_options', UPGRADE_URL + '/filter-options/'),
        ]

        results = []
        for name, url in targets:
            median_ms, queries, status, error = self._measure(self.client, url)
            results.append({
                'endpoint': name, 'url': url, 'median_ms': median_ms,
                'sql_queries': queries, 'http_status': status,
                'error': error or '',
            })
            self.assertEqual(status, 200, (name, status))
            self.assertFalse(error, (name, error))

        print('\n__BASELINE_JSON__')
        print(json.dumps(results, ensure_ascii=False))
