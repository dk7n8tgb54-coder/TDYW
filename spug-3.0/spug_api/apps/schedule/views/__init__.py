# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
Schedule模块视图层

视图层仅负责HTTP请求处理和参数解析，业务逻辑委托给Service层
"""

from .schedule import ScheduleView, ScheduleBatchQueryView
from .staff import ScheduleStaffView
from .shift import ScheduleShiftView
from .swap import ScheduleSwapView
from .substitute import ScheduleSubstituteView
from .batch import (
    ScheduleBatchAdjustView,
    ScheduleBatchSwapView,
    ScheduleBatchSubstituteView,
    ScheduleBatchDeleteView  # 修复P0-2：添加批量删除视图
)

__all__ = [
    'ScheduleView',
    'ScheduleBatchQueryView',
    'ScheduleStaffView',
    'ScheduleShiftView',
    'ScheduleSwapView',
    'ScheduleSubstituteView',
    'ScheduleBatchAdjustView',
    'ScheduleBatchSwapView',
    'ScheduleBatchSubstituteView',
    'ScheduleBatchDeleteView',  # 修复P0-2：添加批量删除视图
]
