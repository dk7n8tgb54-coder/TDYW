from django.urls import re_path
from apps.logs.views import AuditLogView, AuditLogExportView, AuditLogTargetTypesView, AuditLogActionsView

urlpatterns = [
    re_path(r'^audit/$', AuditLogView.as_view()),
    re_path(r'^audit/export/$', AuditLogExportView.as_view()),
    re_path(r'^audit/target_types/$', AuditLogTargetTypesView.as_view()),
    re_path(r'^audit/actions/$', AuditLogActionsView.as_view()),
]
