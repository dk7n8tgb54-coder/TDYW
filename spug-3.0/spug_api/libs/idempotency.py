# -*- coding: utf-8 -*-
"""
幂等性工具：防止重复提交创建重复数据

依据《CRUD 系统可靠性工程实践指南》1.3 幂等性设计要求，
在核心写操作前检查最近时间窗口内是否已存在相同业务数据的记录。

使用方式：
    from libs.idempotency import check_recent_duplicate, IdempotencyError

    if check_recent_duplicate(DutyRecord, {
        'duty_person': form['duty_person'],
        'department': form['department'],
        'duty_date': form['duty_date'],
    }):
        raise IdempotencyError('值班日志')
"""
from datetime import timedelta
from django.utils import timezone


class IdempotencyError(Exception):
    """幂等性拒绝异常：检测到重复提交"""
    pass


def check_recent_duplicate(model_class, filters, window_seconds=30):
    """检查最近时间窗口内是否已存在相同业务数据的记录

    Args:
        model_class: Django 模型类
        filters: dict, 业务字段过滤条件（如 {'name': 'xxx', 'department': 'yyy'}）
        window_seconds: int, 时间窗口秒数，默认 30 秒

    Returns:
        bool: True 表示存在重复（应拒绝创建），False 表示无重复
    """
    threshold = timezone.now() - timedelta(seconds=window_seconds)
    qs = model_class.objects.filter(**filters, created_at__gte=threshold)
    # 过滤掉已软删除的记录，避免误判。
    # 兼容两种软删除约定：is_deleted 布尔标志（TenantModelMixin 系模型）
    # 与 deleted_at 时间戳（非租户全局表，如 DepartmentDutyLog）。
    # 双字段并存的模型走 is_deleted 分支，行为与历史一致。
    if hasattr(model_class, 'is_deleted'):
        qs = qs.filter(is_deleted=False)
    elif hasattr(model_class, 'deleted_at'):
        qs = qs.filter(deleted_at__isnull=True)
    return qs.exists()
