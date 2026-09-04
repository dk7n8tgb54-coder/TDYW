# 规章管理模块上线前测试报告

- 报告编号：`REG-RG-20260903-200135`
- 生成时间：2026-09-03 20:01（UTC+8）
- 测试类型：上线前发布门禁验证（功能正确性 / 权限安全 / 附件数据完整性 / 前后端契约 / 异常处理 / 发布风险）
- 报告结论：**HOLD**（存在 3 项 P1 缺陷，见第 8 节）

> 脱敏声明：本报告不含账号密码、access_token、Cookie、storageState、真实业务文件与未脱敏数据。
> 所有账号均为测试执行期在隔离测试库 `test_spug` 中动态创建的临时账号。

---

## 1. 测试范围与代码版本

### 1.1 代码版本

| 项 | 值 |
|---|---|
| 分支 | `tdyw` |
| 测试执行时 HEAD | `f4146c20eaed219dad6df876de05ecf8b69f246c`（合同协议测试部分代码 附件变化即刷新 资料库缺陷修复） |
| 测试结束后 HEAD | `e6c4b199d47070b50eebe69c90e8ee120766932c`（完成无线电管理、合同协议、干扰模块的缺陷修复，部分规章管理模块的测试代码） |
| 提交说明 | 该提交由本会话之外的操作创建。**本次测试未创建任何 commit**；提交内容包含本次新增的规章测试文件与其他模块的既有改动。本报告全部结论基于测试执行时的代码状态（`f4146c20` + 本次新增测试资产），规章业务代码在该提交中同样无改动。 |
| 测试前 `git status` | 工作区存在**与规章模块无关的既有修改**（contract_agreement / radio_license / interference / stationFrequencyApproval 等），本次未覆盖、未修改、未回滚 |
| 测试前 `git diff --check` | 无空白符错误（仅 LF/CRLF 换行提示，为既有文件） |
| 规章模块业务代码 | **未被修改** —— 对 `models.py` / `views.py` / `storage.py` / `urls.py` 及前端 6 个组件文件执行 `git diff --stat`，输出为空 |

### 1.2 本次新增/变更文件（仅测试资产，不含业务代码）

| 文件 | 类型 | 说明 |
|---|---|---|
| `spug_api/apps/regulation/tests/release_gate/__init__.py` | 新增 | 发布门禁测试包 |
| `spug_api/apps/regulation/tests/release_gate/base.py` | 新增 | 账号矩阵 / 存储隔离 / 操作封装 |
| `spug_api/apps/regulation/tests/release_gate/test_01_crud_validation.py` | 新增 | CRUD + 参数与业务校验 |
| `spug_api/apps/regulation/tests/release_gate/test_02_category.py` | 新增 | 分类管理与 category_manage 权限 |
| `spug_api/apps/regulation/tests/release_gate/test_03_query_pagination.py` | 新增 | 筛选 / 分页 / N+1 / 附件顺序 |
| `spug_api/apps/regulation/tests/release_gate/test_04_permission_tenant.py` | 新增 | 权限矩阵与租户隔离 |
| `spug_api/apps/regulation/tests/release_gate/test_05_attachment_upload.py` | 新增 | 上传与存储安全 |
| `spug_api/apps/regulation/tests/release_gate/test_06_preview_token.py` | 新增 | 下载 / 预览 / 令牌安全 |
| `spug_api/apps/regulation/tests/release_gate/test_07_delete_audit.py` | 新增 | 删除 / 审计 / 事务副作用 |
| `spug_web/src/pages/regulation/__tests__/Http.errorContract.test.js` | 新增 | 前后端错误契约（真实拦截器代码） |
| `spug_web/src/pages/regulation/__tests__/Form.errorPrompt.test.js` | 新增 | 弹窗错误提示行为 |

### 1.3 被测范围

**前端**：`spug_web/src/pages/regulation/` — `index.js`、`Table.js`、`Form.js`、`CategoryTree.js`、`CategoryForm.js`、`store.js`；
`spug_web/src/routes.js`（路由权限）、`spug_web/src/libs/http.js`（公共 HTTP 层）。

**后端**：`spug_api/apps/regulation/` — `models.py`、`views.py`、`storage.py`、`urls.py`、`migrations/`（6 个迁移）；
关联公共组件 `spug_api/libs/middleware.py`、`libs/decorators.py`、`libs/parser.py`、`libs/idempotency.py`、`libs/pagination.py`、
`apps/logs/audit.py`、`apps/logs/models.py`、`apps/evidence/attachment_preview_token.py`。

**后端测试分类**：`apps/regulation/tests/` 下 `characterization`（旧架构行为基线）、`defect_reproduction`（缺陷复现）、
`stable_contract`（长期稳定契约，即本次新增 `release_gate/` 中大部分用例）、`test_smoke.py` / `test_transaction_boundary.py`（存量）。

---

## 2. 测试环境与账号类型

### 2.1 环境

| 项 | 值 |
|---|---|
| 执行容器 | `tdyw-test`（镜像 `tdyw:django42-stage2`，bind mount 可见最新代码） |
| 数据库 | MariaDB `10.8.2-MariaDB-log`；容器内 `db` 解析至 `172.20.0.4`（`tdyw-db-test`，**独立测试实例，非 dev 生产库**） |
| 测试数据库 | `test_spug`（Django test runner 自动创建与销毁，与业务库隔离） |
| `ATOMIC_REQUESTS` | `True` |
| `sql_mode` | `STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION` |
| 物理文件 | 通过 patch 重定向到进程级临时目录，**未触碰容器真实 `storage/documents/`** |
| kkFileView | `KKFILEVIEW_API_URL=/kkfileview`、`KKFILEVIEW_SERVER_URL=http://tdyw-test`（已配置） |
| `REGULATION_MAX_FILE_SIZE` | 未显式配置 → 代码默认 200 MB |
| `DEBUG` | 测试容器为 `True`；对外服务容器 `tdyw` 为 `False` |

> 安全说明：全程未执行 `flush`、清库、恢复或针对业务数据的删除操作。

### 2.2 账号类型（不含凭据）

| 代号 | 权限集合 | 用途 |
|---|---|---|
| `rg_admin` | `document.regulation.*` 全量 7 项 | 正向路径 / 基线 |
| `rg_viewer` | 仅 `view` | 只读边界 |
| `rg_uploader` | `view` + `upload` | 上传权限不越权校验 |
| `rg_downloader` | `view` + `download` | 下载权限不越权校验 |
| `rg_editor` | `view` + `edit` | 编辑权限不越权校验 |
| `rg_creator` | `view` + `add` | 新建权限不越权校验 |
| `rg_deleter` | `view` + `delete` | 删除权限不越权校验 |
| `rg_catman` | `view` + `category_manage` | 分类管理权限不越权校验 |
| `rg_noperm` | 无 | 未授权访问 |
| `rg_other_tenant` | `view`，`tenant_id ≠ default` | 跨租户可见性核对 |
| 匿名 / 无效 token | — | 401 鉴权 |

---

## 3. 执行的命令与结果摘要

| # | 命令 | 结果 |
|---|---|---|
| C1 | `git status` / `git diff --check` | 无规章模块改动；存在其他模块既有改动（未触碰） |
| C2 | `manage.py check`（`tdyw-test`） | 通过；1 条既有告警 `document.DocumentSystemFolder.folder (fields.W342)`，与规章无关 |
| C3 | `manage.py makemigrations regulation --check --dry-run` | `No changes detected in app 'regulation'`（无待生成迁移） |
| C4 | `manage.py test apps.regulation.tests --noinput -v 2` | **309 用例：301 PASS / 7 FAIL / 1 NOT_RUN** |
| C5 | `manage.py test apps.evidence.tests apps.logs.tests --noinput` | **49 用例全部通过**（附件 + 审计公共能力回归） |
| C6 | `react-app-rewired test --testPathPattern src/pages/regulation/__tests__` | **18 用例：17 PASS / 1 FAIL** |
| C7 | `npm run build` | `Compiled with warnings`；告警全部来自 `departmentDutyLog` / `coopTask`，规章模块无告警 |
| C8 | 环境探针（只读） | 数据库、kkFileView、BASE_DIR、DEBUG 等配置项核对完成 |

原始日志见 `evidence/` 目录。

---

## 4. 用例矩阵

逐用例明细见同目录 CSV（可直接导入表格/门禁系统）：

- `test-matrix-backend.csv` —— 309 条，字段：`case_id, layer, risk, module, suite, case, result`
- `test-matrix-frontend.csv` —— 18 条，同结构

### 4.1 结果统计

| 层 | 总数 | PASS | FAIL | NOT_RUN | BLOCKED |
|---|---|---|---|---|---|
| 后端（存量 80 + 新增门禁 229） | 309 | 301 | 7 | 1 | 0 |
| 前端（组件 + 契约） | 18 | 17 | 1 | 0 | 0 |
| 关联回归（evidence + logs） | 49 | 49 | 0 | 0 | 0 |
| **合计** | **376** | **367** | **8** | **1** | **0** |

### 4.2 按风险等级统计（后端 309）

| 风险 | 用例数 | PASS | FAIL/NOT_RUN |
|---|---|---|---|
| P0（令牌安全 / 越权 / 路径穿越） | 46 | 45 | 1（REG-AUDIT-001 侧写） |
| P1（审计 / 事务 / 权限边界 / 删除副作用） | 96 | 91 | 5 |
| P2 | 78 | 78 | 0 |
| P3 | 89 | 87 | 2 |

### 4.3 关键用例明细（按用户要求的核心验证点）

| 用例 ID | 风险 | 前置条件 | 操作步骤 | 预期结果 | 实际结果 | 结论 | 证据 |
|---|---|---|---|---|---|---|---|
| BE-001 | P2 | admin | POST `/regulation/create/` 最小字段 | 200 + 无 error，状态默认 active | 一致 | PASS | evidence/backend-test-run.log |
| BE-012 | P2 | admin | PUT 修改标题/编号/发文单位/业务类型/状态/分类/日期 | 全部落库，updated_by/updated_at 更新 | 一致 | PASS | 同上 |
| BE-013 | P1 | 规章已有 publish/effective 日期 | PUT `{"publish_date":"", "effective_date":""}` 后重新查询 DB | 两字段为 NULL | 一致（落库为 NULL） | PASS | 同上 |
| BE-014 | P1 | 规章已挂叶子分类 | PUT `{"category_id":""}` 后重新查询 DB | `category_id` 为 NULL | 一致 | PASS | 同上 |
| BE-016 | P2 | 规章已有日期 | PUT `{"publish_date": null}` | JSON null ≡ 未提交，保持原值 | 一致（契约确认） | PASS | 同上 |
| BE-017 | P2 | 规章已有分类 | PUT `{"category_id": 0}` | 视为清空分类 | 一致 | PASS | 同上 |
| BE-018 | P2 | 规章已有分类 | PUT 不传 `category_id` | 保持原分类 | 一致 | PASS | 同上 |
| BE-030 | P2 | admin | POST `title` 超 255 字符 | 返回业务错误且不落库 | 返回 error，未落库 | PASS | 同上 |
| BE-032 | P1 | admin | 上条请求的状态码 | 期望 5xx | **实际 HTTP 200 + error** | **FAIL**（REG-HTTP-001） | 同上 |
| BE-033 | P1 | `DEBUG=True` | 检查异常文案是否回显 | 不回显异常原文 | **回显 `Exception: (1406, "Data too long for column 'title'")`** | **FAIL** | 同上 |
| BE-065 | P3 | `DEBUG=False`（Django 测试运行期强制） | 复现异常原文回显 | — | 环境不满足，跳过 | **NOT_RUN** | 同上 |
| BE-040 | P1 | 已废止规章 | 重复 POST `/retire/` | 幂等，无错误、无副作用 | 一致（返回 `status=retired`） | PASS | 同上 |
| BE-041 | P2 | 已废止规章 | PUT 编辑 | 视产品规则 | **后端允许编辑**（前端已隐藏入口） | PASS（记录行为，见 P2-3） | 同上 |
| BE-042 | P2 | 已废止规章 | 上传附件 | 视产品规则 | **后端允许上传** | PASS（记录行为，见 P2-3） | 同上 |
| BE-052 | P1 | 删除规章（含 1 附件） | DELETE + 强制触发 on_commit | DB 记录消失、附件 CASCADE、物理文件清理 | 一致 | PASS | 同上 |
| BE-090 | P1 | 分类被规章引用 | DELETE 分类 | 阻止删除，关联规章完好 | 一致（"该分类下有规章，不能删除"） | PASS | 同上 |
| BE-100 | P1 | 分类管理接口 | PUT 传 `parent_id` | 视接口约定 | **PUT 不接受 parent_id**，父子关系不可变更 | PASS（循环引用场景不可构造） | 同上 |
| BE-120 | P2 | 25 条规章 | `page=0/-3`、`page_size=0/-5/abc/99999` | 归一到 [1,1]/[1,100]，不越界 | 一致 | PASS | 同上 |
| BE-128 | P2 | 10 条规章各带附件 | 统计附件表查询次数 | ≤2 次（无 N+1） | 一致（Prefetch 生效） | PASS | 同上 |
| BE-140 | P0 | 无效 / 缺失 token | GET `/regulation/` | 401 | 一致 | PASS | 同上 |
| BE-142 | P0 | 无权限账号 × 10 个受保护端点 | 直接调用 API | 全部 `权限拒绝`，DB 无变化 | 一致 | PASS | 同上 |
| BE-150~156 | P0 | viewer | 创建/编辑/删除/废止/上传/删附件/下载 | 全部拒绝，DB 与物理文件零变化 | 一致 | PASS | 同上 |
| BE-160~168 | P0 | upload / download / add / delete / cat_manage | 交叉越权 | 权限不得相互隐含 | 一致（无隐含授权） | PASS | 同上 |
| BE-172 | P0 | downloader | 用规章 A 的 URL 访问规章 B 的附件 ID | 拒绝，不返回内容 | 一致（"附件不存在"） | PASS | 同上 |
| BE-173 | P0 | downloader | 篡改 URL 中规章 ID | 拒绝，不返回内容 | 一致 | PASS | 同上 |
| BE-180~186 | P1 | 不同租户账号 | 列表 / 详情 / 分类树 / 附件列表 | 按产品规则 | **跨租户全部可见**（无 tenant_id） | PASS（记录行为，见 P3-1） | 同上 |
| BE-190 | P2 | uploader | 上传 15 种白名单扩展名 | 全部成功 | 一致 | PASS | 同上 |
| BE-195 | P2 | uploader | 空文件（0 字节） | 视产品规则 | **允许上传，file_size=0** | PASS（记录行为，见 P3-5） | 同上 |
| BE-198 | P2 | uploader | 200MB 上限（patch 为 10B 触发） | 拒绝且不落盘 | 一致 | PASS | 同上 |
| BE-205 | P0 | uploader | 文件名 `../../../etc/passwd.pdf` | 物理路径限制在 `regulation/` 内 | 一致（清洗后落盘，无穿越） | PASS | 同上 |
| BE-206 | P0 | uploader | 反斜杠 `..\..\windows\x.pdf` | 同上 | 一致 | PASS | 同上 |
| BE-209 | P1 | uploader | 200 个汉字的长文件名 | 上传成功或明确业务错误 | **HTTP 200 + "服务器内部错误"**（OSError: File name too long） | **FAIL**（REG-UPLOAD-001） | 同上 |
| BE-210 | P1 | — | 校验截断后存储名字节长度（根因） | ≤255 字节 | **257 字节** | **FAIL**（根因确认） | 同上 |
| BE-213 | P3 | uploader | 304 字符原始文件名 | 明确错误或一致落库 | **成功但 `original_name` 静默截断为 255** | PASS（记录行为，见 P3-2） | 同上 |
| BE-215 | P2 | uploader | 同名文件连续上传两次 | `stored_name` 不冲突、内容不覆盖 | 一致 | PASS | 同上 |
| BE-220 | P2 | uploader | 校验元数据 8 项 + MD5 + uploaded_by | 全部正确 | 一致 | PASS | 同上 |
| BE-222 | P1 | uploader | DB create 失败 | 无记录、无孤儿文件 | 一致 | PASS | 同上 |
| BE-223 | P1 | uploader | 物理写入失败 | 无虚假记录 | 一致 | PASS | 同上 |
| BE-224 | P1 | uploader | 上传后检查 `EvidenceAttachment` | 规章附件不写入 | 一致（0 条） | PASS | 同上 |
| BE-230 | P2 | downloader | 下载 / `?inline=1` | Content-Type、Content-Length、disposition | 一致 | PASS | 同上 |
| BE-233 | P0 | downloader | `file_path` 越界的附件记录 | 不泄漏区域外文件 | 一致（"文件不存在"，文件仍在） | PASS | 同上 |
| BE-238 | P2 | viewer | Office 文件预览地址（kkFileView 已配置） | `preview_type=kkfileview` | 一致 | PASS | 同上 |
| BE-239 | P1 | viewer | kkFileView 未配置 | 明确降级错误，不 500 | 一致（HTTP 200 + "Office文档预览服务未配置"） | PASS | 同上 |
| BE-245~258 | P0 | viewer | 令牌缺失/无效/篡改/过期/错附件/错规章/错 module/错 object_type | 全部拒绝且不返回内容 | 一致 | PASS | 同上 |
| BE-259 | P0 | viewer | 预览端点 URL 中携带 `x-token` | 401 | 一致 | PASS | 同上 |
| BE-260 | P0 | — | `/api/` 前缀预览路径命中中间件白名单 | 命中 | 一致 | PASS | 同上 |
| BE-265 | P1 | admin | 删除附件字段与可见性 | is_deleted/deleted_by/deleted_at 正确，列表/下载/预览全部剔除 | 一致 | PASS | 同上 |
| BE-270 | P1 | admin | 事务回滚时 on_commit 是否误删文件 | 不删除 | 一致（回滚后文件保留） | PASS | 同上 |
| BE-271 | P1 | admin | 物理删除失败 | 有日志或待清理机制 | **仅日志，无 is_pending_clean / 无重试任务** | PASS（记录行为，见 P2-2） | 同上 |
| BE-275 | P1 | admin | 删除规章的级联与物理文件 | 记录 CASCADE、文件清理、其他规章不受影响 | 一致 | PASS | 同上 |
| BE-174 | P1 | admin | 上传附件的审计事件 | 存在 `upload_attachment` 审计 | **事件丢失** | **FAIL**（REG-AUDIT-001） | 同上 |
| BE-203 | P1 | downloader | 下载附件的审计事件 | 存在 `download_attachment` 审计 | **事件丢失** | **FAIL**（REG-AUDIT-001） | 同上 |
| BE-234 | P1 | admin | 删除附件的审计事件 | 存在 `delete_attachment` 审计 | **事件丢失** | **FAIL**（REG-AUDIT-001） | 同上 |
| BE-248/250/251 | P1 | admin | 废止审计与动作枚举 | 存在 `retire` 审计 | **事件丢失** | **FAIL**（REG-AUDIT-001） | 同上 |
| FE-001 | P0 | 真实 Form 组件 + 真实拦截器 | HTTP 200 + error 时统计 `message.error` | 1 次 | **2 次** | **FAIL**（REG-UI-001） | evidence/frontend-test-run.json |
| FE-002~010 | P0 | 真实 `libs/http.js` 拦截器 | 200+error / 200+data / 二进制 JSON 错误体 | reject / resolve / 去重 | 一致 | PASS | 同上 |
| FE-011~018 | P2 | 真实组件渲染 | 载荷构造、列宽拖拽、双击复位、会话存储 | 一致 | 一致 | PASS | 同上 |

> 说明：BE 编号为矩阵 CSV 中的 `case_id` 对应关系，部分为同类聚合展示；完整 309 条以 CSV 为准。

---

## 5. 缺陷清单

### P1

#### REG-AUDIT-001　规章模块 4 类业务审计事件 100% 丢失

- **文件 / 接口**
  - `spug_api/apps/logs/models.py:81-89`（`CheckConstraint(audit_action_valid)`，白名单仅 10 个动作）
  - `spug_api/apps/logs/audit.py:366-368`（`save_audit_log` 捕获异常后仅写日志 + 告警）
  - `spug_api/apps/regulation/views.py:657`（`action='retire'`）、`:756`（`upload_attachment`）、`:819`（`download_attachment`）、`:1005`（`delete_attachment`）
- **复现步骤**
  1. 以有权限账号 `POST /api/regulation/<id>/retire/`（或上传/下载/删除任一附件）
  2. 查询 `AuditLog.objects.filter(target_type='regulation', action='retire')`
  3. 观察后端日志出现 `ERROR [AUDIT] 保存审计日志失败: (4025, 'CONSTRAINT audit_action_valid failed for test_spug.audit_logs')`
- **影响**
  - 废止、上传附件、下载附件、删除附件四类操作**无任何审计记录**，无法满足合规追溯与事后取证。
  - 主流程仍返回成功，错误仅落在日志与告警，运维极易漏发现。
  - 附件下载是数据外泄的主要通道，该动作无审计属于安全合规硬伤。
- **建议**
  1. 在 `AuditLog.ACTION_CHOICES` 与 `audit_action_valid` 约束白名单中补充 `retire`、`upload_attachment`、`download_attachment`、`delete_attachment`（需同步生成迁移，注意历史数据兼容）；
  2. 或把自定义动作归一到既有枚举，将细分动作放入 `detail`；
  3. `save_audit_log` 失败应上报可观测指标/告警看板，而不是仅写 error 日志。
- **证据**：BE-174 / BE-203 / BE-234 / BE-248 / BE-250 / BE-251 六个失败用例 + 根因用例 `AuditActionConstraintRootCauseTests`（真实 DB 写入证明 CHECK 约束拒绝）。

#### REG-UPLOAD-001　纯中文长文件名上传必然失败（HTTP 200 + 服务器内部错误）

- **文件**：`spug_api/apps/regulation/storage.py:27` `MAX_STORED_BASENAME_LENGTH = 80`
- **复现步骤**
  1. 上传文件名主体为 80 个及以上汉字的文件（如 200 个汉字 + `.pdf`）
  2. 观察响应与日志
- **实际结果**：`OSError: [Errno 36] File name too long`；经 `HandleExceptionMiddleware` 兜底为 HTTP 200 + `{"error":"服务器内部错误，请联系管理员"}`；DB 未产生记录（无残留）
- **根因**：`_sanitize_filename_stem` 按**字符**截断到 80，而文件系统按**字节**限制 255。80 个汉字 = 240 字节，加 `_` + 12 位 hex + `.pdf`（17 字节）= **257 字节 > 255**。
- **影响**：中文用户使用较长中文文件名（≥80 汉字，`.docx` 等 5 字符扩展名时阈值更低）上传必然失败，且错误信息无业务含义。
- **建议**：改为按字节截断（如先 `stem.encode('utf-8')[:N]` 再安全解码），保证 `len(stored_name.encode('utf-8')) + len(ext) + 13 <= 255`；并在 `save_upload_file` 前显式校验最终字节长度，返回明确业务错误。
- **证据**：BE-209（失败）、BE-210（根因，实测 257 字节）。

#### MIDDLE-001　未处理异常被公共中间件兜底为 HTTP 200（全系统影响）

- **文件**：`spug_api/libs/middleware.py:127-130`
- **复现步骤**：`POST /api/regulation/create/` 传入超长 `title`（300 字符）触发数据库 `DataError`
- **实际结果**：HTTP **200** + `{"error": "服务器内部错误，请联系管理员"}`；`DEBUG=True` 时为 `{"error": "Exception: (1406, \"Data too long for column 'title' at row 1\")"}`
- **影响**
  - 基于 HTTP 状态码的监控、告警、网关统计与 Nginx 访问日志**全部漏报**，5xx 类故障不可观测；
  - `DEBUG=True` 时把异常原文（含表名、列名、SQL 片段、绝对路径）回显给客户端，属信息泄露。
- **环境核对**：`tdyw` 容器 `DEBUG=False`（不回显），`tdyw-test` 容器 `DEBUG=True`；**生产环境配置需人工确认**。
- **建议**：`process_exception` 返回 500 状态码；`DEBUG` 分支只在内部/联调环境启用，生产强制走通用文案。
- **影响面**：该中间件为公共组件，影响全部业务模块，非规章模块独有。
- **证据**：BE-032（状态码失真）、BE-033（DEBUG 回显，仅在 `tdyw-test` 可复现）。

### P2

#### REG-UI-001　同一业务错误重复提示两次

- **文件**：`spug_web/src/libs/http.js:56,92`；`spug_web/src/pages/regulation/Form.js:64,79`；`CategoryForm.js:36,48`
- **复现步骤**
  1. 渲染规章编辑弹窗，令后端返回 HTTP 200 + `{"error":"规章编号不能为空"}`
  2. 统计 `message.error` 调用
- **实际结果**：2 次 —— 第一次为拦截器提示的「规章编号不能为空」，第二次为业务 `.catch(e => message.error(e.message || '操作失败'))` 退化的「操作失败」；两条文案不同，`showErrorOnce` 的 2 秒去重不生效
- **根因**：拦截器以**字符串** reject，`e.message` 为 `undefined`，业务兜底文案丢失原始错误
- **影响**：用户看到两条错误提示，第二条无信息量；违反 AGENTS.md 第九条第 3 点
- **建议**：业务代码 catch 中不再自行提示（拦截器已统一提示），或统一使用 `skipErrorNotification` + 业务自提示，二选一
- **证据**：FE-001（期望 1 次 / 实际 2 次）

#### REG-RETRY-001　规章附件物理删除失败无补偿重试机制

- **文件**：`spug_api/apps/regulation/views.py:994-1003`、`storage.py:170-192`
- **实际结果**：`safe_delete_attachment_file` 失败仅 `logger.error`；`RegulationAttachment` **无 `is_pending_clean` 字段**，也无对应的 Celery 重试任务
- **影响**：DB 已软删除、用户不可见，物理文件永久泄漏，存储空间持续增长且无法自动回收
- **对比**：资料库模块已有 `is_pending_clean` + `retry_clean_pending_files` 机制，规章模块未对齐
- **建议**：增加 `is_pending_clean` 标记并纳入既有的 `retry_clean_pending_files` 消费链路，或新增规章专属重试任务
- **证据**：BE-271

#### REG-RETIRED-001　已废止规章前后端操作规则不一致（需产品确认）

- **前端**：`Form.js:113`（详情模式 retired 时隐藏「编辑」）、`Table.js:118-123`（retired 时隐藏「编辑」「废止」）
- **后端**：`RegulationDetailView.put`、`RegulationAttachmentUploadView`、`RegulationDetailView.delete` **均无状态校验**
- **实际结果**：直接调用 API 可编辑已废止规章、可给已废止规章上传附件、可删除已废止规章
- **影响**：前端隐藏按钮不构成权限控制；若产品规则为"已废止即冻结"，则存在越权修改已归档数据的风险
- **建议**：请产品明确规则；若不允许，后端需在 PUT / upload / retire 前校验 `status != retired` 并返回业务错误（**若确认为不允许，本项升为 P1 发布阻断**）
- **证据**：BE-041 / BE-042 / BE-043（当前通过，记录实际行为）

### P3

| 编号 | 问题 | 文件 | 影响与建议 |
|---|---|---|---|
| REG-TENANT-001 | `Regulation` / `RegulationCategory` / `RegulationAttachment` 均无 `tenant_id`，任意有 `view` 权限的账号（含其他租户）可读取全部规章与附件 | `apps/regulation/models.py` | 需产品确认是否为"全局共享"。若确认为全局共享，应补充文档依据；若要求隔离，则为本轮**发布阻断**。当前 `AGENTS.md` 模块矩阵未标注规章为租户隔离，仓库内 `REGULATION_CRUD_AUDIT_REPORT.md` 亦未涉及租户。证据：BE-180~186 |
| REG-VALID-001 | 上传 304 字符文件名 → 接口返回成功，但 `original_name` 被静默截断为 255 字符（直接 ORM 写入同长度则被数据库拒绝，说明字段约束真实存在） | `views.py:747` | 附件名与源文件不一致且无提示；建议视图层显式校验文件名长度并返回业务错误。证据：BE-213 / BE-014（ORM 对照） |
| REG-CAT-001 | 分类名称纯空白（`'   '`）可入库（创建规章的 `title` 已做 strip 校验，分类未做） | `views.py:213-218` | 产生不可见/不可选的垃圾分类；建议对 `name` 做 strip 后非空校验。证据：BE-095 |
| REG-AUDIT-002 | `retire` / `upload_attachment` 等 action 不在 `AuditLog.ACTION_CHOICES` 声明内（与 REG-AUDIT-001 同源） | `apps/logs/models.py:12-22` | 即使约束放开，审计日志查询页的动作下拉仍无法枚举这些动作 |
| REG-UPLOAD-002 | 0 字节空文件允许上传并生成 `file_size=0` 记录 | `views.py:717` | 视产品规则决定是否拒绝；建议至少在列表给出提示 |
| REG-UPLOAD-003 | 仅按扩展名白名单判定，不校验文件内容；`evil.exe.pdf`（内容实为可执行文件）可上传，且 PDF/图片走 inline 预览 | `storage.py:31-35,66-73` | 内容伪装风险；建议对图片/PDF 增加 magic number 校验 |
| REG-STORE-001 | 仅校验单文件 200MB 上限，无目录/租户总配额与磁盘剩余空间校验 | `views.py:717` | 磁盘写满时会在 `save_upload_file` 抛 OSError → 500 |
| REG-PROMISE-001 | `store.fetchRecords()` / `store.fetchCategories()` 链无 `.catch`，接口失败时产生 unhandled promise rejection | `spug_web/src/pages/regulation/store.js:54-66` | 控制台噪声，且失败后列表保持旧数据但无错误态；建议补 catch 并设置错误态 |

---

## 6. 专项结论

### 6.1 权限

- **结论：通过（无越权）**，但存在"前后端规则不一致"与"审计缺失"两处需跟进。
- 后端 `@auth('document.regulation.*')` 在 10 类受保护端点上独立生效，未授权/无效 token 分别返回 `权限拒绝`（HTTP 200 + error）与 401。
- 权限无隐含授予：`upload` 不获得 `download`/`category_manage`/`edit`/`delete`；`download` 不获得 `upload`/附件删除；`add` 不获得 `edit`/`delete`；`delete` 不获得 `edit`；`category_manage` 不获得规章写权限。
- 所有拒绝场景均验证：HTTP 响应为业务 error、数据库无变化、物理文件数量无变化。
- 附件访问范围以「规章 → 附件」两级归属校验，篡改 URL 中规章 ID 或附件 ID 均被拒绝（返回"附件不存在"，不泄漏内容）。
- **遗留**：已废止规章的写操作后端未限制（REG-RETIRED-001）；废止/附件类动作无审计（REG-AUDIT-001）。

### 6.2 租户

- **结论：数据非租户隔离（全局共享），需产品书面确认。**
- `Regulation` / `RegulationCategory` / `RegulationAttachment` 三个模型均无 `tenant_id` 字段；不同租户账号可读取全部规章、分类树与附件列表。
- 权限体系仍独立生效（无 view 权限的跨租户账号照样被拒）。
- 仓库内未找到"规章为全局共享"的产品文档依据；`AGENTS.md` 未将规章列入租户隔离模型清单。
- **处置**：若产品确认为全局共享 → 降级为 P3 并补文档；若要求租户隔离 → 本项**升级为发布阻断**。

### 6.3 附件路径

- **结论：通过（无路径穿越）**。
- `resolve_absolute_path` 对绝对路径、`..`、区域外相对路径均抛 `ValueError`；上传侧 `build_stored_name` 对 `/ \ : * ? " < > |` 与控制字符做替换，对路径分隔符做 basename 处理。
- 实测 `../../../etc/passwd.pdf`、`..\..\windows\x.pdf` 均落在 `<root>/regulation/{id}/{yyyy}/{mm}/` 内。
- 以越界 `file_path` 构造的附件记录，在下载与预览接口均返回"文件不存在"，区域外文件未被读取、未被删除。
- `safe_delete_attachment_file` 拒绝删除 `regulation/` 之外的路径并记 error 日志。
- **遗留**：无待清理重试机制（REG-RETRY-001）。

### 6.4 预览令牌

- **结论：通过（无绕过）**。
- 令牌基于 `TimestampSigner`，有效期 300 秒，绑定 `attachment_id / user_id / tenant_id / module / object_type / object_id` 六项。
- 以下场景全部拒绝且不返回文件内容：缺失令牌、无效签名、篡改签名、过期（400 秒）、附件 ID 不匹配、规章 ID 不匹配、module 不匹配、object_type 不匹配、附件已软删除、物理文件缺失、`file_path` 越界。
- 预览端点拒绝 URL 中的 `x-token`（401），仅接受 header 或 `preview_token`；`/api/` 前缀路径仍命中中间件鉴权白名单（生产 nginx 重写后路径一致）。
- 预览不要求 `download` 权限（仅 `view`），下载要求 `download` 权限，二者独立生效。
- 令牌未出现在审计 detail 中（脱敏器已覆盖 `token` 关键字）。

### 6.5 事务与文件副作用

- **结论：写顺序正确，回滚安全。**
- 上传：物理文件先落盘（实测在 `objects.create` 被调用时文件已存在且内容完整），DB 写入在事务内；DB 失败时事务回滚且物理文件被清理，**无孤儿文件**（BE-222）。
- 物理写入失败时不产生虚假附件记录（BE-223）。
- 删除附件与删除规章的物理清理均通过 `transaction.on_commit` 注册；事务回滚时 on_commit 不执行，文件保留（BE-270 / BE-278）。
- 删除规章时附件记录 CASCADE 硬删除、物理文件清理，且不影响其他规章的附件（BE-275 / BE-276）。
- `ATOMIC_REQUESTS=True` 提供多步写原子性兜底。
- **遗留**：物理删除失败仅记日志，无重试/补偿（REG-RETRY-001）。

---

## 7. 覆盖率与未覆盖项

| 维度 | 覆盖情况 |
|---|---|
| 后端 CRUD | 覆盖（创建/列表/详情/编辑/删除/废止，含清空语义与 DB 复核） |
| 参数与业务校验 | 覆盖（必填、空值、空白、日期格式、非法状态、分类存在性与叶子、日期先后、超长、Unicode、幂等窗口） |
| 分类管理 | 覆盖（树/列表/新建/编辑/删除/叶子维护/权限）；**父节点变更与循环引用不可构造**（PUT 不接受 `parent_id`，见 BE-100） |
| 查询筛选分页 | 覆盖（关键字、状态、业务类型、发文单位、分类、生效日期区间、组合、边界与非法值、页码越界、无重复行） |
| 权限 | 覆盖（11 类账号 × 10+ 端点，含交叉越权与副作用核验） |
| 租户 | 覆盖（跨租户可见性实测，规则待产品确认） |
| 附件上传存储 | 覆盖（15 种白名单类型、空文件、超大、大小写扩展名、无扩展名、伪造扩展名、路径分隔符、反斜杠、控制字符、超长、Unicode、同名重复、元数据 8 项、落盘顺序、DB/物理失败） |
| 下载预览令牌 | 覆盖（响应头、inline、kkFileView 已配置/未配置、权限分离、8 类令牌异常、越界路径、URL 篡改） |
| 删除与审计 | 覆盖（软删除字段、可见性、重复删除、跨规章删除、级联、回滚、脱敏）；**审计事件写入本身存在缺陷**（REG-AUDIT-001） |
| 数据库迁移 | `makemigrations --check` 无待生成迁移；6 个历史迁移在 `test_spug` 全新库中全部应用成功 |
| 前端组件 | 覆盖（载荷构造、列宽拖拽/复位/会话存储、错误契约、提示行为）；**未覆盖**：详情模式 `AttachmentManager` 的上传/删除交互（组件以 `null` mock 替代）、路由级权限跳转、空/加载/错误态渲染 |
| E2E（Playwright） | **NOT_RUN** —— 本轮未执行真实浏览器流程；`quality/e2e/` 中未检索到规章管理专项用例 |
| kkFileView 真实联调 | **NOT_RUN** —— 仅验证到"生成正确预览地址与回源 URL"，未驱动 kkFileView 真正拉取文件流渲染 |
| 性能/并发 | **NOT_RUN** —— 仅做 N+1 查询计数，未做并发上传、大文件（接近 200MB）真实上传与压测 |
| 生产配置核对 | **部分** —— `DEBUG` 在 `tdyw` 容器为 `False`；kkFileView、附件目录权限、磁盘配额需人工确认 |

---

## 8. 发布结论

> ## **HOLD**

判定依据（满足任一即 HOLD）：

1. 存在 **3 项 P1 缺陷**：REG-AUDIT-001（附件与废止审计 100% 丢失）、REG-UPLOAD-001（中文长文件名上传必然失败）、MIDDLE-001（异常兜底为 HTTP 200，全系统影响）。
2. `stable_contract` 用例未全部通过：7 项后端 + 1 项前端失败，其中 6 项集中于审计完整性这一关键数据完整性要求。
3. 关键安全与数据完整性检查中，权限、路径穿越、预览令牌、事务副作用**通过**；**审计完整性未通过**。

未判定为 BLOCKED：测试环境、数据库、kkFileView、前端构建链路均可用，必要验证已完成。

**建议的放行条件（按优先级）**

1. 修复 REG-AUDIT-001 并使 6 个审计用例转绿（合规硬要求，建议最高优先）。
2. 修复 REG-UPLOAD-001（按字节截断 + 前置校验）。
3. 修复 REG-UI-001（消除重复提示）。
4. 明确 REG-TENANT-001 与 REG-RETIRED-001 的产品规则；若规则为"需隔离"/"已废止冻结"，则对应项升为发布阻断。
5. MIDDLE-001 属公共组件，建议单独立项排期，不影响规章模块单独放行的前提是已确认生产 `DEBUG=False`。

---

## 9. 残余风险、人工确认项与上线后监控建议

### 9.1 残余风险

| 风险 | 等级 | 说明 |
|---|---|---|
| 审计空窗期数据无法追溯 | 高 | 修复前已发生的废止/附件上传下载删除操作无审计记录，历史数据无法补录 |
| 中文长文件名用户上传失败 | 中 | 上线后预计会有零星失败工单，需客服口径 |
| 5xx 监控盲区 | 中 | 因 MIDDLE-001，基于状态码的告警在本轮修复前不可信 |
| 物理文件泄漏累积 | 低 | 无重试机制，删除失败的文件需人工清理 |
| 跨租户数据可见 | 待定 | 取决于产品规则确认结果 |
| 磁盘写满导致上传 500 | 低 | 无配额与剩余空间校验 |

### 9.2 人工确认项

1. **产品规则：规章是否应为租户隔离数据？**（REG-TENANT-001）—— 若要求隔离，本项升为发布阻断。
2. **产品规则：已废止规章是否允许编辑/上传附件/删除？**（REG-RETIRED-001）—— 若不允许，后端须补校验。
3. **生产环境 `DEBUG` 与 `ALLOWED_HOSTS` 配置核对**（MIDDLE-001）—— 确认生产为 `False`。
4. **生产 kkFileView 可用性**—— 本轮仅验证到后端生成地址正确，需人工打开一次 Office 预览确认端到端可用。
5. **生产 `storage/documents/regulation/` 目录权限与磁盘配额**。
6. **`REGULATION_MAX_FILE_SIZE` 是否需要按环境覆盖**（当前取代码默认 200MB）。

### 9.3 上线后监控建议

1. **审计失败告警**：为 `ERROR [AUDIT] 保存审计日志失败` 与 `CONSTRAINT audit_action_valid failed` 建立独立告警规则（修复前必开，修复后作为回归哨兵）。
2. **5xx 语义恢复后**：为 `/api/regulation/*` 建立按 HTTP 状态码的 5xx 告警与 P99 耗时看板（当前因 MIDDLE-001 不可用，可先基于日志 `Unhandled exception on ...` 关键字告警）。
3. **上传失败率**：监控 `OSError` / `File name too long` / 超大文件拒绝的计数，按文件扩展名维度聚合。
4. **物理文件对账**：建议上线后每周对 `tdyw_regulation_attachment`（`is_deleted=0`）与 `storage/documents/regulation/` 做一次条数/体积对账，识别泄漏文件。
5. **预览令牌失败**：监控 `预览令牌无效` / `预览令牌与请求附件不匹配` 的突增，可作为越权探测的信号。
6. **幂等窗口**：`check_recent_duplicate` 为 30 秒窗口，监控"检测到重复提交"的误拒率，避免正常业务被拦。

---

## 10. 附件与证据索引

| 文件 | 说明 |
|---|---|
| `test-matrix-backend.csv` | 后端 309 条逐用例矩阵 |
| `test-matrix-frontend.csv` | 前端 18 条逐用例矩阵 |
| `evidence/backend-test-run.log` | 后端全量详细执行日志（`-v 2`） |
| `evidence/backend-iteration.log` | 迭代期执行日志（含缺陷复现过程） |
| `evidence/regression-evidence-logs.log` | evidence + logs 回归（49 通过） |
| `evidence/frontend-test-run.json` | 前端 Jest 结构化结果 |
| `evidence/frontend-test-run.log` | 前端执行日志 |
| `evidence/frontend-build.log` | 生产构建日志 |
| `_build_matrix.py` / `_build_matrix_fe.py` | 矩阵生成脚本（可复现，纯日志解析） |

---

## 11. 过程合规声明

- 未修改任何业务代码；仅新增测试资产与本报告。
- 未创建任何 git commit。
- 未覆盖或回滚工作区既有修改（测试前后 `git status` 中规章模块业务文件均无改动）。
- 未在开发业务库或生产库执行 flush / 清库 / 恢复 / 删除操作；所有后端测试在 `test_spug` 隔离库完成。
- 未执行 Playwright 真实浏览器流程（本轮 E2E 标记 NOT_RUN）。
- 未通过读取源码字符串、正则匹配源码或伪造 HTTP 响应代替测试；所有断言均基于真实 HTTP 请求、真实数据库状态、真实文件系统副作用与真实组件渲染。
