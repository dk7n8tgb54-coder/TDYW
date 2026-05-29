# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase, Client
from apps.account.models import User
from apps.home.models import Notice, Navigation, Todo
from apps.setting.utils import AppSetting
import json


class HomeAPITest(TestCase):
    """首页模块API测试"""

    def setUp(self):
        """测试前准备"""
        # 创建32位token
        import time
        token = 'a' * 32

        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant',
            is_supper=True,
            is_active=True,
            access_token=token,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default'
        )
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = token
        self.client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        # 禁用IP绑定
        AppSetting.set('bind_ip', False)

    def test_get_notices(self):
        """测试获取通知列表"""
        Notice.objects.create(
            title='测试通知',
            content='测试内容',
            is_stress=False,
            read_ids='[]',
            sort_id=1
        )

        response = self.client.get('/home/notice/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)
        self.assertIsInstance(data['data'], list)

    def test_get_navigation(self):
        """测试获取导航列表"""
        Navigation.objects.create(
            title='测试导航',
            desc='描述',
            logo='data:image/png;base64,iVBORw0KG...',
            links='[{"name":"测试","url":"http://test.com"}]',
            sort_id=1
        )

        response = self.client.get('/home/navigation/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_create_todo(self):
        """测试创建待办事项"""
        response = self.client.post(
            '/home/todo/',
            data=json.dumps({
                'title': '测试待办',
                'description': '描述',
                'priority': 'medium'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data.get('error'))

        # 验证待办已创建
        todo = Todo.objects.filter(user_id=self.user.id).first()
        self.assertIsNotNone(todo)
        self.assertEqual(todo.title, '测试待办')

    def test_get_todos(self):
        """测试获取待办列表"""
        Todo.objects.create(
            user_id=self.user.id,
            user_name=self.user.nickname,
            title='待办1',
            status='pending',
            priority='high',
            created_by=self.user
        )

        response = self.client.get('/home/todo/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_update_todo(self):
        """测试更新待办事项"""
        todo = Todo.objects.create(
            user_id=self.user.id,
            user_name=self.user.nickname,
            title='待办1',
            status='pending',
            priority='high',
            created_by=self.user
        )

        response = self.client.post(
            '/home/todo/',
            data=json.dumps({
                'id': todo.id,
                'title': '更新后的待办',
                'status': 'completed'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        # 验证待办已更新
        todo.refresh_from_db()
        self.assertEqual(todo.title, '更新后的待办')
        self.assertEqual(todo.status, 'completed')

    def test_unauthorized_access(self):
        """测试未授权访问"""
        # 删除 token
        del self.client.defaults['HTTP_X_TOKEN']

        response = self.client.get('/api/home/notice/')
        self.assertEqual(response.status_code, 401)
