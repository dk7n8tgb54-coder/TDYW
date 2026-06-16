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
| Loop 4 | 附件管理 | 待执行 | 上传、下载、删除、权限 |
| Loop 5 | 到期提醒 | 待执行 | 状态计算、提醒表、定时任务 |
| Loop 6 | 验收与复盘 | 待执行 | 全量检查、修复、总结 |

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

待记录。

计划动作：

- 新增附件模型。
- 实现上传接口。
- 实现下载接口。
- 实现删除接口。
- 前端接入附件列表和上传组件。

### 自检

待记录。

检查项：

- 附件类型可保存。
- 上传大小和类型校验有效。
- 下载必须鉴权。
- 删除后附件列表刷新。

### 自修正

待记录。

### 再验证

待记录。

### 当前结论

待执行。

## Loop 5：到期提醒

### 自执行

待记录。

计划动作：

- 新增提醒模型。
- 实现状态计算函数。
- 实现定时扫描任务。
- 接入 Celery Beat。
- 前端展示到期提醒。

### 自检

待记录。

检查项：

- 31 天后为正常。
- 30 天后为即将到期。
- 今天到期剩余 0 天。
- 昨天到期为已过期。
- 重复执行任务不重复提醒。

### 自修正

待记录。

### 再验证

待记录。

### 当前结论

待执行。

## Loop 6：验收与复盘

### 自执行

待记录。

计划动作：

- 按 `05-verify.md` 全量验证。
- 修复所有 P0 失败项。
- 更新 `06-retro.md`。

### 自检

待记录。

### 自修正

待记录。

### 再验证

待记录。

### 当前结论

待执行。

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

## 关键决策记录

| 决策 | 原因 | 影响 |
| --- | --- | --- |
| 使用独立 `radio_license` 模块 | 避免与设备、干扰等模块职责混杂 | 模块边界清晰 |
| 使用频率明细表 | 支持一个执照多个频率并便于查询 | 比逗号字符串更可维护 |
| 提醒独立成记录表 | 支持已读、已处理、去重和追溯 | 方便后续扩展通知 |

## 阻塞项记录

| 问题 | 是否阻塞 | 处理方式 |
| --- | --- | --- |
| 附件使用资料库还是 media | 是，影响 Loop 4 | 开发 Loop 4 前确认 |
| 菜单挂载位置 | 否 | 默认挂到设备管理或无线电管理 |
| 是否接首页待办 | 否 | 本期预留，不阻塞基础功能 |
