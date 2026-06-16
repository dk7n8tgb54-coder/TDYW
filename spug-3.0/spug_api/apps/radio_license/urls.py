# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.conf.urls import url

from apps.radio_license.views import *

urlpatterns = [
    url(r'^$', RadioLicenseView.as_view()),
    url(r'(?P<pk>\d+)/$', RadioLicenseDetailView.as_view()),
    url(r'(?P<pk>\d+)/attachments/$', AttachmentListView.as_view()),
    url(r'attachments/(?P<pk>\d+)/download/$', AttachmentDownloadView.as_view()),
    url(r'attachments/$', AttachmentDeleteView.as_view()),
    url(r'reminders/$', ReminderListView.as_view()),
    url(r'reminders/handle/$', ReminderHandleView.as_view()),
]
