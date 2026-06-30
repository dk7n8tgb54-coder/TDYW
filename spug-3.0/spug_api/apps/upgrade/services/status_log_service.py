# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级状态日志服务 - 记录/列表/删除 + 主表 status 联动"""
import logging
from django.db import transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter
from ..constants import UpgradeStatus
from ..models_status_log import (
    UpgradeStatusLog,
    ACTION_TO_MAIN_STATUS,
    ACTION_CHOICES,
)

logger = logging.getLogger(__name__)

# 动作 → 中文（用于序列化）
_ACTION_TEXT = {code: text for code, text in ACTION_CHOICES}


class StatusLogService:
    """升级状态日志服务"""

    @staticmethod
    def get_logs(upgrade_id, user):
        """获取某升级表单的状态日志列表（时间倒序，最新在前）

        Args:
            upgrade_id: 升级表单ID
            user: 当前请求用户（用于租户隔离）

        Returns:
            list: 日志列表，每项含 action/action_text/remark/operator_name/created_at
        """
        qs = apply_tenant_filter(
            UpgradeStatusLog.objects.filter(upgrade_id=upgrade_id), user
        ).order_by('-created_at', '-id')
        result = []
        for log in qs:
            result.append({
                'id': log.id,
                'action': log.action,
                'action_text': _ACTION_TEXT.get(log.action, log.action),
                'from_status': log.from_status,
                'to_status': log.to_status,
                'operator_id': log.operator_id,
                'operator_name': log.operator_name or '-',
                'remark': log.remark or '',
                'created_at': log.created_at,
            })
        return result

    @staticmethod
    def add_log(upgrade_id, user, action, remark=''):
        """记录一条状态日志，并联动主表 status（如动作对应主表状态变更）

        Args:
            upgrade_id: 升级表单ID
            user: 当前请求用户
            action: 动作类型（必须为 ACTION_CHOICES 中的合法值）
            remark: 备注

        Returns:
            tuple: (log, error)
        """
        from ..models import UpgradeRecord

        # 校验动作类型
        valid_actions = [code for code, _ in ACTION_CHOICES]
        if action not in valid_actions:
            return None, f'无效的动作类型，支持：{", ".join(valid_actions)}'

        # 校验业务对象存在
        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if record is None:
            return None, '升级表单不存在或无权限访问'

        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        from_status = record.status

        # 联动主表 status（如回退→已回退，完成→已完成）
        to_status = ''
        target_main_status = ACTION_TO_MAIN_STATUS.get(action)
        if target_main_status and target_main_status != from_status:
            to_status = target_main_status
        else:
            to_status = from_status  # 不联动则 to=from

        try:
            with transaction.atomic():
                # 1. 写日志
                log = UpgradeStatusLog.objects.create(
                    tenant_id=getattr(user, 'tenant_id', ''),
                    upgrade_id=upgrade_id,
                    action=action,
                    from_status=from_status,
                    to_status=to_status,
                    operator_id=getattr(user, 'id', 0),
                    operator_name=user.nickname or user.username,
                    remark=remark or '',
                    created_at=now_str,
                )

                # 2. 联动主表 status（如需要）
                if target_main_status and target_main_status != from_status:
                    record.status = target_main_status
                    record.updated_at = now_str
                    record.updated_by = user
                    record.save(update_fields=['status', 'updated_at', 'updated_by'])

            logger.info(
                f'[Upgrade] 状态日志 upgrade_id={upgrade_id} action={action} '
                f'{from_status}→{to_status} 用户={user.username}'
            )
            return log, None
        except Exception as e:
            logger.error(f'[Upgrade] 记录状态日志失败: {e}', exc_info=True)
            return None, f'记录状态日志失败: {str(e)}'

    @staticmethod
    def delete_log(log_id, user):
        """删除一条状态日志（仅删除日志，不回滚主表 status）

        Args:
            log_id: 日志ID
            user: 当前请求用户

        Returns:
            str: 错误消息，None 表示成功
        """
        qs = apply_tenant_filter(
            UpgradeStatusLog.objects.all(), user
        )
        log = qs.filter(pk=log_id).first()
        if log is None:
            return '日志不存在或无权限删除'

        try:
            log.delete()
            logger.info(
                f'[Upgrade] 删除状态日志 id={log_id} '
                f'upgrade_id={log.upgrade_id} 用户={user.username}'
            )
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 删除状态日志失败: {e}', exc_info=True)
            return f'删除状态日志失败: {str(e)}'

    @staticmethod
    def get_action_options():
        """获取动作类型选项（供前端下拉选择）

        Returns:
            list: [{value, label, color}, ...]
        """
        from ..models_status_log import ACTION_COLOR_MAP
        return [
            {'value': code, 'label': text, 'color': ACTION_COLOR_MAP.get(code, 'default')}
            for code, text in ACTION_CHOICES
        ]
