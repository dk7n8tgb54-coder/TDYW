# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.interference.views import *
from apps.interference.exporters import (
    InterferenceExportView,
    InterferenceBridgeExportView,
    InterferenceAirExportView,
)
from apps.interference.business_views import (
    BridgeInterferenceView,
    AirInterferenceView,
    BridgeAttachmentView,
    AirAttachmentView,
    InterferenceSummaryView,
)
from apps.interference.import_views import (
    BridgeImportTemplateView,
    BridgeImportValidateView,
    BridgeImportCommitView,
    BridgeImportErrorReportView,
    AirImportTemplateView,
    AirImportValidateView,
    AirImportCommitView,
    AirImportErrorReportView,
)

urlpatterns = [
    # ==== 双业务类型接口（地面无线电通信异常/干扰、空中干扰） ====
    # 注意：必须注册在历史兼容的 (?P<pk>[\w-]+)/attachments/ 通配路由之前
    re_path(r'^bridge/$', BridgeInterferenceView.as_view()),
    re_path(r'^bridge/export/$', InterferenceBridgeExportView.as_view()),
    re_path(r'^bridge/import/template/$', BridgeImportTemplateView.as_view()),
    re_path(r'^bridge/import/validate/$', BridgeImportValidateView.as_view()),
    re_path(r'^bridge/import/commit/$', BridgeImportCommitView.as_view()),
    re_path(r'^bridge/import/error-report/$', BridgeImportErrorReportView.as_view()),
    re_path(r'^bridge/(?P<pk>[\w-]+)/attachments/$', BridgeAttachmentView.as_view()),
    re_path(r'^air/$', AirInterferenceView.as_view()),
    re_path(r'^air/export/$', InterferenceAirExportView.as_view()),
    re_path(r'^air/import/template/$', AirImportTemplateView.as_view()),
    re_path(r'^air/import/validate/$', AirImportValidateView.as_view()),
    re_path(r'^air/import/commit/$', AirImportCommitView.as_view()),
    re_path(r'^air/import/error-report/$', AirImportErrorReportView.as_view()),
    re_path(r'^air/(?P<pk>[\w-]+)/attachments/$', AirAttachmentView.as_view()),
    # 统一汇总统计（仅两类记录共同摘要）
    re_path(r'^summary/$', InterferenceSummaryView.as_view()),

    # ==== 历史兼容：旧 Interference 接口原样保留，服务于历史数据 ====
    # （统计能力已由 数据分析-干扰分析 /api/data-analysis/interference/ 取代）
    re_path(r'^$', InterferenceView.as_view()),
    re_path(r'export/$', InterferenceExportView.as_view()),
    re_path(r'evidence/package/$', InterferenceEvidencePackageView.as_view()),

    # 附件接口
    re_path(r'attachments/$', AttachmentDeleteView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/download/$', AttachmentDownloadView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/preview-url/$', AttachmentPreviewUrlView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/preview-file/$', AttachmentPreviewFileView.as_view()),
    # 匹配数字 ID（已保存记录）和临时 UUID（新建阶段）
    re_path(r'(?P<pk>[\w-]+)/attachments/$', AttachmentListView.as_view()),
]
