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
    event_views, fault_progress_views, fault_views, inspection_views, ledger_row_views,
    ledger_views, views, work_order_views,
)
from apps.upgrade.views.system_records import SystemUpgradeRecordsView


def _na(view):
    """动作视图装配：关闭请求级原子事务（见模块 docstring 的锁提交顺序说明）。"""
    return transaction.non_atomic_requests(view)


urlpatterns = [
    # 系统主数据
    path('systems/', views.SystemView.as_view()),
    path('systems/export/', views.SystemExportView.as_view()),
    path('systems/status-summary/', views.SystemStatusSummaryView.as_view()),
    path('systems/<int:pk>/', views.SystemDetailView.as_view()),
    path('systems/<int:pk>/active/', views.SystemActiveView.as_view()),
    # 按系统查询故障（主体/受影响）
    path('systems/<int:pk>/faults/', fault_views.SystemFaultListView.as_view()),
    # 系统故障（步骤 3.1）
    path('faults/', _na(fault_views.FaultView.as_view())),
    path('faults/export/', fault_views.FaultExportView.as_view()),
    path('faults/candidate-systems/', fault_views.FaultCandidateSystemsView.as_view()),
    path('faults/<int:pk>/', _na(fault_views.FaultDetailView.as_view())),
    path('faults/<int:pk>/start/', _na(fault_views.FaultStartView.as_view())),
    path('faults/<int:pk>/recover/', _na(fault_views.FaultRecoverView.as_view())),
    path('faults/<int:pk>/close/', _na(fault_views.FaultCloseView.as_view())),
    path('faults/<int:pk>/cancel/', _na(fault_views.FaultCancelView.as_view())),
    path('faults/<int:pk>/handling-records/', _na(fault_progress_views.FaultHandlingRecordView.as_view())),
    path('faults/<int:pk>/handling-records/<int:rid>/', _na(fault_progress_views.FaultHandlingRecordDetailView.as_view())),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/', _na(fault_progress_views.FaultHandlingAttachmentView.as_view())),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/download/', fault_progress_views.FaultHandlingAttachmentDownloadView.as_view()),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/', _na(fault_progress_views.FaultHandlingAttachmentDetailView.as_view())),
    # ==================== 运维台账（步骤 3.2） ====================
    # 台账模板
    path('ledger-templates/', ledger_views.LedgerTemplateView.as_view()),
    path('ledger-templates/available/', ledger_views.LedgerTemplateAvailableView.as_view()),
    path('ledger-templates/<int:pk>/', ledger_views.LedgerTemplateDetailView.as_view()),
    path('ledger-templates/<int:pk>/active/', ledger_views.LedgerTemplateActiveView.as_view()),
    path('ledger-templates/<int:pk>/items/', ledger_views.LedgerTemplateItemView.as_view()),
    path('ledger-templates/<int:pk>/items/<int:iid>/', ledger_views.LedgerTemplateItemDetailView.as_view()),
    # 台账模板行节点（第一阶段行对象树：行方向多级，列方向保持平面）
    path('ledger-templates/<int:pk>/row-nodes/', ledger_row_views.LedgerTemplateRowNodesView.as_view()),
    path('ledger-templates/<int:pk>/row-nodes/sort/', ledger_row_views.LedgerTemplateRowNodeSortView.as_view()),
    path('ledger-templates/<int:pk>/row-nodes/<int:nid>/', ledger_row_views.LedgerTemplateRowNodeDetailView.as_view()),
    path('ledger-templates/<int:pk>/row-nodes/<int:nid>/active/', ledger_row_views.LedgerTemplateRowNodeActiveView.as_view()),
    # 台账
    path('ledgers/', ledger_views.LedgerView.as_view()),
    path('ledgers/preview/', ledger_views.LedgerPreviewView.as_view()),
    path('ledgers/abnormal-items/', ledger_views.LedgerAbnormalItemsView.as_view()),
    path('ledgers/export/', ledger_views.LedgerExportView.as_view()),
    path('ledgers/<int:pk>/', ledger_views.LedgerDetailView.as_view()),
    # 矩阵台账行实例与单元格（第一阶段）
    path('ledgers/<int:pk>/row-instances/', ledger_row_views.LedgerRowInstanceView.as_view()),
    path('ledgers/<int:pk>/row-instances/<int:iid>/', ledger_row_views.LedgerRowInstanceDetailView.as_view()),
    path('ledgers/<int:pk>/cells/', ledger_row_views.LedgerCellsView.as_view()),
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
    # ==================== 工单管理与异常转单（步骤 3.3） ====================
    # 工单
    path('work-orders/', _na(work_order_views.WorkOrderView.as_view())),
    path('work-orders/export/', work_order_views.WorkOrderExportView.as_view()),
    path('work-orders/candidate-systems/', work_order_views.WorkOrderCandidateSystemsView.as_view()),
    path('work-orders/candidate-users/', work_order_views.WorkOrderCandidateUsersView.as_view()),
    path('work-orders/<int:pk>/', _na(work_order_views.WorkOrderDetailView.as_view())),
    # 完成工单（单账号协同流程：执行中 → 已完成，无派发/接单/复核环节，
    # 旧 dispatch/accept/start/submit-review/review-* 路由已删除）
    path('work-orders/<int:pk>/complete/', _na(work_order_views.WorkOrderCompleteView.as_view())),
    path('work-orders/<int:pk>/close/', _na(work_order_views.WorkOrderCloseView.as_view())),
    path('work-orders/<int:pk>/cancel/', _na(work_order_views.WorkOrderCancelView.as_view())),
    path('work-orders/<int:pk>/handling-records/', _na(work_order_views.WorkOrderHandlingRecordView.as_view())),
    path('work-orders/<int:pk>/handling-records/<int:rid>/', _na(work_order_views.WorkOrderHandlingRecordDetailView.as_view())),
    path('work-orders/<int:pk>/handling-records/<int:rid>/attachments/', _na(work_order_views.WorkOrderHandlingAttachmentView.as_view())),
    path('work-orders/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/download/', work_order_views.WorkOrderHandlingAttachmentDownloadView.as_view()),
    path('work-orders/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/', _na(work_order_views.WorkOrderHandlingAttachmentDetailView.as_view())),
    # 来源与转单
    path('faults/<int:pk>/work-orders/', work_order_views.FaultWorkOrdersView.as_view()),
    path('faults/<int:pk>/create-work-order/', _na(work_order_views.FaultCreateWorkOrderView.as_view())),
    path('ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-fault/', _na(work_order_views.LedgerItemConvertToFaultView.as_view())),
    path('ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-work-order/', _na(work_order_views.LedgerItemConvertToWorkOrderView.as_view())),
    # 按系统查询工单（目标/受影响）
    path('systems/<int:pk>/work-orders/', work_order_views.SystemWorkOrdersView.as_view()),
    # 按系统查询升级记录（系统详情"升级记录"页签，视图在 upgrade app）
    path('systems/<int:pk>/upgrade-records/', SystemUpgradeRecordsView.as_view()),
    # ==================== 值班巡检（今日巡检改造，独立巡检模型） ====================
    # 巡检模板（模板 → 设备名称 → 检查内容，设备名称不关联系统）
    path('inspection-templates/', inspection_views.InspectionTemplateView.as_view()),
    path('inspection-templates/available/', inspection_views.InspectionTemplateAvailableView.as_view()),
    path('inspection-templates/<int:pk>/', inspection_views.InspectionTemplateDetailView.as_view()),
    path('inspection-templates/<int:pk>/active/', inspection_views.InspectionTemplateActiveView.as_view()),
    # 值班巡检单（值班日 + 模板唯一；四轮固定；只记录结果与现场处理，不提供转故障/转工单接口）
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
    # ==================== 统一系统履历（步骤 3.4，只读 append-only） ====================
    path('system-events/', event_views.SystemEventView.as_view()),
    path('system-events/export/', event_views.SystemEventExportView.as_view()),
    path('systems/<int:pk>/system-events/', event_views.SystemEventsUnderSystemView.as_view()),
    # 系统履历事项聚合（按系统分组 + 业务事项聚合；只读，健康状态/配置快照不参与）
    path('system-event-groups/', event_views.SystemEventGroupView.as_view()),
    path('system-event-groups/nodes/', event_views.SystemEventGroupNodesView.as_view()),
    path('system-event-groups/export/', event_views.SystemEventGroupExportView.as_view()),
]
