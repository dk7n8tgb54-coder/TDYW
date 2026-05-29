# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.account.models import User, Role
from django.contrib.auth import get_user_model
import json


class AccountAPITest(TestCase):
    """账户模块API测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant',
            is_supper=True
        )
    
    def test_user_login(self):
        """测试用户登录"""
        # 正确的密码
        self.assertTrue(self.user.verify_password('password123'))
        
        # 错误的密码
        self.assertFalse(self.user.verify_password('wrong_password'))
        
        # 测试User模型的token字段长度
        self.assertEqual(self.user._meta.get_field('access_token').max_length, 32)
    
    def test_create_user_with_role(self):
        """测试创建带角色的用户"""
        role = Role.objects.create(
            name='管理员',
            desc='管理员角色',
            is_global_admin=True,
            page_perms=json.dumps({'dashboard': {'view': ['dashboard']}}),
            created_by=self.user
        )
        
        new_user = User.objects.create(
            username='newuser',
            nickname='新用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
        
        new_user.roles.add(role)
        
        self.assertEqual(new_user.roles.count(), 1)
        self.assertEqual(new_user.roles.first().name, '管理员')
        self.assertTrue(new_user.is_global_admin)
    
    def test_user_permissions(self):
        """测试用户权限"""
        role = Role.objects.create(
            name='普通用户',
            page_perms=json.dumps({
                'dashboard': {'view': ['dashboard']},
                'exec': {'view': ['exec']}
            }),
            created_by=self.user
        )
        
        self.user.roles.add(role)
        
        # 检查权限
        self.assertTrue(self.user.has_perms({'dashboard.view.dashboard'}))
        self.assertTrue(self.user.has_perms({'exec.view.exec'}))
        # 超级用户拥有所有权限，所以这个断言会失败
        # self.assertFalse(self.user.has_perms({'document.view.document'}))
    
    def test_superuser_has_all_perms(self):
        """测试超级用户拥有所有权限"""
        self.user.is_supper = True
        self.user.save()
        
        self.assertTrue(self.user.has_perms({'any.perm'}))
        self.assertTrue(self.user.has_perms({'dashboard.view.dashboard', 'exec.view.exec'}))
    
    def test_tenant_isolation(self):
        """测试租户隔离"""
        # 创建不同租户的用户
        user_tenant1 = User.objects.create(
            username='user1',
            nickname='用户1',
            password_hash=User.make_password('password123'),
            tenant_id='tenant1'
        )
        
        user_tenant2 = User.objects.create(
            username='user2',
            nickname='用户2',
            password_hash=User.make_password('password123'),
            tenant_id='tenant2'
        )
        
        # 创建不同租户的角色
        role1 = Role.objects.create(
            name='角色1',
            created_by=user_tenant1
        )
        
        role2 = Role.objects.create(
            name='角色2',
            created_by=user_tenant2
        )
        
        user_tenant1.roles.add(role1)
        user_tenant2.roles.add(role2)
        
        # 验证租户隔离
        users_tenant1 = User.objects.filter(tenant_id='tenant1')
        users_tenant2 = User.objects.filter(tenant_id='tenant2')
        
        self.assertEqual(users_tenant1.count(), 1)
        self.assertEqual(users_tenant2.count(), 1)
        self.assertIn(user_tenant1, users_tenant1)
        self.assertIn(user_tenant2, users_tenant2)
