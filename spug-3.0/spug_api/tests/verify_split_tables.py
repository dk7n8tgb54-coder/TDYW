# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
快速验证脚本 - 验证分表改造是否成功
"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate,
    DocumentFolderPublic, DocumentFilePublic,
    DocumentFolder, DocumentFile
)
from apps.document.views import get_folder_model, get_file_model
from apps.document.libs.document_utils import (
    get_document_absolute_path,
    get_document_relative_path,
    is_safe_path
)

def print_section(title):
    """打印章节标题"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)

def test_models():
    """测试模型是否正确导入"""
    print_section("1. 模型导入测试")

    try:
        print(f"✓ DocumentFolderPrivate: {DocumentFolderPrivate}")
        print(f"✓ DocumentFilePrivate: {DocumentFilePrivate}")
        print(f"✓ DocumentFolderPublic: {DocumentFolderPublic}")
        print(f"✓ DocumentFilePublic: {DocumentFilePublic}")
        print(f"✓ DocumentFolder (别名): {DocumentFolder}")
        print(f"✓ DocumentFile (别名): {DocumentFile}")
        return True
    except Exception as e:
        print(f"✗ 模型导入失败: {e}")
        return False

def test_model_fields():
    """测试模型字段是否正确"""
    print_section("2. 模型字段测试")

    try:
        # 检查DocumentFolderPrivate字段
        folder_private_fields = [f.name for f in DocumentFolderPrivate._meta.get_fields()]
        required_folder_fields = ['name', 'parent', 'created_by', 'created_at', 'updated_at']
        for field in required_folder_fields:
            if field in folder_private_fields:
                print(f"✓ DocumentFolderPrivate.{field}")
            else:
                print(f"✗ DocumentFolderPrivate.{field} 缺失")
                return False

        # 检查DocumentFilePrivate字段
        file_private_fields = [f.name for f in DocumentFilePrivate._meta.get_fields()]
        required_file_fields = ['name', 'folder', 'file_path', 'file_size', 'file_type', 'created_by', 'created_at']
        for field in required_file_fields:
            if field in file_private_fields:
                print(f"✓ DocumentFilePrivate.{field}")
            else:
                print(f"✗ DocumentFilePrivate.{field} 缺失")
                return False

        return True
    except Exception as e:
        print(f"✗ 模型字段检查失败: {e}")
        return False

def test_util_functions():
    """测试工具函数"""
    print_section("3. 工具函数测试")

    try:
        # 测试get_folder_model
        folder_model_private = get_folder_model(is_public=False)
        folder_model_public = get_folder_model(is_public=True)
        assert folder_model_private == DocumentFolderPrivate, "get_folder_model(False)失败"
        assert folder_model_public == DocumentFolderPublic, "get_folder_model(True)失败"
        print("✓ get_folder_model()")

        # 测试get_file_model
        file_model_private = get_file_model(is_public=False)
        file_model_public = get_file_model(is_public=True)
        assert file_model_private == DocumentFilePrivate, "get_file_model(False)失败"
        assert file_model_public == DocumentFilePublic, "get_file_model(True)失败"
        print("✓ get_file_model()")

        # 测试路径生成
        private_path = get_document_relative_path(is_public=False, user_id=1)
        assert 'private/user-1' in private_path, f"私有路径错误: {private_path}"
        print(f"✓ get_document_relative_path(私有): {private_path}")

        public_path = get_document_relative_path(is_public=True)
        assert 'public' in public_path, f"公共路径错误: {public_path}"
        print(f"✓ get_document_relative_path(公共): {public_path}")

        # 测试路径安全校验
        assert is_safe_path('/safe/path', '/safe/path/sub') == True, "路径安全校验失败"
        assert is_safe_path('/safe/path', '../../../etc/passwd') == False, "路径遍历检测失败"
        print("✓ is_safe_path()")

        return True
    except Exception as e:
        print(f"✗ 工具函数测试失败: {e}")
        return False

def test_database_tables():
    """测试数据库表是否存在"""
    print_section("4. 数据库表测试")

    try:
        # 检查表是否存在
        from django.db import connection
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names()

            required_tables = [
                'spug_document_folder_private',
                'spug_document_file_private',
                'spug_document_folder_public',
                'spug_document_file_public'
            ]

            for table in required_tables:
                if table in tables:
                    print(f"✓ 数据表存在: {table}")
                else:
                    print(f"✗ 数据表不存在: {table}")
                    return False

        return True
    except Exception as e:
        print(f"✗ 数据库表检查失败: {e}")
        return False

def test_model_aliases():
    """测试模型别名"""
    print_section("5. 模型别名测试")

    try:
        # 测试DocumentFolder别名（指向Private模型，保持向后兼容）
        assert DocumentFolder == DocumentFolderPrivate, "DocumentFolder别名错误"
        print("✓ DocumentFolder == DocumentFolderPrivate")

        # 测试DocumentFile别名（指向Private模型，保持向后兼容）
        assert DocumentFile == DocumentFilePrivate, "DocumentFile别名错误"
        print("✓ DocumentFile == DocumentFilePrivate")

        return True
    except Exception as e:
        print(f"✗ 模型别名测试失败: {e}")
        return False

def test_database_data():
    """测试数据库数据迁移"""
    print_section("6. 数据库数据迁移测试")

    try:
        # 统计各表数据
        folder_private_count = DocumentFolderPrivate.objects.count()
        file_private_count = DocumentFilePrivate.objects.count()
        folder_public_count = DocumentFolderPublic.objects.count()
        file_public_count = DocumentFilePublic.objects.count()

        print(f"  DocumentFolderPrivate: {folder_private_count} 条记录")
        print(f"  DocumentFilePrivate: {file_private_count} 条记录")
        print(f"  DocumentFolderPublic: {folder_public_count} 条记录")
        print(f"  DocumentFilePublic: {file_public_count} 条记录")

        # 至少应该有一些数据（原数据已迁移）
        total = folder_private_count + file_private_count + folder_public_count + file_public_count
        if total == 0:
            print("  ⚠ 警告: 数据库中没有数据，可能数据迁移未完成")
        else:
            print(f"✓ 数据库总记录数: {total}")

        return True
    except Exception as e:
        print(f"✗ 数据迁移测试失败: {e}")
        return False

def test_views():
    """测试视图函数"""
    print_section("7. 视图函数测试")

    try:
        from apps.document.views import (
            FolderView, FileView, FileUploadView, FileDownloadView,
            FilePreviewView, FileChunkUploadView, FileMergeChunksView,
            FileCheckView, FileMergeStatusView, DiskUsageView,
            FileCopyView, FolderCopyView, FileMoveView, FolderMoveView,
            FileRenameView, FolderRenameView, FolderDownloadView
        )

        views = [
            FolderView, FileView, FileUploadView, FileDownloadView,
            FilePreviewView, FileChunkUploadView, FileMergeChunksView,
            FileCheckView, FileMergeStatusView, DiskUsageView,
            FileCopyView, FolderCopyView, FileMoveView, FolderMoveView,
            FileRenameView, FolderRenameView, FolderDownloadView
        ]

        for view in views:
            print(f"✓ {view.__name__}")

        return True
    except Exception as e:
        print(f"✗ 视图函数测试失败: {e}")
        return False

def test_urls():
    """测试URL路由"""
    print_section("8. URL路由测试")

    try:
        from django.urls import reverse
        from django.urls import resolve

        urls = [
            ('/document/folder/', 'document.views.FolderView'),
            ('/document/file/', 'document.views.FileView'),
            ('/document/upload/', 'document.views.FileUploadView'),
            ('/document/upload_chunk/', 'document.views.FileChunkUploadView'),
            ('/document/merge_chunks/', 'document.views.FileMergeChunksView'),
            ('/document/merge_status/', 'document.views.FileMergeStatusView'),
            ('/document/check_file/', 'document.views.FileCheckView'),
            ('/document/disk_usage/', 'document.views.DiskUsageView'),
            ('/document/download/', 'document.views.FileDownloadView'),
            ('/document/folder/download/', 'document.views.FolderDownloadView'),
            ('/document/preview/', 'document.views.FilePreviewView'),
            ('/document/file/copy/', 'document.views.FileCopyView'),
            ('/document/folder/copy/', 'document.views.FolderCopyView'),
            ('/document/file/move/', 'document.views.FileMoveView'),
            ('/document/folder/move/', 'document.views.FolderMoveView'),
            ('/document/file/rename/', 'document.views.FileRenameView'),
            ('/document/folder/rename/', 'document.views.FolderRenameView'),
        ]

        for url, view_path in urls:
            try:
                match = resolve(url)
                print(f"✓ {url} -> {match.view_name}")
            except Exception as e:
                print(f"✗ {url} 解析失败: {e}")
                return False

        return True
    except Exception as e:
        print(f"✗ URL路由测试失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("  文档管理分表改造 - 快速验证")
    print("=" * 60)

    tests = [
        ("模型导入测试", test_models),
        ("模型字段测试", test_model_fields),
        ("工具函数测试", test_util_functions),
        ("数据库表测试", test_database_tables),
        ("模型别名测试", test_model_aliases),
        ("数据迁移测试", test_database_data),
        ("视图函数测试", test_views),
        ("URL路由测试", test_urls),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"✗ {test_name} 异常: {e}")
            results.append((test_name, False))

    # 打印总结
    print_section("验证总结")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for test_name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status} - {test_name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n✅ 分表改造验证成功!")
        print("\n下一步:")
        print("  1. 运行全量测试: python manage.py test tests.test_document_split_tables")
        print("  2. 运行手动测试: python tests/manual_test_split_tables.py")
        print("  3. 查看测试指南: tests/分表改造测试指南.md")
        return 0
    else:
        print("\n❌ 分表改造验证失败!")
        print("\n请检查:")
        print("  1. 数据库迁移是否完成: python manage.py migrate")
        print("  2. 模型定义是否正确: apps/document/models.py")
        print("  3. 工具函数是否正确: apps/document/libs/document_utils.py")
        print("  4. 视图函数是否正确: apps/document/views.py")
        return 1

if __name__ == '__main__':
    sys.exit(main())
