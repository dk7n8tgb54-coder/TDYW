# 04 实现落地：自动闭环开发记录

## 使用方式

本文件由 Agent 在开发过程中持续更新，不是一次性计划文档。

每完成一个自动闭环 Loop，都必须记录：

```text
自执行 -> 自检 -> 自修正 -> 再验证 -> 当前结论
```

## 当前功能

无线电台执照有效期管理。

## 自动闭环执行顺序

| Loop | 阶段 | 状态 | 说明 |
| --- | --- | --- | --- |
| Loop 1 | 后端基础模型 | 已完成 | 创建模块、模型、迁移 |
| Loop 2 | 后端 CRUD 接口 | 已完成 | 列表、详情、新增、编辑、删除 |
| Loop 3 | 前端基础页面 | 已完成 | 列表、表单、store |
| Loop 4 | 附件管理 | 已完成 | 上传、下载、删除、权限 |
| Loop 5 | 到期提醒 | 已完成 | 状态计算、提醒表、定时任务、提醒接口、前端展示 |
| Loop 6 | 验收与复盘 | 已完成 | 全量检查、修复、总结 |
| Loop 7 | 权限配置补充 | 已完成 | codes.js 权限条目 + permissions.sql + 数据库权限写入 |

## Loop 1：后端基础模型

### 自执行

已完成。执行内容：

- 新增 `spug_api/apps/radio_license/` 模块（`__init__.py`、`apps.py`）。
- 新增 `RadioLicense` 模型（执照主表，`tdyw_radio_license`）。
- 新增 `RadioLicenseFrequency` 模型（频率明细表，`tdyw_radio_license_frequency`）。
- 在 `spug/settings.py` 的 `INSTALLED_APPS` 中注册 `apps.radio_license`。
- 生成迁移文件 `0001_initial.py`。

关键设计决策：

- 日期字段使用 `DateField`（而非项目的 `CharField`），因为执照的 `valid_from`/`valid_to` 需要日期计算。
- `last_remind_at` 使用 `CharField(max_length=20)`，与项目 `created_at` 风格一致。
- `responsible_user_id` 使用 `IntegerField`（而非 ForeignKey），与设计文档一致，避免与 User 表强耦合。
- 索引：`tenant_id + created_at + id`（列表查询）、`tenant_id + valid_to`（到期查询）。

### 自检

已完成。检查结果：

| 检查项 | 结果 |
| --- | --- |
| Django `manage.py check` | 通过，0 issues |
| 模型可被 import | 通过 |
| 表名 `tdyw_radio_license` | 通过 |
| 表名 `tdyw_radio_license_frequency` | 通过 |
| 执照主表字段完整 | 通过（15 个字段 + frequencies related_name） |
| 频率明细表字段完整 | 通过（10 个字段） |
| `tenant_id` 字段存在 | 通过（两个模型均有） |
| 迁移文件可生成 | 通过（`0001_initial.py`） |
| `makemigrations --check` 无遗漏 | 通过 |

### 自修正

无需修正。所有检查项一次通过。

### 再验证

无需再次验证。

### 当前结论

Loop 1 已完成。模型定义符合设计文档，迁移文件已生成。

## Loop 2：后端 CRUD 接口

### 自执行

已完成。执行内容：

- 新增 `spug_api/apps/radio_license/views.py`，实现 `RadioLicenseView`（列表/新增编辑/删除）和 `RadioLicenseDetailView`（详情）。
- 新增 `spug_api/apps/radio_license/urls.py`，注册路由 `radio-license/` 和 `radio-license/<pk>/`。
- 在 `spug_api/spug/urls.py` 中注册 `path('radio-license/', include('apps.radio_license.urls'))`。

关键设计决策：

- **新增/编辑合一**：通过 `id` 有无判断，与项目现有 interference 模块风格一致。
- **软删除**：DELETE 请求设置 `is_deleted=True`，GET 请求自动过滤 `is_deleted=False`。
- **频率明细先删后建**：编辑时先删除旧频率再创建新频率，逻辑简单可靠。
- **状态自动计算**：新增/编辑时根据 `valid_to` 自动计算 `status`（normal/expiring/expired）。
- **列表和详情均返回计算字段**：`days_left` 和 `computed_status`，不依赖数据库 `status` 字段。
- **日期校验**：`valid_from > valid_to` 时返回错误。
- **租户过滤**：所有操作均使用 `apply_tenant_filter`。
- **权限编码**：`radio_license.license.view/add/edit/del`，与 03-design.md 一致。

### 自检

已完成。检查结果：

| 检查项 | 结果 |
| --- | --- |
| Django `manage.py check` | 通过，0 issues |
| views.py import 正常 | 通过 |
| URL `/radio-license/` 解析到 RadioLicenseView | 通过 |
| URL `/radio-license/1/` 解析到 RadioLicenseDetailView | 通过 |
| Argument type=list 支持 | 通过（parser.py 原生支持） |
| 权限编码符合 03-design.md | 通过 |
| 软删除逻辑 | 通过 |
| 租户过滤 | 通过 |

### 自修正

无需修正。所有检查项一次通过。

### 再验证

无需再次验证。

### 当前结论

Loop 2 已完成。CRUD 接口已实现，路由已注册，权限和租户过滤已接入。

## Loop 3：前端基础页面

### 自执行

已完成。执行内容：

- 新增 `spug_web/src/pages/radioLicense/store.js`，MobX 状态管理，对接后端 `/api/radio-license/` CRUD 接口。
- 新增 `spug_web/src/pages/radioLicense/index.js`，页面入口，含筛选区（台站/用途/状态/截止日期范围）。
- 新增 `spug_web/src/pages/radioLicense/Table.js`，列表表格，含状态标签、剩余天数、频率展示、操作按钮。
- 新增 `spug_web/src/pages/radioLicense/Form.js`，新增/编辑表单 + 详情查看，含动态频率行（Form.List）。
- 在 `spug_web/src/routes.js` 中注册路由（`/radio-license`，`SafetyCertificateOutlined` 图标）。

关键设计决策：

- **筛选后端执行**：所有筛选参数传给后端 API，不在前端过滤（与 interference 的纯前端过滤不同）。
- **详情和表单合一组件**：Form.js 同时处理详情查看和新增/编辑，通过 `viewMode` state 切换。
- **详情弹窗通过 detailVisible 控制**：双击行或点击"查看"按钮触发，与 formVisible 独立。
- **状态标签**：正常=绿色、即将到期=橙色、已过期=红色，与后端 computed_status 对应。
- **频率显示**：列表中只显示主频率 + "等 N 个"，详情中显示全部。
- **频率表单**：使用 `Form.List` 实现动态行，默认 1 行，支持添加/删除。
- **分页后端执行**： pageNum/pageSize 传给后端 API，后端返回 total。

### 自检

已完成。检查结果：

| 检查项 | 结果 |
| --- | --- |
| IDE Lint 检查 | 通过，0 错误 |
| 前端字段与后端接口对照 | 通过，7 个字段全部对齐 |
| 筛选参数与后端 GET 参数对照 | 通过，4 个筛选条件对齐 |
| 权限编码与 03-design.md 一致 | 通过，radio_license.license.view/add/edit/del |
| 路由注册正确 | 通过，/radio-license 路径 |
| 动态频率表单（Form.List） | 通过 |
| 状态标签展示 | 通过，3 种颜色映射 |
| 详情查看入口 | 通过，双击行 + 操作按钮 |

### 自修正

修正 2 项：

1. Form.js 导入了 `Popconfirm` 但未使用 → 已删除。
2. index.js 只在 `formVisible` 时渲染 Form，双击查看时 `detailVisible=true` 但 Form 不渲染 → 已添加 `{store.detailVisible && <ComForm/>}`。

### 再验证

修正后重新 lint 检查，0 错误。

### 当前结论

Loop 3 已完成。前端页面已实现，路由已注册，与后端接口对接完整。

## Loop 4：附件管理

### 自执行

已完成。执行内容：

- 新增 `RadioLicenseAttachment` 模型（`tdyw_radio_license_attachment`），含 `attachment_type`/`file_name`/`file_path`/`file_size`/`file_ext`/`uploaded_by` 等字段。
- 新增 `ALLOWED_FILE_EXTENSIONS` 白名单（17 种扩展名）和 `MAX_FILE_SIZE_MB = 50`。
- 新增 `AttachmentListView`（GET 列表 + POST 上传），含文件类型/大小校验、文件名清洗、UUID 唯一文件名。
- 新增 `AttachmentDownloadView`（GET 鉴权下载），含 `os.path.realpath` 路径穿越防护 + 租户过滤 + 执照存在性校验。
- 新增 `AttachmentDeleteView`（DELETE 删除），含租户过滤 + 执照权限校验 + 物理文件删除。
- 后端列表/详情接口增加 `attachment_count` 字段。
- 前端新增 `AttachmentList.js` 组件，支持选择附件类型、上传、列表展示、下载、删除。
- 前端详情弹窗（Form.js 详情模式）集成附件列表。
- 前端列表（Table.js）增加附件数列和"附件"操作按钮。
- 生成迁移文件 `0002_add_attachment_model.py`。

关键设计决策：

- **存储方案：独立 MEDIA 存储**，与 upgrade 模块一致（`MEDIA_ROOT/radio_license/attachments/YYYYMM/uuid.ext`），不复用资料库。
- **下载鉴权**：`@auth` + `apply_tenant_filter` + 路径穿越防护，前端通过 `x-token` GET 参数鉴权下载。
- **删除权限**：使用 `radio_license.attachment.upload` 权限（上传者可删除自己的附件）。
- **附件类型**：license/permit/approval/other 四种，前端 Select 选择，后端白名单校验。
- **文件名清洗**：`os.path.basename` + 移除 `..`/`/`/`\`/`\x00`，杜绝路径穿越。
- **UUID 文件名**：避免文件名冲突和信息泄露。
- **附件列表租户过滤**：附件查询显式使用 `apply_tenant_filter`，不依赖执照的隐式过滤。

### 自检

已完成。检查结果：

| 检查项 | 结果 |
| --- | --- |
| IDE Lint 检查 | 通过，0 错误 |
| Django `manage.py check` | 通过，0 issues |
| `makemigrations --check` 无遗漏 | 通过 |
| URL 解析（list/download/delete） | 通过 |
| 附件类型白名单校验 | 通过（`license`/`permit`/`approval`/`other`） |
| 文件类型白名单校验 | 通过（17 种扩展名） |
| 文件大小限制 | 通过（50MB） |
| 文件名清洗（路径穿越防护） | 通过 |
| 下载鉴权（@auth + apply_tenant_filter + realpath） | 通过 |
| 删除鉴权（@auth + apply_tenant_filter + 执照校验） | 通过 |
| 附件列表租户过滤 | 通过 |
| 前端字段与后端接口对齐 | 通过 |
| 前端 x-token 下载鉴权 | 通过（项目中间件支持 GET 参数 x-token） |
| 详情弹窗集成附件列表 | 通过 |
| 列表附件数列 | 通过 |

### 自修正

修正 1 项：

1. 附件列表 GET 接口未显式对附件查询做租户过滤 → 已添加 `apply_tenant_filter(attachments, request.user)`（虽然执照校验已经间接过滤，但显式过滤更安全）。

### 再验证

修正后 Django check 0 issues，Lint 0 错误。

### 当前结论

Loop 4 已完成。附件上传/下载/删除接口已实现，前端组件已集成，安全校验到位。

## Loop 5：到期提醒

### 自执行

已完成。执行内容：

- 新增 `RadioLicenseReminder` 模型（`tdyw_radio_license_reminder`），含 `remind_type`/`remind_date`/`days_left`/`title`/`content`/`receiver_user_id`/`receiver_user_name`/`is_read`/`is_handled` 等字段。
- 新增 `REMIND_LEVELS` 常量（45/30/15/7/1 天映射）、`EXPIRED_REMIND_TYPE`、`REMIND_TYPE_MAP`。
- 实现 `calculate_license_status` 状态计算函数：days_left < 0 → expired，days_left <= 45 → expiring，days_left > 45 → normal。
- 实现 Celery 任务 `scan_radio_license_expiration`：
  - 扫描所有未删除执照
  - 更新执照 status 字段
  - 对命中 45/30/15/7/1 天节点的执照生成分级提醒
  - 对已过期执照生成 expired 提醒
  - 去重：同执照 + 同类型 + 同接收人只生成一条
  - 接收人优先级：责任人 > 创建人
- 新增 `celery_beat_schedule.py`：每日 08:00 执行扫描任务
- 在 `spug/settings.py` 中合并 Beat 配置和任务路由
- 在 `spug/celery.py` 中显式导入 radio_license 任务
- 新增 `ReminderListView`（GET 提醒列表，含租户过滤 + 接收人过滤）
- 新增 `ReminderHandleView`（POST 已读/已处理，含权限校验）
- 前端新增 `ReminderList.js` 组件（提醒表格 + 已读/已处理按钮）
- 前端详情弹窗集成提醒记录
- 前端列表页增加未读提醒 Alert 提示条
- 前端列表页增加未读提醒 Alert 提示条
- 修正状态计算阈值：30天 → 45天（views.py 3处 + Table.js + Form.js）
- 生成迁移文件 `0003_add_reminder_model.py`

#### 增量：右下角弹窗通知提醒

- 新增 `ReminderNotification.js` 组件（`spug_web/src/components/ReminderNotification.js`）：
  - 使用 Ant Design `notification` API，`placement: 'bottomRight'`
  - 组件挂载后延迟 2 秒拉取当前用户未读提醒并弹出
  - 5 分钟轮询检查新提醒
  - `sessionStorage` 记录已弹出提醒 ID，同一会话不重复弹出
  - 弹窗内容：提醒类型标签 + 标题 + 内容 + 剩余天数
  - 点击弹窗跳转执照详情页（`/radio-license?id=xxx`）
  - 关闭弹窗不等于已读，已读状态仍由提醒处理接口控制
  - 纯逻辑组件，`return null`
- 挂载到 `Layout/index.js`（全局生效）
- 移除 `radioLicense/index.js` 中的 Alert 横幅和 `isMounted` hack（全局弹窗已覆盖）

关键设计决策：

- **状态计算阈值 45 天**：与设计文档一致，days_left <= 45 为 expiring
- **提醒去重**：同执照 + 同提醒类型 + 同接收人 = 只生成一条，续期后可进入新周期
- **接收人优先级**：责任人优先，为空时回退到创建人
- **不广播全租户**：每条提醒只发给一个人（责任人或创建人）
- **已过期提醒**：对 days_left < 0 的执照生成 expired 类型提醒（去重保证只一次）
- **权限编码**：`radio_license.reminder.handle`（处理提醒）
- **Celery 队列**：`radio_license`（独立队列，不影响文档任务）
- **Beat 调度**：每天 08:00 crontab(hour=8, minute=0)

### 自检

已完成。检查结果：

| 检查项 | 结果 |
| --- | --- |
| IDE Lint 检查 | 通过，0 错误 |
| Django `manage.py check` | 通过，0 issues |
| `makemigrations --check` 无遗漏 | 通过 |
| URL 解析（reminders/ + reminders/handle/） | 通过 |
| RadioLicenseReminder 字段完整 | 通过（12 个字段全部匹配 03-design.md） |
| 状态计算边界测试（8 个场景） | 全部通过 |
| Celery 任务导入 | 通过 |
| Beat Schedule 配置 | 通过（radio-license-scan-expiration） |
| 任务路由配置 | 通过（radio_license 队列） |
| 提醒去重逻辑 | 通过（同执照+同类型+同接收人） |
| 接收人优先级 | 通过（责任人>创建人） |
| 提醒接口租户过滤 | 通过 |
| 提醒接口权限校验 | 通过 |
| 前端字段对齐 | 通过 |
| 右下角弹窗通知 | 待增量验证 |

### 自修正

修正 2 项：

1. 状态计算阈值从 30 天改为 45 天（3 处 views.py + Table.js + Form.js），与设计文档一致
2. 前端 ReminderList 中 `r.license` 改为 `r.license_id`（to_dict 返回 ForeignKey 的 attname = license_id）

### 再验证

修正后重新运行边界测试，8 个场景全部通过。Django check 0 issues。Lint 0 错误。

### 当前结论

Loop 5 已完成。提醒模型、状态计算、扫描任务、提醒接口、前端展示全部实现，边界测试通过。

增量需求：补充右下角弹窗通知提醒。实现完成后需更新本节自执行、自检和再验证记录。

## Loop 6：验收与复盘

### 自执行

已完成。执行内容：

- Django check：0 issues
- makemigrations --check：No changes detected
- 状态计算边界测试：8/8 PASS
- 提醒去重测试：扫描两次不重复生成 — PASS
- 提醒接收人优先级：责任人为空时回退到创建人 — PASS
- 权限 @auth 审查：10 个接口方法全部有 @auth — PASS
- 前端 lint：0 错误
- 前端构建：exitCode=0
- 前端代码审查：权限/状态标签/去重/弹窗 — PASS
- Celery 任务手动触发：去重正常
- 弹窗去重修复：从模块级 Set 改为 sessionStorage + token key 去重，重新登录后可再弹

### 自检

全部通过。详见 05-verify.md。

### 自修正

修正 1 项：

1. `views.py:69` 频率列表赋值重复 → 已删除重复行（代码质量问题，不影响功能）

修正 2 项（本次会话中的修复）：

2. `ReminderNotification.js` 去重策略：模块级 Set → sessionStorage + token key（用户反馈刷新不弹）
3. `ReminderNotification.js` 去重策略：纯 sessionStorage → sessionStorage + token key（用户反馈希望重新登录后再弹）

### 再验证

修正后所有验证项通过。

### 当前结论

Loop 6 已完成。所有 P0 验收项通过，功能完整。

## Loop 7：权限配置补充

### 自执行

已完成。执行内容：

- 在 `spug_web/src/pages/system/role/codes.js` 中新增 `radio_license` 模块条目，包含 3 个子页面（license/attachment/reminder）和 8 个权限点。
- 新增 `spug_api/apps/radio_license/permissions.sql`，仿 `document/permissions.sql` 风格，为指定角色添加全部 radio_license 权限。
- 在数据库中为现有 2 个角色（ID=1 林杰、ID=2 通信科员工）写入 radio_license 权限，并清除权限缓存。

权限码结构（3 级格式：`{module}.{page}.{perm}`）：

| 权限码 | 中文名称 |
| --- | --- |
| `radio_license.license.view` | 查看执照 |
| `radio_license.license.add` | 新增执照 |
| `radio_license.license.edit` | 编辑执照 |
| `radio_license.license.del` | 删除执照 |
| `radio_license.license.export` | 导出清单 |
| `radio_license.attachment.upload` | 上传附件 |
| `radio_license.attachment.download` | 下载附件 |
| `radio_license.reminder.handle` | 处理提醒 |

### 自检

已完成。检查结果：

| 检查项 | 结果 |
| --- | --- |
| 后端 @auth 权限码 vs codes.js | 一致，7/7 已实现权限码匹配（export 为预留） |
| 前端权限编码 vs codes.js | 一致，AuthDiv/AuthButton/hasPermission 全部匹配 |
| Django check | 通过，0 issues |
| 前端 lint | 通过，0 错误 |
| permissions.sql 语法正确 | 通过，与 document/permissions.sql 风格一致 |
| 数据库权限已写入 | 通过，2 个角色均已有 radio_license 权限 |
| 权限缓存已清除 | 通过，2 个用户的缓存已清除 |

### 自修正

无需修正。所有检查项一次通过。

### 再验证

无需再次验证。

### 当前结论

Loop 7 已完成。权限配置已补齐，后端 @auth 编码与前端权限编码与 codes.js 完全一致。

## 文件变更记录

| 时间 | Loop | 文件 | 变更说明 |
| --- | --- | --- | --- |
| 2026-06-16 | Loop 1 | `spug_api/apps/radio_license/__init__.py` | 新增模块 |
| 2026-06-16 | Loop 1 | `spug_api/apps/radio_license/apps.py` | 新增 AppConfig |
| 2026-06-16 | Loop 1 | `spug_api/apps/radio_license/models.py` | 新增 RadioLicense、RadioLicenseFrequency 模型 |
| 2026-06-16 | Loop 1 | `spug_api/apps/radio_license/migrations/__init__.py` | 新增空文件 |
| 2026-06-16 | Loop 1 | `spug_api/apps/radio_license/migrations/0001_initial.py` | 自动生成迁移 |
| 2026-06-16 | Loop 1 | `spug_api/spug/settings.py` | INSTALLED_APPS 添加 apps.radio_license |
| 2026-06-16 | Loop 2 | `spug_api/apps/radio_license/views.py` | 新增 RadioLicenseView + RadioLicenseDetailView |
| 2026-06-16 | Loop 2 | `spug_api/apps/radio_license/urls.py` | 新增路由注册 |
| 2026-06-16 | Loop 2 | `spug_api/spug/urls.py` | 注册 radio-license 路由 |
| 2026-06-16 | Loop 3 | `spug_web/src/pages/radioLicense/store.js` | 新增 MobX store |
| 2026-06-16 | Loop 3 | `spug_web/src/pages/radioLicense/index.js` | 新增页面入口+筛选区 |
| 2026-06-16 | Loop 3 | `spug_web/src/pages/radioLicense/Table.js` | 新增列表表格 |
| 2026-06-16 | Loop 3 | `spug_web/src/pages/radioLicense/Form.js` | 新增表单+详情 |
| 2026-06-16 | Loop 3 | `spug_web/src/routes.js` | 注册 /radio-license 路由 |
| 2026-06-16 | Loop 4 | `spug_api/apps/radio_license/models.py` | 新增 RadioLicenseAttachment 模型 + 常量 |
| 2026-06-16 | Loop 4 | `spug_api/apps/radio_license/migrations/0002_add_attachment_model.py` | 自动生成迁移 |
| 2026-06-16 | Loop 4 | `spug_api/apps/radio_license/views.py` | 新增 AttachmentListView/DownloadView/DeleteView |
| 2026-06-16 | Loop 4 | `spug_api/apps/radio_license/urls.py` | 注册附件路由 |
| 2026-06-16 | Loop 4 | `spug_web/src/pages/radioLicense/AttachmentList.js` | 新增附件列表组件 |
| 2026-06-16 | Loop 4 | `spug_web/src/pages/radioLicense/Form.js` | 详情弹窗集成附件列表 |
| 2026-06-16 | Loop 4 | `spug_web/src/pages/radioLicense/Table.js` | 新增附件数列+附件按钮 |
| 2026-06-16 | Loop 5 | `spug_api/apps/radio_license/models.py` | 新增 RadioLicenseReminder 模型 + 提醒常量 |
| 2026-06-16 | Loop 5 | `spug_api/apps/radio_license/migrations/0003_add_reminder_model.py` | 自动生成迁移 |
| 2026-06-16 | Loop 5 | `spug_api/apps/radio_license/tasks.py` | 新增到期扫描 Celery 任务 + 状态计算函数 |
| 2026-06-16 | Loop 5 | `spug_api/apps/radio_license/celery_beat_schedule.py` | 新增 Beat 定时配置 |
| 2026-06-16 | Loop 5 | `spug_api/apps/radio_license/views.py` | 新增 ReminderListView/HandleView + 修正 30→45 阈值 |
| 2026-06-16 | Loop 5 | `spug_api/apps/radio_license/urls.py` | 注册提醒路由 |
| 2026-06-16 | Loop 5 | `spug_api/spug/settings.py` | 合并 Beat 配置 + 任务路由 |
| 2026-06-16 | Loop 5 | `spug_api/spug/celery.py` | 导入 radio_license 任务 |
| 2026-06-16 | Loop 5 | `spug_web/src/pages/radioLicense/ReminderList.js` | 新增提醒列表组件 |
| 2026-06-16 | Loop 5 | `spug_web/src/pages/radioLicense/Form.js` | 详情弹窗集成提醒记录 + 修正 30→45 |
| 2026-06-16 | Loop 5 | `spug_web/src/pages/radioLicense/Table.js` | 修正 30→45 天阈值 |
| 2026-06-16 | Loop 5 | `spug_web/src/pages/radioLicense/index.js` | 新增未读提醒 Alert 提示条 |
| 2026-06-16 | Loop 5+ | `spug_web/src/components/ReminderNotification.js` | 新增全局右下角弹窗通知组件 |
| 2026-06-16 | Loop 5+ | `spug_web/src/layout/index.js` | 挂载 ReminderNotification 组件 |
| 2026-06-16 | Loop 5+ | `spug_web/src/pages/radioLicense/index.js` | 移除 Alert 横幅和 isMounted hack |
| 2026-06-16 | Loop 6 | `spug_api/apps/radio_license/views.py` | 删除重复的频率列表赋值行 |
| 2026-06-16 | Loop 6 | `spug_web/src/components/ReminderNotification.js` | 去重策略改为 sessionStorage + token key |
| 2026-06-16 | Loop 7 | `spug_web/src/pages/system/role/codes.js` | 新增 radio_license 权限配置（3 子页面 + 8 权限点） |
| 2026-06-16 | Loop 7 | `spug_api/apps/radio_license/permissions.sql` | 新增权限初始化 SQL 脚本 |

## 关键决策记录

| 决策 | 原因 | 影响 |
| --- | --- | --- |
| 使用独立 `radio_license` 模块 | 避免与设备、干扰等模块职责混杂 | 模块边界清晰 |
| 使用频率明细表 | 支持一个执照多个频率并便于查询 | 比逗号字符串更可维护 |
| 提醒独立成记录表 | 支持已读、已处理、去重和追溯 | 方便后续扩展通知 |
| 附件使用独立 MEDIA 存储 | 与 upgrade 模块一致，不复用资料库 | 简单可靠，不引入复杂依赖 |
| 附件删除权限=上传权限 | 上传者可删除自己的附件 | 与 upgrade 模块一致 |

## 阻塞项记录

| 问题 | 是否阻塞 | 处理方式 |
| --- | --- | --- |
| 附件使用资料库还是 media | 否 | 已选择独立 MEDIA 存储，与 upgrade 模块一致 |
| 菜单挂载位置 | 否 | 默认挂到设备管理或无线电管理 |
| 是否接首页待办 | 否 | 本期预留，不阻塞基础功能 |
