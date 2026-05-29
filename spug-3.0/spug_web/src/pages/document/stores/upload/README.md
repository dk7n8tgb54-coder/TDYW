# UploadCoreStore 拆分说明

## 拆分背景

原 `UploadCoreStore.js` 文件约 **88KB (2494行)**，包含以下功能：
- 上传队列管理
- 普通文件上传
- 分片上传
- 文件夹上传
- MD5计算（Worker池）
- 传输记录管理
- 各种控制方法（暂停/恢复/取消）

## 拆分后的结构

```
stores/upload/
├── core/                          # 上传核心逻辑
│   ├── index.js                   # UploadCoreStore组合器 (~600行)
│   ├── queue.js                   # 队列管理 (~250行)
│   ├── fileUpload.js              # 普通文件上传 (~200行)
│   ├── chunkUpload.js             # 分片上传 (~400行)
│   ├── folderUpload.js            # 文件夹上传 (~150行)
│   ├── md5.js                     # MD5计算 (~200行)
│   └── transfer.js                # 传输记录管理 (~150行)
├── ui/                            # UI状态
│   └── ...                        # 待实现
├── constants/                     # 常量管理
│   ├── index.js                   # 统一导出
│   ├── upload.js                  # 上传常量
│   └── api.js                     # API端点
└── README.md                      # 本文件
```

## 文件说明

### 1. queue.js - 上传队列管理
**职责：**
- 管理按租户分组的上传队列
- 维护活跃上传计数
- 防重复提交（uniqueKeys管理）
- 队列查询和更新方法

**主要方法：**
- `findUploadItem(uploadId)` - 跨租户查找上传项
- `addUploadItem(item, tenantId)` - 添加上传项
- `clearInactiveUploads()` - 清理非活跃上传项
- `waitForSlot()` - 等待并发槽位

### 2. fileUpload.js - 普通文件上传
**职责：**
- 处理小文件（≤20MB）上传
- 创建FormData并发送请求
- 处理上传进度
- 错误处理

**主要方法：**
- `uploadFileNormal(file, folderId, uploadId)` - 普通上传
- `uploadFileToFolder(file, targetFolderId, folderPath)` - 文件夹内上传

### 3. chunkUpload.js - 分片上传
**职责：**
- 处理大文件（>20MB）分片上传
- 断点续传检查
- 分片上传循环
- 合并分片
- 轮询合并状态

**主要方法：**
- `uploadFileChunked(file, folderId, uploadId)` - 分片上传入口
- `uploadSingleChunk(...)` - 上传单个分片
- `mergeChunks(...)` - 合并分片
- `pollMergeStatus(...)` - 轮询合并状态

### 4. folderUpload.js - 文件夹上传
**职责：**
- 处理文件夹选择
- 递归创建文件夹结构
- 批量上传文件夹内文件

**主要方法：**
- `handleFolderSelect(files)` - 处理文件夹选择
- `createFolderStructure(folderPath, parentId)` - 创建文件夹结构

### 5. md5.js - MD5计算
**职责：**
- 管理Web Worker池
- 计算文件MD5
- 任务队列管理

**主要方法：**
- `initMD5WorkerPool()` - 初始化Worker池
- `calculateFileMD5(file, uploadId)` - 计算MD5
- `cleanupMD5WorkerPool()` - 清理Worker池

### 6. transfer.js - 传输记录管理
**职责：**
- 传输记录的CRUD操作
- 批量操作API调用

**主要方法：**
- `fetchTransfers(isPublic)` - 获取传输列表
- `createTransfer(transferData)` - 创建传输记录
- `updateTransferStatus(transferId, status)` - 更新状态
- `batchPauseTransfers(transferIds)` - 批量暂停
- `batchCancelTransfers(transferIds)` - 批量取消

### 7. index.js - UploadCoreStore组合器
**职责：**
- 组合所有子Store
- 提供向后兼容的API
- 管理全局状态（isPaused, isCancelled）
- 初始化和清理

**向后兼容API：**
```javascript
// 属性代理
uploadQueue -> queueStore.uploadQueue
activeUploads -> queueStore.activeUploads
refreshTrigger -> queueStore.refreshTrigger
// ...

// 方法代理
handleFileSelect() -> 调用processUploadQueue()
uploadSingleFile() -> 调用fileUploadStore/chunkUploadStore
pauseAll() -> 调用各子Store方法
// ...
```

## 使用方式

### 方式1：通过RootStore使用（推荐）
```javascript
import rootStore from 'pages/document/stores';

// 访问上传核心Store
rootStore.uploadCoreStore.handleFileSelect(files);
rootStore.uploadCoreStore.pauseAll();

// 访问子Store
rootStore.uploadCoreStore.queueStore.clearQueue();
rootStore.uploadCoreStore.transferStore.fetchTransfers();
```

### 方式2：单独导入子Store
```javascript
import { UploadQueueStore, FileUploadStore } from 'pages/document/stores';

const queueStore = new UploadQueueStore(rootStore);
const fileUploadStore = new FileUploadStore(queueStore, rootStore);
```

## 迁移指南

### 旧代码（原UploadCoreStore.js）
```javascript
import uploadCoreStore from './stores/UploadCoreStore';

// 直接使用
uploadCoreStore.handleFileSelect(files);
uploadCoreStore.pauseAll();
```

### 新代码（拆分后）
```javascript
import rootStore from './stores';

// 方式1：通过RootStore访问（推荐）
rootStore.uploadCoreStore.handleFileSelect(files);
rootStore.uploadCoreStore.pauseAll();

// 方式2：如果组件已注入rootStore
const UploadComponent = inject('rootStore')(observer(({ rootStore }) => {
  const handleUpload = () => {
    rootStore.uploadCoreStore.handleFileSelect(files);
  };
}));
```

## 文件大小对比

| 文件 | 拆分前 | 拆分后 |
|------|--------|--------|
| UploadCoreStore.js | ~88KB (2494行) | - |
| core/index.js | - | ~600行 |
| core/queue.js | - | ~250行 |
| core/fileUpload.js | - | ~200行 |
| core/chunkUpload.js | - | ~400行 |
| core/folderUpload.js | - | ~150行 |
| core/md5.js | - | ~200行 |
| core/transfer.js | - | ~150行 |
| **总计** | **88KB (2494行)** | **~1950行** |

## 注意事项

1. **向后兼容**：`core/index.js` 提供了与原UploadCoreStore相同的API，旧代码无需修改即可运行
2. **依赖注入**：各子Store通过构造函数接收依赖，便于测试
3. **状态共享**：通过rootStore共享navigationStore等全局状态
4. **内存管理**：destroy()方法统一清理定时器、事件监听、Worker池
5. **并发控制**：队列管理集中在queue.js，避免重复逻辑

## 后续优化建议

1. **TypeScript迁移**：为各Store添加类型定义
2. **单元测试**：为每个子Store编写独立测试
3. **性能优化**：考虑使用MobX的computed优化渲染
4. **代码分割**：大文件上传逻辑可进一步懒加载
