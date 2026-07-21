# -*- coding: utf-8 -*-
"""
测试辅助工具：创建测试用户/客户端/环境设置

用法：
    from apps.utils.test_helpers import make_user, make_client, setup_test_env

    class MyTest(TestCase):
        def setUp(self):
            setup_test_env(self)
            self.user = make_user('tester', ['xxx.xxx.view'])
            self.client_auth = make_client(self.user)
"""
import time
from apps.account.models import User
from django.test import Client


def make_user(username, perms=None, is_supper=False):
    """创建测试用户并设置权限缓存

    Args:
        username: 用户名
        perms: 权限码列表，如 ['interference.interference.view']
        is_supper: 是否超管（超管无需 perms）
    """
    token = (username * 10)[:32]
    user = User.objects.create(
        username=username,
        nickname=username,
        password_hash='x',
        is_active=True,
        is_supper=is_supper,
        access_token=token,
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01',
        last_ip='127.0.0.1',
        type='default',
    )
    if not is_supper:
        # version=0 匹配无角色用户的 _get_roles_perms_version() 返回值
        user.set_perms_cache(set(perms or []), version=0)
    return user


def make_client(user):
    """创建带认证头的测试客户端"""
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


def setup_test_env(test_case):
    """通用的 setUp：清理缓存 + 关闭 IP 绑定 + 注册 tearDown

    用法：
        def setUp(self):
            setup_test_env(self)
    """
    from django.core.cache import cache
    from apps.setting.utils import AppSetting
    cache.clear()
    AppSetting.set('bind_ip', False)
    test_case.addCleanup(lambda: cache.clear())
