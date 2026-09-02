# -*- coding: utf-8 -*-
"""合同协议稳定契约测试公共夹具。"""
import json
import os
import tempfile
import time
from datetime import date, timedelta
from urllib.parse import urlencode

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings

from apps.account.models import User
from apps.contract_agreement.models import ContractAgreement
from apps.utils.test_helpers import setup_test_env

# 模块全部权限码
PERM_VIEW = 'contract_agreement.agreement.view'
PERM_ADD = 'contract_agreement.agreement.add'
PERM_EDIT = 'contract_agreement.agreement.edit'
PERM_DEL = 'contract_agreement.agreement.del'
PERM_UPLOAD = 'contract_agreement.attachment.upload'
PERM_DOWNLOAD = 'contract_agreement.attachment.download'
PERM_ATTACH_DEL = 'contract_agreement.attachment.delete'

ALL_PERMS = [PERM_VIEW, PERM_ADD, PERM_EDIT, PERM_DEL,
             PERM_UPLOAD, PERM_DOWNLOAD, PERM_ATTACH_DEL]

CONTRACT_TYPES = ('device_purchase', 'info_access', 'service_guarantee')


def make_user(username, perms=None, tenant_id='admin', is_supper=False, nickname=None):
    """创建指定租户/权限的测试用户。"""
    user = User.objects.create(
        username=username,
        nickname=nickname or username,
        password_hash='x',
        is_active=True,
        is_supper=is_supper,
        access_token=(username * 10)[:32],
        token_expired=int(time.time()) + 3600,
        last_login=None,
        last_ip='127.0.0.1',
        type='default',
        tenant_id=tenant_id,
    )
    if not is_supper:
        user.set_perms_cache(set(perms or []), version=0)
    return user


def make_client(user):
    from django.test import Client
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


def make_agreement(created_by, tenant_id='admin', **kwargs):
    """直接落库创建合同协议（绕过接口，用于准备测试数据）。"""
    defaults = dict(
        contract_name='测试合同',
        contract_no='',
        contract_type='service_guarantee',
        valid_start_date=date.today() - timedelta(days=10),
        valid_end_date=date.today() + timedelta(days=100),
        has_fee=False,
        fee_amount=None,
        fee_currency='人民币',
        fee_detail='',
        signing_party='某某签约单位',
        responsible_user_id=created_by.id if created_by else None,
        responsible_user_name=created_by.nickname if created_by else '',
        status='normal',
        remark='',
        tenant_id=tenant_id,
        created_by=created_by,
    )
    defaults.update(kwargs)
    return ContractAgreement.objects.create(**defaults)


def set_created_at(agreement, when):
    """auto_now_add 字段需用 update 绕过。"""
    ContractAgreement.objects.filter(pk=agreement.pk).update(created_at=when)
    agreement.refresh_from_db()
    return agreement


def build_payload(responsible_user, **overrides):
    payload = {
        'contract_name': '上线前测试合同',
        'contract_type': 'service_guarantee',
        'valid_start_date': str(date.today() - timedelta(days=5)),
        'valid_end_date': str(date.today() + timedelta(days=200)),
        'signing_party': '测试签约方',
        'responsible_user_id': responsible_user.id,
        'responsible_user_name': responsible_user.nickname,
        'has_fee': False,
    }
    payload.update(overrides)
    return payload


def upload_file(name, content=b'contract attachment content', content_type='application/pdf'):
    return SimpleUploadedFile(name, content, content_type=content_type)


class ContractTestMixin(object):
    """合同协议测试夹具：请求封装 + 常用断言。

    子类需自行叠加 TestCase / TransactionTestCase，
    MEDIA_ROOT 覆盖在子类上声明（override_settings 只能装饰 SimpleTestCase 子类）。
    """

    URL = '/contract-agreement/'

    def setUp(self):
        setup_test_env(self)
        self.today = date.today()
        self.user = make_user('qa_full', ALL_PERMS)
        self.client = make_client(self.user)
        self.other_tenant_user = make_user('qa_other_tenant', ALL_PERMS, tenant_id='t_other')
        self.other_client = make_client(self.other_tenant_user)

    # ---------- 请求封装 ----------
    def get_json(self, url, params=None, client=None):
        resp = (client or self.client).get(url, params or {})
        return self._decode(resp)

    def post_json(self, payload, client=None, url=None):
        resp = (client or self.client).post(
            url or self.URL, data=json.dumps(payload), content_type='application/json')
        return self._decode(resp)

    def delete_json(self, params, client=None, url=None):
        """DELETE 参数走 query string（后端 DELETE 视图解析 request.GET）。"""
        target = url or self.URL
        if params:
            target = f'{target}?{urlencode(params)}'
        resp = (client or self.client).delete(target)
        return self._decode(resp)

    def delete_attachment(self, att_id, client=None, reason=None):
        params = {'id': att_id}
        if reason is not None:
            params['delete_reason'] = reason
        target = f'/contract-agreement/attachments/?{urlencode(params)}'
        resp = (client or self.client).delete(target)
        return self._decode(resp)

    def upload(self, pk, file_obj, client=None, extra=None):
        data = {'file': file_obj}
        data.update(extra or {})
        resp = (client or self.client).post(f'{self.URL}{pk}/attachments/', data)
        return self._decode(resp)

    @staticmethod
    def _decode(resp):
        # 流式响应（FileResponse）说明请求被放行并返回了文件流，而非 JSON 业务错误
        if resp.streaming:
            return {'_status': resp.status_code, '_streaming': True,
                    '_content_type': resp.get('Content-Type', '')}
        if resp.status_code != 200:
            return {'_status': resp.status_code}
        try:
            return resp.json()
        except Exception:
            return {'_raw': resp.content[:500].decode('utf-8', 'replace')}

    # ---------- 常用断言 ----------
    def assertBusinessError(self, body, msg=None):
        self.assertTrue(body.get('error'), msg or f'期望业务错误，实际响应: {body}')

    def assertNoError(self, body, msg=None):
        self.assertFalse(body.get('error'), msg or f'期望成功，实际响应: {body}')

    def create_via_api(self, **overrides):
        """通过接口创建合同，返回响应体。"""
        return self.post_json(build_payload(self.user, **overrides))

    def media_path(self, *parts):
        from django.conf import settings
        return os.path.join(settings.MEDIA_ROOT, *parts)

    @staticmethod
    def response_bytes(resp):
        """统一读取响应体（兼容 FileResponse 流式响应）。"""
        return b''.join(resp.streaming_content) if resp.streaming else resp.content


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='contract_qa_'))
class ContractTestCase(ContractTestMixin, TestCase):
    """默认基类：事务内测试，适用于不依赖 on_commit 回调的场景。"""


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='contract_qa_'))
class ContractTransactionTestCase(ContractTestMixin, TransactionTestCase):
    """事务外测试：用于验证 transaction.on_commit 触发的物理文件副作用。"""
