# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from apps.equipment_lifecycle import views

urlpatterns = [
    # 系统类型
    path('system-types/', views.SystemTypeView.as_view()),
    path('system-types/<int:pk>/', views.SystemTypeDetailView.as_view()),
    path('system-types/<int:pk>/fields/', views.TypeFieldView.as_view()),
    path('system-types/<int:pk>/fields/<int:fid>/', views.TypeFieldDetailView.as_view()),
    # 系统主数据
    path('systems/', views.SystemView.as_view()),
    path('systems/export/', views.SystemExportView.as_view()),
    path('systems/<int:pk>/', views.SystemDetailView.as_view()),
    path('systems/<int:pk>/active/', views.SystemActiveView.as_view()),
    path('systems/<int:pk>/config/', views.SystemConfigView.as_view()),
    path('systems/<int:pk>/config/export/', views.SystemConfigExportView.as_view()),
    path('systems/<int:pk>/config/attachments/', views.SystemConfigAttachmentView.as_view()),
    path('systems/<int:pk>/config/attachments/<int:aid>/download/', views.SystemConfigAttachmentDownloadView.as_view()),
    path('systems/<int:pk>/config/attachments/<int:aid>/', views.SystemConfigAttachmentDetailView.as_view()),
    path('systems/<int:pk>/components/', views.SystemComponentView.as_view()),
    path('systems/<int:pk>/components/<int:cid>/', views.SystemComponentDetailView.as_view()),
    path('systems/<int:pk>/custom-fields/', views.CustomFieldView.as_view()),
    path('systems/<int:pk>/custom-fields/<int:fid>/', views.CustomFieldDetailView.as_view()),
    path('systems/<int:pk>/custom-fields/<int:fid>/promote/', views.CustomFieldPromoteView.as_view()),
    path('systems/<int:pk>/changes/', views.SystemChangeView.as_view()),
    path('systems/<int:pk>/snapshots/', views.SystemSnapshotView.as_view()),
    path('systems/<int:pk>/snapshots/<int:sid>/', views.SystemSnapshotDetailView.as_view()),
]
