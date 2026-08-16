# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
无线电台执照编辑保存回归测试。

回归背景：编辑已有执照时，_save_license_version_snapshot 构建的快照
包含原始 datetime 字段（last_remind_at / created_at / updated_at），
json.dumps 无法序列化抛 TypeError，被中间件转为"服务器内部错误"，
导致前端编辑窗口保存必然失败。本测试走真实 HTTP 路径并校验数据库状态。
"""
import json
from datetime import date, timedelta

from django.test import TestCase

from apps.account.models import User
from apps.radio_license.models import (
    RadioLicense, RadioLicenseFrequency, RadioLicenseVersion,
)
from apps.radio_license.tests.test_smoke import _make_user, _grant_perms, _make_client


def _license_perms(*keys):
    """构造执照相关权限列表，keys 缺省给 view。"""
    keys = list(keys) or ['view']
    return [('radio_license', 'license', keys)]


class LicenseEditSaveTests(TestCase):
    """执照编辑保存：字段更新、版本快照、频率重建、连续编辑。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('lic_edit_user', tenant_id='t_le')
        _grant_perms(self.user, _license_perms('view', 'add', 'edit', 'del'))
        self.client = _make_client(self.user)
        self.today = date.today()

    def _create_license(self, station_name='编辑回归台站'):
        today = self.today
        payload = {
            'station_name': station_name,
            'valid_from': str(today - timedelta(days=30)),
            'valid_to': str(today + timedelta(days=300)),
            'purpose': '编辑回归用途',
            'responsible_user_id': self.user.id,
            'remark': '',
            'frequencies': [
                {'frequency_value': 100.5, 'frequency_unit': 'MHz',
                 'frequency_text': '', 'sort_order': 0},
            ],
        }
        resp = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return RadioLicense.objects.get(station_name=station_name)

    def _edit_payload(self, license_obj, **overrides):
        today = self.today
        payload = {
            'id': license_obj.id,
            'station_name': license_obj.station_name,
            'valid_from': str(license_obj.valid_from),
            'valid_to': str(today + timedelta(days=400)),
            'purpose': license_obj.purpose,
            'responsible_user_id': self.user.id,
            'frequencies': [
                {'frequency_value': 88.0, 'frequency_unit': 'MHz',
                 'frequency_text': 'fm', 'sort_order': 0},
                {'frequency_value': 120.0, 'frequency_unit': 'MHz',
                 'frequency_text': '', 'sort_order': 1},
            ],
        }
        payload.update(overrides)
        return payload

    def test_edit_save_updates_record_and_writes_version_snapshot(self):
        """编辑保存：业务字段更新 + 版本快照落库且 JSON 可解析。"""
        license_obj = self._create_license()

        resp = self.client.post(
            '/radio-license/',
            data=json.dumps(self._edit_payload(
                license_obj, station_name='编辑回归台站-改')),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        license_obj.refresh_from_db()
        self.assertEqual(license_obj.station_name, '编辑回归台站-改')
        self.assertEqual(
            str(license_obj.valid_to), str(self.today + timedelta(days=400)))
        self.assertEqual(license_obj.updated_by_id, self.user.id)

        # 版本快照：1 条，记录的是修改前内容，datetime 字段必须可序列化
        versions = RadioLicenseVersion.objects.filter(license=license_obj)
        self.assertEqual(versions.count(), 1)
        v = versions.get()
        self.assertEqual(v.version_no, 1)
        snapshot = json.loads(v.snapshot_json)
        self.assertEqual(snapshot['station_name'], '编辑回归台站')
        self.assertIsInstance(snapshot['created_at'], str)
        self.assertEqual(v.changed_by_id, self.user.id)
        self.assertTrue(v.snapshot_hash)

        # 频率明细先删后建
        freqs = RadioLicenseFrequency.objects.filter(license=license_obj)
        self.assertEqual(freqs.count(), 2)
        self.assertEqual(
            freqs.order_by('sort_order')[0].frequency_text, 'fm')

        # 编辑审计日志落库（动作值必须在 audit_action_valid 约束内）
        from apps.logs.models import AuditLog
        audit = AuditLog.objects.filter(
            target_type='radio_license', target_id=str(license_obj.id),
            action='update',
        )
        self.assertEqual(audit.count(), 1)

    def test_second_edit_increments_version_no(self):
        """连续编辑：版本号按执照递增，不覆盖旧快照。"""
        license_obj = self._create_license()
        for i in range(2):
            resp = self.client.post(
                '/radio-license/',
                data=json.dumps(self._edit_payload(
                    license_obj, station_name=f'编辑回归台站-{i}')),
                content_type='application/json',
            )
            body = resp.json()
            self.assertFalse(body.get('error'), body)

        versions = RadioLicenseVersion.objects.filter(
            license=license_obj).order_by('version_no')
        self.assertEqual(
            [v.version_no for v in versions], [1, 2])

    def test_edit_without_change_returns_success(self):
        """无字段变更的编辑同样保存成功（changed_fields 为空路径）。"""
        license_obj = self._create_license()
        today = self.today
        payload = {
            'id': license_obj.id,
            'station_name': license_obj.station_name,
            'valid_from': str(license_obj.valid_from),
            'valid_to': str(license_obj.valid_to),
            'purpose': license_obj.purpose,
            'responsible_user_id': self.user.id,
        }
        resp = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        # 快照仍写入，业务字段不变
        self.assertEqual(
            RadioLicenseVersion.objects.filter(license=license_obj).count(), 1)
        license_obj.refresh_from_db()
        self.assertEqual(license_obj.station_name, '编辑回归台站')

    def test_evidence_package_export_with_datetime_fields(self):
        """证据包导出：含 datetime 字段的快照/哈希应正常序列化为 zip。"""
        import io
        import zipfile as zf_mod
        license_obj = self._create_license()
        resp = self.client.get(
            f'/radio-license/evidence/package/?id={license_obj.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/zip')
        # FileResponse 是流式响应，需拼接 streaming_content
        content = b''.join(resp.streaming_content)
        with zf_mod.ZipFile(io.BytesIO(content)) as package:
            names = package.namelist()
            self.assertIn('object_snapshot.json', names)
            self.assertIn('hashes.json', names)
            snapshot = json.loads(package.read('object_snapshot.json'))
            # datetime 字段必须已被序列化为字符串
            self.assertIsInstance(snapshot['license']['created_at'], str)
            hashes = json.loads(package.read('hashes.json'))
            self.assertIsInstance(hashes['generated_at'], str)


class LicenseResponsibleUserValidationTests(TestCase):
    """执照责任人校验：跨租户拦截、软删拦截、姓名服务端回填、超管放行。

    覆盖与批复侧 _validate_and_fill_approval_responsible_user 对齐后的规则。
    """

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('lic_resp_user', tenant_id='t_lr')
        _grant_perms(self.user, _license_perms('view', 'add', 'edit'))
        self.client = _make_client(self.user)
        self.today = date.today()

    def _payload(self, **overrides):
        payload = {
            'station_name': '责任人校验台站',
            'valid_from': str(self.today - timedelta(days=30)),
            'valid_to': str(self.today + timedelta(days=300)),
            'purpose': '责任人校验用途',
            'responsible_user_id': self.user.id,
        }
        payload.update(overrides)
        return payload

    def _post(self, payload):
        return self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json',
        ).json()

    def test_create_responsible_user_cross_tenant_rejected(self):
        """普通用户指定他租户用户为责任人：拒绝且不落库。"""
        other = _make_user('lic_resp_other', tenant_id='t_other')
        body = self._post(self._payload(responsible_user_id=other.id))
        self.assertEqual(body.get('error'), '责任人不存在或已禁用，请重新选择')
        self.assertFalse(
            RadioLicense.objects.filter(station_name='责任人校验台站').exists())

    def test_create_responsible_user_soft_deleted_rejected(self):
        """软删用户不得被指定为责任人。"""
        deleted_user = _make_user('lic_resp_deleted', tenant_id='t_lr')
        User.objects.filter(pk=deleted_user.id).update(deleted_by=self.user)
        body = self._post(self._payload(responsible_user_id=deleted_user.id))
        self.assertEqual(body.get('error'), '责任人不存在或已禁用，请重新选择')
        self.assertFalse(
            RadioLicense.objects.filter(station_name='责任人校验台站').exists())

    def test_responsible_user_name_filled_by_server_not_trusted(self):
        """客户端伪造 responsible_user_name：服务端回填真实姓名。"""
        body = self._post(self._payload(responsible_user_name='伪造的姓名'))
        self.assertFalse(body.get('error'), body)
        license_obj = RadioLicense.objects.get(station_name='责任人校验台站')
        self.assertEqual(license_obj.responsible_user_id, self.user.id)
        self.assertEqual(license_obj.responsible_user_name, 'lic_resp_user')

    def test_supper_can_assign_cross_tenant_responsible_user(self):
        """超管可跨租户指定责任人，姓名仍由服务端回填。"""
        supper = _make_user('lic_resp_supper', is_supper=True, tenant_id='t_supper')
        _grant_perms(supper, _license_perms('view', 'add'))
        client = _make_client(supper)
        body = client.post(
            '/radio-license/', data=json.dumps(self._payload()),
            content_type='application/json',
        ).json()
        self.assertFalse(body.get('error'), body)
        license_obj = RadioLicense.objects.get(station_name='责任人校验台站')
        self.assertEqual(license_obj.responsible_user_id, self.user.id)
        self.assertEqual(license_obj.responsible_user_name, 'lic_resp_user')
        # 超管创建的执照归属超管所在租户
        self.assertEqual(license_obj.tenant_id, 't_supper')

    def test_edit_responsible_user_cross_tenant_rejected(self):
        """编辑时更换为他租户责任人同样被拦截，原记录不受影响。"""
        license_obj = self._create_for_edit()
        other = _make_user('lic_resp_other2', tenant_id='t_other')
        body = self._post(self._payload(
            id=license_obj.id, responsible_user_id=other.id,
            station_name=license_obj.station_name))
        self.assertEqual(body.get('error'), '责任人不存在或已禁用，请重新选择')
        license_obj.refresh_from_db()
        self.assertEqual(license_obj.responsible_user_id, self.user.id)

    def _create_for_edit(self):
        body = self._post(self._payload(station_name='责任人编辑台站'))
        self.assertFalse(body.get('error'), body)
        return RadioLicense.objects.get(station_name='责任人编辑台站')
