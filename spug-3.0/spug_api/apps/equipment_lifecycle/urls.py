# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期 URL 装配（步骤 3.5 收口；2026-10-11 合并改造）。

- API 前缀 /equipment-lifecycle/（由项目根 urls.py 按发布开关挂载）；
- 所有持健康重算锁（health_recalc_lock）或编号锁（operation_record_no）的
  动作视图以 non_atomic_requests 装配：ATOMIC_REQUESTS 下请求级事务会延后到
  视图返回后才真正提交，若锁在视图内先释放，并发重算会读到未提交数据、
  以陈旧结果覆盖状态；关闭请求级事务后，视图内 transaction.atomic 即为
  真实事务，"锁 → 事务提交 → 释放锁"顺序成立（步骤 3.5 修复 GET_LOCK 提交窗口）。

2026-10-11 合并改造：
- 原"故障处置"（/faults/*）与"运行记录"（/runtime-records/*）合并为统一
  模块"运行处置记录"（/records/*，SystemOperationRecord/SystemOperationProgress），
  旧路由整体删除，不保留兼容层；
- 原"系统履历"（/system-events/*、/system-event-groups/*、
  /systems/<pk>/system-events/）整体下线，模型/写入/查询一并退役。
"""
from django.db import transaction
from django.urls import path

from apps.equipment_lifecycle import (
    config_attachment_views, config_views,
    excel_ledger_views, excel_template_views, form_ledger_views,
    form_template_views, ledger_views,
    operation_action_views, operation_attachment_views,
    operation_ledger_convert, operation_progress_views, operation_views,
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
    path('systems/<int:pk>/upgrade-records/', SystemUpgradeRecordsView.as_view()),
    # ==================== 运行处置记录（2026-10-11 合并改造） ====================
    # 统一主表承载 一般记录/异常事件/设备故障 三类记录；创建（编号锁，故障另叠
    # 健康锁）与 认定故障/恢复结案/撤销/编辑（健康锁）动作以 non_atomic 装配
    # （锁 → 事务提交 → 释放锁 顺序成立）。
    path('records/', _na(operation_views.RecordView.as_view())),
    path('records/export/', operation_views.RecordExportView.as_view()),
    path('records/candidate-systems/', operation_views.RecordCandidateSystemsView.as_view()),
    path('records/todo/', operation_views.RecordTodoView.as_view()),
    path('records/statistics/', operation_views.RecordStatisticsView.as_view()),
    path('records/<int:pk>/', _na(operation_views.RecordDetailView.as_view())),
    # 主记录附件
    path('records/<int:pk>/attachments/', operation_attachment_views.RecordAttachmentView.as_view()),
    path('records/<int:pk>/attachments/<int:aid>/download/', operation_attachment_views.RecordAttachmentDownloadView.as_view()),
    path('records/<int:pk>/attachments/<int:aid>/', operation_attachment_views.RecordAttachmentDetailView.as_view()),
    # 统一进展（不持健康锁：追加/更正进展不改健康状态，普通请求级事务即可）
    path('records/<int:pk>/progress/', operation_progress_views.RecordProgressView.as_view()),
    path('records/<int:pk>/progress/<int:rid>/', operation_progress_views.RecordProgressDetailView.as_view()),
    # 状态动作（异常事件：完成跟进/认定设备故障；设备故障：恢复结案/撤销/原因分析）
    path('records/<int:pk>/complete/', _na(operation_action_views.RecordCompleteView.as_view())),
    path('records/<int:pk>/identify-fault/', _na(operation_action_views.RecordIdentifyFaultView.as_view())),
    path('records/<int:pk>/recover/', _na(operation_action_views.RecordRecoverView.as_view())),
    path('records/<int:pk>/cancel/', _na(operation_action_views.RecordCancelView.as_view())),
    path('records/<int:pk>/reason-analysis/', operation_action_views.RecordReasonAnalysisView.as_view()),
    # 按系统查询统一记录（系统档案详情页签）
    path('systems/<int:pk>/records/', operation_views.SystemRecordListView.as_view()),
    # ==================== 运维台账 ====================
    # Excel 上传版维护台账模板（固定版式 .xlsx 草稿 + 不可变发布版本；
    # 台账创建走 excel-ledgers）
    path('excel-templates/available/', excel_template_views.ExcelTemplateAvailableView.as_view()),
    path('excel-templates/sample/', excel_template_views.ExcelTemplateSampleView.as_view()),
    path('excel-templates/create-options/', excel_template_views.ExcelTemplateCreateOptionsView.as_view()),
    path('excel-templates/', excel_template_views.ExcelTemplateView.as_view()),
    path('excel-templates/<int:pk>/', excel_template_views.ExcelTemplateDetailView.as_view()),
    # 停用（逻辑停用，幂等）/ 重新启用（停用逆操作，幂等）；
    # DELETE <pk>/ 为物理删除（后端复查引用）
    path('excel-templates/<int:pk>/deactivate/', excel_template_views.ExcelTemplateDeactivateView.as_view()),
    path('excel-templates/<int:pk>/activate/', excel_template_views.ExcelTemplateActivateView.as_view()),
    path('excel-templates/<int:pk>/draft-file/', excel_template_views.ExcelTemplateDraftFileView.as_view()),
    path('excel-templates/<int:pk>/bindings/', excel_template_views.ExcelTemplateBindingsView.as_view()),
    path('excel-templates/<int:pk>/generation-config/', excel_template_views.ExcelTemplateGenerationConfigView.as_view()),
    path('excel-templates/<int:pk>/pdf-params/', excel_template_views.ExcelTemplatePdfParamsView.as_view()),
    path('excel-templates/<int:pk>/publish/', excel_template_views.ExcelTemplatePublishView.as_view()),
    path('excel-templates/<int:pk>/versions/', excel_template_views.ExcelTemplateVersionListView.as_view()),
    path('excel-templates/<int:pk>/versions/<int:version_no>/', excel_template_views.ExcelTemplateVersionDetailView.as_view()),
    # 历史版本只读能力（2026-10-21）：版本自身打印预览 / 源文件下载 /
    # 复制为新草稿（仅替换当前草稿，不改历史版本、不自动发布）
    path('excel-templates/<int:pk>/versions/<int:version_no>/preview/pdf/',
         excel_template_views.ExcelTemplateVersionPreviewView.as_view()),
    path('excel-templates/<int:pk>/versions/<int:version_no>/source/',
         excel_template_views.ExcelTemplateVersionSourceView.as_view()),
    path('excel-templates/<int:pk>/versions/<int:version_no>/copy-to-draft/',
         excel_template_views.ExcelTemplateVersionCopyView.as_view()),
    path('excel-templates/<int:pk>/preview/pdf/', excel_template_views.ExcelTemplatePdfPreviewView.as_view()),
    # Excel 路线维护台账（created_from=excel_template；作废/删除沿用既有 ledgers 端点）
    path('excel-ledgers/', excel_ledger_views.ExcelLedgerView.as_view()),
    path('excel-ledgers/<int:pk>/', excel_ledger_views.ExcelLedgerDetailView.as_view()),
    path('excel-ledgers/<int:pk>/complete/', excel_ledger_views.ExcelLedgerCompleteView.as_view()),
    path('excel-ledgers/<int:pk>/correct/', excel_ledger_views.ExcelLedgerCorrectView.as_view()),
    path('excel-ledgers/<int:pk>/export/check/', excel_ledger_views.ExcelLedgerExportCheckView.as_view()),
    path('excel-ledgers/<int:pk>/export/excel/', excel_ledger_views.ExcelLedgerExportView.as_view(), {'fmt': 'excel'}),
    path('excel-ledgers/<int:pk>/export/pdf/', excel_ledger_views.ExcelLedgerExportView.as_view(), {'fmt': 'pdf'}),
    # 打印预览（详情"打印预览"页签/翻阅真实打印预览，2026-10-21）：与导出 PDF
    # 同一生成服务与参数，inline 下发 + 内容寻址缓存
    path('excel-ledgers/<int:pk>/print-preview/', excel_ledger_views.ExcelLedgerPrintPreviewView.as_view()),
    # ==================== 数字表单台账模板（2026-10-21，与 Excel 路线平行） ====================
    # 结构化表单模板：草稿表单 JSON 编辑 + 发布不可变版本；台账创建走 form-ledgers；
    # 权限域与 Excel 模板一致（ledger_template.*，available 为台账域）
    path('form-templates/available/', form_template_views.FormTemplateAvailableView.as_view()),
    path('form-templates/sample/', form_template_views.FormTemplateSampleView.as_view()),
    path('form-templates/create-options/', form_template_views.FormTemplateCreateOptionsView.as_view()),
    path('form-templates/', form_template_views.FormTemplateView.as_view()),
    path('form-templates/<int:pk>/', form_template_views.FormTemplateDetailView.as_view()),
    path('form-templates/<int:pk>/deactivate/', form_template_views.FormTemplateDeactivateView.as_view()),
    path('form-templates/<int:pk>/activate/', form_template_views.FormTemplateActivateView.as_view()),
    path('form-templates/<int:pk>/generation-config/', form_template_views.FormTemplateGenerationConfigView.as_view()),
    path('form-templates/<int:pk>/publish/', form_template_views.FormTemplatePublishView.as_view()),
    # 发布检查（2026-10-23 P2）：无状态预检提示（errors/warnings + anchor），
    # 不落库不是放行凭证；可携带未保存 form 解决"非法草稿无法先保存"矛盾
    path('form-templates/<int:pk>/publish-check/', form_template_views.FormTemplatePublishCheckView.as_view()),
    path('form-templates/<int:pk>/versions/', form_template_views.FormTemplateVersionListView.as_view()),
    path('form-templates/<int:pk>/versions/<int:version_no>/', form_template_views.FormTemplateVersionDetailView.as_view()),
    # 模板样张 PDF 预览（2026-10-22）：当前草稿结构的空白样例（POST 触发生成）
    path('form-templates/<int:pk>/preview/pdf/', form_template_views.FormTemplatePdfPreviewView.as_view()),
    # 数字表单路线台账（created_from=form_template；作废/删除沿用既有 ledgers 端点）
    path('form-ledgers/', form_ledger_views.FormLedgerView.as_view()),
    path('form-ledgers/<int:pk>/', form_ledger_views.FormLedgerDetailView.as_view()),
    path('form-ledgers/<int:pk>/complete/', form_ledger_views.FormLedgerCompleteView.as_view()),
    # 数字表单台账 PDF 预览/导出（2026-10-22）：同一生成函数（预览=下载），
    # 预览 inline 下发 + 真实反馈头；导出附件下发
    path('form-ledgers/<int:pk>/preview/pdf/', form_ledger_views.FormLedgerPdfPreviewView.as_view()),
    path('form-ledgers/<int:pk>/export/pdf/', form_ledger_views.FormLedgerPdfExportView.as_view()),
    # 台账
    path('ledgers/', ledger_views.LedgerView.as_view()),
    path('ledgers/abnormal-items/', ledger_views.LedgerAbnormalItemsView.as_view()),
    path('ledgers/export/', ledger_views.LedgerExportView.as_view()),
    # 系统选项（"按系统查看"筛选等；原批量创建手工壳 POST 已下线）
    path('ledgers/batch-create/', ledger_views.LedgerBatchCreateView.as_view()),
    # 本期应填台账生成（2026-10-14）：GET 预览 / POST 确认生成（按 Excel 模板）
    path('ledgers/period-generate/', ledger_views.LedgerPeriodGenerateView.as_view()),
    # 明确补建（2026-10-16）：作废占用的本期槽位重新生成（作废台账保留）
    path('ledgers/period-generate/rebuild/', ledger_views.LedgerPeriodGenerateRebuildView.as_view()),
    # 本期工作概览（2026-10-14）：本周/本月或本航季应填情况真实统计
    path('ledgers/period-overview/', ledger_views.LedgerPeriodOverviewView.as_view()),
    # 按维护类型+周期分组的台账列表（组内含各系统台账与填写状态）
    path('ledgers/period-groups/', ledger_views.LedgerPeriodGroupsView.as_view()),
    # 按模板身份分组的台账统计 + 组内台账分页列表（"按模板查看"，2026-10-11；
    # group_key=模板主键，manual=无模板/临时补录组）
    path('ledgers/template-groups/', ledger_views.LedgerTemplateGroupsView.as_view()),
    path('ledgers/template-groups/<str:group_key>/ledgers/',
         ledger_views.LedgerTemplateGroupLedgersView.as_view()),
    # 模板组翻阅清单（"翻阅台账"，2026-10-18）：组内台账有序清单，前端逐张翻阅
    path('ledgers/template-groups/<str:group_key>/browse/',
         ledger_views.LedgerTemplateGroupBrowseView.as_view()),
    # 模板组内批量 PDF 导出（2026-10-11）：GET 确认数据 / POST 生成合并 PDF
    path('ledgers/template-groups/<str:group_key>/export-pdf/',
         excel_ledger_views.LedgerTemplateGroupPdfExportView.as_view()),
    # 台账列表"批量导出 PDF"（2026-10-21，替换原导出明细 CSV 入口）：
    # GET 模板候选清单 / POST 多模板导出（每模板一份 PDF，多模板打包 ZIP）
    path('ledgers/export-pdf/', excel_ledger_views.LedgerMultiTemplatePdfExportView.as_view()),
    path('ledgers/<int:pk>/', ledger_views.LedgerDetailView.as_view()),
    # 完成填写（流程终点：草稿 → 已完成；2026-10-16 替代旧 submit/return/review）
    path('ledgers/<int:pk>/complete/', ledger_views.LedgerCompleteView.as_view()),
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
    # 台账异常明细转统一记录（设备故障；视图自原 fault_views 迁入
    # operation_ledger_convert，转换目标改为统一主表，不再创建第二张单）
    path('ledgers/<int:ledger_pk>/items/<int:item_pk>/convert-to-fault/', _na(operation_ledger_convert.LedgerItemConvertToFaultView.as_view())),
    # ==================== 系统配置（设备管理 → 系统配置维护入口） ====================
    # 2026-10-19 起：写操作集中在「设备管理 → 系统配置」独立维护页；「系统详情 →
    # 配置」页签只读展示并跳转维护入口。配置值只经"初始建档"或"创建草稿 →
    # 应用生效"流程写入；创建/回退持编号锁（non_atomic 装配），应用/验证/取消/
    # 建档走请求级事务+行锁。
    path('config/system-options/', config_views.ConfigSystemOptionsView.as_view()),
    path('systems/<int:pk>/config/', config_views.SystemConfigView.as_view()),
    path('systems/<int:pk>/config/baseline/', config_views.SystemConfigBaselineView.as_view()),
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
    # ==================== 已整体下线（2026-10-11 合并改造） ====================
    # - 系统履历：/system-events/*、/system-event-groups/*、
    #   /systems/<pk>/system-events/ 全部端点与 SystemEvent 模型/写入已删除，
    #   系统档案直接查询统一记录等业务表；
    # - 旧 /faults/* 与 /runtime-records/* 路由随合并删除，不保留兼容层。
]
