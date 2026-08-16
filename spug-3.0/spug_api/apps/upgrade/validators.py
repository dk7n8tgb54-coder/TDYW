# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块校验器
"""
import logging
from datetime import datetime

from .constants import UpgradeStatus, UpgradeType, VALID_STATUS_TRANSITIONS

logger = logging.getLogger(__name__)

# upgrade_time 合法格式（前端提交 'YYYY-MM-DD HH:mm:ss'，兼容日期/分钟精度）
UPGRADE_TIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d')


def validate_upgrade_time(value):
    """校验计划升级时间格式

    Args:
        value: 待校验值（None 表示未提供，直接通过；datetime 对象直接通过；
               字符串按支持的格式解析，空字符串视为非法——清空请传 null）

    Returns:
        str: 错误消息，None 表示合法
    """
    if value is None or hasattr(value, 'strftime'):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text:
            for fmt in UPGRADE_TIME_FORMATS:
                try:
                    datetime.strptime(text, fmt)
                    return None
                except ValueError:
                    continue
    return '计划升级时间格式无效，应为 YYYY-MM-DD HH:mm:ss'


class RecordValidator:
    """升级表单校验器"""

    # 必填字段（提供即不允许清空；创建时必须提供）
    REQUIRED_FIELDS = {
        'title': '标题',
        'system': '升级系统',
        'upgrade_type': '升级类型',
        'owner': '负责人',
        'upgrade_time': '计划升级时间',
        'upgrade_content': '升级内容',
    }

    @staticmethod
    def validate_create(data, user):
        """校验创建数据

        Args:
            data: 表单数据对象（JsonParser 解析后的对象）
            user: 当前请求用户

        Returns:
            str: 错误消息，None 表示校验通过
        """
        errors = []

        # 必填字段非空校验（新建表单只收集建单必需信息）
        for field, label in RecordValidator.REQUIRED_FIELDS.items():
            val = getattr(data, field, None)
            if not val or not str(val).strip():
                errors.append(f'请填写{label}')

        if getattr(data, 'status', None) not in UpgradeStatus.values():
            errors.append(f'状态值无效，仅支持：{"/".join(UpgradeStatus.values())}')

        if getattr(data, 'upgrade_type', None) not in UpgradeType.values():
            errors.append(f'升级类型无效，仅支持：{"/".join(UpgradeType.values())}')

        error = validate_upgrade_time(getattr(data, 'upgrade_time', None))
        if error:
            errors.append(error)

        return None if not errors else '; '.join(errors)

    @staticmethod
    def validate_update(record, data, user):
        """校验更新数据（仅校验请求中实际提供的字段，未提供的不限制）

        Args:
            record: 已有的 UpgradeRecord 实例
            data: 更新数据对象
            user: 当前请求用户

        Returns:
            str: 错误消息，None 表示校验通过
        """
        # 必填字段提供即不可清空（空字符串/纯空白视为清空）
        for field, label in RecordValidator.REQUIRED_FIELDS.items():
            val = getattr(data, field, None)
            if val is not None and not str(val).strip():
                return f'请填写{label}'

        # 枚举值校验（与创建对称）
        new_type = getattr(data, 'upgrade_type', None)
        if new_type is not None and new_type not in UpgradeType.values():
            return f'升级类型无效，仅支持：{"/".join(UpgradeType.values())}'

        new_status = getattr(data, 'status', None)
        if new_status is not None and new_status not in UpgradeStatus.values():
            return f'状态值无效，仅支持：{"/".join(UpgradeStatus.values())}'

        # 时间格式校验（避免非法字符串进入 DateTimeField 触发未捕获异常）
        error = validate_upgrade_time(getattr(data, 'upgrade_time', None))
        if error:
            return error

        # 状态流转校验
        if new_status and new_status != record.status:
            if new_status not in VALID_STATUS_TRANSITIONS.get(record.status, []):
                return f'不允许从 [{record.status}] 转为 [{new_status}]'

        return None
