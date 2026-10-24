# AGENTS.md — 全项目工程规则

> 本文件供 Codex、GLM 等编码智能体修改本项目代码时遵守。下层 `spug_api/AGENTS.md` 和 `spug_web/AGENTS.md` 可补充更具体的规则，但不得与本文件矛盾。

---

## 一、技术栈与目录职责

| 层 | 技术 | 目录 | 说明 |
|---|---|---|---|
| 后端 | Django 4.2 + Django REST Framework + Channels 4 + Celery 5.2 | `spug_api/` | Python 3.10，MariaDB 10.8，Redis |
| 前端 | React 17 + antd 4.21.5 + MobX（legacy decorators + class properties） | `spug_web/` | webpack 打包，LESS 样式 |
| 部署 | Docker Compose | `docker/` | `tdyw`(后端) + `tdyw-db`(MariaDB) + `kkfileview`(预览) |
| 脚本 | Python / PowerShell / Bash | `scripts/` | 运维、审计、数据修复脚本 |
| 压测 | Locust | `locustfile/` | 性能压测脚本 |
| 质量工程 | Django Test / Playwright / Locust / 审计工具 | `quality/` | 跨系统测试、审计、性能、灾备、发布门禁及报告 |

### 关键约束

- **antd 4.21.5**：Modal/Drawer 用 `visible`（非 `open`）；表单用 `Form.useForm()`。
- **MobX legacy decorators**：`@observable` / `@action` 装饰器语法，Babel 需 `@babel/plugin-proposal-decorators`（`legacy: true`）+ `@babel/plugin-proposal-class-properties`。
- **MariaDB 10.8**：不支持部分唯一索引；`LIKE '%xxx'` 前缀通配无法走索引；不支持 `JSON_FIELD` 的部分查询操作。
- **Python 3.10**：可使用 match-case，但项目代码风格以传统 if/elif 为主。
- **行尾符统一 LF**：所有新建或修改的前后端源码文件（Python、JS/JSX、LESS、HTML、JSON、YAML、配置及测试代码）一律使用 LF 行尾，禁止 CRLF；在 Windows 环境下编辑时也必须保持 LF，不得因编辑器默认设置引入 `\r`。
- **维护台账统一打印布局（2026-10-21）**：Excel 路线台账的网页分页参考线与 PDF 导出共用同一份分页计划——`equipment_lifecycle/excel_print_layout.build_print_plan` 是纸张/方向/边距/缩放/分页的唯一事实来源，随版本快照以 `print_plan` 下发；浏览器 PDF 引擎（`EXCEL_PDF_ENGINE=chromium`，生产 compose 缺省）经 `excel_print_html` 渲染统一打印 HTML 后由无头 Chromium 出 PDF，网页与 PDF 排版规则必须一致，改动布局算法时两处（网页 utils/LayoutTable 与 excel_print_layout）必须同步修改；行高列宽是模板精确值（td 定高 + line-height 1 + overflow hidden），不得引入浏览器行框撑高；打印转换只作用于副本，绝不改写源 Excel 与历史快照。
- **公共 HTML→PDF 适配器（2026-10-22 上提）**：`libs/html_pdf.render_html_to_pdf` + `libs/html_pdf_worker`（worker 子进程隔离，gunicorn gevent 须干净进程）是 HTML 打印为 PDF 的唯一公共入口，Excel 统一打印与数字表单 PDF 为其两个真实调用场景；`excel_browser_pdf_service` 仅保留委托外壳（公开签名/`PdfConversionError` 语义/测试补丁目标不变）。新增调用场景直接用公共层，不得再在业务模块内私自起 Chromium；需要内容边距/页脚时必须走显式纸张参数 `paper={'format','landscape'}` + `margin`——`prefer_css_page_size` 与 `margin` 同用会被 Chromium 忽略 margin，且 HTML 内 `@page margin` 会覆盖打印 margin（置 0 即全出血）；启用页脚时 worker 自动置空默认页眉。
- **数字表单台账 PDF（2026-10-22）**：版式唯一实现为 `equipment_lifecycle/form_pdf_service.render_form_html`（模板样张与真实台账共用，预览与导出调用同一生成函数 `ledger_pdf`，保证看到的就是下载的结果）；报告式版式（A4 纵向缺省，任一矩阵列数 ≥6 整份横向），空值语义样张=「待填写」、台账=「未填写」，绝不伪装已填；标题进表格 `<caption>` / 标题+首条明细卡同 avoid 块（Chromium 不支持 break-after: avoid，分组标题不得落单页底），异常说明与判定值渲染在同一行/单元格内；端点权限沿用台账域（样张=模板 view、台账预览/导出=ledger.export），导出不拦截必填（必填终验由"完成填写"承载）。
- **数字表单协议 v2（2026-10-23 P2）**：`form_template_manage.PROTOCOL_VERSION=2`，新增可选键 textarea.`rows`(2~8，默认2)、number.`min`/`max`/`precision`(0~3，可空)、normal_abnormal.`require_desc_when_abnormal`（异常时说明必填，默认否，终验覆盖普通/明细/矩阵行三载体）；结构校验各层（顶层/分组/字段/矩阵列）未知键 fail-closed 拒绝（错误含键名与对象位置，`FormTemplateError.anchor` 携带与前端 selection 同构的定位）；不适用键出现在输入中即拒绝，规范化输出只保留适用键（前端切换类型清理属性与之对齐）；保存接受 v1/v2 输入并统一规范化为 v2（显式保存即升级，存量 v1 草稿由编辑器打开时本地升级并以 dirty 呈现），直接发布存量 v1 草稿明确拒绝，>2 的未来版本整体拒绝；读取端（版本快照/填写值校验/`missing_required_labels`/PDF）同时接受 v1/v2（新键缺省即 v1 语义），历史台账按创建时版本解释、绝不回写快照；`__desc` 键仅 normal_abnormal 字段/矩阵行允许（v2 收紧，明细行与矩阵单元格同样适用）；数字约束（范围/小数位）在保存填写值时校验、必填与异常说明在"完成填写"终验（矩阵单元格仍不做必填）；`publish-check`（POST，模板 edit 权限）为无状态预检（errors/warnings+anchor，可携带未保存 form 解决"非法草稿无法先保存"矛盾），不落库不是放行凭证——发布永远在行锁内重新全量校验。
- **维护台账双路线并行（2026-10-21）**：Excel 模板路线（`excel_*` 体系）与数字表单路线（`form_models/form_template_manage/form_ledger_services`，`created_from=form_template`）并行，由模板类型决定填写方式；数字表单模板/版本/填写值（`OperationLedgerFormTemplate/-Version/-Record`）与 Excel 专属模型完全隔离，台账表头复用 `OperationLedger`（`source_form_template` 外键 + 独立期次唯一约束）；填写值以发布时固定的稳定 field_id/组 id 为键存 JSON（`<field_id>__desc` 为异常说明键，结构 id 禁含 `__`），版本不可变保证历史台账语义不漂移；周期生成/模板分组按 `template_kind`（excel/form）分桶——两条路线模板主键分属不同表可能撞号，任何按模板 id 的键/去重/分派必须携带 kind（如组键 `form:<id>`、生成确认 `template_kinds` 平行数组）；数字表单不做 Excel 版式能力（Excel 路线的 PDF 导出/翻阅回放对 form 台账显式拒绝；数字表单有自己的报告式 PDF，见上条），改动 `ledger_period_services`/`ledger_template_group_services` 时两条路线与手工壳（对两条路线同时占位）必须一并验证。

---

## 二、目录职责与模块边界

| 前端入口 | 后端应用 | 说明 |
|---|---|---|
| `home/`、`system/`、`reminder/` | `home/`、`account/`、`setting/` | 工作台、系统管理和提醒 |
| `dataAnalysis/` | `data_analysis/` | 只读聚合，使用租户隔离缓存 |
| `departmentDutyLog/` | `department_duty_log/` | 部门值班日志（"值班日志" duty 与"事件管理" runlog 两模块已于 2026-10-11 整体下线，前后端、权限码与数据表同步移除） |
| `radioLicense/`、`stationFrequencyApproval/` | `radio_license/` | 执照和批复；批复例外见模块规则 |
| `contractAgreement/` | `contract_agreement/` | 合同协议 |
| `coopTask/` | `coop_task/` | 协作任务及附件清理 |
| `document/`、党建页面、`regulation/` | `document/`、`regulation/` | 文档、党建隔离和规章 |
| `upgrade/`、`exec/fault/`、`interference/` | 同名应用 | 技术运维业务（device 设备管理模块已于 2026-09 整体移除；原生维护台账路线与实验室原生样板已于 2026-10-20 整体移除，维护台账只保留 Excel 模板、Excel 台账与手工补录，清理见 equipment_lifecycle 迁移 0026） |
| `maintenance/` | `logs/`、`alert/` | 审计日志和系统告警 |
| 公共附件、签名能力 | `evidence/`、`signature/` | 业务入口负责权限和归属校验 |

模块级 `AGENTS.md` 记录该模块的例外、状态机和副作用细节；新增或删除模块时同步检查路由、API、权限、数据库、测试和 E2E 覆盖关系。

### 质量工程与测试边界

`scripts/`、`locustfile/` 和其他临时目录不属于生产业务模块。`quality/` 负责跨模块契约、租户隔离、权限和数据库审计、E2E、性能、灾备、发布门禁及报告；业务测试仍放在所属 Django app 或前端页面的 `__tests__/`。

测试必须执行真实代码路径，禁止读取源码或正则匹配冒充行为测试。后端测试使用 Docker 和隔离测试数据库；Playwright 只能使用开发或专用测试环境和测试账号；压测、恢复演练必须 fail-closed；敏感数据不得写入 Git 或报告；产物统一放在 `quality/reports/`。

测试分类：`stable_contract` 可纳入发布门禁，`legacy_characterization` 默认只作对照，`defect_reproduction` 不得弱化断言，`migration_validation` 校验迁移前后完整性。未执行或环境不可用必须标记 `NOT_RUN`、`BLOCKED` 或等价状态。发布门禁不得自动降低阈值、接受视觉基线或创建无期限风险例外。

代码质量由 `scripts/code_quality_check.py` 执行，并使用 `quality/baselines/code_quality_baseline.json` 做增量治理：

- 新增代码不超过 800 行，函数不超过 120 行，圈复杂度不超过 15；历史文件保底为 1000 行、250 行、25，已有超标项只能保持或减少。
- 不得扩大 baseline、删除测试或关闭检查掩盖问题；`--write-baseline` 只允许在明确评审时使用。
- JavaScript 函数边界使用 Babel AST 解析，解析失败必须由前端语法构建检查兜底；门禁同时检查工作区、暂存区和未跟踪文件。
- 语法错误、文件长度和函数长度错误必须阻断，复杂度警告可由发布门禁升级为阻断。

---

## 三、工作区保护与 Git 禁止事项

1. **禁止创建 Git commit**，除非用户明确要求。
2. **禁止 `git push --force`、`git reset --hard`、`git stash`** 等破坏性操作。
3. **禁止覆盖或回滚工作区未提交修改**。修改前必须先 `git status` + `git diff` 检查。
4. **只能修改用户在当前任务中明确授权的文件和目录**，不得自行扩大范围；未获得生产业务代码修改授权时，只允许只读调查或修改当前任务明确允许的测试、工具和报告。
5. 修改文件必须使用精准补丁或等价的局部编辑方式，禁止覆盖式重写已有大文件。

---

## 四、修改前必做流程

1. **先复现**：确认问题真实存在，不凭代码推测。
2. **读调用链**：从 URL → View → Service → Model → Task，完整理解数据流。
3. **确认根因**：定位到具体文件和行号，不猜测。
4. **最小修改**：只改必要的行，不重构无关代码。
5. **跨模块影响检查**：修改公共组件、公共 HTTP 层、权限系统、共享模型时，必须搜索所有调用方。

---

## 五、最小修改原则

- 增量改进优于大爆炸式重写。
- 向后兼容优于破坏性变更。
- 配置化（枚举 + 集合）优于散落的硬编码。同一字符串/逻辑出现 3 次以上应抽出。
- 每次修复后主动全局扫描同类问题。

## 六、解耦硬性原则

1. 跨模块调用必须通过公开的 Service、API 或事件；禁止直接访问其他模块的内部实现。
2. View、页面组件和 Celery Task 只负责入口编排，不承载核心业务规则。
3. 文件、Redis、HTTP 和第三方 SDK 等外部副作用必须集中在对应的 Service 或适配器中。
4. 新增公共抽象必须有至少两个真实调用场景，并能减少重复或隔离变化。
5. 修改公共模块、共享模型或权限租户能力时，必须搜索全部调用方并补充必要测试。

---

## 七、真实行为测试要求

1. **禁止以读取源码字符串代替行为测试**。测试必须执行真实代码路径。
2. **禁止用 `fs.readFileSync` 读取源码再做正则匹配的伪测试**。
3. 后端测试必须在 Docker 容器内执行（依赖 Django 环境 + MariaDB）。
4. 测试必须验证数据库状态及真实副作用，不能只检查 HTTP 响应码。
5. 前端测试必须执行组件渲染、hook 调用、store 变更和请求行为。

---

## 八、数据库迁移纪律

1. `makemigrations` **必须指定 app 名**（如 `makemigrations radio_license`），否则会扫描所有 app 生成意外迁移。
2. 一功能一 migration。
3. 唯一约束拆步：先洗数据，再加约束。
4. `CharField` / `TextField` **禁止 `null=True`**。
5. MariaDB 不支持部分唯一索引；逻辑删除唯一约束冲突用 `__deleted_{id}` 后缀。
6. 改 `default_auto_field` 会触发所有老表 alter id，慎用。
7. DateTimeField **禁用** `__date`/`__year`/`__month`/`__startswith`/`__icontains`，改用 `__gte`/`__lt`。
8. 迁移必须考虑历史数据兼容和回滚路径。

---

## 九、权限、角色、租户和数据范围隔离

1. **权限编码格式**：`<app>.<model>.<action>`（如 `document.document.view`）。
2. **前端路由权限**必须与后端权限编码一致。`spug_web/src/routes.js` 中的 `auth` 字段对应后端 `page_perms`。
3. **权限缓存**：`User.page_perms` 存储在 Redis `perms_{id}`=(version, perms)，修改权限后必须更新版本号。
4. **租户隔离**：所有业务模型继承 `TenantModelMixin`，`TenantModelManager` 自动过滤 `tenant_id`。公共数据（如系统设置）使用 `GLOBAL` 租户类型。
   - **例外（2026-09 起）**：`StationFrequencyApproval`（台站频率批复）为"有权限用户全局共享"——拥有 `radio_license.approval.view/add/edit/del` 的用户跨租户可见可管；`tenant_id` 仅记录创建人来源、附件归属与审计信息，不作为访问边界，权限由 `@auth` 后端独立校验。批复附件访问必须先校验父批复存在，再以 `skip_tenant_filter=True` 局部跳过 `EvidenceAttachment` 租户过滤（详见 `spug_api/apps/radio_license/AGENTS.md`）。`RadioLicense`（执照）仍为租户私有，例外不外溢；批复无责任人字段、无个人主动提醒和弹窗（popup/ack/责任人/指定提醒接收人均不存在），但有权限账户共享全局菜单红点（`approvals/badge/` 全局只读统计，2026-09 第二轮恢复）。
   - **到期菜单红点刷新机制（2026-09 第二轮起）**：执照、批复、合同三类低频到期红点统一采用事件驱动刷新（公共基类 `spug_web/src/layout/expiryBadgeStoreBase.js`）：登录进入主布局立即获取、对应业务新增/编辑/删除真实成功后获取、跨自然日恢复焦点/可见时获取；同一自然日反复切换窗口不重复请求。**禁止使用 setInterval / 循环 setTimeout 固定周期轮询**（协作任务、系统告警等实时性不同的 Store 不适用本约定，维持各自策略）。
5. **对象级权限**：`check_public_space_permission` 校验公共空间操作权限。
6. **党建隔离**：`DocumentSystemFolder` + `system_scope_validators` 实现 fail-closed 隔离。
7. **权限控制不能只隐藏前端按钮**，后端必须独立校验。

---

## 十、API、前端请求及错误提示一致性

1. **HTTP 200 可携带业务错误**：本项目 API 约定 HTTP 200 + `{"error": "..."}` 表示业务失败。前端 `libs/http.js` 拦截器会检查 `error` 字段并自动提示。
2. **前端不得将 HTTP 200 + `error` 当作成功**。
3. **同一个错误只能提示一次**：HTTP 拦截器已提示的错误，业务代码不得重复提示。
4. **成功提示必须等待后端真实成功结果**，不乐观更新。
5. API 参数校验在 View 层完成，业务错误通过 `json_response(error="...")` 返回。

---

## 十一、Celery、定时任务和幂等性要求

1. Celery 任务必须保存并重新校验用户和数据作用域（不信任调用方传入的 user_id）。
2. 异步任务必须设计幂等键。
3. 任务重试需有深度/次数限制。
4. Beat 定时任务用 `get_or_create` 保证幂等。
5. `retry_clean_pending_files` 是 `is_pending_clean` 唯一消费者，不可删。
6. 各模块 Beat Schedule 独立定义在 `celery_beat_schedule.py` 中，在 `settings.py` 合并。

### 已知 Beat Schedule

| 来源 | 用途 |
|---|---|
| `DOCUMENT_BEAT_SCHEDULE` | 分片清理、待清理文件重试 |
| `RADIO_LICENSE_BEAT_SCHEDULE` | 执照过期检查 |
| `CONTRACT_AGREEMENT_BEAT_SCHEDULE` | 合同到期提醒 |
| `LOGS_BEAT_SCHEDULE` | 审计日志归档/清理/哈希链校验 |
| `HOME_BEAT_SCHEDULE` | 公告过期同步 |
| `REMINDER_BEAT_SCHEDULE` | 提醒事项检查 |
| `ALERT_BEAT_SCHEDULE` | 磁盘/DB 监控、数据质量巡检 |
| `COOP_TASK_BEAT_SCHEDULE` | 到期任务附件清理（已完成/已作废/已删除超过 `COOP_TASK_FILE_RETENTION_DAYS`） |

---

## 十二、文件系统与外部服务补偿

1. `transaction.atomic` **不能回滚物理文件或外部系统副作用**。
2. 文件操作顺序：先写物理文件，成功后写数据库；删除时先删物理文件，成功后删数据库记录。
3. 物理文件删除失败时标记 `is_pending_clean`，由 Celery 任务异步重试。
4. 外部服务（kkFileView）调用失败需有降级处理。
5. kkFileView 回源地址：浏览器用 `KKFILEVIEW_API_URL`，容器回源用 `KKFILEVIEW_SERVER_URL`，容器名须进 `ALLOWED_HOSTS`。

---

## 十三、公共组件修改扩大回归范围

修改以下内容时，必须搜索所有调用方并评估影响：

- `spug_api/libs/` 下的所有公共模块（`middleware.py`、`tenant_base_model.py`、`tenant_utils.py`、`pagination.py`、`decorators.py`、`idempotency.py`、`utils.py`、`alert.py`）
- `spug_web/src/libs/` 下的所有公共模块（`http.js`、`router.js`、`functools.js`、`systemFolderContext.js`）
- 权限系统（`User.page_perms`、`RolePolicy`、`check_public_space_permission`）
- 共享模型（`TenantModelMixin`、`TenantModelManager`）
- 附件系统（`EvidenceAttachment`、`AttachmentService`）
- 审计日志（`record_audit_event`）

---

## 十四、启动、检查和测试命令

后端行为测试必须在 Docker 容器和隔离测试数据库中执行；`makemigrations` 必须指定 app；`tdyw-test` 连接开发库，禁止执行 `manage.py flush`。后端、前端和 Docker 的具体命令以 `spug_api/AGENTS.md`、`spug_web/AGENTS.md` 及项目脚本为准。

---

## 十五、最终汇报格式

完成任务后，汇报必须包含：

1. 审计到的正式模块清单。
2. 前后端模块对应关系概览。
3. 创建或修改的 AGENTS.md 及作用域。
4. 为什么选择或不选择模块级 AGENTS.md。
5. 提炼出的主要全局不变量。
6. 各高风险模块的特殊约束。
7. 无法确认而主动省略的内容。
8. `git diff --check` 和 `git status` 结果。
9. 确认没有修改业务代码、没有覆盖原有修改、没有创建 commit。
