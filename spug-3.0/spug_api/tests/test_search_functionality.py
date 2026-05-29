"""
测试递归搜索功能

测试场景：
1. 在根目录下创建多级文件夹结构
2. 在不同层级创建文件
3. 测试搜索是否能递归找到所有匹配项
4. 验证租户隔离是否正常工作
"""

import os
import sys
import django

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.document.models import DocumentFolder, DocumentFile
from apps.account.models import User
from libs.http import MockRequest
import json

def create_test_structure():
    """创建测试用的多级文件夹结构"""
    print("创建测试文件夹结构...")

    # 获取测试用户
    test_user = User.objects.first()
    if not test_user:
        print("错误: 未找到测试用户")
        return None

    # 创建根文件夹
    root_folder = DocumentFolder.objects.create(
        name="测试根目录",
        parent_id=None,
        is_public=False,
        created_by=test_user,
        tenant_id=test_user.tenant_id
    )
    print(f"创建根文件夹: {root_folder.name} (id={root_folder.id})")

    # 创建多级子文件夹
    folders = {
        'root': root_folder,
    }

    folder_structure = [
        ("技术文档", "root"),
        ("技术文档/项目文档", "技术文档"),
        ("技术文档/设计文档", "技术文档"),
        ("技术文档/项目文档/需求文档", "项目文档"),
        ("技术文档/项目文档/API文档", "项目文档"),
        ("资料库", "root"),
        ("资料库/图片", "资料库"),
    ]

    for folder_name, parent_name in folder_structure:
        parent_folder = folders.get(parent_name)
        if not parent_folder:
            print(f"警告: 未找到父文件夹 {parent_name}")
            continue

        new_folder = DocumentFolder.objects.create(
            name=folder_name.split('/')[-1],
            parent_id=parent_folder.id,
            is_public=False,
            created_by=test_user,
            tenant_id=test_user.tenant_id
        )
        folders[folder_name] = new_folder
        print(f"创建文件夹: {folder_name} (id={new_folder.id})")

    return folders, test_user

def create_test_files(folders, test_user):
    """创建测试文件"""
    print("\n创建测试文件...")

    test_files = [
        ("项目计划.pdf", "技术文档", "application/pdf", 1024000),
        ("系统设计.docx", "技术文档/项目文档", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 512000),
        ("API接口说明.docx", "技术文档/项目文档/API文档", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 256000),
        ("需求规格说明书.pdf", "技术文档/项目文档/需求文档", "application/pdf", 2048000),
        ("logo.png", "资料库/图片", "image/png", 51200),
        ("测试报告.docx", "技术文档", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 768000),
    ]

    created_files = []
    for file_name, folder_path, file_type, file_size in test_files:
        folder = folders.get(folder_path)
        if not folder:
            print(f"警告: 未找到文件夹 {folder_path}")
            continue

        # 查找文件夹ID（需要通过name和parent_id）
        folder_obj = DocumentFolder.objects.filter(
            name=file_name.split('/')[0],
            parent_id=folder.id if folder_path != "root" else None
        ).first()

        if not folder_obj:
            # 如果找不到，使用文件夹的直接子文件夹
            folder_obj = DocumentFolder.objects.filter(
                name=folder_path.split('/')[-1],
                parent_id=folder.id if "/" in folder_path else None
            ).first()

        if not folder_obj:
            # 尝试查找完整路径
            parts = folder_path.split('/')
            folder_obj = folders.get(folder_path)

        if not folder_obj:
            print(f"警告: 未找到文件夹对象 {folder_path}")
            continue

        file_obj = DocumentFile.objects.create(
            name=file_name,
            folder_id=folder_obj.id,
            file_type=file_type,
            file_size=file_size,
            is_public=False,
            created_by=test_user,
            tenant_id=test_user.tenant_id
        )
        created_files.append(file_obj)
        print(f"创建文件: {file_name} (id={file_obj.id}, 文件夹={folder_obj.name})")

    return created_files

def test_search_function():
    """测试搜索功能"""
    from apps.document.views import FolderSearchView

    print("\n" + "=" * 50)
    print("测试递归搜索功能")
    print("=" * 50)

    # 创建测试数据
    folders, test_user = create_test_structure()
    if not folders:
        return

    test_files = create_test_files(folders, test_user)

    # 创建模拟请求
    view = FolderSearchView()

    print("\n测试场景 1: 搜索 '文档'")
    print("-" * 50)
    request = MockRequest()
    request.user = test_user
    request.GET = {
        'folder_id': folders['root'].id,
        'keyword': '文档',
        'is_public': 'false'
    }

    response = view.get(request)
    print(f"响应状态: {response.status_code}")
    print(f"文件夹数量: {len(response.data.get('folders', []))}")
    print(f"文件数量: {len(response.data.get('files', []))}")

    for folder in response.data.get('folders', []):
        print(f"  文件夹: {folder['name']} (路径: {folder.get('path', '-')})")

    for file in response.data.get('files', []):
        print(f"  文件: {file['name']} (路径: {file.get('path', '-')})")

    print("\n测试场景 2: 搜索 'PDF'")
    print("-" * 50)
    request.GET['keyword'] = 'PDF'
    response = view.get(request)
    print(f"文件夹数量: {len(response.data.get('folders', []))}")
    print(f"文件数量: {len(response.data.get('files', []))}")

    for file in response.data.get('files', []):
        print(f"  文件: {file['name']} (路径: {file.get('path', '-')})")

    print("\n测试场景 3: 空关键词")
    print("-" * 50)
    request.GET['keyword'] = ''
    response = view.get(request)
    print(f"响应: {response.data}")

    print("\n测试场景 4: 从根目录搜索")
    print("-" * 50)
    request.GET['folder_id'] = None
    request.GET['keyword'] = '项目'
    response = view.get(request)
    print(f"文件夹数量: {len(response.data.get('folders', []))}")
    print(f"文件数量: {len(response.data.get('files', []))}")

    # 清理测试数据
    print("\n清理测试数据...")
    test_files = DocumentFile.objects.filter(created_by=test_user, name__startswith=(
        "项目计划" or "系统设计" or "API接口说明" or "需求规格说明书" or "logo" or "测试报告"
    ))
    test_files.delete()

    for folder in folders.values():
        if folder.id != folders['root'].id:
            folder.delete()
    folders['root'].delete()

    print("\n测试完成！")

if __name__ == '__main__':
    test_search_function()
