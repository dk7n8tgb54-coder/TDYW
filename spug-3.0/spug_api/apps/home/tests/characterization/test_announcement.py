# -*- coding: utf-8 -*-
"""公告管理模块特征测试

覆盖：
- 草稿 CRUD（创建/编辑/详情/删除）
- 发布/撤回状态流转
- 可见性规则（scope_type, 时间区间, 租户范围）
- 已读/未读追踪
- 权限检查（view/add/edit/delete/publish/withdraw）
- 租户隔离（管理端）
- 跨租户可见性（用户端）
- 列表筛选/分页/搜索
- 表单校验（标题/内容/时间/范围）
- 软删除行为
- 已发布不能直接编辑（需先撤回）
- 删除自动撤回
- 审计事件
- HTTP 200 + error 协议
"""
import json
import time
from datetime import datetime, timedelta
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.account.models import User, Role, Tenant
from apps.setting.utils import AppSetting
from apps.home.models import (
    Announcement, AnnouncementScope, AnnouncementRead,
    visible_announcements_for_user,
    SCOPE_ALL, SCOPE_TENANT,
    STATUS_UNPUBLISHED, STATUS_PUBLISHED, STATUS_EXPIRED,
)
from apps.utils.test_helpers import setup_test_env


# ============================================================
# 测试辅助
# ============================================================

def _make_user(username, is_supper=False, tenant_id='default', is_active=True):
    token = (username * 10)[:32]
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=is_active, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return client


def _grant_perms(user, perms):
    perm_dict = {}
    for module, page, keys in perms:
        perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)
    role_name = f'role_{user.username}'
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


ANN_PERMS = [('home', 'announcement', [
    'view', 'add', 'edit', 'delete', 'publish', 'withdraw',
])]


def _make_announcement(user, **kwargs):
    """直接创建公告"""
    defaults = {
        'tenant_id': user.tenant_id,
        'title': '测试公告',
        'content': '公告内容',
        'scope_type': SCOPE_ALL,
        'effective_start_at': timezone.now() - timedelta(hours=1),
        'effective_end_at': None,
        'is_important': False,
        'status': STATUS_PUBLISHED,
        'published_at': timezone.now(),
        'published_by_id': user.id,
        'published_by_name': user.nickname,
        'created_by_id': user.id,
        'created_by_name': user.nickname,
        'publish_department_id': user.tenant_id,
        'publish_department_name': user.tenant_id,
    }
    defaults.update(kwargs)
    return Announcement.objects.create(**defaults)


ADMIN_URL = '/home/announcement/admin/'


# ============================================================
# 草稿 CRUD 测试
# ============================================================

class AnnouncementCRUDTests(TestCase):
    """公告草稿 CRUD 测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ANN_PERMS)
        self.client = _make_client(self.user)

    def _post(self, data):
        return self.client.post(ADMIN_URL, data=json.dumps(data), content_type='application/json')

    def test_create_draft_success(self):
        """创建草稿成功"""
        resp = self._post({
            'title': '新公告',
            'content': '内容',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2026-08-08 09:00:00',
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        ann = Announcement.objects.get(title='新公告')
        self.assertEqual(ann.status, STATUS_UNPUBLISHED)
        self.assertEqual(ann.created_by_id, self.user.id)
        self.assertIsNone(ann.published_at)

    def test_create_missing_title(self):
        """缺少标题"""
        resp = self._post({
            'content': '内容',
            'scope_type': SCOPE_ALL,
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_content(self):
        """缺少内容"""
        resp = self._post({
            'title': '标题',
            'scope_type': SCOPE_ALL,
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_scope_type(self):
        """缺少 scope_type"""
        resp = self._post({
            'title': '标题',
            'content': '内容',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_invalid_scope_type(self):
        """非法 scope_type"""
        resp = self._post({
            'title': '标题',
            'content': '内容',
            'scope_type': 'invalid',
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_tenant_scope_without_targets(self):
        """指定部门范围但未选择部门"""
        resp = self._post({
            'title': '标题',
            'content': '内容',
            'scope_type': SCOPE_TENANT,
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_with_invalid_tenant_ids(self):
        """无效的部门 ID"""
        resp = self._post({
            'title': '标题',
            'content': '内容',
            'scope_type': SCOPE_TENANT,
            'target_tenant_ids': ['nonexistent'],
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_missing_effective_start(self):
        """缺少生效开始时间"""
        resp = self._post({
            'title': '标题',
            'content': '内容',
            'scope_type': SCOPE_ALL,
        })
        self.assertTrue(resp.json().get('error'))

    def test_create_end_before_start(self):
        """结束时间早于开始时间"""
        resp = self._post({
            'title': '标题',
            'content': '内容',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2026-08-10 09:00:00',
            'effective_end_at': '2026-08-08 09:00:00',
        })
        self.assertTrue(resp.json().get('error'))

    def test_edit_draft_success(self):
        """编辑草稿成功"""
        ann = _make_announcement(self.user, status=STATUS_UNPUBLISHED, published_at=None,
                                  published_by_id=None, published_by_name='')
        resp = self._post({
            'id': ann.id,
            'title': '修改后标题',
            'content': '修改后内容',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2026-08-08 09:00:00',
        })
        self.assertFalse(resp.json().get('error'))
        ann.refresh_from_db()
        self.assertEqual(ann.title, '修改后标题')

    def test_edit_published_blocked(self):
        """已发布公告不能直接编辑"""
        ann = _make_announcement(self.user, status=STATUS_PUBLISHED)
        resp = self._post({
            'id': ann.id,
            'title': '修改',
            'content': '修改',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2026-08-08 09:00:00',
        })
        self.assertTrue(resp.json().get('error'))

    def test_edit_nonexistent(self):
        """编辑不存在的公告"""
        resp = self._post({
            'id': 99999,
            'title': '修改',
            'content': '修改',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2026-08-08 09:00:00',
        })
        self.assertTrue(resp.json().get('error'))

    def test_delete_success(self):
        """删除公告（软删除）"""
        ann = _make_announcement(self.user)
        resp = self.client.delete(f'{ADMIN_URL}{ann.id}/')
        self.assertFalse(resp.json().get('error'))
        ann.refresh_from_db()
        self.assertTrue(ann.is_deleted)
        self.assertIsNotNone(ann.deleted_at)

    def test_delete_published_auto_withdraw(self):
        """删除已发布公告先自动撤回"""
        ann = _make_announcement(self.user, status=STATUS_PUBLISHED)
        self.client.delete(f'{ADMIN_URL}{ann.id}/')
        ann.refresh_from_db()
        self.assertTrue(ann.is_deleted)
        self.assertIsNotNone(ann.withdrawn_at)

    def test_delete_nonexistent(self):
        """删除不存在的公告"""
        resp = self.client.delete(f'{ADMIN_URL}99999/')
        self.assertTrue(resp.json().get('error'))

    def test_admin_detail_success(self):
        """管理端详情"""
        ann = _make_announcement(self.user)
        resp = self.client.get(f'{ADMIN_URL}{ann.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['title'], ann.title)

    def test_admin_detail_nonexistent(self):
        """详情不存在"""
        resp = self.client.get(f'{ADMIN_URL}99999/')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 发布/撤回测试
# ============================================================

class AnnouncementPublishWithdrawTests(TestCase):
    """公告发布/撤回测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ANN_PERMS)
        self.client = _make_client(self.user)

    def test_publish_success(self):
        """发布成功"""
        ann = _make_announcement(self.user, status=STATUS_UNPUBLISHED,
                                  published_at=None, published_by_id=None, published_by_name='')
        resp = self.client.post(f'{ADMIN_URL}{ann.id}/publish/')
        self.assertFalse(resp.json().get('error'))
        ann.refresh_from_db()
        self.assertEqual(ann.status, STATUS_PUBLISHED)
        self.assertIsNotNone(ann.published_at)
        self.assertEqual(ann.published_by_id, self.user.id)

    def test_publish_already_published(self):
        """重复发布"""
        ann = _make_announcement(self.user, status=STATUS_PUBLISHED)
        resp = self.client.post(f'{ADMIN_URL}{ann.id}/publish/')
        self.assertTrue(resp.json().get('error'))

    def test_publish_nonexistent(self):
        """发布不存在的公告"""
        resp = self.client.post(f'{ADMIN_URL}99999/publish/')
        self.assertTrue(resp.json().get('error'))

    def test_withdraw_success(self):
        """撤回成功"""
        ann = _make_announcement(self.user, status=STATUS_PUBLISHED)
        resp = self.client.post(f'{ADMIN_URL}{ann.id}/withdraw/')
        self.assertFalse(resp.json().get('error'))
        ann.refresh_from_db()
        self.assertEqual(ann.status, STATUS_UNPUBLISHED)
        self.assertIsNotNone(ann.withdrawn_at)
        self.assertEqual(ann.withdrawn_by_id, self.user.id)

    def test_withdraft_unpublished(self):
        """撤回未发布公告"""
        ann = _make_announcement(self.user, status=STATUS_UNPUBLISHED,
                                  published_at=None, published_by_id=None, published_by_name='')
        resp = self.client.post(f'{ADMIN_URL}{ann.id}/withdraw/')
        self.assertTrue(resp.json().get('error'))

    def test_withdraw_then_republish(self):
        """撤回后重新发布"""
        ann = _make_announcement(self.user, status=STATUS_PUBLISHED)
        self.client.post(f'{ADMIN_URL}{ann.id}/withdraw/')
        ann.refresh_from_db()
        self.assertEqual(ann.status, STATUS_UNPUBLISHED)
        resp = self.client.post(f'{ADMIN_URL}{ann.id}/publish/')
        self.assertFalse(resp.json().get('error'))
        ann.refresh_from_db()
        self.assertEqual(ann.status, STATUS_PUBLISHED)
        self.assertIsNone(ann.withdrawn_at)


# ============================================================
# 可见性测试
# ============================================================

class AnnouncementVisibilityTests(TestCase):
    """公告可见性测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = _make_user('admin', tenant_id='t1')
        _grant_perms(self.admin, ANN_PERMS)

        self.user_t1 = _make_user('user_t1', tenant_id='t1')
        self.c_t1 = _make_client(self.user_t1)

        self.user_t2 = _make_user('user_t2', tenant_id='t2')
        self.c_t2 = _make_client(self.user_t2)

    def test_scope_all_visible_to_all_tenants(self):
        """全平台公告对所有租户可见"""
        ann = _make_announcement(self.admin, scope_type=SCOPE_ALL)
        resp = self.c_t1.get('/home/announcement/')
        body = resp.json()
        ids = [r['id'] for r in body['data']['results']]
        self.assertIn(ann.id, ids)
        resp = self.c_t2.get('/home/announcement/')
        body = resp.json()
        ids = [r['id'] for r in body['data']['results']]
        self.assertIn(ann.id, ids)

    def test_scope_tenant_only_visible_to_target(self):
        """指定部门公告仅目标租户可见"""
        ann = _make_announcement(self.admin, scope_type=SCOPE_TENANT)
        AnnouncementScope.objects.create(announcement=ann, tenant_id='t1', tenant_name='租户1')
        resp = self.c_t1.get('/home/announcement/')
        body = resp.json()
        ids = [r['id'] for r in body['data']['results']]
        self.assertIn(ann.id, ids)
        resp = self.c_t2.get('/home/announcement/')
        body = resp.json()
        ids = [r['id'] for r in body['data']['results']]
        self.assertNotIn(ann.id, ids)

    def test_unpublished_not_visible(self):
        """未发布公告对用户不可见"""
        ann = _make_announcement(self.admin, status=STATUS_UNPUBLISHED,
                                  published_at=None, published_by_id=None, published_by_name='')
        resp = self.c_t1.get('/home/announcement/')
        body = resp.json()
        ids = [r['id'] for r in body['data']['results']]
        self.assertNotIn(ann.id, ids)

    def test_deleted_not_visible(self):
        """已删除公告对用户不可见"""
        ann = _make_announcement(self.admin)
        ann.is_deleted = True
        ann.save()
        resp = self.c_t1.get('/home/announcement/')
        body = resp.json()
        ids = [r['id'] for r in body['data']['results']]
        self.assertNotIn(ann.id, ids)

    def test_future_start_not_visible(self):
        """生效开始时间在未来的公告不可见"""
        ann = _make_announcement(self.admin,
                                  effective_start_at=timezone.now() + timedelta(days=1))
        resp = self.c_t1.get('/home/announcement/')
        body = resp.json()
        ids = [r['id'] for r in body['data']['results']]
        self.assertNotIn(ann.id, ids)

    def test_expired_not_visible(self):
        """已过期公告不可见"""
        ann = _make_announcement(self.admin,
                                  effective_start_at=timezone.now() - timedelta(days=2),
                                  effective_end_at=timezone.now() - timedelta(hours=1))
        resp = self.c_t1.get('/home/announcement/')
        body = resp.json()
        ids = [r['id'] for r in body['data']['results']]
        self.assertNotIn(ann.id, ids)

    def test_detail_auto_mark_read(self):
        """详情自动标记已读"""
        ann = _make_announcement(self.admin)
        self.c_t1.get(f'/home/announcement/{ann.id}/')
        self.assertTrue(AnnouncementRead.objects.filter(
            announcement=ann, user_id=self.user_t1.id).exists())

    def test_manual_mark_read(self):
        """手动标记已读"""
        ann = _make_announcement(self.admin)
        resp = self.c_t1.post(f'/home/announcement/{ann.id}/read/')
        self.assertFalse(resp.json().get('error'))
        self.assertTrue(AnnouncementRead.objects.filter(
            announcement=ann, user_id=self.user_t1.id).exists())

    def test_mark_read_idempotent(self):
        """重复标记已读幂等"""
        ann = _make_announcement(self.admin)
        self.c_t1.post(f'/home/announcement/{ann.id}/read/')
        self.c_t1.post(f'/home/announcement/{ann.id}/read/')
        count = AnnouncementRead.objects.filter(
            announcement=ann, user_id=self.user_t1.id).count()
        self.assertEqual(count, 1)

    def test_detail_not_visible_to_non_target(self):
        """非目标租户不能查看详情"""
        ann = _make_announcement(self.admin, scope_type=SCOPE_TENANT)
        AnnouncementScope.objects.create(announcement=ann, tenant_id='t1', tenant_name='租户1')
        resp = self.c_t2.get(f'/home/announcement/{ann.id}/')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 已读/未读测试
# ============================================================

class AnnouncementReadStatusTests(TestCase):
    """公告已读/未读测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = _make_user('admin', tenant_id='t1')
        _grant_perms(self.admin, ANN_PERMS)
        self.user = _make_user('user', tenant_id='t1')
        self.c_user = _make_client(self.user)

    def test_unread_count(self):
        """未读数量"""
        ann1 = _make_announcement(self.admin, title='公告1')
        ann2 = _make_announcement(self.admin, title='公告2')
        resp = self.c_user.get('/home/announcement/unread-count/')
        body = resp.json()
        self.assertEqual(body['data']['count'], 2)

    def test_unread_count_after_read(self):
        """标记已读后未读减少"""
        ann = _make_announcement(self.admin)
        self.c_user.post(f'/home/announcement/{ann.id}/read/')
        resp = self.c_user.get('/home/announcement/unread-count/')
        body = resp.json()
        self.assertEqual(body['data']['count'], 0)

    def test_reminders_returns_unread(self):
        """reminders 返回未读公告"""
        ann1 = _make_announcement(self.admin, title='公告1')
        ann2 = _make_announcement(self.admin, title='公告2')
        resp = self.c_user.get('/home/announcement/reminders/')
        body = resp.json()
        self.assertEqual(len(body['data']), 2)

    def test_reminders_excludes_read(self):
        """reminders 不返回已读"""
        ann1 = _make_announcement(self.admin, title='公告1')
        ann2 = _make_announcement(self.admin, title='公告2')
        self.c_user.post(f'/home/announcement/{ann1.id}/read/')
        resp = self.c_user.get('/home/announcement/reminders/')
        body = resp.json()
        self.assertEqual(len(body['data']), 1)
        self.assertEqual(body['data'][0]['title'], '公告2')

    def test_read_status_filter(self):
        """按已读状态筛选"""
        ann1 = _make_announcement(self.admin, title='已读')
        ann2 = _make_announcement(self.admin, title='未读')
        self.c_user.post(f'/home/announcement/{ann1.id}/read/')
        resp = self.c_user.get('/home/announcement/?read_status=read')
        body = resp.json()
        titles = [r['title'] for r in body['data']['results']]
        self.assertIn('已读', titles)
        self.assertNotIn('未读', titles)
        resp = self.c_user.get('/home/announcement/?read_status=unread')
        body = resp.json()
        titles = [r['title'] for r in body['data']['results']]
        self.assertIn('未读', titles)
        self.assertNotIn('已读', titles)


# ============================================================
# 权限测试
# ============================================================

class AnnouncementPermissionTests(TestCase):
    """公告权限测试"""

    def setUp(self):
        setup_test_env(self)
        self.viewer = _make_user('viewer', tenant_id='t1')
        _grant_perms(self.viewer, [('home', 'announcement', ['view'])])
        self.c_viewer = _make_client(self.viewer)

        self.editor = _make_user('editor', tenant_id='t1')
        _grant_perms(self.editor, [('home', 'announcement', ['view', 'add', 'edit'])])
        self.c_editor = _make_client(self.editor)

        self.noperm = _make_user('noperm', tenant_id='t1')
        self.c_noperm = _make_client(self.noperm)

        self.supper = _make_user('supper', is_supper=True, tenant_id='t1')
        self.c_supper = _make_client(self.supper)

    def test_admin_view_with_permission(self):
        """有 view 权限可以列表"""
        resp = self.c_viewer.get(ADMIN_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('error'))

    def test_admin_view_without_permission(self):
        """无权限不能访问管理端"""
        resp = self.c_noperm.get(ADMIN_URL)
        self.assertTrue(resp.json().get('error'))

    def test_add_without_permission(self):
        """无 add 权限不能创建"""
        resp = self.c_viewer.post(ADMIN_URL, data=json.dumps({
            'title': '标题',
            'content': '内容',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2026-08-08 09:00:00',
        }), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_publish_without_permission(self):
        """无 publish 权限不能发布"""
        ann = _make_announcement(self.editor, status=STATUS_UNPUBLISHED,
                                  published_at=None, published_by_id=None, published_by_name='')
        resp = self.c_editor.post(f'{ADMIN_URL}{ann.id}/publish/')
        self.assertTrue(resp.json().get('error'))

    def test_withdraw_without_permission(self):
        """无 withdraw 权限不能撤回"""
        ann = _make_announcement(self.editor, status=STATUS_PUBLISHED)
        resp = self.c_editor.post(f'{ADMIN_URL}{ann.id}/withdraw/')
        self.assertTrue(resp.json().get('error'))

    def test_delete_without_permission(self):
        """无 delete 权限不能删除"""
        ann = _make_announcement(self.editor)
        resp = self.c_editor.delete(f'{ADMIN_URL}{ann.id}/')
        self.assertTrue(resp.json().get('error'))

    def test_user_list_no_permission_required(self):
        """用户端列表仅需登录"""
        ann = _make_announcement(self.editor)
        resp = self.c_noperm.get('/home/announcement/')
        body = resp.json()
        # 无权限用户也能看到全平台公告
        ids = [r['id'] for r in body['data']['results']]
        self.assertIn(ann.id, ids)

    def test_supper_bypasses_permission(self):
        """超级管理员绕过权限"""
        resp = self.c_supper.get(ADMIN_URL)
        self.assertFalse(resp.json().get('error'))


# ============================================================
# 管理端列表查询测试
# ============================================================

class AnnouncementAdminListTests(TestCase):
    """管理端公告列表查询测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ANN_PERMS)
        self.client = _make_client(self.user)

        self.ann1 = _make_announcement(self.user, title='公告1', status=STATUS_PUBLISHED)
        self.ann2 = _make_announcement(self.user, title='公告2', status=STATUS_UNPUBLISHED,
                                        published_at=None, published_by_id=None, published_by_name='')
        self.ann3 = _make_announcement(self.user, title='特殊关键词', status=STATUS_PUBLISHED)

    def test_list_default(self):
        """列表默认返回所有未删除"""
        resp = self.client.get(ADMIN_URL)
        body = resp.json()
        self.assertEqual(body['data']['total'], 3)

    def test_filter_by_status(self):
        """按状态筛选"""
        resp = self.client.get(f'{ADMIN_URL}?status={STATUS_PUBLISHED}')
        body = resp.json()
        self.assertEqual(body['data']['total'], 2)

    def test_search_by_keyword(self):
        """关键词搜索"""
        resp = self.client.get(f'{ADMIN_URL}?keyword=特殊')
        body = resp.json()
        self.assertEqual(body['data']['total'], 1)
        self.assertEqual(body['data']['results'][0]['title'], '特殊关键词')

    def test_pagination(self):
        """分页"""
        resp = self.client.get(f'{ADMIN_URL}?page=1&page_size=2')
        body = resp.json()
        self.assertEqual(len(body['data']['results']), 2)
        self.assertEqual(body['data']['total'], 3)

    def test_excludes_deleted(self):
        """不包含已删除"""
        self.ann1.is_deleted = True
        self.ann1.save()
        resp = self.client.get(ADMIN_URL)
        body = resp.json()
        self.assertEqual(body['data']['total'], 2)


# ============================================================
# 跨租户管理端隔离测试
# ============================================================

class AnnouncementAdminTenantTests(TestCase):
    """管理端跨租户隔离测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin_a = _make_user('admin_a', tenant_id='tenant_a')
        _grant_perms(self.admin_a, ANN_PERMS)
        self.c_a = _make_client(self.admin_a)

        self.admin_b = _make_user('admin_b', tenant_id='tenant_b')
        _grant_perms(self.admin_b, ANN_PERMS)
        self.c_b = _make_client(self.admin_b)

        self.supper = _make_user('supper', is_supper=True, tenant_id='tenant_a')
        self.c_supper = _make_client(self.supper)

    def test_admin_list_no_tenant_filter(self):
        """管理端列表不过滤租户（管理员可以看到所有公告）"""
        ann_a = _make_announcement(self.admin_a, title='A的公告')
        ann_b = _make_announcement(self.admin_b, title='B的公告')
        resp = self.c_a.get(ADMIN_URL)
        body = resp.json()
        titles = [r['title'] for r in body['data']['results']]
        self.assertIn('A的公告', titles)
        self.assertIn('B的公告', titles)

    def test_admin_delete_cross_tenant(self):
        """管理端可以跨租户删除（无租户过滤）"""
        ann_b = _make_announcement(self.admin_b)
        resp = self.c_a.delete(f'{ADMIN_URL}{ann_b.id}/')
        # 管理端不过滤租户，所以可以删除
        self.assertFalse(resp.json().get('error'))
        ann_b.refresh_from_db()
        self.assertTrue(ann_b.is_deleted)

    def test_admin_edit_cross_tenant(self):
        """管理端可以跨租户编辑"""
        ann_b = _make_announcement(self.admin_b, status=STATUS_UNPUBLISHED,
                                    published_at=None, published_by_id=None, published_by_name='')
        resp = self.c_a.post(ADMIN_URL, data=json.dumps({
            'id': ann_b.id,
            'title': 'A修改B的',
            'content': '内容',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2026-08-08 09:00:00',
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        ann_b.refresh_from_db()
        self.assertEqual(ann_b.title, 'A修改B的')


# ============================================================
# 部门列表测试
# ============================================================

class AnnouncementDepartmentsTests(TestCase):
    """可选发布部门测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ANN_PERMS)
        self.client = _make_client(self.user)

        Tenant.objects.create(id='t1', name='租户1')
        Tenant.objects.create(id='t2', name='租户2')

    def test_get_departments(self):
        """获取部门列表"""
        resp = self.client.get(f'{ADMIN_URL}departments/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        ids = [t['id'] for t in body['data']]
        self.assertIn('t1', ids)
        self.assertIn('t2', ids)


# ============================================================
# 定时发布测试
# ============================================================

class AnnouncementScheduledPublishTests(TestCase):
    """定时发布验证"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin', tenant_id='t1')
        _grant_perms(self.user, ANN_PERMS)
        self.client = _make_client(self.user)

    def test_no_scheduled_publish_field(self):
        """当前无定时发布功能"""
        resp = self.client.post(ADMIN_URL, data=json.dumps({
            'title': '标题',
            'content': '内容',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2026-08-08 09:00:00',
            'scheduled_publish_at': '2026-08-10 09:00:00',
        }), content_type='application/json')
        # scheduled_publish_at 不是已知字段，被忽略
        self.assertFalse(resp.json().get('error'))
        ann = Announcement.objects.get(title='标题')
        self.assertIsNone(getattr(ann, 'scheduled_publish_at', None))

    def test_future_effective_start_not_auto_published(self):
        """生效开始时间在未来但状态仍为 unpublished"""
        resp = self.client.post(ADMIN_URL, data=json.dumps({
            'title': '标题',
            'content': '内容',
            'scope_type': SCOPE_ALL,
            'effective_start_at': '2030-08-08 09:00:00',
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        ann = Announcement.objects.get(title='标题')
        self.assertEqual(ann.status, STATUS_UNPUBLISHED)
