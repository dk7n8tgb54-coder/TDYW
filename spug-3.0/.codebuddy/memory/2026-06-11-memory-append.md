
## 安全审计补漏（5 项，全部完成）

### 背景
用户在 H-1/H-2/M-1/M-2 安全审计基础上，继续审查发现 4 处补漏 + 1 处死代码：
1. transfer_id 进入分片路径前没做归属校验（IDOR）
2. health/.* 排除规则误伤详细健康检查接口
3. middleware 仍接受 GET x-token 兜底
4. 打包任务归属只存在于 Celery result，pending 阶段无校验
5. merge_orchestrator.py 是死代码

### 修复 1：transfer_id 路径/缓存归属校验（H-3）
- 新增 `validators.py:TransferOwnershipValidator.validate(transfer_id, file_hash, is_public, user)`
  - 不存在/跨用户/跨租户/哈希不一致/空间类型不一致 全部拒绝
  - 管理员跳过；transfer_id 为 None 跳过
- `chunk.py`：使用 transfer_id 路径前调用 `TransferOwnershipValidator.validate`
- `resume.py`：`_get_chunk_dir` / `_check_can_merge` / `_extract_error_code` 全部接入
  - 失败时 `_get_chunk_dir` 降级为不返回目录（不允许猜别人的 transfer_id）

### 修复 2：settings.py 缩小 health 排除范围（H-4）
- `/document/health/.*` / `/api/document/health/.*` 改为精确匹配：
  - `/document/health/$`
  - `/document/health/celery/$`
  - `/api/document/health/$`
  - `/api/document/health/celery/$`
- 详细接口（db_pool/db_metrics）现在被认证保护（之前被排除中间件误伤）

### 修复 3：middleware 预览端点禁止 GET x-token（H-5）
- `middleware.py:AuthenticationMiddleware.process_request()`
  - 预览/文本内容端点的 GET 请求只从 header 读 x-token，禁止 URL 参数
  - URL 中出现 x-token 直接 401 + 警告日志
  - 防止长期 token 出现在 nginx/浏览器/Referer 日志

### 修复 4：打包任务归属服务侧持久化（H-6）
- 新增 `spug_api/apps/document/libs/pack_task_ownership.py`：
  - `record_ownership(task_id, user_id, tenant_id, is_public)` 写入 Django cache（24h）
  - `verify_ownership(task_id, request_user)` 校验
  - 公共空间任何登录用户可访问，私有空间 user_id+tenant_id 双匹配
- `download.py:_submit_async_pack_task` 提交任务后立即记录 ownership
- `FolderDownloadStatusView.get`：所有状态（含 pending）都校验 ownership
- `FolderDownloadReadyView.get`：ready 下载前也校验
- ready 阶段 result 归属校验作为第二道防线（cache 过期场景）

### 修复 5：merge_orchestrator.py 死代码处理
- `git log` 确认 `MergeOrchestrator` 没有任何外部 import 引用
- 顶部加 `【DEPRECATED】` 注释，建议下轮清理删除
- 顺手补 `save_task_id_to_transfer(..., user=context.request.user)` 防御性修正

### 修改文件（8 个 + 1 新增）
- `spug_api/apps/document/views/upload/validators.py`
- `spug_api/apps/document/views/upload/chunk.py`
- `spug_api/apps/document/views/upload/resume.py`
- `spug_api/spug/settings.py`
- `spug_api/libs/middleware.py`
- `spug_api/apps/document/views/folder/download.py`
- `spug_api/apps/document/services/merge_orchestrator.py`
- (新增) `spug_api/apps/document/libs/pack_task_ownership.py`

### Post-Write Verification（全部通过）
- **Lint**：本次修改未引入新 ERROR（pre-existing 9 个 settings.py 常量重定义与本次无关）
- **py_compile**（Docker）：8 个文件全部 OK
- **专项测试脚本**（Docker 内执行，已清理）：
  - A. TransferOwnershipValidator: 9/9 通过（覆盖 9 个场景：不存在/跨用户/跨租户/公共空间跨用户/哈希不一致/空间不一致/合法/管理员/None）
  - B. pack_task_ownership: 6/6 通过（覆盖 6 个场景）
  - C. middleware 预览端点: 2/2 通过
  - D. settings 健康检查排除: 10/10 通过（精确匹配 + 不再误伤 db_pool/db_metrics）
  - **总计 27/27 通过**
- **Mock 注意**：第一次写测试时 A2/A4 错误消息断言写错（以为是"归属"，实际代码返回"无权"），已修正后全部通过
