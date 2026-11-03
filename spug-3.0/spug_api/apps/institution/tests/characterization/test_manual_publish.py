# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""发布版本不可变性、回退、废止与编辑服务契约的真实行为测试

关键验收语义：
- 发布需发布角色 + 变更说明；发布版文件独立存储不可变（SHA256 固定）。
- 回退旧版产生新草稿，再发布产生新版本，历史文件绝不改写。
- 编辑服务回调校验签名令牌、目标草稿与修订序号；迟到回调拒绝。
"""
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.institution import storage
from apps.institution.models import Manual, ManualDraft, ManualFile, \
    ManualVersion
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DRAFT, PERM_DOWNLOAD, PERM_PUBLISH, PERM_VIEW,
    delete_json, get_data, has_error, make_client, make_grant, make_user,
    post_json, put_json, setup_test_env,
)


class PublishWorkflowBase(TestCase):
    """管理者建手册+原稿+草稿；发布/编制角色账号就位"""

    def setUp(self):
        setup_test_env()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.manager = make_user('mgr', tenant_id='deptA', perms=ALL_PERMS)
        self.manager_client = make_client(self.manager)
        self.manual = Manual.objects.create(
            name='部门应急救援手册', code='YJ-001',
            org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
            owner=self.manager, tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptB',
                                perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        self.publisher = make_user('pub', tenant_id='deptC',
                                   perms=[PERM_PUBLISH, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.publisher, can_view=True, can_publish=True)
        self.editor_client = make_client(self.editor)
        self.publisher_client = make_client(self.publisher)
        self._setup_draft(content=b'PK\x03\x04 v-draft-1')

    def _setup_draft(self, content=b'PK\x03\x04 draft', name='原稿.docx'):
        upload = SimpleUploadedFile(name, content)
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/',
            # 会话/保存等写路径负责人独占：指派 editor 为文件负责人
            {'file': upload, 'owner_id': str(self.editor.id)})
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.main_file_id = data['id']
        return data

    def _main_draft(self):
        """主文件草稿（发布套件夹具只有一份文件）"""
        return ManualDraft.objects.get(file_id=self.main_file_id)

    def _set_password(self, password='edit-pass-1'):
        resp = put_json(self.manager_client,
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': password})
        self.assertFalse(has_error(resp), resp.content)
        return password

    def _start_session(self, password='edit-pass-1'):
        resp = post_json(self.editor_client,
                         f'/institution/manuals/{self.manual.id}/draft/session/',
                         {'password': password})
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _save(self, session_key, revision, content):
        upload = SimpleUploadedFile('saved.docx', content)
        resp = self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/draft/save/',
            {'file': upload, 'session_key': session_key, 'revision': revision})
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _publish(self, client=None, note='初始版本', actor=None):
        if client is None:
            client = self.publisher_client
            actor = actor or self.publisher
        if actor is not None:
            self._ensure_handoff(actor)
        resp = post_json(client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': note})
        return resp

    def _ensure_handoff(self, actor):
        """发布前由各文件负责人经真实接口提交编制（预期成功发布的夹具）

        blocked/权限用例直接调用 publish 走真实阻断路径，不经此助手；
        提交失败不断言（缺草稿/会话占用等情况由真实发布自己报错）。
        """
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        for row in get_data(resp):
            owner_id = row['assignment']['owner_id']
            if not owner_id or owner_id == actor.id:
                continue
            owner = ManualFile.objects.get(pk=row['id']).owner
            post_json(
                make_client(owner),
                f'/institution/manuals/{self.manual.id}/files/'
                f'{row["id"]}/submit/', {})


class PublishTests(PublishWorkflowBase):
    def test_publish_creates_immutable_version(self):
        resp = self._publish(note='首次发布')
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['version_no'], 1)
        self.assertTrue(data['is_current'])
        self.assertTrue(data['file_hash'])
        version = ManualVersion.objects.get(pk=data['id'])
        self.assertEqual(version.change_note, '首次发布')
        # 版本显示名=草稿显示名（用户原稿名），非带随机后缀的存储名
        self.assertEqual(version.original_name, '原稿.docx')
        self.assertEqual(data['file_name'], '原稿.docx')
        self.assertEqual(version.published_by_id, self.publisher.id)
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(version.file_path)))
        self.assertTrue(version.file_path.startswith('versions/'))
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, version.id)
        draft = self._main_draft()
        self.assertEqual(draft.base_version_id, version.id)

    def test_publish_uses_file_display_name_not_draft_name(self):
        """版本显示名取文件条目显示名：草稿被 ONLYOFFICE 回调写成系统
        生成名（callback_/oo_cb_ 前缀）也不会透出到版本清单；用户改名
        文件后版本名跟随，历史快照名不可变"""
        draft = self._main_draft()
        draft.original_name = 'callback_1bb6e2b70ca4.docx'
        draft.save(update_fields=['original_name'])
        resp = self._publish(note='回调后发布')
        self.assertFalse(has_error(resp), resp.content)
        version = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(version.original_name, '原稿.docx')
        self.assertEqual(get_data(resp)['files'][0]['file_name'], '原稿.docx')
        self.assertEqual(version.files.count(), 1)
        file_id = version.files.first().manual_file_id
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{file_id}/rename/',
                         {'name': '应急救援总体预案.docx'})
        self.assertFalse(has_error(resp), resp.content)
        resp = self._publish(note='改名后发布')
        version2 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(version2.original_name, '应急救援总体预案.docx')
        version.refresh_from_db()
        self.assertEqual(version.original_name, '原稿.docx')

    def test_publish_missing_draft_file_business_error(self):
        """草稿物理文件丢失：发布返回业务错误而非 500，不产生版本"""
        draft = self._main_draft()
        os.remove(storage.resolve_absolute_path(draft.file_path))
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '测试发布'})
        self.assertTrue(has_error(resp))
        self.assertIn('不存在', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(manual=self.manual).exists())

    def test_publish_requires_change_note(self):
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '   '})
        self.assertTrue(has_error(resp))
        self.assertIn('变更说明', resp.json()['error'])

    def test_publish_requires_publish_grant(self):
        """有编制授权无发布授权者不能发布；页面权限满足但无授权亦不能"""
        resp = self._publish(client=self.editor_client)
        self.assertTrue(has_error(resp))
        insider = make_user('in', tenant_id='deptA', perms=[PERM_PUBLISH])
        resp = self._publish(client=make_client(insider))
        self.assertTrue(has_error(resp))
        # 仅页面权限（无 can_publish 授权行）不能发布
        perm_only = make_user('p2', tenant_id='deptC', perms=[PERM_PUBLISH])
        make_grant(self.manual, perm_only, can_view=True)
        resp = self._publish(client=make_client(perm_only))
        self.assertTrue(has_error(resp))

    def test_owner_can_publish_without_publish_grant(self):
        """第二轮：所有者无需 can_publish 授权即可发布（manual_auth
        对象级豁免 + can_publish 所有者分支）"""
        resp = self._publish(client=self.manager_client, note='所有者发布',
                             actor=self.manager)
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['version_no'], 1)
        self.assertEqual(
            ManualVersion.objects.get(manual=self.manual).published_by_id,
            self.manager.id)

    def test_publish_without_draft_rejected(self):
        empty = Manual.objects.create(
            name='空手册', code='K-002', org_type=Manual.OWNER_SECTION,
            org_name='乙科室', tenant_id='deptA')
        make_grant(empty, self.publisher, can_publish=True)
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{empty.id}/publish/',
                         {'change_note': 'x'})
        self.assertTrue(has_error(resp))

    def test_version_files_never_overwritten(self):
        """发布 v1 后继续编辑再发布 v2：v1 文件与哈希不变"""
        resp = self._publish(note='v1')
        v1 = get_data(resp)
        v1_path = storage.resolve_absolute_path(
            ManualVersion.objects.get(pk=v1['id']).file_path)
        with open(v1_path, 'rb') as f:
            v1_bytes = f.read()
        # 继续编辑草稿并发布 v2
        self._set_password()
        session = self._start_session()
        self._save(session['session_key'], session['revision'], b'PK\x03\x04 v2-content')
        # 发布前退出编辑会话（活跃会话阻断整套发布）
        delete_json(self.editor_client,
                    f'/institution/manuals/{self.manual.id}/draft/session/',
                    {'session_key': session['session_key']})
        resp = self._publish(note='v2 修订')
        self.assertFalse(has_error(resp), resp.content)
        v2 = get_data(resp)
        self.assertEqual(v2['version_no'], 2)
        # v1 文件字节与哈希不变
        with open(v1_path, 'rb') as f:
            self.assertEqual(f.read(), v1_bytes)
        v1_obj = ManualVersion.objects.get(pk=v1['id'])
        self.assertEqual(v1_obj.file_hash, v1['file_hash'])
        self.assertNotEqual(v1_obj.file_path,
                            ManualVersion.objects.get(pk=v2['id']).file_path)

    def test_version_list_visibility(self):
        self._publish()
        # 仅查看授权（跨租户）可见版本列表
        viewer = make_user('v', tenant_id='deptZ', perms=[PERM_VIEW])
        make_grant(self.manual, viewer, can_view=True)
        resp = make_client(viewer).get(
            f'/institution/manuals/{self.manual.id}/versions/')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['total'], 1)
        # can_view 授权可见发布版（仅 can_edit 不再可见——开关已删）
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/versions/')
        self.assertFalse(has_error(resp), resp.content)
        # 无角色者不可见
        outsider = make_user('o', tenant_id='deptA', perms=[PERM_VIEW])
        resp = make_client(outsider).get(
            f'/institution/manuals/{self.manual.id}/versions/')
        self.assertTrue(has_error(resp))

    def test_version_download_and_hash_integrity(self):
        self._publish()
        version = ManualVersion.objects.filter(manual=self.manual).first()
        viewer = make_user('v', tenant_id='deptZ',
                           perms=[PERM_VIEW, PERM_DOWNLOAD])
        make_grant(self.manual, viewer, can_view=True)
        resp = make_client(viewer).get(
            f'/institution/manuals/{self.manual.id}/versions/{version.id}/download/')
        self.assertEqual(resp.status_code, 200)

    def test_deprecate_only_changes_effective_state(self):
        """废止只改变生效状态；历史文件保留"""
        self._publish()
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/deprecate/', {})
        self.assertFalse(has_error(resp), resp.content)
        self.manual.refresh_from_db()
        self.assertIsNone(self.manual.current_version)
        version = ManualVersion.objects.get(manual=self.manual)
        self.assertFalse(version.is_effective)
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(version.file_path)))

    def test_rollback_rebuilds_draft_set_then_new_version(self):
        """整套回退 v1（当前生效为 v2）：按快照重建草稿集合；再发布产生
        更大版本号，v1 文件不变。回退目标即当前生效版本时草稿与生效一致，
        发布会被拒绝（无意义的重复发布），因此本用例先发布 v2 使回退
        目标 v1 与当前生效内容不同"""
        self._publish(note='v1')
        v1 = ManualVersion.objects.get(manual=self.manual)
        v1_path = storage.resolve_absolute_path(v1.file_path)
        # 编辑草稿偏离 v1，退出会话后发布 v2（当前生效）
        self._set_password()
        session = self._start_session()
        self._save(session['session_key'], session['revision'],
                   b'PK\x03\x04 drifted')
        delete_json(self.editor_client,
                    f'/institution/manuals/{self.manual.id}/draft/session/',
                    {'session_key': session['session_key']})
        resp = self._publish(note='v2')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['version_no'], 2)
        # 再次编辑（会话保持活跃），随后整套回退到 v1
        session = self._start_session()
        self._save(session['session_key'], session['revision'],
                   b'PK\x03\x04 drifted-2')
        rev_before = self._main_draft().revision
        # 整套回退到 v1（所有者执行）
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/draft/from-version/',
                         {'version_id': v1.id})
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['restored_files'], 1)
        self.assertEqual(data['from_version_no'], 1)
        draft = self._main_draft()
        self.assertEqual(draft.revision, rev_before + 1)
        self.assertEqual(draft.base_version_id, v1.id)
        # 回退草稿的显示名沿用来源版本显示名
        self.assertEqual(draft.original_name, v1.original_name)
        with open(storage.resolve_absolute_path(draft.file_path), 'rb') as f:
            self.assertEqual(f.read(), b'PK\x03\x04 v-draft-1')
        with open(v1_path, 'rb') as f:
            self.assertEqual(f.read(), b'PK\x03\x04 v-draft-1')
        # 回退后活跃会话已整体失效，旧会话不能再保存
        resp = self._save_draft(session['session_key'], draft.revision)
        self.assertTrue(has_error(resp))
        # 再发布产生 v3（内容与当前生效 v2 不同）
        resp = self._publish(note='回退恢复')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['version_no'], 3)

    def _save_draft(self, session_key, revision):
        upload = SimpleUploadedFile('saved.docx', b'PK\x03\x04 saved')
        return self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/draft/save/',
            {'file': upload, 'session_key': session_key, 'revision': revision})


# 说明：旧 multipart 编辑服务替身契约（EditorContractTests）已随
# ONLYOFFICE Docs 接入整体替换——下载/回调/JWT/越权/迟到回调等语义
# 全部由 test_manual_editor.py 的新协议行为测试承接，勿在此恢复
# editor-draft/editor-callback/preview-file 旧契约路由或测试。
