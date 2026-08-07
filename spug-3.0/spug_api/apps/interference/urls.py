# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.interference.views import *
from apps.interference.exporters import InterferenceExportView

urlpatterns = [
    re_path(r'^$', InterferenceView.as_view()),
    re_path(r'export/$', InterferenceExportView.as_view()),
    re_path(r'statistics/$', InterferenceStatisticsView.as_view()),
    re_path(r'evidence/package/$', InterferenceEvidencePackageView.as_view()),

    # 附件接口
    re_path(r'attachments/$', AttachmentDeleteView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/download/$', AttachmentDownloadView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/preview-url/$', AttachmentPreviewUrlView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/preview-file/$', AttachmentPreviewFileView.as_view()),
    # 匹配数字 ID（已保存记录）和临时 UUID（新建阶段）
    re_path(r'(?P<pk>[\w-]+)/attachments/$', AttachmentListView.as_view()),
]
