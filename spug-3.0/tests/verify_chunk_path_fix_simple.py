#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
分片上传路径一致性修复 - 简化验证脚本（不需要Django环境）

验证内容：
1. 公共函数 get_chunk_dir_path 是否存在
2. 三个视图是否调用公共函数
3. 异常处理代码是否完整
4. 清理函数是否优化
"""

import os
import re
import sys

# 设置 stdout 编码为 utf-8
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')


def check_function_exists():
    """检查公共函数是否存在"""
    print("\n" + "="*60)
    print("检查1: 公共函数 get_chunk_dir_path 是否存在")
    print("="*60)
    
    utils_path = 'data/backend/apps/document/libs/document_utils.py'
    
    if not os.path.exists(utils_path):
        print(f"❌ 文件不存在: {utils_path}")
        return False
    
    with open(utils_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ('def get_chunk_dir_path', '函数定义'),
        ('file_hash, is_public, request_user', '参数列表'),
        ('public_{tenant_id}_{user_id}', '公共空间路径'),
        ('ValueError', '异常处理'),
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
    
    print(f"\n检查结果: {passed} 通过, {failed} 失败")
    return failed == 0


def check_views_import():
    """检查视图是否导入公共函数"""
    print("\n" + "="*60)
    print("检查2: 视图是否导入公共函数")
    print("="*60)
    
    views_path = 'data/backend/apps/document/views.py'
    
    if not os.path.exists(views_path):
        print(f"❌ 文件不存在: {views_path}")
        return False
    
    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ('from .libs.document_utils import', '导入语句'),
        ('get_chunk_dir_path', '导入 get_chunk_dir_path'),
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
    
    print(f"\n检查结果: {passed} 通过, {failed} 失败")
    return failed == 0


def check_chunk_upload_view():
    """检查 FileChunkUploadView 是否使用公共函数"""
    print("\n" + "="*60)
    print("检查3: FileChunkUploadView 是否使用公共函数")
    print("="*60)
    
    views_path = 'data/backend/apps/document/views.py'
    
    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取 FileChunkUploadView 类的内容
    start = content.find('class FileChunkUploadView')
    end = content.find('class CheckUploadedChunksView')
    chunk_upload_section = content[start:end]
    
    checks = [
        ('get_chunk_dir_path(file_hash, is_public, request.user)', '调用公共函数'),
        ('except ValueError as e:', '捕获 ValueError'),
        ('except PermissionError as e:', '捕获 PermissionError'),
        ('except OSError as e:', '捕获 OSError'),
        ('分片目录创建失败：权限不足', '权限错误提示'),
        ('分片目录创建失败:', '系统错误提示'),
    ]
    
    # 检查是否不再有重复的路径生成代码（排除用于安全检查的合理重复）
    # 注意：chunk_base_dir 用于 is_safe_path 安全检查是合理的，不算重复
    duplicate_pattern = re.compile(r'tenant_path = f"public_\{tenant_id\}_\{user_id\}"')
    duplicate_count = len(duplicate_pattern.findall(chunk_upload_section))
    
    passed = 0
    failed = 0
    
    for check_str, description in checks:
        if check_str in chunk_upload_section:
            print(f"✅ {description}")
            passed += 1
        else:
            print(f"❌ {description} - 未找到: {check_str}")
            failed += 1
    
    if duplicate_count == 0:
        print(f"✅ 路径生成代码已消除重复")
        passed += 1
    else:
        print(f"❌ 仍存在 {duplicate_count} 处路径生成代码重复")
        failed += 1
    
    print(f"\n检查结果: {passed} 通过, {failed} 失败")
    return failed == 0


def check_merge_chunks_view():
    """检查 FileMergeChunksView 是否使用公共函数"""
    print("\n" + "="*60)
    print("检查4: FileMergeChunksView 是否使用公共函数")
    print("="*60)
    
    views_path = 'data/backend/apps/document/views.py'
    
    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取 FileMergeChunksView 类的内容
    start = content.find('class FileMergeChunksView')
    end = content.find('class FileMergeStatusView')
    merge_chunks_section = content[start:end]
    
    checks = [
        ('chunk_dir = get_chunk_dir_path(file_hash, is_public, request.user)', '调用公共函数'),
        ('except ValueError as e:', '捕获 ValueError'),
    ]
    
    # 检查是否不再有重复的路径生成代码（排除用于安全检查的合理重复）
    duplicate_pattern = re.compile(r'tenant_path = f"public_\{tenant_id\}_\{user_id\}"')
    duplicate_count = len(duplicate_pattern.findall(merge_chunks_section))
    
    passed = 0
    failed = 0
    
    for check_str, description in checks:
        if check_str in merge_chunks_section:
            print(f"✅ {description}")
            passed += 1
        else:
            print(f"❌ {description} - 未找到: {check_str}")
            failed += 1
    
    if duplicate_count == 0:
        print(f"✅ 路径生成代码已消除重复")
        passed += 1
    else:
        print(f"❌ 仍存在 {duplicate_count} 处路径生成代码重复")
        failed += 1
    
    print(f"\n检查结果: {passed} 通过, {failed} 失败")
    return failed == 0


def check_check_chunks_view():
    """检查 CheckUploadedChunksView 是否使用公共函数（核心修复）"""
    print("\n" + "="*60)
    print("检查5: CheckUploadedChunksView 路径修复（核心修复）")
    print("="*60)
    
    views_path = 'data/backend/apps/document/views.py'
    
    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取 CheckUploadedChunksView 类的内容
    start = content.find('class CheckUploadedChunksView')
    end = content.find('class FileMergeStatusView')
    check_chunks_section = content[start:end]
    
    checks = [
        ('chunk_dir = get_chunk_dir_path(file_hash, is_public, request.user)', '调用公共函数'),
        ('is_public={is_public}', '日志包含 is_public'),
    ]
    
    # 检查是否已删除错误的 'public' 路径生成代码
    bad_pattern = "tenant_path = 'public' if is_public else (tenant_id or 'default')"
    
    passed = 0
    failed = 0
    
    for check_str, description in checks:
        if check_str in check_chunks_section:
            print(f"✅ {description}")
            passed += 1
        else:
            print(f"❌ {description} - 未找到: {check_str}")
            failed += 1
    
    if bad_pattern not in check_chunks_section:
        print(f"✅ 错误的 'public' 路径生成代码已删除")
        passed += 1
    else:
        print(f"❌ 仍存在错误的 'public' 路径生成代码")
        failed += 1
    
    print(f"\n检查结果: {passed} 通过, {failed} 失败")
    return failed == 0


def check_cleanup_function():
    """检查 cleanup_old_chunks 是否优化"""
    print("\n" + "="*60)
    print("检查6: cleanup_old_chunks 函数优化")
    print("="*60)
    
    views_path = 'data/backend/apps/document/views.py'
    
    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取 cleanup_old_chunks 函数的内容
    start = content.find('def cleanup_old_chunks():')
    end = content.find('class FileMergeChunksView')
    cleanup_section = content[start:end]
    
    checks = [
        ('shutil.rmtree(md5_dir_path, ignore_errors=True)', '使用 shutil.rmtree'),
        ('Removed empty tenant directory', '自动清理空租户目录'),
        ('age={dir_age:.0f}s', '日志包含 age 信息'),
        ('tenant_dir={tenant_dir_name}, md5_dir={md5_dir_name}', '日志包含详细的目录信息'),
    ]
    
    passed = 0
    failed = 0
    
    for check_str, description in checks:
        if check_str in cleanup_section:
            print(f"✅ {description}")
            passed += 1
        else:
            print(f"❌ {description} - 未找到: {check_str}")
            failed += 1
    
    print(f"\n检查结果: {passed} 通过, {failed} 失败")
    return failed == 0


def main():
    """主函数"""
    print("\n" + "="*60)
    print("分片上传路径一致性修复 - 简化验证脚本")
    print("="*60)
    
    results = []
    
    # 执行所有检查
    results.append(("公共函数存在性", check_function_exists()))
    results.append(("视图导入检查", check_views_import()))
    results.append(("FileChunkUploadView修复", check_chunk_upload_view()))
    results.append(("FileMergeChunksView修复", check_merge_chunks_view()))
    results.append(("CheckUploadedChunksView修复", check_check_chunks_view()))
    results.append(("cleanup_old_chunks优化", check_cleanup_function()))
    
    # 输出汇总
    print("\n" + "="*60)
    print("检查汇总")
    print("="*60)
    
    for check_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{check_name}: {status}")
    
    total_passed = sum(1 for _, passed in results if passed)
    total_tests = len(results)
    
    print(f"\n总计: {total_passed}/{total_tests} 检查通过")
    
    if total_passed == total_tests:
        print("\n✅ 所有检查通过！修复方案验证成功。")
        print("\n下一步：")
        print("1. 重启 Django 服务")
        print("2. 执行完整的功能测试（参见修复完成报告的验证方案）")
        print("3. 部署到生产环境")
        return 0
    else:
        print(f"\n❌ {total_tests - total_passed} 个检查失败，请检查修复方案。")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
