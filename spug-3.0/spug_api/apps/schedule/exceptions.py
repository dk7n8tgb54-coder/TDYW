# -*- coding: utf-8 -*-
"""
排班模块业务异常定义
Schedule Module Business Exceptions

第一阶段重构：基础设施
"""


class ScheduleException(Exception):
    """排班业务异常基类"""
    
    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        self.code = code or 'SCHEDULE_ERROR'

    def to_dict(self):
        """转换为字典格式，用于API响应"""
        return {
            'error': self.message,
            'code': self.code
        }


class ScheduleConflictError(ScheduleException):
    """排班冲突异常 - 同一人员同一天有多个排班"""
    
    def __init__(self, message='该人员在此日期已有排班'):
        super().__init__(message, 'SCHEDULE_CONFLICT')


class SwapSelfError(ScheduleException):
    """不能与自己换班异常"""
    
    def __init__(self, message='不能与自己换班'):
        super().__init__(message, 'SWAP_SELF')


class AlreadyApprovedError(ScheduleException):
    """已审批记录不能修改异常"""
    
    def __init__(self, message='已审批的记录不能修改'):
        super().__init__(message, 'ALREADY_APPROVED')


class RecordNotFoundError(ScheduleException):
    """记录不存在异常"""
    
    def __init__(self, message='记录不存在或无权操作'):
        super().__init__(message, 'RECORD_NOT_FOUND')


class InvalidStatusTransitionError(ScheduleException):
    """非法状态流转异常"""
    
    def __init__(self, current_status, new_status):
        message = f'不允许的状态流转：{current_status} -> {new_status}'
        super().__init__(message, 'INVALID_STATUS_TRANSITION')


class PermissionDeniedError(ScheduleException):
    """权限不足异常"""
    
    def __init__(self, message='无权执行此操作'):
        super().__init__(message, 'PERMISSION_DENIED')


class TenantIsolationError(ScheduleException):
    """租户隔离异常 - 跨租户操作"""
    
    def __init__(self, message='跨租户操作不被允许'):
        super().__init__(message, 'TENANT_ISOLATION_VIOLATION')
