# Document 模块 Views 迁移测试验证计划

## 测试概述

**测试目标**: 验证 views.py 拆分迁移后的所有功能正常工作
**测试范围**: Document 模块所有 API 接口和功能
**测试环境**: Windows + Docker/MySQL
**预计时间**: 约 1-2 小时

---

## 一、语法和导入测试

### 1.1 Python 语法检查 ✅
- [x] 所有 views/ 子模块语法正确 ✅ (9个文件全部通过)
- [x] urls.py 语法正确 ✅
- [x] __init__.py 导出完整 ✅

**测试结果**: 2026-03-13 全部通过

### 1.2 导入链测试 ✅
- [x] 独立导入每个子模块 ✅
  - base.py: 10个工具函数 ✅
  - cleanup.py: cleanup_old_chunks ✅
  - disk.py: DiskUsageView ✅
  - search.py: FolderSearchView ✅
  - transfer.py: 12个Transfer View ✅
  - upload.py: 4个Upload View + MergeLock ✅
  - folder.py: 5个Folder View ✅
  - file.py: 7个File View ✅
- [x] 通过 __init__.py 统一导入 ✅ (28个导出项)
- [x] urls.py 导入所有 View 类 ✅ (31个View类全部匹配)

**测试结果**: 2026-03-13 全部通过

---

## 二、静态代码分析（无需运行服务）

### 2.1 代码一致性验证 ✅

| 文件 | View类数量 | 状态 |
|------|-----------|------|
| views_original.py (原始) | 31 | ✅ 基准 |
| transfer.py | 13 | ✅ 匹配 |
| folder.py | 5 | ✅ 匹配 |
| file.py | 7 | ✅ 匹配 |
| upload.py | 4 | ✅ 匹配 |
| disk.py | 1 | ✅ 匹配 |
| search.py | 1 | ✅ 匹配 |
| **总计** | **31** | **✅ 完整** |

### 2.2 View 类分布验证 ✅

| 模块 | View 类 | 数量 |
|------|---------|------|
| **transfer.py** | TransferListView, TransferCreateView, TransferProgressUpdateView, TransferCompleteView, TransferCancelView, TransferStatusUpdateView, TransferDeleteView, TransferHashUpdateView, TransferFailView, TransferBatchPauseView, TransferBatchResumeView, TransferBatchCancelView, TransferBatchDeleteView | 13 |
| **folder.py** | FolderView, FolderCopyView, FolderMoveView, FolderDownloadView, FolderRenameView | 5 |
| **file.py** | FileView, FileUploadView, FileDownloadView, FilePreviewView, FileCopyView, FileMoveView, FileRenameView | 7 |
| **upload.py** | FileChunkUploadView, FileMergeChunksView, CheckUploadedChunksView, FileMergeStatusView | 4 |
| **disk.py** | DiskUsageView | 1 |
| **search.py** | FolderSearchView | 1 |
| **合计** | | **31** |

### 2.3 URL 路由验证 ✅

| URL 路径 | View 类 | 状态 |
|----------|---------|------|
| /folder/ | FolderView | ✅ |
| /folder/search/ | FolderSearchView | ✅ |
| /file/ | FileView | ✅ |
| /upload/ | FileUploadView | ✅ |
| /upload_chunk/ | FileChunkUploadView | ✅ |
| /merge_chunks/ | FileMergeChunksView | ✅ |
| /merge_status/ | FileMergeStatusView | ✅ |
| /check_uploaded_chunks/ | CheckUploadedChunksView | ✅ |
| /disk_usage/ | DiskUsageView | ✅ |
| /download/ | FileDownloadView | ✅ |
| /folder/download/ | FolderDownloadView | ✅ |
| /preview/ | FilePreviewView | ✅ |
| /file/copy/ | FileCopyView | ✅ |
| /folder/copy/ | FolderCopyView | ✅ |
| /file/move/ | FileMoveView | ✅ |
| /folder/move/ | FolderMoveView | ✅ |
| /file/rename/ | FileRenameView | ✅ |
| /folder/rename/ | FolderRenameView | ✅ |
| /transfers/ | TransferListView | ✅ |
| /transfers/create/ | TransferCreateView | ✅ |
| /transfers/<id>/progress/ | TransferProgressUpdateView | ✅ |
| /transfers/<id>/complete/ | TransferCompleteView | ✅ |
| /transfers/<id>/cancel/ | TransferCancelView | ✅ |
| /transfers/<id>/status/ | TransferStatusUpdateView | ✅ |
| /transfers/<id>/delete/ | TransferDeleteView | ✅ |
| /transfers/<id>/fail/ | TransferFailView | ✅ |
| /transfers/<id>/update_hash/ | TransferHashUpdateView | ✅ |
| /transfers/batch/pause/ | TransferBatchPauseView | ✅ |
| /transfers/batch/resume/ | TransferBatchResumeView | ✅ |
| /transfers/batch/cancel/ | TransferBatchCancelView | ✅ |
| /transfers/batch/delete/ | TransferBatchDeleteView | ✅ |

**总计: 43 个 URL 路由全部验证通过** ✅

---

## 三、单元测试（需要 Django 环境）

### 3.1 工具函数测试 ⏳
- [ ] format_file_size 格式化正确
- [ ] validate_file_name 校验正确
- [ ] get_mime_type 返回正确类型
- [ ] check_public_space_permission 权限检查正确

### 3.2 模型和常量测试 ⏳
- [ ] DocumentTransfer 模型可导入
- [ ] TransferStatus 枚举可导入
- [ ] 所有常量定义正确

---

## 三、集成测试（需要运行服务）

### 3.1 文件夹管理测试 (Folder Views)

#### 3.1.1 FolderView - 获取列表
```bash
# 获取根文件夹列表
GET /api/document/folder/

# 获取子文件夹
GET /api/document/folder/?parent_id=1

# 公共空间
GET /api/document/folder/?is_public=true
```
- [ ] 返回文件夹列表
- [ ] 返回文件列表
- [ ] 租户隔离正确

#### 3.1.2 FolderView - 创建文件夹
```bash
POST /api/document/folder/
{
  "name": "测试文件夹",
  "parent_id": null,
  "is_public": false
}
```
- [ ] 创建成功
- [ ] 同名检查有效
- [ ] 公共空间权限检查

#### 3.1.3 FolderView - 删除文件夹
```bash
DELETE /api/document/folder/
{
  "id": 1
}
```
- [ ] 删除成功
- [ ] 递归删除子文件夹
- [ ] 物理文件清理

#### 3.1.4 FolderCopyView - 复制文件夹
```bash
POST /api/document/folder/copy/
{
  "source_id": 1,
  "target_id": 2,
  "is_public": false
}
```
- [ ] 复制成功
- [ ] 子文件夹和文件一并复制
- [ ] 租户隔离正确

#### 3.1.5 FolderMoveView - 移动文件夹
```bash
POST /api/document/folder/move/
{
  "source_id": 1,
  "target_id": 2
}
```
- [ ] 移动成功
- [ ] 循环移动检查
- [ ] 权限检查

#### 3.1.6 FolderRenameView - 重命名文件夹
```bash
POST /api/document/folder/rename/
{
  "id": 1,
  "name": "新名称"
}
```
- [ ] 重命名成功
- [ ] 同名检查

#### 3.1.7 FolderDownloadView - 下载文件夹
```bash
GET /api/document/folder/download/?id=1
```
- [ ] ZIP 下载成功
- [ ] 包含所有子文件

---

### 3.2 文件管理测试 (File Views)

#### 3.2.1 FileView - 删除文件
```bash
DELETE /api/document/file/
{
  "id": 1
}
```
- [ ] 删除成功
- [ ] 物理文件清理

#### 3.2.2 FileUploadView - 普通上传
```bash
POST /api/document/upload/
Content-Type: multipart/form-data

file: [二进制文件]
folder_id: 1
is_public: false
```
- [ ] 小文件上传成功 (<5MB)
- [ ] 文件名验证
- [ ] 文件大小限制检查

#### 3.2.3 FileDownloadView - 下载文件
```bash
GET /api/document/download/?id=1
```
- [ ] 下载成功
- [ ] 文件名正确
- [ ] Content-Type 正确

#### 3.2.4 FilePreviewView - 预览文件
```bash
GET /api/document/preview/?id=1
```
- [ ] 图片预览 (jpg, png)
- [ ] PDF 预览
- [ ] 视频预览 (mp4)
- [ ] 不支持类型返回 415

#### 3.2.5 FileCopyView - 复制文件
```bash
POST /api/document/file/copy/
{
  "source_id": 1,
  "target_folder_id": 2
}
```
- [ ] 复制成功
- [ ] 物理文件复制

#### 3.2.6 FileMoveView - 移动文件
```bash
POST /api/document/file/move/
{
  "source_id": 1,
  "target_folder_id": 2
}
```
- [ ] 移动成功
- [ ] 物理文件移动

#### 3.2.7 FileRenameView - 重命名文件
```bash
POST /api/document/file/rename/
{
  "id": 1,
  "name": "新文件名.txt"
}
```
- [ ] 重命名成功
- [ ] display_name 更新

---

### 3.3 分片上传测试 (Upload Views)

#### 3.3.1 FileChunkUploadView - 分片上传
```bash
POST /api/document/upload_chunk/
Content-Type: multipart/form-data

file: [分片数据]
chunk_index: 0
total_chunks: 5
file_hash: "md5_hash"
transfer_id: 1
```
- [ ] 分片上传成功
- [ ] 断点续传正常
- [ ] 分片存储路径正确

#### 3.3.2 CheckUploadedChunksView - 检查已上传分片
```bash
GET /api/document/check_uploaded_chunks/?transfer_id=1
```
- [ ] 返回已上传分片列表
- [ ] 断点续传信息正确

#### 3.3.3 FileMergeChunksView - 合并分片
```bash
POST /api/document/merge_chunks/
{
  "transfer_id": 1,
  "file_hash": "md5_hash"
}
```
- [ ] 合并任务创建成功
- [ ] 异步合并执行
- [ ] MD5 校验正确

#### 3.3.4 FileMergeStatusView - 查询合并状态
```bash
GET /api/document/merge_status/?transfer_id=1
```
- [ ] 返回 pending/merging/completed/failed
- [ ] 状态更新正确

#### 3.3.5 完整大文件上传流程
```
1. 创建传输记录
2. 上传所有分片
3. 触发合并
4. 轮询合并状态
5. 合并完成，文件可用
```
- [ ] 大于 5MB 的文件上传成功
- [ ] 大于 100MB 的文件上传成功
- [ ] 断点续传功能正常

---

### 3.4 传输管理测试 (Transfer Views)

#### 3.4.1 TransferListView - 获取传输列表
```bash
GET /api/document/transfers/
GET /api/document/transfers/?status=PENDING
GET /api/document/transfers/?is_public=true
```
- [ ] 返回传输列表
- [ ] 状态筛选有效
- [ ] 公共空间筛选有效

#### 3.4.2 TransferCreateView - 创建传输记录
```bash
POST /api/document/transfers/create/
{
  "transfer_type": "UPLOAD",
  "file_name": "test.txt",
  "file_size": 1024,
  "file_hash": "md5_hash",
  "folder_id": 1,
  "is_public": false,
  "total_chunks": 5
}
```
- [ ] 创建成功
- [ ] 返回 transfer_id

#### 3.4.3 TransferProgressUpdateView - 更新进度
```bash
POST /api/document/transfers/1/progress/
{
  "chunk_index": 0,
  "transferred_size": 1024
}
```
- [ ] 进度更新成功

#### 3.4.4 TransferCompleteView - 完成传输
```bash
POST /api/document/transfers/1/complete/
```
- [ ] 标记完成成功

#### 3.4.5 TransferCancelView - 取消传输
```bash
POST /api/document/transfers/1/cancel/
```
- [ ] 取消成功
- [ ] 清理分片文件

#### 3.4.6 批量操作测试
```bash
# 批量暂停
POST /api/document/transfers/batch/pause/
{"ids": [1, 2, 3]}

# 批量恢复
POST /api/document/transfers/batch/resume/
{"ids": [1, 2, 3]}

# 批量取消
POST /api/document/transfers/batch/cancel/
{"ids": [1, 2, 3]}

# 批量删除
POST /api/document/transfers/batch/delete/
{"ids": [1, 2, 3]}
```
- [ ] 批量暂停成功
- [ ] 批量恢复成功
- [ ] 批量取消成功
- [ ] 批量删除成功

---

### 3.5 搜索功能测试 (Search View)

#### 3.5.1 FolderSearchView - 搜索
```bash
GET /api/document/folder/search/?keyword=测试
GET /api/document/folder/search/?keyword=测试&folder_id=1
GET /api/document/folder/search/?keyword=测试&is_public=true
```
- [ ] 文件夹搜索结果正确
- [ ] 文件搜索结果正确
- [ ] 递归搜索有效
- [ ] 公共空间搜索有效

---

### 3.6 磁盘使用测试 (Disk View)

#### 3.6.1 DiskUsageView - 磁盘使用
```bash
GET /api/document/disk_usage/
```
- [ ] 返回磁盘使用信息
- [ ] 已用空间计算正确
- [ ] 剩余空间计算正确

---

### 3.7 公共空间权限测试

#### 3.7.1 公共空间写入权限
- [ ] 普通用户不能写入公共空间
- [ ] 管理员可以写入公共空间
- [ ] 创建者可以修改自己创建的内容

#### 3.7.2 公共空间读取权限
- [ ] 所有用户可以读取公共空间
- [ ] 私有空间租户隔离

---

## 四、管理命令测试

### 4.1 cleanup_chunks 命令
```bash
docker exec -it spug_api python manage.py cleanup_chunks
```
- [ ] 命令执行成功
- [ ] 过期分片被清理
- [ ] 日志输出正确

---

## 五、性能测试（可选）

### 5.1 并发上传测试
- [ ] 10个并发上传正常
- [ ] 无死锁或竞争条件

### 5.2 大文件测试
- [ ] 500MB 文件上传成功
- [ ] 1GB 文件上传成功
- [ ] 内存使用稳定

---

## 六、测试执行指南

### 6.1 Windows 快速测试（无需 Docker）

```bash
# 运行批处理脚本
cd e:/TDYW/spug-3.0
run_migration_tests.bat
```

### 6.2 Docker 完整测试（推荐）

```bash
# 1. 启动容器
docker-compose up -d

# 2. 执行验证测试
docker exec -it spug_api python tests/test_views_migration.py

# 3. 运行 Django 测试
docker exec -it spug_api python manage.py test apps.document --verbosity=2
```

### 6.3 手动 API 测试

使用 Postman 或 curl 测试各个接口：

```bash
# 获取 Token
TOKEN=$(curl -s -X POST http://localhost:9000/api/account/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r '.token')

# 测试文件夹列表
curl -H "Authorization: Token $TOKEN" \
  http://localhost:9000/api/document/folder/

# 测试磁盘使用
curl -H "Authorization: Token $TOKEN" \
  http://localhost:9000/api/document/disk_usage/
```

---

## 七、测试执行记录

### 测试日期: 2026-03-13

| 测试项 | 静态检查 | 单元测试 | 集成测试 | 备注 |
|--------|----------|----------|----------|------|
| **语法检查** | ✅ | - | - | 9个文件全部通过 |
| **导入链测试** | ✅ | ⏳ | - | 31个View类全部可导入 |
| **代码一致性** | ✅ | - | - | 原始31个 = 迁移后31个 |
| **URL路由验证** | ✅ | - | - | 43个路由全部匹配 |
| **工具函数测试** | - | ⏳ | - | 待Docker环境 |
| **文件夹CRUD** | - | - | ⏳ | 需手动测试 |
| **文件上传/下载** | - | - | ⏳ | 需手动测试 |
| **分片上传** | - | - | ⏳ | 需手动测试 |
| **传输管理** | - | - | ⏳ | 需手动测试 |
| **搜索功能** | - | - | ⏳ | 需手动测试 |
| **磁盘使用** | - | - | ⏳ | 需手动测试 |
| **公共空间权限** | - | - | ⏳ | 需手动测试 |
| **管理命令** | - | - | ⏳ | 需Docker环境 |

**图例**: ✅ 通过 | ⏳ 待执行 | ❌ 失败 | ⬜ 未开始

---

### 静态检查详细结果

| 检查项 | 期望值 | 实际值 | 状态 |
|--------|--------|--------|------|
| base.py 语法 | 通过 | 通过 | ✅ |
| cleanup.py 语法 | 通过 | 通过 | ✅ |
| disk.py 语法 | 通过 | 通过 | ✅ |
| search.py 语法 | 通过 | 通过 | ✅ |
| transfer.py 语法 | 通过 | 通过 | ✅ |
| upload.py 语法 | 通过 | 通过 | ✅ |
| folder.py 语法 | 通过 | 通过 | ✅ |
| file.py 语法 | 通过 | 通过 | ✅ |
| __init__.py 语法 | 通过 | 通过 | ✅ |
| urls.py 语法 | 通过 | 通过 | ✅ |
| 原始 View 类数 | 31 | 31 | ✅ |
| 迁移后 View 类数 | 31 | 31 | ✅ |
| URL 路由数 | 43 | 43 | ✅ |

**测试人员**: AI Agent
**静态检查结果**: ✅ 全部通过
**待执行任务**: Docker环境单元测试 + 手动API测试

---

## 七、问题记录

| 序号 | 问题描述 | 严重程度 | 状态 |
|------|----------|----------|------|
| 1 | | | |
| 2 | | | |
| 3 | | | |

---

**备注**: 本测试计划应在测试环境执行，确认无误后再部署到生产环境。
