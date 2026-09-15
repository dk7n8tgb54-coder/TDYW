# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
from django.urls import path
from apps.alert.views import (
    AlertListView,
    AlertMarkReadView,
    AlertResolveView,
    DataQualityCheckView,
    RunMetricView,
    RunMetricSummaryView,
)

urlpatterns = [
    path('', AlertListView.as_view()),
    path('mark-read/', AlertMarkReadView.as_view()),
    path('<int:pk>/resolve/', AlertResolveView.as_view()),
    path('data-quality/', DataQualityCheckView.as_view()),
    path('run-metrics/summary/', RunMetricSummaryView.as_view()),
    path('run-metrics/', RunMetricView.as_view()),
]
