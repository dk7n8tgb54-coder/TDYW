# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.regulation.views import (
    CategoryTreeView,
    CategoryListCreateView,
    CategoryDetailView,
    RegulationListView,
    RegulationCreateView,
    RegulationDetailView,
    RegulationRetireView,
    RegulationAttachmentListView,
    RegulationAttachmentUploadView,
    RegulationAttachmentDownloadView,
    RegulationAttachmentDetailView,
    RegulationAttachmentPreviewUrlView,
    RegulationAttachmentPreviewFileView,
)

urlpatterns = [
    # 分类树
    re_path(r'categories/tree/$', CategoryTreeView.as_view()),
    re_path(r'categories/$', CategoryListCreateView.as_view()),
    re_path(r'categories/(?P<pk>\d+)/$', CategoryDetailView.as_view()),

    # 规章台账
    re_path(r'^$', RegulationListView.as_view()),
    re_path(r'create/$', RegulationCreateView.as_view()),
    re_path(r'(?P<pk>\d+)/$', RegulationDetailView.as_view()),
    re_path(r'(?P<pk>\d+)/retire/$', RegulationRetireView.as_view()),

    # 附件管理（独立附件表）
    re_path(r'(?P<pk>\d+)/attachments/$', RegulationAttachmentListView.as_view()),
    re_path(r'(?P<pk>\d+)/attachments/upload/$', RegulationAttachmentUploadView.as_view()),
    re_path(r'(?P<pk>\d+)/attachments/(?P<att_id>\d+)/download/$', RegulationAttachmentDownloadView.as_view()),
    re_path(r'(?P<pk>\d+)/attachments/(?P<att_id>\d+)/preview-url/$', RegulationAttachmentPreviewUrlView.as_view()),
    re_path(r'(?P<pk>\d+)/attachments/(?P<att_id>\d+)/preview-file/$', RegulationAttachmentPreviewFileView.as_view()),
    re_path(r'(?P<pk>\d+)/attachments/(?P<att_id>\d+)/$', RegulationAttachmentDetailView.as_view()),
]
