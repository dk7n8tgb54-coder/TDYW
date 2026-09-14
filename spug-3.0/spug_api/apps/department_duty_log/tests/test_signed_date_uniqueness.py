# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""同日唯一签署约束 - 真实行为测试

业务规则（stable_contract）：
- 同一天允许多条 draft（草稿不限量、创建不做同日检查）；
- 未删除记录中同一 duty_date 最多一条 status=signed；
- 同日已有一条 signed 后，其他 draft 不得再签署；
- 原 signed 退回 draft 后释放该日期，其他 draft 可再签署；
- 约束载体：nullable signed_date + 唯一索引 + 一致性 CHECK（MariaDB 10.8 兼容）；
- 并发最终仲裁由数据库唯一索引承担，服务层将 IntegrityError 转为业务错误。

所有用例均执行真实 Django/MariaDB 代码路径并校验数据库副作用，
不使用源码字符串匹配。并发用例使用 TransactionTestCase + 真实线程。
"""
import json
import shutil
import tempfile
import threading
import uuid
from datetime import date, timedelta

from django.db import transaction, IntegrityError
from django.test import TestCase, TransactionTestCase, override_settings

from apps.setting.utils import AppSetting
from apps.department_duty_log.models import DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED
from apps.department_duty_log import services

from apps.department_duty_log.tests.test_comprehensive import (
    _make_user, _make_client, _grant_perms, _make_record, _make_png_file,
)
from apps.department_duty_log.tests.test_department_duty_log_regression import (
    SignatureFlowBase,
)


# ============================================================
# 草稿创建：同日多条不受限
# ============================================================

class SameDayDraftCreationTests(TestCase):
    """草稿创建不限量：同日多条 draft 一律允许（HTTP 真实路径）"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_sd_creator', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'sign']),
        ])
        self.client = _make_client(self.user)

    def _post(self, duty_record, duty_date=None):
        return self.client.post(
            '/department-duty-log/records/', data=json.dumps({
                'duty_date': str(duty_date or date.today()),
                'weather': '晴',
                'duty_record': duty_record,
                'remark': '',
            }), content_type='application/json').json()

    def test_multiple_drafts_same_day_allowed(self):
        """同一天创建多条草稿全部成功（创建不做同日检查）"""
        for idx in range(3):
            body = self._post('同日草稿%d' % idx)
            self.assertFalse(body.get('error'), body)
        records = DepartmentDutyLog.objects.filter(
            duty_date=date.today(), status=STATUS_DRAFT)
        self.assertEqual(records.count(), 3)
        for record in records:
            self.assertIsNone(record.deleted_at)

    def test_new_draft_allowed_when_same_day_signed_exists(self):
        """同一天已有一条 signed 时，创建新草稿仍然成功"""
        _make_record(self.user, status=STATUS_SIGNED, duty_date=date.today())
        body = self._post('已签同日的另一条草稿')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(
            DepartmentDutyLog.objects.filter(
                duty_date=date.today(), status=STATUS_DRAFT).count(), 1)

    def test_signed_date_is_protected_field(self):
        """约束载体字段 signed_date 只能由服务端维护，客户端提交即拒绝"""
        body = self._post('提交 signed_date 字段')
        self.assertFalse(body.get('error'), body)
        payload = {
            'duty_date': str(date.today()),
            'weather': '晴',
            'duty_record': '伪造 signed_date',
            'remark': '',
            'signed_date': '2026-01-01',
        }
        resp = self.client.post(
            '/department-duty-log/records/', data=json.dumps(payload),
            content_type='application/json').json()
        self.assertIn('不允许提交的字段', resp.get('error', ''), resp)
        self.assertEqual(
            DepartmentDutyLog.objects.filter(
                duty_record='伪造 signed_date').count(), 0)


# ============================================================
# 签署流程：同日唯一（HTTP 真实路径）
# ============================================================

class SameDaySignFlowTests(SignatureFlowBase):
    """签署/退回流程的同日唯一约束行为"""

    def _return(self, record, returner):
        client = _make_client(returner)
        return client.post(
            '/department-duty-log/records/%s/return/' % record.id,
            data=json.dumps({}), content_type='application/json').json()

    def _make_returner(self):
        returner = _make_user('ddl_sd_returner', tenant_id='tenant_a')
        _grant_perms(returner, [
            ('department_duty_log', 'department_duty_log', ['view', 'return']),
        ])
        return returner

    def test_sign_success_persists_signed_date(self):
        """同日没有 signed 时签署成功，且 signed_date 落库等于 duty_date"""
        record = self._create_draft(duty_record='同日唯一-正常签署')
        resp = self._sign(record, 'sd-sign-1', version=1)
        self.assertFalse(resp.json().get('error'), resp.json())

        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_SIGNED)
        self.assertEqual(record.signed_date, record.duty_date)

    def test_sign_blocked_when_same_day_signed_exists(self):
        """同日已有一条 signed 时，同日另一条草稿签署被拒并保持草稿态"""
        draft_a = self._create_draft(duty_record='同日草稿甲')
        draft_b = self._create_draft(duty_record='同日草稿乙')
        resp = self._sign(draft_a, 'sd-sign-a', version=1)
        self.assertFalse(resp.json().get('error'), resp.json())

        resp = self._sign(draft_b, 'sd-sign-b', version=1)
        self.assertEqual(resp.json().get('error'),
                         services.SIGNED_DATE_CONFLICT_ERROR, resp.json())

        draft_b.refresh_from_db()
        self.assertEqual(draft_b.status, STATUS_DRAFT)
        self.assertIsNone(draft_b.signed_date)
        self.assertIsNone(draft_b.signature_usage_id)
        # 甲保持已签
        draft_a.refresh_from_db()
        self.assertEqual(draft_a.status, STATUS_SIGNED)

    def test_return_releases_date_and_other_draft_can_sign(self):
        """signed 退回 draft 后释放日期，同日其他草稿即可签署"""
        draft_a = self._create_draft(duty_record='待退回草稿')
        draft_b = self._create_draft(duty_record='等待签署草稿')
        self.assertFalse(self._sign(draft_a, 'sd-return-a', version=1).json().get('error'))
        # 退回前乙被同日唯一约束拒绝
        self.assertEqual(
            self._sign(draft_b, 'sd-return-b', version=1).json().get('error'),
            services.SIGNED_DATE_CONFLICT_ERROR)

        # 管理员退回甲 -> 释放日期
        body = self._return(draft_a, self._make_returner())
        self.assertFalse(body.get('error'), body)
        draft_a.refresh_from_db()
        self.assertEqual(draft_a.status, STATUS_DRAFT)
        self.assertIsNone(draft_a.signed_date)

        # 乙此时可签署
        resp = self._sign(draft_b, 'sd-return-b2', version=draft_b.version)
        self.assertFalse(resp.json().get('error'), resp.json())
        draft_b.refresh_from_db()
        self.assertEqual(draft_b.status, STATUS_SIGNED)
        self.assertEqual(draft_b.signed_date, draft_b.duty_date)


# ============================================================
# 数据库兜底：绕过服务层的直接写入
# ============================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SameDayDatabaseBackstopTests(TestCase):
    """数据库唯一索引与 CHECK 约束兜底：直接 ORM 写入也不能绕过"""

    def setUp(self):
        AppSetting.set('bind_ip', False)

    def tearDown(self):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def _setup_signature(self, user):
        """经真实上传接口为用户配置签名，使服务层签署流程可达数据库回写步骤"""
        supper = _make_user('ddl_sd_orm_supper', is_supper=True, tenant_id='default')
        client = _make_client(supper)
        resp = client.post(
            '/account/user/%s/signature/' % user.id,
            {'file': _make_png_file(), 'remark': 'sd backstop setup'})
        body = json.loads(resp.content)
        self.assertFalse(body.get('error'), body)

    def _draft_base(self, user, duty_date=None):
        return {
            'duty_date': duty_date or date.today(),
            'duty_person': user,
            'duty_person_name': user.nickname or user.username,
            'weather': '晴',
            'duty_record': '兜底测试记录',
            'remark': '',
            'status': STATUS_DRAFT,
            'version': 1,
            'created_by': user,
        }

    def _signed_kwargs(self, user, duty_date=None):
        """满足全部 CHECK 约束的 signed 字段（signed_date 与 duty_date 一致）"""
        duty_date = duty_date or date.today()
        return {
            'signature_usage_id': uuid.uuid4().int & ((1 << 63) - 1),
            'signed_by': user,
            'signed_by_name': user.nickname or user.username,
            'signed_at': '2026-01-01 00:00:00',
            'signature_version': 1,
            'signature_sha256': 'a' * 64,
            'business_snapshot_hash': 'b' * 64,
            'signed_date': duty_date,
        }

    def test_direct_orm_second_same_day_signed_rejected(self):
        """绕过服务层直接 ORM 创建第二条同日 signed：数据库必须拒绝"""
        user = _make_user('ddl_sd_orm_a', tenant_id='tenant_a')
        _make_record(user, status=STATUS_SIGNED, duty_date=date.today())
        fields = self._draft_base(user)
        fields.update(self._signed_kwargs(user))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(**fields)
        self.assertEqual(
            DepartmentDutyLog.objects.filter(
                duty_date=date.today(), status=STATUS_SIGNED).count(), 1)

    def test_draft_with_signed_date_rejected(self):
        """漂移防护：draft 携带 signed_date 被 CHECK 约束拒绝"""
        user = _make_user('ddl_sd_orm_b', tenant_id='tenant_a')
        fields = self._draft_base(user)
        fields['signed_date'] = fields['duty_date']
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(**fields)

    def test_signed_without_signed_date_rejected(self):
        """漂移防护：signed 缺失 signed_date 被 CHECK 约束拒绝"""
        user = _make_user('ddl_sd_orm_c', tenant_id='tenant_a')
        fields = self._draft_base(user)
        fields.update(self._signed_kwargs(user))
        fields['status'] = STATUS_SIGNED
        fields['signed_date'] = None
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(**fields)

    def test_signed_with_mismatched_signed_date_rejected(self):
        """漂移防护：signed_date 与 duty_date 不一致被 CHECK 约束拒绝"""
        user = _make_user('ddl_sd_orm_d', tenant_id='tenant_a')
        fields = self._draft_base(user)
        fields.update(self._signed_kwargs(user))
        fields['signed_date'] = fields['duty_date'] - timedelta(days=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(**fields)

    def test_status_flip_via_update_without_signed_date_rejected(self):
        """漂移防护：ORM .update() 只改状态不写 signed_date 被拒绝"""
        user = _make_user('ddl_sd_orm_e', tenant_id='tenant_a')
        record = DepartmentDutyLog.objects.create(**self._draft_base(user))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.filter(pk=record.id).update(
                    status=STATUS_SIGNED,
                    version=2,
                    signature_usage_id=uuid.uuid4().int & ((1 << 63) - 1),
                    signed_by_id=user.id,
                    signed_by_name=user.nickname or user.username,
                    signed_at='2026-01-01 00:00:00',
                    signature_version=1,
                    signature_sha256='a' * 64,
                    business_snapshot_hash='b' * 64,
                )
        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_DRAFT)

    def test_signed_date_set_on_draft_via_update_rejected(self):
        """漂移防护：ORM .update() 给 draft 写 signed_date 被拒绝"""
        user = _make_user('ddl_sd_orm_f', tenant_id='tenant_a')
        record = DepartmentDutyLog.objects.create(**self._draft_base(user))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.filter(pk=record.id).update(
                    signed_date=record.duty_date)
        record.refresh_from_db()
        self.assertIsNone(record.signed_date)

    def test_soft_deleted_signed_occupies_date_and_backstop_converts(self):
        """软删除的 signed 记录仍占用日期（fail-closed），并触发唯一索引兜底转换。

        服务层预检查只看未删除记录（感知不到软删除的历史残留），
        此时签署应当走到 update 并被唯一索引拒绝，
        IntegrityError 必须被转换为与预检查相同的业务错误。
        正常业务路径不会出现软删除的 signed（服务层禁止删除已签记录），
        本用例直接 ORM 构造该状态模拟历史遗留数据。
        """
        user = _make_user('ddl_sd_orm_g', tenant_id='tenant_a')
        _grant_perms(user, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self._setup_signature(user)
        signed = _make_record(user, status=STATUS_SIGNED, duty_date=date.today())
        # 直接 ORM 软删除已签记录（模拟历史遗留/历史脚本）
        DepartmentDutyLog.objects.filter(pk=signed.id).update(
            deleted_at='2026-01-01 00:00:00')

        draft = DepartmentDutyLog.objects.create(**self._draft_base(user))
        record, error = services.sign_draft(
            record_id=draft.id, user=user, client_version=1,
            request_id='sd-backstop-%s' % uuid.uuid4().hex, confirm=True)
        self.assertIsNone(record)
        self.assertEqual(error, services.SIGNED_DATE_CONFLICT_ERROR, error)

        draft.refresh_from_db()
        self.assertEqual(draft.status, STATUS_DRAFT)
        self.assertIsNone(draft.signed_date)
        self.assertIsNone(draft.signature_usage_id)

    def test_soft_deleted_draft_does_not_block_signing(self):
        """软删除语义一致：草稿软删除后不占用日期，同日其他草稿可正常签署"""
        user = _make_user('ddl_sd_orm_h', tenant_id='tenant_a')
        _grant_perms(user, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self._setup_signature(user)
        deleted_draft = DepartmentDutyLog.objects.create(
            **self._draft_base(user, duty_date=date.today() - timedelta(days=1)))
        # 经服务层软删除草稿
        _, error = services.soft_delete_draft(deleted_draft.id, user)
        self.assertIsNone(error, error)
        deleted_draft.refresh_from_db()
        self.assertIsNotNone(deleted_draft.deleted_at)
        self.assertIsNone(deleted_draft.signed_date)

        # 同日（昨日）再建草稿并签署：不受已删草稿影响
        draft = DepartmentDutyLog.objects.create(
            **self._draft_base(user, duty_date=date.today() - timedelta(days=1)))
        record, error = services.sign_draft(
            record_id=draft.id, user=user, client_version=1,
            request_id='sd-softdel-%s' % uuid.uuid4().hex, confirm=True)
        self.assertIsNone(error, error)
        self.assertEqual(record.status, STATUS_SIGNED)


# ============================================================
# 并发：两个草稿同时签署同一天
# ============================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ConcurrentSameDaySignTests(TransactionTestCase):
    """真实线程并发签署同一天：最多一个成功（数据库唯一索引仲裁）。

    使用 TransactionTestCase 允许线程内真实提交；
    两个线程各自持有独立数据库连接，完整执行服务层签署事务。
    无论线程交错顺序如何，终态必须满足：同日恰好一条 signed。
    """

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('ddl_cc_supper', is_supper=True, tenant_id='default')
        self.supper_client = _make_client(self.supper)

        self.signer_a = _make_user('ddl_cc_a', tenant_id='tenant_a')
        _grant_perms(self.signer_a, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.signer_b = _make_user('ddl_cc_b', tenant_id='tenant_a')
        _grant_perms(self.signer_b, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'del', 'sign']),
        ])
        # 为两名签署人配置真实签名（走上传接口）
        for signer in (self.signer_a, self.signer_b):
            resp = self.supper_client.post(
                '/account/user/%s/signature/' % signer.id,
                {'file': _make_png_file(), 'remark': 'cc setup'})
            body = json.loads(resp.content)
            assert not body.get('error'), 'signature setup failed: %s' % body.get('error')

        self.duty_date = date.today()
        self.draft_a = _make_record(
            self.signer_a, duty_date=self.duty_date, duty_record='并发草稿A')
        self.draft_b = _make_record(
            self.signer_b, duty_date=self.duty_date, duty_record='并发草稿B')

    def tearDown(self):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def test_two_drafts_concurrent_sign_same_day_only_one_wins(self):
        from django.db import connections

        barrier = threading.Barrier(2)
        results = {}

        def _runner(record, user, key):
            def run():
                try:
                    barrier.wait(timeout=15)
                except Exception:
                    pass
                try:
                    rec, err = services.sign_draft(
                        record_id=record.id, user=user,
                        client_version=record.version,
                        request_id='cc-%s-%s' % (key, uuid.uuid4().hex),
                        confirm=True)
                    results[key] = (rec is not None, err)
                finally:
                    connections.close_all()

            return run

        t1 = threading.Thread(target=_runner(self.draft_a, self.signer_a, 'a'))
        t2 = threading.Thread(target=_runner(self.draft_b, self.signer_b, 'b'))
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)

        self.assertEqual(set(results.keys()), {'a', 'b'}, results)
        winners = [k for k, v in results.items() if v[0]]
        losers = [k for k, v in results.items() if not v[0]]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        self.assertEqual(results[losers[0]][1],
                         services.SIGNED_DATE_CONFLICT_ERROR, results)

        # 终态：同日恰好一条 signed，落败方保持草稿且未占用日期
        signed_ids = list(DepartmentDutyLog.objects.filter(
            duty_date=self.duty_date, status=STATUS_SIGNED)
            .values_list('id', flat=True))
        winner_id = self.draft_a.id if winners[0] == 'a' else self.draft_b.id
        loser_id = self.draft_b.id if winners[0] == 'a' else self.draft_a.id
        self.assertEqual(signed_ids, [winner_id])
        loser = DepartmentDutyLog.objects.get(pk=loser_id)
        self.assertEqual(loser.status, STATUS_DRAFT)
        self.assertIsNone(loser.signed_date)
        self.assertIsNone(loser.signature_usage_id)
