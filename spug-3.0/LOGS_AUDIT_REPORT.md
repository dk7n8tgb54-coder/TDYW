# logs 模块 CRUD 可靠性审计报告

> 审计日期: 2026-08-01
> 审计依据: CRUD系统可靠性指南.md + 前 10 模块实战审计经验
> 测试脚本: `spug_api/apps/logs_audit_tests.py`
> 修复验证: `spug_api/apps/logs_fix_verify.py`
> 执行环境: tdyw-test 容器 (Django 4.2, MariaDB 10.8, dev 库)
> 修复状态: **7/7 项已修复，9/9 项验证通过**

## 审计范围

| 文件 | 说明 |
|------|------|
| `apps/logs/models.py` | AuditLog 模型定义（哈希链字段、索引） |
| `apps/logs/views.py` | 审计日志查询/导出 API |
| `apps/logs/audit.py` | `save_audit_log`、`log_celery_audit`、脱敏、TARGET_TABLE_MAP |
| `apps/logs/middleware.py` | `AuditLogMiddleware`、`_capture_before_values` |
| `apps/logs/hash_chain.py` | `verify_hash_chain`、`verify_log_hash`、`repair_hash_chain` |
| `apps/logs/tasks.py` | `cleanup_old_audit_logs`（90 天定期清理） |
| `apps/logs/urls.py` | URL 路由（4 个端点） |
| `apps/logs/celery_beat_schedule.py` | Celery Beat 配置 |

## 测试结果汇总

| 状态 | 数量 | 风险 ID |
|------|------|---------|
| CONFIRMED | 7 | R1, R2, R3, R4, R6, R7, R11 |
| FALSE_POSITIVE | 2 | R5, R8 |
| MITIGATED | 2 | R9, R10 |

---

## 确认的风险点

### R1 (P2): CharField null=True 违规

**位置**: `models.py` - `tenant_id`, `request_id`, `user_agent`

**现状**: Migration 0008 已修复 `detail`/`target_id`/`target_name`，但遗漏了三个字段：
- `tenant_id = CharField(max_length=50, null=True, default='default')`
- `request_id = CharField(max_length=64, null=True, blank=True, db_index=True)`
- `user_agent = CharField(max_length=500, null=True, blank=True)`

**风险**: NULL 值导致 ORM 查询不一致——`filter(tenant_id='default')` 不匹配 `tenant_id IS NULL` 的行。

**建议**: 改为 `default=''` + `blank=True`，生成 migration 去除 `null=True`。

---

### R2 (P2): detail__icontains 在 TextField 上全表扫描

**位置**: `views.py` - `AuditLogView.get()` 和 `AuditLogExportView.get()`

**现状**: 关键词搜索使用 `Q(detail__icontains=keyword)`，`detail` 是 TextField 无全文索引。`icontains` 生成 `LIKE '%keyword%'`，前缀通配符无法走 B-Tree 索引。

**缓解**: 有关键词时默认限制 90 天，但大表（>10 万行/90 天）仍可能慢查询。

**建议**: 改用 MariaDB FULLTEXT 索引，或将关键字单独提取到索引列。

---

### R3 (P2): username__icontains 绕过索引

**位置**: `views.py` - `username__icontains`（独立过滤 + 关键词搜索）

**现状**: `username` 有 Meta.indexes 索引，但 `icontains` 生成 `LIKE '%xxx%'` 无法利用 B-Tree 索引。`target_name` 同理。

**建议**: 精确匹配用 `__exact`，前缀匹配用 `__startswith`（CRUD 指南 §2.1）。

---

### R4 (P2): 无关键词无时间范围时缺少默认限制

**位置**: `views.py` - `AuditLogView.get()` 第 67-70 行

**现状**: 90 天默认限制在 `if form.keyword:` 条件块内。超管不传 keyword、不传时间范围时，`count()` 全表扫描。

**缓解**: AuditLogView 有分页（page_size<=100），AuditLogExportView 有 `check_export_limit(10000)`。

**建议**: 将默认 90 天限制提到 keyword 条件外，对所有查询生效。

---

### R6 (P2): _capture_before_values 使用 SELECT *

**位置**: `middleware.py` - `AuditLogMiddleware._capture_before_values()`

**现状**: `cursor.execute(f"SELECT * FROM {table_name} WHERE id = %s", [record_id])` 查询全列，包括可能的大文本字段。

**建议**: 使用列白名单或 Django ORM `.only('name', 'status', ...)` 减少网络传输。

---

### R7 (P2): verify_hash_chain 无调用入口

**位置**: `hash_chain.py` - `verify_hash_chain()` 函数

**现状**: 函数已实现且测试验证有效（能检测中间删除篡改），但无 URL、无视图、无 Celery Beat、无 Celery Task 调用。哈希链验证能力完全闲置。

**风险**: 无法发现审计日志被篡改。

**建议**: ① 新增 Celery Beat 定时任务（每日验证）② 或新增管理 API 供管理员手动触发。

---

### R11 (P2): cleanup 删除操作本身无审计

**位置**: `tasks.py` - `cleanup_old_audit_logs()`

**现状**: 物理删除旧审计日志时，删除操作本身未记录审计日志（未调用 `log_celery_audit`）。返回值包含 `deleted_count` 和 `cutoff_date`，但未落库审计。

**风险**: 违反 CRUD 指南 §1.5 "删除操作应有审计记录"。数据消失无法追溯原因。

**建议**: 在 cleanup 完成后调用 `log_celery_audit` 记录清理动作。

---

## 误报分析

### R5 (P1 → FALSE_POSITIVE): cleanup_old_audit_logs 对哈希链的影响

**测试结论**: `verify_hash_chain` 使用 `has_prev` 标志跳过首条记录的 `prev_hash` 检查，能优雅处理 cleanup 删除链首记录的场景。中间删除（篡改）能被正确检测。

**验证数据**:
- 场景 A（头部删除，模拟 cleanup）: `valid=True` — 链路仍完整
- 场景 B（中间删除，模拟篡改）: `valid=False` — 链路断裂，正确报错

**结论**: 设计正确，cleanup 不会导致误报。

---

### R8 (P2 → FALSE_POSITIVE): 敏感字段脱敏覆盖度

**测试结论**: `SENSITIVE_KEYWORDS=('password', 'token', 'secret', 'key', 'private', 'credential', 'captcha', 'cookie', 'session')` 覆盖了所有测试用例（password/api_key/access_token/private_key/secret/credential/wx_token/spug_push_key）。

---

## 已缓解项

### R9 (INFO): 90 天默认限制仅有关键词时生效

与 R4 关联。AuditLogView 的 90 天默认限制在 `if form.keyword` 条件块内，无关键词时不限制（依赖分页保护）。

### R10 (INFO): cleanup_old_audit_logs 批量删除安全

- `DELETE_BATCH_SIZE=5000`（批量大小限制）
- `MIN_RETENTION_DAYS=90`（保留期下限）
- `soft_time_limit=1800s`（Celery 软超时）
- `dry_run` 预演模式

设计合理，符合 CRUD 指南 §2.2 资源兜底要求。

---

## 修复优先级

| 优先级 | 风险 ID | 建议 |
|--------|---------|------|
| P2 | R7 | verify_hash_chain 无调用入口 → 新增 Celery Beat 定时验证 |
| P2 | R4 | 无默认时间范围 → 将 90 天限制提到 keyword 条件外 |
| P2 | R1 | CharField null=True → 改 default='' + migration |
| P2 | R2 | detail__icontains → FULLTEXT 或独立关键字列 |
| P2 | R3 | username__icontains → 改 __startswith |
| P2 | R6 | SELECT * → 列白名单或 ORM .only() |
| P2 | R11 | cleanup 无审计 → 补 log_celery_audit |
