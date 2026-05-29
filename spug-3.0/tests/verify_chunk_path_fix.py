#!/usr/bin/env python
"""
分片上传路径一致性修复 - 自动化验证脚本

验证内容：
1. 公共函数 get_chunk_dir_path 正确性
2. 三个视图路径生成一致性
3. 异常处理完整性
4. 清理函数兼容性
"""

import os
import sys

# 添加项目路径到 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Django环境初始化
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from apps.document.libs.document_utils import get_chunk_dir_path


class MockUser:
    """模拟用户对象"""
    def __init__(self, user_id, tenant_id=None):
        self.id = user_id
        self.tenant_id = tenant_id
        self.username = f'test_user_{user_id}'


def test_get_chunk_dir_path():
    """测试公共路径生成函数"""
    print("\n" + "="*60)
    print("测试1: get_chunk_dir_path 公共函数")
    print("="*60)
    
    test_cases = [
        # (file_hash, is_public, user, expected_tenant_path, description)
        ("a" * 32, True, MockUser(1, 10), "public_10_1", "公共空间：租户10用户1"),
        ("b" * 32, True, MockUser(2, 20), "public_20_2", "公共空间：租户20用户2"),
        ("c" * 32, False, MockUser(3, 30), "30", "私有空间：租户30"),
        ("d" * 32, False, MockUser(4, None), "default", "私有空间：无租户（默认）"),
        ("e" * 32, True, MockUser(5, None), "public_default_5", "公共空间：无租户（默认）"),
    ]
    
    passed = 0
    failed = 0
    
    for file_hash, is_public, user, expected_tenant_path, description in test_cases:
        try:
            result = get_chunk_dir_path(file_hash, is_public, user)
            
            # 检查路径是否包含预期的租户路径
            if expected_tenant_path in result:
                print(f"✅ {description}")
                print(f"   预期包含: {expected_tenant_path}")
                print(f"   实际路径: {result}")
                passed += 1
            else:
                print(f"❌ {description}")
                print(f"   预期包含: {expected_tenant_path}")
                print(f"   实际路径: {result}")
                failed += 1
                
        except Exception as e:
            print(f"❌ {description}")
            print(f"   异常: {e}")
            failed += 1
    
    print(f"\n测试结果: {passed} 通过, {failed} 失败")
    return failed == 0


def test_md5_format_validation():
    """测试MD5格式验证"""
    print("\n" + "="*60)
    print("测试2: MD5格式验证")
    print("="*60)
    
    test_cases = [
        # (file_hash, should_raise, description)
        ("a" * 32, False, "32位MD5（有效）"),
        ("0123456789abcdef0123456789abcdef", False, "32位十六进制（有效）"),
        ("a" * 31, True, "31位MD5（无效）"),
        ("a" * 33, True, "33位MD5（无效）"),
        ("", True, "空字符串（无效）"),
        (None, True, "None（无效）"),
        ("g" * 32, True, "包含非法字符（无效）"),
    ]
    
    passed = 0
    failed = 0
    user = MockUser(1, 10)
    
    for file_hash, should_raise, description in test_cases:
        try:
            result = get_chunk_dir_path(file_hash, True, user)
            
            if should_raise:
                print(f"❌ {description}")
                print(f"   预期: 抛出异常")
                print(f"   实际: 未抛出异常")
                failed += 1
            else:
                print(f"✅ {description}")
                passed += 1
                
        except ValueError as e:
            if should_raise:
                print(f"✅ {description}")
                print(f"   异常: {e}")
                passed += 1
            else:
                print(f"❌ {description}")
                print(f"   预期: 不抛出异常")
                print(f"   实际: 抛出异常 {e}")
                failed += 1
                
        except Exception as e:
            print(f"❌ {description}")
            print(f"   意外异常: {e}")
            failed += 1
    
    print(f"\n测试结果: {passed} 通过, {failed} 失败")
    return failed == 0


def test_views_import():
    """测试视图是否正确导入公共函数"""
    print("\n" + "="*60)
    print("测试3: 视图导入检查")
    print("="*60)
    
    try:
        from apps.document.views import (
            FileChunkUploadView,
            FileMergeChunksView,
            CheckUploadedChunksView
        )
        
        # 检查源文件是否包含 get_chunk_dir_path 导入
        views_path = os.path.join(project_root, 'data/backend/apps/document/views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if 'from .libs.document_utils import get_chunk_dir_path' in content:
            print("✅ views.py 正确导入 get_chunk_dir_path")
            return True
        else:
            print("❌ views.py 未导入 get_chunk_dir_path")
            return False
            
    except ImportError as e:
        print(f"❌ 视图导入失败: {e}")
        return False


def test_cleanup_function():
    """测试清理函数是否存在且正确"""
    print("\n" + "="*60)
    print("测试4: 清理函数检查")
    print("="*60)
    
    try:
        from apps.document.views import cleanup_old_chunks
        
        # 检查源文件是否包含 shutil.rmtree
        views_path = os.path.join(project_root, 'data/backend/apps/document/views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        checks = [
            ('shutil.rmtree', '使用 shutil.rmtree 删除目录'),
            ('Removed empty tenant directory', '自动清理空租户目录'),
            ('age={dir_age:.0f}s', '日志包含 age 信息'),
        ]
        
        passed = 0
        failed = 0
        
        for check_str, description in checks:
            if check_str in content:
                print(f"✅ {description}")
                passed += 1
            else:
                print(f"❌ {description} - 未找到: {check_str}")
                failed += 1
        
        print(f"\n测试结果: {passed} 通过, {failed} 失败")
        return failed == 0
        
    except ImportError as e:
        print(f"❌ 清理函数导入失败: {e}")
        return False


def test_exception_handling():
    """测试异常处理代码"""
    print("\n" + "="*60)
    print("测试5: 异常处理代码检查")
    print("="*60)
    
    views_path = os.path.join(project_root, 'data/backend/apps/document/views.py')
    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查 FileChunkUploadView 的异常处理
    chunk_upload_section = content[content.find('class FileChunkUploadView'):content.find('def cleanup_old_chunks')]
    
    checks = [
        ('ValueError', '捕获 ValueError（MD5格式错误）'),
        ('PermissionError', '捕获 PermissionError（权限错误）'),
        ('OSError', '捕获 OSError（系统错误）'),
        ('分片目录创建失败：权限不足', '权限错误提示'),
        ('分片目录创建失败:', '系统错误提示'),
    ]
    
    passed = 0
    failed = 0
    
    for check_str, description in checks:
        if check_str in chunk_upload_section:
            print(f"✅ {description}")
            passed += 1
        else:
            print(f"❌ {description} - 未找到: {check_str}")
            failed += 1
    
    print(f"\n测试结果: {passed} 通过, {failed} 失败")
    return failed == 0


def main():
    """主函数"""
    print("\n" + "="*60)
    print("分片上传路径一致性修复 - 自动化验证")
    print("="*60)
    
    results = []
    
    # 执行所有测试
    results.append(("公共函数测试", test_get_chunk_dir_path()))
    results.append(("MD5格式验证", test_md5_format_validation()))
    results.append(("视图导入检查", test_views_import()))
    results.append(("清理函数检查", test_cleanup_function()))
    results.append(("异常处理检查", test_exception_handling()))
    
    # 输出汇总
    print("\n" + "="*60)
    print("测试汇总")
    print("="*60)
    
    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name}: {status}")
    
    total_passed = sum(1 for _, passed in results if passed)
    total_tests = len(results)
    
    print(f"\n总计: {total_passed}/{total_tests} 测试通过")
    
    if total_passed == total_tests:
        print("\n✅ 所有测试通过！修复方案验证成功。")
        return 0
    else:
        print(f"\n❌ {total_tests - total_passed} 个测试失败，请检查修复方案。")
        return 1


if __name__ == '__main__':
    sys.exit(main())
