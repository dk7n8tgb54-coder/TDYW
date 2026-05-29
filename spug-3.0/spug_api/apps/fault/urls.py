# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from apps.fault.views import (
    FaultRecordView, FaultPartView
)

urlpatterns = [
    path('faultrecord/', FaultRecordView.as_view()),
    path('faultpart/', FaultPartView.as_view()),
]
