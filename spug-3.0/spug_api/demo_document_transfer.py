#!/usr/bin/env python3
"""
DocumentTransfer 模型使用示例
展示如何在文件上传/下载过程中使用 DocumentTransfer 表持久化传输记录
Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
Copyright: (c) <spug.dev@gmail.com>
Released under the AGPL-3.0 License.
"""
import os
import sys
import django

sys.path.insert(0, '/data/spug/spug_api/apps')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

django.setup()

from apps.document.models import DocumentTransfer
from apps.account.models import User
from django.utils import timezone

print("=" * 60)
print("DocumentTransfer 模型使用示例")
print("=" * 60)

# 示例1: 创建上传记录
print("\n【示例1】创建文件上传记录")
print("-" * 60)
user = User.objects.filter(id=5).first()
upload_transfer = DocumentTransfer.objects.create(
    tenant_id=user.tenant_id if user else 'default',
    user=user,
    transfer_type='UPLOAD',
    status='PENDING',
    file_name='大文件_演示.pdf',
    file_size=1024 * 1024 * 100,  # 100MB
    file_path='/upload/temp/大文件_演示.pdf',
    file_hash='md5_hash_of_large_file',
    folder_id=1,
    is_public=False,
    total_chunks=50,
    uploaded_chunks=0,
    progress=0,
    transferred_size=0,
    speed=0,
)
print(f"✓ 上传记录已创建")
print(f"  ID: {upload_transfer.id}")
print(f"  文件名: {upload_transfer.file_name}")
print(f"  文件大小: {upload_transfer.file_size / 1024 / 1024:.2f} MB")
print(f"  状态: {upload_transfer.status}")

# 示例2: 开始上传
print("\n【示例2】开始上传")
print("-" * 60)
upload_transfer.status = 'UPLOADING'
upload_transfer.started_at = timezone.now()
upload_transfer.save()
print(f"✓ 上传已开始")
print(f"  状态: {upload_transfer.status}")
print(f"  开始时间: {upload_transfer.started_at}")

# 示例3: 更新上传进度
print("\n【示例3】更新上传进度（模拟上传5个分片）")
print("-" * 60)
for i in range(1, 6):
    upload_transfer.uploaded_chunks += 1
    upload_transfer.transferred_size = int(upload_transfer.file_size * upload_transfer.uploaded_chunks / upload_transfer.total_chunks)
    upload_transfer.progress = int(upload_transfer.uploaded_chunks / upload_transfer.total_chunks * 100)
    upload_transfer.speed = 1024 * 1024 * 5  # 5MB/s
    upload_transfer.save()
    print(f"  分片 {i}/{upload_transfer.total_chunks}: 进度 {upload_transfer.progress}%, 已传输 {upload_transfer.transferred_size / 1024 / 1024:.2f} MB")

# 示例4: 上传完成
print("\n【示例4】上传完成")
print("-" * 60)
upload_transfer.status = 'COMPLETED'
upload_transfer.progress = 100
upload_transfer.transferred_size = upload_transfer.file_size
upload_transfer.completed_at = timezone.now()
upload_transfer.save()
print(f"✓ 上传已完成")
print(f"  状态: {upload_transfer.status}")
print(f"  完成时间: {upload_transfer.completed_at}")
print(f"  总耗时: {(upload_transfer.completed_at - upload_transfer.started_at).total_seconds():.2f} 秒")

# 示例5: 创建下载记录
print("\n【示例5】创建文件下载记录")
print("-" * 60)
download_transfer = DocumentTransfer.objects.create(
    tenant_id=user.tenant_id if user else 'default',
    user=user,
    transfer_type='DOWNLOAD',
    status='DOWNLOADING',
    file_name='大文件_演示.pdf',
    file_size=upload_transfer.file_size,
    file_path=upload_transfer.file_path,
    file_hash=upload_transfer.file_hash,
    total_chunks=50,
    uploaded_chunks=10,
    progress=20,
    transferred_size=1024 * 1024 * 20,
    speed=1024 * 1024 * 2,
)
print(f"✓ 下载记录已创建")
print(f"  ID: {download_transfer.id}")
print(f"  文件名: {download_transfer.file_name}")
print(f"  状态: {download_transfer.status}")
print(f"  进度: {download_transfer.progress}%")

# 示例6: 查询用户的传输记录
print("\n【示例6】查询用户的传输记录")
print("-" * 60)
user_transfers = DocumentTransfer.objects.filter(user=user).order_by('-created_at')
print(f"✓ 用户 {user.username} 的传输记录: {user_transfers.count()} 条")
for t in user_transfers[:3]:
    type_str = "上传" if t.transfer_type == 'UPLOAD' else "下载"
    print(f"  [{type_str}] {t.file_name} - {t.status} - {t.progress}%")

# 示例7: 按状态查询
print("\n【示例7】查询正在进行的传输")
print("-" * 60)
active_transfers = DocumentTransfer.objects.filter(
    tenant_id=user.tenant_id,
    status__in=['UPLOADING', 'DOWNLOADING', 'PENDING']
).order_by('-created_at')
print(f"✓ 正在进行的传输: {active_transfers.count()} 条")
for t in active_transfers:
    type_str = "上传" if t.transfer_type == 'UPLOAD' else "下载"
    print(f"  [{type_str}] {t.file_name} - {t.status} - {t.progress}%")

# 示例8: 按租户查询
print("\n【示例8】按租户查询传输记录")
print("-" * 60)
tenant_transfers = DocumentTransfer.objects.filter(tenant_id=user.tenant_id)
print(f"✓ 租户 '{user.tenant_id}' 的所有传输记录: {tenant_transfers.count()} 条")
print(f"  上传: {tenant_transfers.filter(transfer_type='UPLOAD').count()} 条")
print(f"  下载: {tenant_transfers.filter(transfer_type='DOWNLOAD').count()} 条")
print(f"  已完成: {tenant_transfers.filter(status='COMPLETED').count()} 条")
print(f"  进行中: {tenant_transfers.filter(status__in=['UPLOADING', 'DOWNLOADING']).count()} 条")
print(f"  失败: {tenant_transfers.filter(status='FAILED').count()} 条")

# 示例9: 取消传输
print("\n【示例9】取消下载传输")
print("-" * 60)
download_transfer.status = 'CANCELED'
download_transfer.error_message = '用户主动取消'
download_transfer.save()
print(f"✓ 下载已取消")
print(f"  状态: {download_transfer.status}")
print(f"  取消原因: {download_transfer.error_message}")

# 示例10: 清理旧的传输记录
print("\n【示例10】清理30天前的已完成记录")
print("-" * 60)
from datetime import timedelta
cutoff_date = timezone.now() - timedelta(days=30)
old_transfers = DocumentTransfer.objects.filter(
    status='COMPLETED',
    completed_at__lt=cutoff_date
)
count = old_transfers.count()
old_transfers.delete()
print(f"✓ 已清理 {count} 条30天前的已完成记录")

# 清理测试数据
print("\n【清理】删除测试数据")
print("-" * 60)
upload_transfer.delete()
download_transfer.delete()
print("✓ 测试数据已清理")

print("\n" + "=" * 60)
print("所有示例演示完成")
print("=" * 60)
