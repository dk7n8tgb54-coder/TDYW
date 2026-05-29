#!/usr/bin/env python3
"""
递归搜索功能快速测试脚本

使用方法：
    python test_recursive_search_simple.py
"""

import os
import sys
import django

# 设置 Django 环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User
from apps.document.models import DocumentFolderPrivate, DocumentFilePrivate, DocumentFolderPublic, DocumentFilePublic
from apps.document.views import FolderSearchView
from libs.http import MockRequest


class Colors:
    """终端颜色"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_header(text):
    """打印标题"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")


def print_test(name, passed, message=""):
    """打印测试结果"""
    status = f"{Colors.GREEN}✅ PASS{Colors.RESET}" if passed else f"{Colors.RED}❌ FAIL{Colors.RESET}"
    print(f"{status} - {name}")
    if message:
        print(f"    {Colors.YELLOW}→ {message}{Colors.RESET}")


def main():
    """主测试函数"""
    print_header("资料库递归搜索功能测试")

    try:
        # 创建测试用户
        print(f"\n{Colors.YELLOW}准备测试数据...{Colors.RESET}")

        try:
            user_a = User.objects.get(username='test_tenant_a')
        except User.DoesNotExist:
            user_a = User.objects.create_user(
                username='test_tenant_a',
                nickname='测试租户A',
                password='test123',
                tenant_id='tenant_a_001'
            )
            print(f"  创建测试用户A: {user_a.username}")

        try:
            user_b = User.objects.get(username='test_tenant_b')
        except User.DoesNotExist:
            user_b = User.objects.create_user(
                username='test_tenant_b',
                nickname='测试租户B',
                password='test123',
                tenant_id='tenant_b_002'
            )
            print(f"  创建测试用户B: {user_b.username}")

        # 创建租户A的测试数据
        print(f"\n{Colors.YELLOW}创建测试文件夹和文件...{Colors.RESET}")

        # 租户A的根文件夹
        root_a = DocumentFolderPrivate.objects.create(
            name="租户A测试根",
            parent_id=None,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 创建子文件夹
        folder1 = DocumentFolderPrivate.objects.create(
            name="技术文档",
            parent_id=root_a.id,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        folder2 = DocumentFolderPrivate.objects.create(
            name="项目文档",
            parent_id=folder1.id,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 创建测试文件
        file1 = DocumentFilePrivate.objects.create(
            name="项目计划.pdf",
            folder_id=folder1.id,
            file_type="application/pdf",
            file_size=1024000,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        file2 = DocumentFilePrivate.objects.create(
            name="需求规格说明书.pdf",
            folder_id=folder2.id,
            file_type="application/pdf",
            file_size=2048000,
            created_by=user_a,
            tenant_id=user_a.tenant_id
        )

        # 租户B的测试数据（同名文件夹和文件）
        root_b = DocumentFolderPrivate.objects.create(
            name="租户B测试根",
            parent_id=None,
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        folder_b1 = DocumentFolderPrivate.objects.create(
            name="技术文档",  # 与租户A同名
            parent_id=root_b.id,
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        file_b1 = DocumentFilePrivate.objects.create(
            name="项目计划.pdf",  # 与租户A同名
            folder_id=folder_b1.id,
            file_type="application/pdf",
            file_size=3072000,
            created_by=user_b,
            tenant_id=user_b.tenant_id
        )

        print(f"  ✓ 租户A: {root_a.name} (id={root_a.id})")
        print(f"  ✓ 租户B: {root_b.name} (id={root_b.id})")

        # 开始测试
        print_header("开始执行测试")

        view = FolderSearchView()
        test_count = 0
        pass_count = 0

        # 测试1: 租户A搜索
        test_count += 1
        print(f"\n{Colors.BOLD}测试1: 租户A递归搜索{Colors.RESET}")
        request = MockRequest()
        request.user = user_a
        request.GET = {
            'folder_id': root_a.id,
            'keyword': '项目计划',
            'is_public': 'false'
        }

        response = view.get(request)
        files = response.data.get('files', [])
        found_a = len(files) > 0

        print_test(
            "租户A能搜索到自己的文件",
            found_a,
            f"找到 {len(files)} 个文件: {[f['name'] for f in files]}"
        )
        if found_a:
            pass_count += 1

        # 测试2: 租户B搜索
        test_count += 1
        print(f"\n{Colors.BOLD}测试2: 租户B递归搜索{Colors.RESET}")
        request.user = user_b
        request.GET['folder_id'] = root_b.id

        response = view.get(request)
        files = response.data.get('files', [])
        found_b = len(files) > 0

        print_test(
            "租户B能搜索到自己的文件",
            found_b,
            f"找到 {len(files)} 个文件: {[f['name'] for f in files]}"
        )
        if found_b:
            pass_count += 1

        # 测试3: 租户A搜不到租户B的数据（核心安全测试）
        test_count += 1
        print(f"\n{Colors.BOLD}测试3: 租户隔离安全验证{Colors.RESET}")
        request.user = user_a
        request.GET['folder_id'] = None  # 从根目录搜索所有
        request.GET['keyword'] = '项目计划'

        response = view.get(request)
        files = response.data.get('files', [])

        # 验证只找到租户A的数据
        file_sizes = [f['size'] for f in files]
        tenant_b_size_found = '3.00 MB' in file_sizes  # 租户B的文件大小

        print_test(
            "租户A搜不到租户B的数据",
            not tenant_b_size_found,
            f"找到 {len(files)} 个文件，大小: {file_sizes}"
        )
        if not tenant_b_size_found:
            pass_count += 1

        # 测试4: 深层文件夹搜索
        test_count += 1
        print(f"\n{Colors.BOLD}测试4: 深层文件夹递归搜索{Colors.RESET}")
        request.user = user_a
        request.GET['folder_id'] = root_a.id
        request.GET['keyword'] = '需求'

        response = view.get(request)
        files = response.data.get('files', [])
        found_deep = any('需求' in f['name'] for f in files)

        print_test(
            "能搜索到深层文件夹内的文件",
            found_deep,
            f"找到 {len(files)} 个文件: {[f.get('path', '') for f in files]}"
        )
        if found_deep:
            pass_count += 1

        # 测试5: 空关键词
        test_count += 1
        print(f"\n{Colors.BOLD}测试5: 空关键词处理{Colors.RESET}")
        request.GET['keyword'] = ''

        response = view.get(request)
        folders = response.data.get('folders', [])
        files = response.data.get('files', [])

        is_empty = len(folders) == 0 and len(files) == 0

        print_test(
            "空关键词返回空结果",
            is_empty,
            f"文件夹: {len(folders)}, 文件: {len(files)}"
        )
        if is_empty:
            pass_count += 1

        # 测试6: 大小写不敏感
        test_count += 1
        print(f"\n{Colors.BOLD}测试6: 大小写不敏感{Colors.RESET}")
        test_keywords = ['pdf', 'PDF', 'Pdf']
        all_passed = True

        for keyword in test_keywords:
            request.GET['keyword'] = keyword
            response = view.get(request)
            files = response.data.get('files', [])
            if len(files) == 0:
                all_passed = False
                break

        print_test(
            "关键词大小写不敏感",
            all_passed,
            f"测试关键词: {test_keywords}"
        )
        if all_passed:
            pass_count += 1

        # 测试7: 路径信息
        test_count += 1
        print(f"\n{Colors.BOLD}测试7: 路径信息完整性{Colors.RESET}")
        request.GET['keyword'] = '项目'

        response = view.get(request)
        files = response.data.get('files', [])
        all_have_path = all('path' in f for f in files)

        print_test(
            "所有结果包含路径信息",
            all_have_path,
            f"检查了 {len(files)} 个文件"
        )
        if all_have_path:
            pass_count += 1

        # 打印总结
        print_header("测试总结")
        pass_rate = (pass_count / test_count * 100) if test_count > 0 else 0

        print(f"\n{Colors.BOLD}总测试数: {test_count}{Colors.RESET}")
        print(f"{Colors.GREEN}通过: {pass_count}{Colors.RESET}")
        print(f"{Colors.RED}失败: {test_count - pass_count}{Colors.RESET}")
        print(f"{Colors.BOLD}通过率: {pass_rate:.1f}%{Colors.RESET}")

        if pass_count == test_count:
            print(f"\n{Colors.GREEN}{Colors.BOLD}✅ 所有测试通过！{Colors.RESET}")
            return 0
        else:
            print(f"\n{Colors.RED}{Colors.BOLD}❌ 部分测试失败{Colors.RESET}")
            return 1

    except Exception as e:
        print(f"\n{Colors.RED}测试执行出错: {str(e)}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # 清理测试数据
        print(f"\n{Colors.YELLOW}清理测试数据...{Colors.RESET}")

        try:
            # 删除文件
            DocumentFilePrivate.objects.filter(name__in=[
                "项目计划.pdf", "需求规格说明书.pdf"
            ], created_by__in=[user_a, user_b]).delete()

            # 删除文件夹
            DocumentFolderPrivate.objects.filter(name__in=[
                "租户A测试根", "租户B测试根", "技术文档", "项目文档"
            ], created_by__in=[user_a, user_b]).delete()

            # 删除测试用户
            User.objects.filter(username__in=['test_tenant_a', 'test_tenant_b']).delete()

            print(f"{Colors.GREEN}✓ 测试数据清理完成{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}清理失败: {str(e)}{Colors.RESET}")


if __name__ == '__main__':
    sys.exit(main())
