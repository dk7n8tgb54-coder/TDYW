# Upgrade 模块 CRUD 审计报告

> 审计日期：2026-08-01
> 审计依据：CRUD系统可靠性指南.md + 前 10 模块审计经验
> 测试脚本：`apps/upgrade/audit_tests.py`（19 项风险点全部验证为真）

## 一、审计范围

| 层级 | 文件 | 说明 |
|---|---|---|
| Model | `models.py` | UpgradeRecord 主表 |
| Model | `models_checklist.py` | UpgradeRecordStep 步骤表 |
| Model | `models_status_log.py` | UpgradeStatusLog 状态日志表 |
| Model | `models_template.py` | UpgradeTemplate / UpgradePlanStep 方案模板 |
| Service | `services/record_service.py` | RecordService CRUD |
| Service | `services/step_service.py` | RecordStepService 步骤 CRUD |
| Service | `services/plan_service.py` | PlanService 方案 CRUD + apply_to_record |
| Service | `services/status_log_service.py` | StatusLogService 状态日志 |
| Service | `services/statistics_service.py` | StatisticsService 统计 |
| View | `views/record/` | create/update/delete/list/detail |
| View | `views/step.py` | 步骤 CRUD |
| View | `views/status_log.py` | 状态日志列表 |
| View | `views/systems.py` | 系统列表 |
| View | `views/plan.py` | 方案 CRUD |
| View | `views/upload.py` | 附件上传/下载/删除 |
| Export | `exporters.py` | 导出 Excel |

## 二、风险点汇总

| 编号 | 级别 | 类别 | 风险点 | 文件位置 | 验证结果 |
|---|---|---|---|---|---|
| R01 | **P0** | 软删除泄漏 | `upload.py:_get_record` 不过滤 `is_deleted=False` | `views/upload.py:41-45` | ✓ 确认 |
| R02 | **P0** | 软删除泄漏 | `exporters.py` 导出查询不过滤 `is_deleted=False` | `exporters.py:71` | ✓ 确认 |
| R03 | **P0** | 软删除泄漏 | `statistics_service.py` 统计查询不过滤 `is_deleted=False` | `services/statistics_service.py:34` | ✓ 确认 |
| R04 | **P0** | 软删除泄漏 | `status_log_service.add_log` 不过滤 `is_deleted=False` | `services/status_log_service.py:247-249` | ✓ 确认 |
| R05 | **P1** | 数据丢失 | `apply_to_record` replace 模式物理删除所有步骤（含已软删除的） | `services/plan_service.py:297-301` | ✓ 确认 |
| R06 | **P1** | 序号错误 | `apply_to_record` append 模式 `start_seq` 被软删除步骤夸大 | `services/plan_service.py:305-307` | ✓ 确认 |
| R07 | **P1** | 日期过滤 | `_apply_filters` 日期范围 `__lte` 边界遗漏（单日只匹配午夜） | `services/record_service.py:359-363` | ✓ 确认 |
| R08 | **P1** | 事务边界 | `batch_update_status` 状态日志写入在 `transaction.atomic()` 块外 | `services/step_service.py:235-241` | ✓ 确认 |
| R09 | **P2** | 软删除泄漏 | `batch_update_status` 步骤过滤不过滤 `is_deleted=False` | `services/step_service.py:219-221` | ✓ 确认 |
| R10a-d | **P1** | 并发安全 | 4 处 `save()` 无 `update_fields`（last-write-wins） | record_service / step_service / plan_service | ✓ 确认 |
| R11a-b | **P2** | 性能 | `_apply_filters` 使用 `icontains` 生成 `LIKE '%xxx%'` | `services/record_service.py:354,358` | ✓ 确认 |
| R12a-b | **P2** | 死代码 | `created_at=now_str` 传给 `auto_now_add=True` 字段 | `services/record_service.py:64` / `services/step_service.py:144` | ✓ 确认 |
| R13 | **P1** | 软删除泄漏 | `check_phase_completion` 查询步骤未过滤 `is_deleted=False` | `services/status_log_service.py:291-293` | ✓ 确认 |
| R14 | **P1** | 软删除泄漏 | `apply_to_record` 查询记录未过滤 `is_deleted=False` | `services/plan_service.py:269-271` | ✓ 确认 |

**总计：19 项风险点，全部验证为真（100% 确认率）**

## 三、风险点详述

### R01 (P0) - upload.py `_get_record` 不过滤 `is_deleted=False`

**位置**：`views/upload.py:41-45`

```python
def _get_record(record_id, user):
    """获取升级表单（带租户过滤），不存在返回 None"""
    return apply_tenant_filter(
        UpgradeRecord.objects.filter(pk=record_id), user
    ).first()
```

**问题**：缺少 `is_deleted=False` 过滤。软删除的记录仍可进行附件上传/下载/删除操作。

**影响**：
- 用户可以对已删除的升级记录上传附件
- 用户可以下载/删除已删除记录的附件
- 违反软删除语义，数据一致性风险

**对比**：`record_service.py` 中所有查询都正确过滤了 `is_deleted=False`

**验证**：
```
✓ R01_upload_no_is_deleted_filter: PASS
  _get_record 返回了软删除记录(id=23)
```

**修复建议**：
```python
return apply_tenant_filter(
    UpgradeRecord.objects.filter(is_deleted=False, pk=record_id), user
).first()
```

---

### R02 (P0) - exporters.py 不过滤 `is_deleted=False`

**位置**：`exporters.py:71`

```python
qs = apply_tenant_filter(UpgradeRecord.objects.all(), request.user)
```

**问题**：缺少 `is_deleted=False` 过滤。导出的 Excel 包含软删除记录。

**影响**：导出数据包含已删除记录，可能造成数据混淆。

**验证**：
```
✓ R02_export_no_is_deleted_filter: PASS
  导出包含软删除记录
```

**修复建议**：
```python
qs = apply_tenant_filter(
    UpgradeRecord.objects.filter(is_deleted=False), request.user
)
```

---

### R03 (P0) - statistics_service.py 不过滤 `is_deleted=False`

**位置**：`services/statistics_service.py:34`

**问题**：统计查询不过滤 `is_deleted=False`，统计数据包含已删除记录。

**影响**：统计数字偏高（如总数、按系统/状态/类型分布等），误导决策。

**验证**：
```
✓ R03_stats_no_is_deleted_filter: PASS
  total=3（期望2，包含软删除记录）
```

---

### R04 (P0) - status_log_service.add_log 不过滤 `is_deleted=False`

**位置**：`services/status_log_service.py:247-249`

```python
record = apply_tenant_filter(
    UpgradeRecord.objects.filter(pk=upgrade_id), user
).first()
```

**问题**：可以对软删除的记录添加状态日志。

**影响**：已删除记录的状态被修改，违反软删除语义；`_recompute_main_status` 也会被触发，可能修改已删除记录的 `status` 字段。

**验证**：
```
✓ R04_status_log_no_is_deleted_filter: PASS
  成功对软删除记录添加了状态日志(log_id=5)
```

---

### R05 (P1) - apply_to_record replace 模式物理删除

**位置**：`services/plan_service.py:297-301`

```python
if replace:
    existing = UpgradeRecordStep.objects.filter(upgrade_id=upgrade_id)
    deleted_count = existing.count()
    existing.delete()  # 物理删除！包含已软删除的步骤
```

**问题**：
1. `filter(upgrade_id=upgrade_id)` 不过滤 `is_deleted=False`
2. `existing.delete()` 是物理删除，不是软删除
3. `deleted_count` 包含已软删除的步骤，数值被夸大

**影响**：
- 已软删除的步骤被物理删除，审计追踪丢失
- 如果 apply 后续步骤创建失败，虽然 transaction.atomic 会回滚，但物理删除语义与软删除不一致

**验证**：
```
✓ R05_apply_replace_physical_delete: PASS
  旧步骤残留=0（物理删除了含已软删除的所有旧步骤）
```

**修复建议**：
```python
if replace:
    existing = UpgradeRecordStep.objects.filter(
        is_deleted=False, upgrade_id=upgrade_id
    )
    deleted_count = existing.count()
    # 软删除而非物理删除
    now = timezone.now()
    existing.update(is_deleted=True, deleted_at=now)
```

---

### R06 (P1) - apply_to_record append 模式 start_seq 夸大

**位置**：`services/plan_service.py:305-307`

```python
else:
    start_seq = UpgradeRecordStep.objects.filter(
        upgrade_id=upgrade_id
    ).count() + 1  # 不过滤 is_deleted=False
```

**问题**：`count()` 包含已软删除的步骤，`start_seq` 被夸大。

**影响**：新步骤的序号有跳跃（如活跃步骤 3 条 + 软删除 2 条 → start_seq=6，正确应为 4）。

**验证**：
```
✓ R06_apply_append_inflated_seq: PASS
  新步骤 seq=6（正确应为4，被夸大到6）
```

**修复建议**：
```python
start_seq = UpgradeRecordStep.objects.filter(
    is_deleted=False, upgrade_id=upgrade_id
).count() + 1
```

---

### R07 (P1) - 日期范围 `__lte` 边界问题

**位置**：`services/record_service.py:359-363`（exporters.py 中也有同样问题）

```python
if filters.get('start_date') and filters.get('end_date'):
    queryset = queryset.filter(
        upgrade_time__gte=filters['start_date'],
        upgrade_time__lte=filters['end_date'],  # 只匹配到 end_date 00:00:00
    )
```

**问题**：`upgrade_time` 是 DateTimeField，`__lte='2026-08-01'` 只匹配到 `2026-08-01 00:00:00`。当天 12:00 的记录不会被匹配。

**影响**：单日日期范围过滤返回不完整结果（遗漏当天大部分记录）。

**验证**：
```
✓ R07_date_range_boundary: PASS
  单日范围 count=0（期望1，__lte只匹配午夜）
```

**修复建议**：
```python
from datetime import datetime, timedelta
end_date = datetime.strptime(filters['end_date'], '%Y-%m-%d') + timedelta(days=1)
queryset = queryset.filter(
    upgrade_time__gte=filters['start_date'],
    upgrade_time__lt=end_date.strftime('%Y-%m-%d'),
)
```

---

### R08 (P1) - batch_update_status 事务边界

**位置**：`services/step_service.py:235-249`

```python
try:
    with transaction.atomic():
        # ... 步骤状态更新 ...
    # ↓↓↓ 以下在 atomic 块外 ↓↓↓
    for ph in reset_phases:
        StatusLogService.on_step_reset(upgrade_id, user, ph)
    for ph in done_phases:
        StatusLogService.check_phase_completion(upgrade_id, user, ph)
    return None
except Exception as e:
    ...
finally:
    # ↓↓↓ 也在 atomic 块外 ↓↓↓
    RecordStepService._check_and_update_record_status(upgrade_id, user)
```

**问题**：
1. 状态日志写入在 `transaction.atomic()` 块外 - 步骤已提交但日志可能写入失败
2. `finally` 块的 `_check_and_update_record_status` 在事务失败后仍会执行

**影响**：步骤状态已更新但状态日志缺失，数据不一致。

**验证**：
```
✓ R08_batch_update_txn_boundary: PASS
  发现1处在atomic块外的调用
```

---

### R09 (P2) - batch_update_status 步骤过滤不过滤 is_deleted

**位置**：`services/step_service.py:219-221`

```python
step = apply_tenant_filter(
    UpgradeRecordStep.objects.filter(
        pk=step_id, upgrade_id=upgrade_id  # 缺少 is_deleted=False
    ), user
).first()
```

**问题**：可以更新已软删除步骤的状态。

**影响**：软删除步骤被重新激活状态，可能影响 `check_phase_completion` 的判断。

**验证**：
```
✓ R09_batch_update_deleted_step: PASS
  软删除步骤 status 被更新为 completed
```

---

### R10a-d (P1) - save() 无 update_fields

| 位置 | 方法 | save() 调用数 |
|---|---|---|
| `record_service.py:117` | `update_record` | 1 处 |
| `record_service.py:183` | `delete_record` | 1 处 |
| `step_service.py:193` | `delete_step` | 1 处 |
| `plan_service.py:186` | `update_plan` | 1 处 |

**问题**：`save()` 不传 `update_fields`，Django 会生成全字段 UPDATE SQL。

**影响**：
- 性能：不必要的 SQL 字段更新
- 并发：last-write-wins，可能覆盖并发修改
- 安全：可能意外更新不应修改的字段

**验证**：
```
✓ R10a_update_record: PASS  1处save()无update_fields
✓ R10b_delete_record: PASS  1处save()无update_fields
✓ R10c_delete_step: PASS    1处save()无update_fields
✓ R10d_update_plan: PASS    1处save()无update_fields
```

---

### R11a-b (P2) - icontains 性能

**位置**：`services/record_service.py:354, 358`

```python
queryset = queryset.filter(system__icontains=filters['system'])
queryset = queryset.filter(owner__icontains=filters['owner'])
```

**问题**：`icontains` 生成 `LIKE '%xxx%'`，前缀通配符无法使用 B-Tree 索引。

**影响**：大数据量时全表扫描。

**说明**：`system` 在 UI 中是下拉选择，应使用精确匹配。`owner` 可以考虑 `startswith` 或增加索引。

---

### R12a-b (P2) - created_at 死代码

**位置**：`services/record_service.py:64` / `services/step_service.py:144`

```python
# record_service.py
created_at=now_str,  # now_str 是字符串，传给 auto_now_add=True 字段

# step_service.py
created_at=now_str,  # 同上
```

**问题**：`auto_now_add=True` 会在 `save()` 时自动设置为当前时间，覆盖传入值。`created_at=now_str` 是死代码。

**影响**：代码误导，可能让开发者误以为 `created_at` 被手动设置。

---

### R13 (P1) - check_phase_completion 不过滤步骤 is_deleted

**位置**：`services/status_log_service.py:291-293`

**问题**：查询步骤时不过滤 `is_deleted=False`，软删除的步骤也参与阶段完成判断。

**影响**：软删除步骤如果状态为 pending，可能导致阶段永远无法标记为完成。

---

### R14 (P1) - apply_to_record 不过滤记录 is_deleted

**位置**：`services/plan_service.py:269-271`

**问题**：查询记录时不过滤 `is_deleted=False`，可以对软删除记录应用方案。

**影响**：软删除记录被添加新步骤，违反软删除语义。

---

## 四、按风险等级分类

### P0 - 安全/数据一致性（4 项，必须立即修复）

| 编号 | 风险 | 影响 |
|---|---|---|
| R01 | upload.py 不过滤 is_deleted | 软删除记录可上传/下载/删除附件 |
| R02 | exporters.py 不过滤 is_deleted | 导出包含软删除记录 |
| R03 | statistics_service 不过滤 is_deleted | 统计数据包含软删除记录 |
| R04 | status_log_service.add_log 不过滤 is_deleted | 可对软删除记录添加状态日志 |

### P1 - 数据一致性/事务安全（8 项，应尽快修复）

| 编号 | 风险 | 影响 |
|---|---|---|
| R05 | apply_to_record replace 物理删除 | 旧步骤被物理删除，审计丢失 |
| R06 | apply_to_record append start_seq 夸大 | 新步骤序号跳跃 |
| R07 | 日期范围 __lte 边界 | 单日过滤遗漏当天记录 |
| R08 | batch_update 事务边界 | 步骤已提交但日志可能缺失 |
| R10a-d | 4 处 save() 无 update_fields | 并发覆盖风险 |
| R13 | check_phase_completion 不过滤 is_deleted | 软删除步骤影响阶段完成判断 |
| R14 | apply_to_record 不过滤记录 is_deleted | 可对软删除记录应用方案 |

### P2 - 性能/代码质量（7 项，择机修复）

| 编号 | 风险 | 影响 |
|---|---|---|
| R09 | batch_update 步骤过滤不过滤 is_deleted | 软删除步骤状态被更新 |
| R11a-b | icontains 生成 LIKE '%xxx%' | 全表扫描性能问题 |
| R12a-b | created_at=now_str 死代码 | 代码误导 |

## 五、与前 10 模块审计经验对比

| 风险模式 | 前模块发现次数 | upgrade 模块 | 说明 |
|---|---|---|---|
| 软删除泄漏（is_deleted 过滤缺失） | evidence R8、regulation R3 等 | **R01/R02/R03/R04/R05/R06/R09/R13/R14** | upgrade 模块是重灾区（9 处） |
| save() 无 update_fields | regulation R2/R3/R4 等 | **R10a-d** | 4 处 |
| 事务边界缺失 | evidence R4/R5/R7 等 | **R08** | 状态日志在事务外 |
| icontains 性能 | regulation R6、fault 等 | **R11a-b** | 2 处 |
| 日期过滤边界 | fault 导出等 | **R07** | 经典 off-by-one |
| 死代码 | 各模块零星 | **R12a-b** | 2 处 |

## 六、修复优先级建议

### 第一批（P0，立即修复）
1. `upload.py:_get_record` 加 `is_deleted=False`
2. `exporters.py` 加 `is_deleted=False`
3. `statistics_service.py` 加 `is_deleted=False`
4. `status_log_service.add_log` 加 `is_deleted=False`

### 第二批（P1，本周修复）
5. `plan_service.apply_to_record` replace 改软删除 + 过滤 `is_deleted=False`
6. `plan_service.apply_to_record` append 过滤 `is_deleted=False`
7. `record_service._apply_filters` 日期范围 `__lte` → `__lt` + end_date+1
8. `step_service.batch_update_status` 状态日志移入 `transaction.atomic()`
9. 4 处 `save()` 加 `update_fields`
10. `status_log_service.check_phase_completion` 加 `is_deleted=False`
11. `plan_service.apply_to_record` 查询记录加 `is_deleted=False`

### 第三批（P2，择机修复）
12. `step_service.batch_update_status` 步骤过滤加 `is_deleted=False`
13. `record_service._apply_filters` `system__icontains` → `system__iexact` 或 `=`
14. `record_service._apply_filters` `owner__icontains` → `owner__startswith` 或加索引
15. 删除 `created_at=now_str` 死代码
