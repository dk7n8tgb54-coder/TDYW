# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
from django.urls import path
from apps.alert.views import (
    AlertListView,
    AlertMarkReadView,
    AlertResolveView,
    DataQualityCheckView,
)

urlpatterns = [
    path('', AlertListView.as_view()),
    path('mark-read/', AlertMarkReadView.as_view()),
    path('<int:pk>/resolve/', AlertResolveView.as_view()),
    path('data-quality/', DataQualityCheckView.as_view()),
]
