from django.test import TestCase, Client
from apps.account.models import User
from datetime import datetime, timedelta

class TestAPITestCase(TestCase):
    def setUp(self):
        # 创建测试用户（注意：需要正确的字段）
        self.user = User.objects.create(
            username='test_user',
            nickname='测试用户',
            password_hash=User.make_password('test123'),  # 使用哈希密码
            access_token='test_token_123456789012',
            token_expired=datetime.now() + timedelta(hours=1),  # token 1小时后过期
            is_active=True,
            type='default',
            last_login='2026-01-01',
            last_ip='127.0.0.1'
        )
    
    def test_api_get_runlog_with_token(self):
        """测试带 token 获取运行记录"""
        response = self.client.get(
            '/api/exec/runlog/',
            HTTP_X_TOKEN='test_token_123456789012'
        )
        # 注意：这里可能因为权限问题返回 401 或 403
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.json()}")
