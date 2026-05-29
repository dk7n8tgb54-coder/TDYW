#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Document 模块 Views 迁移验证测试脚本

使用方法:
    cd /spug/spug_api
    python tests/test_views_migration.py

测试内容:
    1. 语法检查
    2. 导入链测试
    3. 基础工具函数测试
    4. View 类实例化测试
"""

import os
import sys
import unittest

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("Document 模块 Views 迁移验证测试")
print("=" * 60)

# 测试 1: 基础语法和导入
def test_syntax_and_imports():
    """测试语法和导入链"""
    print("\n[1/5] 语法和导入链测试...")
    
    errors = []
    
    # 1.1 测试基础模块导入
    try:
        from apps.document.views.base import (
            format_file_size, check_public_space_permission, MIME_TYPES,
            get_mime_type, handle_view_errors, log_operation, is_safe_path,
            create_model_instance, validate_file_name, validate_file_upload,
        )
        print("  ✅ base.py 导入成功 (10个工具函数)")
    except Exception as e:
        errors.append(f"base.py: {e}")
        print(f"  ❌ base.py 导入失败: {e}")
    
    # 1.2 测试清理模块
    try:
        from apps.document.views.cleanup import cleanup_old_chunks
        print("  ✅ cleanup.py 导入成功")
    except Exception as e:
        errors.append(f"cleanup.py: {e}")
        print(f"  ❌ cleanup.py 导入失败: {e}")
    
    # 1.3 测试磁盘模块
    try:
        from apps.document.views.disk import DiskUsageView
        print("  ✅ disk.py 导入成功 (DiskUsageView)")
    except Exception as e:
        errors.append(f"disk.py: {e}")
        print(f"  ❌ disk.py 导入失败: {e}")
    
    # 1.4 测试搜索模块
    try:
        from apps.document.views.search import FolderSearchView
        print("  ✅ search.py 导入成功 (FolderSearchView)")
    except Exception as e:
        errors.append(f"search.py: {e}")
        print(f"  ❌ search.py 导入失败: {e}")
    
    # 1.5 测试传输模块
    try:
        from apps.document.views.transfer import (
            TransferListView, TransferCreateView, TransferProgressUpdateView,
            TransferCompleteView, TransferCancelView, TransferStatusUpdateView,
            TransferDeleteView, TransferHashUpdateView, TransferFailView,
            TransferBatchPauseView, TransferBatchResumeView,
            TransferBatchCancelView, TransferBatchDeleteView,
        )
        print("  ✅ transfer.py 导入成功 (12个Transfer View)")
    except Exception as e:
        errors.append(f"transfer.py: {e}")
        print(f"  ❌ transfer.py 导入失败: {e}")
    
    # 1.6 测试上传模块
    try:
        from apps.document.views.upload import (
            FileChunkUploadView, FileMergeChunksView, CheckUploadedChunksView,
            FileMergeStatusView, MergeLock, get_merge_lock, cleanup_stale_locks,
        )
        print("  ✅ upload.py 导入成功 (4个Upload View + MergeLock)")
    except Exception as e:
        errors.append(f"upload.py: {e}")
        print(f"  ❌ upload.py 导入失败: {e}")
    
    # 1.7 测试文件夹模块
    try:
        from apps.document.views.folder import (
            FolderView, FolderCopyView, FolderMoveView,
            FolderDownloadView, FolderRenameView,
        )
        print("  ✅ folder.py 导入成功 (5个Folder View)")
    except Exception as e:
        errors.append(f"folder.py: {e}")
        print(f"  ❌ folder.py 导入失败: {e}")
    
    # 1.8 测试文件模块
    try:
        from apps.document.views.file import (
            FileView, FileUploadView, FileDownloadView,
            FilePreviewView, FileCopyView, FileMoveView, FileRenameView,
        )
        print("  ✅ file.py 导入成功 (7个File View)")
    except Exception as e:
        errors.append(f"file.py: {e}")
        print(f"  ❌ file.py 导入失败: {e}")
    
    # 1.9 测试统一导入
    try:
        from apps.document.views import (
            format_file_size, cleanup_old_chunks,
            DiskUsageView, FolderSearchView,
            TransferListView, TransferCreateView,
            FileChunkUploadView, MergeLock,
            FolderView, FileView,
        )
        print("  ✅ __init__.py 统一导入成功")
    except Exception as e:
        errors.append(f"__init__.py: {e}")
        print(f"  ❌ __init__.py 导入失败: {e}")
    
    return len(errors) == 0, errors


# 测试 2: 工具函数测试
def test_tool_functions():
    """测试工具函数"""
    print("\n[2/5] 工具函数测试...")
    
    errors = []
    
    try:
        from apps.document.views.base import format_file_size
        
        # 测试文件大小格式化
        assert format_file_size(1024) == '1.00 KB', "1KB 格式化失败"
        assert format_file_size(1024 * 1024) == '1.00 MB', "1MB 格式化失败"
        assert format_file_size(1024 * 1024 * 1024) == '1.00 GB', "1GB 格式化失败"
        print("  ✅ format_file_size 测试通过")
    except Exception as e:
        errors.append(f"format_file_size: {e}")
        print(f"  ❌ format_file_size 测试失败: {e}")
    
    try:
        from apps.document.views.base import validate_file_name
        
        # 测试文件名验证
        assert validate_file_name("test.txt") is None, "正常文件名应通过"
        assert validate_file_name("../test.txt") is not None, "路径遍历应被拒绝"
        print("  ✅ validate_file_name 测试通过")
    except Exception as e:
        errors.append(f"validate_file_name: {e}")
        print(f"  ❌ validate_file_name 测试失败: {e}")
    
    try:
        from apps.document.views.base import get_mime_type
        
        # 测试 MIME 类型
        assert get_mime_type("test.txt") == 'text/plain', "txt MIME类型错误"
        assert get_mime_type("test.jpg") == 'image/jpeg', "jpg MIME类型错误"
        print("  ✅ get_mime_type 测试通过")
    except Exception as e:
        errors.append(f"get_mime_type: {e}")
        print(f"  ❌ get_mime_type 测试失败: {e}")
    
    return len(errors) == 0, errors


# 测试 3: View 类实例化测试
def test_view_instantiation():
    """测试 View 类可以实例化"""
    print("\n[3/5] View 类实例化测试...")
    
    errors = []
    view_classes = []
    
    try:
        from apps.document.views import (
            DiskUsageView, FolderSearchView,
            TransferListView, TransferCreateView,
            FileChunkUploadView,
            FolderView, FileView,
        )
        
        view_classes = [
            ('DiskUsageView', DiskUsageView),
            ('FolderSearchView', FolderSearchView),
            ('TransferListView', TransferListView),
            ('TransferCreateView', TransferCreateView),
            ('FileChunkUploadView', FileChunkUploadView),
            ('FolderView', FolderView),
            ('FileView', FileView),
        ]
        
        for name, ViewClass in view_classes:
            try:
                instance = ViewClass()
                print(f"  ✅ {name} 实例化成功")
            except Exception as e:
                errors.append(f"{name}: {e}")
                print(f"  ❌ {name} 实例化失败: {e}")
        
    except Exception as e:
        errors.append(f"导入失败: {e}")
        print(f"  ❌ View 类导入失败: {e}")
    
    return len(errors) == 0, errors


# 测试 4: 模型导入测试
def test_model_imports():
    """测试模型和常量导入"""
    print("\n[4/5] 模型和常量导入测试...")
    
    errors = []
    
    try:
        from apps.document.models import DocumentTransfer
        print("  ✅ DocumentTransfer 模型导入成功")
    except Exception as e:
        errors.append(f"DocumentTransfer: {e}")
        print(f"  ❌ DocumentTransfer 导入失败: {e}")
    
    try:
        from apps.document.constants import TransferStatus
        print("  ✅ TransferStatus 常量导入成功")
    except Exception as e:
        errors.append(f"TransferStatus: {e}")
        print(f"  ❌ TransferStatus 导入失败: {e}")
    
    return len(errors) == 0, errors


# 测试 5: URL 配置测试
def test_url_configuration():
    """测试 URL 配置"""
    print("\n[5/5] URL 配置测试...")
    
    errors = []
    
    try:
        from apps.document.urls import urlpatterns
        url_count = len(urlpatterns)
        print(f"  ✅ URL 配置加载成功 ({url_count} 个路由)")
        
        # 检查关键路由
        paths = [str(p.pattern) for p in urlpatterns]
        required_paths = ['folder/', 'file/', 'upload/', 'transfers/']
        
        for path in required_paths:
            if any(path in p for p in paths):
                print(f"  ✅ 路由 '{path}' 存在")
            else:
                errors.append(f"缺少路由: {path}")
                print(f"  ❌ 路由 '{path}' 缺失")
        
    except Exception as e:
        errors.append(f"URL配置: {e}")
        print(f"  ❌ URL 配置加载失败: {e}")
    
    return len(errors) == 0, errors


def main():
    """主测试函数"""
    results = []
    all_errors = []
    
    # 运行所有测试
    tests = [
        ("语法和导入链", test_syntax_and_imports),
        ("工具函数", test_tool_functions),
        ("View 类实例化", test_view_instantiation),
        ("模型和常量", test_model_imports),
        ("URL 配置", test_url_configuration),
    ]
    
    for name, test_func in tests:
        try:
            success, errors = test_func()
            results.append((name, success))
            all_errors.extend(errors)
        except Exception as e:
            results.append((name, False))
            all_errors.append(f"{name}: {e}")
            print(f"\n  ❌ {name} 测试执行失败: {e}")
    
    # 打印总结
    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{status}: {name}")
    
    print(f"\n总计: {passed}/{total} 项测试通过")
    
    if all_errors:
        print(f"\n错误列表 ({len(all_errors)} 个):")
        for i, error in enumerate(all_errors, 1):
            print(f"  {i}. {error}")
        return 1
    else:
        print("\n🎉 所有测试通过！迁移验证成功。")
        return 0


if __name__ == '__main__':
    try:
        import django
        django.setup()
    except Exception as e:
        print(f"⚠️  Django 初始化警告: {e}")
        print("继续执行基础测试...")
    
    sys.exit(main())
