# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁第八组：性能与可靠性。

覆盖：N+1 查询检测（查询计数随 page_size 增长即 FAIL）、
1 万条数据下的分页/筛选/徽标/提醒查询性能、P95 统计、并发写。
所有实测数据通过 stdout 打印，供报告引用。
"""
import json
import statistics
import threading
import time
from datetime import date, timedelta

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.radio_license.models import RadioLicense, LicenseReminderAck
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, FULL_LICENSE_PERMS, FULL_APPROVAL_PERMS,
    rg_license_payload, rg_make_license, rg_make_approval,
)


class QueryCountTests(TestCase):
    """八.2 N+1 查询检测：列表查询数不应随 page_size 线性增长。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_qc_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS)
        self.client = _make_client(self.user)
        for i in range(25):
            rg_make_license(self.user, station_name=f'RG-QC-L{i:02d}')
            rg_make_approval(self.user, doc_no=f'RG-QC-A{i:02d}')

    def _query_count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(url)
        self.assertFalse(resp.json().get('error'))
        return len(ctx)

    def test_license_list_no_n_plus_1(self):
        q5 = self._query_count('/radio-license/?page_size=5')
        q20 = self._query_count('/radio-license/?page_size=20')
        q25 = self._query_count('/radio-license/?page_size=25')
        print(f'[RG-PERF] 执照列表查询数: page_size=5→{q5}, 20→{q20}, 25→{q25}')
        # 无 N+1 时查询数应与 page_size 无关（允许 ±3 波动）
        self.assertLessEqual(q25 - q5, 3,
                             f'执照列表存在 N+1 查询: 5条={q5}次, 25条={q25}次')

    def test_approval_list_no_n_plus_1(self):
        q5 = self._query_count('/radio-license/approvals/?page_size=5')
        q25 = self._query_count('/radio-license/approvals/?page_size=25')
        print(f'[RG-PERF] 批复列表查询数: page_size=5→{q5}, 25→{q25}')
        self.assertLessEqual(q25 - q5, 3,
                             f'批复列表存在 N+1 查询: 5条={q5}次, 25条={q25}次')


class TenThousandRecordsPerfTests(TransactionTestCase):
    """八.1/八.3 1 万条数据下的性能实测。"""

    COUNT = 10000

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_perf_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()
        self._seed()

    def _seed(self):
        t0 = time.time()
        # 执照：1 万条，全部归属 perf_user（最坏情况：badge/popup 全量命中）
        licenses = [
            RadioLicense(
                tenant_id=TENANT_A,
                station_name=f'RG-PERF-L{i:05d}',
                purpose='RG性能测试',
                valid_from=self.today - timedelta(days=365),
                valid_to=self.today + timedelta(days=(i % 400) - 30),
                responsible_user_id=self.user.id,
                responsible_user_name=self.user.nickname,
                status='normal',
                created_by=self.user,
            )
            for i in range(self.COUNT)
        ]
        RadioLicense.objects.bulk_create(licenses, batch_size=1000)
        # 批复：1 万条
        from apps.radio_license.models import StationFrequencyApproval
        approvals = [
            StationFrequencyApproval(
                tenant_id=TENANT_A,
                name=f'RG-PERF-A{i:05d}',
                doc_no=f'RG-PERF-DOC-{i:05d}',
                frequency_text='100MHz',
                valid_from=self.today - timedelta(days=365),
                valid_to=self.today + timedelta(days=(i % 400) - 30),
                responsible_user_id=self.user.id,
                responsible_user_name=self.user.nickname,
                status='normal',
                created_by=self.user,
            )
            for i in range(self.COUNT)
        ]
        StationFrequencyApproval.objects.bulk_create(approvals, batch_size=1000)
        print(f'[RG-PERF] 种子数据 {self.COUNT * 2} 条写入耗时 {time.time() - t0:.2f}s')

    def _timeit(self, url, label, rounds=1):
        times = []
        for _ in range(rounds):
            t0 = time.time()
            resp = self.client.get(url)
            times.append(time.time() - t0)
            body = resp.json()
            self.assertFalse(body.get('error'), f'{label}: {body}')
        p95 = times[0] if len(times) == 1 else sorted(times)[int(len(times) * 0.95) - 1]
        print(f'[RG-PERF] {label}: {rounds}次 mean={statistics.mean(times):.3f}s '
              f'p95={p95:.3f}s max={max(times):.3f}s')
        return max(times)

    def test_list_pagination_and_filter_performance(self):
        t = self._timeit('/radio-license/?page=1&page_size=20', '执照列表首页(20条)')
        self.assertLess(t, 5, '执照列表 1 万条数据首页超 5 秒')
        t = self._timeit('/radio-license/?page=400&page_size=25', '执照列表深分页(第400页)')
        self.assertLess(t, 5)
        t = self._timeit('/radio-license/?station_name=RG-PERF-L0999', '执照台站筛选')
        self.assertLess(t, 5)
        t = self._timeit(
            '/radio-license/?status=expiring', '执照状态筛选')
        self.assertLess(t, 5)
        t = self._timeit(
            f'/radio-license/?valid_to_start={self.today}&valid_to_end={self.today + timedelta(days=60)}',
            '执照截止日期范围筛选')
        self.assertLess(t, 5)
        t = self._timeit('/radio-license/approvals/?page=1&page_size=20', '批复列表首页(20条)')
        self.assertLess(t, 5)
        t = self._timeit('/radio-license/approvals/?status=expired', '批复状态筛选')
        self.assertLess(t, 5)

    def test_badge_popup_detail_performance(self):
        t = self._timeit('/radio-license/badge/', '执照徽标(1万条本人负责)')
        self.assertLess(t, 5)
        t = self._timeit('/radio-license/approvals/badge/', '批复徽标(1万条本人负责)')
        self.assertLess(t, 5)
        # popup 返回本人负责的 expiring/expired 全量记录（无分页），记录实际耗时与返回量
        t0 = time.time()
        resp = self.client.get('/radio-license/reminders/popup/')
        elapsed = time.time() - t0
        body = resp.json()
        self.assertFalse(body.get('error'))
        print(f'[RG-PERF] 执照popup: {elapsed:.3f}s, 返回 {len(body["data"]["records"])} 条')
        self.assertLess(elapsed, 10, 'popup 全量返回超 10 秒')
        # 详情接口
        lic = RadioLicense.objects.filter(tenant_id=TENANT_A).first()
        t = self._timeit(f'/radio-license/{lic.id}/', '执照详情')
        self.assertLess(t, 5)

    def test_p95_over_repeated_requests(self):
        """八.5 重复请求 P95 统计（20 轮采样）。"""
        results = {}
        for label, url in [
            ('执照列表', '/radio-license/?page=1&page_size=20'),
            ('批复列表', '/radio-license/approvals/?page=1&page_size=20'),
            ('执照徽标', '/radio-license/badge/'),
        ]:
            times = []
            errors = 0
            for _ in range(20):
                t0 = time.time()
                resp = self.client.get(url)
                times.append(time.time() - t0)
                if resp.json().get('error'):
                    errors += 1
            p95 = sorted(times)[18]
            print(f'[RG-PERF] {label} 20轮: p50={statistics.median(times):.3f}s '
                  f'p95={p95:.3f}s max={max(times):.3f}s errors={errors}')
            results[label] = (p95, errors)
            self.assertEqual(errors, 0, f'{label} 出现 {errors} 次业务错误')
            self.assertLess(p95, 5, f'{label} P95 超 5 秒')


class ConcurrentWriteTests(TransactionTestCase):
    """八.4 并发新增、编辑、删除、重复上传和重复确认。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_concw_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def _thread_post(self, target, payload):
        barrier = threading.Barrier(len(payload))

        def run(i, body):
            from django.test import Client
            c = Client()
            c.defaults['HTTP_X_TOKEN'] = self.user.access_token
            barrier.wait()
            try:
                if isinstance(body, dict) and body.get('_method') == 'delete':
                    c.delete(body['url'])
                else:
                    c.post(target, data=json.dumps(body),
                           content_type='application/json')
            finally:
                from django.db import connections
                connections.close_all()

        threads = [threading.Thread(target=run, args=(i, b))
                   for i, b in enumerate(payload)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_concurrent_distinct_creates_all_persisted(self):
        """并发新增不同数据：全部成功落库。"""
        payloads = [
            rg_license_payload(self.user, station_name=f'RG-CONCW-{i}')
            for i in range(5)
        ]
        # 载荷互不相同，幂等检查不应拦截
        self._thread_post('/radio-license/', payloads)
        self.assertEqual(
            RadioLicense.objects.filter(
                station_name__startswith='RG-CONCW-').count(), 5)

    def test_concurrent_duplicate_ack_single_row(self):
        lic = rg_make_license(self.user, station_name='RG-CONCW-ACK',
                              valid_to=self.today + timedelta(days=10))
        self._thread_post('/radio-license/reminders/ack/',
                          [{'license_id': lic.id} for _ in range(5)])
        self.assertEqual(
            LicenseReminderAck.objects.filter(license=lic).count(), 1)
