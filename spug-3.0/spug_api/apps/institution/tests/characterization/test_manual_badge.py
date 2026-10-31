# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提交编制待发布红点统计（GET /manuals/badge/）的真实行为测试

口径（2026-10-31 第二轮权限模型）：提交编制是交给所有持发布授权账号
的交接状态——统计当前用户为所有者或持 can_publish 逐本授权的启用手册
中，未移除且提交编制有效（submission_revision 非空且等于关联草稿修订
号、草稿工作文件在库）的制度文件数；归档手册不计。响应键与
layout/expiryBadgeStoreBase.js 契约一致（count/expiring_count/
expired_count）。轻量提示计数不做物理文件 stat，权威核对仍在
publish-preview/publish。
"""
from django.test import TestCase
from django.utils import timezone

from apps.institution.models import Manual, ManualDraft, ManualFile
from apps.institution.tests.base import (
    PERM_PUBLISH, PERM_VIEW, get_data, has_error, make_client, make_grant,
    make_user, setup_test_env,
)


def _manual(name='红点手册', owner=None, status=Manual.STATUS_ACTIVE):
    return Manual.objects.create(
        name=name, code=f'BD-{name[-2:]}',
        org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
        owner=owner, status=status, tenant_id='deptA')


def _submitted_file(manual, name='文件.docx', draft_revision=3,
                    submission_revision=3, is_removed=False, submitter=None):
    """构造一份制度文件 + 草稿，可按需置为已提交（修订号可比对）"""
    file_entry = ManualFile.objects.create(
        manual=manual, display_name=name, sort_order=0,
        is_removed=is_removed)
    ManualDraft.objects.create(
        manual=manual, file=file_entry,
        file_path=f'drafts/badge/{manual.id}/{file_entry.id}.docx',
        revision=draft_revision)
    if submission_revision is not None:
        file_entry.submission_revision = submission_revision
        file_entry.submitted_at = timezone.now()
        file_entry.submitted_by = submitter
        file_entry.save(update_fields=['submission_revision', 'submitted_at',
                                       'submitted_by'])
    return file_entry


class InstitutionBadgeTests(TestCase):
    """GET /institution/manuals/badge/ 统计口径与权限门"""

    def setUp(self):
        setup_test_env()
        # 持 publish 页面权限码 + can_publish 授权的账号（红点消费者）
        self.publisher = make_user('pub', tenant_id='deptA',
                                   perms=[PERM_PUBLISH, PERM_VIEW])
        self.publisher_client = make_client(self.publisher)
        self.manual = _manual()
        make_grant(self.manual, self.publisher, can_publish=True)
        self.file_entry = _submitted_file(self.manual,
                                          submitter=self.publisher)

    def _badge(self, client=None):
        resp = (client or self.publisher_client).get(
            '/institution/manuals/badge/')
        return resp

    def test_response_contract_keys(self):
        resp = self._badge()
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(set(data.keys()),
                         {'count', 'expiring_count', 'expired_count'})
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['expiring_count'], 0)
        self.assertEqual(data['expired_count'], 0)

    def test_stale_submission_not_counted(self):
        """草稿推进后提交失效（submission_revision != draft.revision）"""
        _submitted_file(self.manual, name='过期.docx',
                        draft_revision=5, submission_revision=2,
                        submitter=self.publisher)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_missing_draft_file_not_counted(self):
        """草稿工作文件不在库（file_path 为空）不计"""
        _submitted_file(self.manual, name='空草稿.docx',
                        submitter=self.publisher)
        ManualDraft.objects.filter(
            file__display_name='空草稿.docx').update(file_path='')
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_removed_file_not_counted(self):
        _submitted_file(self.manual, name='已移除.docx', is_removed=True,
                        submitter=self.publisher)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_archived_manual_not_counted(self):
        archived = _manual(name='归档手册', status=Manual.STATUS_ARCHIVED)
        make_grant(archived, self.publisher, can_publish=True)
        _submitted_file(archived, submitter=self.publisher)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_owner_counted_without_grant(self):
        """所有者（无逐本授权）计入其手册的提交编制文件"""
        owner = make_user('badge-owner', tenant_id='deptB',
                          perms=[PERM_PUBLISH, PERM_VIEW])
        owned = _manual(name='所有者手册', owner=owner)
        _submitted_file(owned, submitter=owner)
        self.assertEqual(get_data(self._badge(make_client(owner)))['count'], 1)
        # 非所有者且无授权的消费者看不到该手册
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_can_edit_only_grant_not_counted(self):
        """仅 can_edit 授权（非所有者、无 can_publish）不计入"""
        editor = make_user('badge-ed', tenant_id='deptB',
                           perms=[PERM_PUBLISH, PERM_VIEW])
        make_grant(self.manual, editor, can_edit=True)
        self.assertEqual(get_data(self._badge(make_client(editor)))['count'],
                         0)

    def test_granted_and_owned_manuals_union_counted(self):
        """所有者∪授权并集：同一账号名下多本手册的提交合计"""
        owner = make_user('badge-multi', tenant_id='deptB',
                          perms=[PERM_PUBLISH, PERM_VIEW])
        owned = _manual(name='并集手册甲', owner=owner)
        _submitted_file(owned, submitter=owner)
        granted = _manual(name='并集手册乙')
        make_grant(granted, owner, can_publish=True)
        _submitted_file(granted, submitter=owner)
        # 授权手册中一份未提交
        _submitted_file(granted, name='未提交.docx', submission_revision=None)
        self.assertEqual(get_data(self._badge(make_client(owner)))['count'],
                         2)

    def test_publish_page_perm_gate(self):
        """@auth('institution.manual.publish') 功能资格门：仅持 can_publish
        授权而无 publish 页面权限码的账号返回"权限拒绝"""
        grant_only = make_user('grant-only', tenant_id='deptB',
                               perms=[PERM_VIEW])
        make_grant(self.manual, grant_only, can_publish=True)
        resp = self._badge(make_client(grant_only))
        self.assertTrue(has_error(resp))
        self.assertIn('权限拒绝', resp.json()['error'])
