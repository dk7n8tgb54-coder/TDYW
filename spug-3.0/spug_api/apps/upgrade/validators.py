# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块校验器
"""
import logging
from .constants import UpgradeStatus, UpgradeType, VALID_STATUS_TRANSITIONS

logger = logging.getLogger(__name__)


class RecordValidator:
    """升级表单校验器"""

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
        required_fields = {
            'title': '标题',
            'system': '升级系统',
            'upgrade_type': '升级类型',
            'owner': '负责人',
            'upgrade_time': '计划升级时间',
            'upgrade_content': '升级内容',
        }
        for field, label in required_fields.items():
            val = getattr(data, field, None)
            if not val or not str(val).strip():
                errors.append(f'请填写{label}')

        if getattr(data, 'status', None) not in UpgradeStatus.values():
            errors.append(f'状态值无效，仅支持：{"/".join(UpgradeStatus.values())}')

        if getattr(data, 'upgrade_type', None) not in UpgradeType.values():
            errors.append(f'升级类型无效，仅支持：{"/".join(UpgradeType.values())}')

        # 同租户内单号唯一性
        upgrade_no = getattr(data, 'upgrade_no', None)
        if upgrade_no:
            from .models import UpgradeRecord
            if UpgradeRecord.objects.filter(
                tenant_id=user.tenant_id,
                upgrade_no=upgrade_no
            ).exists():
                errors.append(f'升级单号 [{upgrade_no}] 已存在')

        return None if not errors else '; '.join(errors)

    @staticmethod
    def validate_update(record, data, user):
        """校验更新数据

        Args:
            record: 已有的 UpgradeRecord 实例
            data: 更新数据对象
            user: 当前请求用户

        Returns:
            str: 错误消息，None 表示校验通过
        """
        # 状态流转校验
        new_status = getattr(data, 'status', None)
        if new_status and new_status != record.status:
            if new_status not in VALID_STATUS_TRANSITIONS.get(record.status, []):
                return f'不允许从 [{record.status}] 转为 [{new_status}]'

        return None
