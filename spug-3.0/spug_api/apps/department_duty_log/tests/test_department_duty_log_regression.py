# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""部门值班日志模块回归测试

固化关键业务不变量，防止后续重构破坏：
- 生命周期旅程：草稿 → 编辑 → 签署 → 退回 → 再编辑 → 再签署，版本号严格 +1
- 退回清空全部签署字段并追加 void 证据事件
- 能力字段真值表（can_edit/can_delete/can_sign/can_return/can_export）
- 列表排序（-duty_date, -id）与摘要截断（100 字边界）
- 已有值班日期：仅已签记录、同日去重、月边界、软删除排除
- 数据库签名一致性检查约束（draft/signed 字段不变量、signed_by == duty_person、version >= 1）
"""
import json
import os
import shutil
import tempfile
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction, IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.setting.utils import AppSetting
from apps.evidence.models import EvidenceEvent
from apps.signature import services as sig_services
from apps.department_duty_log.models import (
    DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED,
)

from apps.department_duty_log.tests.test_comprehensive import (
    _make_user, _make_client, _grant_perms, _make_record, _make_png_file,
)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SignatureFlowBase(TestCase):
    """需要真实签署流程的用例基类：超管 + 签署人（已配置签名）。

    供本文件及容错/安全测试文件复用。
    """

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('ddl_flow_supper', is_supper=True, tenant_id='default')
        self.supper_client = _make_client(self.supper)
        self.signer = _make_user('ddl_flow_signer', tenant_id='tenant_a')
        _grant_perms(self.signer, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.signer_client = _make_client(self.signer)
        resp = self.supper_client.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': _make_png_file(), 'remark': 'ddl flow setup'})
        body = json.loads(resp.content)
        assert not body.get('error'), f'setup assign failed: {body.get("error")}'

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _create_draft(self, duty_record='今日值班正常', duty_date=None):
        resp = self.signer_client.post(
            '/department-duty-log/records/', data=json.dumps({
                'duty_date': str(duty_date or date.today()),
                'duty_record': duty_record,
                'weather': '晴',
            }), content_type='application/json')
        body = resp.json()
        assert not body.get('error'), f'create draft failed: {body.get("error")}'
        return DepartmentDutyLog.objects.get(pk=body['data']['id'])

    def _sign(self, record, request_id, version=None, confirm=True):
        return self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({
                'version': version if version is not None else record.version,
                'confirm': confirm,
                'request_id': request_id,
            }),
            content_type='application/json')


class LifecycleJourneyRegressionTests(SignatureFlowBase):
    """完整生命周期旅程：版本号单调递增 + 退回字段一致性 + 证据链"""

    def _edit(self, record, version, duty_record):
        return self.signer_client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'weather': '多云',
                'duty_record': duty_record,
                'remark': '',
                'version': version,
            }),
            content_type='application/json')

    def test_full_draft_sign_return_resign_journey(self):
        record = self._create_draft(duty_record='旅程第一版')
        self.assertEqual(record.status, STATUS_DRAFT)
        self.assertEqual(record.version, 1)

        # 编辑：v1 -> v2
        resp = self._edit(record, 1, '旅程第二版')
        self.assertFalse(resp.json().get('error'), resp.json())

        # 签署：v2 -> v3
        resp = self._sign(record, 'journey-sign-1', version=2)
        self.assertFalse(resp.json().get('error'), resp.json())
        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_SIGNED)
        self.assertEqual(record.version, 3)
        self.assertEqual(record.signed_by_id, record.duty_person_id)
        usage_1 = record.signature_usage_id
        self.assertIsNotNone(usage_1)
        self.assertIsNotNone(record.signed_at)
        self.assertIsNotNone(record.signature_version)
        self.assertTrue(record.signature_sha256)
        self.assertTrue(record.business_snapshot_hash)

        # 已签记录不可编辑/删除
        resp = self._edit(record, 3, '越权修改')
        self.assertIn('已签署记录不可编辑', resp.json().get('error', ''))
        resp = self.signer_client.delete(f'/department-duty-log/records/{record.id}/')
        self.assertIn('已签署记录不可删除', resp.json().get('error', ''))

        # 管理员退回：v3 -> v4，签署字段全部清空
        returner = _make_user('ddl_flow_returner', tenant_id='tenant_a')
        _grant_perms(returner, [
            ('department_duty_log', 'department_duty_log', ['view', 'return']),
        ])
        resp = _make_client(returner).post(
            f'/department-duty-log/records/{record.id}/return/',
            data=json.dumps({}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_DRAFT)
        self.assertEqual(record.version, 4)
        self.assertIsNone(record.signature_usage_id)
        self.assertIsNone(record.signed_by_id)
        self.assertIsNone(record.signed_at)
        self.assertIsNone(record.signature_version)
        self.assertEqual(record.signed_by_name, '')
        self.assertEqual(record.signature_sha256, '')
        self.assertEqual(record.business_snapshot_hash, '')

        # 证据链：签署 1 条 + 退回 void 1 条
        events = EvidenceEvent.objects.filter(
            module='department_duty_log', object_type='department_duty_log',
            object_id=str(record.id)).order_by('id')
        self.assertEqual(events.count(), 2)
        self.assertEqual(events.last().event_type, 'void')

        # 再编辑 v4 -> v5，再签署 v5 -> v6（新 Usage）
        resp = self._edit(record, 4, '旅程第三版')
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = self._sign(record, 'journey-sign-2', version=5)
        self.assertFalse(resp.json().get('error'), resp.json())
        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_SIGNED)
        self.assertEqual(record.version, 6)
        self.assertIsNotNone(record.signature_usage_id)
        self.assertNotEqual(record.signature_usage_id, usage_1)


class VisibilityCapabilityRegressionTests(TestCase):
    """能力字段真值表：所有权 × 状态 × 权限编码"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('ddl_cap_owner', tenant_id='tenant_a')
        self.other = _make_user('ddl_cap_other', tenant_id='tenant_b')

    def _detail(self, user, record):
        client = _make_client(user)
        return client.get(f'/department-duty-log/records/{record.id}/').json()

    def _grant(self, user, *keys):
        _grant_perms(user, [('department_duty_log', 'department_duty_log', list(keys))])

    def test_owner_draft_full_capabilities(self):
        self._grant(self.owner, 'view', 'add', 'edit', 'del', 'sign')
        record = _make_record(self.owner)
        data = self._detail(self.owner, record)['data']
        self.assertTrue(data['can_edit'])
        self.assertTrue(data['can_delete'])
        self.assertTrue(data['can_sign'])
        self.assertFalse(data['can_return'])
        self.assertFalse(data['can_export'])

    def test_owner_draft_without_write_perms(self):
        """仅有 view/add 的用户对本人草稿无编辑/删除/签署能力"""
        self._grant(self.owner, 'view', 'add')
        record = _make_record(self.owner)
        data = self._detail(self.owner, record)['data']
        self.assertFalse(data['can_edit'])
        self.assertFalse(data['can_delete'])
        self.assertFalse(data['can_sign'])

    def test_owner_signed_export_capability(self):
        self._grant(self.owner, 'view', 'add', 'edit', 'del', 'sign', 'export')
        record = _make_record(self.owner, status=STATUS_SIGNED)
        data = self._detail(self.owner, record)['data']
        self.assertFalse(data['can_edit'])
        self.assertFalse(data['can_delete'])
        self.assertFalse(data['can_sign'])
        self.assertFalse(data['can_return'])
        self.assertTrue(data['can_export'])

    def test_owner_signed_with_return_perm(self):
        self._grant(self.owner, 'view', 'return')
        record = _make_record(self.owner, status=STATUS_SIGNED)
        data = self._detail(self.owner, record)['data']
        self.assertTrue(data['can_return'])
        self.assertFalse(data['can_export'])

    def test_other_user_signed_record_read_only_plus_admin(self):
        """已签记录全局可见；return/export 是附加能力而非所有权能力"""
        self._grant(self.other, 'view', 'edit', 'del', 'sign', 'return', 'export')
        record = _make_record(self.owner, status=STATUS_SIGNED)
        data = self._detail(self.other, record)['data']
        self.assertFalse(data['can_edit'])
        self.assertFalse(data['can_delete'])
        self.assertFalse(data['can_sign'])
        self.assertTrue(data['can_return'])
        self.assertTrue(data['can_export'])

    def test_other_user_cannot_see_draft(self):
        self._grant(self.other, 'view')
        record = _make_record(self.owner)
        body = self._detail(self.other, record)
        self.assertTrue(body.get('error'))


class ListOrderAndSummaryRegressionTests(TestCase):
    """列表排序与摘要截断回归"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_reg_list', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view']),
        ])
        self.client = _make_client(self.user)

    def _list(self, query=''):
        return self.client.get(f'/department-duty-log/records/{query}').json()

    def test_ordered_by_date_desc_then_id_desc(self):
        older = _make_record(
            self.user, duty_date=date.today() - timedelta(days=1), duty_record='旧记录')
        newer = _make_record(self.user, duty_record='新记录')
        ids = [r['id'] for r in self._list()['data']['records']]
        self.assertEqual(ids, [newer.id, older.id])

    def test_same_date_ordered_by_id_desc(self):
        first = _make_record(self.user, duty_record='同日第一条')
        second = _make_record(self.user, duty_record='同日第二条')
        ids = [r['id'] for r in self._list()['data']['records']]
        self.assertEqual(ids, [second.id, first.id])

    def test_summary_truncation_boundary(self):
        """超过 100 字截断加省略号；恰好 100 字不截断"""
        _make_record(self.user, duty_record='值' * 150)
        items = self._list()['data']['records']
        self.assertEqual(items[0]['duty_record_summary'], '值' * 100 + '...')
        _make_record(self.user, duty_record='值' * 100)
        items = self._list()['data']['records']
        self.assertEqual(items[0]['duty_record_summary'], '值' * 100)

    def test_list_item_has_summary_not_full_text(self):
        """列表项返回 duty_record_summary，详情才含全文"""
        record = _make_record(self.user, duty_record='全文内容' * 50)
        item = self._list()['data']['records'][0]
        self.assertNotIn('duty_record', item)
        self.assertIn('duty_record_summary', item)
        detail = self.client.get(
            f'/department-duty-log/records/{record.id}/').json()['data']
        self.assertEqual(detail['duty_record'], '全文内容' * 50)


class DutyDatesRegressionTests(TestCase):
    """已有值班日期回归：仅已签、去重、月边界、软删除排除"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_reg_dates', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view']),
        ])
        self.client = _make_client(self.user)

    def _dates(self, year, month):
        return self.client.get(
            f'/department-duty-log/records/duty_dates/?year={year}&month={month}'
        ).json()['data']['dates']

    def test_only_signed_dates_listed(self):
        """草稿不计入日期底纹，已签才计入"""
        _make_record(self.user, status=STATUS_SIGNED, duty_date=date(2026, 7, 15))
        _make_record(self.user, duty_date=date(2026, 7, 16))
        self.assertEqual(self._dates(2026, 7), ['2026-07-15'])

    def test_same_date_deduplicated(self):
        _make_record(self.user, status=STATUS_SIGNED, duty_date=date(2026, 7, 15))
        _make_record(self.user, status=STATUS_SIGNED, duty_date=date(2026, 7, 15))
        self.assertEqual(self._dates(2026, 7), ['2026-07-15'])

    def test_month_boundary(self):
        """月末最后一天只属于所在月份"""
        _make_record(self.user, status=STATUS_SIGNED, duty_date=date(2026, 7, 31))
        self.assertEqual(self._dates(2026, 7), ['2026-07-31'])
        self.assertEqual(self._dates(2026, 6), [])
        self.assertEqual(self._dates(2026, 8), [])

    def test_deleted_signed_record_excluded(self):
        record = _make_record(self.user, status=STATUS_SIGNED, duty_date=date(2026, 7, 15))
        DepartmentDutyLog.objects.filter(pk=record.id).update(deleted_at=timezone.now())
        self.assertEqual(self._dates(2026, 7), [])


class SignatureConstraintRegressionTests(TestCase):
    """数据库签名一致性检查约束回归（绕过服务层的直接写入必须被约束拦截）"""

    def _base_fields(self, user):
        return {
            'duty_date': date.today(),
            'duty_person': user,
            'duty_person_name': user.nickname or user.username,
            'weather': '晴',
            'duty_record': '约束测试记录',
            'created_by': user,
        }

    def _signed_fields(self, user):
        return {
            'signature_usage_id': 424242,
            'signed_by': user,
            'signed_by_name': user.nickname or user.username,
            'signed_at': timezone.now(),
            'signature_version': 1,
            'signature_sha256': 'a' * 64,
            'business_snapshot_hash': 'b' * 64,
        }

    def test_signed_without_signature_fields_rejected(self):
        user = _make_user('ddl_con_user', tenant_id='tenant_a')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(
                    status=STATUS_SIGNED, **self._base_fields(user))

    def test_draft_with_signature_fields_rejected(self):
        user = _make_user('ddl_con_user2', tenant_id='tenant_a')
        fields = self._base_fields(user)
        fields.update(self._signed_fields(user))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(status=STATUS_DRAFT, **fields)

    def test_signed_by_mismatch_rejected(self):
        owner = _make_user('ddl_con_owner', tenant_id='tenant_a')
        other = _make_user('ddl_con_other', tenant_id='tenant_a')
        fields = self._base_fields(owner)
        signed = self._signed_fields(other)
        signed['signed_by_name'] = other.nickname or other.username
        fields.update(signed)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(status=STATUS_SIGNED, **fields)

    def test_version_below_one_rejected(self):
        user = _make_user('ddl_con_user3', tenant_id='tenant_a')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(version=0, **self._base_fields(user))
