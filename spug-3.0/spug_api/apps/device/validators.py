"""
设备事件验证模块
处理设备事件相关的验证逻辑
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DeviceEventValidator:
    """设备事件验证器"""

    # 事件类型常量（与 DeviceEvent.EVENT_TYPE_* 保持一致）
    EVENT_TYPE_MAINTENANCE = 3

    @classmethod
    def validate_event_type(cls, form):
        """
        验证事件类型是否在合法枚举范围内

        Returns:
            tuple: (is_valid, error_message)
        """
        from apps.device.models import DeviceEvent
        if form.event_type not in DeviceEvent.EVENT_TYPE_VALUES:
            return False, '事件类型非法，仅支持：1=重大故障维修，2=设备更新，3=设备检修'
        return True, None

    @classmethod
    def validate_maintenance_fields(cls, form):
        """
        验证设备维护事件的必填字段

        Returns:
            tuple: (is_valid, error_message)
        """
        if form.event_type != cls.EVENT_TYPE_MAINTENANCE:
            return True, None

        required_fields = [
            ('fault_part', '请填写故障部位'),
            ('fault_phenomenon_cause', '请填写故障现象及原因'),
            ('maintenance_measures', '请填写检修措施'),
            ('repair_time', '请填写修复时间'),
        ]

        for field, message in required_fields:
            if not getattr(form, field, None):
                return False, message

        return True, None

    @classmethod
    def validate_time_logic(cls, form):
        """
        验证时间逻辑（修复时间不能早于故障时间）

        Returns:
            tuple: (is_valid, error_message)
        """
        if not (form.repair_time and form.event_time):
            return True, None

        try:
            repair_time = datetime.strptime(form.repair_time, '%Y-%m-%d %H:%M')
            event_time = datetime.strptime(form.event_time, '%Y-%m-%d %H:%M')
            current_time = datetime.now()

            if repair_time < event_time:
                return False, '修复时间不能早于故障时间'

            if repair_time > current_time or event_time > current_time:
                return False, '时间不能晚于当前时间'

            return True, None

        except ValueError:
            return False, '时间格式错误，请使用YYYY-MM-DD HH:MM格式（如：2026-03-03 14:30）'


class DeviceEventBuilder:
    """设备事件构建器"""

    @classmethod
    def build_event_data(cls, form, device, request_user):
        """
        构建设备事件数据字典

        前端字段命名已规范化为 related_user_name（姓名），
        为兼容旧前端仍传 related_user_id 的情况，此处同时读取两个字段。

        Returns:
            dict: 用于创建 DeviceEvent 的数据
        """
        tenant_id = getattr(request_user, 'tenant_id', '')

        # 优先使用 related_user_name；兼容旧字段 related_user_id（前端旧版传姓名字符串）
        related_user_name = getattr(form, 'related_user_name', None) \
            or getattr(form, 'related_user_id', None) or ''

        return {
            'tenant_id': tenant_id,
            'device_resume_id': form.device_resume_id,
            'device_name': device.device_name,
            'device_sn': device.device_sn,
            'event_type': form.event_type,
            'event_time': form.event_time,
            'event_title': form.event_title,
            'fault_part': form.fault_part,
            'fault_phenomenon_cause': form.fault_phenomenon_cause,
            'maintenance_measures': form.maintenance_measures,
            'related_user_id': None,
            'related_user_name': related_user_name,
            'repair_time': form.repair_time,
            'remark': form.remark,
            'created_by': request_user
        }
