# -*- coding: utf-8 -*-
"""运行处置记录——列表"最近更新/持续时间"展示字段契约测试（2026-10-12）。

两列为计算展示字段（零数据库存储、不新增定时任务，列表接口即时计算）：
- 最近更新 latest_progress_at：该记录全部进展处理时间（handled_at）的最大值，
  后端单次聚合取得；不按进展创建时间或 ID 判断最新，不取主记录 updated_at；
- 持续时间 duration_seconds = 最新进展时间 - 主记录发生时间（occurred_at），
  三种记录类型同一口径，不随当前时间递增、不改用恢复/结案时间。

覆盖真实行为（真实 HTTP + 隔离测试数据库 + 数据库状态断言）：
1. 无进展：两字段均为 None（前端显示"-"）；
2. 多条进展且录入顺序与处理时间顺序不同：取处理时间最大值；
3. 跨天时长与 0 分钟差值；
4. 经真实更正端点修改进展处理时间后，最新进展时间与持续时间随之变化；
5. 最新进展早于发生时间：持续时间为 None（不取绝对值、不静默归零）；
6. 聚合来自全部进展（超出进展列表分页范围的进展仍参与取最大值）；
7. 主列表（/records/）与系统档案页签（/systems/<pk>/records/）两出口一致；
8. 三种记录类型计算口径一致；
9. 2026-10-14 起"持续时间"由列表改至详情展示：详情接口（/records/<pk>/）
   返回 duration_seconds，口径与列表行一致（列表行字段保留）。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.operation_models import SystemOperationProgress
from apps.equipment_lifecycle.operation_services import duration_seconds
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, RECORDS_URL, SYSTEM_RECORDS_URL, make_client,
    make_record, make_system, make_user,
)


class DurationSecondsServiceTest(TestCase):
    """duration_seconds 纯计算口径（服务层单测，真实函数执行）。"""

    def test_none_inputs_return_none(self):
        self.assertIsNone(duration_seconds(None, '2026-10-11 08:00:00'))
        self.assertIsNone(duration_seconds('2026-10-11 08:00:00', None))

    def test_zero_delta_returns_zero(self):
        from datetime import datetime
        at = datetime(2026, 10, 11, 8, 0, 0)
        self.assertEqual(duration_seconds(at, at), 0)

    def test_positive_delta_seconds(self):
        from datetime import datetime
        occurred = datetime(2026, 10, 11, 8, 0, 0)
        latest = datetime(2026, 10, 11, 8, 35, 0)
        self.assertEqual(duration_seconds(occurred, latest), 2100)

    def test_negative_delta_returns_none(self):
        from datetime import datetime
        occurred = datetime(2026, 10, 11, 8, 0, 0)
        latest = datetime(2026, 10, 11, 7, 0, 0)
        self.assertIsNone(duration_seconds(occurred, latest))


class OperationListDisplayTest(TestCase):
    """列表行最近更新/持续时间计算口径契约（主列表 + 系统档案页签）。"""

    def setUp(self):
        self.user = make_user('list_display_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def _add_progress(self, record, handled_at, content='处理进展'):
        """经真实进展端点追加进展。"""
        return self.client.post(
            RECORDS_URL + '/%d/progress/' % record.id,
            json.dumps({'handled_at': handled_at, 'content': content,
                        'handler_name': '李四'}),
            content_type='application/json')

    def _correct_progress(self, record, progress_id, handled_at):
        """经真实更正端点修改进展处理时间（时间更正）。"""
        return self.client.put(
            RECORDS_URL + '/%d/progress/%d/' % (record.id, progress_id),
            json.dumps({'handled_at': handled_at, 'content': '更正后的进展',
                        'correction_reason': '处理时间填写有误'}),
            content_type='application/json')

    def _main_rows(self, params=None):
        res = self.client.get(RECORDS_URL + '/', params or {})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data.get('error'), data)
        return {row['id']: row for row in data['data']['data']}

    def _system_rows(self, system_id):
        res = self.client.get(SYSTEM_RECORDS_URL % system_id)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data.get('error'), data)
        return {row['id']: row for row in data['data']['data']}

    def test_no_progress_returns_none_for_both_fields(self):
        record = make_record(self.user, self.system, record_type='abnormal',
                             occurred_at='2026-10-11 08:00:00')
        row = self._main_rows()[record.id]
        self.assertIsNone(row['latest_progress_at'])
        self.assertIsNone(row['duration_seconds'])
        # 数据库确无进展（展示字段不落库）
        self.assertEqual(SystemOperationProgress.objects.filter(record=record).count(), 0)

    def test_latest_progress_is_max_handled_at_regardless_of_creation_order(self):
        record = make_record(self.user, self.system, record_type='abnormal',
                             occurred_at='2026-10-11 08:00:00')
        # 先录入处理时间更晚的进展，再录入处理时间更早的进展：
        # 最新进展时间必须取处理时间最大值，而非最后创建/最大 ID 的一条
        self._add_progress(record, '2026-10-11 11:00', '后发生的进展')
        self._add_progress(record, '2026-10-11 09:30', '先发生的进展')
        row = self._main_rows()[record.id]
        self.assertEqual(row['latest_progress_at'], '2026-10-11 11:00:00')
        self.assertEqual(row['duration_seconds'], 3 * 3600)
        self.assertEqual(row['progress_count'], 2)

    def test_duration_cross_day(self):
        record = make_record(self.user, self.system, record_type='fault',
                             occurred_at='2026-10-11 08:00:00')
        self._add_progress(record, '2026-10-12 13:30')
        row = self._main_rows()[record.id]
        # 2026-10-11 08:00 → 2026-10-12 13:30 = 29.5 小时
        self.assertEqual(row['duration_seconds'], 29 * 3600 + 30 * 60)

    def test_duration_zero_when_progress_at_occurrence_time(self):
        record = make_record(self.user, self.system, record_type='routine',
                             occurred_at='2026-10-11 08:00:00')
        self._add_progress(record, '2026-10-11 08:00')
        row = self._main_rows()[record.id]
        # 差值为 0 是有效展示值（前端显示"0分钟"），不得误判为无进展
        self.assertEqual(row['latest_progress_at'], '2026-10-11 08:00:00')
        self.assertEqual(row['duration_seconds'], 0)

    def test_duration_none_when_latest_progress_before_occurred_at(self):
        record = make_record(self.user, self.system, record_type='abnormal',
                             occurred_at='2026-10-11 08:00:00')
        self._add_progress(record, '2026-10-11 07:00')
        row = self._main_rows()[record.id]
        # 最新进展时间正常返回，持续时间为 None（不取绝对值、不归零）
        self.assertEqual(row['latest_progress_at'], '2026-10-11 07:00:00')
        self.assertIsNone(row['duration_seconds'])

    def test_correction_updates_latest_and_duration_with_db_state(self):
        record = make_record(self.user, self.system, record_type='abnormal',
                             occurred_at='2026-10-11 08:00:00')
        res = self._add_progress(record, '2026-10-11 09:00')
        progress_id = res.json()['data']['id']
        row = self._main_rows()[record.id]
        self.assertEqual(row['duration_seconds'], 3600)

        # 更正处理时间到更晚：最新进展时间与持续时间随之变化
        res = self._correct_progress(record, progress_id, '2026-10-11 15:00')
        self.assertFalse(res.json().get('error'), res.json())
        progress = SystemOperationProgress.objects.get(pk=progress_id)
        self.assertEqual('%s' % progress.handled_at, '2026-10-11 15:00:00')
        row = self._main_rows()[record.id]
        self.assertEqual(row['latest_progress_at'], '2026-10-11 15:00:00')
        self.assertEqual(row['duration_seconds'], 7 * 3600)

        # 再更正到早于发生时间：持续时间为 None，最新进展时间仍返回
        res = self._correct_progress(record, progress_id, '2026-10-11 06:00')
        self.assertFalse(res.json().get('error'), res.json())
        row = self._main_rows()[record.id]
        self.assertEqual(row['latest_progress_at'], '2026-10-11 06:00:00')
        self.assertIsNone(row['duration_seconds'])

    def test_aggregation_covers_progress_beyond_progress_page_size(self):
        record = make_record(self.user, self.system, record_type='abnormal',
                             occurred_at='2026-10-11 08:00:00')
        # 进展列表接口默认按处理时间正序分页：批量造 100 条早期进展 + 1 条
        # 最晚进展（落在进展列表第 2 页），列表的"最近更新"仍须取到最晚一条，
        # 证明聚合来自后端全量进展而非当前进展分页
        SystemOperationProgress.objects.bulk_create([
            SystemOperationProgress(
                tenant_id=record.tenant_id, record=record,
                handled_at='2026-10-11 09:00:00', handler=self.user,
                handler_name='李四', content='批量进展 %d' % i)
            for i in range(100)
        ])
        self._add_progress(record, '2026-10-11 18:00', '最晚进展')
        # 进展列表接口第 1 页不含最晚进展
        res = self.client.get(RECORDS_URL + '/%d/progress/' % record.id)
        page_times = [p['handled_at'] for p in res.json()['data']['data']]
        self.assertNotIn('2026-10-11 18:00:00', page_times)
        # 主列表仍聚合到最晚进展
        row = self._main_rows()[record.id]
        self.assertEqual(row['latest_progress_at'], '2026-10-11 18:00:00')
        self.assertEqual(row['duration_seconds'], 10 * 3600)

    def test_system_records_endpoint_same_fields(self):
        record = make_record(self.user, self.system, record_type='fault',
                             occurred_at='2026-10-11 08:00:00')
        self._add_progress(record, '2026-10-11 10:00')
        row = self._system_rows(self.system.id)[record.id]
        self.assertEqual(row['latest_progress_at'], '2026-10-11 10:00:00')
        self.assertEqual(row['duration_seconds'], 2 * 3600)

    def test_same_caliber_across_three_record_types(self):
        # 三种记录类型共用同一口径：相同发生时间与进展时间 → 相同持续时间
        ids = {}
        for record_type in ('routine', 'abnormal', 'fault'):
            record = make_record(self.user, self.system, record_type=record_type,
                                 occurred_at='2026-10-11 08:00:00',
                                 title='%s口径' % record_type)
            self._add_progress(record, '2026-10-11 10:00')
            ids[record_type] = record.id
        rows = self._main_rows()
        for record_type, record_id in ids.items():
            self.assertEqual(rows[record_id]['duration_seconds'], 2 * 3600)

    def test_detail_response_includes_duration_seconds(self):
        """详情接口返回 duration_seconds（2026-10-14 起持续时间在详情展示）。

        口径与列表行一致 = 最新进展时间 - 发生时间；无进展/负差值为 None，
        更正进展处理时间后随真实数据重算，且与列表行取值一致。
        """
        record = make_record(self.user, self.system, record_type='abnormal',
                             occurred_at='2026-10-11 08:00:00')
        # 无进展：详情持续时间为 None（前端显示"-"）
        res = self.client.get(RECORDS_URL + '/%d/' % record.id)
        self.assertFalse(res.json().get('error'), res.json())
        data = res.json()['data']
        self.assertIsNone(data['duration_seconds'])

        # 有进展：详情与列表行的持续时间一致（2 小时）
        self._add_progress(record, '2026-10-11 10:00')
        res = self.client.get(RECORDS_URL + '/%d/' % record.id)
        data = res.json()['data']
        self.assertEqual(data['latest_progress_at'], '2026-10-11 10:00:00')
        self.assertEqual(data['duration_seconds'], 2 * 3600)
        row = self._main_rows()[record.id]
        self.assertEqual(row['duration_seconds'], data['duration_seconds'])

        # 更正处理时间到早于发生时间：详情持续时间为 None
        progress_id = SystemOperationProgress.objects.get(record=record).id
        res = self._correct_progress(record, progress_id, '2026-10-11 06:00')
        self.assertFalse(res.json().get('error'), res.json())
        res = self.client.get(RECORDS_URL + '/%d/' % record.id)
        self.assertIsNone(res.json()['data']['duration_seconds'])
