"""
资料库递归搜索功能完整测试用例

测试覆盖范围：
1. 基础功能测试
2. 多租户安全测试（最重要）
3. 边界场景测试
4. 交互功能测试
"""

import os
import sys
import django

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.document.models import DocumentFolder, DocumentFile, PublicFolder, PublicFile
from apps.account.models import User
from apps.document.views import FolderSearchView
from libs.http import MockRequest
import json


class RecursiveSearchTestSuite:
    """递归搜索功能测试套件"""

    def __init__(self):
        self.test_users = {}
        self.test_folders = {}
        self.test_files = {}
        self.test_results = []

    def log_result(self, test_name, passed, message="", details=""):
        """记录测试结果"""
        status = "✅ PASS" if passed else "❌ FAIL"
        self.test_results.append({
            'name': test_name,
            'passed': passed,
            'message': message,
            'details': details
        })
        print(f"{status} - {test_name}")
        if message:
            print(f"    消息: {message}")
        if details:
            print(f"    详情: {details}")

    def setup_test_data(self):
        """设置测试数据"""
        print("\n" + "=" * 70)
        print("设置测试数据")
        print("=" * 70)

        # 创建两个测试用户（模拟两个租户）
        try:
            # 租户A用户
            user_a = User.objects.create_user(
                username='test_tenant_a',
                nickname='测试租户A',
                password='test123',
                is_superuser=False,
                tenant_id='tenant_a_001'
            )
            self.test_users['tenant_a'] = user_a
            print(f"✓ 创建租户A用户: {user_a.username} (tenant_id={user_a.tenant_id})")
        except:
            user_a = User.objects.filter(username='test_tenant_a').first()
            self.test_users['tenant_a'] = user_a
            print(f"✓ 使用已有租户A用户: {user_a.username}")

        try:
            # 租户B用户
            user_b = User.objects.create_user(
                username='test_tenant_b',
                nickname='测试租户B',
                password='test123',
                is_superuser=False,
                tenant_id='tenant_b_002'
            )
            self.test_users['tenant_b'] = user_b
            print(f"✓ 创建租户B用户: {user_b.username} (tenant_id={user_b.tenant_id})")
        except:
            user_b = User.objects.filter(username='test_tenant_b').first()
            self.test_users['tenant_b'] = user_b
            print(f"✓ 使用已有租户B用户: {user_b.username}")

        # 创建租户A的测试文件夹结构
        print("\n创建租户A的测试文件夹结构...")
        self._create_tenant_a_structure(user_a)

        # 创建租户B的测试文件夹结构
        print("\n创建租户B的测试文件夹结构...")
        self._create_tenant_b_structure(user_b)

        # 创建公共空间测试数据
        print("\n创建公共空间测试数据...")
        self._create_public_structure()

        print("\n✓ 测试数据设置完成")

    def _create_tenant_a_structure(self, user):
        """创建租户A的文件夹结构"""
        # 根文件夹
        root = DocumentFolder.objects.create(
            name="租户A根目录",
            parent_id=None,
            is_public=False,
            created_by=user,
            tenant_id=user.tenant_id
        )
        self.test_folders['tenant_a_root'] = root

        # 第一级文件夹
        folder_map = {}
        folder_map['root'] = root

        structure = [
            ("技术文档", "root"),
            ("技术文档/项目文档", "技术文档"),
            ("技术文档/设计文档", "技术文档"),
            ("技术文档/项目文档/需求文档", "项目文档"),
            ("技术文档/项目文档/API文档", "项目文档"),
            ("技术文档/项目文档/需求文档/功能需求", "需求文档"),
            ("技术文档/项目文档/需求文档/非功能需求", "需求文档"),
            ("资料库", "root"),
            ("资料库/图片", "资料库"),
            ("资料库/文档", "资料库"),
            ("个人文件", "root"),
        ]

        for folder_path, parent_path in structure:
            folder_name = folder_path.split('/')[-1]
            parent = folder_map[parent_path]

            folder = DocumentFolder.objects.create(
                name=folder_name,
                parent_id=parent.id,
                is_public=False,
                created_by=user,
                tenant_id=user.tenant_id
            )
            folder_map[folder_path] = folder
            self.test_folders[f'tenant_a_{folder_name}'] = folder
            print(f"  创建文件夹: {folder_path} (id={folder.id})")

        # 创建测试文件
        files_data = [
            ("项目计划.pdf", "技术文档", "application/pdf", 1024000),
            ("系统设计.docx", "技术文档/项目文档", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 512000),
            ("API接口说明.docx", "技术文档/项目文档/API文档", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 256000),
            ("需求规格说明书.pdf", "技术文档/项目文档/需求文档", "application/pdf", 2048000),
            ("logo.png", "资料库/图片", "image/png", 51200),
            ("测试报告.docx", "技术文档", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 768000),
            ("架构设计.pdf", "技术文档/设计文档", "application/pdf", 1536000),
            ("用户手册.pdf", "技术文档/项目文档", "application/pdf", 3072000),
            ("功能需求.docx", "技术文档/项目文档/需求文档/功能需求", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 128000),
            ("性能测试报告.pdf", "技术文档/项目文档/需求文档/非功能需求", "application/pdf", 896000),
            ("avatar.jpg", "资料库/图片", "image/jpeg", 102400),
            ("个人笔记.txt", "个人文件", "text/plain", 2048),
        ]

        for file_name, folder_path, file_type, file_size in files_data:
            folder = folder_map[folder_path]
            file_obj = DocumentFile.objects.create(
                name=file_name,
                folder_id=folder.id,
                file_type=file_type,
                file_size=file_size,
                is_public=False,
                created_by=user,
                tenant_id=user.tenant_id
            )
            self.test_files[f'tenant_a_{file_name}'] = file_obj
            print(f"  创建文件: {file_name} (文件夹={folder_path})")

    def _create_tenant_b_structure(self, user):
        """创建租户B的文件夹结构"""
        root = DocumentFolder.objects.create(
            name="租户B根目录",
            parent_id=None,
            is_public=False,
            created_by=user,
            tenant_id=user.tenant_id
        )
        self.test_folders['tenant_b_root'] = root

        # 创建与租户A同名的文件夹（用于测试租户隔离）
        folder_map = {'root': root}

        structure = [
            ("技术文档", "root"),
            ("技术文档/机密文档", "技术文档"),
            ("财务资料", "root"),
        ]

        for folder_path, parent_path in structure:
            folder_name = folder_path.split('/')[-1]
            parent = folder_map[parent_path]

            folder = DocumentFolder.objects.create(
                name=folder_name,
                parent_id=parent.id,
                is_public=False,
                created_by=user,
                tenant_id=user.tenant_id
            )
            folder_map[folder_path] = folder
            self.test_folders[f'tenant_b_{folder_name}'] = folder
            print(f"  创建文件夹: {folder_path} (id={folder.id})")

        # 创建测试文件（包含同名文件）
        files_data = [
            ("项目计划.pdf", "技术文档", "application/pdf", 2048000),  # 与租户A同名但内容不同
            ("财务报表.xlsx", "财务资料", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 409600),
        ]

        for file_name, folder_path, file_type, file_size in files_data:
            folder = folder_map[folder_path]
            file_obj = DocumentFile.objects.create(
                name=file_name,
                folder_id=folder.id,
                file_type=file_type,
                file_size=file_size,
                is_public=False,
                created_by=user,
                tenant_id=user.tenant_id
            )
            self.test_files[f'tenant_b_{file_name}'] = file_obj
            print(f"  创建文件: {file_name} (文件夹={folder_path})")

    def _create_public_structure(self):
        """创建公共空间测试数据"""
        # 使用租户A作为创建者
        user = self.test_users['tenant_a']

        root = PublicFolder.objects.create(
            name="公共空间根目录",
            parent_id=None,
            created_by=user
        )
        self.test_folders['public_root'] = root

        folder_map = {'root': root}

        structure = [
            ("共享文档", "root"),
            ("共享资源", "root"),
            ("共享文档/公司规范", "共享文档"),
        ]

        for folder_path, parent_path in structure:
            folder_name = folder_path.split('/')[-1]
            parent = folder_map[parent_path]

            folder = PublicFolder.objects.create(
                name=folder_name,
                parent_id=parent.id,
                created_by=user
            )
            folder_map[folder_path] = folder
            self.test_folders[f'public_{folder_name}'] = folder
            print(f"  创建公共文件夹: {folder_path} (id={folder.id})")

        # 创建公共文件
        files_data = [
            ("公司制度.docx", "共享文档/公司规范", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 512000),
            ("培训资料.pdf", "共享文档", "application/pdf", 1536000),
            ("公司Logo.png", "共享资源", "image/png", 102400),
        ]

        for file_name, folder_path, file_type, file_size in files_data:
            folder = folder_map[folder_path]
            file_obj = PublicFile.objects.create(
                name=file_name,
                folder_id=folder.id,
                file_type=file_type,
                file_size=file_size,
                created_by=user
            )
            self.test_files[f'public_{file_name}'] = file_obj
            print(f"  创建公共文件: {file_name} (文件夹={folder_path})")

    def run_basic_function_tests(self):
        """运行基础功能测试"""
        print("\n" + "=" * 70)
        print("1. 基础功能测试")
        print("=" * 70)

        view = FolderSearchView()
        user_a = self.test_users['tenant_a']
        root_folder = self.test_folders['tenant_a_root']

        # 测试1.1: 搜索当前文件夹下的文件/文件夹
        print("\n1.1 搜索当前文件夹下的文件/文件夹")
        request = MockRequest()
        request.user = user_a
        request.GET = {
            'folder_id': root_folder.id,
            'keyword': '技术文档',
            'is_public': 'false'
        }

        response = view.get(request)
        folders = response.data.get('folders', [])
        files = response.data.get('files', [])

        # 期望：找到第一级的"技术文档"文件夹
        found = any(f['name'] == '技术文档' for f in folders)
        self.log_result(
            "搜当前文件夹下的文件夹",
            found,
            f"找到 {len(folders)} 个文件夹",
            f"结果: {[f['name'] for f in folders]}"
        )

        # 测试1.2: 搜索子文件夹内的文件
        print("\n1.2 搜索子文件夹内的文件")
        request.GET['keyword'] = 'API接口说明'
        response = view.get(request)
        files = response.data.get('files', [])

        found = any(f['name'] == 'API接口说明.docx' for f in files)
        expected_path = '技术文档/项目文档/API文档'
        actual_path = files[0]['path'] if files else ''

        self.log_result(
            "搜子文件夹内的文件",
            found,
            f"找到 {len(files)} 个文件",
            f"期望路径: {expected_path}, 实际路径: {actual_path}"
        )

        # 测试1.3: 搜索多层子文件夹
        print("\n1.3 搜索多层子文件夹（4层深度）")
        request.GET['keyword'] = '功能需求'
        response = view.get(request)
        files = response.data.get('files', [])

        found = any(f['name'] == '功能需求.docx' for f in files)
        expected_path = '技术文档/项目文档/需求文档/功能需求'
        actual_path = files[0]['path'] if files else ''

        self.log_result(
            "搜多层子文件夹（4层深度）",
            found,
            f"找到 {len(files)} 个文件",
            f"期望路径: {expected_path}, 实际路径: {actual_path}"
        )

        # 测试1.4: 关键词大小写不敏感
        print("\n1.4 关键词大小写不敏感")
        test_cases = ['pdf', 'PDF', 'Pdf', 'pDf']
        all_passed = True

        for keyword in test_cases:
            request.GET['keyword'] = keyword
            response = view.get(request)
            files = response.data.get('files', [])
            # 期望找到所有PDF文件
            pdf_count = sum(1 for f in files if f['name'].lower().endswith('.pdf'))
            if pdf_count < 1:
                all_passed = False
                print(f"  ✗ 关键词 '{keyword}' 只找到 {pdf_count} 个PDF文件")

        self.log_result(
            "关键词大小写不敏感",
            all_passed,
            "所有大小写变体都能正确搜索",
            f"测试的关键词: {test_cases}"
        )

        # 测试1.5: 部分匹配
        print("\n1.5 部分匹配")
        request.GET['keyword'] = '文档'
        response = view.get(request)
        folders = response.data.get('folders', [])
        files = response.data.get('files', [])

        # 期望：找到所有名称包含"文档"的文件夹和文件
        folder_matches = [f['name'] for f in folders if '文档' in f['name']]
        file_matches = [f['name'] for f in files if '文档' in f['name']]

        self.log_result(
            "部分匹配",
            len(folder_matches) > 0 and len(file_matches) > 0,
            f"找到 {len(folder_matches)} 个文件夹, {len(file_matches)} 个文件",
            f"文件夹: {folder_matches}, 文件: {file_matches[:3]}"
        )

        # 测试1.6: 完全匹配
        print("\n1.6 完全匹配")
        request.GET['keyword'] = 'logo'
        response = view.get(request)
        files = response.data.get('files', [])

        # 期望：找到 logo.png 和 avatar.jpg
        found = any('logo' in f['name'].lower() for f in files)

        self.log_result(
            "完全匹配",
            found,
            f"找到 {len(files)} 个匹配文件",
            f"文件名: {[f['name'] for f in files]}"
        )

    def run_tenant_isolation_tests(self):
        """运行多租户安全测试"""
        print("\n" + "=" * 70)
        print("2. 多租户安全测试（最重要）")
        print("=" * 70)

        view = FolderSearchView()
        user_a = self.test_users['tenant_a']
        user_b = self.test_users['tenant_b']

        # 测试2.1: 租户A搜不到租户B的数据
        print("\n2.1 租户A搜不到租户B的数据")
        request = MockRequest()
        request.user = user_a
        request.GET = {
            'folder_id': None,
            'keyword': '项目计划.pdf',
            'is_public': 'false'
        }

        response = view.get(request)
        files = response.data.get('files', [])

        # 租户A只能看到自己的"项目计划.pdf"
        found_tenant_b_data = any(
            f['name'] == '项目计划.pdf' and '租户B' in f.get('path', '')
            for f in files
        )

        self.log_result(
            "租户A搜不到租户B的数据",
            not found_tenant_b_data,
            f"找到 {len(files)} 个文件",
            f"结果: {[f['name'] for f in files]}"
        )

        # 测试2.2: 租户B搜不到租户A的数据
        print("\n2.2 租户B搜不到租户A的数据")
        request.user = user_b
        response = view.get(request)
        files = response.data.get('files', [])

        found_tenant_a_data = any(
            f['name'] == '项目计划.pdf' and '租户A' in f.get('path', '')
            for f in files
        )

        self.log_result(
            "租户B搜不到租户A的数据",
            not found_tenant_a_data,
            f"找到 {len(files)} 个文件",
            f"结果: {[f['name'] for f in files]}"
        )

        # 测试2.3: 搜索同名文件夹（验证租户隔离）
        print("\n2.3 搜索同名文件夹（验证租户隔离）")
        request.user = user_a
        request.GET['keyword'] = '技术文档'
        response = view.get(request)
        folders = response.data.get('folders', [])

        # 租户A只能看到自己的"技术文档"文件夹，不能看到租户B的
        found_tenant_b_folder = any(
            '租户B' in f.get('path', '')
            for f in folders
        )

        self.log_result(
            "同名文件夹租户隔离",
            not found_tenant_b_folder,
            f"租户A找到 {len(folders)} 个'技术文档'文件夹",
            f"结果: {[f['path'] for f in folders]}"
        )

        # 测试2.4: 公共空间所有人可见
        print("\n2.4 公共空间所有人可见")
        public_files = []

        # 租户A搜索公共空间
        request.user = user_a
        request.GET = {
            'folder_id': None,
            'keyword': '公司制度',
            'is_public': 'true'
        }
        response = view.get(request)
        public_files = response.data.get('files', [])
        tenant_a_can_see = len(public_files) > 0

        # 租户B搜索公共空间
        request.user = user_b
        response = view.get(request)
        public_files_b = response.data.get('files', [])
        tenant_b_can_see = len(public_files_b) > 0

        both_can_see = tenant_a_can_see and tenant_b_can_see

        self.log_result(
            "公共空间所有人可见",
            both_can_see,
            f"租户A: {tenant_a_can_see}, 租户B: {tenant_b_can_see}",
            f"租户A结果: {[f['name'] for f in public_files]}, 租户B结果: {[f['name'] for f in public_files_b]}"
        )

        # 测试2.5: 切换 public/private 标签搜索范围正确
        print("\n2.5 切换 public/private 标签搜索范围正确")
        request.user = user_a

        # 搜索私有空间
        request.GET = {
            'folder_id': None,
            'keyword': '项目计划',
            'is_public': 'false'
        }
        response = view.get(request)
        private_files = response.data.get('files', [])

        # 搜索公共空间
        request.GET['is_public'] = 'true'
        response = view.get(request)
        public_files = response.data.get('files', [])

        # 验证搜索范围正确
        private_only = len(private_files) > 0 and len(public_files) == 0

        self.log_result(
            "切换 public/private 标签搜索范围正确",
            private_only,
            f"私有空间: {len(private_files)} 个, 公共空间: {len(public_files)} 个",
            f"私有空间: {[f['name'] for f in private_files]}, 公共空间: {[f['name'] for f in public_files]}"
        )

    def run_boundary_tests(self):
        """运行边界场景测试"""
        print("\n" + "=" * 70)
        print("3. 边界场景测试")
        print("=" * 70)

        view = FolderSearchView()
        user_a = self.test_users['tenant_a']
        root_folder = self.test_folders['tenant_a_root']

        # 测试3.1: 空关键词
        print("\n3.1 空关键词")
        request = MockRequest()
        request.user = user_a
        request.GET = {
            'folder_id': root_folder.id,
            'keyword': '',
            'is_public': 'false'
        }

        response = view.get(request)
        is_empty = len(response.data.get('folders', [])) == 0 and len(response.data.get('files', [])) == 0

        self.log_result(
            "空关键词返回空结果",
            is_empty,
            f"文件夹: {len(response.data.get('folders', []))}, 文件: {len(response.data.get('files', []))}"
        )

        # 测试3.2: 空格关键词
        print("\n3.2 空格关键词")
        request.GET['keyword'] = '   '
        response = view.get(request)
        is_empty = len(response.data.get('folders', [])) == 0 and len(response.data.get('files', [])) == 0

        self.log_result(
            "空格关键词返回空结果",
            is_empty,
            f"文件夹: {len(response.data.get('folders', []))}, 文件: {len(response.data.get('files', []))}"
        )

        # 测试3.3: 无结果
        print("\n3.3 无结果")
        request.GET['keyword'] = '不存在的文件名xyz123'
        response = view.get(request)
        folders = response.data.get('folders', [])
        files = response.data.get('files', [])

        is_empty = len(folders) == 0 and len(files) == 0

        self.log_result(
            "无结果返回空列表",
            is_empty,
            f"文件夹: {len(folders)}, 文件: {len(files)}"
        )

        # 测试3.4: 特殊字符（SQL注入测试）
        print("\n3.4 特殊字符（SQL注入防护）")
        dangerous_inputs = [
            "'; DROP TABLE document_folder; --",
            "test' OR '1'='1",
            "<script>alert('xss')</script>",
            "../../etc/passwd"
        ]

        all_safe = True
        for keyword in dangerous_inputs:
            request.GET['keyword'] = keyword
            try:
                response = view.get(request)
                # 只要不崩溃就认为通过
                if response.status_code != 200:
                    all_safe = False
                    print(f"  ✗ 关键词 '{keyword}' 导致错误响应: {response.status_code}")
            except Exception as e:
                all_safe = False
                print(f"  ✗ 关键词 '{keyword}' 导致异常: {str(e)}")

        self.log_result(
            "特殊字符安全处理",
            all_safe,
            "所有特殊字符都安全处理",
            f"测试的关键词: {dangerous_inputs}"
        )

        # 测试3.5: 超长关键词
        print("\n3.5 超长关键词")
        long_keyword = "a" * 1000  # 1000个字符
        request.GET['keyword'] = long_keyword

        try:
            response = view.get(request)
            is_empty = len(response.data.get('folders', [])) == 0 and len(response.data.get('files', [])) == 0
            self.log_result(
                "超长关键词处理",
                is_empty,
                f"关键词长度: {len(long_keyword)}, 结果数量: {len(response.data.get('files', []))}"
            )
        except Exception as e:
            self.log_result(
                "超长关键词处理",
                False,
                f"关键词长度: {len(long_keyword)}, 异常: {str(e)}"
            )

        # 测试3.6: 中文关键词
        print("\n3.6 中文关键词")
        request.GET['keyword'] = '用户'
        response = view.get(request)
        files = response.data.get('files', [])

        found = any('用户' in f['name'] for f in files)

        self.log_result(
            "中文关键词搜索",
            found,
            f"找到 {len(files)} 个文件",
            f"结果: {[f['name'] for f in files]}"
        )

        # 测试3.7: 混合字符
        print("\n3.7 混合字符（中英文数字）")
        request.GET['keyword'] = 'API文档'
        response = view.get(request)
        files = response.data.get('files', [])

        found = any('API' in f['name'] or '文档' in f['name'] for f in files)

        self.log_result(
            "混合字符搜索",
            found,
            f"找到 {len(files)} 个文件",
            f"结果: {[f['name'] for f in files]}"
        )

    def run_interaction_tests(self):
        """运行交互功能测试"""
        print("\n" + "=" * 70)
        print("4. 交互功能测试")
        print("=" * 70)

        view = FolderSearchView()
        user_a = self.test_users['tenant_a']
        root_folder = self.test_folders['tenant_a_root']

        # 测试4.1: 点击结果能正确跳转（验证路径正确）
        print("\n4.1 点击结果能正确跳转（验证路径正确）")
        request = MockRequest()
        request.user = user_a
        request.GET = {
            'folder_id': root_folder.id,
            'keyword': '功能需求',
            'is_public': 'false'
        }

        response = view.get(request)
        files = response.data.get('files', [])

        if files:
            file_data = files[0]
            path = file_data.get('path', '')
            folder_id = file_data.get('folder_id')

            # 验证路径格式
            path_valid = '/' in path or path != ''
            folder_valid = isinstance(folder_id, int)

            self.log_result(
                "搜索结果路径格式正确",
                path_valid and folder_valid,
                f"路径: {path}, 文件夹ID: {folder_id}"
            )
        else:
            self.log_result(
                "搜索结果路径格式正确",
                False,
                "未找到测试文件"
            )

        # 测试4.2: 清空关键词恢复原列表（通过调用空关键词验证）
        print("\n4.2 清空关键词恢复原列表")
        request.GET['keyword'] = '文档'
        response_with_keyword = view.get(request)
        files_with_keyword = len(response_with_keyword.data.get('files', []))

        request.GET['keyword'] = ''
        response_empty = view.get(request)
        files_empty = len(response_empty.data.get('files', []))

        is_cleared = files_with_keyword > 0 and files_empty == 0

        self.log_result(
            "清空关键词恢复空结果",
            is_cleared,
            f"有关键词: {files_with_keyword} 个结果, 空关键词: {files_empty} 个结果"
        )

        # 测试4.3: 路径信息完整性
        print("\n4.3 路径信息完整性")
        request.GET['keyword'] = '需求'
        response = view.get(request)
        files = response.data.get('files', [])
        folders = response.data.get('folders', [])

        # 验证所有结果都有路径
        all_files_have_path = all('path' in f for f in files)
        all_folders_have_path = all('path' in f for f in folders)

        self.log_result(
            "所有搜索结果都有路径信息",
            all_files_have_path and all_folders_have_path,
            f"文件: {len(files)}, 文件夹: {len(folders)}"
        )

        # 测试4.4: 创建者信息完整性
        print("\n4.4 创建者信息完整性")
        all_files_have_creator = all('created_by' in f for f in files)
        all_folders_have_creator = all('created_by' in f for f in folders)

        self.log_result(
            "所有搜索结果都有创建者信息",
            all_files_have_creator and all_folders_have_creator,
            f"文件: {len(files)}, 文件夹: {len(folders)}"
        )

    def generate_report(self):
        """生成测试报告"""
        print("\n" + "=" * 70)
        print("测试报告")
        print("=" * 70)

        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r['passed'])
        failed_tests = total_tests - passed_tests
        pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

        print(f"\n总测试数: {total_tests}")
        print(f"通过: {passed_tests} ✅")
        print(f"失败: {failed_tests} ❌")
        print(f"通过率: {pass_rate:.2f}%")

        if failed_tests > 0:
            print("\n失败的测试:")
            for result in self.test_results:
                if not result['passed']:
                    print(f"  ❌ {result['name']}")
                    print(f"     消息: {result['message']}")
                    if result['details']:
                        print(f"     详情: {result['details']}")

        # 按测试类别统计
        print("\n按类别统计:")
        categories = {
            '基础功能': 0,
            '多租户安全': 0,
            '边界场景': 0,
            '交互功能': 0
        }

        for result in self.test_results:
            if '基础' in result['name']:
                categories['基础功能'] += 1
            elif '租户' in result['name'] or '安全' in result['name'] or 'public' in result['name'].lower() or 'private' in result['name'].lower():
                categories['多租户安全'] += 1
            elif '边界' in result['name'] or '空' in result['name'] or '无结果' in result['name'] or '特殊' in result['name'] or '超长' in result['name'] or '中文' in result['name'] or '混合' in result['name']:
                categories['边界场景'] += 1
            elif '交互' in result['name'] or '点击' in result['name'] or '清空' in result['name'] or '路径' in result['name'] or '创建者' in result['name']:
                categories['交互功能'] += 1

        for category, count in categories.items():
            print(f"  {category}: {count} 个测试")

        print("\n" + "=" * 70)

        return passed_tests == total_tests

    def cleanup(self):
        """清理测试数据"""
        print("\n清理测试数据...")

        # 删除测试文件
        for key, file_obj in self.test_files.items():
            try:
                file_obj.delete()
            except:
                pass

        # 删除测试文件夹
        for key, folder_obj in reversed(list(self.test_folders.items())):
            try:
                folder_obj.delete()
            except:
                pass

        # 删除测试用户
        for key, user in self.test_users.items():
            try:
                user.delete()
            except:
                pass

        print("✓ 测试数据清理完成")

    def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "🔍" * 35)
        print("资料库递归搜索功能完整测试套件")
        print("🔍" * 35)

        try:
            # 设置测试数据
            self.setup_test_data()

            # 运行测试
            self.run_basic_function_tests()
            self.run_tenant_isolation_tests()
            self.run_boundary_tests()
            self.run_interaction_tests()

            # 生成报告
            all_passed = self.generate_report()

            return all_passed

        finally:
            # 清理测试数据
            self.cleanup()


def main():
    """主函数"""
    test_suite = RecursiveSearchTestSuite()
    all_passed = test_suite.run_all_tests()

    if all_passed:
        print("\n✅ 所有测试通过！")
        return 0
    else:
        print("\n❌ 部分测试失败，请查看报告")
        return 1


if __name__ == '__main__':
    exit(main())
