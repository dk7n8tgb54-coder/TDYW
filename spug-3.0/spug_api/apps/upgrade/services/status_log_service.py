# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""升级状态日志服务 - 记录/列表/删除 + 主表 status 联动 + 流程顺序校验"""
import json
import logging
from django.db import transaction, models
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter
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
        import json
        target = log.target_action or ''
        # detail 为 JSON 文本；解析失败/为空时返回 None（旧数据无 detail，正常读取）
        detail = None
        if getattr(log, 'detail', ''):
            try:
                parsed = json.loads(log.detail)
                detail = parsed if isinstance(parsed, dict) else None
            except (ValueError, TypeError):
                detail = None
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
            'detail': detail,
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
                     needs_update, record, phase='', detail=None):
        """事务内写入状态日志并按需联动主表 status。

        对升级记录行加 select_for_update 锁，串行化同一升级的事件写入
        （event_seq 取 max+1 的并发竞态防护）。detail 为结构化明细 dict，
        以 JSON 文本落库（步骤快照/数量口径等，供前端展开与追溯）。

        Returns:
            tuple: (log, error_message)。error_message 为 None 表示成功。
        """
        import json
        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with transaction.atomic():
                # 0. 锁升级记录行（串行化 event_seq 分配与主表状态联动）
                if record is not None:
                    locked = type(record).objects.select_for_update().filter(
                        pk=record.pk).first()
                    if locked is not None:
                        record = locked
                # 1. 计算 event_seq（锁内取最大值 + 1）
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
                    detail=json.dumps(detail, ensure_ascii=False) if detail else '',
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
    def _validate_add_log(action, record, target_action, phase, user):
        """add_log 入参/状态校验。返回错误消息或 None。"""
        from .failure_service import FailureService

        exception_actions = {
            ACTION_PAUSE, ACTION_RESUME, ACTION_TEST_FAIL, ACTION_ROLLBACK, ACTION_COMPLETE
        }
        if action not in exception_actions:
            return f'无效的动作类型，支持：{", ".join(sorted(exception_actions))}'
        if action in (ACTION_PAUSE, ACTION_RESUME):
            return '暂停/继续操作已下线：无需提交暂停状态，可直接继续执行步骤'
        # 升级完成门禁：存在失败待处理时不能标记完成
        if action == ACTION_COMPLETE and FailureService.has_pending_failure(
                record.pk, user):
            return '存在未处理完的失败阶段，请先在"处理失败"中完成重做或更正'
        if action == ACTION_ROLLBACK and not target_action:
            return '回退操作必须指定"回退到"哪个阶段'
        if action == ACTION_TEST_FAIL and not phase:
            return '测试失败必须指定失败的阶段'
        if action == ACTION_ROLLBACK:
            # 回退目标必须是该记录现存步骤的阶段（按步骤顺序），
            # 避免未知目标触发"回退到开头"式全量重置
            phases = StatusLogService._ordered_phases(record.pk, user)
            if phases and target_action not in phases:
                return f'回退目标阶段 [{target_action}] 不存在，请从该记录的步骤阶段中选择'
        return None

    @staticmethod
    def add_log(upgrade_id, user, action, remark='', target_action='', is_override=False, phase=''):
        """记录一条异常事件状态日志，并联动主表 status。

        正常的阶段完成（phase_done）由 check_phase_completion 自动写入，不走此方法。
        此方法仅处理异常事件：test_fail/rollback/complete。
        pause/resume 已下线：新写入返回业务错误（旧历史保留展示，不伪造恢复事件）。

        Args:
            upgrade_id: 升级表单ID
            user: 当前请求用户
            action: 异常事件动作（test_fail/rollback/complete）
            remark: 备注（test_fail 时为失败原因，必填）
            target_action: 重新执行目标阶段名（仅 rollback 时必填）
            is_override: 兼容旧参数，新逻辑不再使用顺序校验
            phase: 失败阶段名（仅 test_fail 时必填）

        Returns:
            tuple: (log, error)
        """
        from ..models import UpgradeRecord
        from .failure_service import FailureService
        from .step_service import RecordStepService

        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if record is None:
            return None, '升级表单不存在或无权限访问'

        error = StatusLogService._validate_add_log(
            action, record, target_action, phase, user)
        if error:
            return None, error

        # 旧接口（部署中的前端）rollback 保持原行为：目标及后续阶段步骤重置、
        # 原 phase_done 完成记录失效。前端已切换到 redo-execute 新端点。
        try:
            with transaction.atomic():
                if action == ACTION_TEST_FAIL:
                    # 失败以独立失败单+事件表达：不清步骤、不修改过去完成事件
                    failure, log, err = FailureService.record_failure(
                        upgrade_id, user, phase, remark)
                    if err:
                        return None, err
                    return log, None

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

                if action == ACTION_ROLLBACK:
                    StatusLogService._mark_rollback_phases_failed(upgrade_id, target_action, user)
                    StatusLogService._reset_steps_for_rollback(upgrade_id, target_action, user)
                    RecordStepService._check_and_update_record_status(upgrade_id, user)

            return log, None
        except Exception as e:
            logger.error(f'[Upgrade] 记录状态日志失败: {e}', exc_info=True)
            return None, f'记录状态日志失败: {str(e)}'

    @staticmethod
    def check_phase_completion(upgrade_id, user, phase):
        """检查指定阶段是否全部完成，若是则自动写 phase_done 时间线。

        由步骤 mark_completed/mark_skipped 后调用。
        - phase 为空跳过（无阶段不触发）
        - 该阶段所有步骤 completed/skipped → 写 phase_done（幂等：已有 done 则不重复）
        - 该阶段存在未结失败单时随完成自动结案（resolved），id 记入 phase_done detail
        """
        if not phase:
            return
        from ..models_checklist import UpgradeRecordStep
        from .failure_service import FailureService
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
        # 失败阶段重新完成：结案未结失败单（redoing/pending → resolved）
        resolved_ids = FailureService.resolve_for_phase(
            upgrade_id, phase, user, note='失败阶段重新完成，失败处理闭环')
        detail = {'resolved_failure_ids': resolved_ids} if resolved_ids else None
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
            detail=json.dumps(detail, ensure_ascii=False) if detail else '',
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
    def delete_log(log_id, user):
        """历史事件不可删除（2026-10 追加式历史改造）。

        时间线为独立、可追溯的操作事件：普通入口禁止改写历史，
        更正通过追加事件表达（如更正失败记录）。旧接口保留并统一拒绝。

        Returns:
            str: 错误消息（本方法恒拒绝）
        """
        log = apply_tenant_filter(
            UpgradeStatusLog.objects.all(), user
        ).filter(pk=log_id).first()
        if log is None:
            return '日志不存在或无权限删除'
        return '历史事件不可删除：状态时间线为追加式记录，如需更正请通过相应的更正/重做流程'

    @staticmethod
    def get_action_options():
        """获取异常事件动作选项（供前端 Dropdown，phase_done 由步骤自动触发不在此列）。

        pause/resume 已下线（2026-10），不再出现在选项中。

        Returns:
            list: [{value, label, color}, ...]
        """
        from ..models_status_log import ACTION_COLOR_MAP
        exception_actions = [
            ACTION_TEST_FAIL, ACTION_ROLLBACK, ACTION_COMPLETE
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
