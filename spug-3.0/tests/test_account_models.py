# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.account.models import User, Role, History
from django.core.cache import cache
import json


class UserModelTest(TestCase):
    """User模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_user(self):
        """测试创建用户"""
        self.assertEqual(self.user.username, 'testuser')
        self.assertEqual(self.user.nickname, '测试用户')
        self.assertEqual(self.user.tenant_id, 'test_tenant')
        self.assertTrue(self.user.is_active)
    
    def test_password_hashing(self):
        """测试密码哈希"""
        self.assertTrue(self.user.verify_password('password123'))
        self.assertFalse(self.user.verify_password('wrong_password'))
    
    def test_is_global_admin(self):
        """测试全局管理员判断"""
        self.assertFalse(self.user.is_global_admin)
        
        role = Role.objects.create(
            name='管理员',
            is_global_admin=True,
            created_by=self.user
        )
        self.user.roles.add(role)
        self.assertTrue(self.user.is_global_admin)
    
    def test_page_perms(self):
        """测试页面权限"""
        role = Role.objects.create(
            name='普通角色',
            page_perms=json.dumps({'dashboard': {'view': ['dashboard']}}),
            created_by=self.user
        )
        self.user.roles.add(role)
        perms = self.user.page_perms
        self.assertIn('dashboard.view.dashboard', perms)
    
    def test_has_perms(self):
        """测试权限检查"""
        role = Role.objects.create(
            name='普通角色',
            page_perms=json.dumps({'dashboard': {'view': ['dashboard']}}),
            created_by=self.user
        )
        self.user.roles.add(role)
        
        self.assertTrue(self.user.has_perms({'dashboard.view.dashboard'}))
        self.assertFalse(self.user.has_perms({'exec.view.exec'}))
        
        # 超级用户拥有所有权限
        self.user.is_supper = True
        self.user.save()
        self.assertTrue(self.user.has_perms({'any.perm'}))


class RoleModelTest(TestCase):
    """Role模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='admin',
            nickname='管理员',
            password_hash=User.make_password('admin123'),
            tenant_id='admin',
            is_supper=True
        )
        self.role = Role.objects.create(
            name='测试角色',
            desc='这是一个测试角色',
            is_global_admin=False,
            page_perms=json.dumps({'dashboard': {'view': ['dashboard']}}),
            created_by=self.user
        )
    
    def test_create_role(self):
        """测试创建角色"""
        self.assertEqual(self.role.name, '测试角色')
        self.assertEqual(self.role.desc, '这是一个测试角色')
        self.assertFalse(self.role.is_global_admin)
    
    def test_to_dict(self):
        """测试转换为字典"""
        role_dict = self.role.to_dict()
        self.assertEqual(role_dict['name'], '测试角色')
        self.assertIsInstance(role_dict['page_perms'], dict)
        self.assertIn('dashboard', role_dict['page_perms'])
        self.assertEqual(role_dict['used'], 0)  # 未被使用
    
    def test_add_deploy_perm(self):
        """测试添加部署权限"""
        self.role.add_deploy_perm('apps', 'test_app')
        self.role.refresh_from_db()
        perms = json.loads(self.role.deploy_perms)
        self.assertIn('test_app', perms['apps'])
    
    def test_clear_perms_cache(self):
        """测试清除权限缓存"""
        self.user.roles.add(self.role)
        cache.set(f'perms_{self.user.id}', {'test_perm'})
        self.role.clear_perms_cache()
        cached_perms = cache.get(f'perms_{self.user.id}')
        self.assertEqual(cached_perms, set())


class HistoryModelTest(TestCase):
    """History模型测试"""
    
    def test_create_history(self):
        """测试创建登录历史"""
        history = History.objects.create(
            username='testuser',
            type='default',
            ip='192.168.1.1',
            agent='Mozilla/5.0',
            message='登录成功',
            is_success=True
        )
        self.assertEqual(history.username, 'testuser')
        self.assertEqual(history.ip, '192.168.1.1')
        self.assertTrue(history.is_success)
