# spug_api/AGENTS.md - 后端工程规则

> 本文件覆盖 `spug_api/` 下所有 Django 应用的共同规则。模块级特殊规则见各模块目录下的 `AGENTS.md`（目前仅 `apps/document/`）。

---

## 一、架构分层

```
spug_api/
├── spug/              # Django 项目配置
│   ├── settings.py    # INSTALLED_APPS, MIDDLEWARE, DATABASES, CELERY, CACHE
│   ├── urls.py        # 根 URL 路由
│   ├── wsgi.py        # WSGI 入口
│   └── asgi.py        # ASGI 入口（Channels 4）
├── apps/              # 业务应用
│   ├── account/       # 用户、角色、租户、登录日志
│   ├── alert/         # 系统告警、数据质量巡检
│   ├── contract_agreement/  # 合同协议
│   ├── data_analysis/ # 数据分析（纯只读聚合）
│   ├── department_duty_log/ # 部门值班日志
│   ├── device/        # 设备台账、设备履历
│   ├── document/      # 资料库/文档管理（含党建隔离）
│   ├── duty/          # 值班日志
│   ├── evidence/      # 附件系统（通用多态附件）
│   ├── fault/         # 故障管理
│   ├── home/          # 工作台、导航、公告
│   ├── interference/  # 干扰管理
│   ├── logs/          # 操作日志/审计日志
│   ├── radio_license/ # 无线电台执照、台站频率批复
│   ├── regulation/    # 规章管理
│   ├── reminder/      # 提醒事项
│   ├── runlog/        # 跨日事项跟踪
│   ├── setting/       # 系统设置
│   ├── signature/     # 账号签名
│   └── upgrade/       # 系统升级
├── libs/              # 公共基础设施
│   ├── middleware.py       # 认证 + 异常处理中间件
│   ├── tenant_base_model.py # 租户模型基类 + 逻辑删除 Manager
│   ├── tenant_utils.py     # 租户过滤工具
│   ├── pagination.py       # 分页工具
│   ├── decorators.py       # 权限装饰器
│   ├── idempotency.py      # 幂等检查
│   ├── utils.py            # json_response, get_request_real_ip 等
│   ├── alert.py            # 统一告警
│   └── ...
└── requirements.txt
```

### 职责边界

| 层 | 职责 | 禁止 |
|---|---|---|
| View | 参数校验、权限检查、调用 Service、组装响应 | 直接操作物理文件、跨租户查询 |
| Service | 业务逻辑、数据编排、事务管理 | 直接处理 HTTP 请求/响应 |
| Model | 数据定义、约束、简单查询 | 复杂业务逻辑 |
| Task | 异步执行、幂等重试 | 直接操作 HTTP 请求 |

---

## 二、认证与权限

### 认证

1. **Token 认证**：`AuthenticationMiddleware` 通过 `x-token`（header 或 GET 参数）认证用户。Token 长度必须 32 字符。
2. **preview_token 认证**：预览端点（document/evidence/signature）支持短时效 `preview_token`，优先于 x-token。
3. **预览端点安全限制**：GET 请求禁止 URL 中携带 `x-token`，仅允许 header 或 `preview_token`。
4. **IP 绑定校验**：`bind_ip` 开启时校验 `last_ip`，支持 `fnmatch` 模式排除。
5. **AUTHENTICATION_EXCLUDES**：`settings.py` 中定义免认证路径。

### 权限

1. **权限编码格式**：`<app>.<model>.<action>`（如 `document.document.view`、`radio_license.license.edit`）。
2. **权限检查**：`@decorators.has_perm('xxx.xxx.xxx')` 装饰器检查页面级权限。
3. **权限缓存**：`User.page_perms` -> Redis `perms_{user_id}` = `(version, perms_dict)`。修改角色权限后必须更新版本号使缓存失效。
4. **对象级权限**：`check_public_space_permission(user, space)` 校验公共空间操作权限。
5. **后端必须独立校验权限**，不能依赖前端隐藏按钮。

### 租户隔离

1. **TenantModelMixin**：所有业务模型继承此 Mixin，自动携带 `tenant_id` 字段。
2. **TenantModelManager**：默认 Manager 自动过滤当前用户租户，**逻辑删除记录自动排除**（`is_deleted=False`）。
3. **公共数据**：系统设置等使用 `GLOBAL` 租户类型，通过 `apply_tenant_filter(qs, user)` 统一处理。
4. **跨租户查询禁止**：除非明确需要（如超级管理员），所有查询必须经过租户过滤。
5. **Celery 任务**：异步任务必须重新校验用户和数据作用域，不信任调用方传入的参数。

```python
# 正确：使用 TenantModelManager 自动过滤
class MyModel(TenantModelMixin, models.Model):
    objects = TenantModelManager()  # 自动过滤 tenant_id + is_deleted

# 正确：手动过滤
qs = MyModel.objects.filter(tenant_id=user.tenant_id, is_deleted=False)
```

---

## 三、API 契约

### 响应格式

```python
# 成功
json_response({'key': 'value'})  # HTTP 200, {"data": {...}}

# 业务错误（HTTP 200！）
json_response(error='错误信息')   # HTTP 200, {"error": "错误信息"}
```

**关键约束**：
- HTTP 200 + `{"error": "..."}` 是项目既有的业务错误约定。前端 `libs/http.js` 拦截器会检查 `error` 字段。
- `update_by_dict` 工具函数会过滤 `None` 值，传入 `None` 不会更新对应字段。
- `json_response` 错误时 `data` 默认为空字符串 `''`，不是 `None`。

### 参数校验

1. 必填参数在 View 层校验，缺失时返回 `json_response(error='...')`。
2. 日期参数使用 `__gte`/`__lt` 范围查询，**禁止** `__date`/`__year`/`__month`/`__startswith`/`__icontains`。
3. 分页使用 `libs/pagination.py` 的 `paginate(request)` + `paginate_response(qs, page, page_size, serializer)`。

---

## 四、数据库事务与并发

### 事务规则

1. **ATOMIC_REQUESTS=True**：每个请求自动包裹在事务中。但多步写操作仍建议显式 `transaction.atomic()`。
2. **嵌套 atomic 仅创建 savepoint**，不会创建新事务。
3. **事务内禁止长阻塞外部调用**（HTTP 请求、长时间文件操作）。
4. **transaction.atomic 不能回滚物理文件或外部系统副作用**。文件操作必须在事务外做补偿。

### 并发写入

1. 排序交换（如 Navigation sort_id 交换）必须用 `transaction.atomic()` + `select_for_update()`。
2. 唯一约束冲突需在应用层处理（MariaDB 不支持部分唯一索引）。
3. 逻辑删除唯一约束冲突用 `__deleted_{id}` 后缀方案。

### 删除

1. 核心业务表使用逻辑删除（`is_deleted=True` + `deleted_at` + `deleted_by`）。
2. 删除操作必须 `transaction.atomic()` 包裹，审计日志写入与记录删除在同一事务内。
3. 批量删除需检查外键引用和附件关联。
4. `TenantModelManager.delete()` 默认执行逻辑删除。

### 迁移纪律

1. `makemigrations` **必须指定 app 名**。
2. 一功能一 migration。
3. `CharField`/`TextField` **禁止 `null=True`**。
4. 改字段类型前先洗数据（如 CharField -> DateField 先清空串）。
5. MariaDB alter 被外键引用主键列报错 1833 -> `SET FOREIGN_KEY_CHECKS=0`。
6. 迁移必须考虑历史数据兼容和回滚路径。

---

## 五、Celery 任务

### 任务规则

1. **必须保存并重新校验用户和数据作用域**：任务参数中传入 `user_id`，任务内重新查询用户和租户。
2. **幂等设计**：用 `get_or_create` 或唯一键防止重复执行。
3. **重试限制**：递归重试必须有深度/次数限制（如 `retryCount`/`retryDepth`）。
4. **失败清理**：任务失败时设置 `is_pending_clean` 标记，由清理任务异步重试。
5. **事务与任务**：`transaction.on_commit(lambda: task.delay(...))` 确保数据库提交后才触发任务。

### Beat Schedule

各模块独立定义 `celery_beat_schedule.py`，在 `settings.py` 中合并：

```python
# settings.py 中合并各模块的 beat schedule
from apps.document.celery_beat_schedule import DOCUMENT_BEAT_SCHEDULE
from apps.radio_license.celery_beat_schedule import RADIO_LICENSE_BEAT_SCHEDULE
# ... etc.
CELERY_BEAT_SCHEDULE = {**DOCUMENT_BEAT_SCHEDULE, **RADIO_LICENSE_BEAT_SCHEDULE, ...}
```

### 已知任务

| 任务 | 模块 | 用途 | 幂等机制 |
|---|---|---|---|
| `retry_clean_pending_files` | document | 清理待删除文件 | `is_pending_clean` 唯一消费者 |
| `merge_chunks` | document | 分片合并 | 状态机 + 文件记录验证 |
| `async_copy_files` | document | 异步复制文件 | transfer_id 去重 |
| `check_weekly_report_reminders` | reminder | 周报提醒 | get_or_create + 10 分钟时间窗 |
| `check_license_expiry` | radio_license | 执照过期检查 | - |
| 审计日志归档/清理/哈希链校验 | logs | 日志维护 | - |
| 磁盘/DB 监控 | alert | 系统告警 | - |

---

## 六、附件系统

### EvidenceAttachment 通用附件

1. 多模块共用 `apps/evidence/` 的 `EvidenceAttachment` 模型和 `AttachmentService`。
2. **使用附件的模块**：radio_license、contract_agreement、device、upgrade、fault、interference、department_duty_log。
3. **例外**：`regulation` 使用独立的 `storage.py`，不走 evidence 系统。
4. **新建阶段上传模式**：前端生成临时 UUID 作为 `object_id`，后端 `pk.isdigit()` 判断跳过记录存在性校验；保存记录时传 `attachment_temp_id`，后端 UPDATE `object_id` 关联。
5. **preview_token**：document/libs 和 evidence 各有独立实现，待收口。

### 文件操作安全

1. 文件写入顺序：先写物理文件 -> 成功后写数据库记录。
2. 文件删除顺序：先删物理文件 -> 成功后删数据库记录 -> 失败标记 `is_pending_clean`。
3. 路径拼接必须防止目录穿越（`..` 校验）。
4. 文件大小、类型需在 View 层校验。

---

## 七、审计日志

1. **record_audit_event**（`apps/logs/audit.py`）：所有核心写操作（创建/编辑/删除）必须调用。
2. 审计日志写入必须与业务操作在同一事务内。
3. 审计事件类型：`FILE_DELETE`、`FOLDER_DELETE`、`ROLE_CREATE` 等枚举。
4. 审计日志有哈希链（`AuditLogSequence`），不可随意删除或乱序写入。
5. 日志脱敏：`_SENSITIVE_KEYS` 自动过滤 password/token/secret/key/private/credential/captcha。

---

## 八、幂等性

1. **check_recent_duplicate**（`libs/idempotency.py`）：`check_recent_duplicate(model, filters, window_seconds=30)`，已含 `is_deleted=False` 过滤。
2. 已加 dedup 的模块：fault、interference、contract_agreement、department_duty_log、regulation、home/navigation、signature。
3. signature 使用 `request_id` 标杆实现幂等。
4. 新增 CRUD 模块应评估是否需要加 dedup。

---

## 九、各业务类型共同风险

### 普通 CRUD 模块

- 多步写操作必须 `transaction.atomic()`。
- 删除必须逻辑删除 + 审计日志。
- 列表查询必须过滤租户 + `is_deleted=False`。
- 排序交换必须 `select_for_update`。

### 审批或状态流转模块

- 状态转换必须遵循 `ALLOWED_STATUS_TRANSITIONS`。
- 状态变更必须 `update_fields` 限定，避免覆盖其他字段。
- 审计日志必须记录状态变更前后的值。

### 文件和附件模块

- 物理文件操作不在事务内。
- 删除失败标记 `is_pending_clean`。
- 文件路径防止目录穿越。
- 分片上传需检查 `operationVersion` 防止过期回调。

### 统计分析模块

- 纯只读聚合，无 model/migration。
- 跨 app 查询需注意性能。
- Redis 缓存 60s，key 需含租户隔离。

### Celery 异步模块

- 任务参数中传入 `user_id`，任务内重新查询。
- 递归重试需有深度限制。
- `transaction.on_commit` 触发任务。

### 跨租户或公共数据模块

- 公共数据用 `GLOBAL` 租户类型。
- `apply_tenant_filter` 统一处理。
- 党建隔离用 `system_scope_validators` fail-closed。

### 外部系统集成模块

- kkFileView：浏览器用 `KKFILEVIEW_API_URL`，回源用 `KKFILEVIEW_SERVER_URL`。
- 调用失败需有降级处理。
- 容器名须进 `ALLOWED_HOSTS`。

---

## 十、日志安全

1. **禁止日志输出**：access_token、password、secret、key、private、credential、captcha。
2. `_sanitize_request_body` 自动脱敏请求体。
3. 异常日志包含 `request_id` 用于链路追踪。
4. 生产环境异常信息返回 `"服务器内部错误，请联系管理员"`，不暴露堆栈。
