# DocumentTransfer 表使用说明

## 概述

`DocumentTransfer` 表用于持久化文件上传/下载的传输记录，解决了传输列表在页面刷新后丢失的问题，并支持多租户隔离。

## 表结构

### 字段说明

| 字段名 | 类型 | 说明 | 索引 |
|--------|------|------|------|
| id | INT | 主键ID | 主键 |
| tenant_id | VARCHAR(50) | 租户标识（多租户隔离） | ✓ |
| user_id | INT | 用户ID（外键到users表） | ✓ |
| transfer_type | VARCHAR(20) | 传输类型：UPLOAD（上传）/ DOWNLOAD（下载） | ✓ |
| status | VARCHAR(20) | 状态：PENDING/UPLOADING/DOWNLOADING/PAUSED/COMPLETED/FAILED/CANCELED | ✓ |
| file_name | VARCHAR(255) | 文件名 | - |
| file_size | BIGINT | 文件大小（字节） | - |
| file_path | VARCHAR(500) | 文件存储路径 | - |
| file_hash | VARCHAR(100) | 文件哈希（MD5，用于秒传） | ✓ |
| folder_id | INT | 目标文件夹ID（上传时使用） | - |
| is_public | BOOLEAN | 是否公共空间 | - |
| total_chunks | INT | 总分片数 | - |
| uploaded_chunks | INT | 已上传分片数 | - |
| progress | INT | 进度百分比（0-100） | - |
| transferred_size | BIGINT | 已传输大小（字节） | - |
| speed | FLOAT | 传输速度（字节/秒） | - |
| created_at | DATETIME | 创建时间 | ✓ |
| started_at | DATETIME | 开始时间 | - |
| completed_at | DATETIME | 完成时间 | - |
| updated_at | DATETIME | 更新时间 | - |
| error_message | TEXT | 错误信息 | - |

### 索引设计

- `idx_transfer_tenant_user`: (tenant_id, user_id) - 按租户+用户查询
- `idx_transfer_tenant_status`: (tenant_id, status) - 按租户+状态查询
- `idx_transfer_tenant_hash`: (tenant_id, file_hash) - 按租户+文件哈希查询（秒传检测）
- `idx_transfer_user_status`: (user_id, status) - 按用户+状态查询
- `idx_transfer_created`: (created_at) - 按创建时间查询

## 使用场景

### 1. 开始上传文件

```python
from apps.document.models import DocumentTransfer
from apps.account.models import User
from django.utils import timezone

user = request_user  # 从请求获取用户
transfer = DocumentTransfer.objects.create(
    tenant_id=user.tenant_id,
    user=user,
    transfer_type='UPLOAD',
    status='PENDING',
    file_name=file.name,
    file_size=file.size,
    file_path=temp_path,
    file_hash=file.md5,
    folder_id=folder_id,
    is_public=is_public,
    total_chunks=total_chunks,
    uploaded_chunks=0,
    progress=0,
    transferred_size=0,
    speed=0,
)
```

### 2. 上传过程中更新进度

```python
# 开始上传
transfer.status = 'UPLOADING'
transfer.started_at = timezone.now()
transfer.save()

# 上传每个分片后更新
transfer.uploaded_chunks += 1
transfer.transferred_size = chunk_size * transfer.uploaded_chunks
transfer.progress = int(transfer.transferred_size / transfer.file_size * 100)
transfer.speed = calculate_speed()
transfer.save()
```

### 3. 上传完成

```python
transfer.status = 'COMPLETED'
transfer.progress = 100
transfer.transferred_size = transfer.file_size
transfer.completed_at = timezone.now()
transfer.save()
```

### 4. 上传失败

```python
transfer.status = 'FAILED'
transfer.error_message = error_msg
transfer.save()
```

### 5. 用户取消上传

```python
transfer.status = 'CANCELED'
transfer.error_message = '用户主动取消'
transfer.save()
```

### 6. 开始下载文件

```python
transfer = DocumentTransfer.objects.create(
    tenant_id=user.tenant_id,
    user=user,
    transfer_type='DOWNLOAD',
    status='DOWNLOADING',
    file_name=file.name,
    file_size=file.file_size,
    file_path=file.file_path,
    file_hash=file.md5,
)
```

### 7. 查询用户的传输列表

```python
# 获取所有传输记录（按时间倒序）
transfers = DocumentTransfer.objects.filter(
    tenant_id=user.tenant_id,
    user=user
).order_by('-created_at')

# 获取正在进行的传输
active_transfers = DocumentTransfer.objects.filter(
    tenant_id=user.tenant_id,
    status__in=['UPLOADING', 'DOWNLOADING', 'PENDING']
).order_by('-created_at')

# 获取已完成的传输
completed_transfers = DocumentTransfer.objects.filter(
    tenant_id=user.tenant_id,
    user=user,
    status='COMPLETED'
).order_by('-completed_at')
```

### 8. 检测秒传（通过文件哈希查询）

```python
# 检查该租户下是否已上传过相同文件
existing_transfer = DocumentTransfer.objects.filter(
    tenant_id=user.tenant_id,
    file_hash=file_hash,
    status='COMPLETED',
    is_public=is_public
).first()

if existing_transfer:
    # 秒传成功，直接创建记录即可
    transfer = DocumentTransfer.objects.create(
        tenant_id=user.tenant_id,
        user=user,
        transfer_type='UPLOAD',
        status='COMPLETED',  # 直接完成
        file_name=file_name,
        file_size=file_size,
        file_path=existing_transfer.file_path,  # 复用已有路径
        file_hash=file_hash,
        folder_id=folder_id,
        is_public=is_public,
        total_chunks=0,
        uploaded_chunks=0,
        progress=100,
        transferred_size=file_size,
        speed=0,
        completed_at=timezone.now(),
    )
```

### 9. 清理过期记录

```python
from datetime import timedelta

# 清理30天前的已完成记录
cutoff_date = timezone.now() - timedelta(days=30)
old_transfers = DocumentTransfer.objects.filter(
    status='COMPLETED',
    completed_at__lt=cutoff_date
).delete()

# 清理失败的记录（保留7天）
failed_cutoff = timezone.now() - timedelta(days=7)
failed_transfers = DocumentTransfer.objects.filter(
    status='FAILED',
    created_at__lt=failed_cutoff
).delete()
```

## 前端集成建议

### 1. 页面加载时恢复传输列表

```javascript
async function loadTransferList() {
  const response = await fetch('/api/document/transfers/', {
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });
  const transfers = await response.json();
  this.transferQueue = transfers.data;
  // 恢复正在进行的传输状态
  transfers.data.forEach(t => {
    if (t.status === 'UPLOADING' || t.status === 'DOWNLOADING') {
      // 可以选择自动恢复或标记为暂停
      resumeTransfer(t);
    }
  });
}
```

### 2. 更新传输状态

```javascript
async function updateTransferProgress(transferId, progress, speed) {
  await fetch(`/api/document/transfers/${transferId}/progress/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({
      progress,
      speed,
      uploaded_chunks: ...,
      transferred_size: ...,
    }),
  });
}
```

### 3. 完成传输

```javascript
async function completeTransfer(transferId) {
  await fetch(`/api/document/transfers/${transferId}/complete/`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });
}
```

## 后端API接口建议

### 1. 获取传输列表

```
GET /api/document/transfers/
Query参数:
  - status: 可选，筛选状态
  - type: 可选，筛选类型（UPLOAD/DOWNLOAD）

响应:
{
  "data": [
    {
      "id": 1,
      "transfer_type": "UPLOAD",
      "status": "UPLOADING",
      "file_name": "test.pdf",
      "file_size": 1024000,
      "progress": 50,
      "speed": 1024000,
      "created_at": "2026-02-28 22:00:00"
    },
    ...
  ]
}
```

### 2. 创建传输记录

```
POST /api/document/transfers/
请求体:
{
  "transfer_type": "UPLOAD",
  "file_name": "test.pdf",
  "file_size": 1024000,
  "file_hash": "abc123",
  "folder_id": 1,
  "is_public": false
}

响应:
{
  "data": {
    "id": 1,
    "status": "PENDING",
    ...
  }
}
```

### 3. 更新进度

```
POST /api/document/transfers/{id}/progress/
请求体:
{
  "uploaded_chunks": 5,
  "transferred_size": 512000,
  "progress": 50,
  "speed": 1024000
}
```

### 4. 完成传输

```
POST /api/document/transfers/{id}/complete/
```

### 5. 取消传输

```
POST /api/document/transfers/{id}/cancel/
```

### 6. 删除传输记录

```
DELETE /api/document/transfers/{id}/
```

## 多租户隔离

所有查询都必须包含 `tenant_id` 过滤，确保不同租户的数据完全隔离：

```python
# ✅ 正确：按租户查询
transfers = DocumentTransfer.objects.filter(tenant_id=user.tenant_id)

# ❌ 错误：未过滤租户
transfers = DocumentTransfer.objects.all()  # 违反多租户原则
```

## 性能优化建议

1. **批量更新进度**：每秒更新一次，而不是每个分片都更新
2. **使用数据库索引**：已创建常用查询索引
3. **清理过期数据**：定期清理30天前的已完成记录
4. **使用 select_related**：查询用户信息时使用 `select_related('user')` 减少查询次数

```python
# 高效查询
transfers = DocumentTransfer.objects.filter(
    tenant_id=user.tenant_id
).select_related('user').order_by('-created_at')
```

## 错误处理

```python
try:
    transfer = DocumentTransfer.objects.get(id=transfer_id)
    if transfer.tenant_id != user.tenant_id:
        raise PermissionError('无权访问此传输记录')
except DocumentTransfer.DoesNotExist:
    raise NotFound('传输记录不存在')
```

## 总结

`DocumentTransfer` 表提供了完整的文件传输记录管理功能：
- ✅ 持久化存储，页面刷新不丢失
- ✅ 支持多租户隔离
- ✅ 记录完整的传输进度和状态
- ✅ 支持秒传检测
- ✅ 提供丰富的查询接口
- ✅ 包含性能优化索引
