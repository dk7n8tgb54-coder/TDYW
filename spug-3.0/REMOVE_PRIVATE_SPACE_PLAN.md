# 资料库私有空间移除计划

> 目标：删除资料库模块的私有空间（Private Space）相关代码，保留公共空间和党建功能不受影响。
> 私有空间数据库表直接删除，不迁移数据。

---

## 一、不可触碰清单（HARD CONSTRAINTS）

| # | 内容 | 原因 |
|---|------|------|
| H1 | `DocumentSystemFolder` 模型及其 `is_public` 字段 | 党建隔离依赖此模型，`is_public=True` 表示公共空间，`is_public=False` 表示党建空间 |
| H2 | `check_public_space_permission()` 函数 | 公共空间权限校验，移除私有空间后仍需要 |
| H3 | `system_scope_validators.py` 中的党建校验逻辑 | 党建 fail-closed 隔离 |
| H4 | `system_folder_service.py` 中的 `validate_system_folder_context` | 党建上下文校验 |
| H5 | `TenantType.GLOBAL` / `TENANT_TYPE_CHOICES` 中的 GLOBAL 值 | 全局数据（Setting/Alert/AuditLogSequence 等）仍使用 |
| H6 | `DocumentSystemFolder` 相关的所有视图、迁移、前端路由 | 党建功能完整链路 |

---

## 二、执行阶段

### Phase 1：后端视图层 — 删除 is_public 分支（28 个文件）

**原则**：所有 `is_public` 参数保留为接口参数（前端仍在传），但后端不再分支处理，一律走 Public 模型。这样前端可以后续清理，不阻塞后端。

**改动模式**：

| 模式 | 改前 | 改后 |
|------|------|------|
| `get_folder_model(is_public)` | 动态路由 | 直接 `DocumentFolderPublic` |
| `get_file_model(is_public)` | 动态路由 | 直接 `DocumentFilePublic` |
| `if is_public: ... else: ...` | 双分支 | 只保留 public 分支 |
| `if not is_public: ...` | private 分支 | 删除整个 if 块 |

**文件清单**（按 `is_public` 出现次数排序）：

| # | 文件 | is_public 次数 | 改动要点 |
|---|------|---------------|---------|
| 1 | `views/folder/views.py` | 51 | 9 处 if 分支 -> 删 private 分支；模型选择 -> DocumentFolderPublic |
| 2 | `views/file/copy.py` | 49 | 5 处 if 分支 -> 删 private 分支 |
| 3 | `views/folder/download.py` | 31 | 1 处 if 分支 |
| 4 | `views/file/preview.py` | 26 | is_public 参数传递 -> 保留参数但不再分支 |
| 5 | `views/upload/merge.py` | 19 | get_file_model -> DocumentFilePublic |
| 6 | `views/search.py` | 18 | 4 处 if 分支 -> 只搜 Public 表 |
| 7 | `views/upload/validators.py` | 18 | 1 处 if 分支 |
| 8 | `views/folder/copy.py` | 16 | 3 处 if 分支 |
| 9 | `views/disk.py` | 15 | 1 处 if 分支 -> 只统计 Public |
| 10 | `views/upload/direct_merge.py` | 14 | get_file_model -> DocumentFilePublic |
| 11 | `views/file/upload.py` | 13 | get_file_model -> DocumentFilePublic |
| 12 | `views/folder/move.py` | 13 | 1 处 if 分支 |
| 13 | `views/upload/resume_strategies.py` | 10 | get_file_model -> DocumentFilePublic |
| 14 | `views/transfer/list.py` | 10 | 2 处 if 分支 -> 过滤 is_public=True |
| 15 | `views/file/rename.py` | 10 | 1 处 if 分支 |
| 16 | `views/folder/rename.py` | 9 | 1 处 if 分支 |
| 17 | `views/file/download.py` | 8 | 模型选择 |
| 18 | `views/folder/properties.py` | 8 | 模型选择 |
| 19 | `views/upload/resume.py` | 8 | get_file_model -> DocumentFilePublic |
| 20 | `views/file/views.py` | 7 | 模型选择 |
| 21 | `views/upload/chunk.py` | 6 | get_file_model -> DocumentFilePublic |
| 22 | `views/upload/chunk_checker.py` | 5 | 模型选择 |
| 23 | `views/upload/lock.py` | 3 | 1 处 if 分支 |
| 24 | `views/transfer/transfer_manager.py` | 3 | is_public 传递 |
| 25 | `views/transfer/create.py` | 3 | is_public 传递 |
| 26 | `views/transfer/cancel.py` | 2 | is_public 传递 |
| 27 | `views/system_folder.py` | 1 | ⚠️ 检查是否涉及党建，如果是则不改 |
| 28 | `views/file/move.py` | 17 | 1 处 if 分支 |

**验证检查点**：
```bash
# 语法检查（在容器内）
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python -m py_compile apps/document/views/folder/views.py
# Django check
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check
```

---

### Phase 2：后端服务层 — 删除 is_public 分支（7 个文件）

| # | 文件 | is_public 次数 | 改动要点 |
|---|------|---------------|---------|
| 1 | `services/system_scope_validators.py` | 30 | ⚠️ 检查是否涉及党建校验，党建部分保留 |
| 2 | `services/folder_copy_service.py` | 20 | 删除 is_public 参数，FileCopier/FolderCopier 只用 Public 模型 |
| 3 | `services/file_upload_service.py` | 16 | 删除 is_public 传递 |
| 4 | `services/cleanup_service.py` | 13 | 2 处 if 分支 -> 只清理 Public |
| 5 | `services/conflict_service.py` | 10 | 1 处 if 分支 |
| 6 | `services/merge_orchestrator.py` | 4 | 删除 is_public 传递 |
| 7 | `services/system_folder_service.py` | 2 | ⚠️ 检查是否涉及党建，党建部分保留 |

**验证检查点**：
```bash
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check
```

---

### Phase 3：后端任务层 — 删除 is_public 分支（7 个文件）

| # | 文件 | is_public 次数 | 改动要点 |
|---|------|---------------|---------|
| 1 | `tasks/merge.py` | 19 | get_models -> 直接 DocumentFilePublic |
| 2 | `tasks/async_copy.py` | 18 | 2 处 if 分支 -> 只用 Public |
| 3 | `tasks/pack.py` | 11 | 5 处三元表达式 -> DocumentFolderPublic |
| 4 | `tasks/thumbnail.py` | 6 | get_file_model -> DocumentFilePublic |
| 5 | `tasks/cleanup/base.py` | 3 | is_public 传递 |
| 6 | `tasks/cleanup/orphan_transfers.py` | 2 | 读取 transfer.is_public |
| 7 | `tasks/batch/cleanup.py` | 2 | 读取 transfer.is_public |

**验证检查点**：
```bash
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check
```

---

### Phase 4：后端 Libs 层 — 删除路由基础设施和 Private 引用

| # | 文件 | 改动要点 |
|---|------|---------|
| 1 | `libs/document_utils.py` | 删除 `get_folder_model()`、`get_file_model()`、`_ensure_models_loaded()`、`_get_models()`、`create_model_instance()` 中的 Private 分支；`get_document_relative_path()` 删除 private 路径分支；`get_chunk_dir_path()` 删除 private 路径分支 |
| 2 | `libs/permission_utils.py` | 删除 `DocumentFolderPrivate`/`DocumentFilePrivate` import；`check_folder_permission()` 删除 isinstance Private 分支；`check_file_permission()` 同理；`get_folder_stats_optimized()` 删除 private 分支 |
| 3 | `libs/document_decorators.py` | `document_permission_check()` 删除 is_public 分支，只保留公共空间权限校验路径 |
| 4 | `libs/chunk_cache.py` | 删除 `space = 'public' if self.is_public else f'user_{self.user_id}'` 分支，统一用 `'public'` |
| 5 | `libs/preview_token.py` | `is_public` 标志位保留（preview_token 编码格式不变，避免破坏已有 token），但生成时始终传 True |
| 6 | `libs/pack_task_ownership.py` | is_public 参数保留但始终传 True |
| 7 | `libs/view_utils.py` | `check_public_space_permission()` **保留不动** |

**验证检查点**：
```bash
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check
# 确认无 DocumentFilePrivate / DocumentFolderPrivate import 残留
grep -rn "DocumentFilePrivate\|DocumentFolderPrivate" apps/document/ --include="*.py" | grep -v migrations | grep -v __pycache__
```

---

### Phase 5：后端模型层 — 删除 Private 模型 + 清理 DocumentTransfer.is_public

**文件**：`models.py`

| 改动 | 详情 |
|------|------|
| 删除 `DocumentFolderPrivate` 类 | L171-206 |
| 删除 `DocumentFilePrivate` 类 | L209-322 |
| 删除 `TenantType.PRIVATE` | L27 |
| 删除 `TENANT_TYPE_CHOICES` 中 `('PRIVATE', '私有表')` | L20 |
| `DocumentTransfer.is_public` 字段 | 改为 `default=True` 并保留（避免迁移），后续清理 |
| `DocumentTransfer` 索引 `idx_transfer_user_scope` | 如包含 is_public，保留不动 |
| `DocumentSystemFolder.is_public` | **不动**（H1 约束） |

**验证检查点**：
```bash
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check
```

---

### Phase 6：常量层清理

**文件**：`constants.py`

| 改动 | 详情 |
|------|------|
| `SpaceType` 枚举 | 删除 `PRIVATE = "PRIVATE"`，保留 `PUBLIC = "PUBLIC"` |
| 搜索 `SpaceType.PRIVATE` 引用 | 全部删除或替换 |

---

### Phase 7：数据库迁移 — 删除 Private 表

```bash
# 生成迁移（指定 app）
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py makemigrations document
```

**预期迁移内容**：
- `DeleteModel` DocumentFolderPrivate
- `DeleteModel` DocumentFilePrivate
- 如有 `SpaceType.PRIVATE` 删除导致的 enum 变更

**⚠️ 注意**：
- 迁移文件生成后必须人工检查内容，确认没有误删 Public 或 SystemFolder 相关操作
- 执行前备份 dev 库（`mysqldump spug > /tmp/spug_backup.sql`）
- 此迁移不可逆（用户明确要求直接删除表，不迁移数据）

**验证检查点**：
```bash
# 检查迁移内容
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py sqlmigrate document <migration_number>
# 执行迁移
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py migrate document
# Django check
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check
```

---

### Phase 8：前端清理（21 个文件 + 5 个导航/树文件）

#### 8.1 导航和空间切换（核心改动）

| # | 文件 | 改动要点 |
|---|------|---------|
| 1 | `stores/navigation/actions.js` | 删除 `switchToPrivate()` (L167)、`toggleSpace()` (L174)；`selectRootFolder()` 删除 isPublic 参数，始终走 public |
| 2 | `FolderTree.js` | 删除 `private-root` 虚拟节点 (L244-248)、`privateRoot` 对象 (L260)、`styles.privateRoot` 引用；`isPublic` 状态删除，始终为 true |
| 3 | `FolderTree.module.less` | 删除 `.privateRoot` CSS 类 (L181) |
| 4 | `utils/keyUtils.js` | 删除 `private-root` key 判断 (L22, L39) |
| 5 | `Explorer/utils.js` | 删除 `// 私有空间：始终可以编辑` 注释及关联逻辑 (L30) |

#### 8.2 API 参数清理（is_public 参数可以保留也可以删除）

**策略**：后端 Phase 1 已保留 `is_public` 接口参数（不再分支），前端可以：
- **最小改动**：保留 `is_public: true` 传递（后端忽略），只删 private 切换 UI
- **完整清理**：删除所有 `is_public` 参数传递

**建议先做最小改动**，验证功能正常后再做完整清理。

#### 8.3 上传链路（如选完整清理）

| # | 文件 | 改动要点 |
|---|------|---------|
| 1 | `stores/upload/core/chunkUpload.js` | 删除 `is_public` formData.append (L343)、`is_public` 参数传递 (L78, L545) |
| 2 | `stores/upload/core/fileUpload.js` | 删除 `is_public` formData.append (L91)、参数传递 (L45) |
| 3 | `stores/upload/core/transfer.js` | 删除 `is_public` 参数 (L20, L402) |
| 4 | `stores/upload/core/queue.js` | 删除 `isPublic ? 'public' : 'private'` 哈希后缀 (L68)，统一用 `'public'` |
| 5 | `stores/upload/core/folderUpload.js` | 同上 (L109, L367, L209) |
| 6 | `stores/upload/core/index.js` | 删除 `获取当前空间类型` 注释及逻辑 (L296) |
| 7 | `stores/upload/core/coordinators/FileUploadCoordinator.js` | 删除 is_public 传递 (L128, L213, L317) |
| 8 | `stores/upload/core/controls/ItemOperationController.js` | 删除 is_public 传递 (L161, L189, L199, L230, L266, L420) |
| 9 | `stores/upload/core/folder/FolderStructureBuilder.js` | 删除 is_public 传递 (L199) |

#### 8.4 其他前端文件

| # | 文件 | 改动要点 |
|---|------|---------|
| 1 | `Explorer/hooks/useFileOperations.js` | 13 处 is_public -> 最小改动保留，完整清理删除 |
| 2 | `Explorer/hooks/useDataFetching.js` | 2 处 is_public |
| 3 | `Explorer/index.js` | 1 处 is_public (L308) |
| 4 | `Explorer/components/PropertiesModal.js` | 1 处 is_public |
| 5 | `PreviewModal.js` | 5 处 is_public |
| 6 | `components/PreviewImage.js` | 2 处 is_public |
| 7 | `components/SearchBox.js` | 1 处 is_public |
| 8 | `hooks/useDiskSpace.js` | 1 处 is_public |

**验证检查点**：
```bash
cd spug_web && npm start
# 手动验证：
# 1. 文档管理页面正常加载
# 2. 上传文件成功
# 3. 下载文件成功
# 4. 预览文件成功
# 5. 文件夹 CRUD 正常
# 6. 搜索正常
# 7. 党建工作页面正常加载（H1-H6 约束）
```

---

### Phase 9：测试改写

#### 9.1 回归测试（`tests/regression/`）

| 文件 | 改动要点 |
|------|---------|
| `full/test_full_regression.py` | 删除所有 `is_public=False` 的测试路径；`FullRegressionBase.setUp()` 中 Private 模型创建代码删除 |
| `standard/test_standard_regression.py` | 同上 |
| `quick/test_quick_regression.py` | 同上 |

#### 9.2 前端测试

| 文件 | 改动要点 |
|------|---------|
| `__tests__/partyBuildingFixes.test.js` | ⚠️ 党建测试保留，只删除 private 相关断言 |
| `components/__tests__/FileConflictModal.test.js` | 删除 is_public 分叉测试用例 |
| `stores/upload/core/__tests__/conflictResolution.test.js` | 同上 |
| `stores/upload/core/__tests__/targetContext.test.js` | 删除私有空间测试用例 (L9, L98, L105) |
| `Explorer/hooks/__tests__/renameNotifications.test.js` | 删除 is_public 分叉 |
| `Explorer/hooks/__tests__/createFolderNotifications.test.js` | 同上 |

**验证检查点**：
```bash
# 后端回归测试
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py test apps.document.tests.regression --keepdb --noinput
```

---

### Phase 10：全局扫描确认

```bash
# 后端：确认无 Private 残留（排除 migrations 和 __pycache__）
grep -rn "DocumentFilePrivate\|DocumentFolderPrivate\|SpaceType.PRIVATE\|TenantType.PRIVATE" apps/document/ --include="*.py" | grep -v migrations | grep -v __pycache__
# 预期输出：空

# 后端：确认 is_public 分支已清理（排除 migrations 和测试）
grep -rn "if.*is_public\|if not is_public" apps/document/ --include="*.py" | grep -v migrations | grep -v __pycache__ | grep -v test
# 预期输出：空（或仅剩 DocumentSystemFolder 相关）

# 前端：确认无 private 残留
grep -rn "private\|Private\|私有" spug_web/src/pages/document/ --include="*.js" | grep -v node_modules | grep -v __tests__ | grep -v JSDoc
# 预期输出：空（或仅剩 JSDoc @private 注释）
```

---

## 三、执行顺序与依赖关系

```
Phase 1 (视图层) ─┐
Phase 2 (服务层) ─┼─> Phase 4 (Libs) ─> Phase 5 (模型) ─> Phase 6 (常量) ─> Phase 7 (迁移)
Phase 3 (任务层) ─┘                                                                    │
                                                                                        ▼
                                                                Phase 8 (前端) ─> Phase 9 (测试) ─> Phase 10 (扫描)
```

- Phase 1/2/3 可并行（互不依赖）
- Phase 4 依赖 1/2/3（视图/服务/任务不再调用 get_folder_model 等）
- Phase 5 依赖 4（libs 不再 import Private 模型）
- Phase 7 依赖 5/6（模型和常量已清理）
- Phase 8 可与 Phase 1-7 并行（前端独立）
- Phase 9 依赖 1-8 全部完成
- Phase 10 是最终确认

---

## 四、风险与缓解

| 风险 | 严重度 | 缓解措施 |
|------|--------|---------|
| 误删 DocumentSystemFolder.is_public | P0 | 不可触碰清单 H1-H6 明确标注，每个文件改动时检查 |
| preview_token 编码格式变更导致已有 token 失效 | P1 | Phase 4 中 preview_token 保留 is_public 标志位，只改生成时传 True |
| 迁移误删 Public 表 | P0 | Phase 7 人工检查 sqlmigrate 输出，执行前备份 dev 库 |
| 前端 is_public 参数删除导致后端报错 | P2 | 后端保留 is_public 接口参数（忽略不报错），前端可分批清理 |
| 回归测试遗漏 Private 路径删除 | P1 | Phase 9 统一处理，Phase 10 grep 确认 |

---

## 五、预期净变化

| 指标 | 估算 |
|------|------|
| 删除代码行数 | ~748 行（后端）+ ~200 行（前端） |
| 新增代码行数 | ~0（迁移文件除外） |
| 删除文件 | 0（不删文件，只删代码块） |
| 删除数据库表 | 2（tdyw_document_file_private, tdyw_document_folder_private） |
| 删除模型 | 2（DocumentFilePrivate, DocumentFolderPrivate） |
| 修改文件数 | 后端 ~45 个 + 前端 ~26 个 |
