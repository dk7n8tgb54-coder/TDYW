# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.urls import path

from .views import (
    ReminderView,
    ReminderUsersView,
    ReminderPendingView,
    ReminderAckView,
    ReminderStatusView,
)

urlpatterns = [
    # 管理端
    path('', ReminderView.as_view()),
    path('<int:pk>/', ReminderView.as_view()),
    path('users/', ReminderUsersView.as_view()),
    path('status/', ReminderStatusView.as_view()),
    # 用户端
    path('pending/', ReminderPendingView.as_view()),
    path('ack/', ReminderAckView.as_view()),
]
