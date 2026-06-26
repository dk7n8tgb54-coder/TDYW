# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块 URL 配置

新 RESTful 接口 + 兼容旧接口
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
from .views.upload import AttachmentUploadView
from .views.next_no import NextUpgradeNoView

# === 新接口 - 升级模板 ===
from .views.template import (
    TemplateListView, TemplateCreateView,
    TemplateUpdateView, TemplateDeleteView,
)

# === 新接口 - 步骤清单 ===
from .views.checklist import (
    ChecklistListView, ChecklistDetailView,
    ChecklistCreateView, ChecklistUpdateView, ChecklistDeleteView,
    ChecklistStepAddView, ChecklistStepUpdateView, ChecklistStepDeleteView,
    ChecklistApplyView, ChecklistReorderStepsView,
)

# === 新接口 - 升级记录步骤 ===
from .views.step import (
    RecordStepListView, RecordStepAddView,
    RecordStepUpdateView, RecordStepDeleteView,
    RecordStepBatchUpdateView, RecordStepClearView,
)

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
    path('upload/', AttachmentUploadView.as_view()),                # POST 附件上传
    path('next-no/', NextUpgradeNoView.as_view()),                 # GET 获取下一个升级单号

    # === 升级模板 ===
    path('templates/', TemplateListView.as_view()),                # GET 模板列表
    path('templates/create/', TemplateCreateView.as_view()),       # POST 创建模板
    path('templates/<int:pk>/update/', TemplateUpdateView.as_view()),  # PUT 更新模板
    path('templates/<int:pk>/delete/', TemplateDeleteView.as_view()),  # DELETE 删除模板

    # === 步骤清单 ===
    path('checklists/', ChecklistListView.as_view()),                              # GET 清单列表
    path('checklists/<int:pk>/', ChecklistDetailView.as_view()),                  # GET 清单详情（含步骤）
    path('checklists/create/', ChecklistCreateView.as_view()),                    # POST 创建清单
    path('checklists/<int:pk>/update/', ChecklistUpdateView.as_view()),           # PUT 更新清单
    path('checklists/<int:pk>/delete/', ChecklistDeleteView.as_view()),           # DELETE 删除清单
    path('checklists/<int:pk>/steps/add/', ChecklistStepAddView.as_view()),       # POST 添加步骤
    path('checklists/steps/<int:pk>/update/', ChecklistStepUpdateView.as_view()), # PUT 更新步骤
    path('checklists/steps/<int:pk>/delete/', ChecklistStepDeleteView.as_view()), # DELETE 删除步骤
    path('checklists/<int:pk>/apply/', ChecklistApplyView.as_view()),             # POST 应用清单到升级表单
    path('checklists/<int:pk>/reorder/', ChecklistReorderStepsView.as_view()),    # PUT 重排步骤顺序

    # === 升级记录步骤 ===
    path('records/<int:record_id>/steps/', RecordStepListView.as_view()),                 # GET 步骤列表+统计
    path('records/<int:record_id>/steps/add/', RecordStepAddView.as_view()),              # POST 手动添加步骤
    path('record-steps/<int:pk>/update/', RecordStepUpdateView.as_view()),                # PUT 更新步骤状态
    path('record-steps/<int:pk>/delete/', RecordStepDeleteView.as_view()),                # DELETE 删除步骤
    path('records/<int:record_id>/steps/batch/', RecordStepBatchUpdateView.as_view()),    # PUT 批量更新
    path('records/<int:record_id>/steps/clear/', RecordStepClearView.as_view()),          # DELETE 清空步骤

    # === 兼容旧接口（前端迁移完成后移除）===
    path('upgrade/', LegacyUpgradeView.as_view()),
]
