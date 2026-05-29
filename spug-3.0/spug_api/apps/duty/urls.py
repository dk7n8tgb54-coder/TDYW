# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from apps.duty.views import (
    DutyRecordView, DutyImportView, export_pdf
)

urlpatterns = [
    path('duty/', DutyRecordView.as_view()),
    path('duty/import_records/', DutyImportView.as_view()),
    path('duty/export/pdf/', export_pdf),
]
