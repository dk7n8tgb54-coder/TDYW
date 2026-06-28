# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.device.views import (
    DeviceResumeView, DeviceEventView, DeviceResumeExportView,
    DeviceEvidencePackageView,
)
from apps.device.exporters import DeviceListExportView

urlpatterns = [
    re_path(r'device-resume/export/$', DeviceListExportView.as_view()),
    re_path(r'device-resume/$', DeviceResumeView.as_view()),
    re_path(r'device-event/$', DeviceEventView.as_view()),
    re_path(r'device-resume/export/pdf/$', DeviceResumeExportView.as_view()),
    re_path(r'device-resume/evidence/package/$', DeviceEvidencePackageView.as_view()),
]
