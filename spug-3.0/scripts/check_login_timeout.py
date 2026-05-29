#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
诊断登录超时问题
"""

import os
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("登录超时问题诊断工具")
print("=" * 60)

# 1. 检查基础导入时间
print("\n[1/5] 检查基础模块导入时间...")
start = time.time()
try:
    import django
    django.setup()
    elapsed = time.time() - start
    print(f"  ✅ Django 初始化: {elapsed:.2f}s")
except Exception as e:
    print(f"  ❌ Django 初始化失败: {e}")
    sys.exit(1)

# 2. 检查 account 模块
print("\n[2/5] 检查 account 模块...")
start = time.time()
try:
    from apps.account.models import User
    elapsed = time.time() - start
    print(f"  ✅ User 模型导入: {elapsed:.2f}s")
except Exception as e:
    print(f"  ❌ User 模型导入失败: {e}")

# 3. 检查 document 模块
print("\n[3/5] 检查 document 模块...")
start = time.time()
try:
    from apps.document.models import DocumentTransfer
    elapsed = time.time() - start
    print(f"  ✅ DocumentTransfer 模型导入: {elapsed:.2f}s")
except Exception as e:
    print(f"  ❌ DocumentTransfer 模型导入失败: {e}")

# 4. 检查 views 模块导入时间
print("\n[4/5] 检查 views 模块导入时间...")
start = time.time()
try:
    from apps.document.views import FolderView, FileView, TransferListView
    elapsed = time.time() - start
    print(f"  ✅ Views 导入: {elapsed:.2f}s")
    if elapsed > 5:
        print(f"  ⚠️  警告: Views 导入时间过长，可能导致请求超时!")
except Exception as e:
    print(f"  ❌ Views 导入失败: {e}")

# 5. 检查 Celery
print("\n[5/5] 检查 Celery 配置...")
start = time.time()
try:
    from spug.celery import app
    broker_url = app.conf.broker_url
    result_backend = app.conf.result_backend
    elapsed = time.time() - start
    print(f"  ✅ Celery 配置加载: {elapsed:.2f}s")
    print(f"     Broker: {broker_url}")
    print(f"     Backend: {result_backend}")
except Exception as e:
    print(f"  ❌ Celery 配置加载失败: {e}")

print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)

print("""
常见问题和解决方案:

1. 如果 Views 导入时间 > 5s:
   - 可能是循环导入导致
   - 检查是否有模块级查询数据库的代码

2. 如果 Celery 配置加载时间 > 3s:
   - 检查 Redis 连接是否正常
   - 检查网络延迟

3. 解决方案:
   - 优化导入链
   - 延迟加载耗时的模块
   - 确保 Celery Worker 和 Beat 正常运行
""")
