# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.conf.urls import url

from apps.interference.views import *
from apps.interference.exporters import InterferenceExportView

urlpatterns = [
    url(r'^$', InterferenceView.as_view()),
    url(r'export/$', InterferenceExportView.as_view()),
    url(r'statistics/$', InterferenceStatisticsView.as_view()),
]
