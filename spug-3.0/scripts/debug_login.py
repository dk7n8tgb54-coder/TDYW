#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
登录问题诊断脚本
在容器内运行此脚本检查 Django 启动问题
"""

import os
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

print("=" * 60)
print("登录问题诊断工具")
print("=" * 60)

# 1. 基础导入
print("\n[1/6] 检查基础导入...")
try:
    start = time.time()
    import django
    print(f"  ✓ Django 导入成功 ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"  ✗ Django 导入失败: {e}")
    sys.exit(1)

# 2. Django setup
print("\n[2/6] 检查 Django setup...")
try:
    start = time.time()
    django.setup()
    print(f"  ✓ Django setup 成功 ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"  ✗ Django setup 失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 3. 检查 document 模块
print("\n[3/6] 检查 document 模块...")
try:
    start = time.time()
    from apps import document
    print(f"  ✓ document 模块导入成功 ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"  ✗ document 模块导入失败: {e}")
    import traceback
    traceback.print_exc()

# 4. 检查 document views
print("\n[4/6] 检查 document views...")
try:
    start = time.time()
    from apps.document import views
    print(f"  ✓ document.views 导入成功 ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"  ✗ document.views 导入失败: {e}")
    import traceback
    traceback.print_exc()

# 5. 检查 document tasks
print("\n[5/6] 检查 document tasks...")
try:
    start = time.time()
    from apps.document import tasks
    print(f"  ✓ document.tasks 导入成功 ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"  ✗ document.tasks 导入失败: {e}")
    import traceback
    traceback.print_exc()

# 6. 检查登录功能
print("\n[6/6] 检查登录相关模块...")
try:
    start = time.time()
    from apps.account import views as account_views
    print(f"  ✓ account.views 导入成功 ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"  ✗ account.views 导入失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)
