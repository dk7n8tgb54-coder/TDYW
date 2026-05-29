# -*- coding: utf-8 -*-
"""
排班模块常量定义
Schedule Module Constants

第一阶段重构：基础设施
"""


class SwapStatus:
    """换班/替班状态"""
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    CANCELLED = 'cancelled'


class ScheduleStatus:
    """排班状态"""
    ACTIVE = 'active'
    SWAPPED = 'swapped'
    SUBSTITUTED = 'substituted'


class ShiftType:
    """班次类型"""
    WORK_REST = 'work_rest'
    CUSTOM = 'custom'


# 错误消息
ERROR_MESSAGES = {
    'RECORD_NOT_FOUND': '记录不存在或无权操作',
    'SCHEDULE_CONFLICT': '该人员在此日期已有排班',
    'SWAP_SELF': '不能与自己换班',
    'ALREADY_APPROVED': '已审批的记录不能修改',
    'INVALID_STATUS_TRANSITION': '不允许的状态流转',
}

# 状态显示文本（用于日志和API响应）
STATUS_DISPLAY_NAMES = {
    SwapStatus.PENDING: '待审批',
    SwapStatus.APPROVED: '已通过',
    SwapStatus.REJECTED: '已拒绝',
    SwapStatus.CANCELLED: '已取消',
}

# 班次类型显示文本
SHIFT_TYPE_DISPLAY_NAMES = {
    ShiftType.WORK_REST: '上X休Y',
    ShiftType.CUSTOM: '自定义',
}

# 状态流转规则（用于验证）
VALID_STATUS_TRANSITIONS = {
    SwapStatus.PENDING: [SwapStatus.APPROVED, SwapStatus.REJECTED],
    SwapStatus.APPROVED: [SwapStatus.CANCELLED],
    SwapStatus.REJECTED: [],
    SwapStatus.CANCELLED: [],
}

# 默认分页配置
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 批量操作限制
BATCH_OPERATION_LIMITS = {
    'max_items_per_batch': 100,
    'max_per_minute': 10,
    'max_per_hour': 100,
}
