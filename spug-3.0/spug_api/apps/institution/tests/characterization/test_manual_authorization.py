# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""权限模型第二轮改造（2026-10-31）的真实行为测试：所有者全权 + 逐本授权

验收口径（全部走 test client 真实请求链路；隔离测试库 + 临时存储目录）：
- 两层模型：系统角色（页面权限码 institution.manual.*）授予功能资格；
  具体可操作哪本手册由 Manual.owner（所有者）与 ManualAuthorization
  （逐本账号授权 can_view/can_edit/can_publish）决定；tenant_id 不参与
  任何判定（跨租户授权/所有者是预期行为，本套件继续钉死）。
- 所有者自动拥有该手册范围内全部权限（查看发布版与草稿、编辑任意
  文件、发布、授权与分工管理、设密码），不要求持有页面权限码或逐本
  授权（manual_auth 对象级豁免钉死）。
- "admin"概念收敛为平台超管（is_supper）：原"制度管理员"权限码废除；移交/接管=当前所有者或超管；原所有者移交后失权（会话撤销
  留痕、log/audit 含 kind）。
- 授权配置端点：GET/PUT manuals/<pk>/authorizations/（整体替换、全
  False 删行、失权撤销会话 + 迟到回调拒绝）、owner-candidates（所有者
  或超管）、POST owner（移交/接管；同账号/停用账号拒绝）。
- 负责人独占编辑：非所有者同手册其他持 can_edit 编制授权账号在 会话
  开启/multipart 保存/editor-config/forcesave/开始修订/草稿创建 全部
  拒绝；所有者例外（可编辑该手册任意文件）。
- 发布域：can_publish 授权或所有者；仅 can_edit 授权不再可见发布版
  （editor_can_view_published 开关已删）。
- 编辑密码：仅所有者或平台超管可设置/重置（config 页面码不能覆盖）。
"""
import json
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.institution import storage
from apps.institution.models import (Manual, ManualAuthorization,
                                     ManualEditSession, ManualFile,
                                     ManualDraft, ManualOperationLog,
                                     ManualVersion)
from apps.institution.tests.base import (
    PERM_CONFIG, PERM_DRAFT, PERM_DOWNLOAD, PERM_PUBLISH, PERM_VIEW, get_data,
    has_error, make_client, make_grant, make_user, post_json, put_json,
    setup_test_env,
)
from apps.institution.tests.characterization.test_manual_draft import (
    DraftWorkflowBase,
)
from apps.institution.tests.characterization.test_manual_editor import (
    TEST_SECRET, _StubDocServer, _docx,
)
from apps.institution.onlyoffice_jwt import sign_payload

DOCX = b'PK\x03\x04 authorization-docx'


def _manual(name='授权手册', owner=None, tenant_id='deptA', **kwargs):
    params = dict(name=name, code=f'SQ-{name[-2:]}',
                  org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
                  tenant_id=tenant_id)
    if owner is not None:
        params['owner'] = owner
    params.update(kwargs)
    return Manual.objects.create(**params)


class _AuthEnvBase(TestCase):
    """所有者 + 平台超管 + 编制者/发布者/查看者 + 无关账号"""

    def setUp(self):
        setup_test_env()
        self.owner = make_user('owner', tenant_id='deptA',
                               perms=[PERM_VIEW])
        # "admin"收敛为平台超管：is_supper（原"制度管理员"权限码废除）
        self.admin = make_user('inst-admin', is_supper=True, tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptB',
                                perms=[PERM_DRAFT, PERM_VIEW])
        self.publisher = make_user('pub', tenant_id='deptC',
                                   perms=[PERM_PUBLISH, PERM_VIEW])
        self.viewer = make_user('viewer', tenant_id='deptD', perms=[PERM_VIEW])
        self.stranger = make_user('stranger', tenant_id='deptA',
                                  perms=[PERM_VIEW])
        self.owner_client = make_client(self.owner)
        self.admin_client = make_client(self.admin)
        self.editor_client = make_client(self.editor)
        self.publisher_client = make_client(self.publisher)
        self.viewer_client = make_client(self.viewer)
        self.stranger_client = make_client(self.stranger)


class AuthorizationApiTests(_AuthEnvBase):
    """GET/PUT manuals/<pk>/authorizations/"""

    def setUp(self):
        super().setUp()
        self.manual = _manual(owner=self.owner)
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        self.path = f'/institution/manuals/{self.manual.id}/authorizations/'

    def _put(self, client, items):
        return put_json(client, self.path, {'items': items})

    # -- 业务门禁 --

    def test_owner_manages_own_manual(self):
        """所有者（仅 view 页面权限）可读取与替换自己手册的授权"""
        resp = self.owner_client.get(self.path)
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertNotIn('editor_can_view_published', data)
        self.assertIn(self.editor.id,
                      [x['account_id'] for x in data['items']])
        resp = self._put(self.owner_client, [
            {'account_id': self.viewer.id, 'can_view': True,
             'can_edit': False, 'can_publish': False},
        ])
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(ManualAuthorization.objects.filter(
            manual=self.manual, account=self.viewer, can_view=True).exists())

    def test_platform_admin_manages_any_manual(self):
        """平台超管对任意手册（含非自己所有）可管理授权"""
        resp = self._put(self.admin_client, [
            {'account_id': self.publisher.id, 'can_view': True,
             'can_edit': False, 'can_publish': True},
        ])
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(ManualAuthorization.objects.filter(
            manual=self.manual, account=self.publisher,
            can_publish=True).exists())
        resp = self.admin_client.get(self.path)
        self.assertFalse(has_error(resp), resp.content)
        self.assertNotIn('editor_can_view_published', get_data(resp))

    def test_editor_and_stranger_denied(self):
        """编制/发布/查看授权与无关账号均不能读取或替换授权配置"""
        make_grant(self.manual, self.publisher, can_publish=True)
        for client in (self.editor_client, self.publisher_client,
                       self.viewer_client, self.stranger_client):
            resp = client.get(self.path)
            self.assertTrue(has_error(resp))
            self.assertIn('无权限', resp.json()['error'])
            resp = self._put(client, [])
            self.assertTrue(has_error(resp))
        # 授权行未被改动
        self.assertTrue(ManualAuthorization.objects.filter(
            manual=self.manual, account=self.editor, can_edit=True).exists())

    # -- PUT 语义 --

    def test_put_replaces_whole_set_and_drops_all_false_rows(self):
        """整体替换：不在清单中的授权行删除；全 False 不保留空行"""
        make_grant(self.manual, self.publisher, can_publish=True)
        resp = self._put(self.owner_client, [
            {'account_id': self.editor.id, 'can_view': True,
             'can_edit': True, 'can_publish': False},
            {'account_id': self.viewer.id, 'can_view': False,
             'can_edit': False, 'can_publish': False},
        ])
        self.assertFalse(has_error(resp), resp.content)
        rows = {r.account_id: r for r in
                ManualAuthorization.objects.filter(manual=self.manual)}
        # 不在清单中的 publisher 行被删除
        self.assertNotIn(self.publisher.id, rows)
        # 全 False 的 viewer 不落行
        self.assertNotIn(self.viewer.id, rows)
        # editor 行更新为 can_edit=True/can_view=True
        self.assertTrue(rows[self.editor.id].can_edit)

    def test_put_validates_accounts_and_flags(self):
        """无效/停用/重复账号与非法布尔值明确拒绝"""
        resp = self._put(self.owner_client, [
            {'account_id': 999999, 'can_view': True, 'can_edit': False,
             'can_publish': False}])
        self.assertTrue(has_error(resp))
        self.assertIn('无效', resp.json()['error'])
        resp = self._put(self.owner_client, [
            {'account_id': self.viewer.id, 'can_view': True,
             'can_edit': False, 'can_publish': False},
            {'account_id': self.viewer.id, 'can_view': False,
             'can_edit': True, 'can_publish': False}])
        self.assertTrue(has_error(resp))
        self.assertIn('重复', resp.json()['error'])
        resp = self._put(self.owner_client, [
            {'account_id': self.viewer.id, 'can_view': 'yes',
             'can_edit': False, 'can_publish': False}])
        self.assertTrue(has_error(resp))
        disabled = make_user('disabled', tenant_id='deptA')
        disabled.is_active = False
        disabled.save()
        resp = self._put(self.owner_client, [
            {'account_id': disabled.id, 'can_view': True, 'can_edit': False,
             'can_publish': False}])
        self.assertTrue(has_error(resp))

    def test_put_writes_oplog_and_audit_fields(self):
        resp = self._put(self.owner_client, [
            {'account_id': self.editor.id, 'can_view': True,
             'can_edit': True, 'can_publish': False}])
        self.assertFalse(has_error(resp), resp.content)
        log = ManualOperationLog.objects.filter(
            manual=self.manual, action='authorization_change').latest('id')
        detail = json.loads(log.detail)
        self.assertEqual(detail['revoked_sessions'], 0)
        self.assertNotIn('editor_can_view_published', detail)
        self.assertEqual(detail['grants'][0]['account_id'], self.editor.id)


class RevocationSessionTests(DraftWorkflowBase):
    """失权撤销会话 + 迟到回调拒绝（授权模型与在途编辑的交互）"""

    def setUp(self):
        super().setUp()
        self.editor2 = make_user('editor2', tenant_id='deptC',
                                 perms=[PERM_DRAFT, PERM_VIEW])
        make_grant(self.manual, self.editor2, can_view=True, can_edit=True)
        self._set_password()
        self._add_file()
        self.auth_path = (
            f'/institution/manuals/{self.manual.id}/authorizations/')

    def _put_auth(self, items):
        return put_json(self.manager_client, self.auth_path, {'items': items})

    def test_losing_edit_grant_revokes_sessions_and_rejects_save(self):
        """失权（PUT 授权去掉 can_edit）撤销其在该手册全部文件的活跃会话，
        旧会话保存被拒、未落盘内容显式丢弃"""
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        resp = self._put_auth([
            {'account_id': self.editor.id, 'can_view': True,
             'can_edit': False, 'can_publish': False},
            {'account_id': self.editor2.id, 'can_view': True,
             'can_edit': True, 'can_publish': False},
        ])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revoked_sessions'], 1)
        session = ManualEditSession.objects.get(session_key=session_key)
        self.assertIsNotNone(session.revoked_at)
        self.assertIn('失效', session.revoked_reason)
        # 失权后旧会话保存被拒
        resp = self._save_draft(session_key, 1)
        self.assertTrue(has_error(resp))
        # 失权者重新开启会话也被拒（编制资格已丧失）
        resp = self._start_session()
        self.assertTrue(has_error(resp))

    def test_removed_from_grant_list_revokes_sessions(self):
        """从授权清单中整体移除的账号同样撤销会话"""
        resp = self._start_session()
        session_key = get_data(resp)['session_key']
        resp = self._put_auth([
            {'account_id': self.editor2.id, 'can_view': True,
             'can_edit': True, 'can_publish': False},
        ])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revoked_sessions'], 1)
        self.assertIsNotNone(ManualEditSession.objects.get(
            session_key=session_key).revoked_at)
        self.assertFalse(ManualAuthorization.objects.filter(
            manual=self.manual, account=self.editor).exists())

    def test_keeping_edit_grant_keeps_session(self):
        """未失权（仅调整其他能力位）不撤销会话"""
        resp = self._start_session()
        session_key = get_data(resp)['session_key']
        resp = self._put_auth([
            {'account_id': self.editor.id, 'can_view': True,
             'can_edit': True, 'can_publish': True},
        ])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revoked_sessions'], 0)
        self.assertIsNone(ManualEditSession.objects.get(
            session_key=session_key).revoked_at)

    @override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                       ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                       ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw')
    def test_late_callback_rejected_after_grant_revocation(self):
        """失权撤销会话后，DS 迟到的保存回调被拒（未落盘内容显式丢弃）"""
        resp = self._start_session()
        session_key = get_data(resp)['session_key']
        doc_key = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/editor-config/?session_key={session_key}'))['document_key']
        resp = self._put_auth([
            {'account_id': self.editor.id, 'can_view': True,
             'can_edit': False, 'can_publish': False},
        ])
        self.assertFalse(has_error(resp), resp.content)
        stub = _StubDocServer(payload=_docx(b'late-after-revoke'))
        self.addCleanup(stub.stop)
        body = {'key': doc_key, 'status': 2,
                'url': f'{stub.base_url}/docs/{doc_key}.docx',
                'users': [f'uid-{self.editor.id}']}
        token = sign_payload(body, TEST_SECRET)
        resp = self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'attachments/oo-editor-callback/',
            data=json.dumps(body), content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(resp.status_code, 403)
        # 草稿未被覆盖
        draft = ManualDraft.objects.get(file_id=self.file_id)
        self.assertEqual(draft.revision, 1)
        self.assertNotEqual(draft.file_hash, _docx(b'late-after-revoke'))


class OwnerManagementTests(_AuthEnvBase):
    """owner-candidates（所有者/超管）与 POST owner（移交/接管）"""

    def setUp(self):
        super().setUp()
        self.manual = _manual()  # 初始无所有者（模拟迁移后的存量手册）
        self.candidates_path = (
            f'/institution/manuals/{self.manual.id}/owner-candidates/')
        self.owner_path = f'/institution/manuals/{self.manual.id}/owner/'

    def _assign_owner(self, client, account_id):
        return post_json(client, self.owner_path, {'account_id': account_id})

    def test_owner_candidates_for_owner_or_admin(self):
        """候选清单=手册所有者或平台超管；其他账号拒绝"""
        resp = self.admin_client.get(self.candidates_path)
        self.assertFalse(has_error(resp), resp.content)
        rows = get_data(resp)
        by_id = {r['id']: r for r in rows}
        self.assertIn(self.editor.id, by_id)
        self.assertEqual(by_id[self.editor.id]['name'], self.editor.nickname)
        for row in rows:
            self.assertEqual(set(row.keys()), {'id', 'name'})
        # 指定所有者后，所有者本人可调（第二轮：所有者可移交）
        self._assign_owner(self.admin_client, self.owner.id)
        resp = self.owner_client.get(self.candidates_path)
        self.assertFalse(has_error(resp), resp.content)
        # 非所有者非超管拒绝
        for client in (self.editor_client, self.publisher_client,
                       self.stranger_client):
            resp = client.get(self.candidates_path)
            self.assertTrue(has_error(resp))
            self.assertIn('无权限', resp.json()['error'])

    def test_admin_takeover_then_owner_transfer(self):
        """超管接管（takeover）与所有者移交（transfer）统一入口；留痕"""
        resp = self._assign_owner(self.admin_client, self.owner.id)
        self.assertFalse(has_error(resp), resp.content)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.owner_id, self.owner.id)
        # 超管不是所有者：kind=takeover
        detail = json.loads(ManualOperationLog.objects.filter(
            manual=self.manual, action='owner_change').latest('id').detail)
        self.assertEqual(detail['kind'], 'takeover')
        self.assertIsNone(detail['previous_owner_id'])
        self.assertEqual(detail['owner_id'], self.owner.id)
        # 所有者移交（transfer）：改指另一账号
        resp = self._assign_owner(self.owner_client, self.editor.id)
        self.assertFalse(has_error(resp), resp.content)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.owner_id, self.editor.id)
        detail = json.loads(ManualOperationLog.objects.filter(
            manual=self.manual, action='owner_change').latest('id').detail)
        self.assertEqual(detail['kind'], 'transfer')
        self.assertEqual(detail['previous_owner_id'], self.owner.id)
        self.assertEqual(detail['owner_id'], self.editor.id)

    def test_owner_transfer_revokes_previous_owner_sessions(self):
        """所有者移交后：原所有者活跃编辑会话被撤销留痕，此后不再因
        所有者身份保有权能（无授权则详情/编辑均拒绝）"""
        self._assign_owner(self.admin_client, self.owner.id)
        # 文件+草稿+密码，原所有者（手册所有者）开编辑会话
        with tempfile.TemporaryDirectory() as tmp:
            patcher = patch.object(storage, 'get_institution_storage_base',
                                   return_value=tmp)
            patcher.start()
            self.addCleanup(patcher.stop)
            file_entry = ManualFile.objects.create(
                manual=self.manual, display_name='a.docx', sort_order=0)
            ManualDraft.objects.create(
                manual=self.manual, file=file_entry,
                file_path='drafts/x/202610/a.docx', revision=1)
            resp = put_json(self.owner_client,
                            f'/institution/manuals/{self.manual.id}/password/',
                            {'password': 'pass-1234'})
            self.assertFalse(has_error(resp), resp.content)
            resp = post_json(
                self.owner_client,
                f'/institution/manuals/{self.manual.id}/files/'
                f'{file_entry.id}/draft/session/', {'password': 'pass-1234'})
            self.assertFalse(has_error(resp), resp.content)
            session_key = get_data(resp)['session_key']
            # 移交给 editor
            resp = self._assign_owner(self.owner_client, self.editor.id)
            self.assertFalse(has_error(resp), resp.content)
            session = ManualEditSession.objects.get(session_key=session_key)
            self.assertIsNotNone(session.revoked_at)
            self.assertIn('所有者移交', session.revoked_reason)
            self.assertEqual(
                json.loads(ManualOperationLog.objects.filter(
                    manual=self.manual, action='owner_change').latest('id')
                    .detail)['revoked_sessions'], 1)
        # 原所有者不再因所有者身份保有权能：详情不可见（无授权行）
        resp = self.owner_client.get(
            f'/institution/manuals/{self.manual.id}/')
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_post_owner_same_account_rejected(self):
        """移交给自己（同账号）明确拒绝；超管接管给自己是合法的（不同账号）"""
        self._assign_owner(self.admin_client, self.owner.id)
        resp = self._assign_owner(self.owner_client, self.owner.id)
        self.assertTrue(has_error(resp))
        self.assertIn('相同', resp.json()['error'])
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.owner_id, self.owner.id)
        # 超管接管给自己（不同账号）允许；接管后再次指给自己被拒
        resp = self._assign_owner(self.admin_client, self.admin.id)
        self.assertFalse(has_error(resp), resp.content)
        resp = self._assign_owner(self.admin_client, self.admin.id)
        self.assertTrue(has_error(resp))
        self.assertIn('相同', resp.json()['error'])
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.owner_id, self.admin.id)

    def test_post_owner_denied_for_non_owner(self):
        """非所有者非超管拒绝（编制/发布授权与无关账号）"""
        self._assign_owner(self.admin_client, self.owner.id)
        for client in (self.editor_client, self.publisher_client,
                       self.stranger_client):
            resp = self._assign_owner(client, self.editor.id)
            self.assertTrue(has_error(resp))
            self.assertIn('无权限', resp.json()['error'])
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.owner_id, self.owner.id)

    def test_post_owner_rejects_inactive_or_missing_account(self):
        resp = self._assign_owner(self.admin_client, 999999)
        self.assertTrue(has_error(resp))
        disabled = make_user('gone', tenant_id='deptA')
        disabled.is_active = False
        disabled.save()
        resp = self._assign_owner(self.admin_client, disabled.id)
        self.assertTrue(has_error(resp))
        self.assertIn('停用', resp.json()['error'])


class AccountOptionsTests(_AuthEnvBase):
    """GET manuals/<pk>/account-options/：授权界面账号候选

    授权配置允许普通所有者管理自己的手册（GET/PUT authorizations 同
    门禁），添加授权行需要账号候选来源；口径与 owner-candidates 一致
    （全部启用账号、仅 id+name 最小字段），但业务门禁为所有者/超管。
    """

    def setUp(self):
        super().setUp()
        self.manual = _manual(owner=self.owner)
        self.path = f'/institution/manuals/{self.manual.id}/account-options/'

    def test_owner_lists_account_options_for_own_manual(self):
        """所有者（仅 view 页面权限）可取自己手册的账号候选"""
        resp = self.owner_client.get(self.path)
        self.assertFalse(has_error(resp), resp.content)
        rows = get_data(resp)
        by_id = {r['id']: r for r in rows}
        # 全部启用账号（含尚未持任何授权、待添加的账号）
        self.assertIn(self.editor.id, by_id)
        self.assertEqual(by_id[self.editor.id]['name'], self.editor.nickname)
        self.assertIn(self.stranger.id, by_id)
        for row in rows:
            self.assertEqual(set(row.keys()), {'id', 'name'})

    def test_platform_admin_lists_account_options_for_any_manual(self):
        """平台超管对任意手册可取账号候选"""
        resp = self.admin_client.get(self.path)
        self.assertFalse(has_error(resp), resp.content)
        self.assertIn(self.viewer.id, [r['id'] for r in get_data(resp)])

    def test_grant_holder_without_owner_or_admin_denied(self):
        """持编制授权但非所有者/超管：拒绝（与 PUT authorizations 同门禁）"""
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        resp = self.editor_client.get(self.path)
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])
        # 无任何授权的无关账号同样拒绝
        resp = self.stranger_client.get(self.path)
        self.assertTrue(has_error(resp))


class ExclusiveEditingTests(DraftWorkflowBase):
    """负责人独占编辑：非所有者同手册其他持 can_edit 编制授权账号全部
    写路径拒绝；手册所有者例外（可编辑该手册任意文件）"""

    def setUp(self):
        super().setUp()
        self.other = make_user('other-ed', tenant_id='deptC',
                               perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.other, can_view=True, can_edit=True)
        self.other_client = make_client(self.other)
        self._set_password()
        self._add_file()
        self.base = (f'/institution/manuals/{self.manual.id}/'
                     f'files/{self.file_id}')

    def _session_for(self, client):
        resp = post_json(client, f'{self.base}/draft/session/',
                         {'password': 'edit-pass-1'})
        return resp

    def test_owner_edits_file_assigned_to_other(self):
        """所有者例外：他人担任负责人的文件，所有者可开会话并保存"""
        resp = self._session_for(self.manager_client)
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        upload = SimpleUploadedFile('owner-save.docx', DOCX)
        resp = self.manager_client.post(
            f'{self.base}/draft/save/',
            {'file': upload, 'session_key': key, 'revision': 1})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 2)

    def test_owner_editor_config_for_file_assigned_to_other(self):
        """所有者例外：他人负责的文件可取编辑配置（权限门放行）"""
        resp = self._session_for(self.manager_client)
        key = get_data(resp)['session_key']
        resp = self.manager_client.get(
            f'{self.base}/draft/editor-config/?session_key={key}')
        # 编辑服务已配置的测试环境返回完整配置（含 document_key）；
        # 未配置时降级 editor_available=False——两种形态都说明权限门已通过
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertTrue(data.get('editor_available') is False
                        or 'document_key' in data, resp.content)

    def test_owner_forcesave_gate_passed_for_file_assigned_to_other(self):
        """所有者例外：forcesave 权限门对他人负责的文件放行（会话无在线
        文档的业务错误而非权限拒绝，说明 can_edit_file 已通过）"""
        resp = self._session_for(self.manager_client)
        key = get_data(resp)['session_key']
        resp = post_json(self.manager_client, f'{self.base}/draft/forcesave/',
                         {'session_key': key})
        self.assertTrue(has_error(resp))
        self.assertNotIn('无权限', resp.json()['error'])

    def test_non_owner_session_start_rejected_despite_grant(self):
        resp = self._session_for(self.other_client)
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_non_owner_local_upload_save_rejected(self):
        """本机上传（multipart draft/save）同样负责人独占"""
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        upload = SimpleUploadedFile('evil.docx', DOCX)
        resp = self.other_client.post(
            f'{self.base}/draft/save/',
            {'file': upload, 'session_key': key, 'revision': 1})
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_non_owner_editor_config_rejected(self):
        resp = self._start_session()
        key = get_data(resp)['session_key']
        resp = self.other_client.get(
            f'{self.base}/draft/editor-config/?session_key={key}')
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_non_owner_forcesave_rejected(self):
        resp = self._start_session()
        key = get_data(resp)['session_key']
        resp = post_json(self.other_client, f'{self.base}/draft/forcesave/',
                         {'session_key': key})
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_non_owner_revision_start_rejected(self):
        resp = post_json(self.other_client,
                         f'{self.base}/revision/start/', {})
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_non_owner_draft_create_rejected(self):
        resp = post_json(self.other_client, f'{self.base}/draft/create/', {})
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_password_alone_cannot_grant_edit(self):
        """密码只是附加验证：已验密会话不能单独赋予编辑权——无授权者
        与有授权非负责人即使密码正确也被拒"""
        outsider = make_user('pwd-only', tenant_id='deptE', perms=[PERM_DRAFT])
        resp = post_json(make_client(outsider), f'{self.base}/draft/session/',
                         {'password': 'edit-pass-1'})
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])
        resp = self._session_for(self.other_client)
        self.assertTrue(has_error(resp))


class PublishedVisibilityTests(_AuthEnvBase):
    """can_view_published 组合与发布域按 can_publish 授权/所有者"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.manual = _manual(owner=self.owner)
        self.manual_id = self.manual.id
        file_entry = ManualFile.objects.create(
            manual=self.manual, display_name='a.docx', sort_order=0)
        ManualDraft.objects.create(
            manual=self.manual, file=file_entry,
            file_path='drafts/manual_x/202610/a.docx',
            original_name='a.docx', revision=1)
        self.version = ManualVersion.objects.create(
            manual=self.manual, version_no=1,
            file_path='versions/manual_x/202610/a.docx',
            original_name='a.docx', published_by=self.owner)
        self.manual.current_version = self.version
        self.manual.save(update_fields=['current_version'])

    def _versions(self, client):
        return client.get(
            f'/institution/manuals/{self.manual_id}/versions/')

    def test_view_grant_sees_published(self):
        make_grant(self.manual, self.viewer, can_view=True)
        resp = self._versions(self.viewer_client)
        self.assertFalse(has_error(resp), resp.content)

    def test_edit_only_grant_cannot_see_published(self):
        """仅 can_edit 授权不再可见发布版（editor_can_view_published 开关
        已删除，发布版可见性=所有者/超管/can_view 授权）"""
        make_grant(self.manual, self.editor, can_edit=True)
        resp = self._versions(self.editor_client)
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_owner_sees_published_without_grant(self):
        """owner 自动可见发布版（第二轮：所有者拥有范围内全部权限）"""
        resp = self._versions(self.owner_client)
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['total'], 1)

    def test_platform_admin_sees_published(self):
        resp = self._versions(self.admin_client)
        self.assertFalse(has_error(resp), resp.content)

    def test_publish_requires_publish_grant(self):
        """发布域按 can_publish 授权/所有者：持 publish 页面权限但无逐本
        授权的非所有者不能发布（页面门通过、业务门拒绝）"""
        page_editor = make_user('page-ed', tenant_id='deptB',
                                perms=[PERM_PUBLISH, PERM_DRAFT, PERM_VIEW])
        make_grant(self.manual, page_editor, can_edit=True)
        page_holder = make_user('page-only', tenant_id='deptA',
                                perms=[PERM_PUBLISH, PERM_VIEW])
        for user in (page_editor, page_holder):
            resp = post_json(
                make_client(user),
                f'/institution/manuals/{self.manual_id}/publish/',
                {'change_note': 'x'})
            self.assertTrue(has_error(resp))
            self.assertIn('无权限', resp.json()['error'])
        # 持 can_publish 授权者越过权限门（草稿物理文件缺失的业务错误
        # 说明权限已放行）
        make_grant(self.manual, self.publisher, can_publish=True)
        resp = post_json(
            self.publisher_client,
            f'/institution/manuals/{self.manual_id}/publish/',
            {'change_note': '由发布授权发起'})
        self.assertTrue(has_error(resp))
        self.assertNotIn('无权限', resp.json()['error'])

    def test_owner_publishes_without_grant_or_page_perm(self):
        """所有者无 can_publish 授权、无 publish 页面权限也可发布
        （manual_auth 对象级豁免 + can_publish 所有者分支）"""
        no_perm_owner = make_user('no-perm-owner', tenant_id='deptA')
        self.manual.owner = no_perm_owner
        self.manual.save(update_fields=['owner'])
        draft = ManualDraft.objects.get(manual=self.manual)
        abs_path = storage.resolve_absolute_path(draft.file_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(b'PK\x03\x04 owner-publish')
        resp = post_json(
            make_client(no_perm_owner),
            f'/institution/manuals/{self.manual_id}/publish/',
            {'change_note': '所有者直接发布'})
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(ManualVersion.objects.filter(
            manual=self.manual, version_no=2).exists())


class VisibilityFilterTests(_AuthEnvBase):
    """可见性过滤：列表/详情/work_status 逐手册判定"""

    def setUp(self):
        super().setUp()
        self.owned = _manual(name='所有者手册甲', owner=self.owner)
        self.granted = _manual(name='授权手册乙')
        make_grant(self.granted, self.editor, can_edit=True)
        self.published_granted = _manual(name='发布授权手册丙')
        make_grant(self.published_granted, self.publisher, can_publish=True)
        self.viewed = _manual(name='查看授权手册丁')
        make_grant(self.viewed, self.viewer, can_view=True)

    def _names(self, client):
        resp = client.get('/institution/manuals/')
        self.assertFalse(has_error(resp), resp.content)
        return [x['name'] for x in get_data(resp)['items']]

    def test_owner_sees_own_manuals(self):
        names = self._names(self.owner_client)
        self.assertIn('所有者手册甲', names)
        self.assertNotIn('授权手册乙', names)

    def test_grant_holders_see_granted_manuals(self):
        self.assertIn('授权手册乙', self._names(self.editor_client))
        self.assertIn('发布授权手册丙', self._names(self.publisher_client))
        self.assertIn('查看授权手册丁', self._names(self.viewer_client))
        # 授权范围之外一律不可见
        self.assertNotIn('所有者手册甲', self._names(self.editor_client))

    def test_stranger_sees_nothing_and_cross_tenant_grant_visible(self):
        self.assertEqual(self._names(self.stranger_client), [])
        # 跨租户授权是预期行为（tenant_id 不参与判定）
        cross = _manual(name='跨租户手册戊', tenant_id='deptX')
        outsider = make_user('cross', tenant_id='deptY', perms=[PERM_VIEW])
        make_grant(cross, outsider, can_view=True)
        resp = make_client(outsider).get('/institution/manuals/')
        self.assertIn('跨租户手册戊',
                      [x['name'] for x in get_data(resp)['items']])

    def test_platform_admin_sees_all(self):
        names = self._names(self.admin_client)
        for name in ('所有者手册甲', '授权手册乙', '发布授权手册丙',
                     '查看授权手册丁'):
            self.assertIn(name, names)

    def test_detail_visibility(self):
        resp = self.editor_client.get(
            f'/institution/manuals/{self.granted.id}/')
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertTrue(data['is_owner'] is False)
        self.assertEqual(data['my_roles'], ['edit'])
        resp = self.stranger_client.get(
            f'/institution/manuals/{self.granted.id}/')
        self.assertTrue(has_error(resp))

    def test_work_status_visibility_per_manual(self):
        """work_status：超管/所有者/编制或发布授权可见；仅查看恒为 None"""
        rows = {x['id']: x for x in get_data(
            self.owner_client.get('/institution/manuals/'))['items']}
        self.assertIsNotNone(rows[self.owned.id]['work_status'])
        self.assertEqual(rows[self.owned.id]['work_status']['status'],
                         'no_files')
        # 所有者对授权给他人的手册不可见（不进列表，更不下发 work_status）
        self.assertNotIn(self.granted.id, rows)
        self.assertNotIn(self.viewed.id, rows)
        editor_rows = {x['id']: x for x in get_data(
            self.editor_client.get('/institution/manuals/'))['items']}
        self.assertIsNotNone(editor_rows[self.granted.id]['work_status'])
        # 非授权手册根本不可见（不进列表，更不下发 work_status）
        self.assertNotIn(self.owned.id, editor_rows)
        self.assertNotIn(self.viewed.id, editor_rows)
        publisher_rows = {x['id']: x for x in get_data(
            self.publisher_client.get('/institution/manuals/'))['items']}
        self.assertIsNotNone(
            publisher_rows[self.published_granted.id]['work_status'])
        # 仅查看授权：手册可见但 work_status 恒为 None（不泄漏草稿信息）
        viewer_rows = {x['id']: x for x in get_data(
            self.viewer_client.get('/institution/manuals/'))['items']}
        self.assertIn(self.viewed.id, viewer_rows)
        self.assertIsNone(viewer_rows[self.viewed.id]['work_status'])
        admin_rows = {x['id']: x for x in get_data(
            self.admin_client.get('/institution/manuals/'))['items']}
        self.assertIsNotNone(admin_rows[self.viewed.id]['work_status'])


class OwnerPagePermExemptionTests(TestCase):
    """无任何 institution 页面码的所有者走 manual_auth 通道（第二轮核心）

    所有者不需要角色权限：读详情、开编辑会话、发布、设密码全部成功；
    仅持 config 页面码的非所有者设密码被拒（页面码不能覆盖对象级限制）。
    """

    def setUp(self):
        setup_test_env()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        # 无任何页面权限码的所有者
        self.owner = make_user('bare-owner', tenant_id='deptA')
        self.manual = _manual(owner=self.owner, name='裸所有者手册')
        self.file_entry = ManualFile.objects.create(
            manual=self.manual, display_name='a.docx', sort_order=0)
        self.draft = ManualDraft.objects.create(
            manual=self.manual, file=self.file_entry,
            file_path='drafts/bare/202610/a.docx',
            original_name='a.docx', revision=1)
        self.owner_client = make_client(self.owner)

    def _write_draft_file(self):
        abs_path = storage.resolve_absolute_path(self.draft.file_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(b'PK\x03\x04 bare-owner')

    def test_owner_sets_password_without_any_page_perm(self):
        resp = put_json(self.owner_client,
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': 'pass-1234'})
        self.assertFalse(has_error(resp), resp.content)
        self.manual.refresh_from_db()
        self.assertTrue(self.manual.password_hash)

    def test_super_admin_sets_password(self):
        superuser = make_user('root', is_supper=True, tenant_id='root')
        resp = put_json(make_client(superuser),
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': 'pass-1234'})
        self.assertFalse(has_error(resp), resp.content)

    def test_config_page_perm_non_owner_cannot_set_password(self):
        """仅 config 页面码非所有者设密码被拒（对象级限制不被页面码覆盖）"""
        config_only = make_user('cfg-only', tenant_id='deptA',
                                perms=[PERM_CONFIG])
        resp = put_json(make_client(config_only),
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': 'pass-1234'})
        self.assertTrue(has_error(resp))
        self.assertIn('权限拒绝', resp.json()['error'])
        self.manual.refresh_from_db()
        self.assertFalse(self.manual.password_hash)

    def test_owner_reads_detail_with_full_roles(self):
        resp = self.owner_client.get(
            f'/institution/manuals/{self.manual.id}/')
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertTrue(data['is_owner'])
        self.assertEqual(data['my_roles'], ['view', 'edit', 'publish'])

    def test_owner_opens_edit_session_without_any_page_perm(self):
        self.test_owner_sets_password_without_any_page_perm()
        resp = post_json(
            self.owner_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_entry.id}/draft/session/', {'password': 'pass-1234'})
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(get_data(resp)['session_key'])

    def test_owner_publishes_without_any_page_perm(self):
        self._write_draft_file()
        resp = post_json(
            self.owner_client,
            f'/institution/manuals/{self.manual.id}/publish/',
            {'change_note': '裸所有者发布'})
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(ManualVersion.objects.filter(
            manual=self.manual).exists())

    def test_owner_publish_preview_without_any_page_perm(self):
        """发布预检同走 manual_auth(view) + can_publish 所有者分支"""
        self._write_draft_file()
        resp = self.owner_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertFalse(has_error(resp), resp.content)
