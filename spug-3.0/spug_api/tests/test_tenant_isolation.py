# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.upgrade.models import UpgradeRecord
from apps.interference.models import InterferenceEvent
from apps.account.models import User, Role
from apps.utils.test_helpers import make_upgrade_no
from libs.tenant_utils import apply_tenant_filter
import json


class TenantFilterTest(TestCase):
    """多租户过滤测试"""

    def setUp(self):
        """测试前准备"""
        # 创建不同租户的用户
        self.user1 = User.objects.create(
            username='user1',
            nickname='用户1',
            password_hash=User.make_password('password123'),
            tenant_id='tenant1',
            access_token='u1' * 16,
        )

        self.user2 = User.objects.create(
            username='user2',
            nickname='用户2',
            password_hash=User.make_password('password123'),
            tenant_id='tenant2',
            access_token='u2' * 16,
        )

        self.global_admin = User.objects.create(
            username='admin',
            nickname='全局管理员',
            password_hash=User.make_password('admin123'),
            tenant_id='admin',
            is_supper=True,
            access_token='ad' * 16,
        )

    def _make_interference(self, tenant_id, user, phenomenon):
        return InterferenceEvent.objects.create(
            tenant_id=tenant_id,
            datetime='2024-01-15 10:00:00',
            scene_code='unknown', classification_status='pending',
            interference_kind_code='other', affected_system_code='other',
            source_type_code='unknown', phenomenon=phenomenon,
            created_by=user
        )

    def test_interference_tenant_filter(self):
        """测试干扰事件的租户过滤"""
        # 创建不同租户的干扰事件
        self._make_interference('tenant1', self.user1, '事件1')
        self._make_interference('tenant2', self.user2, '事件2')
        self._make_interference('tenant1', self.user1, '事件3')

        # 用户1只能看到tenant1的数据
        queryset = InterferenceEvent.objects.all()
        filtered = apply_tenant_filter(queryset, self.user1)
        self.assertEqual(filtered.count(), 2)

        # 用户2只能看到tenant2的数据
        filtered = apply_tenant_filter(queryset, self.user2)
        self.assertEqual(filtered.count(), 1)

    def test_upgrade_record_tenant_filter(self):
        """测试升级记录的租户过滤"""
        # 创建不同租户的升级记录
        for i in range(3):
            UpgradeRecord.objects.create(
                upgrade_no=make_upgrade_no(),
                tenant_id='tenant1',
                system_name=f'系统{i}',
                upgrade_type='升级',
                upgrade_time='2024-01-15',
                created_at='2024-01-15',
                owner='张三',
                created_by=self.user1
            )

        for i in range(2):
            UpgradeRecord.objects.create(
                upgrade_no=make_upgrade_no(),
                tenant_id='tenant2',
                system_name=f'系统{i+3}',
                upgrade_type='升级',
                upgrade_time='2024-01-15',
                created_at='2024-01-15',
                owner='李四',
                created_by=self.user2
            )

        queryset = UpgradeRecord.objects.all()

        # 用户1只能看到tenant1的数据
        filtered = apply_tenant_filter(queryset, self.user1)
        self.assertEqual(filtered.count(), 3)

        # 用户2只能看到tenant2的数据
        filtered = apply_tenant_filter(queryset, self.user2)
        self.assertEqual(filtered.count(), 2)

    def test_global_admin_no_filter(self):
        """测试全局管理员不过滤"""
        # 创建不同租户的数据
        self._make_interference('tenant1', self.user1, '事件1')
        self._make_interference('tenant2', self.user2, '事件2')

        queryset = InterferenceEvent.objects.all()

        # 全局管理员应该能看到所有数据
        global_role = Role.objects.create(
            name='全局管理员',
            is_global_admin=True,
            created_by=self.global_admin
        )
        self.global_admin.roles.add(global_role)

        filtered = apply_tenant_filter(queryset, self.global_admin)
        self.assertEqual(filtered.count(), 2)
