# 无线电执照管理模块 上线前全量测试报告

- **报告编号**: RG-RADIO-20260903
- **测试日期**: 2026-09-03
- **测试执行人**: 高级测试工程师 / 接口测试工程师 / 安全审计（ZCode 上线门禁）
- **测试对象**: 无线电执照管理模块（无线电台执照 + 台站频率批复）
- **最终结论**: **BLOCKED**（存在 4 项高危权限/证据完整性缺陷，修复后需复测）

---

## 一、测试环境、版本、数据库和账号说明

| 项 | 值 |
|---|---|
| 测试容器 | `tdyw-test`（bind mount，镜像 `tdyw:django42-stage2`） |
| 数据库容器 | `tdyw-db-test`（MariaDB 10.8.2，端口 3307） |
| 后端测试数据库 | `test_spug`（Django test runner 隔离库，`--keepdb`，每用例事务回滚/截断，未触碰业务库 `spug`） |
| 前端测试 | react-app-rewired + jest（ReactDOM + jsdom 真实渲染） |
| E2E | Playwright (chromium)，`E2E_BASE_URL=http://localhost:8080`（tdyw-test 专用测试环境） |
| 预览服务 | `tdyw-kkfileview-test`（kkFileView 4.1.0，端口 8012） |
| Django / Python | Django 4.2 / Python 3.10 |
| 测试数据前缀 | `RG-`（租户 `rg_ta` / `rg_tb`），E2E 数据前缀 `E2E-`，均在测试库/隔离环境中创建，未涉及生产数据 |
| 测试账号 | 后端用例在 `test_spug` 内即时创建（`rg_*` 前缀，权限经 Role 注入）；E2E 使用 `.env` 配置的专用测试账号（凭据不入库不入报告） |

**环境事件记录（非产品缺陷）**：测试期间发现 `test_spug.users.deleted_by_id` 列为 NOT NULL（与迁移定义 `null=True` 不一致，建表时间戳显示为先前会话遗留的测试库重建产物），导致一次全量运行出现 237 个基础设施性 ERROR。已执行 `ALTER TABLE test_spug.users MODIFY COLUMN deleted_by_id BIGINT NULL` 修复（仅测试库），修复后全量重跑结果见下。业务库 `spug` 全程未做任何写操作。

---

## 二、测试用例总数与结果汇总

| 层 | 用例数 | PASS | FAIL | BLOCKED | NOT_RUN |
|---|---|---|---|---|---|
| 后端（Django test，容器内执行） | 255（既有 102 + 本次新增 153） | 245 | 10 | 0 | 0 |
| 前端组件/Store（jest 真实渲染） | 36（既有 10 + 新增 26） | 32 | 4 | 0 | 0 |
| 前端 E2E（Playwright 真实浏览器） | 14（既有 8 + 新增 6） | 13 | 1 | 0 | 0 |
| 前后端权限编码一致性审计 | 1 项 | 1 | 0 | 0 | 0 |
| **合计** | **306** | **291** | **15** | **0** | 见第六节 |

> 15 个 FAIL 全部为**表达正确业务规格的用例在真实代码路径上失败**，即缺陷证据（非测试脚本错误；测试脚本问题已在执行过程中逐一修复并复跑）。其中 1 项（F-09）为间歇性复现（4 次运行 2 次失败），最终全量运行中通过，但缺陷确认存在。
> 既有 102 个后端用例与既有前端用例全部通过，本次测试未破坏任何既有行为。

**新增长期资产**：
- 后端：`spug_api/apps/radio_license/tests/release_gate/`（7 个测试文件，153 用例，可纳入发布门禁 `stable_contract` 类）
- 前端：`spug_web/src/pages/radioLicense/__tests__/store.request.test.js`、`Form.behavior.test.js`；`stationFrequencyApproval/__tests__/store.request.test.js`、`Form.behavior.test.js`、`Table.perms.test.js`；`home/__tests__/ExpiryOverview.test.js`
- E2E：`quality/e2e/tests/document_admin/rg_responsive_badge.spec.js`
- 运行日志：本目录 `backend_test_run_final.log`、`frontend_test_run.log`、`e2e_test_run.log`

---

## 三、分类结果

### 3.1 功能（执照 A 组 / 批复 B 组 / 到期状态 C 组）

| 范围 | 结果 | 说明 |
|---|---|---|
| 执照列表/分页/默认排序（新→旧）/台站/用途/截止日期范围筛选 | PASS | 25 条分页、深分页正确 |
| 执照 status 筛选 | **FAIL（F-07）** | 依赖缓存 `status` 字段而非实时计算 |
| 执照新增/详情/编辑/删除 | PASS | 含必填校验、日期顺序校验、频率先删后建 |
| 频率明细校验（值>0、sort_order 非负、非法不破坏旧数据） | PASS | 6 个用例全覆盖，非法输入时旧明细保留 |
| 重复提交幂等（执照） | PASS | 30s 窗口拦截第二次提交 |
| `page=abc` 健壮性 | **FAIL（F-10）** | ValueError → 500「服务器内部错误」 |
| 批复 CRUD/分页/筛选（name/doc_no/status/日期范围） | PASS | status 筛选实时转换正确（与执照形成对照） |
| 批复 doc_no 租户内重复 | PASS（按现行规则允许） | 不假设唯一 |
| 批复编辑后 status/days_left/computed_status 即时正确 | PASS | 含缓存状态错误时详情/列表仍实时计算 |
| 边界值 -1/0/60/61（执照+批复，详情 API 实测） | PASS | 8 组边界全部符合 |
| 新增/编辑后状态即时更新 | PASS | 即时扫描生效 |
| Celery 扫描（执照 08:00 / 批复 08:05 任务）多租户+重复执行 | PASS | 第二次全量扫描 updated=0，无写放大 |

### 3.2 提醒、徽标和确认（D 组）

| 范围 | 结果 | 说明 |
|---|---|---|
| popup 只返回本人负责的 expiring/expired，normal/他人/跨租户不出现 | PASS | |
| badge 与 popup 口径一致，expiring/expired 分类正确 | PASS | |
| 确认后本周期不再提醒；同周期重复确认幂等（DB 唯一约束） | PASS | 3 次重复 ack 仅 1 行；并发 5 线程 ack 也仅 1 行 |
| valid_to 续期后旧 ack 失效重新提醒 | PASS | 执照+批复均验证 |
| 更换责任人后新责任人收到、原责任人不收到 | PASS | 执照+批复均验证 |
| 非责任人确认 | 批复 PASS / 执照 **FAIL（F-05）** | 执照 ack 无责任人校验 |
| 确认 normal 记录 | 批复 PASS / 执照 **FAIL（F-06）** | 执照 ack 无状态校验 |
| 跨租户确认 | PASS | 两端均拦截 |
| 执照/批复提醒相互隔离 | PASS | popup 各自只返回本类型记录 |

### 3.3 附件和证据闭环（E 组）

| 范围 | 结果 | 说明 |
|---|---|---|
| 上传/列表/下载(attachment/inline)/预览URL/预览文件/删除全链路（真实物理文件） | PASS | 含 SHA256 落库、物理文件事务提交后删除、空目录清理 |
| 文件类型/大小（>50MB）/异常文件名校验 | PASS | `.exe` 拒绝、50MB+1 拒绝、无 DB 残留 |
| 路径穿越文件名（`../../x.pdf`、反斜杠） | PASS | 存储名清洗，物理路径仍在 MEDIA_ROOT 内 |
| 预览 token：伪造/篡改签名/过期(max_age=0)/attachment_id 不匹配/软删后预览 | PASS | 全部拒绝且提示正确 |
| 预览 token 无 x-token 回调可用（kkFileView 模式） | PASS | |
| 执照/批复附件列表相互隔离 | PASS | object_type 过滤正确 |
| **执照附件端点跨对象越权（下载/删除/预览批复附件）** | **FAIL（F-01/F-02/F-03）** | 见第四节 |
| **执照附件删除证据事件** | **FAIL（F-04）** | 死代码，事件永不写入 |
| 批复附件端点对象类型校验 | PASS | 桥接校验正确（对照实现） |
| 跨租户上传/下载/删除/预览签发 | PASS | 全部拒绝且无残留 |
| 删除执照级联：附件软删+物理文件删除、频率/ack 物理删除 | PASS | |
| 删除批复级联：附件软删（物理文件保留，delete_file=False）、ack 物理删除 | PASS（按现行设计） | 不对称性见 O-02 |
| 证据包 ZIP：五个 JSON+verify.txt、哈希清单仅含未删附件、缺参/不存在/跨租户错误处理 | PASS | |
| 文件操作失败不留错误 DB 成功记录（上传失败无 DB 记录；物理文件丢失下载报错不删记录） | PASS | |

### 3.4 权限和租户隔离（第五组）

| 范围 | 结果 |
|---|---|
| 无 view 权限访问列表/详情/提醒/徽标/责任人下拉（执照+批复，含无权限/仅add/仅edit 三种形态） | PASS（后端真实拦截 `权限拒绝`） |
| 仅 add 不能编辑、仅 edit 不能新增（执照+批复） | PASS |
| 无 del 不能删除记录 | PASS |
| 无 upload/download/delete 不能执行附件操作（含仅 view 可看列表不可操作） | PASS |
| 仅有附件权限无 approval.view 不能通过批复端点上传 | PASS |
| 租户 B 读/改/删/下载租户 A 的执照、批复、附件 | PASS（全部拒绝） |
| 责任人下拉（执照+批复两端点）不泄露其他租户用户、不含禁用/软删用户、仅返回 id/nickname/username | PASS |
| 超管跨租户可见（明确设计）+ 不绕过存在性/软删除校验（超管也不能下载已软删附件） | PASS |
| 前端路由 auth 与后端权限编码一致性（11 个编码双向对齐） | PASS |

### 3.5 版本、审计和数据完整性（F 组）

| 范围 | 结果 |
|---|---|
| 编辑前保存修改前快照（内容为旧值、datetime 可序列化） | PASS |
| version_no 按执照递增（连续 3 次编辑 1/2/3） | PASS |
| snapshot_hash 可校验（重算一致）、篡改后可发现（哈希不匹配） | PASS |
| changed_fields 记录实际变更字段 | **FAIL（F-11）** 恒为空串 |
| 创建/编辑/删除/续期审计日志（租户/操作者/对象/request_id/detail） | PASS |
| 续期证据事件含 before/after | PASS |
| 批复 create/update/delete 审计日志 + ack 专属审计 | PASS |
| 执照附件删除证据事件 | **FAIL（F-04）** |
| 审计日志哈希链字段（request_hash/log_hash）填充 | PASS |
| 并发编辑版本号一致性 | **FAIL（F-09，间歇性 ~50%）** |
| 并发 ack 单行、删除/上传竞争后状态一致 | PASS |

### 3.6 定时任务和部署检查（第七组）

| 范围 | 结果 |
|---|---|
| Beat 注册：执照扫描 crontab 08:00、批复扫描 08:05，队列 `radio_license`，time_limit≥600 | PASS |
| 任务 soft_time_limit=300 / time_limit=600 / queue 正确 | PASS |
| radio_license 迁移全部已应用、`makemigrations --check` 无漂移 | PASS |
| MariaDB 约束实测：status 枚举（执照+批复）、日期顺序、频率>0、sort_order≥0、ack 唯一 | PASS（均触发 IntegrityError） |
| 约束真实存在于 information_schema | PASS |
| DEBUG=False、MEDIA_ROOT 存在、kkFileView 回源 host 在 ALLOWED_HOSTS（测试容器） | PASS |
| 审计请求体脱敏（password 掩码） | PASS |
| 生产 compose 默认 `ALLOWED_HOSTS=*` | 观察项 O-07 |

### 3.7 性能和可靠性（第八组，1 万条执照 + 1 万条批复实测）

| 指标 | 实测值 | 判定 |
|---|---|---|
| 执照列表首页(20条)/深分页(第400页) | 0.181s / 0.180s | PASS |
| 执照台站/状态/日期范围筛选 | 0.077s / 0.027s / 0.127s | PASS |
| 批复列表首页/状态筛选 | 0.057s / 0.045s | PASS |
| 执照徽标 / 批复徽标（1 万条本人负责） | 0.028s / 0.029s | PASS |
| 执照详情 | 0.021s | PASS |
| popup（返回 2275 条，无分页） | 0.217s | PASS（观察项 O-05） |
| P95（20 轮采样）：执照列表 / 批复列表 / 徽标 | 0.196s / 0.063s / 0.025s，错误率 0 | PASS |
| 执照列表查询数：page_size=5/20/25 → 45/134/164 次 | **FAIL（F-08 N+1，每行约 6 次查询）** | |
| 批复列表查询数：page_size=5/25 → 20/19 次（恒定） | PASS（对照实现正确） | |
| 并发新增（5 线程不同数据全部落库）、并发重复 ack（5 线程 1 行） | PASS | |

### 3.8 前端专项（第六组）

| 范围 | 结果 |
|---|---|
| 路由权限编码一致性 | PASS |
| Modal 使用 visible、详情/表单渲染、必填校验、编辑回填、提交载荷（日期格式化/频率 sort_order/id） | PASS |
| 执照表单提交失败：弹窗不关闭、loading 复位、错误提示一次 | **FAIL（F-13）** 双重提示 |
| 批复表单前端日期顺序校验（不发请求+提示） | PASS |
| 关闭后重开表单字段与错误状态重置 | PASS |
| HTTP 200+error 业务失败数据不污染、isFetching 复位（执照+批复 store） | PASS |
| 快速切换筛选时旧请求不覆盖新结果 | **FAIL（F-14，执照+批复同病）** |
| 删除最后一页最后一条后分页回退 | **FAIL（F-15）** |
| 责任人列表 token 缓存与账号切换强制重拉 | PASS |
| 操作列/新建按钮按权限门控（执照+批复） | PASS |
| 批复仅查看用户操作列不渲染（双击行进详情） | PASS（行为记录，与执照表不一致 → F-18） |
| 删除确认流程（Modal.confirm → DELETE → 刷新） | PASS |
| 工作台到期徽标：数量渲染、点击跳转 /radio-license 与 /station-frequency-approval、接口失败降级、无权限占位、全零空态 | PASS（jsdom 4/4 + E2E 真实浏览器跳转） |
| 桌面 1440px / 窄屏 375px 列表页无横向溢出（执照+批复，真实浏览器） | PASS |
| 详情弹窗窄屏溢出 | **FAIL（F-17，375px 下溢出 125px）** |

---

## 四、缺陷清单（按严重级别排序）

### F-01 [High] 执照附件下载端点可下载任意同租户附件（跨对象类型/跨模块）

- **位置**: `spug_api/apps/radio_license/views.py` `AttachmentDownloadView.get`（约 676 行）→ `AttachmentService.download_response`
- **根因**: 下载仅按附件 ID + 租户过滤，未校验 `module='radio_license', object_type='license'`。批复侧（`ApprovalAttachmentDownloadView`）有桥接校验，执照侧缺失。
- **影响**: 持有 `radio_license.attachment.download` 的用户可下载本租户**任意模块**（批复、合同、协作任务、值班日志等）的任意附件（附件 ID 为顺序整数，可遍历）。违反规格 E2/E3「执照附件和批复附件相互隔离」。
- **复现**（测试 `test_license_endpoint_cannot_download_approval_attachment`）:
  1. 租户 A 上传批复附件（`POST /api/radio-license/approvals/{id}/attachments/`）
  2. 用仅有执照权限的账号 `GET /api/radio-license/attachments/{批复附件id}/download/`
  3. **实际**: 返回批复附件文件流（越权下载成功）
  4. **预期**: `{'error': '附件不存在或无权限访问'}`
- **证据**: `backend_test_run_final.log` 中该用例失败信息「执照下载端点返回了批复附件的文件流（越权下载成功）」

### F-02 [High] 执照附件删除端点可软删除任意同租户附件

- **位置**: `spug_api/apps/radio_license/views.py` `AttachmentDeleteView.delete`（约 714 行）
- **根因**: 同 F-01，`AttachmentService.soft_delete` 仅租户过滤。
- **影响**: 持有 `radio_license.attachment.delete` 的用户可软删除本租户任意模块的附件（破坏性操作）。且删除后写入的证据事件**硬编码** `object_type='license'`、`object_id=att.object_id`，对非执照附件会产生归属错误的证据事件（证据链污染）。
- **复现**（测试 `test_license_endpoint_cannot_delete_approval_attachment`）:
  1. 租户 A 存在批复附件
  2. `DELETE /api/radio-license/attachments/?id={批复附件id}`
  3. **实际**: `{'error': ''}`（成功），批复附件被软删
  4. **预期**: 拒绝删除，附件保持未删除
- **证据**: 日志失败信息「执照删除端点删除批复附件应被拒绝，实际返回: {'data': '', 'error': ''}」

### F-03 [High] 执照附件预览端点可为任意同租户附件签发预览令牌

- **位置**: `spug_api/apps/radio_license/views.py` `AttachmentPreviewUrlView.get`（约 688 行）
- **根因**: 同 F-01（`AttachmentService.get_preview_url` 仅租户过滤）。与 F-01/F-02 同一根因族，一并修复。
- **复现**: `GET /api/radio-license/attachments/{批复附件id}/preview-url/` → **实际**返回含有效 preview_token 的 kkFileView URL；**预期**拒绝。

### F-04 [High] 执照附件删除的证据事件是死代码（永不写入）

- **位置**: `spug_api/apps/radio_license/views.py:730-751`
- **根因**: `soft_delete` 成功后，代码用 `EvidenceAttachment.objects.filter(pk=form.id).first()` 重新取附件——但 `TenantModelManager` 默认过滤 `is_deleted=False`，刚被软删的记录查不到 → `if att:` 恒为 False → 证据事件静默跳过（连错误日志都没有）。批复侧（`approval_views.py:547` 用 `att.refresh_from_db()`，走 base manager）不受影响。
- **影响**: 执照附件删除**从不**产生证据事件，证据闭环（E 组「附件删除写入正确审计日志」）断裂，且故障是静默的。
- **复现**（测试 `test_attachment_delete_writes_evidence_event`）: 删除执照附件成功后查询 `EvidenceEvent(module='radio_license', object_type='license', event_type='delete')` → **实际** 0 条；**预期** 1 条。
- **证据**: 日志 `INFO [Evidence] 附件软删除 ID=94 ...` 后无任何 EVIDENCE 错误/写入日志，事件表 0 行。

### F-05 [Medium] 执照提醒确认不校验责任人

- **位置**: `spug_api/apps/radio_license/views.py` `ReminderAckView.post`（约 814 行）
- **对照**: 批复侧 `ApprovalReminderAckView`（`approval_views.py:639`）有「仅责任人可确认」校验。
- **影响**: 同租户任意持 `license.view` 的用户可对他人执照写入 ack（写入的是自己的 ack，不会干扰他人提醒，但产生无意义数据且与批复侧规则不一致；规格 D8 明确要求失败）。
- **复现**: 非责任人（同租户）`POST /radio-license/reminders/ack/ {'license_id': X}` → **实际** `{'data': {'acked': True}}`；**预期** error。

### F-06 [Medium] 执照提醒确认不校验状态（normal 也可确认）

- **位置**: 同 F-05。批复侧有「当前批复状态正常，无需确认处理」校验。
- **影响**: 可对 normal 执照写入无意义 ack；与批复侧及规格 D8 不一致。

### F-07 [Medium] 执照列表 status 筛选依赖缓存字段（与实时口径不一致）

- **位置**: `spug_api/apps/radio_license/views.py:168`（`records.filter(status=status)`）
- **对照**: 批复侧 `_apply_approval_status_filter` 将 status 转换为 valid_to 实时范围（`approval_views.py:93`）。
- **影响**: 当缓存 status 过期（如 Beat 未运行窗口内、或数据经非 API 途径写入）时，列表**显示** `computed_status=expired` 但 `?status=expired` 筛选不出该记录（规格 B5/C「不盲信数据库缓存 status」）。
- **复现**（测试 `test_list_filter_by_status_realtime`）: ORM 直接写入 `valid_to=今天-5天, status='normal'` 的记录 → `GET /radio-license/?status=expired` → **实际** 0 条；**预期** 1 条。

### F-08 [Medium] 执照列表 N+1 查询

- **位置**: `spug_api/apps/radio_license/views.py:186-192`（循环内逐条查频率 + 逐条 `AttachmentService.count`）
- **对照**: 批复侧用 `_bulk_attachment_counts` 批量聚合（`approval_views.py:104`）。
- **实测**: page_size=5/20/25 → 45/134/164 次查询（每行约 6 次）；批复列表恒定 ~20 次。1 万条数据下执照列表 0.181s vs 批复 0.057s（3 倍差距）；page_size=100 时差距进一步放大。
- **复现**: 测试 `test_license_list_no_n_plus_1`（`CaptureQueriesContext` 计数断言失败：`119 not less than or equal to 3`）。

### F-09 [Medium] 并发编辑产生重复 version_no（间歇性 ~50% 复现）

- **位置**: `spug_api/apps/radio_license/views.py:430-433`（`_save_license_version_snapshot` 先读 max(version_no) 再 create，无锁无唯一约束）
- **复现**: 2 线程经 barrier 同时编辑同一执照 → 产生 `[1, 1]` 两个版本号（4 次运行 2 次复现；最终全量运行中通过）。
- **建议**: `(license, version_no)` 唯一约束或 `select_for_update`。

### F-10 [Low] 执照列表 `?page=abc` 触发 500

- **位置**: `spug_api/apps/radio_license/views.py:175`（`int(request.GET.get('page', 1))` 未捕获 ValueError）
- **对照**: 批复侧有 try/except 回退（`approval_views.py:161-169`）。
- **实际**: `{'error': '服务器内部错误，请联系管理员'}`（HandleExceptionMiddleware 兜底，伴随告警）；**预期**: 回退 page=1。

### F-11 [Low] 版本快照 changed_fields 恒为空串

- **位置**: `spug_api/apps/radio_license/views.py:458`（`changed_fields=''` 硬编码）。视图已计算 `_detect_license_changed_fields` 但只用于证据事件，未传入版本快照。
- **影响**: 版本历史的变更字段信息缺失（规格 F3）。

### F-12 [Low] Form 提交的 `validateFields()` 无 `.catch`（执照与批复表单同病）

- **位置**: `spug_web/src/pages/radioLicense/Form.js:60`、`stationFrequencyApproval/Form.js:59`
- **影响**: 校验失败时产生未处理 Promise 拒绝（浏览器控制台 `Uncaught (in promise)`；测试环境下足以使 Node 进程崩溃）。功能上校验错误仍正常显示，属代码质量问题。
- **证据**: 测试运行中进程以 `ERR_UNHANDLED_REJECTION` 崩溃，定位至该调用链；测试侧以 `validateFields` 包装器吸收拒绝后继续验证行为。

### F-13 [Low] 执照表单业务失败双重提示

- **位置**: `spug_web/src/pages/radioLicense/Form.js:96`（`message.error(e.message || '操作失败，请稍后重试')`）
- **根因**: `libs/http.js` 对业务错误 reject 的是**字符串**，`e.message` 恒 undefined → 永远显示通用文案；且拦截器 `showErrorOnce` 已弹过一次具体错误 → 同一错误双重提示且第二条为误导性通用文案（违反「同一错误只能提示一次」）。批复表单 catch 仅 console.error，正确。
- **实测**: `message.error` 收到 `'操作失败，请稍后重试'` 而非 `'起始日期不能晚于截止日期'`。

### F-14 [Medium] 前端 store 无请求时序保护（旧响应覆盖新结果）

- **位置**: `spug_web/src/pages/radioLicense/store.js:48`、`stationFrequencyApproval/store.js:45`（`fetchRecords` 无请求序号/取消保护）
- **影响**: 快速切换筛选或翻页时，慢的旧请求后返回会覆盖新结果，表格显示与筛选条件不符（规格 六.6）。
- **复现**（jsdom 双 deferred 实测）: 新请求先返回（结果 B），旧请求后返回（结果 A）→ store.records 变回 A。

### F-15 [Low] 删除最后一页最后一条记录后分页不回退

- **位置**: 两个 store 的 `fetchRecords`（响应中 page 为空页时 `pageNum = page || pageNum` 保持原值）。
- **影响**: 用户停留在空页，需手动点回上一页（规格 A7）。

### F-16 [Low] 执照附件下载按钮无权限门控

- **位置**: `spug_web/src/pages/radioLicense/Form.js:162-179`（`AttachmentManager` 未传 `downloadPerm`，`AttachmentManager.js:402` 默认 `!downloadPerm → canDownload=true`）
- **影响**: 无 `radio_license.attachment.download` 权限的用户看到下载按钮，点击后被后端拒绝（前端按钮显示与权限不一致，规格 六.7）。批复表单已正确传 `downloadPerm`。

### F-17 [Low] 执照详情弹窗窄屏横向溢出

- **位置**: `spug_web/src/pages/radioLicense/Form.js:109`（`width={900}` 固定宽度）及批复详情 `width={900}`
- **实测**: 375px 视口下弹窗横向溢出 **125px**（E2E `scrollWidth - clientWidth` 实测）；列表页本身无溢出。

### F-18 [Low] 批复操作列对仅查看用户不渲染（与执照表不一致）

- **位置**: `spug_web/src/pages/stationFrequencyApproval/Table.js:120`（条件为 `edit|del`，未含 view；执照表为 `view|edit|del`）
- **影响**: 仅查看用户无「查看」按钮（仍可双击行进详情），交互不一致。

### 观察项（不阻断，建议评估）

| 编号 | 内容 |
|---|---|
| O-01 | `EvidenceAttachment` 无 `is_pending_clean`/物理文件删除失败重试机制——事务提交后物理删除失败仅记 ERROR 日志，孤儿文件无补偿（规格 E6 提及的重试逻辑在本模块不存在） |
| O-02 | 删除批复保留物理文件（`delete_file=False`）vs 删除执照删除物理文件（`delete_file=True`）——不对称，且 O-01 意味着批复删除后的附件文件无清理路径 |
| O-03 | 执照 ack 仅依赖中间件通用审计日志（无 ack 专属 detail），批复侧有专属审计（含 ack_valid_to） |
| O-04 | preview-file 端点路径别名：执照附件的 preview_token 也可用于批复 preview-file 路径（token 与附件绑定，无权限提升，属实现噪音） |
| O-05 | popup 无分页：1 万条数据下本人 2275 条一次性返回（0.217s），数据量再增长需考虑分页/限量 |
| O-06 | 批复创建无重复提交幂等防护（执照侧有 30s 窗口 `check_recent_duplicate`），双击可产生重复记录 |
| O-07 | 生产 compose 默认 `ALLOWED_HOSTS=*`（`docker/docker-compose.yml:39`），建议生产收紧为显式列表 |
| O-08 | 0 字节文件上传当前被允许（size=0 落库），如需拒绝应补充校验 |
| O-09 | 空字符串整数参数（如 `responsible_user_id: ""`）与非法日期格式（`2026/01/01`）会触发 500 而非业务错误提示（与 F-10 同族的健壮性问题） |

---

## 五、数据库、物理文件、审计与 Celery 证据

**数据库状态证据**（测试内实时断言，非事后检查）：
- 约束验证：5 类 CHECK/UNIQUE 约束均以 `IntegrityError` 实际触发（`test_beat_migrations_constraints.py`）
- 级联验证：执照删除后 frequencies/acks 计数为 0；批复删除后 ack 计数为 0；附件软删标记与删除人/原因落库
- ack 幂等：同周期重复与 5 线程并发 ack 后 `LicenseReminderAck` 计数恒为 1

**物理文件证据**（MEDIA_ROOT 临时目录，`captureOnCommitCallbacks(execute=True)`）：
- 上传后物理文件存在、SHA256 落库；软删除后物理文件消失、目录清理
- 路径穿越文件名落盘路径经 `realpath` 校验仍在 MEDIA_ROOT 内
- 物理文件被移除后下载返回业务错误且 DB 记录保留

**审计证据**：
- 执照 create/update/delete、批复 create/update/delete 的 `AuditLog`（含 tenant_id/user_id/request_id/request_hash/log_hash）均断言存在
- 续期 `EvidenceEvent` 的 before/after snapshot JSON 内容断言正确
- 反例：执照附件删除证据事件缺失（F-04）

**Celery 任务证据**：
- `scan_radio_license_expiration.apply().get()` 与 `scan_approval_expiration.apply().get()` 同步执行，多租户 3+2 条记录状态全部更新正确；第二次执行 `updated=0`（无写放大）
- Beat 注册、crontab、队列、时限断言通过

**性能证据**：见 3.7 节表格（P95、查询计数、1 万条实测），原始输出在 `backend_test_run_final.log` 中以 `[RG-PERF]` 前缀记录。

---

## 六、未覆盖项及原因

| 项 | 状态 | 原因 |
|---|---|---|
| 生产环境（tdyw 容器）配置实测 | NOT_RUN | 测试原则禁止连接生产；已用测试容器实测 + `docker-compose.yml` 静态取证代替，生产 ALLOWED_HOSTS/MEDIA 权限需运维另行确认 |
| 生产级 Locust 并发压测 | NOT_RUN | 已以 1 万条数据单机实测（P95/查询数/并发线程）代替；生产规模压测需另行排期 |
| kkFileView 容器间真实回源预览 | NOT_RUN | preview_token 签发/校验逻辑已全量单测（含过期/伪造/不匹配），容器间网络链路未端到端执行 |
| 移动端真机布局 | NOT_RUN | 以 375px 视口 Chromium 模拟代替（发现 F-17） |
| 批复表单「关闭后重开重置」jsdom 用例 | 部分覆盖 | 批复 Form 与执照 Form 同构，执照侧已验证；批复侧重开路径经 E2E/手工路径覆盖 |

---

## 七、最终上线结论

**BLOCKED**

阻断依据（引用门禁标准「存在阻断问题、严重权限/租户问题、数据完整性问题」）：

1. **F-01/F-02/F-03 [High]**：执照附件下载/删除/预览端点缺少对象归属校验，同租户内可跨对象类型、跨模块访问与**删除**其他模块的证据附件——属对象级授权缺失，违反本模块规格的附件隔离要求，且 F-02 为破坏性操作、会污染证据事件归属。
2. **F-04 [High]**：执照附件删除的证据事件为死代码，证据闭环静默断裂——属数据完整性问题。

**最小修复集**（修复后建议复测转 CONDITIONAL）：
- 执照侧三个附件端点补齐与批复侧一致的桥接校验（`module='radio_license' AND object_type='license'`，参照 `approval_views.py:_get_approval_attachment_for_user`）；删除视图在软删**前**取得附件实例用于证据事件（参照批复侧 `refresh_from_db` 模式）。
- 复测范围：`apps.radio_license.tests.release_gate.test_attachments`（31 用例）+ `test_versions_audit` 中附件证据用例。

中低风险问题（F-05~F-18、O-01~O-09）不单独阻断，建议随修复批次排期；其中 F-08（N+1）与 F-14（旧请求覆盖）在大数据量/慢网络下体验影响明确，建议优先。

---

## 八、测试产物清单

| 文件 | 说明 |
|---|---|
| `quality/reports/radio_license_release_gate/backend_test_run_final.log` | 后端全量 255 用例最终运行日志（含 `[RG-PERF]` 性能数据、`[RG-DEPLOY]` 配置取证） |
| `quality/reports/radio_license_release_gate/backend_test_run.log` | 后端 release_gate 153 用例中间运行日志 |
| `quality/reports/radio_license_release_gate/frontend_test_run.log` | 前端 jest 36 用例运行日志 |
| `quality/reports/radio_license_release_gate/e2e_test_run.log` | E2E 14 用例运行日志 |
| `spug_api/apps/radio_license/tests/release_gate/`（7 文件） | 后端门禁测试（可纳入发布门禁 stable_contract） |
| `spug_web/src/pages/{radioLicense,stationFrequencyApproval,home}/__tests__/`（6 新文件） | 前端组件/Store 测试 |
| `quality/e2e/tests/document_admin/rg_responsive_badge.spec.js` | 响应式+徽标跳转 E2E |

报告不含任何密码、Token、Cookie 或未脱敏数据；E2E 凭据仅存在于不入库的 `.env`。
