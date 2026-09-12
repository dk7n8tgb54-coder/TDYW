# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from .views import (
    SystemVersionView,
    ReleaseNoteListView,
    ReleaseNoteUnreadView,
    ReleaseNoteSettingsView,
    ReleaseNoteDetailView,
    ReleaseNoteReadView,
    ReleaseNoteAckView,
    ReleaseNoteAdminListView,
    ReleaseNoteAdminDetailView,
    ReleaseNoteAdminPublishView,
)

urlpatterns = [
    path('version/', SystemVersionView.as_view()),

    # 用户端
    path('release-notes/', ReleaseNoteListView.as_view()),
    path('release-notes/unread/', ReleaseNoteUnreadView.as_view()),
    path('release-notes/settings/', ReleaseNoteSettingsView.as_view()),
    path('release-notes/<int:pk>/', ReleaseNoteDetailView.as_view()),
    path('release-notes/<int:pk>/read/', ReleaseNoteReadView.as_view()),
    path('release-notes/<int:pk>/ack/', ReleaseNoteAckView.as_view()),

    # 管理端
    path('release-notes/admin/', ReleaseNoteAdminListView.as_view()),
    path('release-notes/admin/<int:pk>/', ReleaseNoteAdminDetailView.as_view()),
    path('release-notes/admin/<int:pk>/publish/', ReleaseNoteAdminPublishView.as_view()),
]
