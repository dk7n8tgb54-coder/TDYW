# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.home.models import Notice, Navigation, Todo
from apps.account.models import User
import json


class NoticeModelTest(TestCase):
    """Notice模型测试"""
    
    def test_create_notice(self):
        """测试创建通知"""
        notice = Notice.objects.create(
            title='测试通知',
            content='这是一个测试通知',
            is_stress=False,
            read_ids='[]',
            sort_id=1
        )
        self.assertEqual(notice.title, '测试通知')
        self.assertEqual(notice.content, '这是一个测试通知')
        self.assertFalse(notice.is_stress)
        self.assertEqual(notice.sort_id, 1)
    
    def test_create_stress_notice(self):
        """测试创建重要通知"""
        notice = Notice.objects.create(
            title='重要通知',
            content='系统维护通知',
            is_stress=True,
            read_ids='[]',
            sort_id=0
        )
        self.assertTrue(notice.is_stress)
        self.assertEqual(notice.sort_id, 0)
    
    def test_notice_to_view(self):
        """测试通知视图转换"""
        notice = Notice.objects.create(
            title='测试通知',
            content='内容',
            read_ids='[1, 2, 3]',
            sort_id=1
        )
        
        view = notice.to_view()
        self.assertEqual(view['title'], '测试通知')
        self.assertIsInstance(view['read_ids'], list)
        self.assertEqual(view['read_ids'], [1, 2, 3])
    
    def test_notice_ordering(self):
        """测试通知排序"""
        notice1 = Notice.objects.create(title='通知1', content='内容1', sort_id=2)
        notice2 = Notice.objects.create(title='通知2', content='内容2', sort_id=1)
        notice3 = Notice.objects.create(title='通知3', content='内容3', sort_id=3)
        
        notices = list(Notice.objects.all())
        self.assertEqual(notices[0], notice3)  # 按sort_id倒序
        self.assertEqual(notices[1], notice1)
        self.assertEqual(notices[2], notice2)


class NavigationModelTest(TestCase):
    """Navigation模型测试"""
    
    def test_create_navigation(self):
        """测试创建导航"""
        navigation = Navigation.objects.create(
            title='测试导航',
            desc='这是一个测试导航',
            logo='data:image/png;base64,iVBORw0KG...',
            links='[{"name":"测试","url":"http://test.com"}]',
            sort_id=1
        )
        self.assertEqual(navigation.title, '测试导航')
        self.assertEqual(navigation.desc, '这是一个测试导航')
        self.assertEqual(navigation.sort_id, 1)
    
    def test_navigation_to_view(self):
        """测试导航视图转换"""
        links = [
            {'name': '测试1', 'url': 'http://test1.com'},
            {'name': '测试2', 'url': 'http://test2.com'}
        ]
        navigation = Navigation.objects.create(
            title='测试导航',
            desc='描述',
            logo='logo',
            links=json.dumps(links),
            sort_id=1
        )
        
        view = navigation.to_view()
        self.assertEqual(view['title'], '测试导航')
        self.assertIsInstance(view['links'], list)
        self.assertEqual(len(view['links']), 2)
        self.assertEqual(view['links'][0]['name'], '测试1')
    
    def test_navigation_ordering(self):
        """测试导航排序"""
        nav1 = Navigation.objects.create(title='导航1', desc='描述1', logo='logo1', links='[]', sort_id=2)
        nav2 = Navigation.objects.create(title='导航2', desc='描述2', logo='logo2', links='[]', sort_id=1)
        
        navs = list(Navigation.objects.all())
        self.assertEqual(navs[0], nav1)  # 按sort_id倒序
        self.assertEqual(navs[1], nav2)


class TodoModelTest(TestCase):
    """Todo模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_todo(self):
        """测试创建待办事项"""
        todo = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='测试待办',
            description='这是一个测试待办事项',
            status='pending',
            priority='medium',
            due_date='2024-12-31',
            created_by=self.user
        )
        self.assertEqual(todo.title, '测试待办')
        self.assertEqual(todo.user_name, '测试用户')
        self.assertEqual(todo.status, 'pending')
        self.assertEqual(todo.priority, 'medium')
        self.assertEqual(todo.due_date, '2024-12-31')
    
    def test_create_todo_with_high_priority(self):
        """测试创建高优先级待办"""
        todo = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='紧急待办',
            status='pending',
            priority='high',
            created_by=self.user
        )
        self.assertEqual(todo.priority, 'high')
    
    def test_create_todo_with_low_priority(self):
        """测试创建低优先级待办"""
        todo = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='普通待办',
            status='pending',
            priority='low',
            created_by=self.user
        )
        self.assertEqual(todo.priority, 'low')
    
    def test_complete_todo(self):
        """测试完成待办"""
        todo = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='测试待办',
            status='pending',
            created_by=self.user
        )
        
        self.assertEqual(todo.status, 'pending')
        
        todo.status = 'completed'
        todo.save()
        
        todo.refresh_from_db()
        self.assertEqual(todo.status, 'completed')
    
    def test_todo_repr(self):
        """测试待办字符串表示"""
        todo = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='测试待办',
            status='pending',
            created_by=self.user
        )
        self.assertEqual(repr(todo), '<Todo \'测试待办\'>')
    
    def test_todo_ordering(self):
        """测试待办排序"""
        todo1 = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='待办1',
            status='pending',
            created_by=self.user
        )
        todo2 = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='待办2',
            status='pending',
            created_by=self.user
        )
        todo3 = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='待办3',
            status='pending',
            created_by=self.user
        )
        
        todos = list(Todo.objects.all())
        self.assertEqual(todos[0], todo3)  # 按创建时间和ID倒序
        self.assertEqual(todos[1], todo2)
        self.assertEqual(todos[2], todo1)
    
    def test_todo_to_view(self):
        """测试待办视图转换"""
        todo = Todo.objects.create(
            user_id=self.user.id,
            user_name='测试用户',
            title='测试待办',
            description='描述',
            status='pending',
            priority='high',
            due_date='2024-12-31',
            created_by=self.user
        )
        
        view = todo.to_view()
        self.assertEqual(view['title'], '测试待办')
        self.assertEqual(view['status'], 'pending')
        self.assertEqual(view['priority'], 'high')
        self.assertEqual(view['due_date'], '2024-12-31')
    
    def test_user_todos(self):
        """测试用户的待办事项"""
        user2 = User.objects.create(
            username='user2',
            nickname='用户2',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
        
        Todo.objects.create(user_id=self.user.id, user_name='测试用户', title='待办1', status='pending', created_by=self.user)
        Todo.objects.create(user_id=self.user.id, user_name='测试用户', title='待办2', status='pending', created_by=self.user)
        Todo.objects.create(user_id=user2.id, user_name='用户2', title='待办3', status='pending', created_by=self.user)
        
        user1_todos = Todo.objects.filter(user_id=self.user.id)
        self.assertEqual(user1_todos.count(), 2)
        
        user2_todos = Todo.objects.filter(user_id=user2.id)
        self.assertEqual(user2_todos.count(), 1)
