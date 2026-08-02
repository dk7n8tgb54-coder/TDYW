# 执照管理 + 合同协议 CRUD 可靠性深度审计报告 v2

> 审计日期: 2026-08-01
> 审计范围: 无线电台执照（RadioLicense）、台站频率批复（StationFrequencyApproval）、合同协议（ContractAgreement）
> 审计重点: 影响运行稳定的大风险问题
> 验证方式: 28 个自动化测试用例（代码级 + 行为级），全部通过

## 一、风险清单总览

| 编号 | 模块 | 严重度 | 风险描述 | 验证结果 |
|------|------|--------|----------|----------|
| R-CA-1 | 合同协议 | **P0** | 编辑模式不验证 responsible_user_id，可设置不存在的责任人 | ✅ 已验证为真 |
| R-CA-2 | 合同协议 | **P0** | 编辑模式 responsible_user_name 信任客户端，可伪造责任人姓名 | ✅ 已验证为真 |
| R-CA-3 | 合同协议 | **P1** | agreement.save() 无 update_fields，全字段覆盖导致丢失更新 | ✅ 已验证为真（行为级） |
| R-CA-4 | 合同协议 | **P1** | ReminderAckView create+audit 无事务包裹 | ✅ 已验证为真 |
| R-AP-1 | 台站频率批复 | **P0** | create 的 scan+audit 在事务外 | ✅ 已验证为真 |
| R-AP-2 | 台站频率批复 | **P0** | edit 的 scan+audit 在事务外 | ✅ 已验证为真 |
| R-AP-3 | 台站频率批复 | **P1** | delete 的 audit 在事务外 | ✅ 已验证为真 |
| R-AP-4 | 台站频率批复 | **P1** | ack 的 audit 在事务外 | ✅ 已验证为真 |

对照基线（无线电台执照模块，事务边界正确）:

| 编号 | 模块 | 严重度 | 风险描述 | 验证结果 |
|------|------|--------|----------|----------|
| R-RL-1 | 无线电台执照 | PASS | create 的 scan+audit 在事务内 | ✅ 正确 |
| R-RL-2 | 无线电台执照 | PASS | edit 的 scan+audit 在事务内 | ✅ 正确 |
| R-RL-3 | 无线电台执照 | PASS | delete 的 audit 在事务内 | ✅ 正确 |

## 二、P0 风险详解

### R-CA-1: 合同编辑不验证责任人

**文件**: `apps/contract_agreement/views.py`

**问题**:
- `_post_edit` 方法不调用 `_validate_and_fill_responsible_user`
- `_validate_edit_form` 只校验日期、合同类型、费用，完全跳过 `responsible_user_id`
- 编辑时可将 `responsible_user_id` 设置为任意值（包括不存在的用户 ID）

**影响**:
- 提醒发送到不存在的用户，提醒系统静默失败
- 数据完整性被破坏：`responsible_user_id` 指向不存在或已禁用的用户

**代码对比**:
```python
# 新建模式（正确）：调用了验证
def _post_create(self, request, form):
    err = self._validate_form(form)  # 内部调用 _validate_and_fill_responsible_user
    ...

# 编辑模式（BUG）：未调用验证
def _post_edit(self, request, form):
    err = self._validate_edit_form(agreement, form)  # 不校验 responsible_user
    ...
```

**行为级测试验证**:
```
test_R_CA_1_edit_allows_nonexistent_responsible_user ... ok
# 设置 responsible_user_id=999999（不存在的用户），save() 成功，DB 不阻止
```

### R-CA-2: 合同编辑接受客户端伪造的责任人姓名

**文件**: `apps/contract_agreement/views.py`

**问题**:
- 新建模式调用 `_validate_and_fill_responsible_user` 时，会用服务端查到的真实姓名覆盖 `form.responsible_user_name`
- 编辑模式不做此操作，客户端传入的 `responsible_user_name` 原样写入数据库

**影响**:
- 可伪造责任人姓名，绕过服务端验证
- 审计/提醒显示的责任人姓名与实际用户不匹配

### R-AP-1/R-AP-2: 批复 create/edit 的 scan+audit 在事务外

**文件**: `apps/radio_license/approval_views.py`

**问题**:
```python
# _handle_create（事务只包裹了 create）
try:
    with transaction.atomic():
        approval = StationFrequencyApproval.objects.create(**create_data)
except IntegrityError:
    return '文件编号已存在，请更换'

# 以下在事务外！
scan_single_approval(approval)       # ← 事务外
_record_approval_audit(...)          # ← 事务外
```

**影响**:
1. 如果 `scan_single_approval` 失败（DB 异常），批复已落库但状态缓存为空，用户看到的 `status` 不正确
2. 如果 `_record_approval_audit` 失败，批复已落库但无审计记录，合规追溯断裂

**对照（执照模块正确做法）**:
```python
# _handle_create（事务包裹了 create + scan + audit）
with transaction.atomic():
    license_obj = RadioLicense.objects.create(**create_data)
    _create_frequencies(license_obj, frequencies, user)
    scan_single_license(license_obj)       # ← 事务内 ✓
    record_audit_event(...)                # ← 事务内 ✓
```

## 三、P1 风险详解

### R-CA-3: 合同编辑 save() 无 update_fields 导致丢失更新

**文件**: `apps/contract_agreement/views.py:262-275`

**问题**:
```python
agreement = qs.filter(pk=form.id).first()  # 加载全部字段
# ... 修改部分字段 ...
agreement.save()  # 不带 update_fields，保存全部字段！
```

**行为级测试验证**:
```
1. 创建合同（remark=''）
2. 模拟并发修改：update(remark='并发修改的备注')
3. 模拟编辑：agreement_a.contract_name = '新名称'; agreement_a.save()
4. 结果：remark 被覆盖回 ''（丢失更新！）
```

**对照测试**:
```
使用 agreement.save(update_fields=['contract_name', 'updated_at'])
→ remark 保留为 '并发修改的备注' ✓
```

**影响**:
- Celery 扫描任务更新 `status`/`last_remind_at` 可能被覆盖
- 两个用户并发编辑不同字段时，后保存者覆盖先保存者的全部修改

**对照（执照模块正确做法）**:
```python
# 使用 queryset.update() 只更新传入字段
qs.filter(pk=record_id).update(**update_data)  # 不覆盖其他字段
```

### R-CA-4: 合同 ReminderAckView 无事务

**文件**: `apps/contract_agreement/views.py`

**问题**:
```python
try:
    ContractAgreementReminderAck.objects.create(...)  # ← 无事务
    record_audit_event(...)                            # ← 无事务
except IntegrityError:
    ...
```

**影响**: 如果 create 成功但 audit 失败，数据不一致。

### R-AP-3/R-AP-4: 批复 delete/ack 的 audit 在事务外

**文件**: `apps/radio_license/approval_views.py`

**问题**:
```python
# delete（audit 在事务外）
with transaction.atomic():
    AttachmentService.soft_delete_by_object(...)
    approval.delete()
_record_approval_audit(...)  # ← 事务外！

# ack（audit 在事务外）
with transaction.atomic():
    ack, _ = get_or_create(...)
_record_approval_audit(...)  # ← 事务外！
```

**影响**: 操作成功但审计日志可能丢失，合规追溯断裂。

## 四、事务边界对比矩阵

| 操作 | 无线电台执照 | 台站频率批复 | 合同协议 |
|------|-------------|-------------|---------|
| create | scan+audit 在事务内 ✓ | scan+audit **在事务外** ✗ | scan+audit 在事务内 ✓ |
| edit | scan+audit 在事务内 ✓ | scan+audit **在事务外** ✗ | scan+audit 在事务内 ✓（但 save 无 update_fields ✗） |
| delete | audit 在事务内 ✓ | audit **在事务外** ✗ | audit 在事务内 ✓ |
| ack | N/A | audit **在事务外** ✗ | create+audit **无事务** ✗ |
| responsible_user 验证 | create+edit 都验证 ✓ | create+edit 都验证 ✓ | **仅 create 验证** ✗ |

## 五、修复建议

### P0 修复（立即）

1. **R-CA-1 + R-CA-2**: 在 `_post_edit` 中调用 `_validate_and_fill_responsible_user`
   ```python
   def _post_edit(self, request, form):
       # 在 _validate_edit_form 之前添加
       if hasattr(form, 'responsible_user_id') and form.responsible_user_id is not None:
           err = _validate_and_fill_responsible_user(form)
           if err:
               return json_response(error=err)
       ...
   ```

2. **R-AP-1 + R-AP-2**: 将 `scan_single_approval` 和 `_record_approval_audit` 移入 `transaction.atomic()` 块
   ```python
   try:
       with transaction.atomic():
           approval = StationFrequencyApproval.objects.create(**create_data)
           scan_single_approval(approval)        # ← 移入事务内
           _record_approval_audit(...)           # ← 移入事务内
   except IntegrityError:
       return '文件编号已存在，请更换'
   ```

### P1 修复（尽快）

3. **R-CA-3**: `_post_edit` 改用 `update_fields` 或 `qs.filter(pk=id).update()`
   ```python
   # 方案 A: 使用 update_fields
   agreement.save(update_fields=list(update_data.keys()) + ['updated_at', 'updated_by'])

   # 方案 B: 使用 queryset.update（与执照模块一致）
   qs.filter(pk=form.id).update(**update_data, updated_at=timezone.now(), updated_by=request.user)
   ```

4. **R-AP-3 + R-AP-4**: 将 `_record_approval_audit` 移入 `transaction.atomic()` 块

5. **R-CA-4**: 用 `transaction.atomic()` 包裹 `ReminderAckView.post` 的 create+audit

## 六、测试文件

- 代码级审计（SimpleTestCase）: `apps/radio_license/crud_audit_v2_tests.py`、`apps/contract_agreement/crud_audit_v2_tests.py`
- 行为级审计（TestCase）: `apps/contract_agreement/crud_audit_v2_tests.py::CABehavioralTests`
- 运行方式:
  ```bash
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.radio_license.crud_audit_v2_tests \
    apps.contract_agreement.crud_audit_v2_tests --keepdb --noinput -v2
  ```
- 测试结果: **28/28 PASS**
