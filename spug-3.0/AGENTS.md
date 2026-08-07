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

### 关键约束

- **antd 4.21.5**：Modal/Drawer 用 `visible`（非 `open`）；表单用 `Form.useForm()`。
- **MobX legacy decorators**：`@observable` / `@action` 装饰器语法，Babel 需 `@babel/plugin-proposal-decorators`（`legacy: true`）+ `@babel/plugin-proposal-class-properties`。
- **MariaDB 10.8**：不支持部分唯一索引；`LIKE '%xxx'` 前缀通配无法走索引；不支持 `JSON_FIELD` 的部分查询操作。
- **Python 3.10**：可使用 match-case，但项目代码风格以传统 if/elif 为主。

---

## 二、正式业务模块及前后端对应关系

### 模块矩阵

| 模块 | 前端入口 (`spug_web/src/pages/`) | 后端应用 (`spug_api/apps/`) | 主要模型 | 权限前缀 | 物理文件副作用 | Celery/异步 |
|---|---|---|---|---|---|---|
| 工作台/首页 | `home/` | `home/` | Navigation, Notice | `home.announcement`, `home.navigation` | 无 | HOME_BEAT_SCHEDULE（公告过期同步） |
| 数据分析 | `dataAnalysis/` | `data_analysis/` | 无（纯只读聚合） | `data_analysis.*` | 无 | Redis 60s 缓存 |
| 部门值班日志 | `departmentDutyLog/` | `department_duty_log/` | DepartmentDutyLog, DutyLogSign | `department_duty_log.*` | 附件(evidence) | 无 |
| 无线电台执照 | `radioLicense/` | `radio_license/` | RadioLicense | `radio_license.license.*` | 附件(evidence) | RADIO_LICENSE_BEAT_SCHEDULE（过期检查） |
| 台站频率批复 | `stationFrequencyApproval/` | `radio_license/`（同应用） | StationFrequencyApproval | `radio_license.approval.*` | 附件(evidence) | 同上 |
| 合同协议 | `contractAgreement/` | `contract_agreement/` | ContractAgreement | `contract_agreement.agreement.*` | 附件(evidence) | CONTRACT_AGREEMENT_BEAT_SCHEDULE |
| 资料库/文档管理 | `document/` | `document/` | DocumentFilePrivate/Public, DocumentFolderPrivate/Public, DocumentTransfer, DocumentSystemFolder | `document.document.*`, `document.party_building_document.*` | **是**（文件存储） | 分片上传、合并、清理、异步复制 |
| 党建工作 | `document/PartyBuildingDocumentsIndex.js` | `document/`（system_scope） | DocumentSystemFolder | `document.party_building_document.*` | **是** | 同文档模块 |
| 规章管理 | `regulation/` | `regulation/` | Regulation | `document.regulation.*` | **是**（独立 `storage.py`） | 无 |
| 跨日事项跟踪 | `runlog/` | `runlog/` | RunLog | `runlog.runlog.*` | 无 | 无 |
| 设备台账 | `device/` | `device/` | DeviceResume | `device.device_resume.*` | 无 | 无 |
| 设备履历 | `device/`（同目录） | `device/` | DeviceHistory | `device.device_history.*` | 无 | 无 |
| 系统升级 | `upgrade/` | `upgrade/` | UpgradeRecord, UpgradePlan, UpgradeStatistics | `upgrade.*` | 无 | 无 |
| 故障管理 | `exec/fault/` | `fault/` | FaultRecord, FaultPart | `fault.faultrecord.*`, `fault.faultpart.*` | 无 | 无 |
| 干扰管理 | `interference/` | `interference/` | InterferenceRecord | `interference.*` | 附件(evidence) | 无 |
| 值班日志 | `duty/` | `duty/` | DutyRecord | `duty.duty.*` | 无 | 无 |
| 公告管理 | `system/` | `home/` | Notice | `home.announcement.*` | 无 | HOME_BEAT_SCHEDULE |
| 提醒事项 | `reminder/` | `reminder/` | Reminder | `home.reminder.*` | 无 | REMINDER_BEAT_SCHEDULE |
| 操作日志 | `maintenance/` | `logs/` | AuditLog, AuditLogSequence | `system.audit.*` | 无 | LOGS_BEAT_SCHEDULE（归档/清理/哈希链校验） |
| 系统告警 | `maintenance/` | `alert/` | AlertRule, AlertRecord | `system.alert.*` | 无 | ALERT_BEAT_SCHEDULE（磁盘/DB 监控） |
| 账户管理 | `system/` | `account/` | User, Role, RolePolicy, Tenant, LoginLog | `system.account.*`, `system.role.*`, `system.tenant.*`, `system.login.*` | 无 | 无 |
| 系统设置 | `system/` | `setting/` | AppSetting | `system.setting.*` | 无 | 无 |
| 附件系统 | （内嵌于多模块） | `evidence/` | EvidenceAttachment | （各模块自带） | **是**（文件存储） | 无 |
| 签名系统 | （内嵌） | `signature/` | AccountSignature, SignatureUsage, EvidenceEvent | （各模块自带） | 无 | 无 |

### 非正式模块（不纳入规则覆盖范围）

`backups/`、`scripts/`（运维脚本）、`locustfile/`（压测）、`hy3扫描边界/`、`loop engineering/`、`outputs/`、`Trae/`、`dev/` 以及根目录下的各种 `*_AUDIT_REPORT.md` 均为临时产物或实验目录，不是正式业务模块。

---

## 三、工作区保护与 Git 禁止事项

1. **禁止创建 Git commit**，除非用户明确要求。
2. **禁止 `git push --force`、`git reset --hard`、`git stash`** 等破坏性操作。
3. **禁止覆盖或回滚工作区未提交修改**。修改前必须先 `git status` + `git diff` 检查。
4. **本次任务只能新增或修改 `AGENTS.md` 文件**，不得修改业务代码、配置、依赖、测试、数据库或构建产物。
5. 修改文件时使用 `replace_in_file` 做精准编辑，禁止用 `write_to_file` 覆盖大文件（除非新建文件）。

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

---

## 六、真实行为测试要求

1. **禁止以读取源码字符串代替行为测试**。测试必须执行真实代码路径。
2. **禁止用 `fs.readFileSync` 读取源码再做正则匹配的伪测试**。
3. 后端测试必须在 Docker 容器内执行（依赖 Django 环境 + MariaDB）。
4. 测试必须验证数据库状态及真实副作用，不能只检查 HTTP 响应码。
5. 前端测试必须执行组件渲染、hook 调用、store 变更和请求行为。

---

## 七、数据库迁移纪律

1. `makemigrations` **必须指定 app 名**（如 `makemigrations radio_license`），否则会扫描所有 app 生成意外迁移。
2. 一功能一 migration。
3. 唯一约束拆步：先洗数据，再加约束。
4. `CharField` / `TextField` **禁止 `null=True`**。
5. MariaDB 不支持部分唯一索引；逻辑删除唯一约束冲突用 `__deleted_{id}` 后缀。
6. 改 `default_auto_field` 会触发所有老表 alter id，慎用。
7. DateTimeField **禁用** `__date`/`__year`/`__month`/`__startswith`/`__icontains`，改用 `__gte`/`__lt`。
8. 迁移必须考虑历史数据兼容和回滚路径。

---

## 八、权限、角色、租户和数据范围隔离

1. **权限编码格式**：`<app>.<model>.<action>`（如 `document.document.view`）。
2. **前端路由权限**必须与后端权限编码一致。`spug_web/src/routes.js` 中的 `auth` 字段对应后端 `page_perms`。
3. **权限缓存**：`User.page_perms` 存储在 Redis `perms_{id}`=(version, perms)，修改权限后必须更新版本号。
4. **租户隔离**：所有业务模型继承 `TenantModelMixin`，`TenantModelManager` 自动过滤 `tenant_id`。公共数据（如系统设置）使用 `GLOBAL` 租户类型。
5. **对象级权限**：`check_public_space_permission` 校验公共空间操作权限。
6. **党建隔离**：`DocumentSystemFolder` + `system_scope_validators` 实现 fail-closed 隔离。
7. **权限控制不能只隐藏前端按钮**，后端必须独立校验。

---

## 九、API、前端请求及错误提示一致性

1. **HTTP 200 可携带业务错误**：本项目 API 约定 HTTP 200 + `{"error": "..."}` 表示业务失败。前端 `libs/http.js` 拦截器会检查 `error` 字段并自动提示。
2. **前端不得将 HTTP 200 + `error` 当作成功**。
3. **同一个错误只能提示一次**：HTTP 拦截器已提示的错误，业务代码不得重复提示。
4. **成功提示必须等待后端真实成功结果**，不乐观更新。
5. API 参数校验在 View 层完成，业务错误通过 `json_response(error="...")` 返回。

---

## 十、Celery、定时任务和幂等性要求

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

---

## 十一、文件系统与外部服务补偿

1. `transaction.atomic` **不能回滚物理文件或外部系统副作用**。
2. 文件操作顺序：先写物理文件，成功后写数据库；删除时先删物理文件，成功后删数据库记录。
3. 物理文件删除失败时标记 `is_pending_clean`，由 Celery 任务异步重试。
4. 外部服务（kkFileView）调用失败需有降级处理。
5. kkFileView 回源地址：浏览器用 `KKFILEVIEW_API_URL`，容器回源用 `KKFILEVIEW_SERVER_URL`，容器名须进 `ALLOWED_HOSTS`。

---

## 十二、公共组件修改扩大回归范围

修改以下内容时，必须搜索所有调用方并评估影响：

- `spug_api/libs/` 下的所有公共模块（`middleware.py`、`tenant_base_model.py`、`tenant_utils.py`、`pagination.py`、`decorators.py`、`idempotency.py`、`utils.py`、`alert.py`）
- `spug_web/src/libs/` 下的所有公共模块（`http.js`、`router.js`、`functools.js`、`systemFolderContext.js`）
- 权限系统（`User.page_perms`、`RolePolicy`、`check_public_space_permission`）
- 共享模型（`TenantModelMixin`、`TenantModelManager`）
- 附件系统（`EvidenceAttachment`、`AttachmentService`）
- 审计日志（`record_audit_event`）

---

## 十三、启动、检查和测试命令

### 后端（Docker 容器内）

```bash
# Django check
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check

# 语法检查
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python -m py_compile <file_path>

# 生成迁移（必须指定 app）
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py makemigrations <app_name>

# 执行迁移
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py migrate

# 运行测试
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py test apps.<app>.tests --noinput
```

> **注意**：Django test runner 创建 test_spug 可能因迁移顺序失败，可用 `--keepdb` 或手动创建 test_spug。`tdyw-test` 容器连的是 dev 库，**绝对禁止** `manage.py flush`。

### 前端

```bash
cd spug_web
npm install
npm start          # 开发服务器
npm run build      # 生产构建
```

### JS 语法验证（项目使用 legacy decorators）

```bash
# node --check 不支持 ESM import，需用 @babel/core 脚本
# 必须加 @babel/plugin-proposal-decorators (legacy: true)
# 必须加 @babel/plugin-proposal-class-properties
```

### Docker

```bash
# 重启容器使代码生效（Django dev server 不自动热更新）
docker restart tdyw

# bind mount 容器（tdyw-test）也需重启才能看到最新代码
docker restart tdyw-test
```

---

## 十四、最终汇报格式

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
