#!/usr/bin/env python3
"""
修复拆分后的 views 文件的导入问题
1. 删除重复的工具函数定义
2. 添加正确的导入语句
"""

import os
import re

# 定义哪些函数/变量应该在 utils.py 中，其他文件需要导入
UTILS_ITEMS = [
    'MAX_RECURSION_DEPTH',
    'MAX_FILE_SIZE',
    'CHUNK_CLEANUP_AGE',
    'MERGE_STATUS_TIMEOUT',
    'MERGE_LOCK_TIMEOUT',
    '_merge_locks',
    '_merge_locks_mutex',
    'MergeLock',
    'get_merge_lock',
    'cleanup_stale_locks',
    'cleanup_old_chunks',
    'check_public_space_permission',
    'log_operation',
    'validate_file_name',
    'format_file_size',
    'MIME_TYPES',
    'get_mime_type',
    'handle_view_errors',
    'is_safe_path',
    'create_model_instance',
]

# 需要保留在各自文件中的函数（如果有特殊实现）
KEEP_IN_FILE = {
    'upload.py': ['cleanup_old_chunks'],  # upload.py 中的 cleanup_old_chunks 有特殊逻辑
}

def remove_duplicate_functions(filepath, keep_items=None):
    """删除文件中重复的工具函数定义"""
    if keep_items is None:
        keep_items = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # 删除重复的全局变量定义
    for item in ['MAX_RECURSION_DEPTH', 'MAX_FILE_SIZE', 'CHUNK_CLEANUP_AGE', 
                 'MERGE_STATUS_TIMEOUT', 'MERGE_LOCK_TIMEOUT', '_merge_locks', '_merge_locks_mutex']:
        if item in keep_items:
            continue
        # 匹配变量定义行
        pattern = rf'^{item}\s*=\s*.*?\n'
        content = re.sub(pattern, '', content, flags=re.MULTILINE)
    
    # 删除重复的类定义
    for item in ['MergeLock']:
        if item in keep_items:
            continue
        # 匹配类定义（从 class 开始到下一个类或函数定义之前）
        pattern = rf'^class {item}\(.*?\n(?:(?!\nclass |\ndef ).*?\n)*'
        content = re.sub(pattern, '', content, flags=re.MULTILINE | re.DOTALL)
    
    # 删除重复的函数定义
    for item in UTILS_ITEMS:
        if item in keep_items or item in ['MAX_RECURSION_DEPTH', 'MAX_FILE_SIZE', 'CHUNK_CLEANUP_AGE', 
                                          'MERGE_STATUS_TIMEOUT', 'MERGE_LOCK_TIMEOUT', '_merge_locks', 
                                          '_merge_locks_mutex', 'MergeLock']:
            continue
        # 匹配函数定义（从 def 开始到下一个函数或类定义之前）
        pattern = rf'^def {item}\(.*?\n(?:(?!\nclass |\ndef ).*?\n)*?(?=\nclass |\ndef |\Z)'
        matches = list(re.finditer(pattern, content, re.MULTILINE | re.DOTALL))
        if len(matches) > 0:
            # 删除所有匹配
            for match in reversed(matches):
                content = content[:match.start()] + content[match.end():]
    
    # 删除重复的 MIME_TYPES 字典
    if 'MIME_TYPES' not in keep_items:
        pattern = r'^MIME_TYPES\s*=\s*\{.*?\}\n\n'
        content = re.sub(pattern, '', content, flags=re.MULTILINE | re.DOTALL)
    
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Removed duplicates from {os.path.basename(filepath)}')
        return True
    else:
        print(f'No duplicates found in {os.path.basename(filepath)}')
        return False

def add_imports(filepath):
    """添加从 utils.py 导入的语句"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已经有导入
    if 'from .utils import' in content:
        print(f'Imports already exist in {os.path.basename(filepath)}')
        return
    
    # 找到最后一个 import 语句的位置
    import_match = None
    for pattern in [r'^(?:from|import)\s+.*?\n', r'^import\s+.*?\n']:
        matches = list(re.finditer(pattern, content, re.MULTILINE))
        if matches:
            import_match = matches[-1]
    
    if import_match:
        # 在最后一个 import 后添加新的导入
        insert_pos = import_match.end()
        
        # 根据文件需要导入不同的内容
        imports = '''\n# 从 utils 导入共享函数和变量
from .utils import (
    MAX_RECURSION_DEPTH, MAX_FILE_SIZE, CHUNK_CLEANUP_AGE,
    MERGE_STATUS_TIMEOUT, MERGE_LOCK_TIMEOUT,
    MergeLock, get_merge_lock, cleanup_stale_locks,
    check_public_space_permission, log_operation, validate_file_name,
    format_file_size, get_mime_type, handle_view_errors,
    is_safe_path, create_model_instance,
)\n'''
        
        content = content[:insert_pos] + imports + content[insert_pos:]
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Added imports to {os.path.basename(filepath)}')
    else:
        print(f'Could not find import location in {os.path.basename(filepath)}')

def main():
    base_dir = 'e:/TDYW/spug-3.0/spug_api/apps/document/views'
    
    files_to_fix = ['folder.py', 'file.py', 'upload.py', 'transfer.py']
    
    for fname in files_to_fix:
        filepath = os.path.join(base_dir, fname)
        if not os.path.exists(filepath):
            print(f'File not found: {fname}')
            continue
        
        print(f'\nProcessing {fname}...')
        
        # 删除重复函数
        keep = KEEP_IN_FILE.get(fname, [])
        remove_duplicate_functions(filepath, keep)
        
        # 添加导入
        add_imports(filepath)

if __name__ == '__main__':
    main()
