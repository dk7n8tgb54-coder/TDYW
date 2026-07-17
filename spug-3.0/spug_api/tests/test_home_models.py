# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.home.models import Notice, Navigation
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
