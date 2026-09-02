# -*- coding: utf-8 -*-
"""权限与租户隔离稳定契约测试。

原则：后端必须独立校验权限，不能依赖前端隐藏按钮。
"""
from datetime import timedelta

from apps.contract_agreement.models import ContractAgreement
from .base import (ContractTestCase, build_payload, make_agreement, make_user,
                   make_client, upload_file,
                   PERM_VIEW, PERM_ADD, PERM_EDIT, PERM_DEL,
                   PERM_UPLOAD, PERM_DOWNLOAD, PERM_ATTACH_DEL)

POPUP_URL = '/contract-agreement/reminders/popup/'
ACK_URL = '/contract-agreement/reminders/ack/'
BADGE_URL = '/contract-agreement/badge/'
RESP_USERS_URL = '/contract-agreement/responsible-users/'


class NoPermissionTest(ContractTestCase):
    """无权限用户访问所有接口必须被拒绝"""

    def setUp(self):
        super().setUp()
        self.noperm = make_user('qa_noperm', [])
        self.np = make_client(self.noperm)
        self.ag = make_agreement(self.user, contract_name='权限基线合同',
                                 tenant_id='admin')
        up = self.upload(self.ag.id, upload_file('perm.pdf', b'perm'))
        self.att_id = up['data']['id']

    def test_list_denied(self):
        body = self.get_json(self.URL, client=self.np)
        self.assertBusinessError(body)
        self.assertIn('权限拒绝', body['error'])

    def test_detail_denied(self):
        self.assertBusinessError(self.get_json(f'{self.URL}{self.ag.id}/', client=self.np))

    def test_create_denied(self):
        body = self.post_json(build_payload(self.noperm, contract_name='无权限新增'),
                              client=self.np)
        self.assertBusinessError(body)
        self.assertFalse(ContractAgreement.objects.filter(
            contract_name='无权限新增').exists())

    def test_edit_denied(self):
        body = self.post_json({'id': self.ag.id, 'contract_name': '无权限编辑'},
                              client=self.np)
        self.assertBusinessError(body)
        self.ag.refresh_from_db()
        self.assertEqual(self.ag.contract_name, '权限基线合同')

    def test_delete_denied(self):
        body = self.delete_json({'id': self.ag.id}, client=self.np)
        self.assertBusinessError(body)
        self.assertTrue(ContractAgreement.objects.filter(pk=self.ag.id).exists())

    def test_attachment_list_denied(self):
        self.assertBusinessError(
            self.get_json(f'{self.URL}{self.ag.id}/attachments/', client=self.np))

    def test_attachment_upload_denied(self):
        body = self.upload(self.ag.id, upload_file('x.pdf', b'x'), client=self.np)
        self.assertBusinessError(body)

    def test_attachment_download_denied(self):
        resp = (self.np).get(f'{self.URL}attachments/{self.att_id}/download/')
        body = self._decode(resp)
        self.assertTrue(body.get('error'), f'无下载权限应被拒绝: {body}')

    def test_attachment_delete_denied(self):
        body = self.delete_attachment(self.att_id, client=self.np)
        self.assertTrue(body.get('error'), f'无删除附件权限应被拒绝: {body}')
        from apps.evidence.models import EvidenceAttachment
        self.assertFalse(EvidenceAttachment.objects.filter(pk=self.att_id).first().is_deleted)

    def test_reminder_popup_denied(self):
        self.assertBusinessError(self.get_json(POPUP_URL, client=self.np))

    def test_reminder_ack_denied(self):
        self.assertBusinessError(
            self.post_json({'agreement_id': self.ag.id}, url=ACK_URL, client=self.np))

    def test_badge_denied(self):
        self.assertBusinessError(self.get_json(BADGE_URL, client=self.np))

    def test_responsible_users_denied(self):
        self.assertBusinessError(self.get_json(RESP_USERS_URL, client=self.np))


class GranularPermissionTest(ContractTestCase):
    """按权限细分：仅查看 / 可新增 / 可编辑 / 可删除 / 附件权限"""

    def test_view_only_cannot_write(self):
        viewer = make_user('qa_viewer', [PERM_VIEW])
        vc = make_client(viewer)
        ag = make_agreement(self.user, contract_name='只读基线')
        self.assertNoError(self.get_json(self.URL, client=vc))

        self.assertBusinessError(
            self.post_json(build_payload(viewer, contract_name='只读新增'), client=vc))
        self.assertBusinessError(
            self.post_json({'id': ag.id, 'contract_name': '只读编辑'}, client=vc))
        self.assertBusinessError(self.delete_json({'id': ag.id}, client=vc))
        self.assertBusinessError(
            self.upload(ag.id, upload_file('v.pdf', b'v'), client=vc))

    def test_add_only_cannot_edit(self):
        adder = make_user('qa_adder', [PERM_VIEW, PERM_ADD])
        ac = make_client(adder)
        created = self.post_json(build_payload(adder, contract_name='新增权限合同'),
                                 client=ac)
        self.assertNoError(created)
        pk = created['data']['id']
        body = self.post_json({'id': pk, 'contract_name': '新增者编辑'}, client=ac)
        self.assertBusinessError(body)
        self.assertIn('编辑', body['error'])
        self.assertEqual(
            ContractAgreement.objects.get(pk=pk).contract_name, '新增权限合同')

    def test_edit_perm_can_edit(self):
        editor = make_user('qa_editor', [PERM_VIEW, PERM_EDIT])
        ec = make_client(editor)
        ag = make_agreement(self.user, contract_name='待编辑')
        body = self.post_json({'id': ag.id, 'contract_name': '已编辑'}, client=ec)
        self.assertNoError(body)
        self.assertEqual(
            ContractAgreement.objects.get(pk=ag.id).contract_name, '已编辑')

    def test_edit_perm_cannot_create(self):
        editor = make_user('qa_editor2', [PERM_VIEW, PERM_EDIT])
        ec = make_client(editor)
        body = self.post_json(build_payload(editor, contract_name='编辑者新增'),
                              client=ec)
        self.assertBusinessError(body)
        self.assertIn('新增', body['error'])

    def test_del_perm_can_delete(self):
        deleter = make_user('qa_deleter', [PERM_VIEW, PERM_DEL])
        dc = make_client(deleter)
        ag = make_agreement(self.user, contract_name='待删除', tenant_id='admin')
        self.assertNoError(self.delete_json({'id': ag.id}, client=dc))
        self.assertFalse(ContractAgreement.objects.filter(pk=ag.id).exists())

    def test_attachment_perms_are_independent(self):
        """上传 / 下载 / 删除附件权限必须各自独立生效"""
        base = make_agreement(self.user, contract_name='附件权限基线')
        uploader = make_user('qa_uploader', [PERM_VIEW, PERM_UPLOAD])
        uc = make_client(uploader)
        up = self.upload(base.id, upload_file('u.pdf', b'u'), client=uc)
        self.assertNoError(up)
        att_id = up['data']['id']

        # 有上传权但无下载权 -> 下载应被拒
        resp = uc.get(f'{self.URL}attachments/{att_id}/download/')
        self.assertTrue(self._decode(resp).get('error'),
                        '缺少 attachment.download 权限时下载必须被拒绝')

        downloader = make_user('qa_downloader', [PERM_VIEW, PERM_DOWNLOAD])
        dc = make_client(downloader)
        resp = dc.get(f'{self.URL}attachments/{att_id}/download/')
        self.assertEqual(resp.status_code, 200, '有下载权限应可下载')
        self.assertIn(b'u', self.response_bytes(resp))


class CrossTenantTest(ContractTestCase):
    """跨租户越权"""

    def setUp(self):
        super().setUp()
        self.victim_user = make_user('qa_victim', tenant_id='t_victim')
        self.victim_ag = make_agreement(self.victim_user, contract_name='他租户机密合同',
                                        tenant_id='t_victim')
        self.attacker = make_user('qa_attacker', [PERM_VIEW], tenant_id='t_attack')
        self.ac = make_client(self.attacker)

    def test_cross_tenant_detail_denied(self):
        body = self.get_json(f'{self.URL}{self.victim_ag.id}/', client=self.ac)
        self.assertBusinessError(body)

    def test_cross_tenant_edit_denied(self):
        body = self.post_json({'id': self.victim_ag.id, 'contract_name': '越权改名'},
                              client=self.ac)
        self.assertBusinessError(body)
        self.victim_ag.refresh_from_db()
        self.assertEqual(self.victim_ag.contract_name, '他租户机密合同')

    def test_cross_tenant_delete_denied(self):
        body = self.delete_json({'id': self.victim_ag.id}, client=self.ac)
        self.assertBusinessError(body)
        self.assertTrue(ContractAgreement.objects.filter(pk=self.victim_ag.id).exists())

    def test_cross_tenant_attachment_list_and_upload_denied(self):
        self.assertBusinessError(
            self.get_json(f'{self.URL}{self.victim_ag.id}/attachments/', client=self.ac))
        self.assertBusinessError(
            self.upload(self.victim_ag.id, upload_file('a.pdf', b'a'), client=self.ac))

    def test_cross_tenant_reminder_ack_denied(self):
        body = self.post_json({'agreement_id': self.victim_ag.id}, url=ACK_URL,
                              client=self.ac)
        self.assertBusinessError(body)

    def test_cross_tenant_popup_empty(self):
        make_agreement(self.victim_user, contract_name='他租户到期合同',
                       tenant_id='t_victim',
                       valid_end_date=self.today - timedelta(days=1),
                       responsible_user_id=self.attacker.id)
        body = self.get_json(POPUP_URL, client=self.ac)
        self.assertNoError(body)
        self.assertEqual(body['data']['records'], [],
                         '提醒弹窗不得返回其他租户的合同')

    def test_superuser_cross_tenant_allowed_by_design(self):
        supper = make_user('qa_supper_cross', is_supper=True)
        sc = make_client(supper)
        body = self.get_json(f'{self.URL}{self.victim_ag.id}/', client=sc)
        self.assertNoError(body, '超管跨租户访问为产品设计')


class ResponsibleUserScopeTest(ContractTestCase):
    """责任人选择与服务端姓名回填"""

    def test_responsible_users_scoped_to_tenant(self):
        make_user('qa_same_tenant', [PERM_VIEW], tenant_id='admin', nickname='同租户用户')
        make_user('qa_other_scope', [PERM_VIEW], tenant_id='t_scope', nickname='他租户用户')
        body = self.get_json(RESP_USERS_URL)
        self.assertNoError(body)
        usernames = [u['username'] for u in body['data']]
        self.assertIn('qa_same_tenant', usernames)
        self.assertNotIn('qa_other_scope', usernames)

    def test_superuser_responsible_users_all_tenants(self):
        make_user('qa_scope_other2', [PERM_VIEW], tenant_id='t_scope2')
        supper = make_user('qa_supper_scope', is_supper=True)
        body = self.get_json(RESP_USERS_URL, client=make_client(supper))
        usernames = [u['username'] for u in body['data']]
        self.assertIn('qa_scope_other2', usernames)

    def test_cannot_assign_cross_tenant_responsible_user(self):
        outsider = make_user('qa_outsider', [PERM_VIEW], tenant_id='t_out')
        body = self.post_json(build_payload(self.user,
                                            responsible_user_id=outsider.id,
                                            responsible_user_name=outsider.nickname))
        self.assertBusinessError(body)
        self.assertFalse(ContractAgreement.objects.filter(
            responsible_user_id=outsider.id).exists())

    def test_cannot_assign_inactive_responsible_user(self):
        inactive = make_user('qa_inactive', [PERM_VIEW], tenant_id='admin')
        inactive.is_active = False
        inactive.save(update_fields=['is_active'])
        body = self.post_json(build_payload(self.user,
                                            responsible_user_id=inactive.id,
                                            responsible_user_name=inactive.nickname))
        self.assertBusinessError(body)

    def test_cannot_assign_soft_deleted_responsible_user(self):
        from apps.account.models import User
        deleted = make_user('qa_deleted_user', [PERM_VIEW], tenant_id='admin')
        User.objects.filter(pk=deleted.pk).update(deleted_by=self.user)
        body = self.post_json(build_payload(self.user,
                                            responsible_user_id=deleted.id,
                                            responsible_user_name=deleted.nickname))
        self.assertBusinessError(body)

    def test_superuser_may_assign_cross_tenant_responsible_user(self):
        supper = make_user('qa_supper_assign', is_supper=True)
        sc = make_client(supper)
        outsider = make_user('qa_outsider2', [PERM_VIEW], tenant_id='t_out2',
                             nickname='跨租户责任人')
        body = self.post_json(build_payload(supper,
                                            contract_name='超管跨租户责任人合同',
                                            responsible_user_id=outsider.id,
                                            responsible_user_name='伪造'),
                              client=sc)
        self.assertNoError(body)
        self.assertEqual(body['data']['responsible_user_name'], '跨租户责任人')

    def test_no_perm_user_cannot_be_responsible(self):
        """责任人账号本身不需要具备合同模块权限，只要在本租户且启用即可。"""
        plain = make_user('qa_plain_user', [], tenant_id='admin', nickname='无模块权限用户')
        body = self.post_json(build_payload(self.user,
                                            contract_name='普通账号责任人',
                                            responsible_user_id=plain.id,
                                            responsible_user_name='x'))
        self.assertNoError(body)
        self.assertEqual(body['data']['responsible_user_name'], '无模块权限用户')
