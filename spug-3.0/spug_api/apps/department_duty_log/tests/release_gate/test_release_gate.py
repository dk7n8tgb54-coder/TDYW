# -*- coding: utf-8 -*-
"""部门值班日志 - 上线前发布门禁补充测试

分类：stable_contract（长期稳定的业务不变量，可纳入发布门禁）

本文件补足既有 222 项测试之外的发布门禁验证，重点覆盖：
- RG-A 权限矩阵：7 类权限 + 无权限账号 × 全部 11 个端点，后端真实拒绝
- RG-B 数据库完整性约束：CHECK 约束在 MariaDB 上真实生效
- RG-C 生命周期与证据链：签署 / 退回 / 重签的版本号与 void 事件
- RG-D HTTP 响应头：PDF 导出与签名图片
- RG-E 业务不变量端到端（服务端身份、软删除不可见）
- RG-F 签名图片越权
- RG-G PDF 导出边界与草稿泄露

所有断言均执行真实 Django 代码路径和数据库状态校验，不使用源码字符串匹配。
"""
import io
import json
import os
import shutil
import time
import uuid
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction, IntegrityError, connection
from django.test import TestCase, Client

from apps.account.models import User, Role
from apps.setting.utils import AppSetting
from apps.evidence.models import EvidenceEvent
from apps.signature.models import AccountSignature, SignatureUsage
from apps.signature import services as sig_services
from apps.department_duty_log.models import DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED
from apps.department_duty_log import services


# ============================================================
# 权限常量
# ============================================================

P_VIEW = 'department_duty_log.department_duty_log.view'
P_ADD = 'department_duty_log.department_duty_log.add'
P_EDIT = 'department_duty_log.department_duty_log.edit'
P_DEL = 'department_duty_log.department_duty_log.del'
P_SIGN = 'department_duty_log.department_duty_log.sign'
P_RETURN = 'department_duty_log.department_duty_log.return'
P_EXPORT = 'department_duty_log.department_duty_log.export'

ALL_PERMS = [P_VIEW, P_ADD, P_EDIT, P_DEL, P_SIGN, P_RETURN, P_EXPORT]

# _grant_perms 只能接收动作键（见 Role.page_perms 结构说明）
ALL_ACTIONS = ['view', 'add', 'edit', 'del', 'sign', 'return', 'export']


# ============================================================
# 测试辅助
# ============================================================

def _make_png(width=200, height=100, mode='RGBA'):
    from PIL import Image
    img = Image.new(mode, (width, height), (255, 0, 0, 128) if mode == 'RGBA' else (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _make_png_file(name='sig.png'):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, _make_png(), content_type='image/png')


def _make_user(username, is_supper=False, tenant_id='default'):
    token = (username * 10)[:32]
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=True, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return client


def _grant_perms(user, perm_keys):
    """授予用户 department_duty_log 模块的指定权限键。"""
    role_name = 'rg_role_%s' % user.username
    payload = {'department_duty_log': {'department_duty_log': list(perm_keys)}}
    role = Role.objects.filter(name=role_name).first()
    if role:
        role.page_perms = json.dumps(payload)
        role.save()
    else:
        role = Role.objects.create(name=role_name, page_perms=json.dumps(payload), created_by=user)
        user.roles.add(role)
    user.set_perms_cache()
    return role


def _make_record(user, **kwargs):
    """直接创建记录。signed 状态自动补齐满足 CHECK 约束的签署字段。"""
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


def _parse(resp):
    return json.loads(resp.content)


def _resp_json(resp):
    """解析响应体。签名图片越权拒绝返回 text/plain，需要区分处理。

    Returns:
        (is_json, payload)：payload 为 dict（JSON）或原始文本。
    """
    try:
        return True, json.loads(resp.content)
    except (ValueError, TypeError):
        return False, resp.content.decode('utf-8', 'ignore')


def _err(resp):
    """归一化业务错误：无错误返回 None（json_response 用空串表示成功）。"""
    is_json, payload = _resp_json(resp)
    if not is_json:
        return None
    return payload.get('error') or None


def _body(resp):
    """读取响应体字节。FileResponse 不支持 .content，需走 streaming_content。"""
    if hasattr(resp, 'streaming_content'):
        return b''.join(resp.streaming_content)
    return resp.content


# ============================================================
# RG-A 权限矩阵
# ============================================================

class PermissionMatrixReleaseGateTests(TestCase):
    """RG-A：7 类权限 + 无权限账号 × 全部端点，后端必须真实拒绝。

    不信任前端隐藏按钮：每个越权请求都直接打到后端并断言被拒绝。
    """

    # 端点名 -> (需要的动作键集合, 调用器)
    # 调用器签名：call(client, own_draft_id, own_signed_id)
    ENDPOINTS = {
        'GET_LIST': (
            {'view'},
            lambda c, d, s: c.get('/department-duty-log/records/'),
        ),
        'POST_CREATE': (
            {'add'},
            lambda c, d, s: c.post(
                '/department-duty-log/records/',
                data=json.dumps({
                    'duty_date': str(date.today()),
                    'weather': '晴',
                    'duty_record': '权限矩阵用例 %s' % uuid.uuid4().hex,
                }),
                content_type='application/json'),
        ),
        'GET_DETAIL': (
            {'view'},
            lambda c, d, s: c.get('/department-duty-log/records/%s/' % d),
        ),
        'PUT_EDIT': (
            {'edit'},
            lambda c, d, s: c.put(
                '/department-duty-log/records/%s/' % d,
                data=json.dumps({
                    'duty_date': str(date.today()),
                    'weather': '多云',
                    'duty_record': '编辑后的值班记录',
                    'version': 1,
                }),
                content_type='application/json'),
        ),
        'DELETE': (
            {'del'},
            lambda c, d, s: c.delete('/department-duty-log/records/%s/' % d),
        ),
        'POST_SIGN': (
            {'sign'},
            lambda c, d, s: c.post(
                '/department-duty-log/records/%s/sign/' % d,
                data=json.dumps({
                    'version': 1, 'confirm': True,
                    'request_id': 'rg-matrix-%s' % uuid.uuid4().hex,
                }),
                content_type='application/json'),
        ),
        'POST_RETURN': (
            {'return'},
            lambda c, d, s: c.post('/department-duty-log/records/%s/return/' % s),
        ),
        'GET_SIGIMG': (
            {'view'},
            lambda c, d, s: c.get('/department-duty-log/records/%s/signature-image/' % s),
        ),
        'POST_EXPORT': (
            {'export', 'view'},
            lambda c, d, s: c.post(
                '/department-duty-log/export/pdf/',
                data=json.dumps({}),
                content_type='application/json'),
        ),
        'GET_OPTIONS': (
            {'view'},
            lambda c, d, s: c.get('/department-duty-log/options/'),
        ),
        'GET_DATES': (
            {'view'},
            lambda c, d, s: c.get('/department-duty-log/records/duty_dates/?year=2026&month=1'),
        ),
    }

    # 注意：Role.page_perms 的 JSON 结构为 {module: {page: [动作键...]}}，
    # User.page_perms 会在读取时拼成 '<module>.<page>.<动作键>'，
    # 因此这里只能填动作键（view/add/...），不能填完整权限码。
    ACCOUNTS = {
        'none': [],
        'view': ['view'],
        'add': ['add'],
        'edit': ['edit'],
        'del': ['del'],
        'sign': ['sign'],
        'return': ['return'],
        'export': ['export'],
        'export_view': ['export', 'view'],
        'all': ['view', 'add', 'edit', 'del', 'sign', 'return', 'export'],
    }

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.accounts = {}
        for key, perms in self.ACCOUNTS.items():
            user = _make_user('rg_a_%s' % key, tenant_id='rg_tenant_%s' % key)
            if perms:
                _grant_perms(user, perms)
            else:
                # 显式建空角色，确保 page_perms 为空集合而非意外继承
                _grant_perms(user, [])
            self.accounts[key] = {
                'user': user,
                'client': _make_client(user),
                'perms': set(perms),
                # 每个账号都拥有属于自己的草稿与已签记录，
                # 这样拒绝原因只会是"权限"，不会混入"所有权"
                'draft': _make_record(user, duty_record='权限矩阵草稿 %s' % key),
                'signed': _make_record(user, status=STATUS_SIGNED,
                                       duty_record='权限矩阵已签 %s' % key),
            }

    def test_rg_a01_permission_matrix_backend_enforced(self):
        """RG-A01：无对应权限时后端一律拒绝，且数据库记录不被修改"""
        violations = []

        for acc_key, acc in self.accounts.items():
            for ep_name, (required, call) in self.ENDPOINTS.items():
                draft = acc['draft']
                signed = acc['signed']
                before_draft = DepartmentDutyLog.objects.get(pk=draft.id).to_dict()
                before_signed = DepartmentDutyLog.objects.get(pk=signed.id).to_dict()
                before_count = DepartmentDutyLog.objects.count()

                resp = call(acc['client'], draft.id, signed.id)
                allowed = required.issubset(acc['perms'])
                is_json, payload = _resp_json(resp)
                # 权限拒绝有两种文案：装饰器通用文案，
                # 以及导出端点"export 必须同时持有 view"的专用文案
                denied = (
                    is_json
                    and str(payload.get('error') or '').startswith('权限拒绝')
                )

                after_draft = DepartmentDutyLog.objects.get(pk=draft.id).to_dict()
                after_signed = DepartmentDutyLog.objects.get(pk=signed.id).to_dict()
                after_count = DepartmentDutyLog.objects.count()

                if allowed:
                    # 有权限：不得返回"权限拒绝"（可以是业务错误，也可以是非 JSON 流）
                    if denied:
                        violations.append(
                            'ALLOWED_BUT_DENIED %s/%s error=%s'
                            % (acc_key, ep_name, payload.get('error')))
                    # 有权限也不得产生服务器内部错误
                    if resp.status_code >= 500:
                        violations.append('SERVER_ERROR %s/%s' % (acc_key, ep_name))
                else:
                    if not denied:
                        violations.append(
                            'NOT_DENIED %s/%s status=%s body=%r'
                            % (acc_key, ep_name, resp.status_code, payload))
                    # 越权请求不得改动任何记录
                    if before_draft != after_draft:
                        violations.append('DRAFT_MUTATED %s/%s' % (acc_key, ep_name))
                    if before_signed != after_signed:
                        violations.append('SIGNED_MUTATED %s/%s' % (acc_key, ep_name))
                    if ep_name == 'POST_CREATE' and before_count != after_count:
                        violations.append('RECORD_CREATED %s/%s' % (acc_key, ep_name))
                    if ep_name == 'DELETE' and before_count != after_count:
                        violations.append('RECORD_DELETED %s/%s' % (acc_key, ep_name))

        self.assertEqual([], violations, '权限矩阵违规项：\n' + '\n'.join(violations))

    def test_rg_a02_export_requires_export_and_view(self):
        """RG-A02：导出必须同时持有 export 与 view，缺一不可"""
        # 仅 export：应被"需要查看权限"拒绝
        resp = self.accounts['export']['client'].post(
            '/department-duty-log/export/pdf/',
            data=json.dumps({}), content_type='application/json')
        self.assertEqual('权限拒绝：需要查看权限', _err(resp))

        # export + view：不再是权限错误（此处为空结果，返回业务错误）
        resp = self.accounts['export_view']['client'].post(
            '/department-duty-log/export/pdf/',
            data=json.dumps({}), content_type='application/json')
        self.assertNotEqual('权限拒绝', _err(resp))
        self.assertNotEqual('权限拒绝：需要查看权限', _err(resp))

    def test_rg_a03_no_permission_account_sees_nothing(self):
        """RG-A03：无权限账号所有端点均被拒绝（含只读端点）"""
        acc = self.accounts['none']
        for ep_name in ('GET_LIST', 'GET_DETAIL', 'GET_SIGIMG', 'GET_OPTIONS', 'GET_DATES'):
            required, call = self.ENDPOINTS[ep_name]
            resp = call(acc['client'], acc['draft'].id, acc['signed'].id)
            self.assertEqual('权限拒绝', _err(resp), '%s 应被拒绝' % ep_name)
            self.assertEqual(200, resp.status_code)

    def test_rg_a04_single_perm_does_not_grant_others(self):
        """RG-A04：单一权限不横向放行其它方法（add 账号不能查看/编辑/删除）"""
        acc = self.accounts['add']
        for ep_name in ('GET_LIST', 'GET_DETAIL', 'PUT_EDIT', 'DELETE', 'POST_SIGN',
                        'POST_RETURN', 'POST_EXPORT', 'GET_OPTIONS', 'GET_DATES'):
            required, call = self.ENDPOINTS[ep_name]
            resp = call(acc['client'], acc['draft'].id, acc['signed'].id)
            self.assertEqual('权限拒绝', _err(resp), '%s 应被拒绝' % ep_name)

        # add 账号唯一被放行的写操作是创建
        before = DepartmentDutyLog.objects.count()
        resp = self.ENDPOINTS['POST_CREATE'][1](acc['client'], acc['draft'].id, acc['signed'].id)
        self.assertIsNone(_err(resp), 'add 账号应可创建：%s' % _err(resp))
        self.assertEqual(before + 1, DepartmentDutyLog.objects.count())


# ============================================================
# RG-B 数据库完整性约束
# ============================================================

class DatabaseConstraintReleaseGateTests(TestCase):
    """RG-B：模型 CHECK 约束在数据库层真实生效，非法数据无法落库。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_b_owner', tenant_id='rg_b')

    def _assert_rejected(self, **kwargs):
        kwargs.setdefault('duty_person', self.user)
        kwargs.setdefault('created_by', self.user)
        kwargs.setdefault('duty_date', date.today())
        kwargs.setdefault('duty_person_name', self.user.nickname)
        kwargs.setdefault('weather', '晴')
        kwargs.setdefault('duty_record', '约束测试')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentDutyLog.objects.create(**kwargs)

    def test_rg_b01_constraints_exist_in_database(self):
        """RG-B01：三个 CHECK 约束真实存在于数据库（而非仅声明在模型）"""
        with connection.cursor() as c:
            c.execute("""
                SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tdyw_department_duty_log'
                  AND CONSTRAINT_TYPE = 'CHECK'
            """)
            names = {r[0] for r in c.fetchall()}
        for expected in ('duty_log_status_valid', 'duty_log_version_valid',
                         'duty_log_signature_fields'):
            self.assertIn(expected, names)

    def test_rg_b02_illegal_status_rejected(self):
        """RG-B02：非法 status 无法落库"""
        self._assert_rejected(status='archived', version=1)

    def test_rg_b03_version_zero_rejected(self):
        """RG-B03：version < 1 无法落库"""
        self._assert_rejected(status=STATUS_DRAFT, version=0)

    def test_rg_b04_draft_with_signature_fields_rejected(self):
        """RG-B04：草稿携带签署字段无法落库"""
        self._assert_rejected(
            status=STATUS_DRAFT, version=1,
            signature_usage_id=12345, signed_by=self.user,
            signed_by_name='x', signed_at='2026-01-01 00:00:00',
            signature_version=1, signature_sha256='a' * 64,
            business_snapshot_hash='b' * 64)

    def test_rg_b05_signed_without_signature_fields_rejected(self):
        """RG-B05：已签记录缺失签署字段无法落库"""
        self._assert_rejected(status=STATUS_SIGNED, version=1)

    def test_rg_b06_signed_by_must_equal_duty_person(self):
        """RG-B06：已签记录 signed_by 必须等于 duty_person"""
        other = _make_user('rg_b_other', tenant_id='rg_b')
        self._assert_rejected(
            status=STATUS_SIGNED, version=1,
            signature_usage_id=uuid.uuid4().int & ((1 << 63) - 1),
            signed_by=other, signed_by_name=other.nickname,
            signed_at='2026-01-01 00:00:00', signature_version=1,
            signature_sha256='a' * 64, business_snapshot_hash='b' * 64)

    def test_rg_b07_legal_records_accepted(self):
        """RG-B07：合法草稿与合法已签记录均可落库（约束不过严）"""
        draft = _make_record(self.user, status=STATUS_DRAFT)
        self.assertEqual(STATUS_DRAFT, DepartmentDutyLog.objects.get(pk=draft.id).status)
        signed = _make_record(self.user, status=STATUS_SIGNED)
        self.assertEqual(STATUS_SIGNED, DepartmentDutyLog.objects.get(pk=signed.id).status)

    def test_rg_b08_signature_usage_id_unique(self):
        """RG-B08：signature_usage_id 唯一，防止两条记录复用同一签署证据"""
        usage_id = uuid.uuid4().int & ((1 << 63) - 1)
        _make_record(self.user, status=STATUS_SIGNED, signature_usage_id=usage_id)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                _make_record(self.user, status=STATUS_SIGNED, signature_usage_id=usage_id,
                             duty_date=date.today() - timedelta(days=1))


# ============================================================
# RG-C 生命周期、版本号与证据链
# ============================================================

class LifecycleEvidenceReleaseGateTests(TestCase):
    """RG-C：签署 / 退回 / 重签的版本号、签署字段与证据事件一致性。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('rg_c_supper', is_supper=True, tenant_id='rg_c')
        self.supper_client = _make_client(self.supper)

        self.owner = _make_user('rg_c_owner', tenant_id='rg_c')
        _grant_perms(self.owner, ALL_ACTIONS)
        self.owner_client = _make_client(self.owner)

        self.admin = _make_user('rg_c_admin', tenant_id='rg_c')
        _grant_perms(self.admin, ['view', 'return'])
        self.admin_client = _make_client(self.admin)

        # 为 owner 配置签名（真实走签名上传接口）
        resp = self.supper_client.post(
            '/account/user/%s/signature/' % self.owner.id,
            {'file': _make_png_file(), 'remark': 'rg-c setup'})
        self.assertIsNone(_err(resp), '签名配置失败：%s' % _err(resp))
        self.sig = AccountSignature.objects.get(user_id=self.owner.id)

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _create_draft(self, text='生命周期草稿'):
        resp = self.owner_client.post(
            '/department-duty-log/records/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'weather': '晴',
                'duty_record': text,
            }),
            content_type='application/json')
        self.assertIsNone(_err(resp), _err(resp))
        return DepartmentDutyLog.objects.get(pk=_parse(resp)['data']['id'])

    def _sign(self, record):
        resp = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % record.id,
            data=json.dumps({
                'version': record.version, 'confirm': True,
                'request_id': 'rg-c-%s' % uuid.uuid4().hex,
            }),
            content_type='application/json')
        return resp

    def test_rg_c01_sign_bumps_version_and_freezes_signature(self):
        """RG-C01：签署成功 -> status=signed、version+1、签署字段完整且写入审计"""
        record = self._create_draft('RG-C01 签署前')
        v0 = record.version
        resp = self._sign(record)
        self.assertIsNone(_err(resp), _err(resp))

        record.refresh_from_db()
        self.assertEqual(STATUS_SIGNED, record.status)
        self.assertEqual(v0 + 1, record.version)
        self.assertIsNotNone(record.signature_usage_id)
        self.assertIsNotNone(record.signed_at)
        self.assertEqual(self.owner.id, record.signed_by_id)
        self.assertEqual(record.duty_person_id, record.signed_by_id)
        self.assertEqual(64, len(record.signature_sha256))
        self.assertEqual(64, len(record.business_snapshot_hash))
        self.assertEqual(self.sig.version, record.signature_version)

        usage = SignatureUsage.objects.get(pk=record.signature_usage_id)
        self.assertEqual('department_duty_log', usage.module)
        self.assertEqual('department_duty_log', usage.object_type)
        self.assertEqual(str(record.id), usage.object_id)
        self.assertEqual(self.owner.id, usage.signer_user_id)
        # 快照哈希与记录字段一致
        self.assertEqual(record.business_snapshot_hash, usage.business_snapshot_hash)
        self.assertEqual(record.signature_sha256, usage.signature_sha256)

    def test_rg_c02_sign_twice_rejected(self):
        """RG-C02：已签记录不可重复签署，且状态/版本不变"""
        record = self._create_draft('RG-C02')
        self.assertIsNone(_err(self._sign(record)), '首次签署应成功')
        record.refresh_from_db()
        snapshot = record.to_dict()

        resp = self._sign(record)
        self.assertIsNotNone(_err(resp), '重复签署应被拒绝')
        record.refresh_from_db()
        self.assertEqual(snapshot, record.to_dict(), '重复签署不得改变记录')

    def test_rg_c03_return_clears_signature_and_bumps_version(self):
        """RG-C03：退回 -> draft、签署字段清空、version+1，且写 void 证据事件"""
        record = self._create_draft('RG-C03')
        self.assertIsNone(_err(self._sign(record)), '签署应成功')
        record.refresh_from_db()
        usage_id = record.signature_usage_id
        v_signed = record.version

        resp = self.admin_client.post(
            '/department-duty-log/records/%s/return/' % record.id)
        self.assertIsNone(_err(resp), _err(resp))

        record.refresh_from_db()
        self.assertEqual(STATUS_DRAFT, record.status)
        self.assertEqual(v_signed + 1, record.version)
        self.assertIsNone(record.signature_usage_id)
        self.assertIsNone(record.signed_by_id)
        self.assertIsNone(record.signed_at)
        self.assertIsNone(record.signature_version)
        self.assertEqual('', record.signed_by_name)
        self.assertEqual('', record.signature_sha256)
        self.assertEqual('', record.business_snapshot_hash)

        voids = EvidenceEvent.objects.filter(
            module='department_duty_log', object_type='department_duty_log',
            object_id=str(record.id), event_type='void')
        self.assertEqual(1, voids.count(), '必须写入 1 条 void 证据事件')
        void = voids.first()
        self.assertEqual(self.admin.id, void.actor_user_id)
        self.assertEqual('void', void.event_type)
        snapshot = void.object_snapshot
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        self.assertEqual('管理员退回', snapshot.get('void_reason'),
                         'void 证据事件必须记录作废原因')
        self.assertEqual(usage_id, snapshot.get('signature_usage_id'))

        # SignatureUsage 未被修改（只追加 void 事件）
        self.assertTrue(SignatureUsage.objects.filter(pk=usage_id).exists())

    def test_rg_c04_full_draft_sign_return_resign_journey(self):
        """RG-C04：完整旅程 draft->signed->draft->signed 全程版本号与证据链单调一致"""
        record = self._create_draft('RG-C04')
        self.assertEqual(1, record.version)

        self.assertIsNone(_err(self._sign(record)))
        record.refresh_from_db()
        self.assertEqual((STATUS_SIGNED, 2), (record.status, record.version))
        first_usage = record.signature_usage_id

        self.assertIsNone(_err(self.admin_client.post(
            '/department-duty-log/records/%s/return/' % record.id)))
        record.refresh_from_db()
        self.assertEqual((STATUS_DRAFT, 3), (record.status, record.version))
        self.assertIsNone(record.signature_usage_id)

        self.assertIsNone(_err(self._sign(record)))
        record.refresh_from_db()
        self.assertEqual((STATUS_SIGNED, 4), (record.status, record.version))
        self.assertNotEqual(first_usage, record.signature_usage_id, '重签必须生成新 Usage')

        # 签名公共服务对"签署"事件固定写入 event_type='other'，作废写入 'void'
        events = list(
            EvidenceEvent.objects.filter(
                module='department_duty_log', object_type='department_duty_log',
                object_id=str(record.id))
            .order_by('id').values_list('event_type', flat=True))
        self.assertEqual(['other', 'void', 'other'], events)

    def test_rg_c05_signed_record_cannot_be_edited_or_deleted(self):
        """RG-C05：已签记录不可编辑、不可删除，数据库保持不变"""
        record = self._create_draft('RG-C05')
        self.assertIsNone(_err(self._sign(record)))
        record.refresh_from_db()
        snapshot = record.to_dict()

        resp = self.owner_client.put(
            '/department-duty-log/records/%s/' % record.id,
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '雨',
                'duty_record': '篡改已签记录', 'version': record.version,
            }),
            content_type='application/json')
        self.assertIsNotNone(_err(resp))
        record.refresh_from_db()
        self.assertEqual(snapshot, record.to_dict())

        resp = self.owner_client.delete('/department-duty-log/records/%s/' % record.id)
        self.assertIsNotNone(_err(resp))
        record.refresh_from_db()
        self.assertEqual(snapshot, record.to_dict())
        self.assertIsNone(record.deleted_at)

    def test_rg_c06_sign_requires_confirm_and_correct_version(self):
        """RG-C06：签署校验 confirm=true 与当前 version"""
        record = self._create_draft('RG-C06')

        resp = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % record.id,
            data=json.dumps({'version': 1, 'confirm': False}),
            content_type='application/json')
        self.assertEqual('请确认签署', _err(resp))

        resp = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % record.id,
            data=json.dumps({'version': 999, 'confirm': True}),
            content_type='application/json')
        self.assertIsNotNone(_err(resp))
        record.refresh_from_db()
        self.assertEqual(STATUS_DRAFT, record.status)

    def test_rg_c07_sign_idempotent_retry_same_request_id(self):
        """RG-C07：同 request_id 重试幂等，不同 request_id 重签被拒"""
        record = self._create_draft('RG-C07')
        req_id = 'rg-c07-idem'
        payload = json.dumps({'version': 1, 'confirm': True, 'request_id': req_id})

        r1 = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % record.id,
            data=payload, content_type='application/json')
        self.assertIsNone(_err(r1), _err(r1))
        record.refresh_from_db()
        usage_1 = record.signature_usage_id

        r2 = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % record.id,
            data=payload, content_type='application/json')
        self.assertIsNone(_err(r2), '同 request_id 重试应幂等成功')
        record.refresh_from_db()
        self.assertEqual(usage_1, record.signature_usage_id)
        self.assertEqual(2, record.version, '幂等重试不得再次递增版本号')

        r3 = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % record.id,
            data=json.dumps({'version': 1, 'confirm': True,
                             'request_id': 'rg-c07-other'}),
            content_type='application/json')
        self.assertIsNotNone(_err(r3), '不同 request_id 重复签署应被拒绝')
        record.refresh_from_db()
        self.assertEqual(usage_1, record.signature_usage_id)


# ============================================================
# RG-D HTTP 响应头
# ============================================================

class ResponseHeaderReleaseGateTests(TestCase):
    """RG-D：PDF 导出与签名图片的响应头合规。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('rg_d_supper', is_supper=True, tenant_id='rg_d')
        self.supper_client = _make_client(self.supper)

        self.owner = _make_user('rg_d_owner', tenant_id='rg_d')
        _grant_perms(self.owner, ALL_ACTIONS)
        self.owner_client = _make_client(self.owner)

        self.viewer = _make_user('rg_d_viewer', tenant_id='rg_d_other')
        _grant_perms(self.viewer, ['view'])
        self.viewer_client = _make_client(self.viewer)

        resp = self.supper_client.post(
            '/account/user/%s/signature/' % self.owner.id,
            {'file': _make_png_file(), 'remark': 'rg-d setup'})
        self.assertIsNone(_err(resp), _err(resp))

        self.record = _make_record(self.owner, duty_record='RG-D 已签记录')

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _do_sign(self):
        resp = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % self.record.id,
            data=json.dumps({
                'version': self.record.version, 'confirm': True,
                'request_id': 'rg-d-%s' % uuid.uuid4().hex,
            }),
            content_type='application/json')
        self.assertIsNone(_err(resp), _err(resp))
        self.record.refresh_from_db()

    def test_rg_d01_pdf_response_headers(self):
        """RG-D01：PDF 响应头合规（类型、中文文件名、长度、nosniff）"""
        self._do_sign()
        resp = self.owner_client.post(
            '/department-duty-log/export/pdf/',
            data=json.dumps({}), content_type='application/json')
        self.assertEqual(200, resp.status_code)
        self.assertEqual('application/pdf', resp['Content-Type'])
        self.assertIn('nosniff', resp['X-Content-Type-Options'])
        self.assertTrue(resp['Content-Disposition'].startswith('attachment'))
        self.assertIn("filename*=UTF-8''", resp['Content-Disposition'])
        self.assertIn('%E9%83%A8%E9%97%A8', resp['Content-Disposition'],
                      '中文文件名必须按 RFC 5987 编码')
        self.assertEqual(str(len(resp.content)), resp['Content-Length'])
        self.assertTrue(resp.content.startswith(b'%PDF-'), '必须是合法 PDF 字节流')

    def test_rg_d02_signature_image_response_headers(self):
        """RG-D02：签名图片响应头合规（png、nosniff、私有不缓存）"""
        self._do_sign()
        resp = self.owner_client.get(
            '/department-duty-log/records/%s/signature-image/' % self.record.id)
        self.assertEqual(200, resp.status_code)
        body = _body(resp)
        self.assertEqual('image/png', resp['Content-Type'])
        self.assertIn('nosniff', resp['X-Content-Type-Options'])
        self.assertIn('no-store', resp['Cache-Control'])
        self.assertIn('private', resp['Cache-Control'])
        self.assertEqual(str(len(body)), resp['Content-Length'])
        self.assertTrue(body.startswith(b'\x89PNG'), '必须是合法 PNG')


# ============================================================
# RG-E 业务不变量端到端
# ============================================================

class InvariantReleaseGateTests(TestCase):
    """RG-E：服务端身份决定、软删除不可见、乐观锁冲突。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('rg_e_owner', tenant_id='rg_e')
        _grant_perms(self.owner, ALL_ACTIONS)
        self.owner_client = _make_client(self.owner)

        self.other = _make_user('rg_e_other', tenant_id='rg_e_other')
        _grant_perms(self.other, ALL_ACTIONS)
        self.other_client = _make_client(self.other)

    def test_rg_e01_server_decides_identity_fields(self):
        """RG-E01：值班人员/创建人由服务端决定，客户端无法伪造"""
        resp = self.owner_client.post(
            '/department-duty-log/records/',
            data=json.dumps({
                'duty_date': str(date.today()),
                'weather': '晴',
                'duty_record': '身份字段测试',
                'duty_person': self.other.id,
                'duty_person_name': '伪造姓名',
                'created_by': self.other.id,
            }),
            content_type='application/json')
        self.assertIsNotNone(_err(resp), '伪造身份字段必须被拒绝')
        self.assertFalse(DepartmentDutyLog.objects.filter(duty_record='身份字段测试').exists())

        resp = self.owner_client.post(
            '/department-duty-log/records/',
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': '正常创建',
            }),
            content_type='application/json')
        self.assertIsNone(_err(resp), _err(resp))
        record = DepartmentDutyLog.objects.get(pk=_parse(resp)['data']['id'])
        self.assertEqual(self.owner.id, record.duty_person_id)
        self.assertEqual(self.owner.id, record.created_by_id)
        self.assertEqual(self.owner.nickname, record.duty_person_name)

    def test_rg_e02_soft_deleted_invisible_everywhere(self):
        """RG-E02：软删除记录不出现在列表、详情、duty_dates、导出筛选中"""
        record = _make_record(self.owner, duty_date=date(2026, 3, 15), status=STATUS_SIGNED)
        self.assertEqual(record.duty_person_id, record.signed_by_id)

        resp = self.owner_client.delete('/department-duty-log/records/%s/' % record.id)
        self.assertIsNotNone(_err(resp), '已签记录不可删除')

        draft = _make_record(self.owner, duty_date=date(2026, 3, 16),
                             duty_record='待软删除草稿')
        resp = self.owner_client.delete('/department-duty-log/records/%s/' % draft.id)
        self.assertIsNone(_err(resp), _err(resp))

        draft.refresh_from_db()
        self.assertIsNotNone(draft.deleted_at)
        self.assertEqual(self.owner.id, draft.deleted_by_id)
        self.assertTrue(DepartmentDutyLog.objects.filter(pk=draft.id).exists(),
                        '软删除必须保留数据库记录')

        # 列表
        body = _parse(self.owner_client.get('/department-duty-log/records/?page_size=100'))
        self.assertNotIn(draft.id, [r['id'] for r in body['data']['records']])
        # 详情
        resp = self.owner_client.get('/department-duty-log/records/%s/' % draft.id)
        self.assertEqual('记录不存在', _err(resp))
        # duty_dates（2026-03 只应有 3-15 的已签日期，3-16 的草稿已删除）
        body = _parse(self.owner_client.get(
            '/department-duty-log/records/duty_dates/?year=2026&month=3'))
        self.assertIn('2026-03-15', body['data']['dates'])
        self.assertNotIn('2026-03-16', body['data']['dates'])
        # 导出 QuerySet
        qs_ids = list(services._get_export_queryset(
            self.owner, {'start_date': date(2026, 3, 1), 'end_date': date(2026, 3, 31)}
        ).values_list('id', flat=True))
        self.assertNotIn(draft.id, qs_ids)
        self.assertIn(record.id, qs_ids)

    def test_rg_e03_optimistic_lock_conflict_preserves_data(self):
        """RG-E03：乐观锁冲突时不覆盖他人更新"""
        record = _make_record(self.owner, duty_record='原始内容')
        # 他人先更新（模拟并发）
        updated = DepartmentDutyLog.objects.filter(pk=record.id).update(
            duty_record='他人更新内容', version=2)
        self.assertEqual(1, updated)

        resp = self.owner_client.put(
            '/department-duty-log/records/%s/' % record.id,
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': '我的更新', 'version': 1,
            }),
            content_type='application/json')
        self.assertIsNotNone(_err(resp), '版本冲突必须被拒绝')
        record.refresh_from_db()
        self.assertEqual('他人更新内容', record.duty_record)
        self.assertEqual(2, record.version)

    def test_rg_e04_other_user_draft_fully_isolated(self):
        """RG-E04：他人草稿不可列表、详情、编辑、删除、签署"""
        draft = _make_record(self.owner, duty_record='他人不可见草稿')

        body = _parse(self.other_client.get('/department-duty-log/records/?page_size=100'))
        self.assertNotIn(draft.id, [r['id'] for r in body['data']['records']])

        self.assertEqual('记录不存在',
                         _err(self.other_client.get('/department-duty-log/records/%s/' % draft.id)))
        self.assertEqual('只能编辑本人草稿',
                         _err(self.other_client.put(
                             '/department-duty-log/records/%s/' % draft.id,
                             data=json.dumps({
                                 'duty_date': str(date.today()), 'weather': '晴',
                                 'duty_record': '越权编辑', 'version': 1}),
                             content_type='application/json')))
        self.assertEqual('只能删除本人草稿',
                         _err(self.other_client.delete('/department-duty-log/records/%s/' % draft.id)))
        self.assertEqual('只能签署本人草稿',
                         _err(self.other_client.post(
                             '/department-duty-log/records/%s/sign/' % draft.id,
                             data=json.dumps({
                                 'version': 1, 'confirm': True,
                                 'request_id': 'rg-e04'}),
                             content_type='application/json')))

        draft.refresh_from_db()
        self.assertEqual(STATUS_DRAFT, draft.status)
        self.assertIsNone(draft.deleted_at)
        self.assertEqual('他人不可见草稿', draft.duty_record)

    def test_rg_e05_signed_record_globally_visible_readonly(self):
        """RG-E05：已签记录跨租户可见，但非本人不可编辑/删除/签署"""
        signed = _make_record(self.owner, status=STATUS_SIGNED, duty_record='全局可见已签')

        resp = self.other_client.get('/department-duty-log/records/%s/' % signed.id)
        self.assertIsNone(_err(resp), _err(resp))
        body = _parse(resp)
        self.assertEqual('全局可见已签', body['data']['duty_record'])
        self.assertFalse(body['data']['can_edit'])
        self.assertFalse(body['data']['can_delete'])
        self.assertFalse(body['data']['can_sign'])

    def test_rg_e06_duty_person_and_signed_by_consistency(self):
        """RG-E06：全表 signed_by_id 必须等于 duty_person_id（数据完整性抽查）"""
        _make_record(self.owner, status=STATUS_SIGNED)
        _make_record(self.other, status=STATUS_SIGNED, duty_date=date.today() - timedelta(days=1))
        mismatched = [
            r.id for r in DepartmentDutyLog.objects.filter(status=STATUS_SIGNED)
            if r.signed_by_id != r.duty_person_id
        ]
        self.assertEqual([], mismatched)


# ============================================================
# RG-F 签名图片越权
# ============================================================

class SignatureImageAuthzReleaseGateTests(TestCase):
    """RG-F：签名图片只能读取可见且已签署的记录。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('rg_f_supper', is_supper=True, tenant_id='rg_f')
        self.supper_client = _make_client(self.supper)

        self.owner = _make_user('rg_f_owner', tenant_id='rg_f')
        _grant_perms(self.owner, ALL_ACTIONS)
        self.owner_client = _make_client(self.owner)

        self.stranger = _make_user('rg_f_stranger', tenant_id='rg_f_other')
        _grant_perms(self.stranger, ['view'])
        self.stranger_client = _make_client(self.stranger)

        self.noperm = _make_user('rg_f_noperm', tenant_id='rg_f_other')
        self.noperm_client = _make_client(self.noperm)

        resp = self.supper_client.post(
            '/account/user/%s/signature/' % self.owner.id,
            {'file': _make_png_file(), 'remark': 'rg-f setup'})
        self.assertIsNone(_err(resp), _err(resp))

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _create_and_sign(self, **kwargs):
        record = _make_record(self.owner, **kwargs)
        resp = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % record.id,
            data=json.dumps({
                'version': record.version, 'confirm': True,
                'request_id': 'rg-f-%s' % uuid.uuid4().hex,
            }),
            content_type='application/json')
        self.assertIsNone(_err(resp), _err(resp))
        record.refresh_from_db()
        return record

    def test_rg_f01_draft_signature_image_rejected(self):
        """RG-F01：草稿（未签署）不允许读取签名图片"""
        draft = _make_record(self.owner)
        resp = self.owner_client.get(
            '/department-duty-log/records/%s/signature-image/' % draft.id)
        self.assertEqual(403, resp.status_code)
        self.assertEqual('该记录未签署', resp.content.decode('utf-8'))

    def test_rg_f02_soft_deleted_signed_image_rejected(self):
        """RG-F02：软删除的已签记录不可读取签名图片"""
        record = self._create_and_sign()
        DepartmentDutyLog.objects.filter(pk=record.id).update(
            deleted_at='2026-01-01 00:00:00')
        resp = self.owner_client.get(
            '/department-duty-log/records/%s/signature-image/' % record.id)
        self.assertEqual(403, resp.status_code)

    def test_rg_f03_no_view_permission_rejected(self):
        """RG-F03：无 view 权限账号读取签名图片被拒绝"""
        record = self._create_and_sign()
        resp = self.noperm_client.get(
            '/department-duty-log/records/%s/signature-image/' % record.id)
        self.assertEqual(200, resp.status_code)
        self.assertEqual('权限拒绝', _err(resp))

    def test_rg_f04_signed_image_readable_by_other_viewer(self):
        """RG-F04：已签记录全局可见，跨租户有 view 权限者可读取签名图"""
        record = self._create_and_sign()
        resp = self.stranger_client.get(
            '/department-duty-log/records/%s/signature-image/' % record.id)
        self.assertEqual(200, resp.status_code)
        self.assertTrue(_body(resp).startswith(b'\x89PNG'))

    def test_rg_f05_nonexistent_record_rejected(self):
        """RG-F05：不存在的记录读取签名图片被拒绝且不产生 500"""
        resp = self.owner_client.get('/department-duty-log/records/99999999/signature-image/')
        self.assertEqual(403, resp.status_code)

    def test_rg_f06_tampered_usage_id_rejected(self):
        """RG-F06：篡改 signature_usage_id 后读取签名图片被拒绝"""
        record = self._create_and_sign()
        DepartmentDutyLog.objects.filter(pk=record.id).update(
            signature_usage_id=record.signature_usage_id + 1)
        resp = self.owner_client.get(
            '/department-duty-log/records/%s/signature-image/' % record.id)
        self.assertEqual(403, resp.status_code)
        self.assertNotIn('Traceback', resp.content.decode('utf-8'))


# ============================================================
# RG-G PDF 导出边界与草稿泄露
# ============================================================

class PdfExportBoundaryReleaseGateTests(TestCase):
    """RG-G：PDF 只导出可见已签记录，绝不导出草稿或软删除记录。"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('rg_g_supper', is_supper=True, tenant_id='rg_g')
        self.supper_client = _make_client(self.supper)

        self.owner = _make_user('rg_g_owner', tenant_id='rg_g')
        _grant_perms(self.owner, ALL_ACTIONS)
        self.owner_client = _make_client(self.owner)

        resp = self.supper_client.post(
            '/account/user/%s/signature/' % self.owner.id,
            {'file': _make_png_file(), 'remark': 'rg-g setup'})
        self.assertIsNone(_err(resp), _err(resp))

    def tearDown(self):
        sig_base = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sig_base):
            shutil.rmtree(sig_base, ignore_errors=True)

    def _create_and_sign(self, duty_record, duty_date=None):
        record = _make_record(self.owner, duty_record=duty_record,
                              duty_date=duty_date or date.today())
        resp = self.owner_client.post(
            '/department-duty-log/records/%s/sign/' % record.id,
            data=json.dumps({
                'version': record.version, 'confirm': True,
                'request_id': 'rg-g-%s' % uuid.uuid4().hex,
            }),
            content_type='application/json')
        self.assertIsNone(_err(resp), _err(resp))
        record.refresh_from_db()
        return record

    def _export(self, payload=None):
        return self.owner_client.post(
            '/department-duty-log/export/pdf/',
            data=json.dumps(payload or {}), content_type='application/json')

    def test_rg_g01_draft_never_in_pdf_bytes(self):
        """RG-G01：PDF 字节流中不含草稿正文（含正向对照，防止压缩导致假阴性）"""
        # 关闭 PDF 流压缩，使正文可被字节检索
        import reportlab.rl_config
        original = reportlab.rl_config.pageCompression
        reportlab.rl_config.pageCompression = 0
        try:
            signed = self._create_and_sign('RG_G01_SIGNED_SENTINEL_%s' % uuid.uuid4().hex[:8])
            draft = _make_record(self.owner,
                                 duty_record='RG_G01_DRAFT_SENTINEL_%s' % uuid.uuid4().hex[:8])

            resp = self._export({})
            self.assertEqual(200, resp.status_code)

            # 正向对照：已签记录正文必须出现在 PDF 中，证明检索有效
            self.assertIn(signed.duty_record.encode('utf-8'), resp.content,
                          'PDF 未包含已签记录正文，字节检索无效（可能仍被压缩）')
            # 反向断言：草稿正文绝不能出现
            self.assertNotIn(draft.duty_record.encode('utf-8'), resp.content,
                             'PDF 泄露了草稿内容')
            self.assertNotIn(b'RG_G01_DRAFT_SENTINEL', resp.content)
        finally:
            reportlab.rl_config.pageCompression = original

    def test_rg_g02_soft_deleted_never_in_pdf(self):
        """RG-G02：软删除记录不进入导出"""
        record = self._create_and_sign('RG_G02_%s' % uuid.uuid4().hex[:8])
        resp = self._export({})
        self.assertEqual(200, resp.status_code)
        self.assertIn(record.id, self._exported_ids())

        DepartmentDutyLog.objects.filter(pk=record.id).update(
            deleted_at='2026-01-01 00:00:00')
        exported = self._exported_ids()
        self.assertNotIn(record.id, exported)

    def _exported_ids(self):
        from apps.department_duty_log import services as svc
        return list(svc._get_export_queryset(self.owner, {}).values_list('id', flat=True))

    def test_rg_g03_empty_result_returns_business_error(self):
        """RG-G03：无可导出记录时返回业务错误而非 500 或空 PDF

        导出端点遵循全项目公共导出约定：错误为 JSON + HTTP 400
        （libs/export_utils.build_export_error_response），
        前端 exportFile 依赖 http 拦截器解析该 JSON 并提示。
        """
        resp = self._export({})
        self.assertEqual(400, resp.status_code)
        self.assertEqual('当前筛选条件下没有可导出的已签记录', _err(resp))
        self.assertNotIn('Traceback', _body(resp).decode('utf-8', 'ignore'))

    def test_rg_g04_reversed_date_range_rejected(self):
        """RG-G04：日期区间反转被拒绝"""
        resp = self._export({'start_date': '2026-05-01', 'end_date': '2026-04-01'})
        self.assertEqual(400, resp.status_code)
        self.assertEqual('结束日期不能早于开始日期', _err(resp))

    def test_rg_g05_special_chars_and_boundary_filters(self):
        """RG-G05：特殊字符、超长筛选、边界日期均不产生 500"""
        self._create_and_sign('RG_G05_%s' % uuid.uuid4().hex[:8], duty_date=date(2026, 1, 1))
        cases = [
            {'keyword': '%%%___\\"\''},
            {'keyword': 'x' * 101},
            {'duty_person_name': 'y' * 101},
            {'start_date': '1899-01-01'},
            {'start_date': '9999-12-31', 'end_date': '9999-12-31'},
            {'start_date': 'not-a-date'},
            {'keyword': '<script>alert(1)</script>'},
        ]
        for payload in cases:
            resp = self._export(payload)
            # 导出成功为 200（PDF 流），业务错误为 400（JSON）；两者都不得是 5xx
            self.assertIn(resp.status_code, (200, 400), 'payload=%r' % payload)
            self.assertNotIn('Traceback', _body(resp).decode('utf-8', 'ignore'))
            if resp.status_code == 200:
                self.assertTrue(_body(resp).startswith(b'%PDF-'))

    def test_rg_g06_export_audit_matches_records(self):
        """RG-G06：导出审计记录与实际导出记录一致"""
        from apps.logs.models import AuditLog
        a = self._create_and_sign('RG_G06_A_%s' % uuid.uuid4().hex[:8],
                                  duty_date=date(2026, 2, 1))
        b = self._create_and_sign('RG_G06_B_%s' % uuid.uuid4().hex[:8],
                                  duty_date=date(2026, 2, 2))
        resp = self._export({'start_date': '2026-02-01', 'end_date': '2026-02-28'})
        self.assertEqual(200, resp.status_code)

        logs = AuditLog.objects.filter(target_type='department_duty_log',
                                       action='export').order_by('-id')
        self.assertTrue(logs.exists(), '导出必须写审计日志')
        detail = logs.first().detail
        if isinstance(detail, str):
            detail = json.loads(detail)
        self.assertEqual(2, detail['record_count'])
        self.assertEqual({a.id, b.id}, set(detail['record_ids']))
        self.assertEqual(64, len(detail['pdf_sha256']))
        import hashlib
        self.assertEqual(hashlib.sha256(resp.content).hexdigest(), detail['pdf_sha256'],
                         '审计中的 PDF SHA256 必须与实际响应一致')
