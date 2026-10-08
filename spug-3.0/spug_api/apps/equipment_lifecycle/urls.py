# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期 URL 装配（步骤 3.5 收口）。

- API 前缀 /equipment-lifecycle/（由项目根 urls.py 按发布开关挂载）；
- 所有持健康重算锁（health_recalc_lock）的动作视图以 non_atomic_requests
  装配：ATOMIC_REQUESTS 下请求级事务会延后到视图返回后才真正提交，
  若锁在视图内先释放，并发重算会读到未提交数据、以陈旧结果覆盖状态；
  关闭请求级事务后，视图内 transaction.atomic 即为真实事务，
  "锁 → 事务提交 → 释放锁"顺序成立（步骤 3.5 修复 GET_LOCK 提交窗口）。
"""
from django.db import transaction
from django.urls import path

from apps.equipment_lifecycle import (
    config_attachment_views, config_views,
    event_views, excel_ledger_views, excel_template_views, fault_progress_views,
    fault_views, inspection_views, ledger_views,
    runtime_record_attachment_views, runtime_record_v2_views, runtime_record_views,
    views,
)
from apps.upgrade.views.system_records import SystemUpgradeRecordsView


def _na(view):
    """动作视图装配：关闭请求级原子事务（见模块 docstring 的锁提交顺序说明）。"""
    return transaction.non_atomic_requests(view)


urlpatterns = [
    # 系统主数据
    path('systems/', views.SystemView.as_view()),
    path('systems/export/', views.SystemExportView.as_view()),
    path('systems/<int:pk>/', views.SystemDetailView.as_view()),
    path('systems/<int:pk>/active/', views.SystemActiveView.as_view()),
    # 按系统查询故障（主体/受影响）
    path('systems/<int:pk>/faults/', fault_views.SystemFaultListView.as_view()),
    # 系统故障（步骤 3.1）
    path('faults/', _na(fault_views.FaultView.as_view())),
    path('faults/export/', fault_views.FaultExportView.as_view()),
    path('faults/candidate-systems/', fault_views.FaultCandidateSystemsView.as_view()),
    path('faults/<int:pk>/', _na(fault_views.FaultDetailView.as_view())),
    # start 路由已随"开始处置"步骤整体删除（2026-10 流程简化：新建即处置中，
    # 存量 pending 由迁移 0050 转换；确认恢复并结案接口兼容 pending/recovered）
    path('faults/<int:pk>/recover/', _na(fault_views.FaultRecoverView.as_view())),
    # 原因分析专用更新（2026-10）：详情页"补充原因分析/修改"弹窗保存出口，
    # 只提交原因分析字段（fault.edit 权限 + 审计），仅处置中可修改
    path('faults/<int:pk>/reason-analysis/', _na(fault_views.FaultReasonAnalysisView.as_view())),
    # close 路由保留但已废弃：视图返回清晰业务错误（合并至 recover 单事务操作）
    path('faults/<int:pk>/close/', _na(fault_views.FaultCloseView.as_view())),
    path('faults/<int:pk>/cancel/', _na(fault_views.FaultCancelView.as_view())),
    path('faults/<int:pk>/handling-records/', _na(fault_progress_views.FaultHandlingRecordView.as_view())),
    path('faults/<int:pk>/handling-records/<int:rid>/', _na(fault_progress_views.FaultHandlingRecordDetailView.as_view())),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/', _na(fault_progress_views.FaultHandlingAttachmentView.as_view())),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/download/', fault_progress_views.FaultHandlingAttachmentDownloadView.as_view()),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/', _na(fault_progress_views.FaultHandlingAttachmentDetailView.as_view())),
    # ==================== 运维台账（步骤 3.2） ====================
    # 旧可视化台账模板 / 行节点 / 行实例 / 单元格接口已随旧可视化模板路线
    # 整体删除（2026-10，迁移 0045 清理数据与表）；正式新增台账统一走
    # Excel/WPS 模板路线（excel-templates / excel-ledgers）。
    # Excel 上传版维护台账模板（2026-09-28 试点：固定版式 .xlsx 草稿 + 不可变发布版本；
    # 台账创建走 excel-ledgers）
    path('excel-templates/available/', excel_template_views.ExcelTemplateAvailableView.as_view()),
    path('excel-templates/sample/', excel_template_views.ExcelTemplateSampleView.as_view()),
    path('excel-templates/', excel_template_views.ExcelTemplateView.as_view()),
    path('excel-templates/<int:pk>/', excel_template_views.ExcelTemplateDetailView.as_view()),
    path('excel-templates/<int:pk>/draft-file/', excel_template_views.ExcelTemplateDraftFileView.as_view()),
    path('excel-templates/<int:pk>/bindings/', excel_template_views.ExcelTemplateBindingsView.as_view()),
    path('excel-templates/<int:pk>/pdf-params/', excel_template_views.ExcelTemplatePdfParamsView.as_view()),
    path('excel-templates/<int:pk>/publish/', excel_template_views.ExcelTemplatePublishView.as_view()),
    path('excel-templates/<int:pk>/versions/', excel_template_views.ExcelTemplateVersionListView.as_view()),
    path('excel-templates/<int:pk>/versions/<int:version_no>/', excel_template_views.ExcelTemplateVersionDetailView.as_view()),
    path('excel-templates/<int:pk>/preview/pdf/', excel_template_views.ExcelTemplatePdfPreviewView.as_view()),
    # Excel 路线维护台账（created_from=excel_template；复核/退回/作废沿用既有 ledgers 端点）
    path('excel-ledgers/', excel_ledger_views.ExcelLedgerView.as_view()),
    path('excel-ledgers/<int:pk>/', excel_ledger_views.ExcelLedgerDetailView.as_view()),
    path('excel-ledgers/<int:pk>/submit/', excel_ledger_views.ExcelLedgerSubmitView.as_view()),
    path('excel-ledgers/<int:pk>/export/check/', excel_ledger_views.ExcelLedgerExportCheckView.as_view()),
    path('excel-ledgers/<int:pk>/export/excel/', excel_ledger_views.ExcelLedgerExportView.as_view(), {'fmt': 'excel'}),
    path('excel-ledgers/<int:pk>/export/pdf/', excel_ledger_views.ExcelLedgerExportView.as_view(), {'fmt': 'pdf'}),
    # 台账
    path('ledgers/', ledger_views.LedgerView.as_view()),
    path('ledgers/abnormal-items/', ledger_views.LedgerAbnormalItemsView.as_view()),
    path('ledgers/export/', ledger_views.LedgerExportView.as_view()),
    path('ledgers/<int:pk>/', ledger_views.LedgerDetailView.as_view()),
    path('ledgers/<int:pk>/submit/', ledger_views.LedgerSubmitView.as_view()),
    path('ledgers/<int:pk>/return/', ledger_views.LedgerReturnView.as_view()),
    path('ledgers/<int:pk>/review/', ledger_views.LedgerReviewView.as_view()),
    path('ledgers/<int:pk>/void/', ledger_views.LedgerVoidView.as_view()),
    path('ledgers/<int:pk>/correct/', ledger_views.LedgerCorrectView.as_view()),
    path('ledgers/<int:pk>/confirm-normal/', ledger_views.LedgerConfirmNormalView.as_view()),
    # 台账附件（表头）
    path('ledgers/<int:pk>/attachments/', ledger_views.LedgerAttachmentView.as_view()),
    path('ledgers/<int:pk>/attachments/<int:aid>/download/', ledger_views.LedgerAttachmentDownloadView.as_view()),
    path('ledgers/<int:pk>/attachments/<int:aid>/', ledger_views.LedgerAttachmentDetailView.as_view()),
    # 台账附件（明细）
    path('ledgers/<int:pk>/items/<int:item_pk>/attachments/', ledger_views.LedgerItemAttachmentView.as_view()),
    path('ledgers/<int:pk>/items/<int:item_pk>/attachments/<int:aid>/download/', ledger_views.LedgerItemAttachmentDownloadView.as_view()),
    path('ledgers/<int:pk>/items/<int:item_pk>/attachments/<int:aid>/', ledger_views.LedgerItemAttachmentDetailView.as_view()),
    # 按系统查询台账明细（系统详情页台账 Tab）
    path('systems/<int:pk>/ledger-items/', ledger_views.SystemLedgerItemsView.as_view()),
    # 候选人员（本租户有效账户；今日巡检值班人员登记等场景使用。
    # 原路径 work-orders/candidate-users/ 已随工单功能删除，2026-09-30）
    path('candidate-users/', views.CandidateUsersView.as_view()),
    # 台账异常明细转故障（2026-09-30 工单下线，视图自 work_order_views 迁入
    # fault_views；convert-to-work-order 路由一并删除）
    path('ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-fault/', _na(fault_views.LedgerItemConvertToFaultView.as_view())),
    # 按系统查询升级记录（系统详情"升级记录"页签，视图在 upgrade app）
    path('systems/<int:pk>/upgrade-records/', SystemUpgradeRecordsView.as_view()),
    # ==================== 值班巡检（今日巡检改造，独立巡检模型） ====================
    # 巡检模板（模板 → 设备名称 → 检查内容，设备名称不关联系统）
    path('inspection-templates/', inspection_views.InspectionTemplateView.as_view()),
    path('inspection-templates/available/', inspection_views.InspectionTemplateAvailableView.as_view()),
    path('inspection-templates/<int:pk>/', inspection_views.InspectionTemplateDetailView.as_view()),
    path('inspection-templates/<int:pk>/active/', inspection_views.InspectionTemplateActiveView.as_view()),
    # 值班巡检单（值班日 + 模板唯一；四轮固定；只记录结果与现场处理，不提供转故障接口）
    path('inspection-sheets/export/', inspection_views.InspectionSheetExportView.as_view()),
    path('inspection-sheets/batch-export/xlsx/', inspection_views.InspectionSheetBatchExportXlsxView.as_view()),
    path('inspection-sheets/batch-export/pdf/', inspection_views.InspectionSheetBatchExportPdfView.as_view()),
    path('inspection-sheets/', inspection_views.InspectionSheetView.as_view()),
    path('inspection-sheets/<int:pk>/export/xlsx/', inspection_views.InspectionSheetDetailExportXlsxView.as_view()),
    path('inspection-sheets/<int:pk>/export/pdf/', inspection_views.InspectionSheetDetailExportPdfView.as_view()),
    path('inspection-sheets/<int:pk>/', inspection_views.InspectionSheetDetailView.as_view()),
    path('inspection-sheets/<int:pk>/submit/', inspection_views.InspectionSheetSubmitView.as_view()),
    path('inspection-sheets/<int:pk>/void/', inspection_views.InspectionSheetVoidView.as_view()),
    # 超级管理员退回整改（仅 submitted → returned，后端显式校验 is_supper）
    path('inspection-sheets/<int:pk>/return/', inspection_views.InspectionSheetReturnView.as_view()),
    # ==================== 运行记录（2026-10，第一版） ====================
    # 异常与运行情况统一录入入口；创建（编号锁）与转故障（健康重算锁）动作
    # 以 non_atomic_requests 装配（锁 → 事务提交 → 释放锁 顺序成立）。
    # 旧 triage/close 兼容端点已随 2026-10-06 旧状态归一（迁移 0007）删除；
    # 旧 similar/duplicate-links/mark-repeated 端点已随重复问题功能退役
    # （迁移 0008）删除；跟进计划端点（follow-up）已随跟进计划功能退役
    # （迁移 0009）删除：重新跟进由追加处理进展触发。
    path('runtime-records/', _na(runtime_record_views.RuntimeRecordView.as_view())),
    path('runtime-records/<int:pk>/', runtime_record_views.RuntimeRecordDetailView.as_view()),
    path('runtime-records/<int:pk>/progress/', runtime_record_views.RuntimeRecordProgressView.as_view()),
    path('runtime-records/<int:pk>/progress/<int:rid>/', runtime_record_views.RuntimeRecordProgressDetailView.as_view()),
    path('runtime-records/<int:pk>/convert-to-fault/', _na(runtime_record_views.RuntimeRecordConvertToFaultView.as_view())),
    path('runtime-records/<int:pk>/resolve/', runtime_record_views.RuntimeRecordResolveView.as_view()),
    path('runtime-records/<int:pk>/attachments/', runtime_record_attachment_views.RuntimeRecordAttachmentView.as_view()),
    path('runtime-records/<int:pk>/attachments/<int:aid>/download/', runtime_record_attachment_views.RuntimeRecordAttachmentDownloadView.as_view()),
    path('runtime-records/<int:pk>/attachments/<int:aid>/', runtime_record_attachment_views.RuntimeRecordAttachmentDetailView.as_view()),
    # ==================== 运行记录第二版（2026-10）：待办/统计 ====================
    # 待办（仅跟进中）与只读统计（仅运行记录数据）
    path('runtime-records/todo/', runtime_record_v2_views.RuntimeRecordTodoView.as_view()),
    path('runtime-records/statistics/', runtime_record_v2_views.RuntimeRecordStatisticsView.as_view()),
    # 按系统查询运行记录（系统详情"运行记录"页签）
    path('systems/<int:pk>/runtime-records/', runtime_record_views.SystemRuntimeRecordsView.as_view()),
    # ==================== 系统配置（2026-10：系统详情"配置"页签） ====================
    # 只在系统详情内展示，不设独立菜单；配置值只经"创建草稿 → 应用生效"流程
    # 写入；创建/回退持编号锁（non_atomic 装配），应用/验证/取消走请求级事务+行锁。
    path('systems/<int:pk>/config/', config_views.SystemConfigView.as_view()),
    path('systems/<int:pk>/config/param-options/', config_views.SystemConfigParamOptionsView.as_view()),
    path('systems/<int:pk>/config/changes/', config_views.SystemConfigChangeListView.as_view()),
    path('config-changes/', _na(config_views.ConfigChangeView.as_view())),
    path('config-changes/<int:pk>/', config_views.ConfigChangeDetailView.as_view()),
    path('config-changes/<int:pk>/apply/', config_views.ConfigChangeApplyView.as_view()),
    path('config-changes/<int:pk>/verify/', config_views.ConfigChangeVerifyView.as_view()),
    path('config-changes/<int:pk>/rollback/', _na(config_views.ConfigChangeRollbackView.as_view())),
    path('config-changes/<int:pk>/cancel/', config_views.ConfigChangeCancelView.as_view()),
    path('config-changes/<int:pk>/attachments/', config_attachment_views.ConfigChangeAttachmentView.as_view()),
    path('config-changes/<int:pk>/attachments/<int:aid>/download/', config_attachment_views.ConfigChangeAttachmentDownloadView.as_view()),
    path('config-changes/<int:pk>/attachments/<int:aid>/', config_attachment_views.ConfigChangeAttachmentDetailView.as_view()),
    # 配置参数定义（view 查询 / template 维护；只新增编辑停用，无删除）
    path('config-params/', config_views.ConfigParamView.as_view()),
    path('config-params/<int:pk>/', config_views.ConfigParamDetailView.as_view()),
    # ==================== 统一系统履历（步骤 3.4，只读 append-only） ====================
    path('system-events/', event_views.SystemEventView.as_view()),
    path('system-events/export/', event_views.SystemEventExportView.as_view()),
    path('systems/<int:pk>/system-events/', event_views.SystemEventsUnderSystemView.as_view()),
    # 系统履历事项聚合（按系统分组 + 业务事项聚合；只读，健康状态/配置快照不参与）
    path('system-event-groups/', event_views.SystemEventGroupView.as_view()),
    path('system-event-groups/nodes/', event_views.SystemEventGroupNodesView.as_view()),
    path('system-event-groups/export/', event_views.SystemEventGroupExportView.as_view()),
]
