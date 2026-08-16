# -*- coding: utf-8 -*-
"""合同协议模块冒烟测试"""
import json
import tempfile
from datetime import date, timedelta

from django.test import TestCase, override_settings

from apps.account.models import User
from apps.contract_agreement.models import ContractAgreement
from apps.utils.test_helpers import make_user, make_client, setup_test_env


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ContractAgreementSmokeTest(TestCase):
    URL = '/contract-agreement/'
    PERMS = ['contract_agreement.agreement.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('viewer', self.PERMS)
        self.noperm = make_user('noperm', [])
        self.c_auth = make_client(self.user)
        self.c_noperm = make_client(self.noperm)

    def test_list_ok(self):
        r = self.c_auth.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json().get('error'))

    def test_list_denied(self):
        r = self.c_noperm.get(self.URL)
        self.assertTrue(r.json().get('error'))


def _make_user_in_tenant(username, tenant_id):
    """创建指定租户的用户（make_user 不支持自定义租户）。"""
    import time
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=True, access_token=(username * 10)[:32],
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01', last_ip='127.0.0.1',
        type='default', tenant_id=tenant_id,
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ContractResponsibleUserValidationTests(TestCase):
    """合同协议责任人校验：跨租户拦截、软删拦截、姓名服务端回填、超管放行。

    覆盖创建与编辑两条路径（编辑此前完全不校验责任人）。
    """

    URL = '/contract-agreement/'

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('ct_resp_user', [
            'contract_agreement.agreement.view',
            'contract_agreement.agreement.add',
            'contract_agreement.agreement.edit',
        ])
        self.client = make_client(self.user)
        self.today = date.today()

    def _payload(self, **overrides):
        payload = {
            'contract_name': '责任人校验合同',
            'contract_type': 'service_guarantee',
            'valid_start_date': str(self.today - timedelta(days=30)),
            'valid_end_date': str(self.today + timedelta(days=300)),
            'signing_party': '责任校验对方单位',
            'responsible_user_id': self.user.id,
            'responsible_user_name': self.user.nickname,
            'has_fee': False,
        }
        payload.update(overrides)
        return payload

    def _post(self, payload):
        return self.client.post(
            self.URL, data=json.dumps(payload),
            content_type='application/json',
        ).json()

    def test_create_responsible_user_cross_tenant_rejected(self):
        """普通用户指定他租户用户为责任人：拒绝且不落库。"""
        other = _make_user_in_tenant('ct_resp_other', 't_ct_other')
        body = self._post(self._payload(
            responsible_user_id=other.id, responsible_user_name=other.nickname))
        self.assertEqual(body.get('error'), '责任人不存在或已禁用，请重新选择')
        self.assertFalse(
            ContractAgreement.objects.filter(contract_name='责任人校验合同').exists())

    def test_create_responsible_user_soft_deleted_rejected(self):
        """软删用户不得被指定为责任人。"""
        deleted_user = _make_user_in_tenant('ct_resp_deleted', 'admin')
        User.objects.filter(pk=deleted_user.id).update(deleted_by=self.user)
        body = self._post(self._payload(
            responsible_user_id=deleted_user.id,
            responsible_user_name=deleted_user.nickname))
        self.assertEqual(body.get('error'), '责任人不存在或已禁用，请重新选择')
        self.assertFalse(
            ContractAgreement.objects.filter(contract_name='责任人校验合同').exists())

    def test_responsible_user_name_filled_by_server_not_trusted(self):
        """客户端伪造 responsible_user_name：服务端回填真实姓名。"""
        body = self._post(self._payload(responsible_user_name='伪造的姓名'))
        self.assertFalse(body.get('error'), body)
        agreement = ContractAgreement.objects.get(contract_name='责任人校验合同')
        self.assertEqual(agreement.responsible_user_id, self.user.id)
        self.assertEqual(agreement.responsible_user_name, 'ct_resp_user')

    def test_supper_can_assign_cross_tenant_responsible_user(self):
        """超管可跨租户指定责任人，姓名仍由服务端回填。"""
        supper = make_user('ct_resp_supper', is_supper=True)
        client = make_client(supper)
        body = client.post(
            self.URL, data=json.dumps(self._payload()),
            content_type='application/json',
        ).json()
        self.assertFalse(body.get('error'), body)
        agreement = ContractAgreement.objects.get(contract_name='责任人校验合同')
        self.assertEqual(agreement.responsible_user_id, self.user.id)
        self.assertEqual(agreement.responsible_user_name, 'ct_resp_user')
        # 超管创建的合同归属超管所在租户
        self.assertEqual(agreement.tenant_id, 'admin')

    def _create_for_edit(self):
        body = self._post(self._payload(contract_name='责任人编辑合同'))
        self.assertFalse(body.get('error'), body)
        return ContractAgreement.objects.get(contract_name='责任人编辑合同')

    def test_edit_responsible_user_cross_tenant_rejected(self):
        """编辑时更换为他租户责任人被拦截，原记录不受影响。"""
        agreement = self._create_for_edit()
        other = _make_user_in_tenant('ct_resp_other2', 't_ct_other')
        body = self._post({'id': agreement.id, 'responsible_user_id': other.id})
        self.assertEqual(body.get('error'), '责任人不存在或已禁用，请重新选择')
        agreement.refresh_from_db()
        self.assertEqual(agreement.responsible_user_id, self.user.id)
        self.assertEqual(agreement.responsible_user_name, 'ct_resp_user')

    def test_edit_without_responsible_user_succeeds(self):
        """局部编辑不传责任人：不受新校验影响（回归保护）。"""
        agreement = self._create_for_edit()
        body = self._post({'id': agreement.id, 'remark': '仅改备注'})
        self.assertFalse(body.get('error'), body)
        agreement.refresh_from_db()
        self.assertEqual(agreement.remark, '仅改备注')
        self.assertEqual(agreement.responsible_user_id, self.user.id)
