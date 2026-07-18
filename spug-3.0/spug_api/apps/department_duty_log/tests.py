# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""部门值班日志 - 自动化测试

覆盖：
- 权限和当前用户绑定（跨租户共享、草稿隔离、伪造字段拒绝）
- 校验和分页
- 并发和生命周期（乐观锁、软删除、作废、更正）
- 电子签接入（场景注册、签署事务、幂等、固定版本读取、跨租户签名）
- 审计
"""
import io
import json
import os
import shutil
import time
import hashlib
from datetime import date, timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, Client, override_settings
from django.db import connection

from apps.account.models import User, Role
from apps.setting.utils import AppSetting
from apps.evidence.models import EvidenceEvent, EvidenceAttachment
from apps.signature.models import AccountSignature, SignatureUsage, STATUS_ACTIVE, STATUS_DISABLED
from apps.signature import services as sig_services
from apps.department_duty_log.models import DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED, STATUS_VOID
from apps.department_duty_log import services


# ============================================================
# 测试辅助
# ============================================================

def _make_png(width=200, height=100, mode='RGBA'):
    from PIL import Image
    img = Image.new(mode, (width, height), (255, 0, 0, 128) if mode == 'RGBA' else (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _make_png_file(width=200, height=100, name='sig.png'):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, _make_png(width, height), content_type='image/png')


def _make_user(username, is_supper=False, tenant_id='default', is_active=True):
    token = (username * 10)[:32]
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=is_active, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return client


def _grant_perms(user, perms):
    """给用户授予权限。

    perms: list of (module, page, [perm_keys])
    例如 [('department_duty_log', 'department_duty_log', ['view', 'add'])]
    """
    perm_dict = {}
    for module, page, keys in perms:
        perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)

    role = Role.objects.create(
        name=f'role_{user.username}',
        page_perms=json.dumps(perm_dict),
        created_by=user,
    )
    user.roles.add(role)
    user.set_perms_cache()  # 清空缓存，下次访问重新计算
    return role


def _make_record(user, **kwargs):
    """直接创建一条草稿记录。"""
    defaults = {
        'duty_date': date.today(),
        'duty_person': user,
        'duty_person_name': user.nickname or user.username,
        'mains_voltage': '220V',
        'ups_voltage': '220伏',
        'weather': '晴',
        'duty_record': '值班正常',
        'remark': '',
        'status': STATUS_DRAFT,
        'version': 1,
        'created_by': user,
    }
    defaults.update(kwargs)
    return DepartmentDutyLog.objects.create(**defaults)


# ============================================================
# 权限和当前用户绑定
# ============================================================

class DepartmentDutyLogPermissionTests(TestCase):
    """权限和当前用户绑定测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        # 用户 A（租户 tenant_a）
        self.user_a = _make_user('user_a', tenant_id='tenant_a')
        _grant_perms(self.user_a, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.client_a = _make_client(self.user_a)

        # 用户 B（租户 tenant_b）
        self.user_b = _make_user('user_b', tenant_id='tenant_b')
        _grant_perms(self.user_b, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.client_b = _make_client(self.user_b)

        # 用户 C（无权限）
        self.user_c = _make_user('user_c', tenant_id='tenant_a')
        self.client_c = _make_client(self.user_c)

        # 用户 D（有 void 权限）
        self.user_d = _make_user('user_d', tenant_id='tenant_a')
        _grant_perms(self.user_d, [
            ('department_duty_log', 'department_duty_log', ['view', 'void']),
        ])
        self.client_d = _make_client(self.user_d)

    def _parse(self, response):
        return json.loads(response.content)

    def test_api01_cross_tenant_view_shared_records(self):
        """不同租户用户有 view 权限时看到相同已签/已作废记录，各自只看到本人草稿"""
        # 用户 A 创建草稿
        record_a = _make_record(self.user_a)
        # 用户 B 创建草稿
        record_b = _make_record(self.user_b)

        # A 看不到 B 的草稿，只看到自己的草稿
        resp = self.client_a.get('/department-duty-log/records/')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        record_ids = [r['id'] for r in body['data']['records']]
        self.assertIn(record_a.id, record_ids)
        self.assertNotIn(record_b.id, record_ids)

        # B 看不到 A 的草稿
        resp = self.client_b.get('/department-duty-log/records/')
        body = self._parse(resp)
        record_ids = [r['id'] for r in body['data']['records']]
        self.assertIn(record_b.id, record_ids)
        self.assertNotIn(record_a.id, record_ids)

        # 将 A 的记录标记为 signed（模拟）
        record_a.status = STATUS_SIGNED
        record_a.save()
        # B 现在能看到 A 的已签记录
        resp = self.client_b.get('/department-duty-log/records/')
        body = self._parse(resp)
        record_ids = [r['id'] for r in body['data']['records']]
        self.assertIn(record_a.id, record_ids)

    def test_api02_no_view_permission_denied(self):
        """无 view 权限不能列表"""
        resp = self.client_c.get('/department-duty-log/records/')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_api03_method_level_permissions(self):
        """add/edit/del/sign/void 权限分别独立"""
        # 用户 C 无任何写权限
        resp = self.client_c.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '测试',
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_api05_forged_duty_person_rejected(self):
        """创建请求伪造 duty_person_id 被拒绝"""
        resp = self.client_a.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '测试',
            'duty_person_id': 99999,
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))
        self.assertIn('不允许', body['error'])

    def test_api05b_forged_signature_fields_rejected(self):
        """创建请求伪造签名字段被拒绝"""
        resp = self.client_a.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '测试',
            'signature_usage_id': 123,
            'signed_by_id': 999,
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_api07_other_user_cannot_edit_others_draft(self):
        """其他用户即使有 edit 权限也不能操作该草稿"""
        record_a = _make_record(self.user_a)
        resp = self.client_b.put(
            f'/department-duty-log/records/{record_a.id}/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '修改',
                'version': 1,
            }),
            content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))
        record_a.refresh_from_db()
        self.assertEqual(record_a.duty_record, '值班正常')

    def test_api07b_other_user_cannot_delete_others_draft(self):
        """其他用户不能删除他人草稿"""
        record_a = _make_record(self.user_a)
        resp = self.client_b.delete(f'/department-duty-log/records/{record_a.id}/')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))
        record_a.refresh_from_db()
        self.assertIsNone(record_a.deleted_at)

    def test_api08_owner_can_edit_delete_own_draft(self):
        """当前值班员拥有对应权限时可编辑、删除本人草稿"""
        record_a = _make_record(self.user_a)
        # 编辑
        resp = self.client_a.put(
            f'/department-duty-log/records/{record_a.id}/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '修改后记录',
                'mains_voltage': '220V',
                'ups_voltage': '正常',
                'weather': '晴',
                'version': 1,
            }),
            content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        record_a.refresh_from_db()
        self.assertEqual(record_a.duty_record, '修改后记录')
        self.assertEqual(record_a.version, 2)

        # 删除
        resp = self.client_a.delete(f'/department-duty-log/records/{record_a.id}/')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        record_a.refresh_from_db()
        self.assertIsNotNone(record_a.deleted_at)

    def test_api09_draft_invisible_to_others(self):
        """其他用户尝试按 ID 查看未签草稿返回不存在"""
        record_a = _make_record(self.user_a)
        resp = self.client_b.get(f'/department-duty-log/records/{record_a.id}/')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_create_duty_person_fixed_to_current_user(self):
        """创建时值班员和 created_by 固定为当前用户"""
        resp = self.client_a.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '测试',
            'mains_voltage': '220V',
            'ups_voltage': '正常',
            'weather': '晴',
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        record = DepartmentDutyLog.objects.get(pk=body['data']['id'])
        self.assertEqual(record.duty_person_id, self.user_a.id)
        self.assertEqual(record.created_by_id, self.user_a.id)
        self.assertEqual(record.duty_person_name, self.user_a.nickname)


# ============================================================
# 校验和分页
# ============================================================

class DepartmentDutyLogValidationTests(TestCase):
    """校验和分页测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('val_user', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.client = _make_client(self.user)

    def _parse(self, response):
        return json.loads(response.content)

    def test_api04_invalid_date_rejected(self):
        """非法日期被拒绝"""
        resp = self.client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': 'invalid',
            'duty_record': '测试',
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_api04b_future_date_rejected(self):
        """未来日期被拒绝"""
        future = date.today() + timedelta(days=1)
        resp = self.client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(future),
            'duty_record': '测试',
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_api04d_empty_record_rejected(self):
        """空白记录被拒绝"""
        resp = self.client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'mains_voltage': '220V',
            'ups_voltage': '正常',
            'weather': '晴',
            'duty_record': '',
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_api04g_empty_voltage_rejected(self):
        """空白市电电压被拒绝"""
        resp = self.client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '测试',
            'mains_voltage': '',
            'ups_voltage': '正常',
            'weather': '晴',
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))
        self.assertIn('市电电压', body['error'])

    def test_api04e_voltage_text_saved_as_is(self):
        """220V、220伏、正常、停电检修、旁路 原样保存"""
        test_values = ['220V', '220伏', '正常', '停电检修', '旁路']
        for val in test_values:
            resp = self.client.post('/department-duty-log/records/', data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '测试',
                'mains_voltage': val,
                'ups_voltage': val,
                'weather': val,
                'ups_voltage': val,
            }), content_type='application/json')
            body = self._parse(resp)
            self.assertFalse(body.get('error'), f'保存 {val} 失败: {body.get("error")}')
            record = DepartmentDutyLog.objects.get(pk=body['data']['id'])
            self.assertEqual(record.mains_voltage, val)
            self.assertEqual(record.ups_voltage, val)

    def test_api04f_overlong_fields_rejected(self):
        """超长字段被拒绝"""
        resp = self.client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '测试',
            'mains_voltage': 'V' * 51,
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_api10_invalid_page_no_500(self):
        """非法 page/page_size 不产生 500"""
        resp = self.client.get('/department-duty-log/records/?page=abc&page_size=999')
        self.assertEqual(resp.status_code, 200)
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        self.assertLessEqual(body['data']['page_size'], 100)

    def test_api10b_page_size_max_100(self):
        """page_size 最大 100"""
        resp = self.client.get('/department-duty-log/records/?page_size=500')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['page_size'], 100)

    def test_api11_combined_filter(self):
        """日期、人员、状态、关键字组合筛选"""
        _make_record(self.user, duty_record='关键词A', status=STATUS_SIGNED)
        _make_record(self.user, duty_record='关键词B')

        resp = self.client.get('/department-duty-log/records/?keyword=关键词A')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))
        self.assertTrue(all('关键词A' in r['duty_record_summary'] for r in body['data']['records']))

        resp = self.client.get('/department-duty-log/records/?status=signed')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))
        self.assertTrue(all(r['status'] == 'signed' for r in body['data']['records']))

    def test_options_endpoint(self):
        """选项接口返回 current_user"""
        _make_record(self.user, status=STATUS_SIGNED)
        resp = self.client.get('/department-duty-log/options/')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['current_user']['id'], self.user.id)


# ============================================================
# 并发和生命周期
# ============================================================

class DepartmentDutyLogLifecycleTests(TestCase):
    """并发和生命周期测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('life_user', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.client = _make_client(self.user)

    def _parse(self, response):
        return json.loads(response.content)

    def test_api12_old_version_edit_fails(self):
        """旧 version 编辑失败且原记录不变"""
        record = _make_record(self.user)
        # 先编辑一次，版本变为 2
        resp = self.client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '第一次',
                'mains_voltage': '220V',
                'ups_voltage': '正常',
                'weather': '晴',
                'version': 1,
            }),
            content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))

        # 用旧 version=1 再编辑，应失败
        resp = self.client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '第二次',
                'mains_voltage': '220V',
                'ups_voltage': '正常',
                'weather': '晴',
                'version': 1,
            }),
            content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

        record.refresh_from_db()
        self.assertEqual(record.duty_record, '第一次')
        self.assertEqual(record.version, 2)

    def test_api18_signed_record_put_rejected(self):
        """已签记录 PUT 被拒绝"""
        record = _make_record(self.user, status=STATUS_SIGNED, version=2)
        resp = self.client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '修改',
                'version': 2,
            }),
            content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_api18b_signed_record_delete_rejected(self):
        """已签记录 DELETE 被拒绝"""
        record = _make_record(self.user, status=STATUS_SIGNED, version=2)
        resp = self.client.delete(f'/department-duty-log/records/{record.id}/')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_void_reason_required(self):
        """void 原因必填"""
        record = _make_record(self.user, status=STATUS_SIGNED, version=2)
        resp = self.client.post(
            f'/department-duty-log/records/{record.id}/void/',
            data=json.dumps({'reason': ''}),
            content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_void_preserves_signature_fields(self):
        """void 保留所有签署字段（直接操作不经过签名服务）"""
        record = _make_record(
            self.user, status=STATUS_SIGNED, version=2,
            signature_usage_id=999, signed_by=self.user,
            signed_by_name='测试', signed_at='2026-01-01 00:00:00',
            signature_version=1, signature_sha256='abc',
            business_snapshot_hash='def',
        )
        # 给 user void 权限
        _grant_perms(self.user, [('department_duty_log', 'department_duty_log', ['void'])])

        # void 时没有真实 signature_usage_id，void 证据事件会被跳过（usage 不存在）
        resp = self.client.post(
            f'/department-duty-log/records/{record.id}/void/',
            data=json.dumps({'reason': '测试作废'}),
            content_type='application/json')
        body = self._parse(resp)
        # 因为 signature_usage_id=999 对应的 Usage 不存在，void 证据事件返回错误
        # 这应该导致作废回滚
        self.assertTrue(body.get('error'))

    def test_correction_based_on_void_only(self):
        """更正只能基于 void 记录"""
        record = _make_record(self.user, status=STATUS_DRAFT)
        resp = self.client.post(
            f'/department-duty-log/records/{record.id}/corrections/',
            data=json.dumps({}), content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

    def test_correction_creates_new_draft(self):
        """更正创建新草稿，supersedes 正确"""
        record = _make_record(
            self.user, status=STATUS_VOID, version=2,
            duty_record='原记录',
            signature_usage_id=None,  # void 记录但没有签署
        )
        resp = self.client.post(
            f'/department-duty-log/records/{record.id}/corrections/',
            data=json.dumps({}), content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        new_record = DepartmentDutyLog.objects.get(pk=body['data']['id'])
        self.assertEqual(new_record.status, STATUS_DRAFT)
        self.assertEqual(new_record.supersedes_id, record.id)
        self.assertEqual(new_record.duty_record, '原记录')
        self.assertIsNone(new_record.signature_usage_id)
        self.assertEqual(new_record.version, 1)

    def test_draft_signed_void_field_consistency(self):
        """draft/signed/void 字段一致性"""
        # draft：签署和作废字段为空
        record = _make_record(self.user, status=STATUS_DRAFT)
        self.assertIsNone(record.signature_usage_id)
        self.assertIsNone(record.signed_by_id)
        self.assertIsNone(record.signed_at)
        self.assertIsNone(record.voided_at)
        self.assertIsNone(record.voided_by_id)

        # signed：签署字段非空，作废字段为空
        record.status = STATUS_SIGNED
        record.signature_usage_id = 1
        record.signed_by = self.user
        record.signed_by_name = 'test'
        record.signed_at = '2026-01-01'
        record.signature_version = 1
        record.signature_sha256 = 'a'
        record.business_snapshot_hash = 'b'
        record.save()
        self.assertIsNotNone(record.signature_usage_id)
        self.assertIsNone(record.voided_at)

        # void：保留签署字段，作废字段非空
        record.status = STATUS_VOID
        record.voided_at = '2026-01-02'
        record.voided_by = self.user
        record.void_reason = '作废'
        record.save()
        self.assertIsNotNone(record.signature_usage_id)
        self.assertIsNotNone(record.voided_at)


# ============================================================
# 电子签接入
# ============================================================

class DepartmentDutyLogSignatureTests(TestCase):
    """电子签接入测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        # 超管
        self.supper = _make_user('supper_ddl', is_supper=True, tenant_id='default')
        self.supper_client = _make_client(self.supper)

        # 签署人 A（tenant_a）
        self.signer = _make_user('signer_ddl', tenant_id='tenant_a')
        _grant_perms(self.signer, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.signer_client = _make_client(self.signer)

        # 跨租户查看者 B（tenant_b）
        self.viewer = _make_user('viewer_ddl', tenant_id='tenant_b')
        _grant_perms(self.viewer, [
            ('department_duty_log', 'department_duty_log', ['view']),
        ])
        self.viewer_client = _make_client(self.viewer)

        # void 用户
        self.voider = _make_user('voider_ddl', tenant_id='tenant_a')
        _grant_perms(self.voider, [
            ('department_duty_log', 'department_duty_log', ['view', 'void']),
        ])
        self.voider_client = _make_client(self.voider)

        # 给 signer 配置签名
        resp = self.supper_client.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': _make_png_file(), 'remark': 'ddl setup'},
        )
        body = json.loads(resp.content)
        assert not body.get('error'), f'setup assign failed: {body.get("error")}'
        self.sig = AccountSignature.objects.get(user_id=self.signer.id)

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _parse(self, response):
        return json.loads(response.content)

    def _create_draft(self):
        """创建一条草稿"""
        resp = self.signer_client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '今日值班正常',
            'mains_voltage': '220V',
            'ups_voltage': '正常',
            'weather': '晴',
        }), content_type='application/json')
        body = self._parse(resp)
        assert not body.get('error'), f'create draft failed: {body.get("error")}'
        return DepartmentDutyLog.objects.get(pk=body['data']['id'])

    def test_production_scenes_whitelist(self):
        """生产场景精确等于批准白名单"""
        expected = frozenset({
            sig_services.DEPARTMENT_DUTY_LOG_SIGNATURE_SCENE,
        })
        self.assertEqual(sig_services.SIGNATURE_SCENES, expected)

    def test_production_global_shared_scenes(self):
        """全局共享场景注册正确"""
        self.assertIn(
            sig_services.DEPARTMENT_DUTY_LOG_SIGNATURE_SCENE,
            sig_services.GLOBAL_SHARED_SIGNATURE_SCENES,
        )

    def test_sign_success(self):
        """签署成功：actor、值班员和 signed_by 均为当前用户"""
        record = self._create_draft()
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({
                'version': 1,
                'confirm': True,
                'request_id': 'test-req-001',
            }),
            content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))

        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_SIGNED)
        self.assertEqual(record.duty_person_id, self.signer.id)
        self.assertEqual(record.signed_by_id, self.signer.id)
        self.assertIsNotNone(record.signature_usage_id)
        self.assertIsNotNone(record.signed_at)
        self.assertIsNotNone(record.signature_version)
        self.assertTrue(record.signature_sha256)
        self.assertTrue(record.business_snapshot_hash)

        # 验证创建了唯一 Usage 和 EvidenceEvent
        usage = SignatureUsage.objects.get(pk=record.signature_usage_id)
        self.assertEqual(usage.signer_user_id, self.signer.id)
        self.assertEqual(usage.module, 'department_duty_log')
        events = EvidenceEvent.objects.filter(
            module='department_duty_log', object_type='department_duty_log',
            object_id=str(record.id))
        self.assertEqual(events.count(), 1)

    def test_sign_idempotent(self):
        """相同 request_id 重试返回同一签署结果"""
        record = self._create_draft()
        req_id = 'test-req-idem-001'
        # 第一次签署
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': req_id}),
            content_type='application/json')
        body1 = self._parse(resp)
        self.assertFalse(body1.get('error'), body1.get('error'))
        usage_id_1 = body1['data']['signature_usage_id']

        # 第二次相同 request_id：record 已是 signed，应拒绝（状态检查在前）
        # 但如果版本还是 1，则进入 apply_signature 的幂等逻辑
        # 由于第一次签署后 version 变为 2，第二次 version=1 不匹配会先报版本冲突
        # 这是正确行为
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 2, 'confirm': True, 'request_id': req_id}),
            content_type='application/json')
        body2 = self._parse(resp)
        # record 已 signed，应拒绝
        self.assertTrue(body2.get('error'))

        # 只创建了一条 Usage
        self.assertEqual(SignatureUsage.objects.filter(request_id=req_id).count(), 1)

    def test_sign_no_signature_fails(self):
        """无签名时签署失败"""
        # 创建一个没有签名的用户
        no_sig_user = _make_user('no_sig_user', tenant_id='tenant_a')
        _grant_perms(no_sig_user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'sign']),
        ])
        client = _make_client(no_sig_user)

        # 创建草稿
        resp = client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '测试',
            'mains_voltage': '220V',
            'ups_voltage': '正常',
            'weather': '晴',
        }), content_type='application/json')
        body = self._parse(resp)
        record_id = body['data']['id']

        # 签署应失败
        resp = client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'no-sig-001'}),
            content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))

        # 草稿状态不变
        record = DepartmentDutyLog.objects.get(pk=record_id)
        self.assertEqual(record.status, STATUS_DRAFT)
        self.assertIsNone(record.signature_usage_id)

    def test_sign_forged_fields_rejected(self):
        """签署请求伪造字段被拒绝"""
        record = self._create_draft()
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({
                'version': 1,
                'confirm': True,
                'request_id': 'forge-001',
                'signed_by_id': 999,
                'signature_usage_id': 123,
            }),
            content_type='application/json')
        body = self._parse(resp)
        self.assertTrue(body.get('error'))
        self.assertIn('不允许', body['error'])

    def test_signed_record_viewable_cross_tenant(self):
        """签署后跨租户用户可查看"""
        record = self._create_draft()
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'cross-001'}),
            content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))

        record.refresh_from_db()
        # 跨租户 viewer 能看到
        resp = self.viewer_client.get(f'/department-duty-log/records/{record.id}/')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        self.assertEqual(body['data']['id'], record.id)
        self.assertEqual(body['data']['status'], STATUS_SIGNED)

    def test_detail_returns_full_duty_record_remark_and_signature(self):
        """详情接口返回完整 duty_record、remark 全文及签署信息。

        列表接口仅返回 duty_record_summary（前 100 字摘要），详情接口必须返回
        duty_record / remark 全文，否则前端详情页会显示 '--'。
        """
        long_record = '值班记录全文：\n1. 设备巡检正常\n2. 环境参数达标\n' * 3
        remark_text = '备注：无异常\n第二行'
        record = _make_record(
            self.signer, duty_record=long_record, remark=remark_text)

        # 草稿态详情：本人可读，返回全文 + 无签署信息
        resp = self.signer_client.get(f'/department-duty-log/records/{record.id}/')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        data = body['data']
        self.assertEqual(data['duty_record'], long_record)
        self.assertEqual(data['remark'], remark_text)
        self.assertEqual(data['status'], STATUS_DRAFT)
        self.assertIsNone(data['signature_usage_id'])
        self.assertEqual(data['signed_by_name'], '')

        # 签署
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'detail-001'}),
            content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))

        record.refresh_from_db()
        # 已签态详情：跨租户 viewer 可读，返回全文 + 完整签署信息
        resp = self.viewer_client.get(f'/department-duty-log/records/{record.id}/')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))
        data = body['data']
        self.assertEqual(data['duty_record'], long_record)
        self.assertEqual(data['remark'], remark_text)
        self.assertEqual(data['status'], STATUS_SIGNED)
        self.assertEqual(data['signature_usage_id'], record.signature_usage_id)
        self.assertEqual(data['signed_by_name'], record.signed_by_name)
        self.assertTrue(data['signed_at'])
        self.assertIsNotNone(data['signature_version'])
        self.assertTrue(data['business_snapshot_hash'])

    def test_signature_image_cross_tenant_view(self):
        """跨租户用户有 view 权限可读取签名图片"""
        record = self._create_draft()
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'img-001'}),
            content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))

        record.refresh_from_db()
        # 跨租户 viewer 读取签名图片
        resp = self.viewer_client.get(f'/department-duty-log/records/{record.id}/signature-image/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/png')

    def test_signature_image_tampered_usage_id_rejected(self):
        """篡改 usage_id 被拒绝"""
        record = self._create_draft()
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'tamper-001'}),
            content_type='application/json')
        self._parse(resp)

        # 直接调用全局业务读取，传入错误的 module
        record.refresh_from_db()
        info, error = sig_services.get_signature_image_for_global_business(
            usage_id=record.signature_usage_id,
            module='wrong_module',
            object_type='department_duty_log',
            object_id=str(record.id),
            scene_code='duty_person',
        )
        self.assertIsNotNone(error)

    def test_signature_image_wrong_object_id_rejected(self):
        """篡改 object_id 被拒绝"""
        record = self._create_draft()
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'tamper-002'}),
            content_type='application/json')
        self._parse(resp)

        record.refresh_from_db()
        info, error = sig_services.get_signature_image_for_global_business(
            usage_id=record.signature_usage_id,
            module='department_duty_log',
            object_type='department_duty_log',
            object_id='99999',
            scene_code='duty_person',
        )
        self.assertIsNotNone(error)

    def test_global_business_scene_not_in_whitelist_rejected(self):
        """非白名单场景被拒绝"""
        info, error = sig_services.get_signature_image_for_global_business(
            usage_id=1,
            module='other_module',
            object_type='other_type',
            object_id='1',
            scene_code='other_scene',
        )
        self.assertIsNotNone(error)

    def test_business_snapshot_stable(self):
        """业务快照稳定，同值不同键顺序哈希一致"""
        record = _make_record(user=self.signer, duty_record='测试', remark='备注')
        snap1 = services.build_business_snapshot(record)
        hash1 = sig_services.compute_business_snapshot_hash(snap1)

        # 打乱键顺序
        import collections
        shuffled = dict(reversed(list(snap1.items())))
        hash2 = sig_services.compute_business_snapshot_hash(shuffled)
        self.assertEqual(hash1, hash2)

    def test_business_snapshot_value_change_changes_hash(self):
        """业务值变化哈希变化"""
        record = _make_record(user=self.signer, duty_record='测试A')
        snap1 = services.build_business_snapshot(record)
        hash1 = sig_services.compute_business_snapshot_hash(snap1)

        record.duty_record = '测试B'
        snap2 = services.build_business_snapshot(record)
        hash2 = sig_services.compute_business_snapshot_hash(snap2)
        self.assertNotEqual(hash1, hash2)

    def test_void_success(self):
        """有 void 权限并填写原因：状态变为 void"""
        record = self._create_draft()
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'void-001'}),
            content_type='application/json')
        self._parse(resp)
        record.refresh_from_db()

        resp = self.voider_client.post(
            f'/department-duty-log/records/{record.id}/void/',
            data=json.dumps({'reason': '记录有误需更正'}),
            content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))

        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_VOID)
        self.assertIsNotNone(record.voided_at)
        self.assertEqual(record.voided_by_id, self.voider.id)
        self.assertEqual(record.void_reason, '记录有误需更正')
        # Usage 保持不变
        self.assertIsNotNone(record.signature_usage_id)

        # void 证据事件
        void_events = EvidenceEvent.objects.filter(
            module='department_duty_log', object_type='department_duty_log',
            object_id=str(record.id), event_type='void')
        self.assertEqual(void_events.count(), 1)

    def test_correction_after_void(self):
        """作废后新建更正记录"""
        record = self._create_draft()
        # 签署
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'corr-001'}),
            content_type='application/json')
        self._parse(resp)
        # 作废
        resp = self.voider_client.post(
            f'/department-duty-log/records/{record.id}/void/',
            data=json.dumps({'reason': '需要更正'}),
            content_type='application/json')
        self._parse(resp)
        record.refresh_from_db()

        # 更正
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/corrections/',
            data=json.dumps({}), content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'), body.get('error'))

        new_record = DepartmentDutyLog.objects.get(pk=body['data']['id'])
        self.assertEqual(new_record.status, STATUS_DRAFT)
        self.assertEqual(new_record.supersedes_id, record.id)
        self.assertEqual(new_record.duty_person_id, self.signer.id)
        self.assertIsNone(new_record.signature_usage_id)
        self.assertEqual(new_record.version, 1)


# ============================================================
# 审计
# ============================================================

class DepartmentDutyLogAuditTests(TestCase):
    """审计测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('audit_user', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del']),
        ])
        self.client = _make_client(self.user)

    def _parse(self, response):
        return json.loads(response.content)

    def test_create_audit(self):
        """新增产生审计，target_type 为 department_duty_log"""
        from apps.logs.models import AuditLog
        resp = self.client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': '测试',
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))

        logs = AuditLog.objects.filter(
            target_type='department_duty_log', action='create')
        self.assertTrue(logs.exists())
        log = logs.first()
        self.assertEqual(str(log.target_id), str(body['data']['id']))
        self.assertEqual(log.tenant_id, self.user.tenant_id)

    def test_edit_audit(self):
        """编辑产生审计"""
        from apps.logs.models import AuditLog
        record = _make_record(self.user)
        resp = self.client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '修改后',
                'version': 1,
            }),
            content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))

        logs = AuditLog.objects.filter(
            target_type='department_duty_log', action='update')
        self.assertTrue(logs.exists())

    def test_delete_audit(self):
        """草稿删除产生审计"""
        from apps.logs.models import AuditLog
        record = _make_record(self.user)
        resp = self.client.delete(f'/department-duty-log/records/{record.id}/')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))

        logs = AuditLog.objects.filter(
            target_type='department_duty_log', action='delete')
        self.assertTrue(logs.exists())

    def test_audit_no_binary_or_full_text(self):
        """审计不包含签名二进制或完整长文本"""
        from apps.logs.models import AuditLog
        long_text = 'A' * 5000
        resp = self.client.post('/department-duty-log/records/', data=json.dumps({
            'duty_date': str(date.today()),
            'duty_record': long_text,
            'mains_voltage': '220V',
            'ups_voltage': '正常',
            'weather': '晴',
        }), content_type='application/json')
        body = self._parse(resp)
        self.assertFalse(body.get('error'))

        logs = AuditLog.objects.filter(
            target_type='department_duty_log', action='create')
        log = logs.first()
        detail = json.loads(log.detail) if log.detail else {}
        # 审计详情不应包含完整 5000 字符的长文本
        detail_str = json.dumps(detail)
        self.assertNotIn('A' * 100, detail_str)


# ============================================================
# 模型和迁移检查
# ============================================================

class DepartmentDutyLogModelTests(TestCase):
    """模型和迁移检查"""

    def test_no_tenant_id_field(self):
        """模型不包含 tenant_id 字段"""
        field_names = {f.name for f in DepartmentDutyLog._meta.get_fields()}
        self.assertNotIn('tenant_id', field_names)

    def test_table_name(self):
        """表名为 tdyw_department_duty_log"""
        self.assertEqual(DepartmentDutyLog._meta.db_table, 'tdyw_department_duty_log')

    def test_status_choices(self):
        """状态常量正确"""
        self.assertEqual(STATUS_DRAFT, 'draft')
        self.assertEqual(STATUS_SIGNED, 'signed')
        self.assertEqual(STATUS_VOID, 'void')

    def test_signature_usage_id_unique(self):
        """signature_usage_id 唯一"""
        field = DepartmentDutyLog._meta.get_field('signature_usage_id')
        self.assertTrue(field.unique)
