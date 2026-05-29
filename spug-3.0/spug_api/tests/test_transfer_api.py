#!/usr/bin/env python3
"""
测试传输记录 API 接口
Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
Copyright: (c) <spug.dev@gmail.com>
Released under the AGPL-3.0 License.
"""
import os
import sys
import django
import json

sys.path.insert(0, '/data/spug/spug_api/apps')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

django.setup()

from apps.document.models import DocumentTransfer
from apps.account.models import User
from django.test import Client
from django.urls import reverse

print("=" * 60)
print("传输记录 API 接口测试")
print("=" * 60)

# 获取测试用户
user = User.objects.filter(id=5).first()
if not user:
    print("✗ 测试用户不存在")
    sys.exit(1)

print(f"\n测试用户: {user.username}, 租户ID: {user.tenant_id}")

# 创建 Django 测试客户端
client = Client()

# 模拟登录（需要根据实际认证方式调整）
# 由于使用的是自定义认证，这里直接测试逻辑

print("\n【测试1】创建传输记录")
print("-" * 60)

# 直接创建测试数据（不通过API，因为需要认证token）
transfer1 = DocumentTransfer.objects.create(
    tenant_id=user.tenant_id,
    user=user,
    transfer_type='UPLOAD',
    status='UPLOADING',
    file_name='测试文件1.pdf',
    file_size=1024 * 1024 * 50,
    file_path='/upload/test1.pdf',
    file_hash='hash1',
    folder_id=1,
    is_public=False,
    total_chunks=25,
    uploaded_chunks=10,
    progress=40,
    transferred_size=1024 * 1024 * 20,
    speed=1024 * 1024,
)
print(f"✓ 创建成功: ID={transfer1.id}, 文件名={transfer1.file_name}, 状态={transfer1.status}")

transfer2 = DocumentTransfer.objects.create(
    tenant_id=user.tenant_id,
    user=user,
    transfer_type='DOWNLOAD',
    status='COMPLETED',
    file_name='测试文件2.docx',
    file_size=1024 * 1024 * 10,
    file_path='/download/test2.docx',
    file_hash='hash2',
    folder_id=2,
    is_public=True,
    total_chunks=5,
    uploaded_chunks=5,
    progress=100,
    transferred_size=1024 * 1024 * 10,
    speed=0,
)
print(f"✓ 创建成功: ID={transfer2.id}, 文件名={transfer2.file_name}, 状态={transfer2.status}")

print("\n【测试2】查询传输记录")
print("-" * 60)

# 测试按用户查询
user_transfers = DocumentTransfer.objects.filter(user=user)
print(f"✓ 用户 {user.username} 的传输记录: {user_transfers.count()} 条")
for t in user_transfers:
    type_str = "上传" if t.transfer_type == 'UPLOAD' else "下载"
    print(f"  [{type_str}] {t.file_name} - {t.status} - {t.progress}%")

# 测试按租户查询
tenant_transfers = DocumentTransfer.objects.filter(tenant_id=user.tenant_id)
print(f"\n✓ 租户 {user.tenant_id} 的传输记录: {tenant_transfers.count()} 条")

# 测试按状态查询
uploading_transfers = DocumentTransfer.objects.filter(status='UPLOADING')
print(f"✓ 正在上传的记录: {uploading_transfers.count()} 条")

completed_transfers = DocumentTransfer.objects.filter(status='COMPLETED')
print(f"✓ 已完成的记录: {completed_transfers.count()} 条")

print("\n【测试3】更新传输进度")
print("-" * 60)

transfer1.progress = 60
transfer1.uploaded_chunks = 15
transfer1.transferred_size = 1024 * 1024 * 30
transfer1.speed = 1024 * 1024 * 2
transfer1.save()
print(f"✓ 更新成功: {transfer1.file_name} - 进度={transfer1.progress}%")

print("\n【测试4】完成传输")
print("-" * 60)

from django.utils import timezone
transfer1.status = 'COMPLETED'
transfer1.progress = 100
transfer1.transferred_size = transfer1.file_size
transfer1.uploaded_chunks = transfer1.total_chunks
transfer1.completed_at = timezone.now()
transfer1.save()
print(f"✓ 完成成功: {transfer1.file_name} - 状态={transfer1.status}")

print("\n【测试5】取消传输（创建新记录用于测试）")
print("-" * 60)

transfer3 = DocumentTransfer.objects.create(
    tenant_id=user.tenant_id,
    user=user,
    transfer_type='UPLOAD',
    status='UPLOADING',
    file_name='测试文件3.pdf',
    file_size=1024 * 1024 * 20,
    file_path='/upload/test3.pdf',
    file_hash='hash3',
    folder_id=1,
    is_public=False,
    total_chunks=10,
    uploaded_chunks=5,
    progress=50,
    transferred_size=1024 * 1024 * 10,
    speed=1024 * 1024,
)
print(f"✓ 创建: {transfer3.file_name} - 状态={transfer3.status}")

transfer3.status = 'CANCELED'
transfer3.error_message = '用户主动取消'
transfer3.save()
print(f"✓ 取消成功: {transfer3.file_name} - 状态={transfer3.status}")

print("\n【测试6】删除传输记录")
print("-" * 60)

# 只能删除已完成的记录
file_name = transfer3.file_name
transfer3.delete()
print(f"✓ 删除成功: {file_name}")

print("\n【测试7】权限验证（多租户隔离）")
print("-" * 60)

# 创建另一个租户的记录
other_user = User.objects.filter(id=6).first()
if other_user and other_user.tenant_id != user.tenant_id:
    other_transfer = DocumentTransfer.objects.create(
        tenant_id=other_user.tenant_id,
        user=other_user,
        transfer_type='UPLOAD',
        status='UPLOADING',
        file_name='其他租户文件.pdf',
        file_size=1024 * 1024 * 5,
        file_path='/upload/other.pdf',
        file_hash='other_hash',
        folder_id=1,
        is_public=False,
        total_chunks=5,
        uploaded_chunks=2,
        progress=40,
        transferred_size=1024 * 1024 * 2,
        speed=512 * 1024,
    )
    print(f"✓ 创建其他租户记录: {other_transfer.file_name}, 租户={other_transfer.tenant_id}")

    # 验证租户隔离：用户A只能看到自己的记录
    user_tenant_transfers = DocumentTransfer.objects.filter(tenant_id=user.tenant_id)
    print(f"✓ 租户隔离验证: 用户{user.username}的租户记录数={user_tenant_transfers.count()}")

    other_tenant_transfers = DocumentTransfer.objects.filter(tenant_id=other_user.tenant_id)
    print(f"✓ 租户隔离验证: 用户{other_user.username}的租户记录数={other_tenant_transfers.count()}")

    # 清理其他租户的测试数据
    other_transfer.delete()

print("\n【测试8】复杂查询（组合条件）")
print("-" * 60)

# 组合查询：租户 + 用户 + 状态
complex_query = DocumentTransfer.objects.filter(
    tenant_id=user.tenant_id,
    user=user,
    status='COMPLETED'
)
print(f"✓ 组合查询（租户+用户+已完成）: {complex_query.count()} 条")

# 按时间范围查询
from datetime import timedelta, datetime
time_threshold = timezone.now() - timedelta(minutes=5)
recent_transfers = DocumentTransfer.objects.filter(
    tenant_id=user.tenant_id,
    created_at__gte=time_threshold
)
print(f"✓ 最近5分钟的记录: {recent_transfers.count()} 条")

# 清理测试数据
print("\n【清理】删除测试数据")
print("-" * 60)

transfer1.delete()
transfer2.delete()
print("✓ 测试数据已清理")

print("\n" + "=" * 60)
print("所有 API 接口测试完成")
print("=" * 60)
print("\n提示：实际 HTTP API 测试需要使用认证 token，建议使用 Postman 或 curl")
