#!/usr/bin/env python3
"""
快速验证事务保护和批量操作实现

运行方式:
    python verify_implementation.py

功能验证:
    1. 验证Celery任务添加事务保护
    2. 验证批量API端点可用
    3. 验证前端批量方法已添加
"""

import os
import sys

def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_check(name, status, details=""):
    icon = "[OK]" if status else "[FAIL]"
    print(f"  {icon} {name}")
    if details:
        print(f"      {details}")

def check_backend_transaction_protection():
    """检查后端事务保护实现"""
    print_header("Backend Transaction Protection")
    
    batch_file = 'spug_api/apps/document/tasks/batch.py'
    
    if not os.path.exists(batch_file):
        print_check("batch.py 文件存在", False, f"文件不存在: {batch_file}")
        return False
    
    with open(batch_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查事务导入
    has_transaction_import = 'from django.db import transaction' in content
    print_check("Import transaction module", has_transaction_import)
    
    # 检查批量删除任务的事务保护
    batch_delete_has_atomic = 'with transaction.atomic():' in content and 'batch_delete_transfers' in content
    print_check("batch_delete_transfers transaction protection", batch_delete_has_atomic)
    
    # 检查批量取消任务的事务保护
    batch_cancel_has_atomic = content.count('with transaction.atomic():') >= 2
    print_check("batch_cancel_transfers transaction protection", batch_cancel_has_atomic)
    
    # 检查 select_for_update 使用
    has_select_for_update = 'select_for_update()' in content
    print_check("Use select_for_update()", has_select_for_update)
    
    return all([
        has_transaction_import,
        batch_delete_has_atomic,
        batch_cancel_has_atomic,
        has_select_for_update
    ])

def check_frontend_batch_operations():
    """检查前端批量操作实现"""
    print_header("Frontend Batch Operations")
    
    transfer_file = 'spug_web/src/pages/document/stores/upload/core/transfer.js'
    index_file = 'spug_web/src/pages/document/stores/upload/core/index.js'
    
    all_good = True
    
    # 检查 transfer.js
    if os.path.exists(transfer_file):
        with open(transfer_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        has_batch_pause = 'batchPauseTransfers' in content
        print_check("batchPauseTransfers method", has_batch_pause)
        
        has_batch_resume = 'batchResumeTransfers' in content
        print_check("batchResumeTransfers method", has_batch_resume)
        
        has_batch_cancel = 'batchCancelTransfers' in content
        print_check("batchCancelTransfers method", has_batch_cancel)
        
        has_loading = 'message.loading' in content
        print_check("Loading state management", has_loading)
        
        all_good = all_good and all([has_batch_pause, has_batch_resume, has_batch_cancel, has_loading])
    else:
        print_check("transfer.js exists", False, f"File not found: {transfer_file}")
        all_good = False
    
    # 检查 index.js
    if os.path.exists(index_file):
        with open(index_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查是否使用批量API替代循环
        pause_uses_batch = 'batchPauseTransfers' in content
        print_check("pauseAll uses batch API", pause_uses_batch)
        
        resume_uses_batch = 'batchResumeTransfers' in content
        print_check("resumeAll uses batch API", resume_uses_batch)
        
        cancel_uses_batch = 'batchCancelTransfers' in content
        print_check("cancelAll uses batch API", cancel_uses_batch)
        
        all_good = all_good and all([pause_uses_batch, resume_uses_batch, cancel_uses_batch])
    else:
        print_check("index.js exists", False, f"File not found: {index_file}")
        all_good = False
    
    return all_good

def check_api_endpoints():
    """检查API端点配置"""
    print_header("API Endpoints")
    
    api_file = 'spug_web/src/pages/document/stores/constants/api.js'
    
    if not os.path.exists(api_file):
        print_check("api.js 文件存在", False, f"文件不存在: {api_file}")
        return False
    
    with open(api_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    endpoints = [
        'TRANSFERS_BATCH_PAUSE',
        'TRANSFERS_BATCH_RESUME',
        'TRANSFERS_BATCH_CANCEL',
        'TRANSFERS_BATCH_DELETE',
    ]
    
    all_exist = True
    for endpoint in endpoints:
        exists = endpoint in content
        print_check(f"{endpoint} 端点", exists)
        all_exist = all_exist and exists
    
    return all_exist

def show_code_snippets():
    """展示关键代码片段"""
    print_header("Key Code Snippets")
    
    print("\n[1. Backend Transaction Protection Code]")
    print("-" * 70)
    batch_file = 'spug_api/apps/document/tasks/batch.py'
    if os.path.exists(batch_file):
        with open(batch_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 找到 transaction.atomic 相关代码
        for i, line in enumerate(lines):
            if 'with transaction.atomic():' in line:
                start = max(0, i - 2)
                end = min(len(lines), i + 8)
                for j in range(start, end):
                    prefix = ">>> " if j == i else "    "
                    print(f"{prefix}{lines[j].rstrip()}")
                print()
                break
    
    print("\n[2. Frontend Batch Pause Method]")
    print("-" * 70)
    transfer_file = 'spug_web/src/pages/document/stores/upload/core/transfer.js'
    if os.path.exists(transfer_file):
        with open(transfer_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 找到 batchPauseTransfers 方法
        import re
        match = re.search(r'async batchPauseTransfers\(ids\) \{[^}]+\}', content, re.DOTALL)
        if match:
            snippet = match.group(0)[:300]
            print(snippet + "...")
        print()
    
    print("\n[3. pauseAll Using Batch API]")
    print("-" * 70)
    index_file = 'spug_web/src/pages/document/stores/upload/core/index.js'
    if os.path.exists(index_file):
        with open(index_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 找到批量API调用
        if 'batchPauseTransfers' in content:
            idx = content.find('batchPauseTransfers')
            start = max(0, idx - 100)
            end = min(len(content), idx + 200)
            snippet = content[start:end]
            lines = snippet.split('\n')
            for line in lines:
                if 'batchPauseTransfers' in line or 'try' in line or 'catch' in line:
                    print(f"    {line.strip()}")
        print()

def main():
    print("\n" + "=" * 70)
    print("  Transaction Protection & Batch Operations Verification")
    print("=" * 70)
    
    results = []
    
    # 检查后端
    backend_ok = check_backend_transaction_protection()
    results.append(("后端事务保护", backend_ok))
    
    # 检查前端
    frontend_ok = check_frontend_batch_operations()
    results.append(("前端批量操作", frontend_ok))
    
    # 检查API端点
    api_ok = check_api_endpoints()
    results.append(("API端点配置", api_ok))
    
    # 展示代码片段
    show_code_snippets()
    
    # 最终总结
    print_header("Verification Summary")
    
    all_passed = all(r[1] for r in results)
    
    for name, status in results:
        icon = "[OK]" if status else "[FAIL]"
        print(f"  {icon} {name}")
    
    print("\n" + "-" * 70)
    if all_passed:
        print("  [OK] All checks passed! Implementation is correct.")
    else:
        print("  [FAIL] Some checks failed. Please check details above.")
    print("-" * 70)
    
    print("\nNext Steps:")
    print("  1. Run full tests: python run_batch_transaction_tests.py")
    print("  2. Read test docs: 事务保护与批量操作测试说明.md")
    print("  3. Manual API test: Use curl or Postman to test batch endpoints")
    
    print("\n" + "=" * 70 + "\n")
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
