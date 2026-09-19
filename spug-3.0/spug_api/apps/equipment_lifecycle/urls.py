# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from apps.equipment_lifecycle import fault_views, ledger_views, views, work_order_views

urlpatterns = [
    # 系统类型
    path('system-types/', views.SystemTypeView.as_view()),
    path('system-types/<int:pk>/', views.SystemTypeDetailView.as_view()),
    path('system-types/<int:pk>/fields/', views.TypeFieldView.as_view()),
    path('system-types/<int:pk>/fields/<int:fid>/', views.TypeFieldDetailView.as_view()),
    # 系统主数据
    path('systems/', views.SystemView.as_view()),
    path('systems/export/', views.SystemExportView.as_view()),
    path('systems/form-fields/', views.SystemFormFieldsView.as_view()),
    path('systems/<int:pk>/', views.SystemDetailView.as_view()),
    path('systems/<int:pk>/active/', views.SystemActiveView.as_view()),
    path('systems/<int:pk>/config/', views.SystemConfigView.as_view()),
    path('systems/<int:pk>/config/export/', views.SystemConfigExportView.as_view()),
    path('systems/<int:pk>/config/attachments/', views.SystemConfigAttachmentView.as_view()),
    path('systems/<int:pk>/config/attachments/<int:aid>/download/', views.SystemConfigAttachmentDownloadView.as_view()),
    path('systems/<int:pk>/config/attachments/<int:aid>/', views.SystemConfigAttachmentDetailView.as_view()),
    path('systems/<int:pk>/components/', views.SystemComponentView.as_view()),
    path('systems/<int:pk>/components/<int:cid>/', views.SystemComponentDetailView.as_view()),
    path('systems/<int:pk>/custom-fields/', views.CustomFieldView.as_view()),
    path('systems/<int:pk>/custom-fields/<int:fid>/', views.CustomFieldDetailView.as_view()),
    path('systems/<int:pk>/custom-fields/<int:fid>/promote/', views.CustomFieldPromoteView.as_view()),
    path('systems/<int:pk>/changes/', views.SystemChangeView.as_view()),
    path('systems/<int:pk>/snapshots/', views.SystemSnapshotView.as_view()),
    path('systems/<int:pk>/snapshots/<int:sid>/', views.SystemSnapshotDetailView.as_view()),
    # 按系统查询故障（主体/受影响）
    path('systems/<int:pk>/faults/', fault_views.SystemFaultListView.as_view()),
    # 系统故障（步骤 3.1）
    path('faults/', fault_views.FaultView.as_view()),
    path('faults/export/', fault_views.FaultExportView.as_view()),
    path('faults/candidate-systems/', fault_views.FaultCandidateSystemsView.as_view()),
    path('faults/<int:pk>/', fault_views.FaultDetailView.as_view()),
    path('faults/<int:pk>/start/', fault_views.FaultStartView.as_view()),
    path('faults/<int:pk>/recover/', fault_views.FaultRecoverView.as_view()),
    path('faults/<int:pk>/close/', fault_views.FaultCloseView.as_view()),
    path('faults/<int:pk>/cancel/', fault_views.FaultCancelView.as_view()),
    path('faults/<int:pk>/handling-records/', fault_views.FaultHandlingRecordView.as_view()),
    path('faults/<int:pk>/handling-records/<int:rid>/', fault_views.FaultHandlingRecordDetailView.as_view()),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/', fault_views.FaultHandlingAttachmentView.as_view()),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/download/', fault_views.FaultHandlingAttachmentDownloadView.as_view()),
    path('faults/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/', fault_views.FaultHandlingAttachmentDetailView.as_view()),
    # ==================== 运维台账（步骤 3.2） ====================
    # 巡检点
    path('inspection-points/', ledger_views.InspectionPointView.as_view()),
    path('inspection-points/<int:pk>/', ledger_views.InspectionPointDetailView.as_view()),
    path('inspection-points/<int:pk>/active/', ledger_views.InspectionPointActiveView.as_view()),
    # 台账模板
    path('ledger-templates/', ledger_views.LedgerTemplateView.as_view()),
    path('ledger-templates/available/', ledger_views.LedgerTemplateAvailableView.as_view()),
    path('ledger-templates/<int:pk>/', ledger_views.LedgerTemplateDetailView.as_view()),
    path('ledger-templates/<int:pk>/active/', ledger_views.LedgerTemplateActiveView.as_view()),
    path('ledger-templates/<int:pk>/items/', ledger_views.LedgerTemplateItemView.as_view()),
    path('ledger-templates/<int:pk>/items/<int:iid>/', ledger_views.LedgerTemplateItemDetailView.as_view()),
    # 台账
    path('ledgers/', ledger_views.LedgerView.as_view()),
    path('ledgers/preview/', ledger_views.LedgerPreviewView.as_view()),
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
    # ==================== 工单管理与异常转单（步骤 3.3） ====================
    # 工单
    path('work-orders/', work_order_views.WorkOrderView.as_view()),
    path('work-orders/export/', work_order_views.WorkOrderExportView.as_view()),
    path('work-orders/candidate-systems/', work_order_views.WorkOrderCandidateSystemsView.as_view()),
    path('work-orders/candidate-users/', work_order_views.WorkOrderCandidateUsersView.as_view()),
    path('work-orders/<int:pk>/', work_order_views.WorkOrderDetailView.as_view()),
    path('work-orders/<int:pk>/dispatch/', work_order_views.WorkOrderDispatchView.as_view()),
    path('work-orders/<int:pk>/accept/', work_order_views.WorkOrderAcceptView.as_view()),
    path('work-orders/<int:pk>/start/', work_order_views.WorkOrderStartView.as_view()),
    path('work-orders/<int:pk>/submit-review/', work_order_views.WorkOrderSubmitReviewView.as_view()),
    path('work-orders/<int:pk>/review-pass/', work_order_views.WorkOrderReviewPassView.as_view()),
    path('work-orders/<int:pk>/review-return/', work_order_views.WorkOrderReviewReturnView.as_view()),
    path('work-orders/<int:pk>/close/', work_order_views.WorkOrderCloseView.as_view()),
    path('work-orders/<int:pk>/cancel/', work_order_views.WorkOrderCancelView.as_view()),
    path('work-orders/<int:pk>/handling-records/', work_order_views.WorkOrderHandlingRecordView.as_view()),
    path('work-orders/<int:pk>/handling-records/<int:rid>/', work_order_views.WorkOrderHandlingRecordDetailView.as_view()),
    path('work-orders/<int:pk>/handling-records/<int:rid>/attachments/', work_order_views.WorkOrderHandlingAttachmentView.as_view()),
    path('work-orders/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/download/', work_order_views.WorkOrderHandlingAttachmentDownloadView.as_view()),
    path('work-orders/<int:pk>/handling-records/<int:rid>/attachments/<int:aid>/', work_order_views.WorkOrderHandlingAttachmentDetailView.as_view()),
    # 来源与转单
    path('faults/<int:pk>/work-orders/', work_order_views.FaultWorkOrdersView.as_view()),
    path('faults/<int:pk>/create-work-order/', work_order_views.FaultCreateWorkOrderView.as_view()),
    path('ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-fault/', work_order_views.LedgerItemConvertToFaultView.as_view()),
    path('ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-work-order/', work_order_views.LedgerItemConvertToWorkOrderView.as_view()),
    # 按系统查询工单（目标/受影响）
    path('systems/<int:pk>/work-orders/', work_order_views.SystemWorkOrdersView.as_view()),
]
