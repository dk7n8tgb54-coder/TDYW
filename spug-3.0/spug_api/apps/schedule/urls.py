# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
排班模块路由配置

重构后视图分层结构：
- views/schedule.py: 排班CRUD、批量查询
- views/staff.py: 人员管理
- views/shift.py: 班次管理
- views/swap.py: 换班管理
- views/substitute.py: 替班管理
- views/batch.py: 批量操作
"""

from django.urls import path
from .views import (
    ScheduleView, ScheduleBatchQueryView,
    ScheduleStaffView,
    ScheduleShiftView,
    ScheduleSwapView,
    ScheduleSubstituteView,
    ScheduleBatchAdjustView,
    ScheduleBatchSwapView,
    ScheduleBatchSubstituteView,
    ScheduleBatchDeleteView  # 修复P0-2：添加批量删除视图
)

app_name = 'schedule'

urlpatterns = [
    # 排班CRUD
    path('', ScheduleView.as_view()),
    path('auto/', ScheduleView.as_view()),  # 自动排班复用ScheduleView

    # 批量查询
    path('batch_query/', ScheduleBatchQueryView.as_view()),

    # 人员管理
    path('staff/', ScheduleStaffView.as_view()),

    # 班次管理
    path('shift/', ScheduleShiftView.as_view()),

    # 换班管理
    path('swap/', ScheduleSwapView.as_view()),

    # 替班管理
    path('substitute/', ScheduleSubstituteView.as_view()),

    # 批量操作
    path('batch_delete/', ScheduleBatchDeleteView.as_view()),  # 修复P0-2：添加批量删除路由
    path('batch_adjust/', ScheduleBatchAdjustView.as_view()),
    path('batch_swap/', ScheduleBatchSwapView.as_view()),
    path('batch_substitute/', ScheduleBatchSubstituteView.as_view()),
]
