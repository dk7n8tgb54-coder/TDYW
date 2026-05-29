# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.conf.urls import url

from apps.device.views import DeviceResumeView, DeviceEventView, DeviceResumeExportView

urlpatterns = [
    url(r'device-resume/$', DeviceResumeView.as_view()),
    url(r'device-event/$', DeviceEventView.as_view()),
    url(r'device-resume/export/pdf/$', DeviceResumeExportView.as_view()),
]
