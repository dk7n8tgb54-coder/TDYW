# -*- coding: utf-8 -*-
"""
数据验证工具
Data Validation Utilities

第一阶段重构：基础设施
"""

import re
from datetime import datetime

from ..constants import VALID_STATUS_TRANSITIONS


class ScheduleValidator:
    """排班数据验证器"""
    
    # 正则表达式模式
    DATETIME_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
    DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    
    @classmethod
    def validate_datetime(cls, value, field_name='时间'):
        """
        验证日期时间格式
        
        Args:
            value: 待验证的值
            field_name: 字段名称，用于错误提示
            
        Returns:
            str/None: 错误信息或None（验证通过）
        """
        if not value:
            return None
        if not cls.DATETIME_PATTERN.match(str(value)):
            return f'{field_name}格式错误，请使用：YYYY-MM-DD HH:MM:SS'
        return None
    
    @classmethod
    def validate_date(cls, value, field_name='日期'):
        """
        验证日期格式
        
        Args:
            value: 待验证的值
            field_name: 字段名称，用于错误提示
            
        Returns:
            str/None: 错误信息或None（验证通过）
        """
        if not value:
            return None
        if not cls.DATE_PATTERN.match(str(value)):
            return f'{field_name}格式错误，请使用：YYYY-MM-DD'
        return None
    
    @classmethod
    def validate_date_range(cls, start_date, end_date):
        """
        验证日期范围
        
        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
            
        Returns:
            str/None: 错误信息或None（验证通过）
        """
        if not start_date or not end_date:
            return None
        
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            
            if start > end:
                return '开始日期不能晚于结束日期'
            
            # 限制日期范围不超过1年
            days_diff = (end - start).days
            if days_diff > 365:
                return '日期范围不能超过1年'
            
            return None
        except ValueError:
            return '日期格式无效'
    
    @classmethod
    def validate_swap_status_transition(cls, current_status, new_status):
        """
        验证换班状态流转是否合法
        
        Args:
            current_status: 当前状态
            new_status: 目标状态
            
        Returns:
            str/None: 错误信息或None（验证通过）
        """
        valid_transitions = VALID_STATUS_TRANSITIONS.get(current_status, [])
        
        if new_status not in valid_transitions:
            return f'不允许的状态流转：{current_status} -> {new_status}'
        return None
    
    @classmethod
    def validate_staff_id(cls, staff_id, field_name='人员ID'):
        """
        验证人员ID
        
        Args:
            staff_id: 人员ID
            field_name: 字段名称
            
        Returns:
            str/None: 错误信息或None（验证通过）
        """
        if not staff_id:
            return f'{field_name}不能为空'
        
        try:
            staff_id = int(staff_id)
            if staff_id <= 0:
                return f'{field_name}必须大于0'
            return None
        except (ValueError, TypeError):
            return f'{field_name}必须是有效的整数'
    
    @classmethod
    def validate_batch_items(cls, items, max_items=100):
        """
        验证批量操作数据
        
        Args:
            items: 待验证的数据列表
            max_items: 最大允许数量
            
        Returns:
            str/None: 错误信息或None（验证通过）
        """
        if not items:
            return '批量操作数据不能为空'
        
        if not isinstance(items, list):
            return '批量操作数据必须是列表'
        
        if len(items) > max_items:
            return f'批量操作数量不能超过{max_items}条'
        
        if len(items) == 0:
            return '批量操作数据不能为空列表'
        
        return None
