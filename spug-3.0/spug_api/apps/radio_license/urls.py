# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.radio_license.views import *

urlpatterns = [
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
