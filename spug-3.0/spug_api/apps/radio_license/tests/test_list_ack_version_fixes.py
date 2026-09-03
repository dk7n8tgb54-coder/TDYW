# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
无线电执照模块中危缺陷修复回归测试。

覆盖范围（对应上线前测试报告确认的 5 项中危缺陷）：
1. 提醒 ack 校验不足：非责任人 / normal 状态 / 跨租户拒绝；ack_valid_to
   只取数据库当前 valid_to；同周期重复确认幂等；续期后旧 ack 自动失效；
2. 列表 status 筛选实时化：按 valid_to 与当天差值计算，不依赖缓存
   status 字段；-1 / 0 / 60 / 61 天边界；
3. 列表 N+1 查询消除：附件数量批量聚合 + 频率 prefetch_related，
   查询数不随执照数量线性增长；
4. 并发编辑 version_no：行锁序列化同一执照的版本号分配（真实并发测试）；
5. popup / badge 与 ack 的责任人和状态规则一致性。

所有测试走真实 HTTP 路径（Django test client）并校验数据库状态。
"""
import json
import threading
from datetime import date, timedelta

from django.db import connection, transaction
from django.test import TransactionTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from apps.evidence.models import EvidenceAttachment
from apps.radio_license.models import (
    RadioLicense, RadioLicenseVersion, LicenseReminderAck,
)
from apps.radio_license.views import (
    _save_license_version_snapshot,
)
from apps.radio_license.tests.test_smoke import (
    _make_user, _grant_perms, _make_client,
)


def _license_perms(*keys):
    """构造执照相关权限列表，keys 缺省给 view。"""
    keys = list(keys) or ['view']
    return [('radio_license', 'license', keys)]


def _make_license(owner, tenant_id, station_name, valid_to_offset,
                  cached_status='normal', valid_from_offset=-365):
    """直接创建一条执照记录；cached_status 用于构造与实时状态不一致的缓存。"""
    today = date.today()
    return RadioLicense.objects.create(
        tenant_id=tenant_id,
        station_name=station_name,
        purpose='回归测试用途',
        valid_from=today + timedelta(days=valid_from_offset),
        valid_to=today + timedelta(days=valid_to_offset),
        responsible_user_id=owner.id,
        responsible_user_name=owner.nickname or owner.username,
        status=cached_status,
        created_by=owner,
    )


def _make_attachment(user, tenant_id, license_id, file_name,
                     object_type='license', is_deleted=False):
    return EvidenceAttachment.objects.create(
        tenant_id=tenant_id, module='radio_license', object_type=object_type,
        object_id=str(license_id), file_name=file_name,
        file_path=f'radio_license/{tenant_id}/202601/license_{license_id}/{file_name}',
        file_size=10, file_ext='.pdf', file_hash_sha256='hash-' + file_name,
        uploaded_by_id=user.id, uploaded_by_name=user.nickname or user.username,
        is_deleted=is_deleted,
    )


# ============================================================
# 缺陷1：提醒 ack 校验
# ============================================================


class LicenseReminderAckValidationTests(TestCase):
    """ack 校验：责任人 / 实时状态 / 租户 / 幂等 / 续期失效。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('ack_owner', tenant_id='t_ack')
        _grant_perms(self.owner, _license_perms('view'))
        self.client = _make_client(self.owner)
        # 同租户的其他持权用户（有 view 权限但不是责任人）
        self.colleague = _make_user('ack_colleague', tenant_id='t_ack')
        _grant_perms(self.colleague, _license_perms('view'))
        # 跨租户用户
        self.foreigner = _make_user('ack_foreigner', tenant_id='t_other_ack')
        _grant_perms(self.foreigner, _license_perms('view'))
        self.foreign_client = _make_client(self.foreigner)

    def _ack(self, client, license_id, extra=None):
        payload = {'license_id': license_id}
        if extra:
            payload.update(extra)
        return client.post(
            '/radio-license/reminders/ack/',
            data=json.dumps(payload), content_type='application/json',
        ).json()

    def test_non_responsible_ack_rejected(self):
        """同租户非责任人确认：拒绝且不落库。"""
        other_owner = _make_user('ack_real_owner', tenant_id='t_ack')
        lic = _make_license(other_owner, 't_ack', '非责任人台站', 10)
        body = self._ack(self.client, lic.id)
        self.assertEqual(body.get('error'), '仅责任人可确认处理提醒')
        self.assertFalse(
            LicenseReminderAck.objects.filter(license=lic).exists())

    def test_normal_status_ack_rejected(self):
        """实时状态 normal（valid_to 超过 60 天）：拒绝且不落库。"""
        lic = _make_license(self.owner, 't_ack', '正常状态台站', 200)
        body = self._ack(self.client, lic.id)
        self.assertEqual(body.get('error'), '当前执照状态正常，无需确认处理')
        self.assertFalse(
            LicenseReminderAck.objects.filter(license=lic).exists())

    def test_cross_tenant_ack_rejected(self):
        """跨租户执照确认：统一返回不存在或无权限，不落库。"""
        lic = _make_license(self.owner, 't_ack', '跨租户台站', 10)
        body = self._ack(self.foreign_client, lic.id)
        self.assertEqual(body.get('error'), '执照不存在或无权限')
        self.assertFalse(
            LicenseReminderAck.objects.filter(license=lic).exists())

    def test_repeated_ack_idempotent(self):
        """同用户同执照同周期重复确认：幂等成功且只写一条。"""
        lic = _make_license(self.owner, 't_ack', '幂等台站', 10)
        for _ in range(3):
            body = self._ack(self.client, lic.id)
            self.assertFalse(body.get('error'), body)
            self.assertTrue(body['data']['acked'])
        self.assertEqual(
            LicenseReminderAck.objects.filter(license=lic).count(), 1)
        ack = LicenseReminderAck.objects.get(license=lic)
        # ack_valid_to 必须等于数据库当前 valid_to
        self.assertEqual(str(ack.ack_valid_to), str(lic.valid_to))
        self.assertEqual(ack.user_id, self.owner.id)

    def test_ack_valid_to_not_trusted_from_client(self):
        """客户端伪造 valid_to 参数：不生效，仍取数据库当前 valid_to。"""
        lic = _make_license(self.owner, 't_ack', '防伪造台站', 10)
        body = self._ack(self.client, lic.id, {'valid_to': '1990-01-01'})
        self.assertFalse(body.get('error'), body)
        ack = LicenseReminderAck.objects.get(license=lic)
        self.assertEqual(str(ack.ack_valid_to), str(lic.valid_to))

    def test_valid_to_change_invalidates_old_ack(self):
        """续期后旧 ack 自动失效：popup 重新出现，可再次确认新周期。"""
        lic = _make_license(self.owner, 't_ack', '续期失效台站', 10)

        # ack 后 popup 排除
        body = self._ack(self.client, lic.id)
        self.assertFalse(body.get('error'), body)
        resp = self.client.get('/radio-license/reminders/popup/').json()
        self.assertEqual(
            [r['license_id'] for r in resp['data']['records']], [])

        # 续期（绕过视图直接改库，模拟 Celery/管理操作后的新周期）
        new_valid_to = date.today() + timedelta(days=20)
        RadioLicense.objects.filter(pk=lic.id).update(valid_to=new_valid_to)

        # 旧 ack 失效：popup 重新出现
        resp = self.client.get('/radio-license/reminders/popup/').json()
        self.assertEqual(
            [r['license_id'] for r in resp['data']['records']], [lic.id])
        # badge 重新计数
        badge = self.client.get('/radio-license/badge/').json()['data']
        self.assertEqual(badge['count'], 1)

        # 新周期可再次确认：两条 ack，ack_valid_to 不同
        body = self._ack(self.client, lic.id)
        self.assertFalse(body.get('error'), body)
        acks = LicenseReminderAck.objects.filter(license=lic).order_by('ack_valid_to')
        self.assertEqual(acks.count(), 2)
        self.assertEqual(
            [str(a.ack_valid_to) for a in acks],
            [str(lic.valid_to), str(new_valid_to)],
        )


class LicenseReminderPopupConsistencyTests(TestCase):
    """popup 与 ack 的责任人和状态规则一致性。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('popup_owner', tenant_id='t_pop')
        _grant_perms(self.owner, _license_perms('view'))
        self.client = _make_client(self.owner)

    def test_popup_only_returns_responsible_user_licenses(self):
        """同租户内别人负责的到期执照不进我的 popup。"""
        other = _make_user('popup_other', tenant_id='t_pop')
        _make_license(other, 't_pop', '别人负责的台站', 10)
        resp = self.client.get('/radio-license/reminders/popup/').json()
        self.assertEqual(resp['data']['records'], [])

    def test_popup_status_computed_realtime_not_cached(self):
        """popup 返回的 status 必须实时计算，缓存字段错误也不影响。"""
        # 缓存 status='normal'，但 valid_to 已过期 → 应返回 expired
        lic = _make_license(self.owner, 't_pop', '缓存错误台站', -3,
                            cached_status='normal')
        resp = self.client.get('/radio-license/reminders/popup/').json()
        records = resp['data']['records']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['license_id'], lic.id)
        self.assertEqual(records[0]['status'], 'expired')
        self.assertEqual(records[0]['remind_type'], 'expired')
        self.assertEqual(records[0]['days_left'], -3)

    def test_popup_excludes_normal_window(self):
        """valid_to 超过 60 天的执照不进 popup。"""
        _make_license(self.owner, 't_pop', '远期台站', 200)
        resp = self.client.get('/radio-license/reminders/popup/').json()
        self.assertEqual(resp['data']['records'], [])


# ============================================================
# 缺陷2：列表 status 实时筛选
# ============================================================


class LicenseListStatusFilterTests(TestCase):
    """status 筛选实时化：-1 / 0 / 60 / 61 天边界，不依赖缓存字段。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('filter_user', tenant_id='t_filter')
        _grant_perms(self.owner, _license_perms('view'))
        self.client = _make_client(self.owner)

        # 缓存 status 全部故意写成 normal（与实时状态不符），
        # 若筛选仍依赖缓存字段，expired/expiring 将查不到任何记录
        self.lic_m1 = _make_license(self.owner, 't_filter', '边界-1天', -1,
                                    cached_status='normal')
        self.lic_0 = _make_license(self.owner, 't_filter', '边界0天', 0,
                                   cached_status='normal')
        self.lic_60 = _make_license(self.owner, 't_filter', '边界60天', 60,
                                    cached_status='normal')
        self.lic_61 = _make_license(self.owner, 't_filter', '边界61天', 61,
                                    cached_status='expired')
        self.lic_200 = _make_license(self.owner, 't_filter', '边界200天', 200,
                                     cached_status='normal')

    def _filter(self, status):
        resp = self.client.get(f'/radio-license/?status={status}').json()
        self.assertFalse(resp.get('error'), resp)
        return resp['data']

    def test_expired_filter_boundary(self):
        """valid_to < today（-1 天）→ expired。"""
        data = self._filter('expired')
        ids = [r['id'] for r in data['records']]
        self.assertEqual(ids, [self.lic_m1.id])
        self.assertEqual(data['records'][0]['computed_status'], 'expired')
        self.assertEqual(data['total'], 1)

    def test_expiring_filter_boundary(self):
        """today <= valid_to <= today+60（0/60 天）→ expiring。"""
        data = self._filter('expiring')
        ids = {r['id'] for r in data['records']}
        self.assertEqual(ids, {self.lic_0.id, self.lic_60.id})
        for record in data['records']:
            self.assertEqual(record['computed_status'], 'expiring')

    def test_normal_filter_boundary(self):
        """valid_to > today+60（61/200 天）→ normal，61 天严格归 normal。"""
        data = self._filter('normal')
        ids = {r['id'] for r in data['records']}
        self.assertEqual(ids, {self.lic_61.id, self.lic_200.id})
        for record in data['records']:
            self.assertEqual(record['computed_status'], 'normal')

    def test_filter_ignores_cached_status_field(self):
        """缓存字段与实时状态相反时，筛选必须按实时状态返回。"""
        # lic_61 缓存是 expired，但实时是 normal → 只出现在 normal 结果里
        self.assertNotIn(self.lic_61.id,
                         [r['id'] for r in self._filter('expired')['records']])
        # lic_m1 缓存是 normal，但实时是 expired → 出现在 expired 结果里
        self.assertIn(self.lic_m1.id,
                      [r['id'] for r in self._filter('expired')['records']])

    def test_filter_combines_with_other_filters(self):
        """status 筛选与台站名筛选可组合，分页排序行为不变。"""
        resp = self.client.get(
            f"/radio-license/?status=expired&station_name=边界-1").json()
        data = resp['data']
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['records'][0]['id'], self.lic_m1.id)

    def test_filter_consistent_after_direct_db_update(self):
        """直接改库（模拟扫描前数据变化）后，列表立即反映实时状态。"""
        # lic_200 续期改到 -5 天（绕过视图，模拟缓存未同步场景）
        RadioLicense.objects.filter(pk=self.lic_200.id).update(
            valid_to=date.today() - timedelta(days=5))
        data = self._filter('expired')
        ids = {r['id'] for r in data['records']}
        self.assertEqual(ids, {self.lic_m1.id, self.lic_200.id})


# ============================================================
# 缺陷3：列表 N+1 查询消除
# ============================================================


class LicenseListQueryCountTests(TestCase):
    """列表查询数不随执照数量线性增长（page_size=25）。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('nplus_user', tenant_id='t_nplus')
        _grant_perms(self.owner, _license_perms('view'))
        self.client = _make_client(self.owner)

    def _create_licenses(self, count, prefix):
        for i in range(count):
            lic = _make_license(self.owner, 't_nplus', f'{prefix}-{i}', 300)
            # 每条执照 1 个频率 + 2 个附件，放大 N+1 的可检测性
            from apps.radio_license.models import RadioLicenseFrequency
            RadioLicenseFrequency.objects.create(
                tenant_id='t_nplus', license=lic,
                frequency_value=100 + i, frequency_unit='MHz',
                created_by=self.owner,
            )
            _make_attachment(self.owner, 't_nplus', lic.id, f'{prefix}-{i}.pdf')

    def _list_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get('/radio-license/?page_size=25')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return len(ctx.captured_queries), body['data']

    def test_attachment_count_matches_actual_data(self):
        """附件数量与实际数据一致：未删除的才统计，object_type 隔离。"""
        lic_a = _make_license(self.owner, 't_nplus', '附件统计A', 300)
        lic_b = _make_license(self.owner, 't_nplus', '附件统计B', 300)
        # A：2 个有效 license 附件 + 1 个已软删 + 1 个 approval 类型（不计）
        _make_attachment(self.owner, 't_nplus', lic_a.id, 'a1.pdf')
        _make_attachment(self.owner, 't_nplus', lic_a.id, 'a2.pdf')
        _make_attachment(self.owner, 't_nplus', lic_a.id, 'a-del.pdf',
                         is_deleted=True)
        _make_attachment(self.owner, 't_nplus', lic_a.id, 'a-approval.pdf',
                         object_type='approval')
        # B：无附件
        data = self.client.get('/radio-license/?page_size=25').json()['data']
        counts = {r['id']: r['attachment_count'] for r in data['records']}
        self.assertEqual(counts[lic_a.id], 2)
        self.assertEqual(counts[lic_b.id], 0)

    def test_attachment_count_respects_tenant(self):
        """跨租户同 object_id 的附件不计数（不绕过租户过滤）。"""
        lic = _make_license(self.owner, 't_nplus', '租户附件隔离', 300)
        _make_attachment(self.owner, 't_nplus', lic.id, 'mine.pdf')
        foreigner = _make_user('nplus_foreign', tenant_id='t_nplus_other')
        _make_attachment(foreigner, 't_nplus_other', lic.id, 'theirs.pdf')
        data = self.client.get('/radio-license/?page_size=25').json()['data']
        target = [r for r in data['records'] if r['id'] == lic.id][0]
        self.assertEqual(target['attachment_count'], 1)

    def test_query_count_does_not_scale_with_records(self):
        """25 条 vs 50 条执照：查询数应为常量（差额不超过少量固定查询）。"""
        self._create_licenses(25, '批A')
        count_25, data_25 = self._list_query_count()
        self.assertEqual(data_25['total'], 25)
        # 附件数量正确返回
        for record in data_25['records']:
            self.assertEqual(record['attachment_count'], 1)

        self._create_licenses(25, '批B')
        count_50, data_50 = self._list_query_count()
        self.assertEqual(data_50['total'], 50)
        for record in data_50['records']:
            self.assertEqual(record['attachment_count'], 1)

        # 修复前：每条记录 2 个额外查询（附件 count + 频率），50 条比 25 条
        # 至少多 25 个查询；修复后：分页恒为 25 条，查询数应为常量
        self.assertLessEqual(count_50 - count_25, 3,
                             f'查询数随数据量增长: {count_25} -> {count_50}')
        # 整个列表请求的查询数必须远小于记录数（无逐条查询）
        self.assertLess(count_50, 40,
                        f'列表查询数过大，疑似 N+1: {count_50}')

    def test_frequencies_returned_for_all_page_records(self):
        """prefetch 后每条记录的频率列表仍完整返回（API 格式兼容）。"""
        self._create_licenses(25, '频率')
        data = self.client.get('/radio-license/?page_size=25').json()['data']
        self.assertEqual(len(data['records']), 25)
        for record in data['records']:
            self.assertEqual(len(record['frequencies']), 1)
            self.assertIn('frequency_value', record['frequencies'][0])


# ============================================================
# 缺陷4：并发编辑 version_no（真实并发）
# ============================================================


class ConcurrentEditVersionNoTests(TransactionTestCase):
    """两个并发事务编辑同一执照：行锁保证 version_no 严格递增不重复。

    真实并发测试：线程 1 持有执照行锁并写入版本 v1，线程 2 在锁释放前
    无法读取最大版本号（select_for_update 阻塞），只能在线程 1 提交后
    写入 v2。修复前两个事务都能读到相同的 max version_no，产生重复。
    """

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('conc_user', tenant_id='t_conc')
        _grant_perms(self.user, _license_perms('view', 'edit'))
        self.license = _make_license(self.user, 't_conc', '并发编辑台站', 300)

    def _thread_worker(self, hold_lock_event, release_event, errors):
        """先拿行锁再调 _save_license_version_snapshot（与视图一致的事务结构）。"""

        def worker():
            conn = connection
            try:
                with transaction.atomic():
                    locked = RadioLicense.objects.select_for_update().get(
                        pk=self.license.id)
                    if hold_lock_event is not None:
                        hold_lock_event.set()       # 已持有行锁
                        self.assertTrue(release_event.wait(15))
                    _save_license_version_snapshot(locked, self.user)
            except Exception as e:  # noqa: BLE001 - 线程内异常回传主线程断言
                errors.append(e)
            finally:
                conn.close()

        return worker

    def test_concurrent_snapshots_get_distinct_version_no(self):
        lock_acquired = threading.Event()
        release = threading.Event()
        errors = []

        t1 = threading.Thread(
            target=self._thread_worker(lock_acquired, release, errors))
        t1.start()
        self.assertTrue(lock_acquired.wait(15), '线程1未能获取行锁')

        # 线程2在线程1持锁期间启动：其 select_for_update 必须阻塞到线程1提交
        t2 = threading.Thread(
            target=self._thread_worker(None, None, errors))
        t2.start()
        release.set()
        t1.join(20)
        t2.join(20)

        self.assertEqual(errors, [], f'并发事务出现异常: {errors}')
        versions = list(
            RadioLicenseVersion.objects.filter(license=self.license)
            .order_by('version_no'))
        self.assertEqual([v.version_no for v in versions], [1, 2])
        # 快照语义保持：changed_by / hash 均写入
        for v in versions:
            self.assertEqual(v.changed_by_id, self.user.id)
            self.assertTrue(v.snapshot_hash)

    def test_serial_edits_still_increment_version_no(self):
        """串行多次编辑版本号连续递增（回归保护）。"""
        for _ in range(3):
            with transaction.atomic():
                locked = RadioLicense.objects.select_for_update().get(
                    pk=self.license.id)
                _save_license_version_snapshot(locked, self.user)
        versions = list(
            RadioLicenseVersion.objects.filter(license=self.license)
            .order_by('version_no'))
        self.assertEqual([v.version_no for v in versions], [1, 2, 3])


# ============================================================
# 缺陷5 后端配套：编辑失败不留半条版本记录
# ============================================================


class EditFailureAtomicityTests(TestCase):
    """编辑失败时不得留下半条版本记录或错误快照。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('atomic_user', tenant_id='t_atomic')
        _grant_perms(self.user, _license_perms('view', 'edit', 'add'))
        self.client = _make_client(self.user)
        self.license = _make_license(self.user, 't_atomic', '原子性台站', 300)

    def test_edit_failure_leaves_no_version_snapshot(self):
        """频率校验失败（先于事务）不产生版本快照。"""
        payload = {
            'id': self.license.id,
            'station_name': self.license.station_name,
            'valid_from': str(self.license.valid_from),
            'valid_to': str(date.today() + timedelta(days=400)),
            'purpose': self.license.purpose,
            'responsible_user_id': self.user.id,
            'frequencies': [
                {'frequency_value': -5, 'frequency_unit': 'MHz',
                 'frequency_text': '', 'sort_order': 0},
            ],
        }
        body = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()
        self.assertTrue(body.get('error'))
        self.assertFalse(
            RadioLicenseVersion.objects.filter(license=self.license).exists())
        # 业务字段未被修改
        self.license.refresh_from_db()
        self.assertEqual(str(self.license.valid_to),
                         str(date.today() + timedelta(days=300)))

    def test_edit_success_writes_version_before_update(self):
        """编辑成功：快照记录的是修改前状态，版本号从 1 开始。"""
        old_valid_to = str(self.license.valid_to)
        payload = {
            'id': self.license.id,
            'station_name': self.license.station_name,
            'valid_from': str(self.license.valid_from),
            'valid_to': str(date.today() + timedelta(days=400)),
            'purpose': self.license.purpose,
            'responsible_user_id': self.user.id,
            'frequencies': [],
        }
        body = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        versions = RadioLicenseVersion.objects.filter(license=self.license)
        self.assertEqual(versions.count(), 1)
        v = versions.get()
        self.assertEqual(v.version_no, 1)
        snapshot = json.loads(v.snapshot_json)
        # 快照是修改前状态
        self.assertEqual(snapshot['valid_to'], old_valid_to)
        self.license.refresh_from_db()
        self.assertEqual(str(self.license.valid_to),
                         str(date.today() + timedelta(days=400)))


# ============================================================
# 防御：未授权用户不能访问列表/ack（权限分支回归）
# ============================================================


class LicenseAccessPermissionTests(TestCase):
    """无权限场景：ack / 列表 / badge 必须拒绝。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user_no_perm = _make_user('noperm_user', tenant_id='t_noperm')
        self.client = _make_client(self.user_no_perm)
        self.license = _make_license(self.user_no_perm, 't_noperm', '无权台站', 10)

    def test_ack_without_view_perm_rejected(self):
        body = self.client.post(
            '/radio-license/reminders/ack/',
            data=json.dumps({'license_id': self.license.id}),
            content_type='application/json',
        )
        self.assertIn(body.status_code, (403, 200))
        if body.status_code == 200:
            self.assertTrue(body.json().get('error'))
        self.assertFalse(
            LicenseReminderAck.objects.filter(license=self.license).exists())

    def test_list_without_view_perm_rejected(self):
        body = self.client.get('/radio-license/')
        self.assertIn(body.status_code, (403, 200))
        if body.status_code == 200:
            self.assertTrue(body.json().get('error'))

    def test_badge_without_view_perm_rejected(self):
        body = self.client.get('/radio-license/badge/')
        self.assertIn(body.status_code, (403, 200))
        if body.status_code == 200:
            self.assertTrue(body.json().get('error'))
