# -*- coding: utf-8 -*-
"""
Bug 3 回归测试：编辑指定部门公告的发布范围回显（已修复）

原缺陷：
  管理端详情接口不返回 _scope_tenant_ids，编辑表单部门选择框永远为空，
  管理员被迫盲选重选；详情页也无法核对目标部门列表。
  （后端 _validate_scope 始终拒绝空 target_tenant_ids，发布范围不会被静默清空。）

修复：
  AnnouncementAdminDetailView.get 返回 _scope_tenant_ids / _scope_tenant_names，
  前端 Form.js 使用 detail._scope_tenant_ids 回填编辑表单。

本文件验证修复后行为：
  1. 管理端详情返回 scope 字段且值正确；用户端详情不返回（避免部门枚举泄露）
  2. 端到端：GET 详情 → 用回显数据构造编辑 payload → POST → scope 保留
  3. 空 target_tenant_ids 仍被拒绝（防清空护栏不变）
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.account.models import Tenant
from apps.home.models import (
    AnnouncementScope,
    SCOPE_TENANT,
    STATUS_UNPUBLISHED, STATUS_PUBLISHED,
)
from apps.home.tests.characterization.test_announcement import (
    _make_user, _grant_perms, _make_client, _make_announcement, ANN_PERMS,
)
from apps.utils.test_helpers import setup_test_env


class Bug3ScopeEchoBackTests(TestCase):
    """编辑指定部门公告的发布范围回显修复回归"""

    def setUp(self):
        setup_test_env(self)
        self.admin = _make_user('admin_scope', tenant_id='t_owner')
        _grant_perms(self.admin, ANN_PERMS)
        self.client = _make_client(self.admin)

        self.target_t1 = _make_user('user_t1', tenant_id='t_target1')

        Tenant.objects.create(id='t_target1', name='目标部门1')
        Tenant.objects.create(id='t_target2', name='目标部门2')

    def _make_tenant_scoped_announcement(self, status=STATUS_UNPUBLISHED):
        ann = _make_announcement(
            self.admin, status=status,
            published_at=None if status == STATUS_UNPUBLISHED else timezone.now(),
            published_by_id=None if status == STATUS_UNPUBLISHED else self.admin.id,
            published_by_name='' if status == STATUS_UNPUBLISHED else self.admin.nickname,
            scope_type=SCOPE_TENANT,
            effective_start_at=timezone.now() - timedelta(hours=1),
        )
        AnnouncementScope.objects.create(
            announcement=ann, tenant_id='t_target1', tenant_name='目标部门1')
        AnnouncementScope.objects.create(
            announcement=ann, tenant_id='t_target2', tenant_name='目标部门2')
        return ann

    def test_admin_detail_returns_scope_fields(self):
        """管理端详情返回 _scope_tenant_ids / _scope_tenant_names 且值正确"""
        ann = self._make_tenant_scoped_announcement()

        resp = self.client.get(f'/home/announcement/admin/{ann.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        data = body['data']
        self.assertEqual(data['_scope_tenant_ids'], ['t_target1', 't_target2'])
        self.assertEqual(data['_scope_tenant_names'], ['目标部门1', '目标部门2'])

    def test_user_detail_does_not_expose_scope_fields(self):
        """用户端详情不返回 scope 字段（部门列表仅管理端可见）"""
        ann = self._make_tenant_scoped_announcement(status=STATUS_PUBLISHED)
        c_user = _make_client(self.target_t1)

        resp = c_user.get(f'/home/announcement/{ann.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertNotIn('_scope_tenant_ids', body['data'])
        self.assertNotIn('_scope_tenant_names', body['data'])

    def test_edit_with_echoed_scopes_preserves_them(self):
        """端到端：详情回显 → 编辑保存 → scope 完整保留（原缺陷场景回归）"""
        ann = self._make_tenant_scoped_announcement()

        # 1. GET 详情（编辑入口的数据来源，与 index.js openEdit 一致）
        resp = self.client.get(f'/home/announcement/admin/{ann.id}/')
        detail = resp.json()['data']

        # 2. 用回显数据构造编辑 payload（与 Form.js handleOk 一致）
        payload = {
            'id': detail['id'],
            'title': detail['title'],
            'content': '修改后内容',
            'scope_type': detail['scope_type'],
            'target_tenant_ids': detail['_scope_tenant_ids'],
            'effective_start_at': '2026-08-08 09:00:00',
        }
        resp = self.client.post(
            '/home/announcement/admin/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertFalse(resp.json().get('error'), resp.json())

        # 3. scope 完整保留，编辑表单不再丢失已选部门
        scope_count = AnnouncementScope.objects.filter(announcement=ann).count()
        self.assertEqual(scope_count, 2,
                         '使用回显数据编辑后，发布范围应完整保留')

    def test_empty_targets_still_rejected(self):
        """防清空护栏不变：scope_type=tenant 且空 target_tenant_ids 仍被拒绝"""
        ann = self._make_tenant_scoped_announcement()

        payload = {
            'id': ann.id,
            'title': ann.title,
            'content': '内容',
            'scope_type': SCOPE_TENANT,
            'target_tenant_ids': [],
            'effective_start_at': '2026-08-08 09:00:00',
        }
        resp = self.client.post(
            '/home/announcement/admin/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertEqual(body.get('error'), '请选择发布部门')
        self.assertEqual(
            AnnouncementScope.objects.filter(announcement=ann).count(), 2,
            '被拒绝的编辑不应改动已有 scope 记录')

    def test_scope_clearance_makes_announcement_invisible(self):
        """scope 一旦被清空，目标租户用户即不可见（后果验证，直接 ORM 删除模拟）"""
        ann = self._make_tenant_scoped_announcement(status=STATUS_PUBLISHED)

        self.assertTrue(ann.is_visible_to(self.target_t1))
        AnnouncementScope.objects.filter(announcement=ann).delete()
        self.assertFalse(ann.is_visible_to(self.target_t1),
                         'scope 被清空后，目标租户用户不再可见')
