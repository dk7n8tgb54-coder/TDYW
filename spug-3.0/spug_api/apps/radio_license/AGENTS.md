# spug_api/apps/radio_license/AGENTS.md - 无线电台执照 / 台站频率批复模块规则

> 本文件覆盖 `apps/radio_license/` 内执照与批复两条业务线的特殊规则，补充但不推翻根目录与 `spug_api/AGENTS.md`。

## 一、一个应用，两套数据范围规则

`radio_license` 后端应用同时承载**无线电台执照**（views.py）与**台站频率批复**（approval_views.py）。二者数据范围规则不同，改动前必须先确认目标业务线：

| 业务线 | 数据范围 | tenant_id 语义 | 责任人 | 主动提醒 |
|---|---|---|---|---|
| RadioLicense（执照） | **租户私有**，查询必须 `apply_tenant_filter` | 访问边界 | 保留（`responsible_user_id/name` + 责任人候选接口） | 保留（popup / ack / badge / `LicenseReminderAck`） |
| StationFrequencyApproval（批复） | **有权限用户全局共享**（2026-09 起），查询不做租户过滤 | 仅创建人来源、附件归属与审计信息 | **已删除**（字段、索引、候选接口、快照字段） | **无个人主动提醒**：popup / ack / 责任人候选接口与 `StationFrequencyApprovalReminderAck` 已删除，指定提醒接收人不实现；菜单红点为全局只读统计（`StationFrequencyApprovalBadgeView`，2026-09 第二轮恢复，见下） |

### 批复菜单红点（badge）约束（2026-09 第二轮恢复）

`GET /radio-license/approvals/badge/`（`StationFrequencyApprovalBadgeView`，权限 `radio_license.approval.view`）是**全局只读统计**：

1. 直接统计全部 `StationFrequencyApproval`，**不调用 `apply_tenant_filter`、不按请求账户 `tenant_id`、责任人或 ACK 筛选**——所有拥有 `approval.view` 的账户看到相同数字。
2. 按 `valid_to` 实时统计（expiring：`today <= valid_to <= today + EXPIRING_DAYS_THRESHOLD`；expired：`valid_to < today`；`count = expiring + expired`），不依赖缓存 `status` 字段或 Celery 扫描。
3. **不创建任何数据库副作用**：不写 ACK、提醒、审计日志或证据事件；纯只读端点。
4. 不恢复批复 popup / ack 接口、`StationFrequencyApprovalReminderAck`、责任人字段或指定提醒接收人。

约定：

1. 批复的可见性与可管性只由 `@auth('radio_license.approval.*')` 权限装饰器 + 方法内 `has_perms` 决定；不得给批复查询重新加回 `apply_tenant_filter`，也不得把"跨租户放行"扩散到执照。
2. 批复新增仍用 `assign_tenant_id(form, user)` 记录创建人租户；编辑/删除不得改写 `tenant_id`。
3. 批复列表/详情的 `status`/`days_left` 一律按 `valid_to` 实时计算（`_compute_approval_status_fields`）；缓存 `status` 字段只由 `scan_single_approval` / `scan_approval_expiration` 维护（新增/编辑后即时调用一次 + 每日 Beat 兜底）。
4. 执照侧规则（责任人校验、提醒 ack、租户隔离）与本文件批复章节互不适用；修改 views.py 时不要"顺手对齐"批复。

## 二、批复附件跨租户安全闸门（父对象先行）

批复全局共享后，其附件通过**局部跳过** `EvidenceAttachment` 租户过滤实现跨租户访问，但闸门条件是强制的——批复附件端点调用 `AttachmentService` 前必须经 `_get_approval_attachment_for_user` / `_get_approval_by_id` 校验，全部满足才放行：

1. 附件存在且未软删除（默认 Manager 已过滤 `is_deleted`）；
2. `module == 'radio_license'` 且 `object_type == 'approval'`（防跨模块/跨对象类型越权）；
3. `attachment.object_id` 对应的父批复真实存在。

各端点要求：

| 操作 | 权限 | 额外规则 |
|---|---|---|
| 附件列表 / 计数 | `approval.view` | 父批复校验后 `AttachmentService.list(..., skip_tenant_filter=True)` |
| 下载 | `attachment.download` + `approval.view` | `download_response(..., skip_tenant_filter=True)` |
| 预览 URL | `approval.view` | `get_preview_url(..., skip_tenant_filter=True)`；preview_token 绑定附件真实 `tenant_id`，不绑定查看者租户 |
| 上传 | `attachment.upload` + `approval.view` | `upload(..., owner_tenant_id=approval.tenant_id)`：新附件归属**父批复租户**，非上传人租户 |
| 删除附件 | `attachment.delete` + `approval.view` | 父批复校验后 `soft_delete(..., skip_tenant_filter=True)` 跨租户软删 |
| 删除批复 | `approval.del` | `soft_delete_by_object(..., skip_tenant_filter=True)` 只软删该批复 module/object_type/object_id 匹配的附件 |

约束：

1. **`skip_tenant_filter` 是豁免口子，默认必须为 False**。`AttachmentService` 各方法只在批复路径传 `True`；其他模块（执照、合同、干扰、公告、协作任务、升级）不得传。新增调用方时先全局搜索评估。
2. 软删除校验不被豁免：`is_deleted=True` 的批复附件即使跨租户有权限也必须拒绝。
3. 失败响应统一为「附件不存在或无权限访问 / 删除」，不泄露租户、路径、真实模块。
4. 证据事件（`record_evidence_event`）用删除前快照写入，`tenant_id` 取附件记录值。
