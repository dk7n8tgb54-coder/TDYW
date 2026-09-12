# -*- coding: utf-8 -*-
"""系统版本更新日志行为测试

覆盖：
- 未发布日志不会返回给普通用户
- 已读状态能够正确保存
- 更新日志面向全平台所有用户（跨租户可见）
- 角色范围限制有效
- 重要更新确认状态有效
- 管理端权限校验与仅超级管理员可管理
"""
import json
from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.account.models import Role
from apps.release.models import ReleaseNote, ReleaseNoteRead, ReleaseNoteRole
from apps.setting.models import UserSetting

TENANT_A = 'tenant_a'
TENANT_B = 'tenant_b'

ADMIN_PERMS = [
    'system.release_note.view',
    'system.release_note.add',
    'system.release_note.edit',
    'system.release_note.del',
    'system.release_note.publish',
]


class ReleaseNoteApiTest(TestCase):
    """用户端接口行为"""

    def setUp(self):
        setup_test_env(self)
        self.supper = self._make_user('rel_supper', [], is_supper=True, tenant='admin')
        self.admin = self._make_user('rel_admin', ADMIN_PERMS, tenant=TENANT_A)
        self.user_a = self._make_user('rel_user_a', [], tenant=TENANT_A)
        self.user_b = self._make_user('rel_user_b', [], tenant=TENANT_B)
        self.no_perm = self._make_user('rel_noperm', [], tenant=TENANT_A)

        self.c_supper = make_client(self.supper)
        self.c_admin = make_client(self.admin)
        self.c_a = make_client(self.user_a)
        self.c_b = make_client(self.user_b)
        self.c_noperm = make_client(self.no_perm)

    def _make_user(self, username, perms, tenant, is_supper=False):
        user = make_user(username, perms, is_supper=is_supper)
        user.tenant_id = tenant
        user.save(update_fields=['tenant_id'])
        return user

    def _make_role(self, name, perms=None):
        return Role.objects.create(
            name=name,
            desc=name,
            page_perms=json.dumps(perms or {}),
            created_by=self.supper,
        )

    def _create_note(self, is_published=True, is_required=False, version='v3.3.3',
                     title='本次更新', role_ids=None, offset_minutes=-5):
        # 可见范围固定全平台：由平台侧（超管租户）创建，跨租户可见
        note = ReleaseNote.objects.create(
            tenant_id='admin',
            version=version,
            title=title,
            content='更新内容：%s' % title,
            is_published=is_published,
            is_required=is_required,
            publish_at=timezone.now() + timedelta(minutes=offset_minutes) if is_published else None,
            created_by_id=self.supper.id,
            created_by_name=self.supper.nickname,
        )
        for rid in role_ids or []:
            ReleaseNoteRole.objects.create(note=note, role_id=rid, tenant_id='admin')
        return note

    # ==================== 版本接口 ====================

    def test_version_api_returns_settings_version(self):
        resp = self.c_a.get('/system/version/')
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(body['error'])
        self.assertEqual(body['data']['version'], settings.SPUG_VERSION)

    # ==================== 发布状态 ====================

    def test_unpublished_note_not_returned_to_user(self):
        self._create_note(is_published=False)

        unread = self.c_a.get('/system/release-notes/unread/').json()
        self.assertFalse(unread['error'])
        self.assertEqual(unread['data']['unread_count'], 0)
        self.assertEqual(unread['data']['items'], [])

        listed = self.c_a.get('/system/release-notes/').json()
        self.assertFalse(listed['error'])
        self.assertEqual(listed['data']['total'], 0)

    def test_published_note_is_listed_for_user(self):
        self._create_note()
        listed = self.c_a.get('/system/release-notes/').json()
        self.assertFalse(listed['error'])
        self.assertEqual(listed['data']['total'], 1)
        item = listed['data']['items'][0]
        self.assertEqual(item['version'], 'v3.3.3')
        self.assertEqual(item['title'], '本次更新')
        self.assertFalse(item['is_read'])
        self.assertEqual(listed['data']['current_version'], settings.SPUG_VERSION)

    def test_future_publish_at_note_is_hidden(self):
        self._create_note(offset_minutes=30)
        unread = self.c_a.get('/system/release-notes/unread/').json()
        self.assertEqual(unread['data']['unread_count'], 0)

    # ==================== 已读状态 ====================

    def test_mark_read_is_persisted(self):
        note = self._create_note()

        before = self.c_a.get('/system/release-notes/unread/').json()['data']
        self.assertEqual(before['unread_count'], 1)

        resp = self.c_a.post(
            '/system/release-notes/%s/read/' % note.id,
            data=json.dumps({}), content_type='application/json')
        self.assertFalse(resp.json()['error'])

        self.assertTrue(ReleaseNoteRead.objects.filter(
            note=note, user_id=self.user_a.id).exists())

        after = self.c_a.get('/system/release-notes/unread/').json()['data']
        self.assertEqual(after['unread_count'], 0)

        listed = self.c_a.get('/system/release-notes/').json()['data']['items'][0]
        self.assertTrue(listed['is_read'])

    def test_read_is_isolated_between_users(self):
        note = self._create_note(title='全平台更新')
        self.assertEqual(
            self.c_b.get('/system/release-notes/unread/').json()['data']['unread_count'], 1)

        self.c_a.post('/system/release-notes/%s/read/' % note.id,
                      data=json.dumps({}), content_type='application/json')

        self.assertEqual(
            self.c_a.get('/system/release-notes/unread/').json()['data']['unread_count'], 0)
        # 同一条日志，另一个用户仍为未读
        self.assertEqual(
            self.c_b.get('/system/release-notes/unread/').json()['data']['unread_count'], 1)
        self.assertFalse(ReleaseNoteRead.objects.filter(
            note=note, user_id=self.user_b.id).exists())

    def test_detail_returns_content_and_title(self):
        note = self._create_note(title='新增批量移动')
        body = self.c_a.get('/system/release-notes/%s/' % note.id).json()
        self.assertFalse(body['error'])
        self.assertEqual(body['data']['title'], '新增批量移动')
        self.assertEqual(body['data']['content'], '更新内容：新增批量移动')

    # ==================== 全平台可见 ====================

    def test_note_visible_across_tenants(self):
        note = self._create_note(title='全平台更新')

        # 不同租户的用户都能看到同一条更新日志
        self.assertEqual(
            self.c_a.get('/system/release-notes/unread/').json()['data']['unread_count'], 1)
        self.assertEqual(
            self.c_b.get('/system/release-notes/unread/').json()['data']['unread_count'], 1)

        # 跨租户用户可读取详情并标记已读
        body = self.c_b.get('/system/release-notes/%s/' % note.id).json()
        self.assertFalse(body['error'])
        self.assertEqual(body['data']['title'], '全平台更新')

        resp = self.c_b.post('/system/release-notes/%s/read/' % note.id,
                             data=json.dumps({}), content_type='application/json')
        self.assertFalse(resp.json()['error'])
        self.assertTrue(ReleaseNoteRead.objects.filter(
            note=note, user_id=self.user_b.id).exists())

    # ==================== 角色范围 ====================

    def test_role_scope_limits_visibility(self):
        role_target = self._make_role('目标角色')
        role_other = self._make_role('其他角色')
        note = self._create_note(role_ids=[role_target.id])

        self.user_a.roles.add(role_target)
        self.user_b.roles.add(role_other)
        # 权限缓存按角色版本失效，显式刷新避免读到旧缓存
        self.user_a.set_perms_cache()
        self.user_b.set_perms_cache()

        self.assertEqual(
            self.c_a.get('/system/release-notes/unread/').json()['data']['unread_count'], 1)
        # 角色不匹配的用户（无论哪个租户）看不到
        self.assertEqual(
            self.c_b.get('/system/release-notes/unread/').json()['data']['unread_count'], 0)

        # 无任何角色的用户同样看不到限定了角色的日志
        user_no_role = self._make_user('rel_user_a2', [], tenant=TENANT_A)
        client_no_role = make_client(user_no_role)
        self.assertEqual(
            client_no_role.get('/system/release-notes/unread/').json()['data']['unread_count'], 0)
        self.assertTrue(ReleaseNoteRole.objects.filter(note=note).exists())

    # ==================== 重要更新确认 ====================

    def test_required_note_must_be_acknowledged(self):
        note = self._create_note(is_required=True, title='重要变更：权限模型调整')

        self.c_a.post('/system/release-notes/%s/read/' % note.id,
                      data=json.dumps({}), content_type='application/json')
        read = ReleaseNoteRead.objects.get(note=note, user_id=self.user_a.id)
        self.assertIsNotNone(read.read_at)
        self.assertFalse(read.is_acknowledged)

        # 仅已读、未确认：仍属于未处理，接口继续返回
        pending = self.c_a.get('/system/release-notes/unread/').json()['data']
        self.assertEqual(pending['unread_count'], 1)
        self.assertTrue(pending['has_required'])

        ack = self.c_a.post('/system/release-notes/%s/ack/' % note.id,
                            data=json.dumps({}), content_type='application/json')
        self.assertFalse(ack.json()['error'])

        read.refresh_from_db()
        self.assertTrue(read.is_acknowledged)
        self.assertIsNotNone(read.acknowledged_at)

        after = self.c_a.get('/system/release-notes/unread/').json()['data']
        self.assertEqual(after['unread_count'], 0)

    def test_required_note_flag_in_detail(self):
        note = self._create_note(is_required=True)
        body = self.c_a.get('/system/release-notes/%s/' % note.id).json()['data']
        self.assertTrue(body['is_required'])


class ReleaseNoteAdminApiTest(TestCase):
    """管理端接口行为：更新日志面向全平台，仅超级管理员可管理"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('rel_supper2', [], is_supper=True)
        self.supper.tenant_id = 'admin'
        self.supper.save(update_fields=['tenant_id'])
        self.admin = make_user('rel_admin2', ADMIN_PERMS)
        self.admin.tenant_id = TENANT_A
        self.admin.save(update_fields=['tenant_id'])
        self.user = make_user('rel_user2', [])
        self.user.tenant_id = TENANT_A
        self.user.save(update_fields=['tenant_id'])
        self.noperm = make_user('rel_noperm2', [])
        self.noperm.tenant_id = TENANT_A
        self.noperm.save(update_fields=['tenant_id'])

        self.c_supper = make_client(self.supper)
        self.c_admin = make_client(self.admin)
        self.c_user = make_client(self.user)
        self.c_noperm = make_client(self.noperm)

    def _create_payload(self, **overrides):
        payload = {
            'version': 'v3.4.0',
            'title': '新增资料库批量移动',
            'content': '支持批量移动文件',
        }
        payload.update(overrides)
        return payload

    def test_admin_list_requires_permission(self):
        self.assertTrue(self.c_noperm.get('/system/release-notes/admin/').json()['error'])
        self.assertFalse(self.c_admin.get('/system/release-notes/admin/').json()['error'])

    def test_non_supper_cannot_create_even_with_perms(self):
        resp = self.c_admin.post(
            '/system/release-notes/admin/',
            data=json.dumps(self._create_payload()),
            content_type='application/json')
        self.assertTrue(resp.json()['error'])
        self.assertFalse(ReleaseNote.objects.filter(version='v3.4.0').exists())

    def test_supper_create_publish_and_user_sees_it(self):
        resp = self.c_supper.post(
            '/system/release-notes/admin/',
            data=json.dumps(self._create_payload(is_required=True)),
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body['error'])
        note_id = body['data']['id']
        self.assertEqual(body['data']['title'], '新增资料库批量移动')
        self.assertFalse(ReleaseNote.objects.get(id=note_id).is_published)

        # 未发布前用户看不到
        self.assertEqual(
            self.c_user.get('/system/release-notes/unread/').json()['data']['unread_count'], 0)

        published = self.c_supper.post(
            '/system/release-notes/admin/%s/publish/' % note_id,
            data=json.dumps({'is_published': True}), content_type='application/json')
        self.assertFalse(published.json()['error'])

        unread = self.c_user.get('/system/release-notes/unread/').json()['data']
        self.assertEqual(unread['unread_count'], 1)
        self.assertEqual(unread['items'][0]['version'], 'v3.4.0')
        self.assertTrue(ReleaseNote.objects.get(id=note_id).is_required)

    def test_non_supper_cannot_publish_or_delete(self):
        created = self.c_supper.post(
            '/system/release-notes/admin/',
            data=json.dumps(self._create_payload(version='v3.5.0')),
            content_type='application/json').json()['data']

        denied_publish = self.c_admin.post(
            '/system/release-notes/admin/%s/publish/' % created['id'],
            data=json.dumps({'is_published': True}), content_type='application/json')
        self.assertTrue(denied_publish.json()['error'])
        self.assertFalse(ReleaseNote.objects.get(id=created['id']).is_published)

        denied_delete = self.c_admin.delete(
            '/system/release-notes/admin/',
            data=json.dumps({'id': created['id']}), content_type='application/json')
        self.assertTrue(denied_delete.json()['error'])
        self.assertTrue(ReleaseNote.objects.filter(id=created['id']).exists())

    def test_supper_delete_removes_note_and_relations(self):
        created = self.c_supper.post(
            '/system/release-notes/admin/',
            data=json.dumps(self._create_payload(version='v3.5.1')),
            content_type='application/json').json()['data']
        ReleaseNoteRole.objects.create(
            note_id=created['id'], role_id=1, tenant_id='admin')

        ok = self.c_supper.delete(
            '/system/release-notes/admin/',
            data=json.dumps({'id': created['id']}), content_type='application/json')
        self.assertFalse(ok.json()['error'])
        self.assertFalse(ReleaseNote.objects.filter(id=created['id']).exists())
        self.assertFalse(ReleaseNoteRole.objects.filter(note_id=created['id']).exists())

    def test_supper_update_note(self):
        created = self.c_supper.post(
            '/system/release-notes/admin/',
            data=json.dumps(self._create_payload(version='v3.6.0')),
            content_type='application/json').json()['data']

        updated = self.c_supper.post(
            '/system/release-notes/admin/',
            data=json.dumps({
                'id': created['id'], 'version': 'v3.6.0', 'title': '修订标题',
                'content': '修订内容', 'is_required': True,
            }),
            content_type='application/json')
        self.assertFalse(updated.json()['error'])
        note = ReleaseNote.objects.get(id=created['id'])
        self.assertEqual(note.title, '修订标题')
        self.assertEqual(note.content, '修订内容')
        self.assertTrue(note.is_required)


class ReleaseNoteSettingsApiTest(TestCase):
    """「每次更新后自动弹出更新日志」用户偏好（每用户独立控制）"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('rel_set_supper', [], is_supper=True)
        self.supper.tenant_id = 'admin'
        self.supper.save(update_fields=['tenant_id'])
        self.user_a = make_user('rel_set_user_a', [])
        self.user_a.tenant_id = TENANT_A
        self.user_a.save(update_fields=['tenant_id'])
        self.user_b = make_user('rel_set_user_b', [])
        self.user_b.tenant_id = TENANT_B
        self.user_b.save(update_fields=['tenant_id'])

        self.c_supper = make_client(self.supper)
        self.c_a = make_client(self.user_a)
        self.c_b = make_client(self.user_b)

    def _put_settings(self, client, show_after_update):
        return client.put(
            '/system/release-notes/settings/',
            data=json.dumps({'show_after_update': show_after_update}),
            content_type='application/json')

    def test_default_is_enabled_for_fresh_user(self):
        # 默认勾选：未设置偏好的用户，未读接口与设置接口都返回 True
        unread = self.c_a.get('/system/release-notes/unread/').json()
        self.assertFalse(unread['error'])
        self.assertTrue(unread['data']['show_after_update'])

        got = self.c_a.get('/system/release-notes/settings/').json()
        self.assertFalse(got['error'])
        self.assertTrue(got['data']['show_after_update'])

    def test_user_updates_own_preference(self):
        resp = self._put_settings(self.c_a, False)
        self.assertFalse(resp.json()['error'])
        self.assertFalse(resp.json()['data']['show_after_update'])

        # 真实落库（user_settings 表），读取接口与未读接口同步反映
        self.assertTrue(UserSetting.objects.filter(
            user=self.user_a, key='release_note_popup', value='false').exists())
        got = self.c_a.get('/system/release-notes/settings/').json()
        self.assertFalse(got['data']['show_after_update'])
        unread = self.c_a.get('/system/release-notes/unread/').json()
        self.assertFalse(unread['data']['show_after_update'])

        # 重新开启
        resp = self._put_settings(self.c_a, True)
        self.assertFalse(resp.json()['error'])
        self.assertTrue(UserSetting.objects.filter(
            user=self.user_a, key='release_note_popup', value='true').exists())

    def test_preference_is_isolated_between_users(self):
        self._put_settings(self.c_a, False)

        # 用户 B 未受影响，仍默认勾选
        got_b = self.c_b.get('/system/release-notes/settings/').json()
        self.assertTrue(got_b['data']['show_after_update'])
        unread_b = self.c_b.get('/system/release-notes/unread/').json()
        self.assertTrue(unread_b['data']['show_after_update'])
        self.assertFalse(UserSetting.objects.filter(user=self.user_b).exists())

    def test_update_requires_boolean(self):
        resp = self.c_a.put(
            '/system/release-notes/settings/',
            data=json.dumps({'show_after_update': 'yes'}),
            content_type='application/json')
        self.assertTrue(resp.json()['error'])
        # 非法参数不写入配置
        self.assertFalse(UserSetting.objects.filter(user=self.user_a).exists())
