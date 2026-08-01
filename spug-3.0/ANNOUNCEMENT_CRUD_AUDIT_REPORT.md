# 公告模块 CRUD 可靠性审计报告

> 审计日期：2026-07-31
> 审计范围：`apps/home/notice.py` + `apps/home/announcement.py`
> 测试脚本：`spug_api/run_announcement_audit.py`
> 执行环境：tdyw-test 容器（Django 4.2, MariaDB 10.8.2）

## 审计结果总览

| ID | 等级 | 状态 | 标题 |
|----|------|------|------|
| R1 | P0 | **RISK** | Notice sort swap 非事务致 sort_id 重复 |
| R2 | P1 | **RISK** | Notice edit 不过滤 is_deleted |
| R3 | P1 | **RISK** | Notice is_stress 批量清除无事务 |
| R4 | P2 | **RISK** | Notice read_ids read-modify-write 竞态 |
| R5 | P0 | **RISK** | Announcement _sync_scopes delete+recreate 非事务 |
| R6 | P0 | **RISK** | Announcement delete 非事务（撤回+软删除分离） |
| R7 | P1 | **RISK** | Announcement create/update save+sync_scopes 非事务 |
| R8 | P1 | **RISK** | Announcement publish 设 withdrawn_at='' 赋值给 DateTimeField |
| R9 | P2 | **RISK** | Announcement publish 允许重复发布 |
| R10 | P1 | **RISK** | Announcement delete 无 select_for_update + 无事务 |
| R11 | P2 | **RISK** | Announcement RemindersView N+1 查询 |
| R12 | P2 | OK | Notice create(**form) mass assignment（JsonParser 已过滤） |

**总计：12 项 | 风险确认：11 | 风险不成立：1 | 测试异常：0**

---

## P0 严重风险（3 项）

### R1: Notice sort swap 非事务致 sort_id 重复

**代码位置**：`notice.py:62-73`

```python
# PATCH sort swap 逻辑
tmp.sort_id, notice.sort_id = notice.sort_id, tmp.sort_id
tmp.save()     # 第一次 save — 成功
# ... read_ids 逻辑 ...
notice.save()  # 第二次 save — 如果失败，sort_id 已损坏
```

**测试验证**：
```
n1.sort_id=20, n2.sort_id=20
重复=True
```
n1.save() 成功后 sort_id=20 写入 DB，n2.save() 失败后 DB 中 n2.sort_id 仍为 20 → **两条记录 sort_id 相同**。

**影响**：排序混乱，前端展示顺序不可预测。

**修复建议**：用 `transaction.atomic()` 包裹 swap 逻辑，或用单条 `UPDATE ... SET sort_id = CASE WHEN ...` 原子操作。

---

### R5: Announcement _sync_scopes delete+recreate 非事务

**代码位置**：`announcement.py:99-108`

```python
def _sync_scopes(ann, scope_type, tids, tenants):
    ann.scopes.all().delete()          # 先删除所有旧 scope
    if scope_type == SCOPE_TENANT and tids:
        for tid in tids:
            AnnouncementScope.objects.create(...)  # 逐个重建
```

**测试验证**：
```
旧scope已删, 新scope第2个create失败
剩余scope=['t3']
范围丢失=True
```
旧 scope 全部删除，新 scope 只成功创建 1/3 → **公告可见范围损坏**。

**影响**：公告被发送到错误的租户范围，或完全不可见。

**修复建议**：用 `transaction.atomic()` 包裹 delete+create 全过程。

---

### R6: Announcement delete 非事务

**代码位置**：`announcement.py:308-330`

```python
# Phase 1: 撤回
if ann.status == STATUS_PUBLISHED:
    ann.status = STATUS_UNPUBLISHED
    ann.save()  # 第一次 save — 成功

# Phase 2: 软删除
ann.is_deleted = True
ann.save()  # 第二次 save — 如果失败...

# Phase 3: 附件软删除
AttachmentService.soft_delete_by_object(...)

# Phase 4: 审计
record_audit_event(...)
```

**测试验证**：
```
第1次save(撤回)成功, 第2次save(软删除)失败
status=unpublished, is_deleted=False
状态不一致=True
```
公告已从"已发布"变为"未发布"，但 `is_deleted=False` → **已撤回但未删除，用户看不到但数据残留**。

**影响**：公告状态不一致，撤回后无法再次发布（因为 status 不对了），且管理员可能以为已删除。

**修复建议**：整个 delete 流程用 `transaction.atomic()` 包裹。

---

## P1 高风险（5 项）

### R2: Notice edit 不过滤 is_deleted

**代码位置**：`notice.py:33`

```python
record_id = form.pop('id')
Notice.objects.filter(pk=record_id).update(**update_data)
# ↑ filter 只有 pk=record_id，没有 is_deleted=False
```

**测试验证**：
```
已软删除 Notice(id=3) 被修改 title='[AUDIT] EDITED AFTER DELETE'
被篡改=True
```

**影响**：已删除的通告内容可被篡改。

**修复**：`filter(pk=record_id, is_deleted=False)`

---

### R3: Notice is_stress 批量清除无事务

**代码位置**：`notice.py:27-28`

```python
if form.is_stress:
    Notice.objects.filter(is_stress=True).update(is_stress=False)  # 清除所有
# 后续 create/update 可能失败 -> 已清除的 stress 不会恢复
```

**测试验证**：
```
原 is_stress=True, 清除后 create 失败
is_stress=False, stress丢失=True
```

**影响**：置顶通告被意外取消置顶，且无法恢复。

**修复**：整个 create/update 用 `transaction.atomic()` 包裹。

---

### R7: Announcement create/update save+sync_scopes 非事务

**代码位置**：`announcement.py:202-203, 224-225`

```python
def _create_announcement(...):
    ann.save()              # 公告保存成功
    _sync_scopes(ann, ...)  # scope 同步失败 -> 公告无范围

def _update_announcement(...):
    ann.save()              # 公告更新成功
    _sync_scopes(ann, ...)  # scope 同步失败 -> 旧 scope 已删，新 scope 未建
```

**测试验证**：
```
title已更新但scope为空
title='[AUDIT] updated', scope_count=0
不一致=True
```

**影响**：公告已创建/更新但无可见范围，或更新后丢失原范围。

**修复**：`ann.save()` + `_sync_scopes()` 用 `transaction.atomic()` 包裹。

---

### R8: Announcement publish 设 withdrawn_at='' 赋值给 DateTimeField

**代码位置**：`announcement.py:357`

```python
ann.withdrawn_at = ''  # DateTimeField，应设 None
```

**测试验证**：
```
save() 抛异常: ["" value has an invalid format. 
It must be in YYYY-MM-DD HH:MM[:ss[.uuuuuu]][TZ] format.]
```

**影响**：重新发布已撤回的公告时，`save()` 直接抛异常 → **发布操作失败**。

**修复**：`ann.withdrawn_at = None`

---

### R10: Announcement delete 缺少 select_for_update + transaction.atomic

**代码位置**：`announcement.py:308-330`

```python
ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
# ↑ 没有 select_for_update，两个管理员可同时读到 is_deleted=False
```

**测试验证（源码审查）**：
```
select_for_update=无, atomic=无
并发删除时两请求都能通过 is_deleted=False 检查
```

**影响**：并发删除时重复执行 withdraw/soft_delete/attachment_delete，可能产生不一致状态。

**修复**：`filter(pk=pk, is_deleted=False).select_for_update().first()` + `transaction.atomic()`

---

## P2 中风险（3 项）

### R4: Notice read_ids read-modify-write 竞态

**代码位置**：`notice.py:69-72`

```python
read_ids = json.loads(notice.read_ids)
read_ids.append(str(request.user.id))
notice.read_ids = json.dumps(read_ids)
notice.save()  # 无 select_for_update，后写覆盖先写
```

**测试验证**：
```
期望 ['userA','userB']
实际 ['userB']
数据丢失=True (userA 被覆盖)
```

**影响**：并发已读标记丢失（低概率，影响小）。

**修复**：用 `select_for_update` 或改为 `F()` 表达式 / 单独表。

---

### R9: Announcement publish 允许重复发布

**代码位置**：`announcement.py:346-363`

```python
ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
# 没有 status 检查
ann.status = STATUS_PUBLISHED
ann.published_at = now  # 覆盖原始发布时间
```

**测试验证**：
```
原 published_at=2026-07-31 22:31:36, by='Original'
现 published_at=2026-07-31 23:31:36, by='New'
被覆盖=True
```

**影响**：已发布公告可被重复发布，丢失原始发布时间和发布人。

**修复**：添加 `if ann.status != STATUS_UNPUBLISHED: return json_response(error='仅未发布公告可发布')`

---

### R11: Announcement RemindersView N+1 查询

**代码位置**：`announcement.py:534-540`

```python
for ann in qs:
    if not AnnouncementRead.objects.filter(...).exists():
        # 每个公告一条查询
```

**测试验证（源码审查）**：
```
循环内查询: loop=True, inner_query=True, exists=True, batch=False
N+1 模式=True
```

**影响**：公告数量多时查询性能差。

**修复**：批量查询已读记录 `AnnouncementRead.objects.filter(announcement_id__in=[...], user=...)`。

---

## 风险不成立（1 项）

### R12: Notice create(**form) mass assignment — OK

JsonParser 只解析已定义的 `Argument` 字段（id, title, content, is_stress），传入的 `is_deleted`/`tenant_id` 等未定义字段被自动丢弃，**不存在 mass assignment 风险**。

---

## 修复优先级建议

| 优先级 | 风险 ID | 修复内容 |
|--------|---------|----------|
| 立即修复 | R8 | `withdrawn_at = ''` → `None`（当前会导致发布失败） |
| 立即修复 | R5, R6 | `_sync_scopes` 和 `delete` 加 `transaction.atomic()` |
| 尽快修复 | R1, R7 | sort swap 和 create/update 加 `transaction.atomic()` |
| 尽快修复 | R2 | edit filter 加 `is_deleted=False` |
| 计划修复 | R10 | delete 加 `select_for_update` |
| 计划修复 | R3 | is_stress 清除纳入事务 |
| 优化 | R4, R9, R11 | 并发竞态、重复发布检查、N+1 优化 |
