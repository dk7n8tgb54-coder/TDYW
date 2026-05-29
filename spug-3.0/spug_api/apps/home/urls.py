# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from .views import *
from apps.home.notice import NoticeView
from apps.home.navigation import NavView

urlpatterns = [
    path('statistic/', get_statistic),
    path('duty/today/', DutyTodayView.as_view()),
    path('notice/', NoticeView.as_view()),
    path('navigation/', NavView.as_view()),
]
