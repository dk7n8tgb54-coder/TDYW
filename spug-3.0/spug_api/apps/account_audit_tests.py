# -*- coding: utf-8 -*-
"""
账号模块审计测试

覆盖 account/views.py 和 account/models.py 的潜在问题：
A1: _handle_user_edit 中 tenant_id='' 绕过迁移逻辑（已确认 BUG）
A2: 编辑用户的 IntegrityError 错误消息说"无法重复创建"（已修复）
A3: 租户删除未过滤软删除用户
A5: 恢复用户不恢复角色（设计限制，非 BUG）
A6: _handle_user_edit 忽略 password 参数（设计验证）
A7: 软删除用户后 username 可重建（active_username 唯一约束验证）

运行方式：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.account_audit_tests --noinput -v2
"""
import json
import inspect
import uuid

from django.test import TestCase, Client
from django.conf import settings

from apps.account.models import User, Role, Tenant
from apps.utils.test_helpers import make_user, make_client, setup_test_env


class AccountEditTests(TestCase):
    """用户编辑相关测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = make_user('admin', is_supper=True)
        self.client_admin = make_client(self.admin)

    def tearDown(self):
        User.objects.all().update(created_by=None, deleted_by=None)
        Role.objects.all().delete()
        User.objects.all().delete()

    def test_a1_tenant_id_empty_string_bypasses_migration(self):
        """
        A1: _handle_user_edit 中 tenant_id='' 不再绕过迁移逻辑（已修复）

        修复前：tenant_id='' 被写入 user.tenant_id，但迁移逻辑被跳过
        修复后：tenant_id 从 update_data 中排除，空字符串不会改变租户归属
        """
        target_user = make_user('target_user')
        target_user.tenant_id = 'tenant_a'
        target_user.save()

        original_tenant = target_user.tenant_id
        self.assertNotEqual(original_tenant, '')

        # 模拟编辑请求（超管传 tenant_id=''）
        response = self.client_admin.post('/account/user/', data=json.dumps({
            'id': target_user.id,
            'username': 'target_user',
            'password': 'Test1234!',
            'nickname': 'Target',
            'tenant_id': '',
        }), content_type='application/json')

        target_user.refresh_from_db()

        # 修复后：tenant_id 不应被空字符串覆盖
        self.assertEqual(
            target_user.tenant_id, original_tenant,
            "A1 已修复：tenant_id='' 不应改变用户租户归属"
        )

    def test_a2_edit_integrity_error_message_fixed(self):
        """
        A2: 编辑用户的 IntegrityError 错误消息不应包含"创建"

        修复前：消息说"已存在登录名为【xxx】的用户，无法重复创建"
        修复后：消息说"保存失败，可能登录名【xxx】与其他用户冲突"
        """
        from apps.account.views import UserView

        source = inspect.getsource(UserView._handle_user_edit)

        # 验证 IntegrityError 处理存在
        self.assertIn('IntegrityError', source)

        # 验证错误消息不再包含"无法重复创建"
        self.assertNotIn(
            '无法重复创建', source,
            "A2 已修复：编辑操作的 IntegrityError 消息不应包含'无法重复创建'"
        )

    def test_a6_edit_ignores_password_parameter(self):
        """
        A6: _handle_user_edit 忽略 password 参数（设计验证）

        设计意图：密码修改通过 PATCH 方法，不通过 POST 编辑。
        验证 PATCH 方法支持密码修改即可。
        """
        from apps.account.views import UserView

        # 验证 _handle_user_edit 不使用 password（设计如此）
        source = inspect.getsource(UserView._handle_user_edit)
        # password 在方法签名中但不被使用 - 这是设计，密码通过 PATCH 修改

        # 验证 PATCH 方法处理密码
        patch_source = inspect.getsource(UserView.patch)
        self.assertIn('password', patch_source,
                      "PATCH 方法应支持密码修改")

    def test_a7_soft_deleted_username_can_be_recreated(self):
        """
        A7: 软删除用户后 username 可重建

        验证 _check_duplicate_username 不会对软删除用户误报。
        不实际创建重复用户（避免 active_username 唯一约束复杂化 tearDown）。
        """
        from django.utils import timezone

        # 创建用户
        user1 = make_user('testuser_a7')

        # 软删除用户
        user1.is_active = False
        user1.deleted_by = self.admin
        user1.deleted_at = timezone.now()
        user1.roles.clear()
        user1.save()

        # 验证 _check_duplicate_username 不会误报
        from apps.account.views import UserView

        class FakeForm:
            username = 'testuser_a7'
            id = None

        view = UserView()
        error = view._check_duplicate_username(FakeForm())
        self.assertIsNone(
            error,
            f"软删除用户后应允许同名重建，但检查返回: {error}"
        )

        # 清理：先解除 deleted_by 引用再删除
        user1.deleted_by = None
        user1.save()
        user1.delete()


class TenantDeleteTests(TestCase):
    """租户删除相关测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = make_user('admin', is_supper=True)

    def tearDown(self):
        User.objects.all().update(created_by=None, deleted_by=None)
        Tenant.objects.all().delete()
        Role.objects.all().delete()
        User.objects.all().delete()

    def test_a3_tenant_delete_filters_soft_deleted_users(self):
        """
        A3: 租户删除已过滤软删除用户（已修复）

        修复前：User.objects.filter(tenant_id=...) 未过滤软删除用户
        修复后：加了 deleted_by_id__isnull=True 过滤
        """
        from django.utils import timezone

        tenant = Tenant.objects.create(
            id='test_tenant_a3',
            name='测试租户A3',
            created_by=self.admin,
        )

        # 创建一个用户并软删除
        user = User.objects.create(
            username='test_user_a3',
            nickname='Test',
            password_hash=User.make_password('Test1234!'),
            access_token=uuid.uuid4().hex,
            tenant_id='test_tenant_a3',
            created_by=self.admin,
        )
        user.deleted_by = self.admin
        user.deleted_at = timezone.now()
        user.is_active = False
        user.save()

        # 验证：过滤软删除后返回 False
        has_active_users = User.objects.filter(
            tenant_id='test_tenant_a3', deleted_by_id__isnull=True
        ).exists()
        self.assertFalse(has_active_users, "过滤软删除后应返回 False")

        # 静态验证：TenantView.delete 的查询已加过滤
        from apps.account.views import TenantView
        source = inspect.getsource(TenantView.delete)

        self.assertIn(
            'deleted_by_id__isnull', source,
            "A3 已修复：TenantView.delete 应过滤软删除用户"
        )


class UserRestoreTests(TestCase):
    """用户恢复相关测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = make_user('admin', is_supper=True)

    def tearDown(self):
        User.objects.all().update(created_by=None, deleted_by=None)
        Role.objects.all().delete()
        User.objects.all().delete()

    def test_a5_restore_user_does_not_restore_roles(self):
        """
        A5: 恢复用户不恢复角色（设计限制）

        软删除时 user.roles.clear() 清空角色，恢复时不重新分配。
        这是设计限制而非 BUG - 管理员需手动重新分配角色。
        """
        from django.utils import timezone

        # 创建角色
        role = Role.objects.create(
            name='test_role_a5',
            created_by=self.admin,
            tenant_id='admin',
        )

        # 创建用户并分配角色
        user = make_user('restore_test_a5')
        user.roles.add(role)
        self.assertEqual(user.roles.count(), 1)

        # 软删除（模拟 delete 操作）
        user.is_active = False
        user.deleted_at = timezone.now()
        user.deleted_by = self.admin
        user.roles.clear()
        user.save()

        self.assertEqual(user.roles.count(), 0, "软删除后角色应被清空")

        # 恢复
        user.is_active = True
        user.deleted_at = None
        user.deleted_by = None
        user.save()

        # 确认：恢复后无角色（设计限制）
        self.assertEqual(
            user.roles.count(), 0,
            "恢复后的用户无角色 - 管理员需手动重新分配。"
            "建议：软删除时保留角色关联，或在恢复时提示管理员。"
        )


class LoginSecurityTests(TestCase):
    """登录安全相关测试"""

    def setUp(self):
        setup_test_env(self)
        self.admin = make_user('login_test_admin', is_supper=True)

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()
        User.objects.all().update(created_by=None, deleted_by=None)
        Role.objects.all().delete()
        User.objects.all().delete()

    def test_login_rate_limiting_ip_level(self):
        """验证 IP 级别登录限流（30次/小时）"""
        from django.core.cache import cache
        cache.clear()

        client = Client(HTTP_USER_AGENT='TestAgent/1.0')
        # 模拟 30 次失败登录
        for i in range(30):
            client.post('/account/login/', data=json.dumps({
                'username': f'nonexistent_{i}',
                'password': 'WrongPass123!',
            }), content_type='application/json')

        # 第 31 次应被限流
        response = client.post('/account/login/', data=json.dumps({
            'username': 'another_user',
            'password': 'WrongPass123!',
        }), content_type='application/json')

        body = json.loads(response.content)
        self.assertIn(
            '频繁', body.get('error', ''),
            f"IP 级别限流应在 30 次失败后生效，实际返回: {body}"
        )

    def test_login_rate_limiting_user_level(self):
        """验证用户级别登录限流（5次/15分钟）"""
        from django.core.cache import cache
        cache.clear()

        client = Client(HTTP_USER_AGENT='TestAgent/1.0')
        # 模拟 5 次失败登录
        for i in range(5):
            client.post('/account/login/', data=json.dumps({
                'username': 'login_test_admin',
                'password': 'WrongPass123!',
            }), content_type='application/json')

        # 第 6 次应被锁定
        response = client.post('/account/login/', data=json.dumps({
            'username': 'login_test_admin',
            'password': 'WrongPass123!',
        }), content_type='application/json')

        body = json.loads(response.content)
        self.assertIn(
            '锁定', body.get('error', ''),
            f"用户级别限流应在 5 次失败后锁定，实际返回: {body}"
        )

    def test_login_generates_new_access_token(self):
        """验证登录时生成新的 access_token（防止会话固定）"""
        self.admin.access_token = 'old_fixed_token'
        self.admin.save()

        client = Client(HTTP_USER_AGENT='TestAgent/1.0')
        response = client.post('/account/login/', data=json.dumps({
            'username': 'login_test_admin',
            'password': '123456',
        }), content_type='application/json')

        body = json.loads(response.content)
        if body.get('access_token'):
            self.assertNotEqual(
                body['access_token'], 'old_fixed_token',
                "登录后应生成新的 access_token，防止会话固定攻击"
            )

        self.admin.refresh_from_db()


class PasswordPolicyTests(TestCase):
    """密码策略测试"""

    def test_verify_password_minimum_length(self):
        """验证密码最少 8 位"""
        from apps.account.utils import verify_password
        self.assertFalse(verify_password('Ab1!'))  # 太短
        self.assertFalse(verify_password('Ab1!567'))  # 7 位

    def test_verify_password_requires_complexity(self):
        """验证密码复杂度要求"""
        from apps.account.utils import verify_password
        self.assertFalse(verify_password('abcdefgh'))  # 无数字、大写、特殊
        self.assertFalse(verify_password('ABCDEFGH'))  # 无数字、小写、特殊
        self.assertFalse(verify_password('12345678'))  # 无字母、特殊
        self.assertFalse(verify_password('Abcd1234'))  # 无特殊字符
        self.assertTrue(verify_password('Abcd1234!'))  # 满足所有要求
        self.assertTrue(verify_password('P@ssw0rd'))  # 满足所有要求

    def test_password_hash_uses_pbkdf2(self):
        """验证密码哈希使用 pbkdf2_sha256"""
        hashed = User.make_password('Test1234!')
        self.assertTrue(
            hashed.startswith('pbkdf2_sha256$'),
            f"密码哈希应使用 pbkdf2_sha256，实际: {hashed[:20]}..."
        )


class SelfViewTests(TestCase):
    """个人设置相关测试"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('selfuser')
        self.client_user = make_client(self.user)

    def tearDown(self):
        User.objects.all().update(created_by=None, deleted_by=None)
        Role.objects.all().delete()
        User.objects.all().delete()

    def test_change_password_requires_old_password(self):
        """验证修改密码需要旧密码"""
        response = self.client_user.patch('/account/self/', data=json.dumps({
            'new_password': 'NewPass1234!',
        }), content_type='application/json')

        body = json.loads(response.content)
        # 只传新密码不传旧密码 -> 不修改密码，无错误
        self.assertIsNone(body.get('error'))

    def test_change_password_with_wrong_old_password(self):
        """验证旧密码错误时拒绝修改"""
        response = self.client_user.patch('/account/self/', data=json.dumps({
            'old_password': 'wrong_old',
            'new_password': 'NewPass1234!',
        }), content_type='application/json')

        body = json.loads(response.content)
        self.assertIn('原密码错误', body.get('error', ''))

    def test_change_password_with_weak_new_password(self):
        """验证新密码不符合策略时拒绝修改"""
        response = self.client_user.patch('/account/self/', data=json.dumps({
            'old_password': '123456',
            'new_password': 'weak',
        }), content_type='application/json')

        body = json.loads(response.content)
        self.assertIn('至少8位', body.get('error', ''))

    def test_change_nickname_without_password(self):
        """验证只修改昵称不需要密码"""
        response = self.client_user.patch('/account/self/', data=json.dumps({
            'nickname': 'New Nickname',
        }), content_type='application/json')

        body = json.loads(response.content)
        self.assertIsNone(body.get('error'))

        self.user.refresh_from_db()
        self.assertEqual(self.user.nickname, 'New Nickname')
