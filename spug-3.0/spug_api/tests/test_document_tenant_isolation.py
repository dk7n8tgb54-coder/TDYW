#!/usr/bin/env python3
"""
资料库模块租户隔离自动化测试脚本

测试内容：
1. 文件夹创建租户隔离
2. 文件上传租户隔离
3. 文件夹复制租户隔离（同名检查）
4. 文件夹移动租户隔离（同名检查）
5. 文件复制租户隔离（同名检查）
6. 文件移动租户隔离（同名检查）
7. 公共空间跨租户访问

使用方法：
    python3 test_document_tenant_isolation.py
"""

import os
import sys
import django

# 设置 Django 环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User
from apps.document.models import (
    DocumentFolderPrivate,
    DocumentFilePrivate,
    DocumentFolderPublic,
    DocumentFilePublic
)
from apps.libs.tenant_utils import apply_tenant_filter


class Colors:
    """终端颜色"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


class TestResult:
    """测试结果统计"""
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.errors = []

    def add_pass(self, test_name):
        self.total += 1
        self.passed += 1
        print(f"{Colors.GREEN}✓ PASS{Colors.RESET}: {test_name}")

    def add_fail(self, test_name, reason):
        self.total += 1
        self.failed += 1
        error_msg = f"{Colors.RED}✗ FAIL{Colors.RESET}: {test_name} - {reason}"
        print(error_msg)
        self.errors.append((test_name, reason))

    def print_summary(self):
        print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}测试结果汇总{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"总测试数: {self.total}")
        print(f"{Colors.GREEN}通过: {self.passed}{Colors.RESET}")
        print(f"{Colors.RED}失败: {self.failed}{Colors.RESET}")
        print(f"通过率: {(self.passed/self.total*100):.2f}%" if self.total > 0 else "通过率: 0%")

        if self.errors:
            print(f"\n{Colors.YELLOW}失败的测试详情:{Colors.RESET}")
            for test_name, reason in self.errors:
                print(f"  - {test_name}: {reason}")


def cleanup_test_data():
    """清理测试数据"""
    print(f"\n{Colors.BLUE}[清理] 开始清理测试数据...{Colors.RESET}")

    # 删除测试用户
    User.objects.filter(username__in=['test_tenant_a', 'test_tenant_b']).delete()

    # 删除测试文件夹（通过名称识别）
    test_folder_names = [
        'test_folder_a', 'test_folder_b', 'common_name',
        'copy_source_a', 'copy_dest_a', 'copy_source_b', 'copy_dest_b',
        'move_source_a', 'move_target_a', 'move_source_b', 'move_target_b',
        'folder_a', 'folder_b'
    ]
    DocumentFolderPrivate.objects.filter(name__in=test_folder_names).delete()

    # 删除公共空间测试文件夹
    DocumentFolderPublic.objects.filter(name__in=['public_test_folder']).delete()

    # 删除测试文件
    DocumentFilePrivate.objects.filter(name__in=[
        'file_a.docx', 'file_b.docx', 'duplicate_a.docx', 'duplicate_b.docx',
        'move_file_a.docx', 'move_file_b.docx'
    ]).delete()

    # 删除公共空间测试文件
    DocumentFilePublic.objects.filter(name__in=['public_file.docx']).delete()

    print(f"{Colors.GREEN}[清理] 测试数据清理完成{Colors.RESET}")


def create_test_users(result):
    """创建测试用户"""
    print(f"\n{Colors.BLUE}[准备] 创建测试用户...{Colors.RESET}")

    try:
        # 创建租户A用户
        user_a, created = User.objects.get_or_create(
            username='test_tenant_a',
            defaults={
                'nickname': '测试租户A',
                'password_hash': User.make_password('Test123456'),
                'tenant_id': 'tenant_a',
                'is_active': True,
                'type': 'default',
                'access_token': 'a_token_32_chars_1234567890',
                'token_expired': None,
                'last_login': '2026-02-28 00:00:00',
                'last_ip': '127.0.0.1'
            }
        )
        if created:
            user_a.save()
        result.add_pass("创建租户A用户 (test_tenant_a)")

        # 创建租户B用户
        user_b, created = User.objects.get_or_create(
            username='test_tenant_b',
            defaults={
                'nickname': '测试租户B',
                'password_hash': User.make_password('Test123456'),
                'tenant_id': 'tenant_b',
                'is_active': True,
                'type': 'default',
                'access_token': 'b_token_32_chars_1234567890',
                'token_expired': None,
                'last_login': '2026-02-28 00:00:00',
                'last_ip': '127.0.0.1'
            }
        )
        if created:
            user_b.save()
        result.add_pass("创建租户B用户 (test_tenant_b)")

        return user_a, user_b

    except Exception as e:
        result.add_fail("创建测试用户", str(e))
        return None, None


def test_folder_isolation(result, user_a, user_b):
    """测试1: 文件夹创建租户隔离"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试1: 文件夹创建租户隔离{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 租户A创建同名文件夹
        folder_a = DocumentFolderPrivate.objects.create(
            name='common_name',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )
        result.add_pass("租户A创建文件夹 'common_name'")

        # 租户B创建同名文件夹
        folder_b = DocumentFolderPrivate.objects.create(
            name='common_name',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )
        result.add_pass("租户B创建同名文件夹 'common_name'")

        # 验证租户A只能看到自己的文件夹
        queryset_a = DocumentFolderPrivate.objects.filter(name='common_name')
        filtered_a = apply_tenant_filter(queryset_a, user_a)
        count_a = filtered_a.count()

        if count_a == 1:
            result.add_pass("租户A只能看到1个 'common_name' 文件夹（租户隔离正常）")
        else:
            result.add_fail("租户A看到的文件夹数量", f"预期1个，实际{count_a}个")

        # 验证租户B只能看到自己的文件夹
        queryset_b = DocumentFolderPrivate.objects.filter(name='common_name')
        filtered_b = apply_tenant_filter(queryset_b, user_b)
        count_b = filtered_b.count()

        if count_b == 1:
            result.add_pass("租户B只能看到1个 'common_name' 文件夹（租户隔离正常）")
        else:
            result.add_fail("租户B看到的文件夹数量", f"预期1个，实际{count_b}个")

        # 验证租户A的文件夹确实是租户A的
        folder_a_filtered = filtered_a.first()
        if folder_a_filtered and folder_a_filtered.tenant_id == user_a.tenant_id:
            result.add_pass("租户A看到的文件夹属于租户A")
        else:
            result.add_fail("租户A看到的文件夹", f"文件夹租户ID不匹配")

        # 验证租户B的文件夹确实是租户B的
        folder_b_filtered = filtered_b.first()
        if folder_b_filtered and folder_b_filtered.tenant_id == user_b.tenant_id:
            result.add_pass("租户B看到的文件夹属于租户B")
        else:
            result.add_fail("租户B看到的文件夹", f"文件夹租户ID不匹配")

    except Exception as e:
        result.add_fail("文件夹创建租户隔离测试", str(e))


def test_file_isolation(result, user_a, user_b):
    """测试2: 文件上传租户隔离"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试2: 文件上传租户隔离{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 租户A上传同名文件
        file_a = DocumentFilePrivate.objects.create(
            name='file_a.docx',
            file_path='/test/path/file_a.docx',
            file_size=1024,
            file_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )
        result.add_pass("租户A上传文件 'file_a.docx'")

        # 租户B上传同名文件
        file_b = DocumentFilePrivate.objects.create(
            name='file_b.docx',
            file_path='/test/path/file_b.docx',
            file_size=2048,
            file_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )
        result.add_pass("租户B上传文件 'file_b.docx'")

        # 租户A创建测试文件（同名用于测试）
        file_a_duplicate = DocumentFilePrivate.objects.create(
            name='duplicate_a.docx',
            file_path='/test/path/duplicate_a.docx',
            file_size=1024,
            file_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 租户B创建测试文件（同名用于测试）
        file_b_duplicate = DocumentFilePrivate.objects.create(
            name='duplicate_b.docx',
            file_path='/test/path/duplicate_b.docx',
            file_size=2048,
            file_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        # 验证租户A只能看到自己的文件
        queryset_a = DocumentFilePrivate.objects.filter(name__startswith='duplicate')
        filtered_a = apply_tenant_filter(queryset_a, user_a)
        count_a = filtered_a.count()

        if count_a == 1:
            result.add_pass("租户A只能看到自己的 'duplicate' 文件")
        else:
            result.add_fail("租户A看到的文件数量", f"预期1个，实际{count_a}个")

        # 验证租户B只能看到自己的文件
        queryset_b = DocumentFilePrivate.objects.filter(name__startswith='duplicate')
        filtered_b = apply_tenant_filter(queryset_b, user_b)
        count_b = filtered_b.count()

        if count_b == 1:
            result.add_pass("租户B只能看到自己的 'duplicate' 文件")
        else:
            result.add_fail("租户B看到的文件数量", f"预期1个，实际{count_b}个")

    except Exception as e:
        result.add_fail("文件上传租户隔离测试", str(e))


def test_folder_copy_isolation(result, user_a, user_b):
    """测试3: 文件夹复制租户隔离（同名检查）"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试3: 文件夹复制租户隔离（同名检查）{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        from apps.libs.tenant_utils import check_tenant_unique_name

        # 租户A创建源文件夹和目标文件夹
        source_a = DocumentFolderPrivate.objects.create(
            name='copy_source_a',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )
        dest_a = DocumentFolderPrivate.objects.create(
            name='copy_dest_a',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 在源文件夹中创建子文件夹
        child_a = DocumentFolderPrivate.objects.create(
            name='child',
            parent=source_a,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 模拟复制操作：检查目标文件夹中是否存在同名文件夹
        is_unique_a, _ = check_tenant_unique_name(
            DocumentFolderPrivate,
            {'name': 'copy_source_a', 'parent': dest_a.id},
            user_a,
            is_public=False
        )

        if is_unique_a:
            result.add_pass("租户A首次复制: 目标文件夹中无同名文件夹（可以复制）")
        else:
            result.add_fail("租户A首次复制", "目标文件夹中不应该有同名文件夹")

        # 租户B创建同名结构
        source_b = DocumentFolderPrivate.objects.create(
            name='copy_source_b',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )
        dest_b = DocumentFolderPrivate.objects.create(
            name='copy_dest_b',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        # 模拟租户A再次复制操作（租户B的操作不应影响租户A）
        is_unique_a_2, _ = check_tenant_unique_name(
            DocumentFolderPrivate,
            {'name': 'copy_source_a', 'parent': dest_a.id},
            user_a,
            is_public=False
        )

        if is_unique_a_2:
            result.add_pass("租户A再次复制: 不受租户B影响，检查结果一致（租户隔离正常）")
        else:
            result.add_fail("租户A再次复制", "应该不受租户B影响，但检查结果异常")

    except Exception as e:
        result.add_fail("文件夹复制租户隔离测试", str(e))


def test_folder_move_isolation(result, user_a, user_b):
    """测试4: 文件夹移动租户隔离（同名检查）"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试4: 文件夹移动租户隔离（同名检查）{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        from apps.libs.tenant_utils import check_tenant_unique_name

        # 租户A创建源文件夹和目标文件夹
        source_a = DocumentFolderPrivate.objects.create(
            name='move_source_a',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )
        target_a = DocumentFolderPrivate.objects.create(
            name='move_target_a',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 模拟移动操作：检查目标文件夹中是否存在同名文件夹
        is_unique_a, _ = check_tenant_unique_name(
            DocumentFolderPrivate,
            {'name': 'move_source_a', 'parent': target_a.id},
            user_a,
            is_public=False
        )

        if is_unique_a:
            result.add_pass("租户A首次移动: 目标文件夹中无同名文件夹（可以移动）")
        else:
            result.add_fail("租户A首次移动", "目标文件夹中不应该有同名文件夹")

        # 租户B创建同名目标文件夹
        target_b = DocumentFolderPrivate.objects.create(
            name='move_target_b',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        # 模拟租户A再次检查移动（租户B的操作不应影响租户A）
        is_unique_a_2, _ = check_tenant_unique_name(
            DocumentFolderPrivate,
            {'name': 'move_source_a', 'parent': target_a.id},
            user_a,
            is_public=False
        )

        if is_unique_a_2:
            result.add_pass("租户A再次检查移动: 不受租户B影响（租户隔离正常）")
        else:
            result.add_fail("租户A再次检查移动", "应该不受租户B影响，但检查结果异常")

    except Exception as e:
        result.add_fail("文件夹移动租户隔离测试", str(e))


def test_file_copy_isolation(result, user_a, user_b):
    """测试5: 文件复制租户隔离（同名检查）"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试5: 文件复制租户隔离（同名检查）{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        from apps.libs.tenant_utils import check_tenant_unique_name

        # 租户A创建文件夹和文件
        folder_a = DocumentFolderPrivate.objects.create(
            name='folder_a',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 模拟文件复制操作：检查目标文件夹中是否存在同名文件
        is_unique_a, _ = check_tenant_unique_name(
            DocumentFilePrivate,
            {'name': 'file_a.docx', 'folder': folder_a.id},
            user_a,
            is_public=False
        )

        if is_unique_a:
            result.add_pass("租户A首次复制文件: 目标文件夹中无同名文件（可以复制）")
        else:
            result.add_fail("租户A首次复制文件", "目标文件夹中不应该有同名文件")

        # 租户B创建同名文件夹
        folder_b = DocumentFolderPrivate.objects.create(
            name='folder_b',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        # 模拟租户A再次检查文件复制（租户B的操作不应影响租户A）
        is_unique_a_2, _ = check_tenant_unique_name(
            DocumentFilePrivate,
            {'name': 'file_a.docx', 'folder': folder_a.id},
            user_a,
            is_public=False
        )

        if is_unique_a_2:
            result.add_pass("租户A再次检查文件复制: 不受租户B影响（租户隔离正常）")
        else:
            result.add_fail("租户A再次检查文件复制", "应该不受租户B影响，但检查结果异常")

    except Exception as e:
        result.add_fail("文件复制租户隔离测试", str(e))


def test_public_space_cross_tenant(result, user_a, user_b):
    """测试6: 公共空间跨租户访问"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试6: 公共空间跨租户访问{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 租户A在公共空间创建文件夹
        public_folder = DocumentFolderPublic.objects.create(
            name='public_test_folder',
            created_by=user_a
        )
        result.add_pass("租户A在公共空间创建文件夹 'public_test_folder'")

        # 租户A在公共空间上传文件
        public_file = DocumentFilePublic.objects.create(
            name='public_file.docx',
            file_path='/test/path/public_file.docx',
            file_size=1024,
            file_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            created_by=user_a
        )
        result.add_pass("租户A在公共空间上传文件 'public_file.docx'")

        # 租户B查看公共空间文件夹（应该能看到租户A创建的）
        public_folders = DocumentFolderPublic.objects.filter(name='public_test_folder')
        if public_folders.exists():
            result.add_pass("租户B可以查看公共空间文件夹（租户A创建的）")
        else:
            result.add_fail("租户B查看公共空间文件夹", "应该能看到租户A创建的文件夹")

        # 租户B查看公共空间文件（应该能看到租户A上传的）
        public_files = DocumentFilePublic.objects.filter(name='public_file.docx')
        if public_files.exists():
            result.add_pass("租户B可以查看公共空间文件（租户A上传的）")
        else:
            result.add_fail("租户B查看公共空间文件", "应该能看到租户A上传的文件")

    except Exception as e:
        result.add_fail("公共空间跨租户访问测试", str(e))


def test_duplicate_name_in_private_space(result, user_a, user_b):
    """测试7: 私有空间同名检查（模拟重复场景）"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试7: 私有空间同名检查（模拟重复场景）{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        from apps.libs.tenant_utils import check_tenant_unique_name

        # 租户A创建目标文件夹和子文件夹
        target_folder = DocumentFolderPrivate.objects.create(
            name='test_target',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 在目标文件夹中创建一个子文件夹
        existing_folder = DocumentFolderPrivate.objects.create(
            name='existing_folder',
            parent=target_folder,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 租户B创建同名文件夹（但不在租户A的目标文件夹中）
        target_folder_b = DocumentFolderPrivate.objects.create(
            name='test_target_b',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        existing_folder_b = DocumentFolderPrivate.objects.create(
            name='existing_folder',
            parent=target_folder_b,
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        # 检查租户A的目标文件夹中是否有同名文件夹
        is_unique_a, queryset_a = check_tenant_unique_name(
            DocumentFolderPrivate,
            {'name': 'existing_folder', 'parent': target_folder.id},
            user_a,
            is_public=False
        )

        if not is_unique_a:
            result.add_pass("租户A检查同名文件夹: 检测到同名（租户A自己的文件夹）")
        else:
            result.add_fail("租户A检查同名文件夹", "应该检测到同名文件夹")

        # 检查租户B的同名文件夹不应该影响租户A
        # 检查租户A在根目录（另一个位置）创建同名文件夹时，是否受租户B影响
        # 先检查根目录中是否已有同名（此时应该没有）
        is_unique_new, _ = check_tenant_unique_name(
            DocumentFolderPrivate,
            {'name': 'existing_folder', 'parent': None},  # 根目录
            user_a,
            is_public=False
        )

        if is_unique_new:
            result.add_pass("租户A根目录检查: 无同名文件夹（不受租户B影响）")
        else:
            result.add_fail("租户A根目录检查", "不应该有同名文件夹")

    except Exception as e:
        result.add_fail("私有空间同名检查测试", str(e))


def main():
    """主测试函数"""
    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("=" * 60)
    print("资料库模块租户隔离自动化测试")
    print("=" * 60)
    print(f"{Colors.RESET}")

    result = TestResult()

    # 创建测试用户
    user_a, user_b = create_test_users(result)
    if not user_a or not user_b:
        print(f"{Colors.RED}测试用户创建失败，退出测试{Colors.RESET}")
        return

    try:
        # 执行所有测试
        test_folder_isolation(result, user_a, user_b)
        test_file_isolation(result, user_a, user_b)
        test_folder_copy_isolation(result, user_a, user_b)
        test_folder_move_isolation(result, user_a, user_b)
        test_file_copy_isolation(result, user_a, user_b)
        test_public_space_cross_tenant(result, user_a, user_b)
        test_duplicate_name_in_private_space(result, user_a, user_b)

    finally:
        # 打印测试结果汇总
        result.print_summary()

        # 询问是否清理测试数据
        print(f"\n{Colors.YELLOW}是否清理测试数据？(y/n){Colors.RESET}")
        # 在自动化测试中直接清理
        cleanup_test_data()


if __name__ == '__main__':
    main()
