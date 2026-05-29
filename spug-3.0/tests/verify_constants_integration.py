#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证常量集成后的正确性
"""
import os
import sys

# 设置控制台输出编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 设置Django环境
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'data/backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

try:
    import django
    django.setup()
except Exception as e:
    print(f'❌ Django setup失败: {e}')
    sys.exit(1)

def test_constants_import():
    """测试常量导入"""
    print('=' * 60)
    print('测试1: 常量导入')
    print('=' * 60)
    try:
        from apps.document.constants import (
            TransferStatus,
            DEFAULT_MAX_FOLDER_DEPTH,
            DEFAULT_MAX_FILE_SIZE,
            DEFAULT_QUICK_UPLOAD_CACHE_TIMEOUT,
            DEFAULT_CHUNK_CLEANUP_AGE,
            DEFAULT_MERGE_LOCK_TIMEOUT,
            DEFAULT_MERGE_STATUS_TIMEOUT,
            QUICK_UPLOAD_CACHE_KEY_PREFIX
        )
        print('✅ 所有常量导入成功')
        return True
    except ImportError as e:
        print(f'❌ 导入失败: {e}')
        return False

def test_transfer_status_values():
    """测试TransferStatus枚举值"""
    print('\n' + '=' * 60)
    print('测试2: TransferStatus枚举值')
    print('=' * 60)
    try:
        from apps.document.constants import TransferStatus
        from apps.document.models import DocumentTransfer

        model_choices = dict(DocumentTransfer.TRANSFER_STATUS_CHOICES)
        all_ok = True

        print('\n状态值兼容性检查:')
        for status in TransferStatus:
            value = status.value
            lower = value.lower()
            if value in model_choices:
                print(f'  ✅ {status.name}: value="{value}", lower="{lower}"')
            else:
                print(f'  ❌ {status.name}: value="{value}" 不在模型中')
                all_ok = False

        if all_ok:
            print('\n✅ 所有状态值与模型兼容')
        return all_ok
    except Exception as e:
        print(f'❌ 测试失败: {e}')
        import traceback
        traceback.print_exc()
        return False

def test_constant_values():
    """测试常量值是否正确"""
    print('\n' + '=' * 60)
    print('测试3: 配置常量值')
    print('=' * 60)
    try:
        from apps.document.constants import (
            DEFAULT_MAX_FOLDER_DEPTH,
            DEFAULT_MAX_FILE_SIZE,
            DEFAULT_QUICK_UPLOAD_CACHE_TIMEOUT,
            DEFAULT_CHUNK_CLEANUP_AGE,
            DEFAULT_MERGE_LOCK_TIMEOUT,
            DEFAULT_MERGE_STATUS_TIMEOUT,
            QUICK_UPLOAD_CACHE_KEY_PREFIX
        )

        expected = {
            'DEFAULT_MAX_FOLDER_DEPTH': 100,
            'DEFAULT_MAX_FILE_SIZE': 10 * 1024 * 1024 * 1024,
            'DEFAULT_QUICK_UPLOAD_CACHE_TIMEOUT': 86400,
            'DEFAULT_CHUNK_CLEANUP_AGE': 24 * 3600,
            'DEFAULT_MERGE_LOCK_TIMEOUT': 600,
            'DEFAULT_MERGE_STATUS_TIMEOUT': 300,
            'QUICK_UPLOAD_CACHE_KEY_PREFIX': 'spug:quick_upload:'
        }

        all_ok = True
        for name, expected_value in expected.items():
            actual_value = eval(name)
            if actual_value == expected_value:
                print(f'  ✅ {name} = {actual_value}')
            else:
                print(f'  ❌ {name} = {actual_value}, 期望 {expected_value}')
                all_ok = False

        if all_ok:
            print('\n✅ 所有常量值正确')
        return all_ok
    except Exception as e:
        print(f'❌ 测试失败: {e}')
        import traceback
        traceback.print_exc()
        return False

def test_views_syntax():
    """测试views.py语法"""
    print('\n' + '=' * 60)
    print('测试4: views.py语法检查')
    print('=' * 60)
    try:
        import py_compile
        py_compile.compile('data/backend/apps/document/views.py', doraise=True)
        print('✅ views.py语法正确')
        return True
    except py_compile.PyCompileError as e:
        print(f'❌ 语法错误: {e}')
        return False

def test_no_hardcoded_strings():
    """测试没有硬编码状态字符串"""
    print('\n' + '=' * 60)
    print('测试5: 硬编码字符串检查')
    print('=' * 60)
    try:
        with open('data/backend/apps/document/views.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查是否还有单引号或双引号包裹的状态字符串（排除注释和字符串中的自然语言）
        import re

        # 检查形如 'failed' 或 "failed" 的独立字符串（排除在json.dumps中的情况）
        # 这里只检查在 write() 调用中的情况
        write_pattern = r"f\.write\(['\"](?:failed|pending|merging|completed|canceled|uploading|paused)['\"]"
        matches = re.findall(write_pattern, content)

        if matches:
            print(f'  ❌ 发现{len(matches)}处未替换的硬编码状态字符串')
            for match in matches[:5]:  # 只显示前5个
                print(f'     {match}')
            return False
        else:
            print('✅ 未发现write()中的硬编码状态字符串')

        # 检查status字段赋值中的硬编码
        status_pattern = r"'status':\s*['\"](?:failed|pending|merging)['\"]"
        status_matches = re.findall(status_pattern, content)

        if status_matches:
            print(f'  ❌ 发现{len(status_matches)}处未替换的硬编码status')
            return False
        else:
            print('✅ 未发现硬编码status赋值')

        return True
    except Exception as e:
        print(f'❌ 检查失败: {e}')
        import traceback
        traceback.print_exc()
        return False

def test_import_in_views():
    """测试views.py中的导入"""
    print('\n' + '=' * 60)
    print('测试6: views.py导入检查')
    print('=' * 60)
    try:
        with open('data/backend/apps/document/views.py', 'r', encoding='utf-8') as f:
            content = f.read()

        required_imports = [
            'TransferStatus',
            'DEFAULT_MAX_FOLDER_DEPTH',
            'DEFAULT_MAX_FILE_SIZE',
            'DEFAULT_QUICK_UPLOAD_CACHE_TIMEOUT',
            'DEFAULT_CHUNK_CLEANUP_AGE',
            'DEFAULT_MERGE_LOCK_TIMEOUT',
            'DEFAULT_MERGE_STATUS_TIMEOUT',
            'QUICK_UPLOAD_CACHE_KEY_PREFIX'
        ]

        all_ok = True
        for import_name in required_imports:
            if import_name in content:
                print(f'  ✅ {import_name} 已导入')
            else:
                print(f'  ❌ {import_name} 未导入')
                all_ok = False

        if all_ok:
            print('\n✅ 所需常量已导入')
        return all_ok
    except Exception as e:
        print(f'❌ 检查失败: {e}')
        return False

def main():
    print('\n' + '=' * 60)
    print('常量集成验证报告')
    print('=' * 60)

    results = {
        '常量导入': test_constants_import(),
        'TransferStatus枚举值': test_transfer_status_values(),
        '配置常量值': test_constant_values(),
        'views.py语法': test_views_syntax(),
        '硬编码字符串': test_no_hardcoded_strings(),
        'views.py导入': test_import_in_views()
    }

    print('\n' + '=' * 60)
    print('测试结果汇总')
    print('=' * 60)
    for test_name, passed in results.items():
        status = '✅ 通过' if passed else '❌ 失败'
        print(f'  {test_name}: {status}')

    all_passed = all(results.values())
    print('\n' + '=' * 60)
    if all_passed:
        print('🎉 所有测试通过！未发现新bug')
    else:
        print('⚠️  部分测试失败，请检查上述错误')
    print('=' * 60 + '\n')

    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
