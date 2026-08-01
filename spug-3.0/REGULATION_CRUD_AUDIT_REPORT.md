# 规章管理模块 CRUD 可靠性审计报告

> **审计日期**: 2026-07-31
> **修复日期**: 2026-08-01
> **审计范围**: `apps/regulation/` 全模块（models / views / storage / urls）
> **审计方法**: 代码审查 + 独立脚本测试（savepoint 回滚，不污染 dev 数据）
> **测试脚本**: `apps/regulation/run_crud_audit.py`
> **Django TestCase**: `apps/regulation/crud_audit_tests.py`
> **修复验证**: 15/15 PASS，0 CONFIRMED，0 FAIL

---

## 审计结果总览

| 级别 | 风险编号 | 描述 | 修复前 | 修复后 |
|------|----------|------|--------|--------|
| **P0 BUG** | R1 | `check_recent_duplicate(Regulation)` 抛 `FieldError` | ⚠ 确认 | ✓ 已修复 |
| **P1** | R2 | `RegulationDetailView.put` `save()` 无 `update_fields` | ⚠ 确认 | ✓ 已修复 |
| **P1** | R3 | `CategoryDetailView.put` `save()` 无 `update_fields` | ⚠ 确认 | ✓ 已修复 |
| **P1** | R4 | `RegulationRetireView.post` `save()` 无 `update_fields` | ⚠ 确认 | ✓ 已修复 |
| **P2** | R5 | 删除规章：软删除附件被 CASCADE 硬删除覆盖（冗余） | ⚠ 确认 | ✓ 已修复 |
| **P2** | R6 | `__icontains` 生成 `LIKE '%xxx%'` 绕过 B-Tree 索引（4 处） | ⚠ 确认 | ✓ 已修复 |
| **P2** | R7 | `page/page_size` 被 JsonParser + paginate() 重复解析（死代码） | ⚠ 确认 | ✓ 已修复 |
| **P2** | R8 | `ORDER BY -effective_date` NULL 排序行为 | ✓ 排除 | - |
| **P2** | R9 | 附件 `is_deleted` 检查模式不一致 | ⚠ 确认 | ✓ 已修复 |

**修复后**: 15/15 PASS，0 CONFIRMED，0 FAIL

---

## 风险详情

### R1 (P0 BUG): `check_recent_duplicate(Regulation)` 抛 `FieldError`

**根因**:
- `Regulation` 模型只有 `updated_at`，没有 `created_at` 字段
- `libs/idempotency.py:40` 中 `check_recent_duplicate` 硬编码 `created_at__gte=threshold`
- `RegulationCreateView.post`（views.py:435）调用 `check_recent_duplicate(Regulation, {...})`

**影响**:
- 创建规章时每次抛 `FieldError: Cannot resolve keyword 'created_at' into field`
- 用户无法通过 API 创建规章（500 错误）

**测试验证**:
```
⚠ [R1-1] Regulation 无 created_at 字段
    字段: ['attachments', 'biz_type', 'category', 'effective_date', 'id',
           'issuing_authority', 'publish_date', 'rule_no', 'status', 'title',
           'updated_at', 'updated_by']
⚠ [R1-2] check_recent_duplicate 抛 FieldError
    Cannot resolve keyword 'created_at' into field. Choices are: attachments,
    biz_type, category, ..., updated_at, updated_by, updated_by_id
✓ [R1-3] RegulationCategory 对比正常（有 created_at，不抛异常）
```

**修复方案**:
- 方案 A（推荐）: 给 `Regulation` 模型添加 `created_at = models.DateTimeField(auto_now_add=True)`
- 方案 B: 修改 `check_recent_duplicate` 支持 `timestamp_field` 参数，默认 `created_at`，对 `Regulation` 传 `updated_at`

---

### R2 (P1): `RegulationDetailView.put` `save()` 无 `update_fields`

**根因**:
- views.py `RegulationDetailView.put`: `regulation.save()` 保存全部列
- `changed` dict 记录了变更字段，但 `save()` 未使用 `update_fields` 参数

**影响**:
- 并发场景 last-write-wins：A 改 title、B 改 rule_no，B 的 save 覆盖 A 的 title
- `updated_by` 可能被覆盖（权限审计追溯断裂）

**测试验证**:
```
⚠ [R2-1] B 的 save 覆盖了 A 的 title
    title="R2原始"（被 B 覆盖回原始值）, rule_no="R2-002"
⚠ [R2-2] PUT save() 未传 update_fields
    代码确认：regulation.save() 保存全部列
```

**修复方案**:
```python
# 收集变更字段
changed = {}
if form.title and form.title != regulation.title:
    changed['title'] = form.title
    regulation.title = form.title
# ... 其他字段同理
if changed:
    regulation.updated_by = request.user
    regulation.updated_at = timezone.now()
    regulation.save(update_fields=list(changed.keys()) + ['updated_by', 'updated_at'])
```

---

### R3 (P1): `CategoryDetailView.put` `save()` 无 `update_fields`

**根因**: 同 R2，`cat.save()` 未传 `update_fields`

**测试验证**:
```
⚠ [R3-1] 分类 PUT save() 未传 update_fields
    代码确认：cat.save() 保存全部列
```

**修复方案**: 同 R2，使用 `cat.save(update_fields=[...])`

---

### R4 (P1): `RegulationRetireView.post` `save()` 无 `update_fields`

**根因**: 废止操作只改 `status`/`updated_by`/`updated_at`，但 `save()` 保存全部列

**测试验证**:
```
⚠ [R4-1] 废止 save() 未传 update_fields
    代码确认：regulation.save() 保存全部列（仅改 status）
```

**修复方案**: `regulation.save(update_fields=['status', 'updated_by', 'updated_at'])`

---

### R5 (P2): 删除规章时软删除附件被 CASCADE 硬删除覆盖

**根因**:
- views.py `RegulationDetailView.delete`:
  1. `regulation.attachments.update(is_deleted=True, deleted_by=..., deleted_at=...)` — 软删除
  2. `regulation.delete()` — 触发 `on_delete=CASCADE`，硬删除全部 `RegulationAttachment` 记录
- 步骤 1 的软删除被步骤 2 的 CASCADE 覆盖

**影响**:
- 软删除是冗余操作（白做功）
- `deleted_by`/`deleted_at` 审计信息随记录一起消失

**测试验证**:
```
⚠ [R5-1] 软删除后被 CASCADE 硬删除
    软删除是冗余操作
```

**修复方案**:
- 方案 A: 删除前记录审计信息到日志/审计表，再 CASCADE 删除（去掉冗余的 soft-delete update）
- 方案 B: 将 `RegulationAttachment.regulation` 改为 `on_delete=models.DO_NOTHING`，手动控制删除顺序（保持软删除记录）

---

### R6 (P2): `__icontains` 生成 `LIKE '%xxx%'` 绕过 B-Tree 索引

**根因**:
- views.py `RegulationListView.get` 使用 4 处 `__icontains`:
  - `title__icontains`（title 无索引）
  - `rule_no__icontains`（rule_no 有 `db_index=True`，但 `LIKE '%xxx%'` 无法使用）
  - `biz_type__icontains`（biz_type 有 `db_index=True`，同上）
  - `issuing_authority__icontains`（issuing_authority 有 `db_index=True`，同上）
- MariaDB 中 `LIKE '%xxx%'` 前缀通配符无法走 B-Tree 索引

**影响**:
- 全表扫描，数据量大时性能下降

**测试验证**:
```
⚠ [R6-1] title__icontains 生成 LIKE %xxx%
    icontains 在无索引/有索引 CharField 上均生成 LIKE，绕过 B-Tree
⚠ [R6-2] 共 4 处 __icontains（含 rule_no/biz_type/issuing_authority）
    LIKE %xxx% 绕过 db_index 索引
```

**修复方案**:
- 短期: 对 `rule_no`/`biz_type`/`issuing_authority` 改用 `__startswith`（`LIKE 'xxx%'` 可走索引）或精确匹配
- 长期: 引入全文索引（MariaDB FULLTEXT）或 Elasticsearch

---

### R7 (P2): `page/page_size` 被重复解析（死代码）

**根因**:
- views.py `RegulationListView.get`:
  ```python
  form = JsonParser(
      Argument('page', type=int, required=False, default=1),
      Argument('page_size', type=int, required=False, default=20),
  ).parse(request.GET)       # 第一次解析
  ...
  page, page_size = paginate(request, default_page_size=20, max_page_size=100)  # 第二次解析
  ```
- `paginate()` 直接从 `request.GET` 读取，`form.page`/`form.page_size` 从未被使用

**影响**: 死代码，无功能影响，增加维护成本

**测试验证**:
```
⚠ [R7-1] paginate() 独立从 request.GET 读取
    JsonParser 解析结果被忽略
✓ [R7-2] max_page_size=100 限制生效
```

**修复方案**: 删除 `JsonParser` 中的 `page`/`page_size` 参数

---

### R8 (已排除): `ORDER BY -effective_date` NULL 排序

**初始假设**: MariaDB `ORDER BY col DESC` 时 NULL 排在最前

**实际测试结果**:
```
✓ [R8-1] NULL 在 DESC 排序中排最后
    当前行为正确（R8 已排除）
```

**结论**: MariaDB 视 NULL 为最低值，DESC 降序时 NULL 排在最后。当前行为正确，无需修复。

---

### R9 (P2): 附件 `is_deleted` 检查模式不一致

**根因**:
- `RegulationAttachmentPreviewFileView`（views.py:894）: `regulation.attachments.get(pk=att_id)` — 不含 `is_deleted` 过滤
- 对比: `_get_attachment` 辅助方法先 `filter(is_deleted=False)`，返回 None 表示不存在
- 功能正确（get 后检查 `att.is_deleted`），但模式不一致

**影响**: 维护性问题，无安全风险

**测试验证**:
```
⚠ [R9-1] get(pk=) 可检索软删除附件
    PreviewFileView 用 get(pk=) 而非 filter(is_deleted=False)
✓ [R9-2] filter(is_deleted=False) 正确排除
```

**修复方案**: 统一使用 `_get_attachment` 辅助方法

---

## 修复优先级建议

| 优先级 | 风险 | 工作量 | 状态 | 说明 |
|--------|------|--------|------|------|
| **紧急** | R1 | 1h | ✓ 已修复 | 给 Regulation 加 `created_at` 字段 + migration |
| **高** | R2/R3/R4 | 2h | ✓ 已修复 | 3 处 `save()` 加 `update_fields` |
| **中** | R5 | 0.5h | ✓ 已修复 | 去掉冗余的 soft-delete update |
| **中** | R6 | 2h | ✓ 已修复 | `__icontains` -> `__startswith`（保留 title 模糊搜索） |
| **低** | R7 | 0.5h | ✓ 已修复 | 删除死代码 |
| **低** | R9 | 0.5h | ✓ 已修复 | 统一 `is_deleted` 检查模式 |

---

## 修复详情

### R1 修复：添加 `created_at` 字段

**文件**: `apps/regulation/models.py`
**Migration**: `apps/regulation/migrations/0009_regulation_created_at.py`

```python
# models.py - Regulation 模型
created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name='创建时间')
```

- `auto_now_add=True`: 新记录自动设置创建时间
- `null=True`: 允许已有记录的 created_at 为 NULL（避免 migration 报错）
- `check_recent_duplicate(Regulation, ...)` 不再抛 `FieldError`

### R2/R3/R4 修复：`save(update_fields=...)`

**文件**: `apps/regulation/views.py`

```python
# R2: RegulationDetailView.put
if changed:
    regulation.save(update_fields=list(changed.keys()) + ['updated_by', 'updated_at'])
else:
    regulation.save()

# R3: CategoryDetailView.put
if changed:
    cat.save(update_fields=list(changed.keys()))
else:
    cat.save()

# R4: RegulationRetireView.post
regulation.save(update_fields=['status', 'updated_by', 'updated_at'])
```

- 并发场景下各字段独立保存，不再 last-write-wins

### R5 修复：移除冗余 soft-delete

**文件**: `apps/regulation/views.py` - `RegulationDetailView.delete`

```python
# 修复前：先软删除 -> CASCADE 硬删除（软删除白做功）
regulation.attachments.update(is_deleted=True, ...)
regulation.delete()

# 修复后：直接 CASCADE 删除
attachments_to_clean = list(regulation.attachments.filter(is_deleted=False).values('id', 'file_path'))
regulation.delete()
```

### R6 修复：`__icontains` -> `__startswith`

**文件**: `apps/regulation/views.py` - `RegulationListView.get`

| 字段 | 修复前 | 修复后 | 索引可用 |
|------|--------|--------|----------|
| title (keyword) | `__icontains` | `__icontains`（保留模糊搜索） | 否（无索引） |
| rule_no (keyword) | `__icontains` | `__startswith` | ✓ `LIKE 'xxx%'` 走索引 |
| biz_type | `__icontains` | `__startswith` | ✓ 走索引 |
| issuing_authority | `__icontains` | `__startswith` | ✓ 走索引 |

`__icontains` 从 4 处减至 1 处（仅 title 保留模糊搜索）。

### R7 修复：删除 `page`/`page_size` 死代码

**文件**: `apps/regulation/views.py` - `RegulationListView.get`

```python
# 修复前
form = JsonParser(
    Argument('page', type=int, required=False, default=1),       # 死代码
    Argument('page_size', type=int, required=False, default=20),  # 死代码
    ...
).parse(request.GET)
page, page_size = paginate(request, ...)  # 实际从这里读取

# 修复后
form = JsonParser(
    ...  # page/page_size 已删除
).parse(request.GET)
page, page_size = paginate(request, ...)  # 唯一分页入口
```

### R9 修复：统一 `is_deleted` 检查模式

**文件**: `apps/regulation/views.py` - `RegulationAttachmentPreviewFileView.get`

```python
# 修复前
att = regulation.attachments.get(pk=att_id)  # 不过滤 is_deleted
if att.is_deleted:
    return json_response(error='附件已删除')

# 修复后
att = _get_attachment(regulation, att_id)  # 内部 filter(is_deleted=False)
if att is None:
    return json_response(error='附件不存在')
```

---

## 修复验证结果

```
✓ [R1-1] Regulation 有 created_at 字段
✓ [R1-2] check_recent_duplicate 正常
✓ [R1-3] RegulationCategory 对比正常
✓ [R1-4] API 创建规章返回 200
✓ [R2-1] 使用 update_fields 后并发不覆盖
✓ [R2-2] PUT 使用了 update_fields
✓ [R3-1] 分类 PUT 使用了 update_fields
✓ [R4-1] 废止使用 update_fields
✓ [R5-1] delete 方法已移除冗余 soft-delete
✓ [R6-1] keyword 搜索优化（title 用 icontains，rule_no 用 startswith）
✓ [R6-2] icontains=1, startswith=3
✓ [R7-1] JsonParser 已移除 page/page_size（死代码已清理）
✓ [R7-2] max_page_size=100 限制生效
✓ [R8-1] NULL 在 DESC 排序中排最后
✓ [R9-1] PreviewFileView 使用 _get_attachment（统一模式）

确认风险 (CONFIRMED): 0
通过 (PASS): 15
失败 (FAIL): 0
总计: 15
```

---

## 测试脚本

- **独立脚本**: `apps/regulation/run_crud_audit.py`（savepoint 回滚，不污染 dev 数据）
- **Django TestCase**: `apps/regulation/crud_audit_tests.py`（test DB 迁移问题待修复后可用）

运行方式:
```bash
wsl bash -c 'cat /mnt/e/TDYW/spug-3.0/spug_api/apps/regulation/run_crud_audit.py | \
  docker exec -i -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py shell 2>&1'
```
