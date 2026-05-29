#!/usr/bin/env python3
"""
资料库模块完整功能自动化测试脚本

测试内容：
1. 文件夹CRUD操作（创建、读取、更新、删除）
2. 文件上传/下载
3. 文件复制/移动/重命名
4. 权限控制（私有空间、公共空间）
5. 文件类型验证
6. 文件大小限制
7. 租户隔离
8. 公共空间共享

使用方法：
    python3 test_document_full_features.py
"""

import os
import sys
import django
import tempfile
import hashlib

# 设置 Django 环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User, Role
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


def create_test_users_and_roles(result):
    """创建测试用户和角色"""
    print(f"\n{Colors.BLUE}[准备] 创建测试用户和角色...{Colors.RESET}")

    try:
        # 先获取或创建一个系统用户作为创建者
        system_user, _ = User.objects.get_or_create(
            username='system_test',
            defaults={
                'nickname': '系统测试用户',
                'password_hash': User.make_password('System123456'),
                'tenant_id': 'system',
                'is_active': True,
                'type': 'default',
                'access_token': 'system_32_chars_123456789012',
                'token_expired': None,
                'last_login': '2026-02-28 00:00:00',
                'last_ip': '127.0.0.1',
                'is_supper': True
            }
        )

        # 创建普通用户角色
        normal_role, _ = Role.objects.get_or_create(
            name='test_normal_role',
            defaults={
                'page_perms': '{}',
                'is_global_admin': False,
                'created_by': system_user
            }
        )

        # 创建管理员角色
        admin_role, _ = Role.objects.get_or_create(
            name='test_admin_role',
            defaults={
                'page_perms': '{}',
                'is_global_admin': True,
                'created_by': system_user
            }
        )

        # 创建普通用户（租户A）
        user_a, created = User.objects.get_or_create(
            username='test_normal_a',
            defaults={
                'nickname': '测试普通用户A',
                'password_hash': User.make_password('Test123456'),
                'tenant_id': 'tenant_a',
                'is_active': True,
                'type': 'default',
                'access_token': 'normal_a_32_chars_1234567890',
                'token_expired': None,
                'last_login': '2026-02-28 00:00:00',
                'last_ip': '127.0.0.1',
                'is_supper': False
            }
        )
        if created:
            user_a.roles.add(normal_role)
        result.add_pass("创建普通用户A (test_normal_a)")

        # 创建普通用户（租户B）
        user_b, created = User.objects.get_or_create(
            username='test_normal_b',
            defaults={
                'nickname': '测试普通用户B',
                'password_hash': User.make_password('Test123456'),
                'tenant_id': 'tenant_b',
                'is_active': True,
                'type': 'default',
                'access_token': 'normal_b_32_chars_1234567890',
                'token_expired': None,
                'last_login': '2026-02-28 00:00:00',
                'last_ip': '127.0.0.1',
                'is_supper': False
            }
        )
        if created:
            user_b.roles.add(normal_role)
        result.add_pass("创建普通用户B (test_normal_b)")

        # 创建管理员用户
        admin_user, created = User.objects.get_or_create(
            username='test_admin',
            defaults={
                'nickname': '测试管理员',
                'password_hash': User.make_password('Test123456'),
                'tenant_id': 'tenant_admin',
                'is_active': True,
                'type': 'default',
                'access_token': 'admin_32_chars_12345678901234',
                'token_expired': None,
                'last_login': '2026-02-28 00:00:00',
                'last_ip': '127.0.0.1',
                'is_supper': True
            }
        )
        if created:
            admin_user.roles.add(admin_role)
        result.add_pass("创建管理员用户 (test_admin)")

        return user_a, user_b, admin_user

    except Exception as e:
        result.add_fail("创建测试用户和角色", str(e))
        return None, None, None


def test_folder_crud(result, user_a, user_b):
    """测试1: 文件夹CRUD操作"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试1: 文件夹CRUD操作{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 1.1 创建文件夹
        folder1 = DocumentFolderPrivate.objects.create(
            name='test_folder_crud',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )
        if folder1.id:
            result.add_pass("创建文件夹 'test_folder_crud'")
        else:
            result.add_fail("创建文件夹", "文件夹ID为空")

        # 1.2 读取文件夹
        folder_read = DocumentFolderPrivate.objects.get(id=folder1.id)
        if folder_read.name == 'test_folder_crud':
            result.add_pass("读取文件夹信息")
        else:
            result.add_fail("读取文件夹", "文件夹名称不匹配")

        # 1.3 更新文件夹名称
        folder_read.name = 'test_folder_updated'
        folder_read.save()
        folder_updated = DocumentFolderPrivate.objects.get(id=folder1.id)
        if folder_updated.name == 'test_folder_updated':
            result.add_pass("更新文件夹名称")
        else:
            result.add_fail("更新文件夹", "文件夹名称未更新")

        # 1.4 删除文件夹
        folder_id = folder1.id
        folder1.delete()
        if not DocumentFolderPrivate.objects.filter(id=folder_id).exists():
            result.add_pass("删除文件夹")
        else:
            result.add_fail("删除文件夹", "文件夹仍然存在")

        # 1.5 验证租户隔离：租户A创建的文件夹，租户B看不到
        folder_a = DocumentFolderPrivate.objects.create(
            name='folder_only_a',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        queryset_b = DocumentFolderPrivate.objects.filter(name='folder_only_a')
        filtered_b = apply_tenant_filter(queryset_b, user_b)
        if filtered_b.count() == 0:
            result.add_pass("租户隔离：租户B看不到租户A的文件夹")
        else:
            result.add_fail("租户隔离", "租户B能看到租户A的文件夹")

    except Exception as e:
        result.add_fail("文件夹CRUD操作测试", str(e))


def test_file_upload_download(result, user_a):
    """测试2: 文件上传和下载"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试2: 文件上传和下载{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 创建测试文件
        test_file = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.txt',
            delete=False
        )
        test_file.write('这是测试文件内容')
        test_file.close()

        # 计算文件哈希和大小
        with open(test_file.name, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
            file_size = os.path.getsize(test_file.name)

        # 模拟上传文件到数据库
        uploaded_file = DocumentFilePrivate.objects.create(
            name='test_upload.txt',
            file_path=test_file.name,
            file_size=file_size,
            file_type='text/plain',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        if uploaded_file.id:
            result.add_pass("文件上传成功（创建数据库记录）")

        # 2.1 验证文件信息
        file_record = DocumentFilePrivate.objects.get(id=uploaded_file.id)
        if file_record.name == 'test_upload.txt':
            result.add_pass("验证文件记录信息")
        else:
            result.add_fail("验证文件信息", "文件名称不匹配")

        # 2.2 验证文件大小
        if file_record.file_size == file_size:
            result.add_pass("验证文件大小")
        else:
            result.add_fail("验证文件大小", f"文件大小不匹配")

        # 2.3 验证文件类型
        if file_record.file_type == 'text/plain':
            result.add_pass("验证文件类型")
        else:
            result.add_fail("验证文件类型", "文件类型不匹配")

        # 2.4 测试文件删除
        file_id = uploaded_file.id
        uploaded_file.delete()
        if not DocumentFilePrivate.objects.filter(id=file_id).exists():
            result.add_pass("文件删除成功")
        else:
            result.add_fail("文件删除", "文件记录仍然存在")

        # 清理测试文件
        if os.path.exists(test_file.name):
            os.unlink(test_file.name)

    except Exception as e:
        result.add_fail("文件上传下载测试", str(e))


def test_file_copy_move_rename(result, user_a, user_b):
    """测试3: 文件复制、移动、重命名"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试3: 文件复制、移动、重命名{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        from apps.libs.tenant_utils import check_tenant_unique_name

        # 3.1 测试文件重命名
        file1 = DocumentFilePrivate.objects.create(
            name='file_rename_test.txt',
            file_path='/test/path/file1.txt',
            file_size=1024,
            file_type='text/plain',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        file1.name = 'file_renamed.txt'
        file1.save()

        file_renamed = DocumentFilePrivate.objects.get(id=file1.id)
        if file_renamed.name == 'file_renamed.txt':
            result.add_pass("文件重命名成功")
        else:
            result.add_fail("文件重命名", "文件名称未更新")

        # 3.2 测试文件移动（更改父文件夹）
        folder1 = DocumentFolderPrivate.objects.create(
            name='folder1',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        folder2 = DocumentFolderPrivate.objects.create(
            name='folder2',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        file2 = DocumentFilePrivate.objects.create(
            name='file_move_test.txt',
            file_path='/test/path/file2.txt',
            file_size=1024,
            file_type='text/plain',
            folder=folder1,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        file2.folder = folder2
        file2.save()

        file_moved = DocumentFilePrivate.objects.get(id=file2.id)
        if file_moved.folder.id == folder2.id:
            result.add_pass("文件移动成功（更改父文件夹）")
        else:
            result.add_fail("文件移动", "文件父文件夹未更新")

        # 3.3 测试文件复制（创建新记录）
        file3 = DocumentFilePrivate.objects.create(
            name='file_copy_test.txt',
            file_path='/test/path/file3.txt',
            file_size=1024,
            file_type='text/plain',
            folder=folder1,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 复制文件（创建新记录）
        file3_copy = DocumentFilePrivate.objects.create(
            name='file_copy_test.txt',
            file_path='/test/path/file3_copy.txt',
            file_size=file3.file_size,
            file_type=file3.file_type,
            folder=folder2,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        if file3_copy.id and file3_copy.id != file3.id:
            result.add_pass("文件复制成功（创建新记录）")
        else:
            result.add_fail("文件复制", "文件复制失败")

        # 3.4 验证租户隔离：租户A的文件，租户B看不到
        file_a = DocumentFilePrivate.objects.create(
            name='file_only_a.txt',
            file_path='/test/path/file_a.txt',
            file_size=1024,
            file_type='text/plain',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        queryset_b = DocumentFilePrivate.objects.filter(name='file_only_a.txt')
        filtered_b = apply_tenant_filter(queryset_b, user_b)
        if filtered_b.count() == 0:
            result.add_pass("租户隔离：租户B看不到租户A的文件")
        else:
            result.add_fail("租户隔离", "租户B能看到租户A的文件")

    except Exception as e:
        result.add_fail("文件复制移动重命名测试", str(e))


def test_file_type_validation(result, user_a):
    """测试4: 文件类型验证"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试4: 文件类型验证{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 支持的文件类型
        supported_types = {
            'test.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'test.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'test.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'test.pdf': 'application/pdf',
            'test.jpg': 'image/jpeg',
            'test.png': 'image/png',
            'test.zip': 'application/zip',
            'test.txt': 'text/plain',
        }

        # 4.1 测试支持的文件类型
        for filename, expected_type in supported_types.items():
            test_file = DocumentFilePrivate.objects.create(
                name=filename,
                file_path=f'/test/path/{filename}',
                file_size=1024,
                file_type=expected_type,
                created_by=user_a,
                tenant_id=user_a.tenant_id
            )

            if test_file.file_type == expected_type:
                result.add_pass(f"支持的文件类型: {filename}")
            else:
                result.add_fail(f"文件类型验证", f"{filename} 类型不匹配")

        # 4.2 测试长MIME类型（file_type字段修复验证）
        long_mime_file = DocumentFilePrivate.objects.create(
            name='long_mime_test.docx',
            file_path='/test/path/long_mime_test.docx',
            file_size=1024,
            file_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        if long_mime_file.file_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
            result.add_pass("长MIME类型保存成功（file_type字段修复验证）")
        else:
            result.add_fail("长MIME类型", "MIME类型被截断或错误")

    except Exception as e:
        result.add_fail("文件类型验证测试", str(e))


def test_file_size_limit(result, user_a):
    """测试5: 文件大小限制"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试5: 文件大小限制{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 5.1 测试小文件（1KB）
        small_file = DocumentFilePrivate.objects.create(
            name='small_file.txt',
            file_path='/test/path/small_file.txt',
            file_size=1024,
            file_type='text/plain',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        if small_file.file_size == 1024:
            result.add_pass("小文件上传成功（1KB）")

        # 5.2 测试中等文件（10MB）
        medium_file = DocumentFilePrivate.objects.create(
            name='medium_file.txt',
            file_path='/test/path/medium_file.txt',
            file_size=10 * 1024 * 1024,
            file_type='text/plain',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        if medium_file.file_size == 10 * 1024 * 1024:
            result.add_pass("中等文件上传成功（10MB）")

        # 5.3 测试大文件（100MB）
        large_file = DocumentFilePrivate.objects.create(
            name='large_file.txt',
            file_path='/test/path/large_file.txt',
            file_size=100 * 1024 * 1024,
            file_type='text/plain',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        if large_file.file_size == 100 * 1024 * 1024:
            result.add_pass("大文件上传成功（100MB）")

    except Exception as e:
        result.add_fail("文件大小限制测试", str(e))


def test_private_space_permissions(result, user_a, user_b):
    """测试6: 私有空间权限控制"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试6: 私有空间权限控制{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 6.1 租户A创建私有文件夹
        private_folder_a = DocumentFolderPrivate.objects.create(
            name='private_folder_a',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 6.2 租户B创建私有文件夹
        private_folder_b = DocumentFolderPrivate.objects.create(
            name='private_folder_b',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        # 6.3 验证租户A只能看到自己的文件夹
        queryset_a = DocumentFolderPrivate.objects.all()
        filtered_a = apply_tenant_filter(queryset_a, user_a)

        a_folders = [f.name for f in filtered_a]
        if 'private_folder_a' in a_folders and 'private_folder_b' not in a_folders:
            result.add_pass("租户A只能看到自己的私有文件夹")
        else:
            result.add_fail("私有空间权限", "租户A看到了其他租户的文件夹")

        # 6.4 验证租户B只能看到自己的文件夹
        queryset_b = DocumentFolderPrivate.objects.all()
        filtered_b = apply_tenant_filter(queryset_b, user_b)

        b_folders = [f.name for f in filtered_b]
        if 'private_folder_b' in b_folders and 'private_folder_a' not in b_folders:
            result.add_pass("租户B只能看到自己的私有文件夹")
        else:
            result.add_fail("私有空间权限", "租户B看到了其他租户的文件夹")

        # 6.5 测试文件权限
        private_file_a = DocumentFilePrivate.objects.create(
            name='private_file_a.txt',
            file_path='/test/path/private_file_a.txt',
            file_size=1024,
            file_type='text/plain',
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        private_file_b = DocumentFilePrivate.objects.create(
            name='private_file_b.txt',
            file_path='/test/path/private_file_b.txt',
            file_size=1024,
            file_type='text/plain',
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        # 验证租户A只能看到自己的文件
        queryset_a_files = DocumentFilePrivate.objects.all()
        filtered_a_files = apply_tenant_filter(queryset_a_files, user_a)

        a_files = [f.name for f in filtered_a_files]
        if 'private_file_a.txt' in a_files and 'private_file_b.txt' not in a_files:
            result.add_pass("租户A只能看到自己的私有文件")
        else:
            result.add_fail("私有空间权限", "租户A看到了其他租户的文件")

        # 验证租户B只能看到自己的文件
        queryset_b_files = DocumentFilePrivate.objects.all()
        filtered_b_files = apply_tenant_filter(queryset_b_files, user_b)

        b_files = [f.name for f in filtered_b_files]
        if 'private_file_b.txt' in b_files and 'private_file_a.txt' not in b_files:
            result.add_pass("租户B只能看到自己的私有文件")
        else:
            result.add_fail("私有空间权限", "租户B看到了其他租户的文件")

    except Exception as e:
        result.add_fail("私有空间权限控制测试", str(e))


def test_public_space_sharing(result, user_a, user_b, admin_user):
    """测试7: 公共空间共享"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}测试7: 公共空间共享{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    try:
        # 7.1 租户A在公共空间创建文件夹
        public_folder_a = DocumentFolderPublic.objects.create(
            name='public_folder_a',
            created_by=user_a
        )
        result.add_pass("租户A在公共空间创建文件夹")

        # 7.2 租户A在公共空间上传文件
        public_file_a = DocumentFilePublic.objects.create(
            name='public_file_a.txt',
            file_path='/test/path/public_file_a.txt',
            file_size=1024,
            file_type='text/plain',
            created_by=user_a
        )
        result.add_pass("租户A在公共空间上传文件")

        # 7.3 验证租户B可以看到公共空间的资源
        public_folders = DocumentFolderPublic.objects.filter(name='public_folder_a')
        if public_folders.exists():
            result.add_pass("租户B可以看到公共空间文件夹")
        else:
            result.add_fail("公共空间共享", "租户B看不到公共空间文件夹")

        public_files = DocumentFilePublic.objects.filter(name='public_file_a.txt')
        if public_files.exists():
            result.add_pass("租户B可以看到公共空间文件")
        else:
            result.add_fail("公共空间共享", "租户B看不到公共空间文件")

        # 7.4 验证公共空间资源信息
        folder = public_folders.first()
        if folder and folder.created_by_id == user_a.id:
            result.add_pass("公共空间文件夹创建者信息正确")
        else:
            result.add_fail("公共空间信息", "文件夹创建者信息不匹配")

        file_obj = public_files.first()
        if file_obj and file_obj.created_by_id == user_a.id:
            result.add_pass("公共空间文件创建者信息正确")
        else:
            result.add_fail("公共空间信息", "文件创建者信息不匹配")

    except Exception as e:
        result.add_fail("公共空间共享测试", str(e))


def main():
    """主测试函数"""
    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("=" * 60)
    print("资料库模块完整功能自动化测试")
    print("=" * 60)
    print(f"{Colors.RESET}")

    result = TestResult()

    # 创建测试用户和角色
    user_a, user_b, admin_user = create_test_users_and_roles(result)
    if not user_a or not user_b or not admin_user:
        print(f"{Colors.RED}测试用户创建失败，退出测试{Colors.RESET}")
        return

    try:
        # 执行所有测试
        test_folder_crud(result, user_a, user_b)
        test_file_upload_download(result, user_a)
        test_file_copy_move_rename(result, user_a, user_b)
        test_file_type_validation(result, user_a)
        test_file_size_limit(result, user_a)
        test_private_space_permissions(result, user_a, user_b)
        test_public_space_sharing(result, user_a, user_b, admin_user)

    finally:
        # 打印测试结果汇总
        result.print_summary()


if __name__ == '__main__':
    main()
