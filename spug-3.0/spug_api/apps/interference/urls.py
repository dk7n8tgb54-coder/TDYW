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
]
