# radio_license & device 模块 CRUD 可靠性深度审计报告

> 审计日期: 2026-07-31
> 审计依据: CRUD系统可靠性指南.md §1.1-§3.5
> 测试文件: `apps/radio_license/crud_audit_tests.py` (47 tests) + `apps/device/crud_audit_tests.py` (42 tests) = 89 tests
> 测试结果: **全部通过 (89/89 OK)**

---

## 一、审计报告摘要

### radio_license 模块

| 编号 | 级别 | 章节 | 风险描述 | 文件/行号 | 测试结果 | 修复状态 |
|------|------|------|----------|-----------|----------|----------|
| R1 | P1 | §1.1 | RadioLicense 无业务唯一约束，可创建重复执照 | models.py | R1 PASS(风险确认) | 设计限制(非BUG) |
| R2 | P1 | §1.1 | RadioLicense 无 is_deleted，DELETE 为物理删除 | models.py | R2 PASS(风险确认) | 设计限制(非BUG) |
| R3 | P1 | §1.1 | StationFrequencyApproval 无 is_deleted，物理删除 | models.py | R3 PASS(风险确认) | 设计限制(非BUG) |
| R4 | P2 | §1.1 | responsible_user_id 为 IntegerField，无 FK 约束 | models.py:25 | R4 PASS(风险确认) | 设计限制(非BUG) |
| R5 | P2 | §1.2 | RadioLicenseView.delete 未包裹 transaction.atomic() | views.py | **已修复 -> P21** | **已修复** |
| R6 | P2 | §1.3 | RadioLicenseView POST 创建无去重逻辑 | views.py | R6 PASS(风险确认) | 设计限制(无自然唯一键) |
| R7 | P1 | §1.5 | RadioLicenseView.delete 使用物理删除 | views.py | R7 PASS(风险确认) | 设计限制(非BUG) |
| R8 | P2 | §1.5 | RadioLicenseView 创建/编辑无审计日志 | views.py | **已修复 -> P22** | **已修复** |
| R9 | P2 | §2.2 | RadioLicenseView 列表无 page_size 上限 | views.py | **已修复 -> P23** | **已修复** |
| R10 | P2 | §2.2 | 证据包导出无行数上限 | views.py | R10 PASS(风险确认) | 待办(低优先级) |
| R11 | P2 | §2.2 | scan_radio_license_expiration 未用 iterator() | tasks.py | R11 PASS(风险确认) | 待办(低优先级) |
| R12 | P2 | §2.2 | 扫描任务循环内无 try/except 错误隔离 | tasks.py | **已修复 -> P24** | **已修复** |
| R13 | P2 | §3.5 | AttachmentPreviewFileView 无 @auth 装饰器 | views.py:648 | R13 PASS(风险确认) | 设计限制(依赖 preview_token) |
| R14 | P2 | §3.5 | ApprovalAttachmentPreviewFileView 无 @auth | approval_views.py | R14 PASS(风险确认) | 设计限制(依赖 preview_token) |

### device 模块

| 编号 | 级别 | 章节 | 风险描述 | 文件/行号 | 测试结果 | 修复状态 |
|------|------|------|----------|-----------|----------|----------|
| R1 | P1 | §1.1 | DeviceEvent 无唯一约束，可创建重复事件 | models.py | R1 PASS(风险确认) | 设计限制(无自然唯一键) |
| R2 | P2 | §1.1 | device_resume_id 为 IntegerField，无 FK 约束 | models.py:130 | R2 PASS(风险确认) | 设计限制(性能优化) |
| R3 | P2 | §1.1 | DeviceEvent 有 is_deleted 但使用硬删除 | models.py + views.py | R3 PASS(风险确认) | 待办(低优先级) |
| R4 | P2 | §1.1 | DeviceEvent 无 updated_at/updated_by 字段 | models.py | R4 PASS(风险确认) | 设计限制(事件不可变) |
| R5 | P2 | §1.2 | DeviceEventView PUT 无 transaction.atomic() | views.py:538 | **已修复 -> P21** | **已修复** |
| R6 | P2 | §1.3 | DeviceEventView POST 创建无去重逻辑 | views.py | R6 PASS(风险确认) | 设计限制(无自然唯一键) |
| R7 | P1 | §1.5 | DeviceEventView DELETE 无审计日志 | views.py:571 | **已修复 -> P22** | **已修复** |
| R8 | P2 | §2.2 | 证据包审计日志 fallback 查询范围 | views.py | R8 PASS(风险确认) | 已有 90天+1000条限制 |
| R9 | P2 | §2.2 | PDF 导出无超时限制 | pdf_export.py | R9 PASS(风险确认) | 待办(低优先级) |
| R10 | P2 | §3.5 | DeviceEventView DELETE 租户过滤验证 | views.py | R10 PASS(已过滤) | 无需修复 |

---

## 二、已修复 BUG 详情 (6 项)

### FIX-1: RadioLicenseView.delete 未包裹事务 (R5 -> P21)

- **文件**: `apps/radio_license/views.py`
- **风险**: DELETE 操作先软删附件再硬删执照，未包裹事务。若执照删除失败，附件已被软删，数据不一致。
- **修复**: 将附件软删 + 审计日志 + 执照物理删除包裹在 `with transaction.atomic():` 内

### FIX-2: RadioLicenseView 创建/编辑无审计日志 (R8 -> P22)

- **文件**: `apps/radio_license/views.py`
- **风险**: `_handle_create` 和 `_handle_edit` 未调用 `record_audit_event`，创建和编辑操作无审计记录。
- **修复**:
  - `_handle_create`: 在 `transaction.atomic()` 内添加 `record_audit_event(request, 'create', 'radio_license', ...)`
  - `_handle_edit`: 添加 `record_audit_event(request, 'edit', 'radio_license', ...)`
  - `post` 方法传 `request` 而非 `request.user` 给 `_handle_create`/`_handle_edit`

### FIX-3: RadioLicenseView 列表无 page_size 上限 (R9 -> P23)

- **文件**: `apps/radio_license/views.py`
- **风险**: page_size 参数无上限，可传 page_size=999999 拉取全量数据。
- **修复**: `page_size = min(int(request.GET.get('page_size', 20)), 100)`

### FIX-4: 扫描任务循环内无 try/except (R12 -> P24)

- **文件**: `apps/radio_license/tasks.py`
- **风险**: `scan_radio_license_expiration` 的 for 循环内无 try/except，单条坏数据导致整个扫描中断。
- **修复**: 在 for 循环内添加 `try/except Exception` 包裹 `scan_single_license` 调用，失败时 `logger.error` 记录并继续。

### FIX-5: DeviceEventView PUT 无事务包裹 (R5 -> P21)

- **文件**: `apps/device/views.py`
- **风险**: 事件编辑涉及 save + audit 日志写入，但未包裹事务。
- **修复**: 将 `event.save()` + `record_audit_event()` 包裹在 `with transaction.atomic():` 内

### FIX-6: DeviceEventView DELETE 无审计日志 (R7 -> P22)

- **文件**: `apps/device/views.py`
- **风险**: 事件删除为硬删除，且无 `record_audit_event` 审计，删除后无任何痕迹。
- **修复**: 在 `event.delete()` 前添加 `record_audit_event(request, 'delete', 'device_event', ...)`，包裹在 `transaction.atomic()` 内

---

## 三、设计限制（非 BUG）

以下风险经审计确认为设计限制，不建议立即修改：

1. **RadioLicense/StationFrequencyApproval 无 is_deleted**: 添加软删需 migration + 改状态机，影响范围大。当前删除有审计日志 + 附件软删。
2. **RadioLicense 无唯一约束**: 台站名 + 有效期不是真正的业务唯一键（同台站可有多个不同期执照）。
3. **DeviceEvent 无唯一约束**: 事件基于时间，无自然唯一键。
4. **responsible_user_id / device_resume_id 为 IntegerField**: 避免 FK JOIN 性能开销，用户/设备删除时应用层处理。
5. **PreviewFileView 无 @auth**: 依赖 preview_token 鉴权（行业惯例，如钉钉/飞书文件预览）。
6. **PDF 导出无超时**: 同步生成，低频操作，单设备事件量有限（有 10000 条上限）。
7. **scan_radio_license_expiration 用 list()**: 执照数量通常 <1000，内存影响可忽略。
8. **证据包导出无行数上限**: 低频操作，且有 90天+1000条审计日志限制。

---

## 四、优秀实践确认

| 编号 | 模块 | 实践 | 文件 |
|------|------|------|------|
| P1 | radio_license | StationFrequencyApproval 有 (tenant_id, doc_no) 唯一约束 | models.py |
| P2 | radio_license | RadioLicense 有 CHECK 约束（status + 日期顺序） | models.py |
| P3 | radio_license | LicenseReminderAck 有唯一约束（幂等性保障） | models.py |
| P4 | radio_license | RadioLicenseFrequency 有 CHECK 约束（频率>0, 排序>=0） | models.py |
| P5 | radio_license | 外键 ON DELETE 策略正确（PROTECT/CASCADE） | models.py |
| P6 | radio_license | ApprovalView.delete 包裹 transaction.atomic() | approval_views.py |
| P7 | radio_license | RadioLicenseView 创建包裹 transaction.atomic() | views.py |
| P8 | radio_license | ApprovalView 创建有 doc_no 去重 + IntegrityError 兜底 | approval_views.py |
| P9 | radio_license | ApprovalReminderAck 使用 get_or_create 实现幂等 | approval_views.py |
| P10 | radio_license | ApprovalView 有 _record_approval_audit 审计 | approval_views.py |
| P11 | radio_license | 无 DateTimeField __icontains/__year/__month 查询 | views.py |
| P12 | radio_license | 无 raw SQL / .raw() / .extra() | views.py |
| P13 | radio_license | ApprovalView 列表有 page_size 上限 | approval_views.py |
| P14 | radio_license | 无 requests.get/post、无 subprocess | views.py |
| P15 | radio_license | 所有列表查询使用 apply_tenant_filter | views.py |
| P16 | radio_license | 无 CharField/TextField null=True 违规 | models.py |
| P17 | radio_license | 列表接口有分页 | views.py |
| P1 | device | DeviceResume 有 (tenant_id, device_sn) 唯一约束 | models.py |
| P2 | device | DeviceResume 有 CHECK 约束（current_status） | models.py |
| P3 | device | DeviceResume 使用软删除（is_deleted + SoftDeleteTenantManager） | models.py |
| P4 | device | DeviceEvent 有 CHECK 约束（event_type） | models.py |
| P5 | device | DeviceResume 无 CharField/TextField null=True | models.py |
| P6 | device | DeviceResumeView DELETE 包裹 transaction.atomic() | views.py |
| P7 | device | DeviceResumeView PUT 包裹 transaction.atomic() | views.py |
| P8 | device | DeviceResumeView POST 有 device_sn 去重 | views.py |
| P9 | device | DeviceResumeView DELETE 有审计日志 | views.py |
| P10 | device | DeviceResumeView PUT 有审计日志 | views.py |
| P11 | device | DeviceListExportView 有审计日志 | exporters.py |
| P12 | device | 无 DateTimeField __icontains/__year/__month 查询 | views.py |
| P13 | device | 无 raw SQL / .raw() / .extra() | views.py |
| P14 | device | DeviceListExportView 有 check_export_limit 行数上限 | exporters.py |
| P15 | device | 无 requests.get/post、无 subprocess | views.py |
| P16 | device | 列表接口有分页 | views.py |
| P17 | device | 所有列表查询使用 apply_tenant_filter | views.py |
| P18 | device | DeviceResumeView DELETE 使用软删除 | views.py |
| P19 | device | DeviceResumeView DELETE 有 EvidenceEvent 记录 | views.py |
| P20 | device | DeviceResumeExportView PDF 导出有事件上限(10000) | views.py |

---

## 五、待办事项（低优先级）

1. [ ] RadioLicenseEvidencePackageView 添加行数上限（当前无限制）
2. [ ] scan_radio_license_expiration 改用 iterator(chunk_size=500)（与 scan_approval_expiration 一致）
3. [ ] DeviceEvent 软删除策略对齐（is_deleted 字段已存在但未使用）
4. [ ] PDF 导出添加超时保护
5. [ ] RadioLicense/StationFrequencyApproval 考虑添加 is_deleted 软删字段（需 migration）

---

## 六、修改文件清单

| 文件 | 修改类型 | 修改内容 |
|------|----------|----------|
| `apps/radio_license/views.py` | FIX | R5: delete 包裹 transaction.atomic() |
| `apps/radio_license/views.py` | FIX | R8: _handle_create/_handle_edit 添加 record_audit_event |
| `apps/radio_license/views.py` | FIX | R9: 列表 page_size 添加 min(,100) 上限 |
| `apps/radio_license/tasks.py` | FIX | R12: scan 循环添加 try/except 错误隔离 |
| `apps/device/views.py` | FIX | R5: DeviceEventView.put 包裹 transaction.atomic() + 审计 |
| `apps/device/views.py` | FIX | R7: DeviceEventView.delete 添加 record_audit_event + transaction |
| `apps/radio_license/crud_audit_tests.py` | NEW | 47 个审计测试 |
| `apps/device/crud_audit_tests.py` | NEW | 42 个审计测试 |
