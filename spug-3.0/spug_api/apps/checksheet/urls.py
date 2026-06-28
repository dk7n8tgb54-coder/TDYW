# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path
from . import views

urlpatterns = [
    path('template/', views.TemplateView.as_view()),
    path('template/projects/', views.ProjectListView.as_view()),
    path('template/<int:pk>/', views.TemplateDetailView.as_view()),
    path('record/', views.RecordListView.as_view()),
    path('export/pdf/', views.export_pdf),
    path('submission/', views.SubmissionView.as_view()),
    path('evidence/package/', views.EvidencePackageView.as_view()),
]
