# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""从某阶段重新执行服务（原"回退到某阶段"的明确化）

含义：目标阶段及后续阶段重新执行，前面阶段保持原状。只重置工作清单，
不代表软件/配置/数据库已经实际回滚。

- 预览（preview）与执行（execute）使用同一阶段顺序（步骤 sequence 保序去重）
  与同一统计口径，后端执行时重新校验，不信任前端预览；
- 后续已完成阶段不得静默清空：执行时必须显式选择"同时重新执行"或
  "保留并确认有效（必填理由）"，选择与理由写入事件 detail；
- 覆盖范围内的失败待处理单随重新执行解除阻塞（resolved，写入事件 detail）；
- 本来待执行的步骤不重复重置、不产生虚假快照；
- 被重置步骤所在阶段的旧 phase_done 完成记录随之失效（时间/操作人保留原样），
  重新完成后会新写 phase_done（幂等检查只认 outcome=done）。
"""
import logging
from django.db import transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


class RedoFromService:
    """从某阶段重新执行"""

    # 影响范围计算（预览与执行共用；口径与前端确认预览一致）
    @staticmethod
    def _build_scope(upgrade_id, user, target_phase):
        """计算影响范围。

        Returns:
            tuple: (scope_dict, error)。scope_dict:
              order, affected, phase_steps: [{name, steps, to_reset, pending_count}],
              selected_count, later_completed_phases, pending_failures
        """
        from ..models_checklist import UpgradeRecordStep
        from ..models_failure import UpgradeFailureHandling, FAILURE_PENDING
        from .status_log_service import StatusLogService

        order = StatusLogService._ordered_phases(upgrade_id, user)
        if target_phase not in order:
            return None, f'目标阶段 [{target_phase}] 不存在，请从该记录的步骤阶段中选择'
        idx = order.index(target_phase)
        affected = order[idx:]

        steps = list(apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, upgrade_id=upgrade_id),
            user
        ).order_by('sequence', 'id'))
        steps_by_phase = {name: [] for name in affected}
        for s in steps:
            if (s.phase or '') in steps_by_phase:
                steps_by_phase[s.phase].append(s)

        phase_items = []
        for name in affected:
            ss = steps_by_phase[name]
            phase_items.append({
                'name': name,
                'total': len(ss),
                'to_reset': [s for s in ss if s.status != 'pending'],
                'pending_count': sum(1 for s in ss if s.status == 'pending'),
            })

        pending_failures = list(apply_tenant_filter(
            UpgradeFailureHandling.objects.filter(
                upgrade_id=upgrade_id, status=FAILURE_PENDING,
                phase__in=affected), user
        ).order_by('id'))

        return {
            'order': order,
            'affected': affected,
            'phase_items': phase_items,
            'selected_count': sum(len(p['to_reset']) for p in phase_items),
            'later_completed_phases': [p['name'] for p in phase_items[1:] if p['to_reset']],
            'pending_failures': pending_failures,
        }, None

    @staticmethod
    def preview(upgrade_id, user, target_phase):
        """预览影响范围（确认窗口渲染真实数据；执行时后端重新校验）

        Returns:
            tuple: (dict, error)
        """
        scope, error = RedoFromService._build_scope(upgrade_id, user, target_phase)
        if error:
            return None, error
        return {
            'target_phase': target_phase,
            'phases': [
                {'name': p['name'], 'total': p['total'],
                 'to_reset': len(p['to_reset']), 'pending': p['pending_count']}
                for p in scope['phase_items']
            ],
            'selected_count': scope['selected_count'],
            'later_completed_phases': scope['later_completed_phases'],
            'pending_failures': [
                {'id': f.id, 'phase': f.phase} for f in scope['pending_failures']
            ],
        }, None

    @staticmethod
    def _validate_execute(scope, later_action, later_reason):
        """执行前校验：后续结果决定与理由。返回错误消息或 None。"""
        if later_action not in (None, 'redo', 'keep'):
            return '无效的后续结果处理方式，仅支持 redo/keep'
        later_completed = scope['later_completed_phases']
        if later_completed and later_action is None:
            return (
                f'存在后续已完成阶段（{"、".join(later_completed)}），'
                f'请选择"同时重新执行"或"保留并确认有效"')
        if later_completed and later_action == 'keep' and not (later_reason or '').strip():
            return '保留后续已完成结果时，请填写确认继续有效的理由'
        return None

    @staticmethod
    def _collect_reset_scope(scope, target_phase, later_action):
        """按 later_action 收集要重置的步骤与阶段（目标阶段恒重置）。

        Returns:
            tuple: (to_reset_steps, reset_phases)
        """
        to_reset = []
        reset_phases = []
        for p in scope['phase_items']:
            if p['name'] == target_phase or later_action == 'redo':
                to_reset.extend(p['to_reset'])
                if p['to_reset']:
                    reset_phases.append(p['name'])
        return to_reset, reset_phases

    @staticmethod
    def _reset_steps_and_fail_phase_done(upgrade_id, user, to_reset, reset_phases):
        """重置步骤为待执行，并使被重置阶段的旧 done phase_done 失效。

        Returns:
            list[dict]: 步骤快照（id/标题/阶段/变更前后状态）
        """
        from ..models_status_log import UpgradeStatusLog, ACTION_PHASE_DONE, OUTCOME_DONE, OUTCOME_FAILED
        snapshots = []
        for s in to_reset:
            snapshots.append({
                'id': s.id, 'title': s.title, 'phase': s.phase or '',
                'from_status': s.status, 'to_status': 'pending',
            })
            s.reset_status()
        if reset_phases:
            apply_tenant_filter(
                UpgradeStatusLog.objects.filter(
                    upgrade_id=upgrade_id, action=ACTION_PHASE_DONE,
                    phase__in=reset_phases, outcome=OUTCOME_DONE),
                user
            ).update(outcome=OUTCOME_FAILED)
        return snapshots

    @staticmethod
    def execute(upgrade_id, user, target_phase, later_action=None, later_reason='', note=''):
        """执行重新执行：重置范围内已执行的步骤，写 rollback 摘要事件。

        - later_action 必须显式给出（存在后续已完成阶段时）：
          'redo'=同时重新执行后续阶段；'keep'=保留后续结果（later_reason 必填）；
        - 取消或未完成确认不会进入本方法（前端控制），缺少确认参数同样拒绝。

        Returns:
            tuple: (log, error)
        """
        from ..models import UpgradeRecord
        from ..models_failure import FAILURE_RESOLVED
        from ..models_status_log import ACTION_ROLLBACK
        from .status_log_service import StatusLogService
        from .step_service import RecordStepService

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    UpgradeRecord.objects.select_for_update().filter(pk=upgrade_id), user
                ).first()
                if record is None:
                    return None, '升级表单不存在或无权限访问'

                # 后端重新计算影响范围（不信任前端预览）
                scope, error = RedoFromService._build_scope(upgrade_id, user, target_phase)
                if error:
                    return None, error
                error = RedoFromService._validate_execute(scope, later_action, later_reason)
                if error:
                    return None, error

                to_reset, reset_phases = RedoFromService._collect_reset_scope(
                    scope, target_phase, later_action)
                pending_failures = scope['pending_failures']
                if not to_reset and not pending_failures:
                    return None, '所选范围内没有已执行的步骤，无需重新执行'

                snapshots = RedoFromService._reset_steps_and_fail_phase_done(
                    upgrade_id, user, to_reset, reset_phases)

                # 覆盖范围内的失败待处理单解除阻塞
                failures_resolved = RedoFromService._resolve_pending_failures(
                    pending_failures, target_phase)

                selected_count = sum(
                    len(p['to_reset']) for p in scope['phase_items']
                    if p['name'] == target_phase or later_action == 'redo')
                log, err = StatusLogService._persist_log(
                    upgrade_id=upgrade_id, user=user, action=ACTION_ROLLBACK,
                    remark=note or '', target_action=target_phase, is_override=False,
                    from_status=record.status, to_status='已回退',
                    target_main_status='已回退', needs_update=True, record=record,
                    phase='', detail={
                        'target_phase': target_phase,
                        'selected_count': selected_count,
                        'reset_count': len(to_reset),
                        'later_action': later_action,
                        'later_reason': (later_reason or '').strip(),
                        'later_completed_phases': scope['later_completed_phases'],
                        'note': note or '',
                        'steps': snapshots,
                        'failures_resolved': failures_resolved,
                    })
                if err:
                    raise ValueError(err)

                RecordStepService._check_and_update_record_status(upgrade_id, user)

            logger.info(
                f'[Upgrade] 从阶段重新执行 upgrade_id={upgrade_id} target={target_phase} '
                f'reset={len(to_reset)} later={later_action} 用户={user.username}')
            return log, None
        except ValueError as e:
            return None, str(e)
        except Exception as e:
            logger.error(f'[Upgrade] 重新执行失败: {e}', exc_info=True)
            return None, f'重新执行失败: {str(e)}'

    @staticmethod
    def _resolve_pending_failures(pending_failures, target_phase):
        """覆盖范围内的失败待处理单结案并返回摘要（写入事件 detail）"""
        from ..models_failure import FAILURE_RESOLVED
        now = timezone.now()
        failures_resolved = []
        for f in pending_failures:
            f.status = FAILURE_RESOLVED
            f.resolved_at = now
            f.resolved_note = f'包含在「从【{target_phase}】重新执行」范围内'
            f.save(update_fields=['status', 'resolved_at', 'resolved_note'])
            failures_resolved.append({'id': f.id, 'phase': f.phase})
        return failures_resolved
