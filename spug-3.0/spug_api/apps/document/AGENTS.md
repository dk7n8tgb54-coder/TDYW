# apps/document/AGENTS.md - 资料库模块后端规则

> 本文件仅记录资料库模块**独有**的、不能放在 `spug_api/AGENTS.md` 上层的规则。通用后端规则见上层文件。

---

## 一、模型架构

### 双表设计（Public/Private）

资料库使用 Public/Private 双表设计实现租户隔离：

| 模型 | 租户类型 | 用途 |
|---|---|---|
| `DocumentFolderPrivate` | PRIVATE | 租户私有文件夹 |
| `DocumentFolderPublic` | PUBLIC | 公共文件夹 |
| `DocumentFilePrivate` | PRIVATE | 租户私有文件 |
| `DocumentFilePublic` | PUBLIC | 公共文件 |
| `DocumentTransfer` | PRIVATE | 传输记录（上传/下载/复制） |
| `DocumentSystemFolder` | GLOBAL | 党建系统文件夹（无租户隔离） |

### Mixin 继承

```
FolderPathMixin          # get_full_path() 迭代实现 + 循环引用/深度保护
UniqueKeyMixin           # save() 自动计算 unique_key，update_fields 自动补 unique_key
FolderDeleteMixin        # 文件夹物理删除
DocumentFileDeleteMixin  # 文件物理删除 + 缩略图清理 + is_pending_clean 兜底
```

### 关键约束

1. **`unique_key` 自动计算**：`UniqueKeyMixin.save()` 自动调用 `_compute_unique_key()`，子类必须实现此方法。使用 `update_fields` 时自动补入 `unique_key`。
2. **`get_full_path()` 有深度保护**：最大深度 `DEFAULT_MAX_FOLDER_DEPTH=100`，检测循环引用。
3. **逻辑删除已移除**：2026-06-23 起删除改为直接物理删除，模型层保留 `is_deleted`/`deleted_at`/`deleted_by` 字段（避免 migration），但不再被业务设置。
4. **`DocumentFileDeleteMixin.delete()`**：先删物理文件 + 缩略图，成功后 `super().delete()`；失败时用 savepoint 保存 `is_pending_clean` 标记并抛出 `DocumentPhysicalDeleteError`。

---

## 二、党建隔离（System Folder）

1. **`DocumentSystemFolder`**：无租户隔离（GLOBAL），用于党建工作文档。
2. **`system_scope_validators`**：fail-closed 设计，未匹配到有效 system_folder 的请求直接拒绝。
3. **HTTP 请求注入**：前端 `libs/systemFolderContext.js` 激活时，`http.js` 自动为 `/api/document/*` 请求注入 `system_folder` 参数（GET->query, POST->body/FormData）。
4. **View 层校验**：所有涉及 system_folder 的 View 必须校验 `system_folder` 参数有效性。
5. **权限编码**：`document.party_building_document.view` 独立于 `document.document.view`。

---

## 三、传输状态机

### 状态定义

```python
class TransferStatus:
    PENDING     # 等待中
    UPLOADING   # 上传中
    DOWNLOADING # 下载中
    COPYING     # 复制中
    PAUSED      # 已暂停
    MERGING     # 合并中
    COMPLETED   # 已完成（终态）
    FAILED      # 已失败（可重试）
    CANCELED    # 已取消（终态）
```

### 状态转换矩阵

```
PENDING     -> UPLOADING, DOWNLOADING, COPYING, PAUSED, CANCELED, COMPLETED, FAILED
UPLOADING   -> PAUSED, MERGING, COMPLETED, FAILED, CANCELED
DOWNLOADING -> PAUSED, COMPLETED, FAILED, CANCELED
PAUSED      -> UPLOADING, DOWNLOADING, COPYING, FAILED, CANCELED
MERGING     -> COMPLETED, FAILED, CANCELED
COPYING     -> PAUSED, COMPLETED, FAILED, CANCELED
COMPLETED   -> (终态)
FAILED      -> UPLOADING, DOWNLOADING, COPYING, CANCELED (允许重试)
CANCELED    -> (终态)
```

### 状态机规则

1. **所有状态变更必须通过 `is_valid_status_transition()` 校验**。
2. **`UPLOADING -> COMPLETED` 已修复**：普通上传（无分片）需要此转换，之前缺失导致小文件上传后端记录卡在 UPLOADING。
3. **合并中（MERGING）保留取消能力**：与取消接口行为一致。
4. **`DirectMergeView` COMPLETED 分支必须验证文件记录存在**：Celery 任务异常可能导致文件记录未创建但传输状态停在 COMPLETED，重试时需重置为 UPLOADING 重新合并。

### 合并相关常量

| 常量 | 值 | 说明 |
|---|---|---|
| `DEFAULT_MERGE_LOCK_TIMEOUT` | 600s | 合并锁超时（10 分钟） |
| `DEFAULT_MERGE_STATUS_TIMEOUT` | 300s | 合并状态查询超时（5 分钟） |
| `DEFAULT_ASYNC_COPY_THRESHOLD` | 50MB | 异步复制阈值 |
| `DEFAULT_CHUNK_CLEANUP_AGE` | 24h | 分片清理时间 |
| `DEFAULT_MAX_FILE_SIZE` | 100MB | 文件大小上限 |

---

## 四、文件上传链

### 分片上传流程

1. **前端计算 MD5**（`calculating` 状态）-> 检查已上传分片 -> 分片上传 -> 合并请求。
2. **断点续传**：`check_uploaded_chunks` 接口返回已上传分片列表，前端跳过已传分片。
3. **合并**：`DirectMergeView` 调用 Celery `merge_chunks` 任务。
4. **合并幂等**：`direct_merge.py` 和 `merge.py` 的 COMPLETED 分支必须验证 `FileModel.objects.filter(...).exists()`，文件不存在时重置状态为 UPLOADING 重新合并。

### 上传链已知风险（已修复）

1. **`ALLOWED_STATUS_TRANSITIONS` 必须包含 `UPLOADING -> COMPLETED`**：小文件无分片合并，前端 `completeTransfer` 直接标记完成，后端状态机必须允许。
2. **`chunkUpload.js` XHR 回调必须检查 `operationVersion`**：过期回调可覆盖新状态。
3. **`mergeChunks` 递归重试必须有深度限制**：缺失 `retryCount`/`retryDepth` 会导致无限递归。

### error 字段一致性

1. **正常状态**（waiting/calculating/uploading/merging）**不应有** error 字段。
2. **错误状态**（error/cancelled）才设置 error 字段。
3. 原因：前端 `TransferItem.js` 双重条件 `status === 'error' && item.error` 防止误显示，但 error 字段会触发 React.memo 重渲染。

---

## 五、文件操作安全

### 物理路径

1. **物理文件路径由 `file_path` 字段存储**，逻辑名（`name`）与物理名可不同。
2. **展示名**（`display_name`）用于前端展示，可为空（回退到 `name`）。
3. **路径拼接禁止目录穿越**：文件名中不允许 `..`。
4. **生产单块机械盘**：`chunks`/`documents`/`media` 同处 `/dev/sdd`，大文件操作需注意 IO 竞争。

### 删除安全

1. **文件夹删除**：递归删除子文件夹和文件，先删物理文件再删数据库记录。
2. **文件删除失败**：标记 `is_pending_clean=True` + `clean_retry_count++` + `last_clean_attempt=now()`，由 Celery `retry_clean_pending_files` 异步重试。
3. **`retry_clean_pending_files` 是 `is_pending_clean` 唯一消费者**，不可删除。
4. **`is_pending_clean` 标记使用 savepoint**：如果外层事务回滚，标记也会被回滚。调用方捕获异常后不应回滚外层事务。

### 移动/复制

1. **跨空间移动**（Private -> Public 或反向）：需要重新计算路径和权限。
2. **异步复制**：文件 >= `DEFAULT_ASYNC_COPY_THRESHOLD`（50MB）时使用 Celery `async_copy_files` 任务。
3. **复制幂等**：基于 `transfer_id` 去重。

---

## 六、Celery 任务

| 任务 | 用途 | 幂等机制 | 注意事项 |
|---|---|---|---|
| `merge_chunks` | 分片合并 | 状态机 + 文件记录验证 | COMPLETED 分支必须验证文件存在 |
| `retry_clean_pending_files` | 清理待删除文件 | `is_pending_clean` 唯一消费者 | 不可删除 |
| `async_copy_files` | 异步复制 | `transfer_id` 去重 | 大文件 IO 竞争 |
| 分片清理 | 清理过期分片 | 时间阈值 `DEFAULT_CHUNK_CLEANUP_AGE` | - |

---

## 七、权限

1. **权限编码**：
   - `document.document.view/edit/delete` - 资料库文档
   - `document.party_building_document.view/edit/delete` - 党建文档
   - `document.regulation.view/edit/delete` - 规章管理
2. **公共空间操作**：`check_public_space_permission(user, space)` 校验。
3. **删除二次确认**：前端 `Modal.confirm` 二次确认，后端不依赖前端确认。
4. **审计日志**：`FILE_DELETE`、`FOLDER_DELETE` 事件。
