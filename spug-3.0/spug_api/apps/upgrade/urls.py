# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块 URL 配置

新 RESTful 接口 + 兼容旧接口

注意：原 templates/ 与 checklists/ 路由已合并为 plans/。
"""
from django.urls import path

# === 新接口 - 升级表单 ===
from .views.record.list import RecordListView
from .views.record.detail import RecordDetailView
from .views.record.create import RecordCreateView
from .views.record.update import RecordUpdateView
from .views.record.delete import RecordDeleteView

# === 新接口 - 辅助 ===
from .views.filter_options import FilterOptionsView
from .views.statistics import StatisticsView
from .views.upload import (
    AttachmentUploadView, AttachmentListView,
    AttachmentDownloadView, AttachmentDeleteView,
)
from .views.next_no import NextUpgradeNoView

# === 新接口 - 升级方案（合并原模板+步骤清单）===
from .views.plan import (
    PlanListView, PlanDetailView,
    PlanCreateView, PlanUpdateView, PlanDeleteView,
    PlanApplyView, PlanReorderStepsView,
)

# === 新接口 - 升级记录步骤 ===
from .views.step import (
    RecordStepListView, RecordStepAddView,
    RecordStepUpdateView, RecordStepDeleteView,
    RecordStepBatchUpdateView, RecordStepClearView,
)

# === 新接口 - 升级状态日志 ===
from .views.status_log import StatusLogListView, StatusLogDeleteView

# === 兼容旧接口 ===
from .views.legacy import LegacyUpgradeView

# === 导出 ===
from .exporters import RecordExportView

urlpatterns = [
    # === 升级表单 ===
    path('records/export/', RecordExportView.as_view()),            # GET 导出 Excel
    path('records/', RecordListView.as_view()),                     # GET 列表（分页）
    path('records/<int:pk>/', RecordDetailView.as_view()),          # GET 详情
    path('records/create/', RecordCreateView.as_view()),            # POST 创建
    path('records/<int:pk>/update/', RecordUpdateView.as_view()),   # PUT 更新
    path('records/<int:pk>/delete/', RecordDeleteView.as_view()),   # DELETE 删除

    # === 辅助接口 ===
    path('filter-options/', FilterOptionsView.as_view()),          # GET 筛选选项
    path('statistics/', StatisticsView.as_view()),                  # GET 统计数据
    path('upload/', AttachmentUploadView.as_view()),                # POST 附件上传（旧版，仅返回 URL）
    path('next-no/', NextUpgradeNoView.as_view()),                 # GET 获取下一个升级单号

    # === 附件接口（新版，写表 + 哈希 + 软删除）===
    path('records/<int:record_id>/attachments/', AttachmentListView.as_view()),                    # GET 列表 / POST 上传
    path('attachments/<int:pk>/download/', AttachmentDownloadView.as_view()),                      # GET 下载
    path('attachments/', AttachmentDeleteView.as_view()),                                          # DELETE 删除（?id=）

    # === 升级方案（原模板 + 步骤清单合并）===
    path('plans/', PlanListView.as_view()),                              # GET 方案列表
    path('plans/<int:pk>/', PlanDetailView.as_view()),                   # GET 方案详情（含预设步骤）
    path('plans/create/', PlanCreateView.as_view()),                     # POST 创建方案
    path('plans/<int:pk>/update/', PlanUpdateView.as_view()),            # PUT 更新方案（含步骤整体替换）
    path('plans/<int:pk>/delete/', PlanDeleteView.as_view()),            # DELETE 删除方案
    path('plans/<int:pk>/apply/', PlanApplyView.as_view()),              # POST 应用方案步骤到升级记录
    path('plans/<int:pk>/reorder/', PlanReorderStepsView.as_view()),     # PUT 重排预设步骤

    # === 升级记录步骤 ===
    path('records/<int:record_id>/steps/', RecordStepListView.as_view()),                 # GET 步骤列表+统计
    path('records/<int:record_id>/steps/add/', RecordStepAddView.as_view()),              # POST 手动添加步骤
    path('record-steps/<int:pk>/update/', RecordStepUpdateView.as_view()),                # PUT 更新步骤状态
    path('record-steps/<int:pk>/delete/', RecordStepDeleteView.as_view()),                # DELETE 删除步骤
    path('records/<int:record_id>/steps/batch/', RecordStepBatchUpdateView.as_view()),    # PUT 批量更新
    path('records/<int:record_id>/steps/clear/', RecordStepClearView.as_view()),          # DELETE 清空步骤

    # === 升级状态日志（时间线）===
    path('records/<int:record_id>/status-logs/', StatusLogListView.as_view()),            # GET 列表 / POST 记录 / GET ?action=options 动作选项
    path('status-logs/<int:pk>/delete/', StatusLogDeleteView.as_view()),                  # DELETE 删除日志

    # === 兼容旧接口（前端迁移完成后移除）===
    path('upgrade/', LegacyUpgradeView.as_view()),
]
