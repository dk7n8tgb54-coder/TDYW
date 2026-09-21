# 权限审计覆盖缺口

生成时间: 2026-09-21 20:52:46

## 动态权限无法解析

- API: `/api/account/^login/$` - View: `login` - 需人工确认
- API: `/api/account/^logout/$` - View: `logout` - 需人工确认
- API: `/api/account/^user/tenant_choices/$` - View: `get_tenant_choices` - 需人工确认
- API: `/api/account/^user/restore/$` - View: `restore_user` - 需人工确认
- API: `/api/data-analysis/overview/` - View: `overview_view` - 需人工确认
- API: `/api/data-analysis/interference/` - View: `interference_view` - 需人工确认
- API: `/api/data-analysis/device/` - View: `device_view` - 需人工确认
- API: `/api/data-analysis/upgrade/` - View: `upgrade_view` - 需人工确认
- API: `/api/duty/duty/export/pdf/` - View: `export_pdf` - 需人工确认
- API: `/api/equipment_lifecycle/faults/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/start/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/recover/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/close/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/cancel/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/handling-records/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/handling-records/<int:rid>/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/handling-records/<int:rid>/attachments/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/dispatch/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/accept/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/start/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/submit-review/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/review-pass/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/review-return/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/close/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/cancel/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/handling-records/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/handling-records/<int:rid>/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/handling-records/<int:rid>/attachments/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/work-orders/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/faults/<int:pk>/create-work-order/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-fault/` - View: `_na` - 需人工确认
- API: `/api/equipment_lifecycle/ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-work-order/` - View: `_na` - 需人工确认
- API: `/api/home/statistic/` - View: `get_statistic` - 需人工确认
- API: `/api/interference/^events/(?P<pk>\d+)/attachments/$` - View: `EventAttachmentListView` - 需人工确认
- API: `/api/interference/^investigations/(?P<pk>\d+)/attachments/$` - View: `InvestigationAttachmentListView` - 需人工确认
- API: `/api/interference/^measurements/(?P<pk>\d+)/attachments/$` - View: `MeasurementAttachmentListView` - 需人工确认
- API: `/api/setting/^email_test/$` - View: `email_test` - 需人工确认
- API: `/api/setting/^about/$` - View: `get_about` - 需人工确认

## 数据库权限数据

- 数据库权限数据未直接查询（需要 Docker 环境）
- 运行时测试脚本已生成，可在 Docker 环境中执行验证
- 角色权限矩阵需要从数据库中读取 Role.page_perms 数据

## Redis 权限缓存

- 缓存测试脚本已生成，可在 Docker 环境中执行
- 测试脚本位置: `quality/permission_audit/tests/runtime/test_permission_behavior.py`

## 前端解析限制

- routes.js 使用正则+状态机解析，非完整 AST
- 动态 import 页面可能未被发现
- 嵌套路由的子路由权限可能未完全覆盖

## 业务权限含义不明确

- View 'login' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'logout' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'get_tenant_choices' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'restore_user' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'overview_view' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'interference_view' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'device_view' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'upgrade_view' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'export_pdf' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View '_na' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'get_statistic' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'EventAttachmentListView' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'InvestigationAttachmentListView' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'MeasurementAttachmentListView' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'email_test' could not be resolved by static analysis. May be a function-based view or dynamically imported.
- View 'get_about' could not be resolved by static analysis. May be a function-based view or dynamically imported.

## 未纳入的条件性模块

- schedule（排班模块）已删除，不在审计范围
- shift_handover（交接班模块）已删除，不在审计范围
- 非正式模块（backups/scripts/locustfile 等）不在审计范围
