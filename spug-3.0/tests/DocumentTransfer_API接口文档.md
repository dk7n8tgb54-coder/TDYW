# DocumentTransfer API 接口文档

## 概述

`DocumentTransfer` API 提供文件上传/下载传输记录的持久化管理，支持多租户隔离。

## 基础信息

- **Base URL**: `/api/document/`
- **认证方式**: Token 认证（在请求头中携带 `Authorization: Bearer {token}`）
- **多租户隔离**: 所有接口自动应用租户过滤，用户只能操作自己的传输记录

## 接口列表

### 1. 获取传输记录列表

**接口**: `GET /api/document/transfers/`

**权限**: `document.document.view`

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 否 | 传输状态筛选（PENDING/UPLOADING/DOWNLOADING/COMPLETED/FAILED/CANCELED） |
| transfer_type | string | 否 | 传输类型筛选（UPLOAD/DOWNLOAD） |

**响应示例**:
```json
{
  "data": [
    {
      "id": 1,
      "transfer_type": "UPLOAD",
      "status": "UPLOADING",
      "file_name": "大文件.pdf",
      "file_size": 104857600,
      "progress": 50,
      "transferred_size": 52428800,
      "speed": 1048576,
      "total_chunks": 50,
      "uploaded_chunks": 25,
      "folder_id": 1,
      "is_public": false,
      "created_at": "2026-02-28 22:00:00",
      "started_at": "2026-02-28 22:00:05",
      "completed_at": null,
      "error_message": null
    }
  ]
}
```

**前端使用示例**:
```javascript
async function loadTransferList(statusFilter = '') {
  const params = {};
  if (statusFilter) {
    params.status = statusFilter;
  }

  const response = await http.get('/api/document/transfers/', { params });
  return response.data;
}

// 获取所有传输记录
const allTransfers = await loadTransferList();

// 获取正在进行的传输
const activeTransfers = await loadTransferList('UPLOADING');

// 获取已完成的传输
const completedTransfers = await loadTransferList('COMPLETED');
```

---

### 2. 创建传输记录

**接口**: `POST /api/document/transfers/create/`

**权限**: `document.document.upload`

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| transfer_type | string | 是 | 传输类型：UPLOAD（上传）/ DOWNLOAD（下载） |
| file_name | string | 是 | 文件名 |
| file_size | int | 是 | 文件大小（字节） |
| file_hash | string | 否 | 文件哈希（MD5，用于秒传） |
| folder_id | int | 否 | 目标文件夹ID（上传时使用） |
| is_public | bool | 否 | 是否公共空间 |
| total_chunks | int | 否 | 总分片数 |

**请求示例**:
```json
{
  "transfer_type": "UPLOAD",
  "file_name": "大文件.pdf",
  "file_size": 104857600,
  "file_hash": "d41d8cd98f00b204e9800998ecf8427e",
  "folder_id": 1,
  "is_public": false,
  "total_chunks": 50
}
```

**响应示例**:
```json
{
  "data": {
    "id": 1,
    "status": "PENDING"
  }
}
```

**前端使用示例**:
```javascript
async function createTransfer(file, folderId, isPublic) {
  const response = await http.post('/api/document/transfers/create/', {
    transfer_type: 'UPLOAD',
    file_name: file.name,
    file_size: file.size,
    file_hash: file.md5 || '',
    folder_id: folderId,
    is_public: isPublic,
    total_chunks: Math.ceil(file.size / CHUNK_SIZE),
  });
  return response.data; // { id: 1, status: 'PENDING' }
}
```

---

### 3. 更新传输进度

**接口**: `POST /api/document/transfers/{transfer_id}/progress/`

**权限**: `document.document.upload`

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uploaded_chunks | int | 否 | 已上传分片数 |
| progress | int | 否 | 进度百分比（0-100） |
| transferred_size | int | 否 | 已传输大小（字节） |
| speed | float | 否 | 传输速度（字节/秒） |

**请求示例**:
```json
{
  "uploaded_chunks": 25,
  "progress": 50,
  "transferred_size": 52428800,
  "speed": 1048576
}
```

**响应示例**:
```json
{
  "data": {
    "status": "updated"
  }
}
```

**前端使用示例**:
```javascript
async function updateProgress(transferId, progressData) {
  await http.post(`/api/document/transfers/${transferId}/progress/`, {
    uploaded_chunks: progressData.uploadedChunks,
    progress: progressData.progress,
    transferred_size: progressData.transferredSize,
    speed: progressData.speed,
  });
}

// 在分片上传回调中使用
onChunkUploaded: async (transferId, chunkIndex, totalChunks, transferredSize) => {
  const progress = Math.round((chunkIndex + 1) / totalChunks * 100);
  await updateProgress(transferId, {
    uploadedChunks: chunkIndex + 1,
    progress: progress,
    transferredSize: transferredSize,
    speed: calculateSpeed(), // 需要自己实现速度计算
  });
}
```

---

### 4. 完成传输

**接口**: `POST /api/document/transfers/{transfer_id}/complete/`

**权限**: `document.document.upload`

**请求参数**: 无

**响应示例**:
```json
{
  "data": {
    "status": "completed",
    "completed_at": "2026-02-28 22:30:00"
  }
}
```

**前端使用示例**:
```javascript
async function completeTransfer(transferId) {
  const response = await http.post(`/api/document/transfers/${transferId}/complete/`);
  return response.data;
}

// 文件合并完成后调用
onMergeComplete: async (transferId) => {
  await completeTransfer(transferId);
  // 刷新传输列表
  await loadTransferList();
}
```

---

### 5. 取消传输

**接口**: `POST /api/document/transfers/{transfer_id}/cancel/`

**权限**: `document.document.upload`

**请求参数**: 无

**响应示例**:
```json
{
  "data": {
    "status": "canceled"
  }
}
```

**前端使用示例**:
```javascript
async function cancelTransfer(transferId) {
  const response = await http.post(`/api/document/transfers/${transferId}/cancel/`);
  return response.data;
}

// 用户点击取消按钮时调用
onCancel: async (transferId) => {
  await cancelTransfer(transferId);
  // 取消前端的上传任务
  cancelUploadTask(transferId);
  // 刷新传输列表
  await loadTransferList();
}
```

---

### 6. 删除传输记录

**接口**: `DELETE /api/document/transfers/{transfer_id}/delete/`

**权限**: `document.document.upload`

**请求参数**: 无

**响应示例**:
```json
{
  "data": {
    "status": "deleted"
  }
}
```

**前端使用示例**:
```javascript
async function deleteTransfer(transferId) {
  const response = await http.delete(`/api/document/transfers/${transferId}/delete/`);
  return response.data;
}

// 用户点击删除记录按钮时调用
onDelete: async (transferId) => {
  await deleteTransfer(transferId);
  // 刷新传输列表
  await loadTransferList();
}
```

---

## 完整前端集成示例

### 1. 页面加载时恢复传输列表

```javascript
import { http } from '@/libs/http';

class TransferStore {
  constructor() {
    this.transfers = [];
    this.loading = false;
  }

  // 页面加载时恢复传输列表
  async loadTransfers() {
    this.loading = true;
    try {
      const response = await http.get('/api/document/transfers/');
      this.transfers = response.data;

      // 恢复正在进行的传输状态
      const activeTransfers = this.transfers.filter(t =>
        t.status === 'UPLOADING' || t.status === 'DOWNLOADING'
      );

      // 可以选择自动恢复或标记为暂停
      for (const transfer of activeTransfers) {
        console.log(`发现未完成的传输: ${transfer.file_name}, ID=${transfer.id}`);
        // TODO: 恢复上传逻辑
      }
    } catch (error) {
      console.error('加载传输列表失败:', error);
    } finally {
      this.loading = false;
    }
  }

  // 创建上传任务
  async createUploadTask(file, folderId, isPublic) {
    const response = await http.post('/api/document/transfers/create/', {
      transfer_type: 'UPLOAD',
      file_name: file.name,
      file_size: file.size,
      file_hash: file.md5 || '',
      folder_id: folderId,
      is_public: isPublic,
      total_chunks: Math.ceil(file.size / CHUNK_SIZE),
    });

    const transfer = {
      id: response.data.id,
      status: 'UPLOADING',
      ...response.data,
    };

    this.transfers.unshift(transfer);
    return transfer;
  }

  // 更新上传进度
  async updateProgress(transferId, progressData) {
    await http.post(`/api/document/transfers/${transferId}/progress/`, {
      uploaded_chunks: progressData.uploadedChunks,
      progress: progressData.progress,
      transferred_size: progressData.transferredSize,
      speed: progressData.speed,
    });

    // 更新本地状态
    const transfer = this.transfers.find(t => t.id === transferId);
    if (transfer) {
      Object.assign(transfer, progressData);
    }
  }

  // 完成上传
  async completeUpload(transferId) {
    await http.post(`/api/document/transfers/${transferId}/complete/`);

    // 更新本地状态
    const transfer = this.transfers.find(t => t.id === transferId);
    if (transfer) {
      transfer.status = 'COMPLETED';
      transfer.progress = 100;
      transfer.completed_at = new Date().toLocaleString();
    }
  }

  // 取消上传
  async cancelUpload(transferId) {
    await http.post(`/api/document/transfers/${transferId}/cancel/`);

    // 更新本地状态
    const transfer = this.transfers.find(t => t.id === transferId);
    if (transfer) {
      transfer.status = 'CANCELED';
    }
  }

  // 删除记录
  async deleteTransfer(transferId) {
    await http.delete(`/api/document/transfers/${transferId}/delete/`);

    // 从本地状态中移除
    this.transfers = this.transfers.filter(t => t.id !== transferId);
  }

  // 获取正在进行的传输
  getActiveTransfers() {
    return this.transfers.filter(t =>
      t.status === 'UPLOADING' || t.status === 'DOWNLOADING' || t.status === 'PENDING'
    );
  }

  // 获取已完成的传输
  getCompletedTransfers() {
    return this.transfers.filter(t => t.status === 'COMPLETED');
  }
}

// 导出单例
export const transferStore = new TransferStore();
```

### 2. 在 UploadCoreStore 中集成

```javascript
// 在现有的 UploadCoreStore 中添加传输记录管理
class UploadCoreStore {
  // ... 现有代码 ...

  async uploadFile(file, folderId, isPublic) {
    // 1. 创建传输记录
    const transfer = await transferStore.createUploadTask(file, folderId, isPublic);

    // 2. 开始上传
    transfer.status = 'UPLOADING';
    transfer.started_at = new Date().toLocaleString();

    // 3. 分片上传
    for (let i = 0; i < totalChunks; i++) {
      await this.uploadChunk(file, i);

      // 更新进度
      const progress = Math.round((i + 1) / totalChunks * 100);
      const transferredSize = (i + 1) * CHUNK_SIZE;

      await transferStore.updateProgress(transfer.id, {
        uploadedChunks: i + 1,
        progress: progress,
        transferredSize: Math.min(transferredSize, file.size),
        speed: this.calculateSpeed(),
      });
    }

    // 4. 合并分片
    await this.mergeChunks(file, folderId, isPublic);

    // 5. 完成传输
    await transferStore.completeUpload(transfer.id);
  }
}
```

### 3. 在组件中使用

```jsx
import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { transferStore } from '@/stores/transferStore';

const TransferList = observer(() => {
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadTransfers();
  }, []);

  const loadTransfers = async () => {
    setLoading(true);
    await transferStore.loadTransfers();
    setLoading(false);
  };

  const handleCancel = async (transferId) => {
    await transferStore.cancelUpload(transferId);
    await loadTransfers();
  };

  const handleDelete = async (transferId) => {
    await transferStore.deleteTransfer(transferId);
  };

  if (loading) return <div>加载中...</div>;

  return (
    <div>
      <h2>传输列表</h2>

      {/* 正在进行的传输 */}
      <div>
        <h3>正在上传</h3>
        {transferStore.getActiveTransfers().map(transfer => (
          <div key={transfer.id}>
            <span>{transfer.file_name}</span>
            <span>{transfer.progress}%</span>
            <button onClick={() => handleCancel(transfer.id)}>取消</button>
          </div>
        ))}
      </div>

      {/* 已完成的传输 */}
      <div>
        <h3>已完成</h3>
        {transferStore.getCompletedTransfers().map(transfer => (
          <div key={transfer.id}>
            <span>{transfer.file_name}</span>
            <span>{transfer.completed_at}</span>
            <button onClick={() => handleDelete(transfer.id)}>删除</button>
          </div>
        ))}
      </div>
    </div>
  );
});

export default TransferList;
```

---

## 错误码说明

| 错误码 | 说明 | 解决方案 |
|--------|------|---------|
| 无权更新此传输记录 | 尝试更新其他用户的传输记录 | 检查当前用户是否为传输记录的创建者 |
| 无权操作此传输记录 | 尝试完成/取消其他用户的传输记录 | 检查当前用户是否为传输记录的创建者 |
| 无权删除此传输记录 | 尝试删除其他用户的传输记录 | 检查当前用户是否为传输记录的创建者 |
| 只能取消未完成的传输 | 尝试取消已完成的传输 | 检查传输状态 |
| 只能删除已完成的传输记录 | 尝试删除进行中的传输 | 等待传输完成或先取消传输 |
| 传输记录不存在 | 指定的传输ID不存在 | 检查传输ID是否正确 |

---

## 性能优化建议

1. **批量更新进度**: 每秒更新一次，而不是每个分片都更新
2. **限制返回数量**: 列表接口默认返回最近100条记录
3. **使用索引优化**: 已针对高频查询场景添加索引
4. **前端缓存**: 本地维护传输状态，减少频繁的 API 调用

---

## 安全说明

1. **多租户隔离**: 所有接口自动应用租户过滤，用户只能操作自己的传输记录
2. **权限验证**: 每个接口都进行权限检查
3. **审计日志**: 关键操作记录日志（创建、完成、取消、删除）
4. **越权防护**: 检查用户是否为传输记录的创建者，防止越权操作
