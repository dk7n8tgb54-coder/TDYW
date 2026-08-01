# Interference 模块 CRUD 可靠性审计报告

**审计日期**: 2026-08-01
**审计范围**: 事务边界、约束、安全（幂等性+索引已于 7/29 审查）
**审计依据**: `CRUD系统可靠性指南.md` + 前 10 模块实战审计经验
**验证方式**: 独立脚本 `run_interference_audit.py` 在 tdyw-test 容器内运行
**修复状态**: 11 项已修复（11 PASS / 0 FAIL / 2 SKIP / 1 ACCEPT）

---

## 审计结果总览

| 严重度 | 数量 | 说明 |
|--------|------|------|
| P1 (BUG) | 2 | 需立即修复 |
| P2 | 5 | 应尽快修复 |
| P3 | 5 | 可排期修复 |
| **合计** | **12** | **全部经测试验证为真** |

### 已审查通过项（前期已完成）

| 项 | 状态 | 完成日期 |
|----|------|----------|
| 幂等性 - `check_recent_duplicate` | ✅ 已完成 | 7/29 |
| 索引 - 2 个索引 + `__icontains` 评估 | ✅ 已完成 | 7/29 |
| 逻辑删除 - `is_deleted`/`deleted_at` 字段 | ✅ 已完成 | 7/30 |
| 删除审计 - `record_audit_event` | ✅ 已完成 | 7/30 |
| 导出审计 - `record_audit_event` | ✅ 已完成 | 7/30 |
| 列表/编辑/删除/证据包/统计 - `is_deleted=False` 过滤 | ✅ 已完成 | 7/30 |
| CHECK 约束 - 6 个状态/字段组合约束 | ✅ 已有 | - |
| 租户隔离 - `apply_tenant_filter` 全覆盖 | ✅ 已有 | - |
| 权限控制 - `@auth` 全覆盖 | ✅ 已有 | - |
| 导出限制 - `check_export_limit` | ✅ 已有 | - |

---

## 风险项明细

### R1 (P1 BUG) - Export 缺少 `is_deleted=False` 过滤

**位置**: `exporters.py:42`

**代码**:
```python
qs = apply_tenant_filter(Interference.objects.all(), request.user)
```

**问题**: `get_export_queryset` 使用 `Interference.objects.all()` 而非 `Interference.objects.filter(is_deleted=False)`，导致软删除记录出现在导出数据中。模块内其他所有视图（列表/编辑/删除/证据包/统计）均已过滤 `is_deleted=False`，唯独导出遗漏。

**验证结果**: ✅ 代码检查 FAIL（确认）。数据验证 SKIP（当前无软删除记录，但代码层面已确认）。

**修复方案**:
```python
qs = apply_tenant_filter(Interference.objects.filter(is_deleted=False), request.user)
```

**参考**: evidence 模块审计 R8 同类问题（`download_response` 未过滤 `is_deleted`），已于 7/31 修复。

---

### R2 (P1 BUG) - 证据包审计日志 fallback 泄露其他记录数据

**位置**: `views.py:292-295`

**代码**:
```python
if not audit_logs:
    audit_logs = list(AuditLog.objects.filter(
        tenant_id=tenant_id, target_type='interference',
    ).order_by('id'))
```

**问题**: 当目标记录无审计日志时，fallback 查询返回租户下**所有** interference 审计日志（无 `target_id` 过滤、无时间范围限制、无行数限制）。用户下载记录 A 的证据包，可能看到记录 B/C/D 的审计日志。

**验证结果**: ✅ 代码检查 FAIL（确认）。数据验证 SKIP（当前仅 1 条审计日志，但代码层面已确认）。

**修复方案**: 参考 runlog/device 模块（7/29 已修复同类问题），添加时间范围 + 行数限制：
```python
if not audit_logs:
    cutoff = timezone.now() - timedelta(days=90)
    audit_logs = list(AuditLog.objects.filter(
        tenant_id=tenant_id, target_type='interference',
        created_at__gte=cutoff,
    ).order_by('-id')[:1000])
```

---

### R3 (P2) - 删除操作未包裹在 `transaction.atomic()` 中

**位置**: `views.py:244-258`

**问题**: 删除流程包含三个写操作，但未包裹在事务中：
1. `_record_interference_evidence` (L244-247) - 证据事件（try/except 非阻塞）
2. `record_audit_event` (L249-254) - 审计日志
3. `record.save()` (L256-258) - 软删除

若步骤 3 失败（数据库连接断开等），步骤 2 已写入审计日志说"已删除"，但记录实际未删除，产生不一致。

**验证结果**: ✅ FAIL（确认）

**修复方案**:
```python
with transaction.atomic():
    record_audit_event(...)
    record.is_deleted = True
    record.deleted_at = timezone.now()
    record.save(update_fields=['is_deleted', 'deleted_at'])
```

---

### R4 (P2) - 删除 `save()` 未使用 `update_fields`

**位置**: `views.py:256-258`

**代码**:
```python
record.is_deleted = True
record.deleted_at = timezone.now()
record.save()
```

**问题**: `save()` 不带 `update_fields`，会写入所有字段。并发场景下，若另一请求在 `filter()` 和 `save()` 之间修改了记录的其他字段，本次 `save()` 会覆盖那次修改。

**验证结果**: ✅ FAIL（确认）

**修复方案**:
```python
record.save(update_fields=['is_deleted', 'deleted_at'])
```

---

### R5 (P2) - 统计视图使用 `Substr` 截取 DateTimeField

**位置**: `views.py:353`

**代码**:
```python
annotated = filtered_records.annotate(date=Substr('datetime', 1, 10))
```

**问题**: `Substr('datetime', 1, 10)` 对 DateTimeField 做字符串截取，依赖 MySQL datetime→string 转换，无法走索引。upgrade 模块已于 7/29 修复同类问题（改用 `TruncDate`）。

**验证结果**: ✅ FAIL（确认）

**修复方案**:
```python
from django.db.models.functions import TruncDate
annotated = filtered_records.annotate(date=TruncDate('datetime'))
```

---

### R6 (P2) - 创建操作 check + create TOCTOU 竞态

**位置**: `views.py:222-228`

**问题**: `check_recent_duplicate` 与 `Interference.objects.create` 之间无事务保护。两个并发请求可同时通过去重检查，各自创建记录，导致重复数据。

**验证结果**: ✅ FAIL（确认）

**修复方案**: 将 check + create 包裹在 `transaction.atomic()` 中。概率低但真实存在。

---

### R7 (P3) - 统计视图错误响应泄露内部异常信息

**位置**: `views.py:401`

**代码**:
```python
return json_response(error=str(e))
```

**问题**: 将原始异常信息返回给用户，可能泄露数据库表名、SQL 语句、文件路径等敏感信息。

**验证结果**: ✅ FAIL（确认）

**修复方案**:
```python
return json_response(error='获取统计数据失败，请稍后重试')
```

---

### R8 (P3) - 人员引用字段使用 IntegerField 而非 FK

**位置**: `models.py:44-70`

**问题**: `submitted_by_id`、`reviewed_by_id`、`reported_by_id`、`handled_by_id`、`closed_by_id`、`voided_by_id` 均为 `IntegerField`（6/6），无引用完整性约束。用户删除后引用变为悬空。

**验证结果**: ✅ FAIL（确认）

**评估**: 这是快照模式设计选择，与 `radio_license`/`device` 模块一致。保存人员姓名快照（`submitted_by_name` 等）可部分缓解。**接受现状，不修复**。

---

### R9 (P3) - `datetime` 模型允许 null 但视图要求必填

**位置**: `models.py:31` vs `views.py:210-211`

**问题**: `DateTimeField(null=True, blank=True)` 但视图校验必填（`'datetime': '日期时间'`）。模型层与业务层不一致，绕过视图直接操作数据库可写入 null。

**验证结果**: ✅ FAIL（确认）

**修复方案**: 设 `null=False`（需 migration）。低优先级。

---

### R10 (P3) - 重复导入 timezone（3 次）

**位置**: `views.py:5, 7, 255`

**问题**:
- L5: `from django.utils import timezone`
- L7: `from django.utils import timezone`（重复）
- L255: `from django.utils import timezone`（函数内重复导入）

**验证结果**: ✅ FAIL（确认，3 次）

**修复方案**: 删除 L7 和 L255 的重复导入。

---

### R12 (P2) - 删除操作未使用 `select_for_update`

**位置**: `views.py:239-258`

**问题**: 并发删除同一记录时，两个请求都能通过 `is_deleted=False` 过滤，第二个请求覆盖第一个的 `deleted_at`。配合 R3 的 `transaction.atomic()` 修复可一并解决。

**验证结果**: ✅ FAIL（确认）

**修复方案**: 在 `transaction.atomic()` 中使用 `select_for_update()`：
```python
with transaction.atomic():
    record = qs.select_for_update().filter(pk=form.id).first()
    ...
```

---

### R13 (P3) - 统计视图重复调用 `count()`（2 次）

**位置**: `views.py:346, 365`

**问题**: `filtered_records.count()` 被调用 2 次（L346 用于日志、L365 用于返回），执行 2 次 SQL COUNT 查询。

**验证结果**: ✅ FAIL（确认）

**修复方案**: 缓存为变量：
```python
total_count = filtered_records.count()
logger.info(f'... 记录数: {total_count}')
...
return json_response({'total_count': total_count, ...})
```

---

## 修复优先级与状态

| 优先级 | 项 | 修复复杂度 | 影响 |
|--------|-----|-----------|------|
| 立即 | R1 Export is_deleted 过滤 | 1 行 | 软删除记录泄露到导出 |
| 立即 | R2 证据包 fallback 限制 | 5 行 | 跨记录数据泄露 |
| 尽快 | R3+R4+R12 删除事务+update_fields+锁 | 10 行 | 数据一致性 |
| 尽快 | R5 Substr→TruncDate | 2 行 | 查询性能 |
| 尽快 | R6 创建事务 | 3 行 | 并发去重 |
| 排期 | R7 错误消息 | 1 行 | 信息泄露 |
| 排期 | R10 重复导入 | 2 行 | 代码质量 |
| 排期 | R13 count() 缓存 | 2 行 | 性能 |
| 排期 | R9 datetime null=False | migration | 约束 |
| 接受 | R8 IntegerField vs FK | - | 设计选择 |

---

## 测试验证

审计测试脚本 `run_interference_audit.py` 在 tdyw-test 容器内运行结果：

**修复前**: `总计: 14 项 | PASS: 0 | FAIL: 12 | SKIP: 2`（12 项风险全部确认）
**修复后**: `总计: 14 项 | PASS: 11 | FAIL: 0 | SKIP: 2 | ACCEPT: 1`（11 项修复全部验证通过）

修改文件: `views.py`(9项) / `exporters.py`(R1) / `models.py`(R9) / `migrations/0009`(R9)

脚本路径: `spug_api/run_interference_audit.py`
运行方式: `docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python run_interference_audit.py`
