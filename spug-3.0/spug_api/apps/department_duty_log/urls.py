# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""部门值班日志 - URL 路由"""
from django.urls import path

from .views import (
    DepartmentDutyLogListCreateView,
    DepartmentDutyLogDetailView,
    DepartmentDutyLogSignView,
    DepartmentDutyLogVoidView,
    DepartmentDutyLogCorrectionView,
    DepartmentDutyLogSignatureImageView,
    DepartmentDutyLogOptionsView,
)

urlpatterns = [
    path('records/', DepartmentDutyLogListCreateView.as_view()),
    path('records/<int:pk>/', DepartmentDutyLogDetailView.as_view()),
    path('records/<int:pk>/sign/', DepartmentDutyLogSignView.as_view()),
    path('records/<int:pk>/void/', DepartmentDutyLogVoidView.as_view()),
    path('records/<int:pk>/corrections/', DepartmentDutyLogCorrectionView.as_view()),
    path('records/<int:pk>/signature-image/', DepartmentDutyLogSignatureImageView.as_view()),
    path('options/', DepartmentDutyLogOptionsView.as_view()),
]
