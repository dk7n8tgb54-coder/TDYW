# 01 现状读取：项目上下文与可复用能力

## 仓库上下文

当前项目根目录：

```text
E:\TDYW\spug-3.0
```

项目是基于 Spug 深度定制的通导运维平台，已有多个业务模块和文档方案。

主要技术栈：

| 层级 | 技术 |
| --- | --- |
| 后端 | Python / Django 2.2 / Django View 风格接口 |
| 前端 | React 16 / Ant Design 4 / MobX |
| 数据库 | MySQL / MariaDB |
| 缓存与任务 | Redis / Celery / Celery Beat |
| 文件能力 | 已有资料库模块和 media 存储能力 |
| 权限 | 使用 `auth()` 权限装饰器 |
| 多租户 | 使用 `tenant_id`、`TenantModelMixin`、`TenantModelManager` |

## 已有相关模块

| 模块 | 路径 | 可借鉴点 |
| --- | --- | --- |
| 设备履历 | `spug_api/apps/device`、`spug_web/src/pages/device` | 业务表单、事件记录、设备字段设计 |
| 干扰管理 | `spug_api/apps/interference`、`spug_web/src/pages/interference` | 简单业务模块 CRUD、统计、权限写法 |
| 资料库 | `spug_api/apps/document`、`spug_web/src/pages/document` | 附件上传、下载、预览、Celery 任务 |
| 日检查单 | `spug_api/apps/checksheet`、`spug_web/src/pages/checksheet` | 表单、查询、导出、业务页面组织 |
| 系统设置 | `spug_api/apps/setting`、`spug_web/src/pages/system` | 系统级配置和权限入口 |

## 可复用后端能力

| 能力 | 当前做法 | 本功能用法 |
| --- | --- | --- |
| 多租户隔离 | `TenantModelMixin`、`TenantModelManager`、`apply_tenant_filter` | 执照、频率、附件、提醒均带 `tenant_id` |
| 权限校验 | `@auth('module.permission')` | 新增执照查看、新增、编辑、删除、附件下载等权限点 |
| JSON 参数解析 | `JsonParser`、`Argument` | 用于执照保存、提醒处理等接口 |
| 统一响应 | `json_response` | 所有接口保持统一响应结构 |
| 审计日志 | 非 GET 请求进入审计中间件 | 新增、编辑、删除、上传、提醒处理自动留痕 |
| 定时任务 | Celery `shared_task` + Beat schedule | 每日扫描执照到期状态 |
| 附件任务 | document 模块已有文件能力 | 优先复用资料库文件能力 |

## 可复用前端能力

| 能力 | 当前做法 | 本功能用法 |
| --- | --- | --- |
| 表格 | Ant Design `Table` | 执照列表 |
| 表单 | Ant Design `Form`、`Modal`、`Drawer` | 新增/编辑执照 |
| 日期 | Ant Design `DatePicker` | 起始日期、截止日期 |
| 标签 | Ant Design `Tag` | 正常、即将到期、已过期 |
| 提示 | Ant Design `Alert`、`message` | 到期提醒、操作反馈 |
| 上传 | Ant Design `Upload` | 执照附件 |
| 状态管理 | MobX store | 列表、筛选、详情、提醒状态 |

## 现有约束

### 后端约束

- 项目中部分日期字段使用字符串保存，新增功能建议使用 `DateField`，但接口输出需要保持前端易处理。
- 当前业务模块多使用 Django `View`，本功能优先沿用现有风格，不强行引入新的 DRF ViewSet。
- 权限编码需要和平台菜单/权限体系保持一致。

### 前端约束

- 前端使用 React 16 和 Ant Design 4。
- 页面风格应与现有 `device`、`interference` 等模块保持一致。
- 不引入新的 UI 框架。

### 附件约束

- 若直接复用资料库，需要确认业务文件和资料库空间的关联方式。
- 若使用 media 存储，需要额外实现下载鉴权，避免静态目录直出。

### 任务约束

- 定时任务依赖 Celery Beat。
- 如果生产环境未启用 Beat，则提醒只会在任务手动执行或后续替代机制中触发。

## 推荐模块位置

后端新增：

```text
spug_api/apps/radio_license/
```

前端新增：

```text
spug_web/src/pages/radioLicense/
```

文档位置：

```text
无线电台执照有效期管理功能设计方案.md
agent-loop/
```

## 与当前设计方案的关系

当前 Loop 以根目录中的《无线电台执照有效期管理功能设计方案.md》为设计输入，将其中的业务方案转化为工程执行闭环。

该设计方案负责回答：

- 要做什么功能？
- 页面长什么样？
- 数据表怎么设计？
- 接口怎么设计？
- 提醒怎么触发？
- 如何验收？

本文件负责回答：

- 项目当前有哪些能力可以复用？
- 实现时应放在哪里？
- 哪些约束需要注意？

## 退出标准

- 已明确项目技术栈。
- 已明确可复用模块。
- 已明确后端、前端、附件、任务约束。
- 已明确推荐新增模块位置。
