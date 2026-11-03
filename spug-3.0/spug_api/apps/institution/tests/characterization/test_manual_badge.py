# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提交待发布核对红点统计（GET /manuals/badge/）的真实行为测试

口径（2026-11-03 固定快照）：唯一实现
version_compare.count_handoff_badge，统计当前用户为所有者或持
can_publish 逐本授权的启用手册中，满足全部条件的制度文件数——
未移除；有效负责人非空且非当前用户（本人负责的文件本人发布无需交接）；
草稿有效（file_path 非空）；存在修订号与当前草稿一致的 pending
ManualSubmission 固定快照；该文件相对当前生效版本为新增或内容变化
（无 current_version 视为新增；哈希相同=未变化不计；已随发布消费的
提交自然不计）。响应键与 layout/expiryBadgeStoreBase.js 契约一致
（count/expiring_count/expired_count）。轻量提示计数不做物理文件
stat，权威核对仍在 publish-preview/publish。
"""
from django.test import TestCase
from django.utils import timezone

from apps.institution.models import (
    Manual, ManualDraft, ManualFile, ManualSubmission, ManualVersion,
    ManualVersionFile,
)
from apps.institution.tests.base import (
    PERM_PUBLISH, PERM_VIEW, get_data, has_error, make_client, make_grant,
    make_user, setup_test_env,
)


def _manual(name='红点手册', owner=None, status=Manual.STATUS_ACTIVE):
    return Manual.objects.create(
        name=name, code=f'BD-{name[-2:]}',
        org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
        owner=owner, status=status, tenant_id='deptA')


def _file(manual, name='文件.docx', owner=None, is_removed=False,
          sort_order=0):
    return ManualFile.objects.create(
        manual=manual, display_name=name, sort_order=sort_order,
        owner=owner, owner_name=(owner.nickname or owner.username)
        if owner else '', is_removed=is_removed)


def _draft(file_entry, revision=1, file_hash='hash-v1', file_path=None):
    path = file_path
    if path is None:
        path = (f'drafts/badge/{file_entry.manual_id}/'
                f'{file_entry.id}.docx')
    return ManualDraft.objects.create(
        manual=file_entry.manual, file=file_entry, file_path=path,
        original_name=file_entry.display_name, revision=revision,
        file_hash=file_hash)


def _submitted(file_entry, revision):
    """直接落库构造"待发布人核对"提交（红点只读判定，不复制物理快照）

    2026-11-03 起有效提交以 ManualSubmission 固定快照行判定；红点只做
    DB 判定（修订号/负责人/哈希），不 stat 物理文件，故无需真实副本。
    """
    draft = ManualDraft.objects.get(file=file_entry)
    return ManualSubmission.objects.create(
        manual=file_entry.manual, file=file_entry,
        draft_revision=revision, file_path=draft.file_path,
        original_name=draft.original_name, file_size=draft.file_size,
        file_hash=draft.file_hash, status=ManualSubmission.STATUS_PENDING,
        submitted_by_name='负责人', submitted_at=timezone.now())


def _pending_file(manual, owner, name='待发布.docx', revision=1,
                  file_hash='hash-v1', is_removed=False):
    """新增/变化 + 负责人 + 有效提交 = 应计入红点"""
    file_entry = _file(manual, name=name, owner=owner,
                       is_removed=is_removed)
    _draft(file_entry, revision=revision, file_hash=file_hash)
    _submitted(file_entry, revision)
    return file_entry


def _snapshot_version(manual, published_by, rows):
    """构造当前生效版本（rows = [(file_entry, file_hash)]）"""
    version = ManualVersion.objects.create(
        manual=manual, version_no=1,
        file_path='versions/badge/seed.docx', original_name='seed.docx',
        published_by=published_by)
    for file_entry, file_hash in rows:
        ManualVersionFile.objects.create(
            version=version, manual_file=file_entry,
            display_name=file_entry.display_name,
            sort_order=file_entry.sort_order,
            file_path='versions/badge/seed.docx', file_hash=file_hash)
    manual.current_version = version
    manual.save(update_fields=['current_version'])
    return version


class InstitutionBadgeTests(TestCase):
    """GET /institution/manuals/badge/ 统计口径与权限门"""

    def setUp(self):
        setup_test_env()
        # 持 publish 页面权限码 + can_publish 授权的红点消费者
        self.publisher = make_user('pub', tenant_id='deptA',
                                   perms=[PERM_PUBLISH, PERM_VIEW])
        self.publisher_client = make_client(self.publisher)
        self.editor = make_user('ed', tenant_id='deptA')
        self.editor2 = make_user('ed2', tenant_id='deptA')
        self.manual = _manual()
        make_grant(self.manual, self.publisher, can_publish=True)
        make_grant(self.manual, self.editor, can_edit=True)
        make_grant(self.manual, self.editor2, can_edit=True)
        # 本次新增（无生效版本）+ 负责人非发布人 + 提交有效 = 1
        self.pending = _pending_file(self.manual, self.editor)

    def _badge(self, client=None):
        return (client or self.publisher_client).get(
            '/institution/manuals/badge/')

    def test_response_contract_keys_and_basic_count(self):
        resp = self._badge()
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(set(data.keys()),
                         {'count', 'expiring_count', 'expired_count'})
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['expiring_count'], 0)
        self.assertEqual(data['expired_count'], 0)

    def test_stale_submission_not_counted(self):
        stale = _file(self.manual, name='过期.docx', owner=self.editor2)
        _draft(stale, revision=5, file_hash='hash-v1')
        _submitted(stale, 2)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_missing_draft_file_not_counted(self):
        empty = _file(self.manual, name='空草稿.docx', owner=self.editor2)
        _draft(empty, revision=1, file_path='')
        _submitted(empty, 1)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_removed_file_not_counted(self):
        _pending_file(self.manual, self.editor2, name='已移除.docx',
                      is_removed=True)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_archived_manual_not_counted(self):
        archived = _manual(name='归档手册', status=Manual.STATUS_ARCHIVED)
        make_grant(archived, self.publisher, can_publish=True)
        _pending_file(archived, self.editor2)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_unassigned_file_not_counted(self):
        """未分配负责人：无交接对象，不计（即使存在历史提交记录）"""
        unassigned = _file(self.manual, name='未分配.docx')
        _draft(unassigned, revision=1)
        _submitted(unassigned, 1)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_owner_self_file_not_counted(self):
        """本人负责的文件本人发布无需交接：即使提交有效也不计"""
        own = _file(self.manual, name='自己的.docx', owner=self.publisher)
        _draft(own, revision=1)
        _submitted(own, 1)
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_can_edit_only_grant_not_counted(self):
        """仅 can_edit 授权（非所有者、无 can_publish）不进红点可见集合"""
        editor = make_user('badge-ed', tenant_id='deptB',
                           perms=[PERM_PUBLISH, PERM_VIEW])
        make_grant(self.manual, editor, can_edit=True)
        self.assertEqual(
            get_data(self._badge(make_client(editor)))['count'], 0)

    def test_owner_counted_without_grant(self):
        """所有者（无逐本授权）计入其手册中他人负责的待交接文件"""
        owner = make_user('badge-owner', tenant_id='deptB',
                          perms=[PERM_PUBLISH, PERM_VIEW])
        owned = _manual(name='所有者手册', owner=owner)
        _pending_file(owned, self.editor)
        self.assertEqual(
            get_data(self._badge(make_client(owner)))['count'], 1)
        # 非所有者且无授权的消费者看不到该手册
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_granted_and_owned_manuals_union_counted(self):
        """所有者∪授权并集：同一账号名下多本手册的待交接合计"""
        owner = make_user('badge-multi', tenant_id='deptB',
                          perms=[PERM_PUBLISH, PERM_VIEW])
        owned = _manual(name='并集手册甲', owner=owner)
        _pending_file(owned, self.editor)
        granted = _manual(name='并集手册乙')
        make_grant(granted, owner, can_publish=True)
        _pending_file(granted, self.editor)
        # 授权手册中一份未提交
        not_submitted = _file(granted, name='未提交.docx', owner=self.editor)
        _draft(not_submitted, revision=1)
        self.assertEqual(
            get_data(self._badge(make_client(owner)))['count'], 2)

    def test_unchanged_from_current_version_not_counted(self):
        """相对当前生效版本未变化（哈希相同）不计，变化/新增才计

        setUp 中已有一份"无生效版本=新增"的 pending（计 1），本用例再建
        未变化（不计）与已变化（计 1），故合计 3；同时钉死计数只按
        当前草稿修订号有效的 pending 快照。
        """
        unchanged = _pending_file(self.manual, self.editor2,
                                  name='未变化.docx', revision=2,
                                  file_hash='hash-v1')
        changed = _pending_file(self.manual, self.editor2,
                                name='已变化.docx', revision=3,
                                file_hash='hash-v2')
        _snapshot_version(self.manual, self.publisher,
                          [(unchanged, 'hash-v1'), (changed, 'hash-v1')])
        self.assertEqual(get_data(self._badge())['count'], 3)

    def test_consumed_submission_not_counted(self):
        """已随发布消费（status=published）的提交不再计入

        setUp 中另有一份新增 pending（计 1），本行发布后状态置 published，
        因此仍为 1（若误把已消费记录计入会变 2）。
        """
        published = _file(self.manual, name='已发布.docx', owner=self.editor2)
        _draft(published, revision=1)
        submission = _submitted(published, 1)
        submission.status = ManualSubmission.STATUS_PUBLISHED
        submission.consumed_at = timezone.now()
        submission.save(update_fields=['status', 'consumed_at'])
        _snapshot_version(self.manual, self.publisher,
                          [(published, 'hash-v1')])
        self.assertEqual(get_data(self._badge())['count'], 1)

    def test_publish_page_perm_gate(self):
        """@auth('institution.manual.publish') 功能资格门：仅持
        can_publish 授权而无 publish 页面权限码的账号返回"权限拒绝"""
        grant_only = make_user('grant-only', tenant_id='deptB',
                               perms=[PERM_VIEW])
        make_grant(self.manual, grant_only, can_publish=True)
        resp = self._badge(make_client(grant_only))
        self.assertTrue(has_error(resp))
        self.assertIn('权限拒绝', resp.json()['error'])
