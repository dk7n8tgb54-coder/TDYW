# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from .views import *
from apps.home.notice import NoticeView
from apps.home.navigation import NavView
from apps.home.announcement import (
    AnnouncementAdminListView,
    AnnouncementAdminDetailView,
    AnnouncementDepartmentsView,
    AnnouncementPublishView,
    AnnouncementWithdrawView,
    AnnouncementAttachmentListView,
    AnnouncementAttachmentDeleteView,
    AnnouncementListView,
    AnnouncementDetailView,
    AnnouncementReadView,
    AnnouncementUserAttachmentListView,
    AnnouncementUnreadCountView,
    AnnouncementRemindersView,
    AnnouncementAttachmentDownloadView,
    AnnouncementAttachmentPreviewUrlView,
    AnnouncementAttachmentPreviewFileView,
)

urlpatterns = [
    path('statistic/', get_statistic),
    path('alert/', AlertListView.as_view()),
    path('alert/mark-read/', AlertMarkReadView.as_view()),
    path('alert/<int:pk>/resolve/', AlertResolveView.as_view()),
    path('notice/', NoticeView.as_view()),
    path('navigation/', NavView.as_view()),

    # ===== 公告发布模块 =====
    # 管理端
    path('announcement/admin/', AnnouncementAdminListView.as_view()),
    path('announcement/admin/departments/', AnnouncementDepartmentsView.as_view()),
    path('announcement/admin/<int:pk>/', AnnouncementAdminDetailView.as_view()),
    path('announcement/admin/<int:pk>/publish/', AnnouncementPublishView.as_view()),
    path('announcement/admin/<int:pk>/withdraw/', AnnouncementWithdrawView.as_view()),
    path('announcement/admin/<int:pk>/attachments/', AnnouncementAttachmentListView.as_view()),
    path('announcement/admin/attachments/', AnnouncementAttachmentDeleteView.as_view()),
    # 用户端
    path('announcement/', AnnouncementListView.as_view()),
    path('announcement/unread-count/', AnnouncementUnreadCountView.as_view()),
    path('announcement/reminders/', AnnouncementRemindersView.as_view()),
    path('announcement/<int:pk>/', AnnouncementDetailView.as_view()),
    path('announcement/<int:pk>/read/', AnnouncementReadView.as_view()),
    path('announcement/<int:pk>/attachments/', AnnouncementUserAttachmentListView.as_view()),
    # 附件下载 / 预览（用户与管理员共用路径）
    path('announcement/attachments/<int:pk>/download/', AnnouncementAttachmentDownloadView.as_view()),
    path('announcement/attachments/<int:pk>/preview-url/', AnnouncementAttachmentPreviewUrlView.as_view()),
    path('announcement/attachments/<int:pk>/preview-file/', AnnouncementAttachmentPreviewFileView.as_view()),
]
