# 资料库模块发布前测试报告

> 本报告为资料库（`apps/document` / `pages/document`）模块的上线前质量门禁结论。
> 所有断言均来自真实 HTTP 请求、真实数据库状态与真实文件系统副作用，未使用读取源码字符串的方式代替行为测试。

---

## 1. 测试时间、代码版本与环境

| 项 | 值 |
|---|---|
| 报告日期 | 2026-09-02 |
| 分支 | `tdyw` |
| HEAD | `9b62488e57e01b62f32ea6378863663fb87d5ab4` |
| HEAD 作者 / 时间 | jay choi / 2026-09-02 17:35:59 +0800 |
| HEAD 标题 | 合同协议资料库、无线电管理部分测试代码以及登录界面修改。 |

**后端执行环境**

| 项 | 值 |
|---|---|
| 容器 | `tdyw-test`（镜像 `tdyw:django42-stage2`，路径 `/data/spug/spug_api`） |
| Django / Python | 4.2.30 / 3.10 |
| 数据库 | `db` → 容器 `a45d84978565`（MariaDB 10.8.2，**测试实例**，非 dev 实例 `tdyw-db`） |
| 业务库 | `spug`（**只读引用，未做任何写入/清理/迁移**） |
| 隔离测试库 | `test_spug`（本次全部行为测试在此库执行） |
| `ATOMIC_REQUESTS` | `True`（影响缺陷 DOC-F02 的判定） |
| Celery worker | 8 个进程在 `tdyw-test` 内运行 |
| Redis | 可用（Django cache 连通性验证通过） |
| 文档存储根 | `/data/spug/spug_api/storage/documents` |

**前端 / E2E 执行环境**

| 项 | 值 |
|---|---|
| 被测前端 | `http://localhost:8080`（`tdyw-test` 容器） |
| 前端测试 | `spug_web` + `react-app-rewired test`（jsdom） |
| E2E | Playwright 1.62.1 / chromium，专用测试环境 |
| kkFileView（浏览器） | `/kkfileview` |
| kkFileView（回源） | `http://tdyw-test`（该容器名在 `ALLOWED_HOSTS` 内） |

**未触碰的环境**：`tdyw`（dev 后端）、`tdyw-db`（dev 库）。全程未执行 `flush`、未对业务库执行 `migrate`。

---

## 2. 实际执行的命令（摘要）

```bash
# 执行前检查
git status --short
git --no-pager diff --check
docker ps -a
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check
docker exec ... python manage.py showmigrations document

# 后端行为测试（隔离测试库，--keepdb 复用 test_spug）
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py test \
  apps.document.tests.release_gate.test_public_basics \
  apps.document.tests.release_gate.test_party_building_isolation \
  apps.document.tests.release_gate.test_permissions \
  apps.document.tests.release_gate.test_upload_merge \
  apps.document.tests.release_gate.test_fs_safety \
  apps.document.tests.release_gate.test_download_preview \
  apps.document.tests.release_gate.test_integrity --keepdb

# 干净测试库迁移验证（销毁并重建 test_spug，跑全部迁移）
docker exec ... tdyw-test python manage.py test \
  apps.document.tests.release_gate.test_integrity --noinput

# 前端组件与状态测试
cd spug_web && CI=true npx react-app-rewired test --watchAll=false \
  --testPathPattern="src/pages/document"

# Playwright E2E
cd quality/e2e && E2E_BASE_URL=http://localhost:8080 npx playwright test \
  tests/document_admin/document.spec.js \
  tests/document_admin/party_building.spec.js \
  tests/document_admin/document_release_gate.spec.js --project=chromium --reporter=list

# 既有资料库测试基线
docker exec ... tdyw-test python manage.py test apps.document.tests.test_smoke --keepdb
```

---

## 3. 测试范围与未覆盖范围

### 3.1 已覆盖

- 后端：`apps/document/`（models / views / services / tasks / libs / migrations）
- 前端：`pages/document/`（组件、hook、MobX store、上传子系统）
- 路由与权限关联：`apps/document/urls.py`、`spug_web/src/routes.js`、`libs/http.js`、`libs/systemFolderContext.js`
- 测试：`apps/document/tests/**`、`pages/document/**/__tests__/**`、`quality/e2e/tests/document_admin/{document,party_building}.spec.js`

### 3.2 明确未覆盖 / 不可构造

| 项 | 状态 | 原因 |
|---|---|---|
| E2E 大文件分片（>32MB）与刷新后恢复 | NOT_RUN | 需 >32MB 文件与长等待；后端断点续传接口已行为级覆盖 |
| E2E 无权限账号访问 | NOT_RUN | `.env` 未配置 `E2E_NO_DOC_*`；后端权限矩阵已 26 例覆盖 |
| 跨 `system_folder` 隔离 | NOT_APPLICABLE | `SYSTEM_FOLDER_CODES` 仅含 `party_building_documents`，不存在第二系统目录 |
| kkFileView 真实渲染 | PARTIAL | 仅验证 URL 构造（含 base64 回源地址与 preview_token） |
| 性能压测 / 灾备演练 | NOT_RUN | 不在本次 quick/standard 门禁；禁止指向开发业务库与真实文件目录 |
| `regulation` 规章管理 | 未纳入 | 未发现资料库代码依赖其公共能力（`regulation` 走独立 `storage.py`，资料库走 `apps/evidence` 无关路径） |

---

## 4. 用例统计

| 域 | 用例数 | PASS | FAIL | SKIP |
|---|---:|---:|---:|---:|
| 后端 stable_contract（7 个模块） | 201 | 197 | 3 | 1 |
| 后端干净库迁移验证 | 23 | 23 | 0 | 0 |
| 前端组件与状态 | 487 | 487 | 0 | 0 |
| Playwright E2E | 23 | 23 | 0 | 0 |
| **合计（不含迁移验证子集）** | **711** | **707** | **3** | **1** |

后端分模块明细：

| 模块 | 用例 | PASS | FAIL | SKIP |
|---|---:|---:|---:|---:|
| `test_public_basics.py`（公共资料库） | 34 | 34 | 0 | 0 |
| `test_party_building_isolation.py`（党建隔离） | 34 | 34 | 0 | 0 |
| `test_permissions.py`（权限矩阵） | 26 | 26 | 0 | 0 |
| `test_upload_merge.py`（分片上传/合并/状态机） | 49 | 48 | 1 | 0 |
| `test_fs_safety.py`（文件系统与补偿） | 17 | 14 | 2 | 1 |
| `test_download_preview.py`（下载/预览/令牌） | 18 | 18 | 0 | 0 |
| `test_integrity.py`（完整性/复制移动/审计） | 23 | 23 | 0 | 0 |

**BLOCKED：0；NOT_RUN（已声明）：5 类（见 3.2）**

---

## 5. 按功能域结果

| 功能域 | 结论 | 说明 |
|---|---|---|
| 公共资料库 | PASS | 目录列表/创建/幂等/重命名/删除、文件上传/冲突 4 策略/重命名/删除、搜索、属性统计、递归复制与移动，均验证 DB 与物理文件双侧状态 |
| 党建隔离 | PASS | 34 例覆盖双向隔离、根目录保护、非法/缺失 `system_folder` fail-closed、搜索隔离、物理路径归属 |
| 权限 | PASS | 6 类角色（仅查看 / 可编辑不可删除 / 可删除 / 无权限 / 仅普通 / 仅党建）、对象归属 `not_owner`、传输记录归属、HTTP 200+error 识别 |
| 分片上传 | **FAIL** | 48/49 通过；1 例为合并恢复路径缺陷（DOC-F01）|
| 文件系统 | **FAIL** | 14/17 通过；2 例为删除补偿缺陷（DOC-F02），1 例因前置失败跳过 |
| 复制移动 | PASS | 同 scope 移动/复制、异步阈值 50MB、`copy_file_async` 的 `transfer_id` 幂等、跨 scope 拒绝 |
| 下载预览 | PASS | 内容/文件名/Content-Type、RFC 5987 中文名、文本读取、PDF 预览、kkFileView URL、preview_token 有效/过期/伪造/跨文件/跨作用域 |
| 数据完整性 | PASS | `unique_key` 自动计算与 `update_fields` 保护、100 层深度与循环引用保护、审计事件 `FILE_DELETE`/`FOLDER_DELETE`/create |
| 前端组件 | PASS | 既有 32 套件 465 例 + 新增 22 例（http 拦截器、党建上下文注入、错误去重、二进制透传）|
| Playwright E2E | PASS | 既有 8 例 + 新增 15 例门禁用例 |

---

## 6. 失败项详情

### DOC-F01 — 合并恢复路径对 NOT NULL 字段写入 None，上传状态机永久卡死

- **严重级别**：P1
- **是否阻断发布**：**是**（命中规则「上传状态机卡死 / 数据不一致」）
- **失败用例**：`test_38_direct_merge_completed_without_file_record_resets`
- **复现步骤**
  1. 创建 UPLOADING 传输记录并上传全部分片；
  2. 模拟 Celery 异常：将记录置为 `status=COMPLETED`、`file_path=''`、`celery_task_id=NULL`（文件记录未创建）；
  3. `POST /document/direct_merge/`。
- **预期结果**：按 `apps/document/AGENTS.md` 三.4 与四 的约定，重置为 `UPLOADING` 后重新合并，最终产出文件记录。
- **实际结果**：
  `django.db.utils.IntegrityError: (1048, "Column 'file_path' cannot be null")`
  异常被 `direct_merge.py:174` 的 `except Exception` 吞掉，对外返回 `提交合并任务失败，请稍后重试`；传输记录**永久停留在 COMPLETED 且无文件记录**。
- **相关位置**
  - `spug_api/apps/document/views/upload/direct_merge.py:209-212`
  - `spug_api/apps/document/models.py:360`（`file_path = models.CharField(max_length=500)`，无 `null=True`）
- **对比**：`views/upload/merge.py:347-353` 对同一异常的处理是正确的（记录日志后返回 `None`，继续走正常合并流程），缺陷仅存在于 `direct_merge` 路径。

### DOC-F02 — 删除补偿标记被请求级事务回滚，物理文件永久泄漏

- **严重级别**：P1
- **是否阻断发布**：**是**（命中规则「文件删除补偿失败」）
- **失败用例**：`test_10_physical_delete_failure_marks_pending_clean`、`test_11_pending_clean_flag_survives_request_transaction`
  （`test_12_retry_clean_pending_files_recovers` 因前置条件不成立而 SKIP，非独立失败）
- **复现步骤**
  1. 创建带真实物理文件的文件记录；
  2. 令 `safe_delete_document_file` 返回 `(False, '模拟删除失败')`（等价磁盘/权限/文件锁故障）；
  3. `DELETE /document/file/?id=<id>&is_public=true`。
- **预期结果**：保留记录并落库 `is_pending_clean=True`、`clean_retry_count=1`、`last_clean_attempt=<now>`，由 Celery `retry_clean_pending_files` 异步重试。
- **实际结果**：三个字段全部回退为 `False / 0 / NULL`。`retry_clean_pending_files` 的查询条件是 `is_pending_clean=True`，因此**永远选不中该记录**；物理文件与数据库记录双双永久残留。接口返回 `文件删除失败，已加入待清理队列，系统将自动重试`，与实际行为不符。
- **根因**：
  - `views/file/views.py:80` 的 `with transaction.atomic():` 包裹 `file.delete()`；
  - `models.py:154-164` 的补偿标记写在**嵌套 savepoint** 内；
  - `DocumentPhysicalDeleteError` 在 `views.py:98` 于 atomic 块**之外**被捕获 → atomic 块回滚 → savepoint 内容一并撤销；
  - 叠加 `settings.DATABASES['default']['ATOMIC_REQUESTS'] = True`，请求级事务进一步放大该效应。
- **相关位置**
  - `spug_api/apps/document/views/file/views.py:78-104`
  - `spug_api/apps/document/models.py:154-164`
  - `spug_api/apps/document/tasks/cleanup/pending_files.py:33-46`
- **说明**：`apps/document/AGENTS.md` 五.2 已记录此风险（「如果调用方外层事务回滚，此标记也会被回滚」），但在 `ATOMIC_REQUESTS=True` 的生产配置下该风险是**必然发生**而非偶发。

### 其余非阻断项（P2/P3）

| ID | 级别 | 摘要 | 阻断 |
|---|---|---|---|
| DOC-F03 | P2 | `@rate_limit` 用于类视图方法时抛 `AttributeError` 并 fail-open，删除与合并接口限流静默失效（`libs/view_utils.py:22-55`、`views/file/views.py:32`、`views/upload/merge.py:599`） | 否 |
| DOC-F04 | P3 | 普通上传接口对含 `..`/分隔符的文件名"净化"而非"拒绝"，与分片上传接口不一致；物理名由服务端重生成，无穿越风险 | 否 |
| DOC-F05 | P3 | 合并状态查询对未知 `task_id` 返回 `pending`（Celery 无结果后端限制，前端 300s 超时兜底） | 否 |
| DOC-F06 | P2 | 既有 `tests/test_smoke.py` 4 例因模型移除 `tenant_id` 而 ERROR（测试债务，未改动以"让测试变绿"） | 否 |
| DOC-F07 | P3 | `rg_responsive_badge.spec.js`（无线电台执照）失败，属范围外模块 | 否 |

---

## 7. 证据

### 7.1 数据库状态

- 全部后端用例在隔离库 `test_spug` 执行，业务库 `spug` 未被写入。
- 干净迁移验证：销毁并重建 `test_spug`，`document` 应用 22 个迁移（`0001_initial` → `0022_documentfilepublic_doc_pub_file_name_idx_and_more`）全部 `[X]` 应用成功，23 个用例通过。
- 数据完整性断言：`unique_key` 自动计算、`update_fields` 更新不丢失、同名同父唯一约束生效、删除/移动/复制后无孤儿记录（`test_01`–`test_22`）。

### 7.2 物理文件状态

- 递归删除：子目录 + 文件记录 + 物理文件全部清除，兄弟目录与存储根目录完好（`test_12`/`test_13`/`test_16`/`test_17`）。
- 删除顺序：先删物理文件再删数据库记录（`test_09`）。
- 路径安全：`is_safe_path` 拒绝越界；`safe_delete_document_file` / `safe_delete_thumbnail` 拒绝删除存储根目录外文件；越界 `file_path` 的下载/预览被拒；符号链接删除仅移除链接、保留目标（`test_01`–`test_08`）。
- 党建物理隔离：党建上传文件落在 `storage/documents/party_building_documents/files/` 内（`test_34`）。

### 7.3 传输状态

- 状态转换矩阵与 `AGENTS.md` 完全一致（9 状态逐项比对，`test_02`）；`COMPLETED` / `CANCELED` 为终态（`test_03`）；`FAILED` 可重试且不可直跳 `COMPLETED`（`test_04`）；`UPLOADING -> COMPLETED` 必须允许（`test_05`）。
- 分片落盘、乱序/重复分片、断点续传缺失分片报告、全部分片就绪判定均通过（`test_20`–`test_25`）。
- 合并幂等：重复提交返回同一 `task_id` 且 `is_idempotent=True`（`test_36`）；`COMPLETED` + 文件记录存在 → 幂等返回，不重复建记录（`test_37`）。
- **异常**：`COMPLETED` 但文件记录缺失的恢复路径必然失败（DOC-F01）。

### 7.4 审计日志

- `FILE_DELETE` / `FOLDER_DELETE` / 创建事件均通过 `transaction.on_commit` 落库 `AuditLog`（`test_18`–`test_20`），`target_type='document'`、`action` 映射正确。
- 作用域拒绝事件在服务端产生结构化 `[SCOPE] cross-scope denied` 日志，不泄露 token 或文件内容。

---

## 8. 产物

| 类型 | 路径 |
|---|---|
| 后端门禁用例 | `spug_api/apps/document/tests/release_gate/`（7 个模块 + `helpers.py`） |
| 前端门禁用例 | `spug_web/src/pages/document/__tests__/releaseGateHttp.test.js` |
| E2E 门禁用例 | `quality/e2e/tests/document_admin/document_release_gate.spec.js` |
| 机器可读结果 | `quality/reports/document/release_gate_results.json` |
| 本报告 | `quality/reports/document/RELEASE_GATE_REPORT.md` |

报告中不含密码、Cookie、Token、`storageState`、数据库备份、真实业务文件或未脱敏数据；`.env` 凭据仅以 `SET` 占位展示。

---

## 9. 结论

# RELEASE_BLOCKED

依据门禁判定原则：

- `stable_contract` 失败 → **阻断**
- 上传状态机卡死（DOC-F01）→ **阻断**
- 文件删除补偿失败（DOC-F02）→ **阻断**

**必须修复后方可发布的最小集合**：

1. `direct_merge.py:211` 将 `transfer.file_path = None` 改为 `transfer.file_path = ''`（字段为 `NOT NULL` 的 `CharField`），使恢复路径与 `merge.py:347-353` 行为一致。
2. 让 `is_pending_clean` 补偿标记在 `ATOMIC_REQUESTS=True` 下可靠落库：将 `DocumentPhysicalDeleteError` 的捕获移入 `transaction.atomic()` 块内，或改用 `transaction.on_commit` 写标记，或引入独立的异步补偿投递。

**建议同时处理**：DOC-F03（限流静默失效）、DOC-F06（既有冒烟测试失效）。

修复后建议重跑：

```bash
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py test \
  apps.document.tests.release_gate.test_upload_merge \
  apps.document.tests.release_gate.test_fs_safety --keepdb
```

DOC-F01、DOC-F02 对应用例转为 PASS 后，本模块可重新判定。
