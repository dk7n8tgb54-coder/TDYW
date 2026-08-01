# Account 模块 CRUD 可靠性审计报告

> 审计日期：2026-08-01
> 审计依据：`CRUD系统可靠性指南.md` §1.1-§3.5 + 前 10 模块实战审计经验
> 测试文件：`apps/account/crud_audit_tests.py`（49 个测试，全部 PASS）

---

## 审计范围

| 文件 | 说明 |
|------|------|
| `apps/account/models.py` | User / Role / History / Tenant 模型 |
| `apps/account/views.py` | UserView / RoleView / TenantView / SelfView / login / logout |
| `apps/account/history.py` | HistoryView（登录历史查询） |
| `apps/account/utils.py` | validate_tenant_id / verify_password |
| `apps/account/urls.py` | URL 路由 |
| `apps/logs/middleware.py` | AuditLogMiddleware（自动审计） |
| `apps/account/migrations/0010_active_username_unique.py` | 部分唯一索引迁移 |

---

## 风险汇总

| # | 等级 | 风险 | 指南条款 | 状态 |
|---|------|------|----------|------|
| R1 | PASS | ~~User.username 无 DB 唯一约束~~ | §1.1 | **FALSE POSITIVE** - 有 uniq_users_active_username 部分唯一索引 |
| R2 | PASS | Role 有 unique_together DB 唯一约束 | §1.1 | **优秀实践** |
| R3 | P2 | Role 物理删除而非逻辑删除 | §1.1 | 确认存在，风险低（配置表+前置检查） |
| R4 | P2 | User 无 updated_at/updated_by 字段 | §1.5 | 确认存在 |
| R5 | P1 | UserView.delete 无显式 transaction.atomic() | §1.2 | 确认存在（ATOMIC_REQUESTS 兜底） |
| R6 | P1 | UserView.patch 无显式 transaction.atomic() | §1.2 | 确认存在（POST 路径有，PATCH 没有，不一致） |
| R7 | P1 | RoleView.post(edit) .update() 绕过 save() | §1.2 | 确认存在（当前不可利用，脆弱设计） |
| R8 | P1 | UserView.post 无 check_recent_duplicate | §1.3 | 确认存在（DB 唯一索引兜底） |
| R9 | P1 | RoleView.post 无幂等 + IntegrityError 未捕获 | §1.3 | 确认存在（重复名称返回 500） |
| R10 | P1 | TenantView.post 无幂等 + IntegrityError 未捕获 | §1.3 | 确认存在 |
| R11 | P1 | account CRUD 缺 record_audit_event | §1.5 | 确认存在（Middleware 兜底但 DELETE 无 target_name） |
| R12 | P2 | UserView.get_tenant_choices N+1 查询 | §2.1 | 确认存在（tenant 数量少，低风险） |
| R13 | P0 | HistoryView.get 无分页全表查询 | §2.2 | 确认存在（最高优先级） |
| R14 | P2 | TenantView.get 无分页 | §2.2 | 确认存在（tenant 数量少） |
| R15 | P2 | password_hash 使用 pbkdf2_sha256 | §3.5 | 确认存在 |
| R16 | INFO | HistoryView 无 PERM_MAP（仅超管可访问） | §3.5 | 安全设计，非风险 |
| R17 | P2 | History 模型无 tenant_id 字段 | §3.5 | 确认存在（仅超管可访问，风险有限） |
| R18 | P1 | Tenant 删除后 tenant_id 悬空引用 | §1.1 | 确认存在（CharField 非 FK） |
| R19 | P1 | RoleView.delete 检查 user_set 不过滤软删除用户 | §1.1 | 确认存在（保守设计，非 BUG） |
| R20 | P1 | token_expired=0 永不过期 + delete 不清空 | §3.5 | 确认存在 |
| R21 | P2 | History.created_at/username 无 db_index | §2.1 | 确认存在 |

**统计**：21 项排查，2 项优秀实践（FALSE POSITIVE/PASS），19 项确认风险（P0×1, P1×8, P2×8, INFO×1, 另 1 项保守设计）

---

## P0 风险详情

### R13: HistoryView.get 无分页全表查询

**位置**：`apps/account/history.py:11`

```python
class HistoryView(AdminView):
    def get(self, request):
        histories = History.objects.all()
        return json_response(histories)
```

**风险**：
- `History.objects.all()` 返回所有登录历史记录，无分页、无限制、无时间过滤
- 随着时间推移记录数无限增长（每次登录产生 1 条），可导致：
  - 内存溢出（单次查询加载全表到内存）
  - 响应超时（序列化大量 JSON 数据）
  - 数据库慢查询

**对比**：前序审计已修复 UserView.get 为 `[:500]`，但 HistoryView 遗漏。

**修复建议**：
```python
def get(self, request):
    histories = History.objects.all()[:500]
    return json_response(histories)
```

---

## P1 风险详情

### R5: UserView.delete 无显式 transaction.atomic()

**位置**：`apps/account/views.py:286-290`

```python
def delete(self, request, key):
    user = ...
    user.is_active = False
    user.deleted_at = timezone.now()
    user.deleted_by = request.user
    user.roles.clear()
    user.save()
```

**风险**：多步写操作（`roles.clear()` + `user.save()`）无显式事务包裹。虽有 `ATOMIC_REQUESTS=True` 兜底，但不符合编码规范。

**对比**：`_handle_user_edit` (POST 路径) 有显式 `transaction.atomic()`。

### R6: UserView.patch 无显式 transaction.atomic()

**位置**：`apps/account/views.py:251-264`

```python
def patch(self, request, key):
    ...
    self._migrate_user_tenant(user, form.tenant_id)
    user.tenant_id = form.tenant_id
    ...
    user.save()
```

**风险**：`_migrate_user_tenant` 执行跨表数据迁移 + `user.save()` 多步操作无显式事务。

**对比**：`_handle_user_edit` (POST 路径) 有 `with transaction.atomic():`，但 `patch` 方法没有，事务策略不一致。

### R7: RoleView.post(edit) .update() 绕过 save()

**位置**：`apps/account/views.py:400`

```python
Role.objects.filter(pk=role_id).update(**fields)
```

**风险**：`QuerySet.update()` 不触发 `Role.save()`，`perms_version` 自增逻辑被绕过。

**验证**：测试 R7b 确认 `.update()` 不递增 `perms_version`，R7c 确认 `save()` 路径会递增。

**当前安全性**：`fields` 不含 `page_perms`（仅通过 PATCH 修改），当前不可利用。但属于脆弱设计。

### R8/R9/R10: 幂等性缺失 + IntegrityError 未捕获

| 视图 | 幂等检查 | IntegrityError 捕获 | DB 唯一约束 | 影响 |
|------|---------|-------------------|------------|------|
| UserView.post | 无 | 有 | uniq_users_active_username | 竞态安全，返回友好提示 |
| RoleView.post | 无 | **无** | unique_together | 重复名称返回 500 |
| TenantView.post | 无 | **无** | PK (id) | 重复 ID 返回 500 |

**对比**：UserView 的 `_handle_user_create` 有 `try/except IntegrityError` 返回友好提示，但 RoleView 和 TenantView 没有，不一致。

### R11: account CRUD 缺 record_audit_event

**确认**：UserView/RoleView/TenantView 的 post/patch/delete 方法均不调用 `record_audit_event` 或 `save_audit_log`。

**对比**：`login` 委托 `handle_login_record` -> `save_audit_log` 记录审计日志，CRUD 操作没有。

**现状**：AuditLogMiddleware 自动记录 POST/PATCH/DELETE，但 DELETE 操作 `target_name=None`（中间件无法从 body 提取主体名），审计日志缺少被删除对象的名称。

### R18: Tenant 删除后 tenant_id 悬空引用

**确认**：`User.tenant_id` 和 `Role.tenant_id` 是 `CharField`（非 FK），`TenantView.delete` 物理删除 Tenant 记录后，关联用户/角色的 `tenant_id` 指向不存在的租户。

**风险**：删除租户后，该租户下的用户仍可登录（如果 `is_active=True`），但其 `tenant_id` 指向不存在的租户，可能导致数据查询异常。

### R19: RoleView.delete 检查 user_set 不过滤软删除用户

**确认**：`role.user_set.exists()` 包含软删除用户（`deleted_by_id` 非空），软删除用户仍占用角色关联，阻止角色删除。

**评估**：这是"宁可保守"的设计（防止误删有关联的角色），非 BUG，但可能造成运维困扰（无法删除被软删除用户关联的角色）。

### R20: token_expired=0 永不过期 + delete 不清空

**确认**：
- `token_expired` 字段允许 `null=True`，值为 0 时认证中间件不检查过期
- `UserView.delete` 设置 `is_active=False` 但不清空 `token_expired`
- 禁用用户后旧 token 理论上仍可使用（如果中间件不检查 `is_active`）

---

## 优秀实践（FALSE POSITIVE）

### R1: uniq_users_active_username 部分唯一索引

**发现**：migration 0010 创建了 `uniq_users_active_username` 部分唯一索引，使用 MariaDB 生成列实现：
- 活跃用户（`deleted_by_id IS NULL`）：`active_username = username`，唯一约束生效
- 软删除用户（`deleted_by_id IS NOT NULL`）：`active_username = NULL`，允许多个 NULL

**评价**：这是比简单 `unique=True` 更优秀的设计，完美解决了软删除 + 唯一约束的冲突。前序审计中 `is_deleted` + `__deleted_{id}` 后缀方案是另一种实现，但生成列方案更优雅。

### R2: Role unique_together

**确认**：`Role._meta.unique_together = (('tenant_id', 'name'),)` 在 DB 层强制租户内角色名唯一。

---

## 修复优先级建议

| 优先级 | 风险 | 修复方式 | 工作量 |
|--------|------|---------|--------|
| **P0** | R13 HistoryView 无分页 | 添加 `[:500]` 切片 | 1 行 |
| **P1** | R9 RoleView IntegrityError | 添加 try/except IntegrityError | 5 行 |
| **P1** | R10 TenantView IntegrityError | 同上 | 5 行 |
| **P1** | R5/R6 显式事务 | 添加 `with transaction.atomic():` | 4 行 |
| **P2** | R11 审计日志 | delete 时调用 `record_audit_event` | 10 行/视图 |
| **P2** | R3 Role 逻辑删除 | 添加 is_deleted 字段（需 migration） | 中等 |
| **P2** | R15 密码哈希 | 迁移到 bcrypt | 中等 |
| **P2** | R21 History 索引 | 添加 db_index=True（需 migration） | 小 |

---

## 测试执行

```
Ran 49 tests in 0.492s
OK
```

测试文件：`apps/account/crud_audit_tests.py`
运行方式：`docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py test apps.account.crud_audit_tests --keepdb --noinput -v2`
