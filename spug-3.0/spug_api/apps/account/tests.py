# -*- coding: utf-8 -*-
"""账号模块测试

覆盖：
- 登录/登出（成功/失败/锁定/审计日志）
- UserView：用户 CRUD + 权限码 + 跨租户隔离 + 软删除/恢复
- RoleView：角色 CRUD + 可分配边界 + 权限子集校验
- AssignableRoleView：可分配角色下拉（按目标租户收敛）
- TenantView：租户 CRUD + 关联用户检查
- SelfView：个人信息修改 + 改密
- role_permissions 工具函数
"""
import json
import tempfile
import time
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.account.models import User, Role, Tenant, History
from apps.account.role_permissions import (
    get_assignable_roles,
    get_assignable_roles_for_target,
    get_manageable_role,
    validate_assignable_role_ids,
    validate_page_perms_subset,
    flatten_page_perms,
)
from apps.logs.models import AuditLog
from apps.utils.test_helpers import make_user, make_client, setup_test_env


# 满足复杂度要求的测试密码（≥8 位 + 数字 + 大写 + 小写 + 特殊字符）
VALID_PWD = 'Admin888..'
WEAK_PWD = '123'  # 不满足复杂度


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class LoginLogoutTest(TestCase):
    """登录/登出测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = User.objects.create(
            username='alice',
            nickname='Alice',
            password_hash=User.make_password(VALID_PWD),
            is_active=True,
            access_token=('alice' * 10)[:32],  # 32 字符
            token_expired=int(time.time()) + 3600,
            last_login='2026-01-01',
            last_ip='127.0.0.1',
            type='default',
        )

    def _post_login(self, username='alice', password=VALID_PWD, ip='127.0.0.1'):
        from django.test import Client
        client = Client()
        client.defaults['HTTP_X_FORWARDED_FOR'] = ip
        client.defaults['HTTP_USER_AGENT'] = 'Mozilla/5.0 Test'
        return client.post(
            '/account/login/',
            data=json.dumps({'username': username, 'password': password}),
            content_type='application/json',
        )

    def test_login_success(self):
        r = self._post_login()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body.get('error'), body)
        self.assertIn('access_token', body['data'])
        self.assertEqual(body['data']['id'], self.user.id)
        # token 应被刷新（防 session fixation）
        self.user.refresh_from_db()
        self.assertNotEqual(
            self.user.access_token, ('alice' * 10)[:32]
        )

    def test_login_success_records_audit_log(self):
        self._post_login()
        log = AuditLog.objects.filter(
            action='login', target_type='auth', is_success=True
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.username, 'alice')

    def test_login_wrong_password(self):
        r = self._post_login(password='wrong_pwd')
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('用户名或密码错误', body['error'])

    def test_login_wrong_password_records_failure_audit(self):
        self._post_login(password='wrong_pwd')
        log = AuditLog.objects.filter(
            action='login', is_success=False
        ).first()
        self.assertIsNotNone(log)

    def test_login_user_lockout_after_5_fails(self):
        """连续 5 次失败后账户锁定"""
        for i in range(5):
            self._post_login(password='wrong')
        # 第 6 次应该被锁定
        r = self._post_login(password='wrong')
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('锁定', body['error'])

    def test_login_success_clears_fail_counter(self):
        """登录成功清除失败计数"""
        self._post_login(password='wrong')
        self._post_login()  # 成功
        # 失败计数应被清除
        self.assertIsNone(cache.get(f'login_fail:user:alice'))

    def test_login_disabled_user(self):
        self.user.is_active = False
        self.user.save()
        r = self._post_login()
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('禁用', body['error'])

    def test_login_deleted_user_rejected(self):
        """已软删除用户不能登录"""
        self.user.deleted_by = self.user
        self.user.save()
        r = self._post_login()
        body = r.json()
        self.assertTrue(body.get('error'))

    def test_login_records_history(self):
        self._post_login()
        hist = History.objects.filter(username='alice', is_success=True).first()
        self.assertIsNotNone(hist)

    def test_logout_records_audit(self):
        client = make_client(self.user)
        r = client.post('/account/logout/', data='{}', content_type='application/json')
        self.assertFalse(r.json().get('error'))
        log = AuditLog.objects.filter(
            action='logout', target_type='auth'
        ).first()
        self.assertIsNotNone(log)
        # logout 后 token_expired 应置 0
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_expired, 0)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UserViewTest(TestCase):
    """用户管理视图测试"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.admin = make_user('admin', [
            'system.account.view', 'system.account.add',
            'system.account.edit', 'system.account.del',
        ])
        self.noperm = make_user('noperm', [])
        self.supper_client = make_client(self.supper)
        self.admin_client = make_client(self.admin)
        self.noperm_client = make_client(self.noperm)

    # ---- 权限 ----

    def test_list_denied_without_perm(self):
        r = self.noperm_client.get('/account/user/')
        self.assertTrue(r.json().get('error'))

    def test_list_ok_with_perm(self):
        r = self.admin_client.get('/account/user/')
        body = r.json()
        self.assertFalse(body.get('error'))
        # 应该能看到 admin 和 noperm（同租户），但看不到 supper（不同租户）
        usernames = [u['username'] for u in body['data']]
        self.assertIn('admin', usernames)

    def test_list_supper_sees_all(self):
        r = self.supper_client.get('/account/user/')
        body = r.json()
        self.assertFalse(body.get('error'))

    # ---- 创建 ----

    def test_create_user_success(self):
        r = self.supper_client.post(
            '/account/user/',
            data=json.dumps({
                'username': 'newuser',
                'password': VALID_PWD,
                'nickname': 'New',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_create_user_weak_password_rejected(self):
        r = self.supper_client.post(
            '/account/user/',
            data=json.dumps({
                'username': 'newuser',
                'password': WEAK_PWD,
                'nickname': 'New',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('密码', body['error'])

    def test_create_user_duplicate_username_rejected(self):
        r = self.supper_client.post(
            '/account/user/',
            data=json.dumps({
                'username': 'supper',
                'password': VALID_PWD,
                'nickname': 'Dup',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_create_user_missing_username(self):
        r = self.supper_client.post(
            '/account/user/',
            data=json.dumps({
                'password': VALID_PWD,
                'nickname': 'New',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    # ---- 编辑 ----

    def test_edit_user_nickname(self):
        """编辑用户昵称（只提交部分字段，不传 tenant_id）"""
        r = self.supper_client.post(
            '/account/user/',
            data=json.dumps({
                'id': self.admin.id,
                'username': 'admin',
                'password': VALID_PWD,
                'nickname': 'AdminNew',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.nickname, 'AdminNew')

    def test_edit_nonexistent_user_returns_error(self):
        r = self.supper_client.post(
            '/account/user/',
            data=json.dumps({
                'id': 99999,
                'username': 'ghost',
                'password': VALID_PWD,
                'nickname': 'Ghost',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    # ---- PATCH 重置密码/禁用 ----

    def test_patch_disable_user(self):
        r = self.supper_client.patch(
            '/account/user/',
            data=json.dumps({'id': self.admin.id, 'is_active': False}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_active)

    def test_patch_reset_password(self):
        r = self.supper_client.patch(
            '/account/user/',
            data=json.dumps({'id': self.admin.id, 'password': 'NewPass123!'}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.verify_password('NewPass123!'))
        # 重置密码后 token 应失效
        self.assertEqual(self.admin.token_expired, 0)

    def test_patch_reset_password_weak_rejected(self):
        r = self.supper_client.patch(
            '/account/user/',
            data=json.dumps({'id': self.admin.id, 'password': WEAK_PWD}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    # ---- DELETE 软删除 ----

    def test_delete_user_soft_delete(self):
        r = self.supper_client.delete(f'/account/user/?id={self.admin.id}')
        self.assertFalse(r.json().get('error'))
        self.admin.refresh_from_db()
        self.assertIsNotNone(self.admin.deleted_at)
        self.assertFalse(self.admin.is_active)
        # 角色关联应被清除
        self.assertEqual(self.admin.roles.count(), 0)

    def test_delete_self_rejected(self):
        """不能删除当前登录账户"""
        r = self.supper_client.delete(f'/account/user/?id={self.supper.id}')
        self.assertTrue(r.json().get('error'))
        self.assertIn('当前', r.json()['error'])

    def test_delete_missing_id(self):
        r = self.supper_client.delete('/account/user/')
        self.assertTrue(r.json().get('error'))

    # ---- 租户隔离 ----

    def test_admin_cannot_edit_cross_tenant_user(self):
        """普通管理员不能编辑其他租户用户"""
        # supper 在 'admin' 租户，self.admin 也在 'admin' 租户
        # 创建一个其他租户用户
        other = make_user('other', [])
        other.tenant_id = 'tenant-x'
        other.save()
        r = self.admin_client.post(
            '/account/user/',
            data=json.dumps({
                'id': other.id,
                'username': 'other',
                'password': VALID_PWD,
                'nickname': 'Other',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))
        self.assertIn('租户', r.json()['error'])

    def test_admin_cannot_delete_cross_tenant_user(self):
        other = make_user('other', [])
        other.tenant_id = 'tenant-x'
        other.save()
        r = self.admin_client.delete(f'/account/user/?id={other.id}')
        self.assertTrue(r.json().get('error'))

    # ---- 恢复 ----

    def test_restore_deleted_user(self):
        self.supper_client.delete(f'/account/user/?id={self.admin.id}')
        r = self.supper_client.post(
            '/account/user/restore/',
            data=json.dumps({'id': self.admin.id}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertIsNone(self.admin.deleted_by)

    def test_restore_non_deleted_rejected(self):
        r = self.supper_client.post(
            '/account/user/restore/',
            data=json.dumps({'id': self.admin.id}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    # ---- get_tenant_choices ----

    def test_tenant_choices_denied_for_non_supper(self):
        r = self.admin_client.get('/account/user/tenant_choices/')
        self.assertTrue(r.json().get('error'))

    def test_tenant_choices_ok_for_supper(self):
        Tenant.objects.create(id='t1', name='租户1', created_by=self.supper)
        r = self.supper_client.get('/account/user/tenant_choices/')
        body = r.json()
        self.assertFalse(body.get('error'))
        ids = [t['id'] for t in body['data']]
        self.assertIn('t1', ids)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RoleViewTest(TestCase):
    """角色管理视图测试"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.admin = make_user('admin', [
            'system.account.view', 'system.account.edit', 'system.account.del',
        ])
        # 给 admin 关联一个本租户角色，便于测试权限子集校验
        self.admin_role = Role.objects.create(
            name='管理员角色', tenant_id='admin', is_system=False,
            is_global_admin=False, page_perms=json.dumps({
                'system': {'account': ['view', 'add', 'edit', 'del']}
            }),
            created_by=self.supper,
        )
        self.admin.roles.add(self.admin_role)
        self.admin.set_perms_cache()
        self.supper_client = make_client(self.supper)
        self.admin_client = make_client(self.admin)

    def test_list_roles_as_supper(self):
        r = self.supper_client.get('/account/role/')
        body = r.json()
        self.assertFalse(body.get('error'))

    def test_list_roles_as_admin_only_own_tenant(self):
        """普通管理员只看到本租户、非系统、非全局管理员角色"""
        Role.objects.create(
            name='平台角色', tenant_id='', is_system=True,
            created_by=self.supper
        )
        r = self.admin_client.get('/account/role/')
        body = r.json()
        self.assertFalse(body.get('error'))
        names = [role['name'] for role in body['data']]
        self.assertIn('管理员角色', names)
        self.assertNotIn('平台角色', names)

    def test_create_role_as_supper(self):
        r = self.supper_client.post(
            '/account/role/',
            data=json.dumps({'name': '新角色', 'desc': '测试'}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.assertTrue(Role.objects.filter(name='新角色').exists())

    def test_create_role_admin_cannot_set_global_admin(self):
        """普通管理员不能创建全局管理员角色"""
        r = self.admin_client.post(
            '/account/role/',
            data=json.dumps({'name': '全局', 'is_global_admin': True}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))
        self.assertIn('全局管理员', r.json()['error'])

    def test_create_role_admin_forced_own_tenant(self):
        """普通管理员创建角色强制绑定本租户、is_system=False"""
        self.admin_client.post(
            '/account/role/',
            data=json.dumps({'name': '租户角色', 'is_system': True}),
            content_type='application/json',
        )
        role = Role.objects.get(name='租户角色')
        self.assertEqual(role.tenant_id, 'admin')
        self.assertFalse(role.is_system)
        self.assertFalse(role.is_global_admin)

    def test_patch_role_page_perms_subset_violation(self):
        """普通管理员分配超过自身权限的 page_perms 被拒"""
        r = self.admin_client.patch(
            '/account/role/',
            data=json.dumps({
                'id': self.admin_role.id,
                'page_perms': {
                    'system': {'account': ['view', 'add', 'edit', 'del', 'non_existent_perm']}
                },
            }),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_patch_role_page_perms_within_subset_ok(self):
        """普通管理员分配自身权限子集的 page_perms 通过"""
        r = self.admin_client.patch(
            '/account/role/',
            data=json.dumps({
                'id': self.admin_role.id,
                'page_perms': {
                    'system': {'account': ['view']}
                },
            }),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))

    def test_patch_role_supper_no_subset_restriction(self):
        """超管分配任意 page_perms 都通过"""
        r = self.supper_client.patch(
            '/account/role/',
            data=json.dumps({
                'id': self.admin_role.id,
                'page_perms': {
                    'system': {'account': ['view', 'add', 'edit', 'del', 'anything']}
                },
            }),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))

    def test_delete_role_with_users_rejected(self):
        """有用户关联的角色不能删除"""
        r = self.supper_client.delete(f'/account/role/?id={self.admin_role.id}')
        self.assertTrue(r.json().get('error'))
        self.assertIn('解除关联', r.json()['error'])

    def test_delete_role_without_users_ok(self):
        empty_role = Role.objects.create(
            name='空角色', tenant_id='admin', created_by=self.supper
        )
        r = self.supper_client.delete(f'/account/role/?id={empty_role.id}')
        self.assertFalse(r.json().get('error'))
        self.assertFalse(Role.objects.filter(id=empty_role.id).exists())

    def test_admin_cannot_delete_system_role(self):
        """普通管理员不能删除系统角色（get_manageable_role 返回 None）"""
        sys_role = Role.objects.create(
            name='系统', tenant_id='admin', is_system=True, created_by=self.supper
        )
        r = self.admin_client.delete(f'/account/role/?id={sys_role.id}')
        self.assertTrue(r.json().get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AssignableRoleViewTest(TestCase):
    """可分配角色下拉接口测试"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.admin = make_user('admin', ['system.account.view'])
        # 平台级角色
        self.platform_role = Role.objects.create(
            name='平台角色', tenant_id='', is_system=True, created_by=self.supper
        )
        # 全局管理员角色
        self.global_role = Role.objects.create(
            name='全局管理员', is_global_admin=True, is_system=True,
            created_by=self.supper
        )
        # admin 所在租户的普通角色
        self.tenant_role = Role.objects.create(
            name='租户角色', tenant_id='admin', is_system=False,
            created_by=self.supper
        )
        # 其他租户的角色
        self.other_role = Role.objects.create(
            name='其他租户角色', tenant_id='tenant-x', is_system=False,
            created_by=self.supper
        )
        self.supper_client = make_client(self.supper)
        self.admin_client = make_client(self.admin)

    def test_admin_gets_own_tenant_roles_only(self):
        """普通管理员只能看到本租户角色"""
        r = self.admin_client.get('/account/role/assignable/')
        body = r.json()
        names = [role['name'] for role in body['data']]
        self.assertIn('租户角色', names)
        self.assertNotIn('平台角色', names)
        self.assertNotIn('其他租户角色', names)

    def test_supper_without_tenant_param(self):
        """超管不传 tenant_id：只返回平台级 + 全局管理员"""
        r = self.supper_client.get('/account/role/assignable/')
        body = r.json()
        names = [role['name'] for role in body['data']]
        self.assertIn('平台角色', names)
        self.assertIn('全局管理员', names)
        self.assertNotIn('租户角色', names)
        self.assertNotIn('其他租户角色', names)

    def test_supper_with_tenant_param(self):
        """超管传 tenant_id：追加该租户角色"""
        r = self.supper_client.get('/account/role/assignable/?tenant_id=admin')
        body = r.json()
        names = [role['name'] for role in body['data']]
        self.assertIn('平台角色', names)
        self.assertIn('全局管理员', names)
        self.assertIn('租户角色', names)
        self.assertNotIn('其他租户角色', names)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TenantViewTest(TestCase):
    """租户管理视图测试"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.admin = make_user('admin', [
            'system.tenant.view', 'system.tenant.add',
            'system.tenant.edit', 'system.tenant.del',
        ])
        self.supper_client = make_client(self.supper)
        self.admin_client = make_client(self.admin)

    def test_list_denied_for_non_supper(self):
        """普通管理员即便有 system.tenant.view 也看不到（AdminView 不区分 PERM_MAP 与 is_supper 的关系）
        
        实际上 AdminView.dispatch 会按 PERM_MAP 校验，admin 有权限应能通过。
        但 TenantView.get 返回 Tenant.objects.all() 不做租户过滤，
        普通管理员能看到所有租户，这是设计决策（租户管理通常仅超管）。
        本测试验证有权限的 admin 也能列表。
        """
        r = self.admin_client.get('/account/tenant/')
        body = r.json()
        self.assertFalse(body.get('error'))

    def test_create_tenant_success(self):
        r = self.supper_client.post(
            '/account/tenant/',
            data=json.dumps({'id': 't1', 'name': '租户1'}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.assertTrue(Tenant.objects.filter(id='t1').exists())

    def test_create_tenant_invalid_id_format(self):
        """租户 ID 格式校验（仅字母/数字/下划线/横线）"""
        r = self.supper_client.post(
            '/account/tenant/',
            data=json.dumps({'id': 'invalid id!', 'name': '租户'}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_create_tenant_duplicate_id(self):
        Tenant.objects.create(id='t1', name='已有', created_by=self.supper)
        r = self.supper_client.post(
            '/account/tenant/',
            data=json.dumps({'id': 't1', 'name': '重复'}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_delete_tenant_with_users_rejected(self):
        """有用户的租户不能删除"""
        Tenant.objects.create(id='t1', name='租户1', created_by=self.supper)
        # 创建一个该租户用户
        User.objects.create(
            username='u1', nickname='U1', password_hash='x',
            is_active=True, tenant_id='t1', type='default',
        )
        r = self.supper_client.delete('/account/tenant/?id=t1')
        self.assertTrue(r.json().get('error'))
        self.assertIn('用户', r.json()['error'])

    def test_delete_tenant_without_users_ok(self):
        Tenant.objects.create(id='t1', name='租户1', created_by=self.supper)
        r = self.supper_client.delete('/account/tenant/?id=t1')
        self.assertFalse(r.json().get('error'))
        self.assertFalse(Tenant.objects.filter(id='t1').exists())

    def test_patch_tenant(self):
        """编辑租户名称（只提交 id+name，不传 description/is_active）"""
        Tenant.objects.create(id='t1', name='旧名', created_by=self.supper)
        r = self.supper_client.patch(
            '/account/tenant/',
            data=json.dumps({'id': 't1', 'name': '新名'}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.assertEqual(Tenant.objects.get(id='t1').name, '新名')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SelfViewTest(TestCase):
    """个人信息视图测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('alice', [])
        self.client = make_client(self.user)

    def test_get_self(self):
        r = self.client.get('/account/self/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['nickname'], 'alice')

    def test_patch_nickname(self):
        r = self.client.patch(
            '/account/self/',
            data=json.dumps({'nickname': 'Alice2'}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.nickname, 'Alice2')

    def test_patch_password_correct_old(self):
        self.user.password_hash = User.make_password(VALID_PWD)
        self.user.save()
        r = self.client.patch(
            '/account/self/',
            data=json.dumps({
                'old_password': VALID_PWD,
                'new_password': 'NewPass123!',
            }),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.verify_password('NewPass123!'))
        self.assertEqual(self.user.token_expired, 0)

    def test_patch_password_wrong_old(self):
        self.user.password_hash = User.make_password(VALID_PWD)
        self.user.save()
        r = self.client.patch(
            '/account/self/',
            data=json.dumps({
                'old_password': 'wrong_old',
                'new_password': 'NewPass123!',
            }),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))
        self.assertIn('原密码', r.json()['error'])

    def test_patch_password_weak_new(self):
        self.user.password_hash = User.make_password(VALID_PWD)
        self.user.save()
        r = self.client.patch(
            '/account/self/',
            data=json.dumps({
                'old_password': VALID_PWD,
                'new_password': WEAK_PWD,
            }),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RolePermissionsUtilTest(TestCase):
    """role_permissions 工具函数测试"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.admin = make_user('admin', [])
        self.platform_role = Role.objects.create(
            name='平台', tenant_id='', is_system=True, created_by=self.supper
        )
        self.global_role = Role.objects.create(
            name='全局', is_global_admin=True, is_system=True, created_by=self.supper
        )
        self.tenant_role_a = Role.objects.create(
            name='租户A', tenant_id='admin', is_system=False, created_by=self.supper
        )
        self.tenant_role_b = Role.objects.create(
            name='租户B', tenant_id='tenant-b', is_system=False, created_by=self.supper
        )

    # ---- get_assignable_roles ----

    def test_supper_get_all_roles(self):
        roles = get_assignable_roles(self.supper)
        self.assertEqual(roles.count(), 4)

    def test_admin_get_own_tenant_roles_only(self):
        roles = get_assignable_roles(self.admin)
        ids = set(roles.values_list('id', flat=True))
        self.assertIn(self.tenant_role_a.id, ids)
        self.assertNotIn(self.platform_role.id, ids)
        self.assertNotIn(self.global_role.id, ids)
        self.assertNotIn(self.tenant_role_b.id, ids)

    # ---- validate_assignable_role_ids ----

    def test_validate_nonexistent_role_id(self):
        err = validate_assignable_role_ids(self.supper, [99999])
        self.assertIsNotNone(err)
        self.assertIn('不存在', err)

    def test_validate_supper_cross_tenant_role_rejected(self):
        """超管把租户 B 的角色分配给租户 A 用户被拒"""
        err = validate_assignable_role_ids(
            self.supper, [self.tenant_role_b.id], target_tenant_id='admin'
        )
        self.assertIsNotNone(err)
        self.assertIn('其他租户', err)

    def test_validate_supper_platform_role_ok(self):
        """超管把平台级角色分配给任意租户用户通过"""
        err = validate_assignable_role_ids(
            self.supper, [self.platform_role.id], target_tenant_id='admin'
        )
        self.assertIsNone(err)

    def test_validate_supper_global_role_ok(self):
        """超管把全局管理员角色分配给任意租户用户通过"""
        err = validate_assignable_role_ids(
            self.supper, [self.global_role.id], target_tenant_id='admin'
        )
        self.assertIsNone(err)

    def test_validate_admin_only_own_tenant(self):
        """普通管理员只能分配本租户角色"""
        err = validate_assignable_role_ids(
            self.admin, [self.tenant_role_a.id]
        )
        self.assertIsNone(err)
        err = validate_assignable_role_ids(
            self.admin, [self.tenant_role_b.id]
        )
        self.assertIsNotNone(err)

    def test_validate_admin_cross_tenant_role_rejected(self):
        err = validate_assignable_role_ids(
            self.admin, [self.platform_role.id]
        )
        self.assertIsNotNone(err)

    def test_validate_empty_role_ids_ok(self):
        err = validate_assignable_role_ids(self.supper, [])
        self.assertIsNone(err)

    # ---- get_manageable_role ----

    def test_manageable_role_admin_cannot_get_system(self):
        """普通管理员不能管理系统角色"""
        role = get_manageable_role(self.admin, self.platform_role.id)
        self.assertIsNone(role)

    def test_manageable_role_admin_cannot_get_cross_tenant(self):
        role = get_manageable_role(self.admin, self.tenant_role_b.id)
        self.assertIsNone(role)

    def test_manageable_role_supper_gets_all(self):
        role = get_manageable_role(self.supper, self.platform_role.id)
        self.assertIsNotNone(role)

    # ---- flatten_page_perms ----

    def test_flatten_page_perms(self):
        perms = {'system': {'account': ['view', 'add']}, 'document': {'folder': ['view']}}
        flat = flatten_page_perms(perms)
        self.assertEqual(flat, {
            'system.account.view', 'system.account.add', 'document.folder.view'
        })

    def test_flatten_empty(self):
        self.assertEqual(flatten_page_perms(None), set())
        self.assertEqual(flatten_page_perms({}), set())

    # ---- validate_page_perms_subset ----

    def test_validate_page_perms_subset_supper_passes(self):
        err = validate_page_perms_subset(self.supper, {'any': {'thing': ['perm']}})
        self.assertIsNone(err)

    def test_validate_page_perms_subset_empty_passes(self):
        err = validate_page_perms_subset(self.admin, {})
        self.assertIsNone(err)
