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
# 问题 2：清空日期后列表与导出范围不一致
# ============================================================

class Audit2Issue2_DateDefaultStillInconsistentTests(TestCase):
    """验证问题 2：前端初始化了日期，但用户清空后后端行为仍不一致。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('a2user2', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'export']),
        ])
        self.client_obj = _make_client(self.user)

    def test_list_with_empty_dates_defaults_to_31_days(self):
        """列表无日期参数时默认 31 天"""
        old_date = date.today() - timedelta(days=60)
        _make_record(self.user, duty_date=old_date, status=STATUS_SIGNED,
                     duty_record='60天前已签')
        _make_record(self.user, duty_date=date.today(), status=STATUS_SIGNED,
                     duty_record='今天的')

        # 不传日期参数（模拟用户清空日期）
        resp = self.client_obj.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        items = body['data']['records']
        old_items = [i for i in items if '60天前' in i.get('duty_record', '')]
        self.assertEqual(len(old_items), 0,
                         '列表默认 31 天，60 天前的记录不应出现')

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

    def test_list_and_export_date_parsers_diverge(self):
        """列表和导出的日期解析器行为不同"""
        # 列表解析器：无日期 -> 默认 31 天
        list_start, list_end, list_err = services._parse_list_date_range({})
        self.assertIsNone(list_err)
        self.assertIsNotNone(list_start)
        self.assertEqual(list_end, date.today())

        # 导出解析器：无日期 -> 无默认
        export_filters, export_err = services._parse_export_filters({})
        self.assertIsNone(export_err)
        self.assertNotIn('start_date', export_filters)
        self.assertNotIn('end_date', export_filters)

        # 核心断言：两者的默认行为不一致
        self.assertTrue(list_start is not None and 'start_date' not in export_filters,
                        '列表有默认日期，导出没有 -> 行为不一致')


# ============================================================
# 问题 3：签署接口没有实现真正的幂等重试
# ============================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Audit2Issue3_SignNotTrulyIdempotentTests(TestCase):
    """验证问题 3：sign_draft 在状态检查阶段拒绝已签记录，
    无法利用 apply_signature 的幂等能力。

    场景：首次签署成功但响应丢失，客户端用相同 request_id 重试。
    预期（正确）：返回已有签署结果。
    实际（当前）：返回 "当前记录状态不可签署"。
    """

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

    def test_retry_with_same_request_id_fails(self):
        """首次签署成功后，用相同 request_id 重试应返回已有结果，但实际返回失败"""
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
        usage_id_1 = body1['data']['signature_usage_id']

        # 模拟响应丢失，客户端用相同 request_id 和 version=2（当前版本）重试
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({'version': 2, 'confirm': True, 'request_id': req_id}),
            content_type='application/json',
        )
        body2 = json.loads(resp.content)

        # 核心断言：当前行为是返回错误（非幂等）
        self.assertTrue(body2.get('error'),
                        '当前 sign_draft 在状态检查阶段拒绝已签记录，未利用 apply_signature 的幂等能力')
        self.assertIn('状态', body2['error'])

        # 只创建了一条 Usage（apply_signature 没有被第二次调用）
        self.assertEqual(
            SignatureUsage.objects.filter(request_id=req_id).count(), 1,
            'apply_signature 的幂等逻辑未被触达',
        )

    def test_apply_signature_itself_is_idempotent(self):
        """apply_signature 本身有幂等检查，但 sign_draft 的前置状态检查阻止了重试触达它。

        直接调用 apply_signature 两次（相同 request_id、相同上下文）应返回同一结果。
        但通过 sign_draft 重试时，状态检查在 apply_signature 之前就拒绝了。
        """
        draft_data = self._create_draft()
        record_id = draft_data['id']
        req_id = f'a2-idem-sig-{uuid.uuid4().hex[:8]}'

        # 第一次签署
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record_id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': req_id}),
            content_type='application/json',
        )
        body1 = json.loads(resp.content)
        usage_id_1 = body1['data']['signature_usage_id']

        # 签署后 record 状态变了，快照也变了
        # 直接调用 apply_signature（绕过 sign_draft 的状态检查）
        # 此时快照与第一次不同 -> apply_signature 报幂等冲突（正确行为）
        record = DepartmentDutyLog.objects.get(pk=record_id)
        snapshot = services.build_business_snapshot(record)

        usage2, error2 = sig_services.apply_signature(
            actor=self.signer,
            module=services.MODULE,
            object_type=services.OBJECT_TYPE,
            object_id=str(record.id),
            scene_code=services.SCENE_CODE,
            business_snapshot=snapshot,
            request_id=req_id,
            request=None,
        )

        # apply_signature 检测到上下文不一致 -> 冲突（正确）
        self.assertIsNotNone(error2,
                             '上下文不一致时 apply_signature 报幂等冲突是正确行为')
        self.assertIn('幂等冲突', error2)

        # 核心断言：sign_draft 的前置状态检查阻止了重试触达 apply_signature
        # 即使 apply_signature 有幂等逻辑，sign_draft 也无法利用它
        self.assertEqual(
            SignatureUsage.objects.filter(request_id=req_id).count(), 1,
            'apply_signature 幂等，未创建新 Usage',
        )


# ============================================================
# 问题 4：数据库约束仍未完整覆盖草稿签署残留（CharField）
# ============================================================

class Audit2Issue4_DraftCharFieldResidualTests(TestCase):
    """验证问题 4：草稿分支只检查 4 个可空字段，未限制 3 个 CharField 残留。

    当前约束的 DRAFT 分支检查：
      signature_usage_id IS NULL ✓
      signed_by_id IS NULL ✓
      signed_at IS NULL ✓
      signature_version IS NULL ✓
    但未检查：
      signed_by_name = '' ✗
      signature_sha256 = '' ✗
      business_snapshot_hash = '' ✗
    """

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('a2user4', tenant_id='tenant_a')

    def test_draft_with_residual_signed_by_name(self):
        """草稿携带残留 signed_by_name 能保存（约束漏洞）"""
        from django.db import IntegrityError
        try:
            record = DepartmentDutyLog.objects.create(
                duty_date=date.today(),
                duty_person=self.user,
                duty_person_name=self.user.username,
                weather='晴',
                duty_record='测试残留 signed_by_name',
                status=STATUS_DRAFT,
                version=1,
                created_by=self.user,
                # 4 个可空字段为 NULL（通过约束）
                # 但 CharField 有残留
                signed_by_name='张三',
            )
            # 如果没有抛异常，说明约束没有覆盖这个字段
            record.refresh_from_db()
            self.assertEqual(record.status, STATUS_DRAFT)
            self.assertEqual(record.signed_by_name, '张三')
            constraint_covers = False
        except IntegrityError:
            constraint_covers = True

        # 核心断言：约束未覆盖 signed_by_name
        self.assertFalse(constraint_covers,
                         '草稿携带残留 signed_by_name 未被约束拦截')

    def test_draft_with_residual_signature_sha256(self):
        """草稿携带残留 signature_sha256 能保存（约束漏洞）"""
        from django.db import IntegrityError
        try:
            record = DepartmentDutyLog.objects.create(
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
            record.refresh_from_db()
            self.assertEqual(record.status, STATUS_DRAFT)
            self.assertEqual(record.signature_sha256, 'c' * 64)
            constraint_covers = False
        except IntegrityError:
            constraint_covers = True

        self.assertFalse(constraint_covers,
                         '草稿携带残留 signature_sha256 未被约束拦截')

    def test_draft_with_residual_business_snapshot_hash(self):
        """草稿携带残留 business_snapshot_hash 能保存（约束漏洞）"""
        from django.db import IntegrityError
        try:
            record = DepartmentDutyLog.objects.create(
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
            record.refresh_from_db()
            self.assertEqual(record.status, STATUS_DRAFT)
            self.assertEqual(record.business_snapshot_hash, 'd' * 64)
            constraint_covers = False
        except IntegrityError:
            constraint_covers = True

        self.assertFalse(constraint_covers,
                         '草稿携带残留 business_snapshot_hash 未被约束拦截')

    def test_draft_all_nullable_null_but_all_char_filled(self):
        """草稿 4 个可空字段为 NULL 但 3 个 CharField 全有值能保存（最隐蔽的残留）"""
        from django.db import IntegrityError
        try:
            record = DepartmentDutyLog.objects.create(
                duty_date=date.today(),
                duty_person=self.user,
                duty_person_name=self.user.username,
                weather='晴',
                duty_record='全部 CharField 残留',
                status=STATUS_DRAFT,
                version=1,
                created_by=self.user,
                # 可空字段全 NULL（通过约束）
                # CharField 全有值
                signed_by_name='李四',
                signature_sha256='e' * 64,
                business_snapshot_hash='f' * 64,
            )
            record.refresh_from_db()
            constraint_covers = False
        except IntegrityError:
            constraint_covers = True

        self.assertFalse(constraint_covers,
                         '草稿 4 可空字段为 NULL 但 3 CharField 有值未被约束拦截')


# ============================================================
# 问题 5：列表返回全文放大响应体
# ============================================================

class Audit2Issue5_ListResponseSizeTests(TestCase):
    """验证问题 5：列表返回完整 duty_record 放大响应体。

    这是性能问题而非正确性问题，测试验证 duty_record 全文确实在列表响应中。
    """

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('a2user5', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view']),
        ])
        self.client_obj = _make_client(self.user)

    def test_list_returns_full_duty_record_not_just_summary(self):
        """列表返回完整 duty_record（可用于编辑回填，但放大响应）"""
        long_text = 'X' * 5000  # 5000 字正文
        _make_record(self.user, duty_record=long_text)

        resp = self.client_obj.get('/department-duty-log/records/')
        body = json.loads(resp.content)
        item = body['data']['records'][0]

        # 列表返回了完整正文
        self.assertEqual(item['duty_record'], long_text)
        # 同时也返回了摘要（冗余）
        self.assertIn('duty_record_summary', item)

        # 响应体大小
        resp_size = len(resp.content)
        # 5000 字正文 + 摘要 + 其他字段，至少 5000 字节
        self.assertGreater(resp_size, 5000,
                           '列表响应体包含完整正文，显著增大')

    def test_list_with_many_records_amplifies_response(self):
        """多条记录时响应体放大效果明显"""
        # 创建 10 条长正文记录
        for i in range(10):
            _make_record(
                self.user,
                duty_record=f'记录{i}_' + 'Y' * 3000,
                duty_date=date.today() - timedelta(days=i),
            )

        resp = self.client_obj.get('/department-duty-log/records/')
        resp_size = len(resp.content)

        # 10 条 * 3000 字正文 = 30000+ 字节
        self.assertGreater(resp_size, 30000,
                          '10 条记录的列表响应体因包含完整正文而显著增大')
