#!/usr/bin/env python3
"""
测试 DocumentTransfer 模型
Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
Copyright: (c) <spug.dev@gmail.com>
Released under the AGPL-3.0 License.
"""
import os
import sys
import django

# 添加项目路径
sys.path.insert(0, '/data/spug/spug_api/apps')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

django.setup()

from apps.document.models import DocumentTransfer
from apps.account.models import User

print("=== DocumentTransfer 模型测试 ===\n")

# 测试1: 创建一条传输记录
print("1. 创建传输记录...")
try:
    # 先检查用户是否存在
    user = User.objects.filter(id=5).first()
    if not user:
        print("✗ 用户不存在，使用 NULL")
        transfer = DocumentTransfer.objects.create(
            tenant_id='admin',
            transfer_type='UPLOAD',
            status='UPLOADING',
            file_name='test_file.pdf',
            file_size=1024000,
            file_path='/test/path/test_file.pdf',
            file_hash='abc123def456',
            folder_id=1,
            is_public=False,
            total_chunks=10,
            uploaded_chunks=5,
            progress=50,
            transferred_size=512000,
            speed=102400.0,
        )
    else:
        print(f"✓ 使用用户: {user.username}")
        transfer = DocumentTransfer.objects.create(
            tenant_id='admin',
            user=user,
            transfer_type='UPLOAD',
            status='UPLOADING',
            file_name='test_file.pdf',
            file_size=1024000,
            file_path='/test/path/test_file.pdf',
            file_hash='abc123def456',
            folder_id=1,
            is_public=False,
            total_chunks=10,
            uploaded_chunks=5,
            progress=50,
            transferred_size=512000,
            speed=102400.0,
        )
    print(f"✓ 创建成功，ID: {transfer.id}")
    print(f"  - 文件名: {transfer.file_name}")
    print(f"  - 状态: {transfer.status}")
    print(f"  - 进度: {transfer.progress}%")
except Exception as e:
    print(f"✗ 创建失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试2: 查询传输记录
print("\n2. 查询传输记录...")
try:
    transfer = DocumentTransfer.objects.get(id=transfer.id)
    print(f"✓ 查询成功")
    print(f"  - 租户ID: {transfer.tenant_id}")
    print(f"  - 传输类型: {transfer.transfer_type}")
    print(f"  - 文件大小: {transfer.file_size} 字节")
except Exception as e:
    print(f"✗ 查询失败: {e}")
    sys.exit(1)

# 测试3: 更新传输记录
print("\n3. 更新传输记录...")
try:
    transfer.progress = 75
    transfer.uploaded_chunks = 8
    transfer.transferred_size = 768000
    transfer.save()
    print(f"✓ 更新成功")
    print(f"  - 新进度: {transfer.progress}%")
    print(f"  - 已上传分片: {transfer.uploaded_chunks}")
except Exception as e:
    print(f"✗ 更新失败: {e}")
    sys.exit(1)

# 测试4: 按租户查询
print("\n4. 按租户查询...")
try:
    transfers = DocumentTransfer.objects.filter(tenant_id='admin')
    print(f"✓ 查询成功，找到 {transfers.count()} 条记录")
except Exception as e:
    print(f"✗ 查询失败: {e}")
    sys.exit(1)

# 测试5: 按状态查询
print("\n5. 按状态查询...")
try:
    uploading_transfers = DocumentTransfer.objects.filter(status='UPLOADING')
    print(f"✓ 查询成功，正在上传的记录: {uploading_transfers.count()} 条")
except Exception as e:
    print(f"✗ 查询失败: {e}")
    sys.exit(1)

# 测试6: 完成传输
print("\n6. 完成传输...")
try:
    from django.utils import timezone
    transfer.status = 'COMPLETED'
    transfer.progress = 100
    transfer.uploaded_chunks = transfer.total_chunks
    transfer.transferred_size = transfer.file_size
    transfer.completed_at = timezone.now()
    transfer.save()
    print(f"✓ 完成成功")
    print(f"  - 最终状态: {transfer.status}")
    print(f"  - 完成时间: {transfer.completed_at}")
except Exception as e:
    print(f"✗ 完成失败: {e}")
    sys.exit(1)

# 清理测试数据
print("\n7. 清理测试数据...")
try:
    transfer.delete()
    print(f"✓ 清理成功")
except Exception as e:
    print(f"✗ 清理失败: {e}")

print("\n=== 所有测试通过 ===")
