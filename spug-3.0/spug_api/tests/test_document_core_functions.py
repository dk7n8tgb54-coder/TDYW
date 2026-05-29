# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
文档管理核心函数测试
测试apply_tenant_filter函数和其他核心工具函数
"""
import os
import time
from django.test import TestCase
from apps.account.models import User
from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate,
    DocumentFolderPublic, DocumentFilePublic
)
from apps.libs.tenant_utils import apply_tenant_filter
from apps.document.libs.document_utils import (
    get_folder_model, get_file_model, get_document_relative_path,
    get_document_absolute_path, is_safe_path, is_global_admin
)


class DocumentCoreFunctionsTest(TestCase):
    """文档管理核心函数测试"""

    def setUp(self):
        """测试前准备"""
        # 创建管理员用户
        self.admin = User.objects.create(
            username='admin',
            nickname='管理员',
            password_hash=User.make_password('password123'),
            is_supper=True,
            is_active=True,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default'
        )

        # 创建普通用户（有tenant_id）
        self.user_with_tenant = User.objects.create(
            username='user_with_tenant',
            nickname='有租户用户',
            password_hash=User.make_password('password123'),
            is_supper=False,
            is_active=True,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default',
            tenant_id='tenant1'
        )

        # 创建普通用户（无tenant_id）
        self.user_no_tenant = User.objects.create(
            username='user_no_tenant',
            nickname='无租户用户',
            password_hash=User.make_password('password123'),
            is_supper=False,
            is_active=True,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default'
            # 故意不设置tenant_id，测试默认值
        )

        # 创建测试数据
        # 公共文件夹
        self.public_folder = DocumentFolderPublic.objects.create(
            name='公共文件夹',
            created_by=self.admin
        )

        # 私有文件夹（有租户）
        self.private_folder_with_tenant = DocumentFolderPrivate.objects.create(
            name='私有文件夹_tenant1',
            created_by=self.user_with_tenant,
            tenant_id='tenant1'
        )

        # 私有文件夹（admin租户）
        self.private_folder_admin = DocumentFolderPrivate.objects.create(
            name='私有文件夹_admin',
            created_by=self.user_no_tenant,
            tenant_id='admin'
        )

    def test_apply_tenant_filter_admin(self):
        """测试管理员使用apply_tenant_filter"""
        print("\n=== 测试管理员使用apply_tenant_filter ===")

        # 管理员应该看到所有私有文件夹
        queryset = DocumentFolderPrivate.objects.all()
        filtered_queryset = apply_tenant_filter(queryset, self.admin)
        self.assertEqual(filtered_queryset.count(), 2)  # 两个私有文件夹

        print("✓ 管理员使用apply_tenant_filter测试通过")

    def test_apply_tenant_filter_with_tenant(self):
        """测试有tenant_id的用户使用apply_tenant_filter"""
        print("\n=== 测试有tenant_id的用户使用apply_tenant_filter ===")

        # 有租户的用户应该只看到自己租户的文件夹
        queryset = DocumentFolderPrivate.objects.all()
        filtered_queryset = apply_tenant_filter(queryset, self.user_with_tenant)
        self.assertEqual(filtered_queryset.count(), 1)  # 只看到tenant1的文件夹
        self.assertEqual(filtered_queryset.first().name, '私有文件夹_tenant1')

        print("✓ 有tenant_id的用户使用apply_tenant_filter测试通过")

    def test_apply_tenant_filter_no_tenant(self):
        """测试无tenant_id的用户使用apply_tenant_filter"""
        print("\n=== 测试无tenant_id的用户使用apply_tenant_filter ===")

        # 无租户的用户应该看到admin租户的文件夹
        queryset = DocumentFolderPrivate.objects.all()
        filtered_queryset = apply_tenant_filter(queryset, self.user_no_tenant)
        self.assertEqual(filtered_queryset.count(), 1)  # 只看到admin的文件夹
        self.assertEqual(filtered_queryset.first().name, '私有文件夹_admin')

        print("✓ 无tenant_id的用户使用apply_tenant_filter测试通过")

    def test_get_folder_model(self):
        """测试get_folder_model函数"""
        print("\n=== 测试get_folder_model函数 ===")

        # 测试公共文件夹模型
        public_model = get_folder_model(is_public=True)
        self.assertEqual(public_model.__name__, 'DocumentFolderPublic')

        # 测试私有文件夹模型
        private_model = get_folder_model(is_public=False)
        self.assertEqual(private_model.__name__, 'DocumentFolderPrivate')

        print("✓ get_folder_model函数测试通过")

    def test_get_file_model(self):
        """测试get_file_model函数"""
        print("\n=== 测试get_file_model函数 ===")

        # 测试公共文件模型
        public_model = get_file_model(is_public=True)
        self.assertEqual(public_model.__name__, 'DocumentFilePublic')

        # 测试私有文件模型
        private_model = get_file_model(is_public=False)
        self.assertEqual(private_model.__name__, 'DocumentFilePrivate')

        print("✓ get_file_model函数测试通过")

    def test_get_document_relative_path(self):
        """测试get_document_relative_path函数"""
        print("\n=== 测试get_document_relative_path函数 ===")

        # 测试公共空间路径
        public_path = get_document_relative_path(is_public=True, folder_id=1)
        self.assertEqual(public_path, 'public/folder-1')

        public_root_path = get_document_relative_path(is_public=True)
        self.assertEqual(public_root_path, 'public')

        # 测试私有空间路径
        private_path = get_document_relative_path(is_public=False, user_id=1, folder_id=1)
        self.assertEqual(private_path, 'private/user-1/folder-1')

        private_root_path = get_document_relative_path(is_public=False, user_id=1)
        self.assertEqual(private_root_path, 'private/user-1')

        # 测试私有空间缺少user_id
        with self.assertRaises(ValueError):
            get_document_relative_path(is_public=False)

        print("✓ get_document_relative_path函数测试通过")

    def test_is_safe_path(self):
        """测试is_safe_path函数"""
        print("\n=== 测试is_safe_path函数 ===")

        # 测试安全路径
        base_path = '/path/to/base'
        safe_path = '/path/to/base/subdir/file.txt'
        self.assertTrue(is_safe_path(base_path, safe_path))

        # 测试不安全路径（路径遍历）
        unsafe_path = '/path/to/other/file.txt'
        self.assertFalse(is_safe_path(base_path, unsafe_path))

        print("✓ is_safe_path函数测试通过")

    def test_is_global_admin(self):
        """测试is_global_admin函数"""
        print("\n=== 测试is_global_admin函数 ===")

        # 测试管理员
        self.assertTrue(is_global_admin(self.admin))

        # 测试普通用户
        self.assertFalse(is_global_admin(self.user_with_tenant))
        self.assertFalse(is_global_admin(self.user_no_tenant))

        print("✓ is_global_admin函数测试通过")

    def test_public_folder_query_without_tenant(self):
        """测试无tenant_id时的公共文件夹查询"""
        print("\n=== 测试无tenant_id时的公共文件夹查询 ===")

        # 测试公共文件夹查询（不应该应用tenant_id过滤）
        public_folders = DocumentFolderPublic.objects.all()
        self.assertEqual(public_folders.count(), 1)
        self.assertEqual(public_folders.first().name, '公共文件夹')

        # 测试通过get_folder_model获取公共文件夹
        FolderModel = get_folder_model(is_public=True)
        public_folders = FolderModel.objects.all()
        self.assertEqual(public_folders.count(), 1)
        self.assertEqual(public_folders.first().name, '公共文件夹')

        print("✓ 无tenant_id时的公共文件夹查询测试通过")


def run_all_tests():
    """运行所有测试"""
    import sys
    from django.test.utils import get_runner
    from django.conf import settings

    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2, interactive=False, keepdb=False)

    failures = test_runner.run_tests([
        'tests.test_document_core_functions'
    ])

    if failures:
        print(f"\n❌ 测试失败: {failures}")
        return False
    else:
        print("\n✅ 所有测试通过!")
        return True


if __name__ == '__main__':
    print("=" * 60)
    print("文档管理核心函数测试")
    print("=" * 60)
    success = run_all_tests()
    sys.exit(0 if success else 1)
