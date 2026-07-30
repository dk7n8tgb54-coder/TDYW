# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 审查测试：验证部门值班日志 8 项审查发现
# 运行：docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
#       python manage.py test apps.department_duty_log.audit_tests --noinput
import io
import json
import os
import shutil
import tempfile
import time
import uuid
from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.conf import settings

from apps.account.models import User, Role
from apps.setting.utils import AppSetting
from apps.signature import services as sig_services

from .models import DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED
from . import services


# ============================================================
# 测试辅助函数（与 tests.py 保持一致）
# ============================================================

def _make_user(username, **kwargs):
    """创建用户并生成 access_token"""
    token = (username * 10)[:32]
    defaults = {
        'username': username,
        'nickname': username,
        'password_hash': 'x',
        'is_active': True,
        'is_supper': False,
        'access_token': token,
        'token_expired': int(time.time()) + 3600,
        'last_login': '2026-01-01',
        'last_ip': '127.0.0.1',
        'type': 'default',
        'tenant_id': 'default',
    }
    defaults.update(kwargs)
    return User.objects.create(**defaults)


def _make_client(user):
    """创建认证 client"""
    from django.test import Client
    c = Client()
    c.defaults['HTTP_X_TOKEN'] = user.access_token
    c.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return c


def _grant_perms(user, perms):
    """授权（复用 tests.py 中的模式，但修复重复创建角色问题）"""
    perm_dict = {}
    for module, page, keys in perms:
        perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)

    # 修复：先查已有同名角色，有则更新而非重建
    role_name = f'audit_role_{user.username}'
    role = Role.objects.filter(name=role_name).first()
    if role:
        existing = json.loads(role.page_perms) if role.page_perms else {}
        for m, pages in perm_dict.items():
            if m not in existing:
                existing[m] = {}
            for p, keys in pages.items():
                if p not in existing[m]:
                    existing[m][p] = []
                existing[m][p].extend(keys)
        role.page_perms = json.dumps(existing)
        role.save()
    else:
        role = Role.objects.create(
            name=role_name,
            page_perms=json.dumps(perm_dict),
            created_by=user,
        )
        user.roles.add(role)
    user.set_perms_cache()  # 清空缓存，下次访问重新计算
    return role


def _make_record(user, **kwargs):
    """直接创建记录"""
    defaults = {
        'duty_date': date.today(),
        'duty_person': user,
        'duty_person_name': user.nickname or user.username,
        'weather': '晴',
        'duty_record': '值班正常',
        'remark': '',
        'status': STATUS_DRAFT,
        'version': 1,
        'created_by': user,
    }
    defaults.update(kwargs)
    if defaults['status'] == STATUS_SIGNED:
        signed_defaults = {
            'signature_usage_id': uuid.uuid4().int & ((1 << 63) - 1),
            'signed_by': user,
            'signed_by_name': user.nickname or user.username,
            'signed_at': '2026-01-01 00:00:00',
            'signature_version': 1,
            'signature_sha256': 'a' * 64,
            'business_snapshot_hash': 'b' * 64,
        }
        for field, value in signed_defaults.items():
            defaults.setdefault(field, value)
    return DepartmentDutyLog.objects.create(**defaults)


def _make_png_file(width=200, height=100, name='sig.png'):
    """生成有效 PNG 文件（与 tests.py 一致）"""
    from PIL import Image
    from django.core.files.uploadedfile import SimpleUploadedFile
    img = Image.new('RGBA', (width, height), (255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


# ============================================================
# 审查问题 1 & 2（已修复）：列表只返回摘要，编辑/签署通过详情接口回填
# ============================================================

class AuditIssue1_2_ListSummaryWithDetailFetchTests(TestCase):
    """验证修复：列表只返回摘要，编辑/签署通过详情接口获取完整正文。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('audit_user_12', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'sign']),
        ])
        self.client_obj = _make_client(self.user)

    def test_list_item_only_has_summary(self):
        """列表项只有 duty_record_summary，不含 duty_record 全文"""
        long_text = 'A' * 200
        _make_record(self.user, duty_record=long_text, remark='上级要求内容')

        resp = self.client_obj.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        self.assertFalse(body.get('error'), f'list failed: {body.get("error")}')

        items = body['data']['records']
        self.assertEqual(len(items), 1)
        item = items[0]

        # 列表不含全文
        self.assertNotIn('duty_record', item)
        # 列表有摘要
        self.assertIn('duty_record_summary', item)
        self.assertLessEqual(len(item['duty_record_summary']), 103)
        # 列表返回 remark
        self.assertEqual(item['remark'], '上级要求内容')

    def test_detail_returns_full_duty_record(self):
        """详情接口返回完整 duty_record"""
        long_text = 'B' * 200
        record = _make_record(self.user, duty_record=long_text)

        resp = self.client_obj.get(f'/department-duty-log/records/{record.id}/')
        body = json.loads(resp.content)
        self.assertFalse(body.get('error'))

        data = body['data']
        self.assertEqual(data['duty_record'], long_text)
        self.assertNotIn('duty_record_summary', data)

    def test_edit_form_fetches_detail_for_full_text(self):
        """模拟前端 showForm：先调详情接口获取完整 duty_record"""
        long_text = 'C' * 200
        record = _make_record(self.user, duty_record=long_text)

        # 列表只有摘要
        resp = self.client_obj.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        list_record = body['data']['records'][0]
        self.assertNotIn('duty_record', list_record)

        # 详情接口返回完整正文
        resp = self.client_obj.get(f'/department-duty-log/records/{record.id}/')
        body = json.loads(resp.content)
        detail_record = body['data']
        self.assertEqual(detail_record['duty_record'], long_text)


# ============================================================
# 审查问题 3：列表和导出对"未选择日期"的默认行为不一致
# ============================================================

class AuditIssue3_DateDefaultInconsistencyTests(TestCase):
    """验证：列表默认最近 31 天，导出不加默认（全量）"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('audit_user_3', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'export']),
        ])
        self.client_obj = _make_client(self.user)

    def test_list_no_date_returns_all(self):
        """列表无日期参数时返回全部记录（不再默认 31 天）"""
        # 创建 60 天前的已签记录
        old_date = date.today() - timedelta(days=60)
        _make_record(
            self.user,
            duty_date=old_date,
            duty_record='60天前的记录',
            status=STATUS_SIGNED,
        )
        # 创建今天的已签记录
        _make_record(
            self.user,
            duty_date=date.today(),
            duty_record='今天的记录',
            status=STATUS_SIGNED,
        )

        # 不传日期参数
        resp = self.client_obj.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        self.assertFalse(body.get('error'))

        items = body['data']['records']
        # 60 天前的记录也应出现
        old_items = [i for i in items if '60天前' in i.get('duty_record_summary', '')]
        self.assertEqual(len(old_items), 1,
                         '列表无日期时应返回全部记录，包括 60 天前的')

    def test_export_filters_no_date_default(self):
        """导出解析器无日期参数时不加默认限制"""
        # 模拟前端不传日期
        filters, error = services._parse_export_filters({})
        self.assertIsNone(error)
        # 核心断言：导出不设默认日期
        self.assertNotIn('start_date', filters)
        self.assertNotIn('end_date', filters)

    def test_list_date_parser_no_default(self):
        """列表日期解析器无日期时不加默认"""
        start, end, error = services._parse_list_date_range({})
        self.assertIsNone(error)
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_export_queryset_includes_old_records_without_date(self):
        """导出 queryset 无日期时包含全部已签记录"""
        old_date = date.today() - timedelta(days=60)
        _make_record(
            self.user,
            duty_date=old_date,
            duty_record='60天前已签',
            status=STATUS_SIGNED,
        )

        filters, _ = services._parse_export_filters({})
        qs = services._get_export_queryset(self.user, filters)
        # 核心断言：导出包含 60 天前的记录
        self.assertTrue(qs.filter(duty_record='60天前已签').exists())


# ============================================================
# 审查问题 4（已修复）：签署接口 version 现在必填
# ============================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AuditIssue4_SignVersionRequiredTests(TestCase):
    """验证修复：签署接口 version 现在必填，无法绕过乐观锁"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('audit_supper_4', is_supper=True, tenant_id='default')
        self.supper_client = _make_client(self.supper)

        self.signer = _make_user('audit_signer_4', tenant_id='tenant_a')
        _grant_perms(self.signer, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'sign']),
        ])
        self.signer_client = _make_client(self.signer)

        # 配置签名
        resp = self.supper_client.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': _make_png_file(), 'remark': 'audit test sig'},
        )
        body = json.loads(resp.content)
        assert not body.get('error'), f'signature setup failed: {body.get("error")}'

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _create_draft(self):
        resp = self.signer_client.post(
            '/department-duty-log/records/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '测试版本必填',
                'weather': '晴',
            }),
            content_type='application/json',
        )
        body = json.loads(resp.content)
        assert not body.get('error'), f'create failed: {body.get("error")}'
        return body['data']

    def test_sign_without_version_now_rejected(self):
        """修复后：不传 version 被拒绝（参数校验层拦截）"""
        draft_data = self._create_draft()
        record_id = draft_data['id']

        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({
                'confirm': True,
                'request_id': f'audit-no-ver-{uuid.uuid4().hex[:8]}',
                # 故意不传 version
            }),
            content_type='application/json',
        )
        body = json.loads(resp.content)
        # 修复后：应返回参数错误
        self.assertTrue(body.get('error'),
                        '不传 version 应被拒绝')

    def test_sign_with_wrong_version_rejected(self):
        """传错误 version 被乐观锁拦截"""
        draft_data = self._create_draft()
        record_id = draft_data['id']

        # 模拟并发修改
        DepartmentDutyLog.objects.filter(pk=record_id).update(version=999)

        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({
                'version': 1,
                'confirm': True,
                'request_id': f'audit-wrong-ver-{uuid.uuid4().hex[:8]}',
            }),
            content_type='application/json',
        )
        body = json.loads(resp.content)
        self.assertTrue(body.get('error'))
        self.assertIn('版本', body['error'])

    def test_sign_with_correct_version_succeeds(self):
        """传正确 version 签署成功"""
        draft_data = self._create_draft()
        record_id = draft_data['id']

        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({
                'version': 1,
                'confirm': True,
                'request_id': f'audit-ok-ver-{uuid.uuid4().hex[:8]}',
            }),
            content_type='application/json',
        )
        body = json.loads(resp.content)
        self.assertFalse(body.get('error'),
                         f'正确 version 签署应成功: {body.get("error")}')
        self.assertEqual(body['data']['status'], STATUS_SIGNED)


# ============================================================
# 审查问题 5（已修复）：数据库约束现已完整
# ============================================================

class AuditIssue5_DatabaseConstraintFixedTests(TestCase):
    """验证修复：
    1. 草稿不能携带残留签署字段（约束拦截）
    2. 已签记录的 signed_by_id 必须等于 duty_person_id（约束拦截）
    """

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('audit_user_5', tenant_id='tenant_a')
        self.other_user = _make_user('audit_other_5', tenant_id='tenant_a')

    def test_draft_cannot_have_residual_signature_fields(self):
        """修复后：草稿携带残留签署字段被约束拦截"""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            DepartmentDutyLog.objects.create(
                duty_date=date.today(),
                duty_person=self.user,
                duty_person_name=self.user.username,
                weather='晴',
                duty_record='测试残留',
                status=STATUS_DRAFT,
                version=1,
                created_by=self.user,
                # 残留签署字段
                signature_usage_id=12345,
                signed_by=self.user,
                signed_by_name='残留签署人',
                signed_at='2026-01-01 00:00:00',
                signature_version=1,
                signature_sha256='a' * 64,
                business_snapshot_hash='b' * 64,
            )

    def test_signed_record_wrong_signer_rejected(self):
        """修复后：已签记录 signed_by != duty_person 被约束拦截"""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            DepartmentDutyLog.objects.create(
                duty_date=date.today(),
                duty_person=self.user,       # 值班人是 user
                duty_person_name=self.user.username,
                weather='晴',
                duty_record='测试签署人不一致',
                status=STATUS_SIGNED,
                version=2,
                created_by=self.user,
                # 签署人是 other_user，不等于 duty_person
                signature_usage_id=99999,
                signed_by=self.other_user,
                signed_by_name=self.other_user.username,
                signed_at='2026-01-01 00:00:00',
                signature_version=1,
                signature_sha256='c' * 64,
                business_snapshot_hash='d' * 64,
            )

    def test_draft_without_signature_fields_ok(self):
        """正常草稿（无签署字段）能正常保存"""
        record = DepartmentDutyLog.objects.create(
            duty_date=date.today(),
            duty_person=self.user,
            duty_person_name=self.user.username,
            weather='晴',
            duty_record='正常草稿',
            status=STATUS_DRAFT,
            version=1,
            created_by=self.user,
        )
        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_DRAFT)
        self.assertIsNone(record.signature_usage_id)

    def test_signed_with_correct_signer_ok(self):
        """正常已签记录（signed_by == duty_person）能正常保存"""
        record = DepartmentDutyLog.objects.create(
            duty_date=date.today(),
            duty_person=self.user,
            duty_person_name=self.user.username,
            weather='晴',
            duty_record='正常已签',
            status=STATUS_SIGNED,
            version=2,
            created_by=self.user,
            signature_usage_id=88888,
            signed_by=self.user,  # 签署人 == 值班人
            signed_by_name=self.user.username,
            signed_at='2026-01-01 00:00:00',
            signature_version=1,
            signature_sha256='e' * 64,
            business_snapshot_hash='f' * 64,
        )
        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_SIGNED)
        self.assertEqual(record.duty_person_id, record.signed_by_id)


# ============================================================
# 审查问题 6：_grant_perms 重复调用导致角色唯一约束冲突
# ============================================================

class AuditIssue6_GrantPermsDuplicateRoleTests(TestCase):
    """验证：对同一用户调用两次 _grant_perms 会触发 IntegrityError"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('audit_user_6', tenant_id='tenant_a')

    def test_duplicate_grant_perms_raises_integrity_error(self):
        """第二次 _grant_perms 创建同名角色触发 unique_together 冲突"""
        from django.db import IntegrityError

        # 模拟 tests.py 中的 _grant_perms（不修复版本）
        def _original_grant_perms(user, perms):
            perm_dict = {}
            for module, page, keys in perms:
                perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)
            role = Role.objects.create(
                name=f'role_{user.username}',
                page_perms=json.dumps(perm_dict),
                created_by=user,
            )
            user.roles.add(role)
            user.set_perms_cache()

        # 第一次授权
        _original_grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add']),
        ])

        # 第二次授权 -> 应该触发 unique_together('tenant_id', 'name') 冲突
        with self.assertRaises(IntegrityError):
            _original_grant_perms(self.user, [
                ('department_duty_log', 'department_duty_log', ['return']),
            ])

    def test_fixed_grant_perms_no_conflict(self):
        """修复后的 _grant_perms 不重复创建角色"""
        # 使用本文件顶部修复后的 _grant_perms
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add']),
        ])
        # 第二次调用不应报错
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['return']),
        ])
        # 验证权限已合并
        roles = self.user.roles.all()
        self.assertEqual(len(roles), 1)
        perms = json.loads(roles[0].page_perms)
        self.assertIn('return', perms['department_duty_log']['department_duty_log'])


# ============================================================
# 审查问题 9（已修复）：export 现在同时校验 view
# ============================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AuditIssue9_ExportRequiresViewTests(TestCase):
    """验证修复：export 现在是 view 的附加能力，仅有 export 无 view 被拒绝"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('audit_supper_9', is_supper=True, tenant_id='default')
        self.supper_client = _make_client(self.supper)

        self.signer = _make_user('audit_signer_9', tenant_id='tenant_a')
        _grant_perms(self.signer, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'sign', 'export']),
        ])
        self.signer_client = _make_client(self.signer)

        # 仅有 export 权限，没有 view
        self.export_only = _make_user('audit_export_only_9', tenant_id='tenant_a')
        _grant_perms(self.export_only, [
            ('department_duty_log', 'department_duty_log', ['export']),
        ])
        self.export_only_client = _make_client(self.export_only)

        # 配置签名
        resp = self.supper_client.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': _make_png_file(), 'remark': 'audit test sig'},
        )
        assert not json.loads(resp.content).get('error')

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _sign_record(self):
        """创建并签署一条记录"""
        resp = self.signer_client.post(
            '/department-duty-log/records/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': 'audit export test',
                'weather': '晴',
            }),
            content_type='application/json',
        )
        body = json.loads(resp.content)
        record_id = body['data']['id']

        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({
                'version': 1,
                'confirm': True,
                'request_id': f'audit-export-{uuid.uuid4().hex[:8]}',
            }),
            content_type='application/json',
        )
        return record_id

    def test_export_only_user_cannot_view_list(self):
        """仅有 export 权限的用户不能访问列表（无 view 权限）"""
        resp = self.export_only_client.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        self.assertTrue(body.get('error'),
                         '无 view 权限应被拒绝访问列表')

    def test_export_only_user_cannot_export(self):
        """修复后：仅有 export 无 view 的用户被拒绝导出"""
        self._sign_record()

        resp = self.export_only_client.post(
            '/department-duty-log/export/pdf/',
            data=json.dumps({}),
            content_type='application/json',
        )
        # 修复后：应返回权限错误
        body = json.loads(resp.content)
        self.assertTrue(body.get('error'),
                        '仅有 export 无 view 的用户应被拒绝导出')

    def test_user_with_both_view_and_export_can_export(self):
        """同时有 view 和 export 权限的用户能正常导出"""
        self._sign_record()

        resp = self.signer_client.post(
            '/department-duty-log/export/pdf/',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
