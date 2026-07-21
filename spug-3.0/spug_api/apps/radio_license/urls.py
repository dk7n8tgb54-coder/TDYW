# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.radio_license.views import *
from apps.radio_license.approval_views import *  # 批复相关视图（从 views.py 拆分）

urlpatterns = [
    # ===== 台站频率批复（固定路径在前，数字主键在后）=====
    re_path(r'^approvals/$', StationFrequencyApprovalView.as_view()),
    re_path(r'^approvals/responsible-users/$', ApprovalResponsibleUserListView.as_view()),
    re_path(r'^approvals/reminders/popup/$', ApprovalReminderPopupView.as_view()),
    re_path(r'^approvals/reminders/ack/$', ApprovalReminderAckView.as_view()),
    re_path(r'^approvals/badge/$', ApprovalBadgeView.as_view()),

    re_path(r'^approvals/attachments/(?P<pk>\d+)/download/$', ApprovalAttachmentDownloadView.as_view()),
    re_path(r'^approvals/attachments/(?P<pk>\d+)/preview-url/$', ApprovalAttachmentPreviewUrlView.as_view()),
    re_path(r'^approvals/attachments/(?P<pk>\d+)/preview-file/$', ApprovalAttachmentPreviewFileView.as_view()),
    re_path(r'^approvals/attachments/$', ApprovalAttachmentDeleteView.as_view()),

    re_path(r'^approvals/(?P<pk>\d+)/attachments/$', ApprovalAttachmentListView.as_view()),
    re_path(r'^approvals/(?P<pk>\d+)/$', StationFrequencyApprovalDetailView.as_view()),

    # ===== 无线电台执照 =====
    re_path(r'^$', RadioLicenseView.as_view()),
    re_path(r'(?P<pk>\d+)/$', RadioLicenseDetailView.as_view()),
    re_path(r'(?P<pk>\d+)/attachments/$', AttachmentListView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/download/$', AttachmentDownloadView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/preview-url/$', AttachmentPreviewUrlView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/preview-file/$', AttachmentPreviewFileView.as_view()),
    re_path(r'attachments/$', AttachmentDeleteView.as_view()),
    re_path(r'reminders/popup/$', ReminderPopupView.as_view()),
    re_path(r'reminders/ack/$', ReminderAckView.as_view()),
    re_path(r'badge/$', RadioLicenseBadgeView.as_view()),
    re_path(r'responsible-users/$', ResponsibleUserListView.as_view()),
    re_path(r'evidence/package/$', RadioLicenseEvidencePackageView.as_view()),
]
