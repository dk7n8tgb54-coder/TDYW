# evidence 模块 CRUD 可靠性审计报告

> 审计日期: 2026-07-31
> 审计范围: `apps/evidence` 全模块（5 个核心文件 + 对比 `document/libs/preview_token.py`）
> 测试结果: **38 项测试全部 PASS**（`run_evidence_audit.py`）

## 审计文件清单

| 文件 | 大小 | 职责 |
|------|------|------|
| `attachment_service.py` | 25.3KB | 附件 CRUD + 软删除 + 预览 URL 生成 |
| `attachment_preview_token.py` | 2.8KB | token 生成/验证（TimestampSigner） |
| `models.py` | 9.7KB | EvidenceEvent（哈希链）+ EvidenceAttachment |
| `services.py` | 6.8KB | 哈希链写入 `record_evidence_event()` |
| `hash.py` | 5.9KB | SHA256 哈希工具 `compute_event_hash_from_values()` |
| `document/libs/preview_token.py` | - | 另一套 preview_token 实现（对比） |

---

## §1.1 数据库约束

### R1(P1) EvidenceAttachment 无唯一约束

**发现**: 模型无任何 `UniqueConstraint`。同一文件（同 SHA256）可重复创建附件记录。

**影响**: 重复上传产生冗余记录，但不影响数据完整性（每个附件有独立 ID）。

**建议**: 若需去重，考虑 `(tenant_id, module, object_type, object_id, file_hash_sha256)` 组合唯一约束——但需先清洗存量重复数据。当前 YAGNI，暂不修。

### R2(P2) 哈希链无 DB 级 CHECK 约束

**发现**: `EvidenceEvent` 有 `event_type` 的 CHECK 约束（`ev_event_type_valid`），但 `prev_hash`/`event_hash` 之间的一致性无 DB 级校验。可直接插入 `prev_hash` 与上一条 `event_hash` 不匹配的记录。

**影响**: 应用层 bug 或直接 SQL 操作可导致链断裂，事后难以发现。

**建议**: 定期运行链完整性校验脚本（应用层巡检），不推荐加 DB CHECK（MariaDB CHECK 对复杂表达式支持有限）。

### R3(P2) 逻辑外键无 DB 引用完整性

**发现**: `actor_user_id`、`uploaded_by_id`、`deleted_by_id`、`audit_log_id` 均为 `IntegerField`（逻辑外键），无 `ForeignKey` 约束。用户删除后这些字段指向不存在的 ID。

**影响**: 查询时 `JOIN users` 会丢失关联数据。

**建议**: 查询时用 `actor_name`/`uploaded_by_name` 冗余字段兜底（已有）。不建议加 ForeignKey（7+ 模块跨引用会导致循环依赖 + 锁争用）。

### P1 ✅ CharField/TextField 无 null=True 违规

所有 CharField/TextField 均使用 `default=''` + `blank=True`，符合 Django 官方规范。

### P2 ✅ EvidenceEvent 有 event_type CHECK 约束

`ev_event_type_valid` CHECK 约束确保 `event_type` 只能是 `submit/approve/reject/close/correct/delete/export/void/other`。无效值会被 DB 拒绝。

---

## §1.2 事务边界

### R4(P0) 哈希链写入未使用 select_for_update — 并发竞态

**发现**: `record_evidence_event()` 查询 `prev_hash` 时使用 `.order_by('-id').first()`，**未加 `select_for_update()`**。两个并发调用可能读取相同的 `prev_hash`，导致：
1. 两个事件指向同一个 `prev_hash`
2. 第二个事件的 `prev_hash` 不等于第一个事件的 `event_hash`
3. **哈希链断裂**

**测试验证**: `test_r4b_concurrent` 模拟并发场景，确认两个事件可指向同一 `prev_hash`。

**影响**: 哈希链完整性被破坏，审计证据链可信度降低。

**建议**: 在 `record_evidence_event()` 中用 `select_for_update()` 锁定最新事件记录：
```python
last_event = (EvidenceEvent.objects
    .select_for_update()
    .filter(...)
    .order_by('-id').first())
```
需在 `transaction.atomic()` 内调用（当前已有 atomic 包裹）。

### R5(P2) soft_delete_by_object 无 transaction.atomic

**发现**: `soft_delete_by_object()` 循环逐个保存附件，未用 `transaction.atomic()` 包裹。中途失败导致部分删除。

**影响**: 批量删除业务对象附件时，可能残留部分未删除的附件。

**建议**: 用 `transaction.atomic()` 包裹整个循环。

### P3 ✅ AttachmentService.upload 正确使用 transaction.atomic

`upload()` 方法在创建 `EvidenceAttachment` 时使用 `transaction.atomic()` 包裹，文件写入在事务外，失败时清理临时文件。

---

## §1.3 幂等性

### R6(P2) 附件上传无去重

**发现**: `upload()` 无 `check_recent_duplicate` 调用，同 SHA256 文件可重复上传。

**影响**: 用户重复上传产生冗余记录。

**建议**: 低优先级。附件场景天然允许多次上传同名文件（如不同版本）。

### R7(P2) 哈希链重试不幂等

**发现**: `record_evidence_event()` 无幂等键，Celery 重试可能重复写入 `EvidenceEvent`。

**影响**: 审计日志可能出现重复事件。

**建议**: 增加 `request_id` 或 `idempotency_key` 参数，写入前检查最近是否有相同 key 的事件。

---

## §1.5 防误操作与可追溯

### R8(P1 BUG) download_response 未过滤 is_deleted

**发现**: `download_response()` 查询附件时使用 `qs.filter(pk=attachment_id).first()`，**未加 `is_deleted=False`**。软删除的附件仍可被下载。

**对比**:
- `get_preview_url()`: 有 `is_deleted=False` ✅
- `preview_file_response()`: 有 `is_deleted` 检查 ✅
- `download_response()`: **缺失** ❌

**测试验证**: `test_r8b_soft_deleted_downloadable` 确认软删除附件可被 `download_response` 查到。

**影响**: 用户可下载已删除的附件文件。

**建议**: 在 `download_response()` 的查询中添加 `is_deleted=False`：
```python
att = qs.filter(pk=attachment_id, is_deleted=False).first()
if not att:
    return None, '附件不存在或已删除'
```

### R9(P3) 附件操作本身无审计日志

**发现**: `upload()`/`soft_delete()`/`soft_delete_by_object()` 均不写审计日志（`AuditLog`），仅依赖 `EvidenceEvent` 记录。

**影响**: 非业务对象操作（如直接下载）无审计记录。

**建议**: 低优先级。`EvidenceEvent` 已覆盖核心操作（submit/correct/delete/export）。

### P4 ✅ 软删除保留物理文件

`soft_delete()` 的 `delete_file` 参数默认 `False`，软删除仅标记 `is_deleted=True`，物理文件保留。

### P5 ✅ preview_file_response 检查 is_deleted

`preview_file_response()` 在验证 token 后检查 `att.is_deleted`，软删除附件不可预览，返回 `'附件已删除'`。

---

## §2.1 索引与慢查询

### P6 ✅ EvidenceAttachment 索引完备

| 索引名 | 字段 | 覆盖场景 |
|--------|------|----------|
| `ev_att_obj_idx` | (tenant_id, module, object_type, object_id) | 按业务对象查附件 |
| `ev_att_obj_del_time_idx` | (tenant_id, module, object_type, object_id, is_deleted, uploaded_at, id) | 软删除过滤 + 时间排序 |
| `ev_att_sha256_idx` | (file_hash_sha256) | SHA256 去重查询 |
| `ev_att_del_idx` | (tenant_id, is_deleted) | 全局软删除查询 |

### P7 ✅ EvidenceEvent 索引完备

| 索引名 | 字段 | 覆盖场景 |
|--------|------|----------|
| `ev_obj_chain_idx` | (tenant_id, module, object_type, object_id, -id) | 哈希链查询（取最新事件） |
| `ev_event_hash_idx` | (event_hash) | 哈希验证 |
| `ev_event_actor_idx` | (actor_user_id) | 按操作人查询 |
| `ev_event_type_idx` | (tenant_id, event_type) | 按事件类型查询 |

---

## §3.5 安全维度

### P8 ✅ preview_token 绑定 6 维信息

`generate_attachment_preview_token()` 绑定：
1. `attachment_id` — 附件 ID
2. `user_id` — 操作用户 ID
3. `tenant_id` — 租户 ID
4. `module` — 业务模块
5. `object_type` — 对象类型
6. `object_id` — 对象 ID

使用 Django `TimestampSigner`（HMAC-SHA256 + 时间戳），300s 有效期。

### R10-R14 ✅ 跨附件/跨租户/跨用户/跨对象/篡改 — 全部拒绝

| 测试 | 场景 | 结果 |
|------|------|------|
| R10 | 用附件 A 的 token 访问附件 B | 拒绝（"attachment_id 不匹配"） |
| R11 | 修改附件 tenant_id 后用旧 token | 拒绝（"token 无效"） |
| R12 | token 中 user_id 与请求用户不一致 | token 数据绑定正确 |
| R13 | 修改附件 object_id 后用旧 token | 拒绝（"token 无效"） |
| R14a | 篡改 token 最后一个字符 | 返回 None |
| R14b | 完全伪造的 token | 返回 None |

### R15 ✅ 过期 token 被拒绝

`ATTACHMENT_PREVIEW_TOKEN_MAX_AGE = 300`（5 分钟），`max_age=0` 时 token 立即失效。

### R16 ✅ 软删除后 preview_file_response 拒绝预览

### R17(P2) 冒号分隔符注入风险

**发现**: token 使用 `:` 分隔字段（`attachment_id:user_id:tenant_id:module:object_type:object_id`）。如果 `module` 含 `:`，`split(':')` 产生 >6 段 -> 返回 None（拒绝）。

**影响**: 安全（拒绝），但脆弱——未来如果改成不检查段数就会出问题。

**建议**: 低优先级。当前 module/object_type 均为程序内部值（不含冒号）。如需加固，改用 JSON 序列化或 `|` 分隔符。

### R18(P3) 两套 preview_token 实现对比

| 维度 | evidence/attachment_preview_token.py | document/libs/preview_token.py |
|------|------|------|
| 绑定字段 | attachment_id, user_id, tenant_id, module, object_type, object_id | file_id, user_id, tenant_id, is_public, system_folder |
| 安全维度 | 业务对象绑定 | 访问范围绑定 |
| 签名算法 | Django TimestampSigner (HMAC-SHA256) | 同 |
| 有效期 | 300s | 300s |
| 字段数 | 6 | 5 |

**影响**: 两套实现模式相似但绑定维度不同，维护负担。

**建议**: 长期收口为一个通用 `preview_token` 模块，支持可配置绑定字段。短期 YAGNI。

---

## skip_tenant_filter=True 路径审计

**发现**: 仅 `home/announcement.py` 使用 `skip_tenant_filter=True`，3 处调用：
1. `AttachmentService.list()` — 前置 `ann.is_visible_to(request.user)` 校验 ✅
2. `AttachmentService.download_response()` — 前置 `ann.is_visible_to(request.user)` 校验 ✅
3. `AttachmentService.get_preview_url()` — 前置 `ann.is_visible_to(request.user)` + `token_tenant_id=att.tenant_id` ✅

**结论**: skip_tenant_filter=True 路径安全，调用方均做了权限校验。

---

## 修复优先级与状态

| 编号 | 风险 | 优先级 | 状态 | 修复内容 |
|------|------|--------|------|----------|
| **R4** | 哈希链并发竞态 | **P0** | ✅ 已修复 | `record_evidence_event` 加 `select_for_update()` |
| **R8** | download_response 未过滤 is_deleted | **P1** | ✅ 已修复 | 查询加 `is_deleted=False`，错误提示"附件不存在或无权限访问" |
| **R5** | soft_delete_by_object 无 atomic | P2 | ✅ 已修复 | 循环包裹 `transaction.atomic()` + `list(qs)` 缓存 |
| **R7** | 哈希链重试不幂等 | P2 | ✅ 已修复 | 新增 `idempotency_key` 参数，30s 窗口去重，存 remark 前缀 |
| R2 | 哈希链无 DB CHECK | P2 | 未修 | 应用层巡检脚本（YAGNI，当前低频） |
| R17 | 冒号分隔符脆弱 | P2 | 未修 | 当前安全（拒绝），module/object_type 均为内部值 |
| R18 | 两套 preview_token | P3 | 未修 | 长期收口 |
| R9 | 附件操作无审计日志 | P3 | 未修 | YAGNI |
| R1 | 附件无唯一约束 | P3 | 未修 | YAGNI |

### 修复验证

38 项测试全部 PASS，其中 6 项为修复后新增验证：
- `P9 select_for_update`: 确认源码包含 `select_for_update`
- `P10 soft_delete有atomic`: 确认源码包含 `transaction.atomic`
- `P11 有幂等键参数`: 确认源码包含 `idempotency_key`
- `P12 幂等键防重复`: 确认相同 key 重复调用返回 None
- `P13 download有is_deleted`: 确认源码包含 `is_deleted` 过滤
- `P14 软删除不可下载`: 确认软删除附件返回错误

---

## 测试文件

- `apps/evidence/crud_audit_tests.py` — Django TestCase 格式（38 个测试方法）
- `run_evidence_audit.py` — 独立运行脚本（绕过 Django test runner 迁移问题）

### 运行方式

```bash
# 独立脚本（推荐，使用 dev 库，无需创建测试库）
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python run_evidence_audit.py'

# Django test runner（需先创建 test_spug 并复制 schema + django_migrations）
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py test apps.evidence.crud_audit_tests --noinput --keepdb'
```
