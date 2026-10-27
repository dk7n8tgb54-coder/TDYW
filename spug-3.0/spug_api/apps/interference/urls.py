"""干扰管理统一事件 API 路由。"""

from django.urls import re_path

from apps.interference.category_views import CategoryDetailView, CategoryListView
from apps.interference.investigation_actions import (
    InvestigationCancelView,
    InvestigationFinishView,
)
from apps.interference.views import (
    AttachmentDeleteView,
    AttachmentDownloadView,
    AttachmentPreviewFileView,
    AttachmentPreviewUrlView,
    EventAttachmentListView,
    EventDetailView,
    EventExportView,
    EventImportView,
    EventListView,
    InvestigationAttachmentListView,
    InvestigationDetailView,
    InvestigationEventsView,
    InvestigationListView,
    InvestigationMeasurementsView,
    MeasurementAttachmentListView,
    MeasurementDetailView,
)


urlpatterns = [
    re_path(r'^categories/$', CategoryListView.as_view(), name='interference-categories'),
    re_path(r'^categories/(?P<pk>\d+)/$',
            CategoryDetailView.as_view(), name='interference-category-detail'),

    re_path(r'^events/export/$', EventExportView.as_view(), name='interference-event-export'),
    re_path(r'^events/import/$', EventImportView.as_view(), name='interference-event-import'),
    re_path(r'^events/$', EventListView.as_view(), name='interference-events'),
    re_path(r'^events/(?P<pk>\d+)/attachments/$',
            EventAttachmentListView.as_view(), name='interference-event-attachments'),
    re_path(r'^events/(?P<pk>\d+)/$', EventDetailView.as_view(), name='interference-event-detail'),

    re_path(r'^investigations/$', InvestigationListView.as_view(),
            name='interference-investigations'),
    re_path(r'^investigations/(?P<pk>\d+)/events/$', InvestigationEventsView.as_view(),
            name='interference-investigation-events'),
    re_path(r'^investigations/(?P<pk>\d+)/finish/$', InvestigationFinishView.as_view(),
            name='interference-investigation-finish'),
    re_path(r'^investigations/(?P<pk>\d+)/cancel/$', InvestigationCancelView.as_view(),
            name='interference-investigation-cancel'),
    re_path(r'^investigations/(?P<pk>\d+)/measurements/$',
            InvestigationMeasurementsView.as_view(),
            name='interference-investigation-measurements'),
    re_path(r'^investigations/(?P<pk>\d+)/attachments/$',
            InvestigationAttachmentListView.as_view(),
            name='interference-investigation-attachments'),
    re_path(r'^investigations/(?P<pk>\d+)/$', InvestigationDetailView.as_view(),
            name='interference-investigation-detail'),

    re_path(r'^measurements/(?P<pk>\d+)/attachments/$',
            MeasurementAttachmentListView.as_view(),
            name='interference-measurement-attachments'),
    re_path(r'^measurements/(?P<pk>\d+)/$', MeasurementDetailView.as_view(),
            name='interference-measurement-detail'),

    re_path(r'^attachments/$', AttachmentDeleteView.as_view(),
            name='interference-attachment-delete'),
    re_path(r'^attachments/(?P<pk>\d+)/download/$', AttachmentDownloadView.as_view(),
            name='interference-attachment-download'),
    re_path(r'^attachments/(?P<pk>\d+)/preview-url/$',
            AttachmentPreviewUrlView.as_view(), name='interference-attachment-preview-url'),
    re_path(r'^attachments/(?P<pk>\d+)/preview-file/$',
            AttachmentPreviewFileView.as_view(), name='interference-attachment-preview-file'),
]
