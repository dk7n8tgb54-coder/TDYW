# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""升级状态日志服务 - 记录/列表/删除 + 主表 status 联动 + 流程顺序校验"""
import logging
from django.db import transaction, models
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter
from ..constants import UpgradeStatus
from ..constants import (
    MAIN_FLOW_ACTIONS, MAIN_FLOW_INDEX, ROLLBACK_TARGET_ACTIONS,
    FLOW_NODE_LABELS, FLOW_STAGE_LABELS,
)
from ..models_status_log import (
    UpgradeStatusLog,
    ACTION_TO_MAIN_STATUS,
    ACTION_CHOICES,
    ACTION_TEST,
    ACTION_TEST_FAIL,
)

logger = logging.getLogger(__name__)

# 动作 → 中文（用于序列化）
_ACTION_TEXT = {code: text for code, text in ACTION_CHOICES}


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes', 'on')
    return bool(value)


class StatusLogService:
    """升级状态日志服务"""

    @staticmethod
    def to_view(log):
        """单条日志序列化（供视图层调用）"""
        target = log.target_action or ''
        return {
            'id': log.id,
            'action': log.action,
            'action_text': _ACTION_TEXT.get(log.action, log.action),
            'from_status': log.from_status,
            'to_status': log.to_status,
            'operator_id': log.operator_id,
            'operator_name': log.operator_name or '-',
            'remark': log.remark or '',
            'created_at': log.created_at,
            'target_action': target,
            'target_action_text': FLOW_STAGE_LABELS.get(target, target) if target else '',
            'event_seq': log.event_seq,
            'is_override': log.is_override,
        }

    @staticmethod
    def get_logs(upgrade_id, user):
        """获取某升级表单的状态日志列表（event_seq 倒序，最新在前）

        前端展示用倒序；流程归约（computeFlowState）在正序处理时自行排序。
        """
        qs = apply_tenant_filter(
            UpgradeStatusLog.objects.filter(upgrade_id=upgrade_id), user
        ).order_by('-event_seq', '-id')
        return [StatusLogService.to_view(log) for log in qs]

    @staticmethod
    def _compute_current_index(logs):
        """重放日志序列，计算当前流程进度索引（-1 表示尚未开始）。

        与前端 computeFlowState 逻辑一致：
        - 主线 action 推进 currentIndex（需满足顺序或 is_override）
        - rollback 根据 target_action 把 currentIndex 退回到 target_idx - 1
          （目标节点变为"待重做"，即 current）
        """
        current_index = -1
        for log in logs:
            action = log.action
            if action == 'rollback':
                target = log.target_action or ''
                if target in MAIN_FLOW_INDEX:
                    target_idx = MAIN_FLOW_INDEX[target]
                    # 仅当目标在当前进度范围内才生效（不能回退到未完成的节点）
                    if target_idx <= current_index:
                        current_index = target_idx - 1
            elif action == ACTION_TEST_FAIL:
                test_idx = MAIN_FLOW_INDEX.get('test_pass')
                if test_idx is not None and (test_idx <= current_index + 1 or log.is_override):
                    if log.is_override:
                        current_index = max(current_index, test_idx - 1)
                    else:
                        current_index = min(current_index, test_idx - 1)
            elif action in MAIN_FLOW_INDEX:
                idx = MAIN_FLOW_INDEX[action]
                if idx <= current_index + 1 or log.is_override:
                    current_index = max(current_index, idx)
        return current_index

    @staticmethod
    def _next_event_seq(upgrade_id):
        """获取下一个 event_seq（同一 upgrade_id 内递增）。"""
        max_seq = UpgradeStatusLog.objects.filter(upgrade_id=upgrade_id).aggregate(
            max_seq=models.Max('event_seq')
        )['max_seq'] or 0
        return max_seq + 1

    @staticmethod
    def _validate_flow(action, upgrade_id, target_action, is_override):
        """校验动作的流程顺序合法性（rollback / 主线推进 / test_fail）。

        Returns:
            tuple: (is_jump, error_message)。error_message 为 None 表示通过。
        """
        # rollback：必须指定合法的回退目标节点
        if action == 'rollback':
            if not target_action:
                return False, '回退操作必须指定"回退到"哪个节点'
            if target_action not in ROLLBACK_TARGET_ACTIONS:
                return False, f'回退目标"{target_action}"不是标准主线流程中的合法节点'
            return False, None

        # 非主线、非 test_fail 的动作不做顺序校验
        if action not in MAIN_FLOW_INDEX and action != ACTION_TEST_FAIL:
            return False, None

        existing_logs = list(
            UpgradeStatusLog.objects.filter(upgrade_id=upgrade_id)
            .order_by('event_seq', 'id')
        )
        current_index = StatusLogService._compute_current_index(existing_logs)
        current_label = (
            MAIN_FLOW_ACTIONS[current_index] if current_index >= 0 else '未开始'
        )
        current_text = FLOW_NODE_LABELS.get(current_label, current_label)

        if action == ACTION_TEST_FAIL:
            test_idx = MAIN_FLOW_INDEX.get('test_pass')
            is_jump = test_idx is not None and current_index < test_idx - 1
        else:
            action_idx = MAIN_FLOW_INDEX[action]
            is_jump = action_idx > current_index + 1
        action_text = FLOW_NODE_LABELS.get(action, action)

        if is_jump and not is_override:
            return True, (
                f'不能直接记录"{action_text}"，当前进度仅到'
                f'"{current_text}"。如需补录请勾选"补录/跳步"并填写备注原因。'
            )
        return is_jump, None

    @staticmethod
    def _resolve_to_status(action, from_status):
        """计算日志的 to_status 及是否需要联动主表 status。

        Returns:
            tuple: (to_status, target_main_status, needs_update)
        """
        target_main_status = ACTION_TO_MAIN_STATUS.get(action)
        needs_update = bool(target_main_status) and target_main_status != from_status
        to_status = target_main_status if needs_update else from_status
        return to_status, target_main_status, needs_update

    @staticmethod
    def _persist_log(*, upgrade_id, user, action, remark, target_action,
                     is_override, from_status, to_status, target_main_status,
                     needs_update, record):
        """事务内写入状态日志并按需联动主表 status。

        Returns:
            tuple: (log, error_message)。error_message 为 None 表示成功。
        """
        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with transaction.atomic():
                # 1. 计算 event_seq（事务内取最大值 + 1）
                event_seq = StatusLogService._next_event_seq(upgrade_id)
                # 2. 写日志
                log = UpgradeStatusLog.objects.create(
                    tenant_id=getattr(user, 'tenant_id', ''),
                    upgrade_id=upgrade_id,
                    action=action,
                    from_status=from_status,
                    to_status=to_status,
                    operator_id=getattr(user, 'id', 0),
                    operator_name=user.nickname or user.username,
                    remark=remark or '',
                    target_action=target_action or '',
                    event_seq=event_seq,
                    is_override=is_override,
                    created_at=now_str,
                )
                # 3. 联动主表 status（如需要）
                if needs_update:
                    record.status = target_main_status
                    record.updated_at = now_str
                    record.updated_by = user
                    record.save(update_fields=['status', 'updated_at', 'updated_by'])
            logger.info(
                f'[Upgrade] 状态日志 upgrade_id={upgrade_id} action={action} '
                f'target={target_action or "-"} override={is_override} '
                f'{from_status}→{to_status} 用户={user.username}'
            )
            return log, None
        except Exception as e:
            logger.error(f'[Upgrade] 记录状态日志失败: {e}', exc_info=True)
            return None, f'记录状态日志失败: {str(e)}'

    @staticmethod
    def add_log(upgrade_id, user, action, remark='', target_action='', is_override=False):
        """记录一条状态日志，并联动主表 status

        Args:
            upgrade_id: 升级表单ID
            user: 当前请求用户
            action: 动作类型（必须为 ACTION_CHOICES 中的合法值）
            remark: 备注
            target_action: 回退目标动作（仅 action=rollback 时必填）
            is_override: 是否补录/跳步（允许跳过前置节点，需配合 remark）

        Returns:
            tuple: (log, error)
        """
        from ..models import UpgradeRecord
        is_override = _as_bool(is_override)

        # 校验动作类型
        valid_actions = [code for code, _ in ACTION_CHOICES if code != ACTION_TEST]
        if action not in valid_actions:
            return None, f'无效的动作类型，支持：{", ".join(valid_actions)}'

        # 校验业务对象存在
        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if record is None:
            return None, '升级表单不存在或无权限访问'

        # === 流程顺序校验（rollback / 主线推进 / test_fail） ===
        is_jump, flow_error = StatusLogService._validate_flow(
            action, upgrade_id, target_action, is_override
        )
        if flow_error:
            return None, flow_error

        # is_override 时 remark 必填
        if is_jump and is_override and not remark.strip():
            return None, '补录/跳步操作必须在备注中说明原因'

        if not is_jump:
            is_override = False

        # 联动主表 status（回退→已回退，完成→已完成）
        to_status, target_main_status, needs_update = StatusLogService._resolve_to_status(
            action, record.status
        )
        return StatusLogService._persist_log(
            upgrade_id=upgrade_id, user=user, action=action, remark=remark,
            target_action=target_action, is_override=is_override,
            from_status=record.status, to_status=to_status,
            target_main_status=target_main_status, needs_update=needs_update,
            record=record,
        )

    @staticmethod
    def _recompute_main_status(upgrade_id, user):
        """根据剩余日志重算主表 status（删除日志后调用）。

        重放所有剩余日志，找到最后一条影响主表状态的记录（complete/rollback）：
        - 最后是 complete → 已完成
        - 最后是 rollback → 已回退
        - 无影响主表状态的记录 → 处理中
        """
        from ..models import UpgradeRecord

        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if record is None:
            return

        logs = list(
            apply_tenant_filter(
                UpgradeStatusLog.objects.filter(upgrade_id=upgrade_id), user
            ).order_by('event_seq', 'id')
        )

        # 找最后一条影响主表状态的 action
        last_status_action = None
        for log in logs:
            if log.action in ACTION_TO_MAIN_STATUS:
                last_status_action = log.action

        if last_status_action == 'complete':
            new_status = UpgradeStatus.COMPLETED
        elif last_status_action == 'rollback':
            new_status = UpgradeStatus.ROLLED_BACK
        else:
            new_status = UpgradeStatus.IN_PROGRESS

        if record.status != new_status:
            now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            record.status = new_status
            record.updated_at = now_str
            record.updated_by = user
            record.save(update_fields=['status', 'updated_at', 'updated_by'])
            logger.info(
                f'[Upgrade] 删除日志后重算主表状态 upgrade_id={upgrade_id} '
                f'status={new_status}'
            )

    @staticmethod
    def delete_log(log_id, user):
        """删除一条状态日志，并重算主表 status（避免不一致）

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

        upgrade_id = log.upgrade_id

        try:
            with transaction.atomic():
                log.delete()
            # 事务提交后重算主表状态
            StatusLogService._recompute_main_status(upgrade_id, user)
            logger.info(
                f'[Upgrade] 删除状态日志 id={log_id} '
                f'upgrade_id={upgrade_id} 用户={user.username}'
            )
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 删除状态日志失败: {e}', exc_info=True)
            return f'删除状态日志失败: {str(e)}'

    @staticmethod
    def get_action_options():
        """获取动作类型选项（供前端下拉选择）

        Returns:
            list: [{value, label, color, is_main_flow}, ...]
        """
        from ..models_status_log import ACTION_COLOR_MAP
        return [
            {
                'value': code,
                'label': text,
                'color': ACTION_COLOR_MAP.get(code, 'default'),
                'is_main_flow': code in MAIN_FLOW_INDEX,
            }
            for code, text in ACTION_CHOICES
            if code != ACTION_TEST
        ]

    @staticmethod
    def get_rollback_targets():
        """获取可作为回退目标的主线节点列表（供前端下拉选择）

        Returns:
            list: [{value, label}, ...]
        """
        return [
            {'value': action, 'label': FLOW_STAGE_LABELS.get(action, action)}
            for action in ROLLBACK_TARGET_ACTIONS
        ]
