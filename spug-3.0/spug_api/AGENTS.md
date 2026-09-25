# spug_api/AGENTS.md - 后端工程规则

> 本文件覆盖 `spug_api/` 下所有 Django 应用的共同规则。模块级特殊规则见各模块目录下的 `AGENTS.md`（目前仅 `apps/document/`）。

---

## 一、架构分层

后端目录分为 Django 配置（`spug/`）、业务应用（`apps/`）、公共基础设施（`libs/`）和依赖配置。业务应用按领域独立组织；共享租户、权限、分页、幂等、响应和告警能力只能通过 `libs/` 的公开接口使用。

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

1. 删除语义以模块产品决策为准：业务主表默认**物理删除 + 审计留痕**；确需逻辑删除的模块（如带 `is_deleted` 字段的 interference）必须显式设计并在测试中固化。
2. 附件删除统一走 `EvidenceAttachment` 软删除留痕，物理文件删除失败标记 `is_pending_clean` 由 Celery 重试。
3. 删除操作必须 `transaction.atomic()` 包裹，审计日志写入与记录删除在同一事务内。
4. 批量删除需检查外键引用和附件关联。
5. `TenantModelManager` 在模型含 `is_deleted` 字段时默认查询自动过滤已删除记录（`all_with_deleted()` 可查全量）。

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

### 附件接口归属校验（防跨模块越权，必做）

业务模块的附件下载、删除、预览地址（preview-url）端点，调用 `AttachmentService` 前**必须**先做归属校验：

1. 附件存在且未软删除（`is_deleted=False`）；
2. `module` 与 `object_type` 等于本模块常量；
3. 附件属于当前用户可访问的租户范围（`apply_tenant_filter`，超管放行）。

校验不通过统一返回业务错误（如「附件不存在或无权限访问」），不泄露目标模块或路径信息。`preview-file`（kkFileView 回调）已有 preview_token 绑定校验，无需额外处理。

建议通过模块私有的 `_get_xxx_attachment_for_user` 辅助函数集中校验：

```python
def _get_xxx_attachment_for_user(user, attachment_id):
    att = apply_tenant_filter(
        EvidenceAttachment.objects.filter(is_deleted=False), user
    ).filter(pk=attachment_id).first()
    if not att:
        return None, '附件不存在或无权限访问'
    if att.module != ATTACHMENT_MODULE or att.object_type != ATTACHMENT_OBJECT_TYPE:
        return None, '附件不存在或无权限访问'
    return att, None
```

补充约束：

1. 父业务记录存在性校验按模块需要叠加（radio_license 校验父执照租户可见性；interference 因临时 UUID 上传模式不强制父记录存在）。
2. 新增使用附件的模块必须照此实现，并配套「跨模块附件访问/删除被拒绝」的稳定契约测试。
3. 软删除后默认 Manager 过滤 `is_deleted=True`，需要附件快照写证据事件/审计的必须在删除**前**取附件对象（删除后查询必为 None，属死代码）。
4. 后续可给 `AttachmentService` 增加必填 `module`/`object_type` 参数，把校验下沉到公共层；迁移完成前继续在视图层校验。

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

## 九、模块变更检查清单

按模块类型补充检查：

- 状态流转：使用 `ALLOWED_STATUS_TRANSITIONS`，用 `update_fields` 限定写入，并审计前后值。
- 统计分析：保持只读，跨 app 查询评估性能，缓存 key 必须含租户范围。
- 跨租户或党建数据：使用 `GLOBAL`、`apply_tenant_filter` 和 fail-closed 的 `system_scope_validators`。
- 外部集成：kkFileView 区分浏览器回源地址，调用失败有降级，容器名加入 `ALLOWED_HOSTS`。
- 文件、事务、Celery、幂等和删除规则分别遵守前述章节，不在此重复。

---

## 十、日志安全

1. **禁止日志输出**：access_token、password、secret、key、private、credential、captcha。
2. `_sanitize_request_body` 自动脱敏请求体。
3. 异常日志包含 `request_id` 用于链路追踪。
4. 生产环境异常信息返回 `"服务器内部错误，请联系管理员"`，不暴露堆栈。
