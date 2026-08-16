# -*- coding: utf-8 -*-
"""
Bug 3 复现测试：编辑指定部门公告时发布范围丢失

缺陷描述：
  后端 Announcement.to_view() 不返回 _scope_tenant_ids 字段，
  前端编辑表单从详情接口获取数据后 target_tenant_ids 为空数组，
  保存时 _sync_scopes() 先清空再写入空列表，导致发布范围被清空。

复现路径：
  1. 创建 scope_type=tenant 的公告，并写入 2 条 AnnouncementScope
  2. GET 管理端详情接口，确认响应不含 _scope_tenant_ids
  3. 模拟前端编辑流程（将详情数据回传，不补充 scope）
  4. POST 管理端编辑接口
  5. 断言 AnnouncementScope 被清空，用户端不可见
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.account.models import Tenant
from apps.home.models import (
    Announcement, AnnouncementScope,
    SCOPE_ALL, SCOPE_TENANT,
    STATUS_UNPUBLISHED, STATUS_PUBLISHED,
)
from apps.home.tests.characterization.test_announcement import (
    _make_user, _grant_perms, _make_client, _make_announcement, ANN_PERMS,
)
from apps.utils.test_helpers import setup_test_env


class Bug3ScopeLostOnEditTests(TestCase):
    """编辑指定部门公告时发布范围丢失"""

    def setUp(self):
        setup_test_env(self)
        self.admin = _make_user('admin_scope', tenant_id='t_owner')
        _grant_perms(self.admin, ANN_PERMS)
        self.client = _make_client(self.admin)

        self.target_t1 = _make_user('user_t1', tenant_id='t_target1')
        self.target_t2 = _make_user('user_t2', tenant_id='t_target2')

        # 创建目标租户
        Tenant.objects.create(id='t_target1', name='目标部门1')
        Tenant.objects.create(id='t_target2', name='目标部门2')

    def test_detail_response_missing_scope_tenant_ids(self):
        """管理端详情接口不返回 _scope_tenant_ids 字段"""
        ann = _make_announcement(
            self.admin, status=STATUS_UNPUBLISHED,
            published_at=None, published_by_id=None, published_by_name='',
            scope_type=SCOPE_TENANT,
        )
        AnnouncementScope.objects.create(
            announcement=ann, tenant_id='t_target1', tenant_name='目标部门1')
        AnnouncementScope.objects.create(
            announcement=ann, tenant_id='t_target2', tenant_name='目标部门2')

        resp = self.client.get(f'/home/announcement/admin/{ann.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        data = body['data']
        # 核心断言：详情接口不包含 _scope_tenant_ids
        self.assertNotIn('_scope_tenant_ids', data,
                         '详情接口不应缺少 _scope_tenant_ids 字段，'
                         '缺少会导致前端编辑时无法回填已选部门')

    def test_edit_tenant_scope_clears_scopes(self):
        """编辑指定部门公告但不传 target_tenant_ids 时，scope 被清空"""
        ann = _make_announcement(
            self.admin, status=STATUS_UNPUBLISHED,
            published_at=None, published_by_id=None, published_by_name='',
            scope_type=SCOPE_TENANT,
            title='范围丢失测试',
        )
        AnnouncementScope.objects.create(
            announcement=ann, tenant_id='t_target1', tenant_name='目标部门1')
        AnnouncementScope.objects.create(
            announcement=ann, tenant_id='t_target2', tenant_name='目标部门2')

        self.assertEqual(
            AnnouncementScope.objects.filter(announcement=ann).count(), 2)

        # 模拟前端编辑流程：
        # 1. GET 详情
        resp = self.client.get(f'/home/announcement/admin/{ann.id}/')
        detail = resp.json()['data']

        # 2. 构造编辑 payload（前端从详情数据中取不到 _scope_tenant_ids，所以不传）
        payload = {
            'id': detail['id'],
            'title': detail['title'],
            'content': '修改后内容',
            'scope_type': detail['scope_type'],
            'effective_start_at': '2026-08-08 09:00:00',
            # target_tenant_ids 缺失或为空 — 模拟前端行为
            'target_tenant_ids': [],
        }
        resp = self.client.post(
            '/home/announcement/admin/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertFalse(resp.json().get('error'), resp.json())

        # 3. 断言 scope 被清空
        scope_count = AnnouncementScope.objects.filter(announcement=ann).count()
        self.assertEqual(scope_count, 0,
                         '编辑时应保留原有 scope，但 _sync_scopes 先清空再写空列表导致丢失')

    def test_scope_clearance_makes_announcement_invisible(self):
        """scope 清空后，目标租户用户无法看到公告"""
        ann = _make_announcement(
            self.admin, status=STATUS_PUBLISHED,
            scope_type=SCOPE_TENANT,
            effective_start_at=timezone.now() - timedelta(hours=1),
        )
        AnnouncementScope.objects.create(
            announcement=ann, tenant_id='t_target1', tenant_name='目标部门1')

        # 确认编辑前可见
        self.assertTrue(ann.is_visible_to(self.target_t1))

        # 模拟编辑清空 scope
        AnnouncementScope.objects.filter(announcement=ann).delete()

        # 编辑后不可见
        ann.refresh_from_db()
        self.assertFalse(ann.is_visible_to(self.target_t1),
                         'scope 被清空后，目标租户用户不再可见')

    def test_edit_with_explicit_scopes_preserves_them(self):
        """编辑时正确传入 target_tenant_ids 则 scope 被保留（对照组）"""
        ann = _make_announcement(
            self.admin, status=STATUS_UNPUBLISHED,
            published_at=None, published_by_id=None, published_by_name='',
            scope_type=SCOPE_TENANT,
        )
        AnnouncementScope.objects.create(
            announcement=ann, tenant_id='t_target1', tenant_name='目标部门1')

        payload = {
            'id': ann.id,
            'title': '保留范围测试',
            'content': '内容',
            'scope_type': SCOPE_TENANT,
            'target_tenant_ids': ['t_target1', 't_target2'],
            'effective_start_at': '2026-08-08 09:00:00',
        }
        resp = self.client.post(
            '/home/announcement/admin/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertFalse(resp.json().get('error'), resp.json())

        scope_count = AnnouncementScope.objects.filter(announcement=ann).count()
        self.assertEqual(scope_count, 2,
                         '正确传入 target_tenant_ids 时 scope 应被保留')
