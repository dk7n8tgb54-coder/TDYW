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
    ACTION_PHASE_DONE,
    ACTION_PAUSE,
    ACTION_RESUME,
    ACTION_ROLLBACK,
    ACTION_COMPLETE,
    OUTCOME_DONE,
    OUTCOME_FAILED,
    OUTCOME_REVOKED,
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
            'target_action_text': target,
            'event_seq': log.event_seq,
            'is_override': log.is_override,
            'phase': log.phase or '',
            'outcome': log.outcome or OUTCOME_DONE,
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
                     needs_update, record, phase=''):
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
                    phase=phase or '',
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
    def add_log(upgrade_id, user, action, remark='', target_action='', is_override=False, phase=''):
        """记录一条异常事件状态日志，并联动主表 status 与 phase_done outcome。

        正常的阶段完成（phase_done）由 check_phase_completion 自动写入，不走此方法。
        此方法仅处理异常事件：pause/resume/test_fail/rollback/complete。

        Args:
            upgrade_id: 升级表单ID
            user: 当前请求用户
            action: 异常事件动作（pause/resume/test_fail/rollback/complete）
            remark: 备注
            target_action: 回退目标阶段名（仅 rollback 时必填）
            is_override: 兼容旧参数，新逻辑不再使用顺序校验
            phase: 失败阶段名（仅 test_fail 时必填）

        Returns:
            tuple: (log, error)
        """
        from ..models import UpgradeRecord

        exception_actions = {
            ACTION_PAUSE, ACTION_RESUME, ACTION_TEST_FAIL, ACTION_ROLLBACK, ACTION_COMPLETE
        }
        if action not in exception_actions:
            return None, f'无效的动作类型，支持：{", ".join(sorted(exception_actions))}'

        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if record is None:
            return None, '升级表单不存在或无权限访问'

        if action == ACTION_ROLLBACK and not target_action:
            return None, '回退操作必须指定"回退到"哪个阶段'
        if action == ACTION_TEST_FAIL and not phase:
            return None, '测试失败必须指定失败的阶段'
        if action == ACTION_ROLLBACK:
            # 回退目标必须是该记录现存步骤的阶段（按步骤顺序），
            # 避免未知目标触发"回退到开头"式全量重置
            phases = StatusLogService._ordered_phases(upgrade_id, user)
            if phases and target_action not in phases:
                return None, f'回退目标阶段 [{target_action}] 不存在，请从该记录的步骤阶段中选择'

        to_status, target_main_status, needs_update = StatusLogService._resolve_to_status(
            action, record.status
        )
        log, err = StatusLogService._persist_log(
            upgrade_id=upgrade_id, user=user, action=action, remark=remark,
            target_action=target_action, is_override=False,
            from_status=record.status, to_status=to_status,
            target_main_status=target_main_status, needs_update=needs_update,
            record=record, phase=phase,
        )
        if err:
            return None, err

        # 联动 phase_done outcome
        if action == ACTION_TEST_FAIL:
            StatusLogService._mark_phase_done_outcome(upgrade_id, phase, OUTCOME_FAILED)
        elif action == ACTION_ROLLBACK:
            StatusLogService._mark_rollback_phases_failed(upgrade_id, target_action, user)
            StatusLogService._reset_steps_for_rollback(upgrade_id, target_action, user)

        return log, None

    @staticmethod
    def check_phase_completion(upgrade_id, user, phase):
        """检查指定阶段是否全部完成，若是则自动写 phase_done 时间线。

        由步骤 mark_completed/mark_skipped 后调用。
        - phase 为空跳过（无阶段不触发）
        - 该阶段所有步骤 completed/skipped → 写 phase_done（幂等：已有 done 则不重复）
        """
        if not phase:
            return
        from ..models_checklist import UpgradeRecordStep
        steps = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(upgrade_id=upgrade_id, phase=phase), user
        )
        if not steps.exists():
            return
        if steps.exclude(status__in=['completed', 'skipped']).exists():
            return
        # 幂等：已有 outcome=done 的 phase_done 则不重复写
        if UpgradeStatusLog.objects.filter(
            upgrade_id=upgrade_id, action=ACTION_PHASE_DONE,
            phase=phase, outcome=OUTCOME_DONE
        ).exists():
            return
        event_seq = StatusLogService._next_event_seq(upgrade_id)
        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        UpgradeStatusLog.objects.create(
            tenant_id=getattr(user, 'tenant_id', ''),
            upgrade_id=upgrade_id,
            action=ACTION_PHASE_DONE,
            from_status='', to_status='',
            operator_id=getattr(user, 'id', 0),
            operator_name=user.nickname or user.username,
            remark='',
            target_action='',
            event_seq=event_seq,
            is_override=False,
            phase=phase,
            outcome=OUTCOME_DONE,
            created_at=now_str,
        )
        logger.info(f'[Upgrade] 阶段完成自动记录 upgrade_id={upgrade_id} phase={phase}')

    @staticmethod
    def on_step_reset(upgrade_id, user, phase):
        """步骤被重置为待执行时联动：撤销该阶段最近一条 done 的 phase_done。

        - phase 为空跳过
        - 该阶段最近 phase_done 若 outcome=done → 改 revoked（误操作撤销）
        - 若 outcome=failed → 不动（失败重做场景，保留历史）
        """
        if not phase:
            return
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=upgrade_id, action=ACTION_PHASE_DONE, phase=phase
        ).order_by('-event_seq', '-id').first()
        if log and log.outcome == OUTCOME_DONE:
            log.outcome = OUTCOME_REVOKED
            log.save(update_fields=['outcome'])
            logger.info(f'[Upgrade] 阶段完成撤销 upgrade_id={upgrade_id} phase={phase}')

    @staticmethod
    def _ordered_phases(upgrade_id, user):
        """获取该升级记录步骤的阶段顺序（按步骤 sequence/id 保序去重）"""
        from ..models_checklist import UpgradeRecordStep
        steps = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(upgrade_id=upgrade_id), user
        ).order_by('sequence', 'id')
        order = []
        for s in steps:
            ph = (s.phase or '').strip()
            if ph and ph not in order:
                order.append(ph)
        return order

    @staticmethod
    def _mark_phase_done_outcome(upgrade_id, phase, outcome):
        """把指定阶段最近一条 outcome=done 的 phase_done 改为指定 outcome。"""
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=upgrade_id, action=ACTION_PHASE_DONE,
            phase=phase, outcome=OUTCOME_DONE
        ).order_by('-event_seq', '-id').first()
        if log:
            log.outcome = outcome
            log.save(update_fields=['outcome'])

    @staticmethod
    def _mark_rollback_phases_failed(upgrade_id, target_phase, user):
        """回退到 target_phase：把 target_phase 及其后所有阶段的 done phase_done 改 failed。

        阶段顺序由该升级的步骤阶段顺序决定（保序去重）。
        """
        order = StatusLogService._ordered_phases(upgrade_id, user)
        try:
            idx = order.index(target_phase)
        except ValueError:
            idx = 0
        affected = order[idx:]
        if affected:
            UpgradeStatusLog.objects.filter(
                upgrade_id=upgrade_id, action=ACTION_PHASE_DONE,
                phase__in=affected, outcome=OUTCOME_DONE
            ).update(outcome=OUTCOME_FAILED)

    @staticmethod
    def _reset_steps_for_rollback(upgrade_id, target_phase, user):
        """回退到 target_phase：把 target_phase 及其后所有阶段的步骤重置为 pending。

        与 _mark_rollback_phases_failed 配合：phase_done 标 failed + 步骤重置，
        使该阶段重新变为 current 待执行。
        """
        order = StatusLogService._ordered_phases(upgrade_id, user)
        try:
            idx = order.index(target_phase)
        except ValueError:
            idx = 0
        affected = order[idx:]
        if affected:
            from ..models_checklist import UpgradeRecordStep
            apply_tenant_filter(
                UpgradeRecordStep.objects.filter(
                    upgrade_id=upgrade_id, phase__in=affected
                ), user
            ).update(
                status='pending', completed_by='', completed_at=None, remark=''
            )
            logger.info(f'[Upgrade] 回退重置步骤 upgrade_id={upgrade_id} phases={affected}')

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
        """获取异常事件动作选项（供前端 Dropdown，phase_done 由步骤自动触发不在此列）。

        Returns:
            list: [{value, label, color}, ...]
        """
        from ..models_status_log import ACTION_COLOR_MAP
        exception_actions = [
            ACTION_PAUSE, ACTION_RESUME, ACTION_TEST_FAIL, ACTION_ROLLBACK, ACTION_COMPLETE
        ]
        action_text = {code: text for code, text in ACTION_CHOICES}
        return [
            {
                'value': code,
                'label': action_text.get(code, code),
                'color': ACTION_COLOR_MAP.get(code, 'default'),
            }
            for code in exception_actions
        ]

    @staticmethod
    def get_rollback_targets(upgrade_id, user):
        """获取可回退的阶段列表（从该升级的步骤阶段动态生成，保序去重）。

        Returns:
            list: [{value, label}, ...]
        """
        order = StatusLogService._ordered_phases(upgrade_id, user)
        return [{'value': ph, 'label': ph} for ph in order]
