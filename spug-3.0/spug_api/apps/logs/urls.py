from django.conf.urls import url
from apps.logs.views import AuditLogView, AuditLogExportView, AuditLogTargetTypesView, AuditLogActionsView

urlpatterns = [
    url(r'^audit/$', AuditLogView.as_view()),
    url(r'^audit/export/$', AuditLogExportView.as_view()),
    url(r'^audit/target_types/$', AuditLogTargetTypesView.as_view()),
    url(r'^audit/actions/$', AuditLogActionsView.as_view()),
]
