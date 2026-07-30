# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 第二轮审查验证测试：验证另一个 AI 发现的 5 个问题
# 运行：docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
#       python manage.py test apps.department_duty_log.audit2_tests --noinput
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
from apps.signature.models import SignatureUsage

from .models import DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED
from . import services


# ============================================================
# 辅助函数（与 audit_tests.py 一致）
# ============================================================

def _make_user(username, **kwargs):
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
    from django.test import Client
    c = Client()
    c.defaults['HTTP_X_TOKEN'] = user.access_token
    c.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return c


def _grant_perms(user, perms):
    perm_dict = {}
    for module, page, keys in perms:
        perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)
    role_name = f'audit2_role_{user.username}'
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
    user.set_perms_cache()
    return role


def _make_record(user, **kwargs):
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
    from PIL import Image
    from django.core.files.uploadedfile import SimpleUploadedFile
    img = Image.new('RGBA', (width, height), (255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


# ============================================================
# 问题 1：异步详情请求可能覆盖错误记录（前端竞态）
# ============================================================

class Audit2Issue1_AsyncDetailRaceConditionTests(TestCase):
    """验证问题 1：showForm 异步详情请求无序号/无 AbortController，存在竞态。

    这是前端 JavaScript 问题，无法用 Django 后端测试直接复现。
    但可以通过代码审查确认以下事实：
    1. showForm 无条件写入异步响应（store.js:89）
    2. componentDidMount 仅挂载时填充表单（Form.js:19）
    3. handleSubmit 从 store.formRecord 获取 id/version（Form.js:73-76）

    以下测试验证后端不会阻止这种竞态（即后端没有额外的防护）。
    """

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('a2user1', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'edit']),
        ])
        self.client_obj = _make_client(self.user)

    def test_edit_uses_version_from_list_not_detail(self):
        """编辑提交时 version 来自 store.formRecord，可能被异步详情覆盖。

        模拟：列表返回 version=1 的记录 A，详情返回 version=2 的记录 A（并发修改）。
        前端用列表的 version=1 提交，后端应该拒绝（乐观锁）。
        但如果异步详情返回 version=2，前端会用 version=2 提交，绕过乐观锁。
        """
        record = _make_record(self.user, duty_record='原始内容', version=1)

        # 列表返回 version=1
        resp = self.client_obj.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        list_item = body['data']['records'][0]
        self.assertEqual(list_item['version'], 1)

        # 详情返回 version=2（模拟并发修改后详情）
        DepartmentDutyLog.objects.filter(pk=record.id).update(version=2)
        resp = self.client_obj.get(f'/department-duty-log/records/{record.id}/')
        body = json.loads(resp.content)
        detail_item = body['data']
        self.assertEqual(detail_item['version'], 2)

        # 如果前端用详情的 version=2 提交（异步详情覆盖了列表的 version=1），
        # 后端会接受，但用户看到的是旧内容 -> 误覆盖
        resp = self.client_obj.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'weather': '雨',
                'duty_record': '用户修改的内容',
                'remark': '',
                'version': 2,  # 来自异步详情，不是列表
            }),
            content_type='application/json',
        )
        body = json.loads(resp.content)
        self.assertFalse(body.get('error'),
                         '用详情返回的最新 version 提交成功 -> 绕过乐观锁')

        # 后端确实接受了，但另一个并发修改可能被覆盖
        record.refresh_from_db()
        self.assertEqual(record.duty_record, '用户修改的内容')


# ============================================================
# 问题 2（已修复）：列表和导出无日期时都返回全部记录
# ============================================================

class Audit2Issue2_DateDefaultFixedTests(TestCase):
    """验证修复：列表无日期时返回全部记录，与导出行为一致。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('a2user2', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'export']),
        ])
        self.client_obj = _make_client(self.user)

    def test_list_with_empty_dates_returns_all(self):
        """列表无日期参数时返回全部记录（不再默认 31 天）"""
        old_date = date.today() - timedelta(days=60)
        _make_record(self.user, duty_date=old_date, status=STATUS_SIGNED,
                     duty_record='60天前已签')
        _make_record(self.user, duty_date=date.today(), status=STATUS_SIGNED,
                     duty_record='今天的')

        # 不传日期参数
        resp = self.client_obj.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        items = body['data']['records']
        old_items = [i for i in items if '60天前' in i.get('duty_record_summary', '')]
        self.assertEqual(len(old_items), 1,
                         '列表无日期时应返回全部记录，包括 60 天前的')

    def test_export_with_empty_dates_returns_all_history(self):
        """导出无日期参数时返回全部历史"""
        old_date = date.today() - timedelta(days=60)
        _make_record(self.user, duty_date=old_date, status=STATUS_SIGNED,
                     duty_record='60天前已签导出')

        # 不传日期参数
        filters, error = services._parse_export_filters({})
        self.assertIsNone(error)
        self.assertNotIn('start_date', filters)
        self.assertNotIn('end_date', filters)

        qs = services._get_export_queryset(self.user, filters)
        self.assertTrue(qs.filter(duty_record='60天前已签导出').exists(),
                        '导出无日期默认，60 天前的记录被包含')

    def test_list_and_export_date_parsers_consistent(self):
        """列表和导出的日期解析器行为一致：无日期都返回 None"""
        list_start, list_end, list_err = services._parse_list_date_range({})
        self.assertIsNone(list_err)
        self.assertIsNone(list_start)
        self.assertIsNone(list_end)

        export_filters, export_err = services._parse_export_filters({})
        self.assertIsNone(export_err)
        self.assertNotIn('start_date', export_filters)
        self.assertNotIn('end_date', export_filters)

        # 核心断言：两者无日期时行为一致（都不加日期过滤）
        self.assertTrue(
            list_start is None and 'start_date' not in export_filters,
            '列表和导出无日期时行为一致：都不加日期过滤',
        )


# ============================================================
# 问题 3（已修复）：签署接口现在支持真正的幂等重试
# ============================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Audit2Issue3_SignIdempotentRetryTests(TestCase):
    """验证修复：sign_draft 对相同 request_id 的重试返回已有签署结果。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('a2supper3', is_supper=True, tenant_id='default')
        self.supper_client = _make_client(self.supper)

        self.signer = _make_user('a2signer3', tenant_id='tenant_a')
        _grant_perms(self.signer, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'sign']),
        ])
        self.signer_client = _make_client(self.signer)

        resp = self.supper_client.post(
            f'/account/user/{self.signer.id}/signature/',
            {'file': _make_png_file(), 'remark': 'audit2 test sig'},
        )
        assert not json.loads(resp.content).get('error'), 'signature setup failed'

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _create_draft(self):
        resp = self.signer_client.post(
            '/department-duty-log/records/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'duty_record': '幂等重试测试',
                'weather': '晴',
            }),
            content_type='application/json',
        )
        body = json.loads(resp.content)
        assert not body.get('error'), f'create failed: {body.get("error")}'
        return body['data']

    def test_retry_with_same_request_id_returns_existing_result(self):
        """修复后：首次签署成功后，用相同 request_id 重试返回已有结果"""
        draft_data = self._create_draft()
        record_id = draft_data['id']
        req_id = f'a2-idem-{uuid.uuid4().hex[:8]}'

        # 第一次签署：成功
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': req_id}),
            content_type='application/json',
        )
        body1 = json.loads(resp.content)
        self.assertFalse(body1.get('error'), f'第一次签署应成功: {body1.get("error")}')

        # 模拟响应丢失，用相同 request_id 重试（version=2 已是当前版本）
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({'version': 2, 'confirm': True, 'request_id': req_id}),
            content_type='application/json',
        )
        body2 = json.loads(resp.content)

        # 修复后：应返回已有结果（无错误）
        self.assertFalse(body2.get('error'),
                         f'相同 request_id 重试应返回已有结果: {body2.get("error")}')
        self.assertEqual(body2['data']['status'], STATUS_SIGNED)

        # 只创建了一条 Usage（幂等，没有重复签署）
        self.assertEqual(
            SignatureUsage.objects.filter(request_id=req_id).count(), 1,
            '幂等重试不应创建新 Usage',
        )

    def test_different_request_id_on_signed_record_still_fails(self):
        """不同 request_id 签署已签记录仍然失败"""
        draft_data = self._create_draft()
        record_id = draft_data['id']

        # 第一次签署
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': f'first-{uuid.uuid4().hex[:8]}'}),
            content_type='application/json',
        )
        self.assertFalse(json.loads(resp.content).get('error'))

        # 用不同的 request_id 签署 -> 应失败
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({'version': 2, 'confirm': True, 'request_id': f'other-{uuid.uuid4().hex[:8]}'}),
            content_type='application/json',
        )
        body = json.loads(resp.content)
        self.assertTrue(body.get('error'), '不同 request_id 签署已签记录应失败')


# ============================================================
# 问题 4（已修复）：数据库约束现已覆盖草稿 CharField 残留
# ============================================================

class Audit2Issue4_DraftCharFieldBlockedTests(TestCase):
    """验证修复：草稿携带 CharField 签署残留现在被约束拦截。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('a2user4', tenant_id='tenant_a')

    def test_draft_with_residual_signed_by_name_blocked(self):
        """修复后：草稿携带残留 signed_by_name 被约束拦截"""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            DepartmentDutyLog.objects.create(
                duty_date=date.today(),
                duty_person=self.user,
                duty_person_name=self.user.username,
                weather='晴',
                duty_record='测试残留 signed_by_name',
                status=STATUS_DRAFT,
                version=1,
                created_by=self.user,
                signed_by_name='张三',
            )

    def test_draft_with_residual_signature_sha256_blocked(self):
        """修复后：草稿携带残留 signature_sha256 被约束拦截"""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            DepartmentDutyLog.objects.create(
                duty_date=date.today(),
                duty_person=self.user,
                duty_person_name=self.user.username,
                weather='晴',
                duty_record='测试残留 sha256',
                status=STATUS_DRAFT,
                version=1,
                created_by=self.user,
                signature_sha256='c' * 64,
            )

    def test_draft_with_residual_business_snapshot_hash_blocked(self):
        """修复后：草稿携带残留 business_snapshot_hash 被约束拦截"""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            DepartmentDutyLog.objects.create(
                duty_date=date.today(),
                duty_person=self.user,
                duty_person_name=self.user.username,
                weather='晴',
                duty_record='测试残留 snapshot_hash',
                status=STATUS_DRAFT,
                version=1,
                created_by=self.user,
                business_snapshot_hash='d' * 64,
            )

    def test_draft_all_char_filled_blocked(self):
        """修复后：草稿 3 个 CharField 全有值被约束拦截"""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            DepartmentDutyLog.objects.create(
                duty_date=date.today(),
                duty_person=self.user,
                duty_person_name=self.user.username,
                weather='晴',
                duty_record='全部 CharField 残留',
                status=STATUS_DRAFT,
                version=1,
                created_by=self.user,
                signed_by_name='李四',
                signature_sha256='e' * 64,
                business_snapshot_hash='f' * 64,
            )

    def test_clean_draft_still_ok(self):
        """正常草稿（无任何签署字段）能正常保存"""
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


# ============================================================
# 问题 5（已修复）：列表恢复只返回摘要，响应体不再放大
# ============================================================

class Audit2Issue5_ListResponseOptimizedTests(TestCase):
    """验证修复：列表不再返回完整 duty_record，响应体保持紧凑。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('a2user5', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view']),
        ])
        self.client_obj = _make_client(self.user)

    def test_list_does_not_return_full_duty_record(self):
        """列表不返回完整 duty_record，只返回摘要"""
        long_text = 'X' * 5000
        _make_record(self.user, duty_record=long_text)

        resp = self.client_obj.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        item = body['data']['records'][0]

        # 列表不含全文
        self.assertNotIn('duty_record', item,
                         '列表不应包含 duty_record 全文')
        # 列表有摘要（最多 103 字符）
        self.assertIn('duty_record_summary', item)
        self.assertLessEqual(len(item['duty_record_summary']), 103)

    def test_list_response_size_compact(self):
        """多条长正文记录的列表响应体保持紧凑"""
        for i in range(10):
            _make_record(
                self.user,
                duty_record=f'记录{i}_' + 'Y' * 3000,
                duty_date=date.today() - timedelta(days=i),
            )

        resp = self.client_obj.get('/department-duty-log/records/')
        resp_size = len(resp.content)

        # 10 条记录，每条摘要最多 103 字，正文不在响应中
        # 响应体应远小于 30000 字节（之前包含全文时 >30000）
        self.assertLess(resp_size, 15000,
                        '列表响应体应保持紧凑（不含全文正文）')
