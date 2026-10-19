# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""升级失败处理服务 - 标记失败/开始重做/更正失败/阶段完成解除

规则（2026-10 失败处理闭环改造）：
- 标记失败只建失败单+写 test_fail 事件：不清空步骤、不修改过去完成事件、保留失败现场；
- pending 失败阻塞该阶段普通完成/跳过与整体自动完成，强制走"处理失败"；
- 开始重做：明确选择重做范围（部分步骤/整个阶段），只重置所选的完成/跳过步骤，
  记录"选择数"与"实际重置数"，解除阻塞（redoing）；
- 该阶段重新完成（phase_done）时失败单自动 resolved；
- 更正失败：误标场景，填写原因追加更正事件，原失败事件保留；
- 所有状态迁移与事件写入同事务，对升级记录行加锁防并发覆盖/重复事件。
"""
import logging
from django.db import transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


def _now():
    return timezone.now()


class FailureService:
    """升级失败处理单服务"""

    # ---------------------------------------------------------------- 序列化
    @staticmethod
    def to_view(f):
        return {
            'id': f.id,
            'upgrade_id': f.upgrade_id,
            'phase': f.phase,
            'reason': f.reason or '',
            'status': f.status,
            'status_display': f.get_status_display(),
            'failed_by_name': f.failed_by_name or '',
            'failed_at': f.failed_at,
            'redo_selected_count': f.redo_selected_count,
            'redo_reset_count': f.redo_reset_count,
            'redo_by_name': f.redo_by_name or '',
            'redo_at': f.redo_at,
            'resolved_at': f.resolved_at,
            'resolved_note': f.resolved_note or '',
            'correct_reason': f.correct_reason or '',
            'correct_by_name': f.correct_by_name or '',
            'correct_at': f.correct_at,
            'created_at': f.created_at,
        }

    @staticmethod
    def get_failures(upgrade_id, user):
        """失败单列表（id 倒序，前端展示用）"""
        from ..models_failure import UpgradeFailureHandling
        qs = apply_tenant_filter(
            UpgradeFailureHandling.objects.filter(upgrade_id=upgrade_id), user
        ).order_by('-id')
        return [FailureService.to_view(f) for f in qs]

    # ---------------------------------------------------------------- 查询门禁
    @staticmethod
    def _unresolved_qs(upgrade_id, user):
        from ..models_failure import UpgradeFailureHandling, FAILURE_UNRESOLVED_STATUSES
        return apply_tenant_filter(
            UpgradeFailureHandling.objects.filter(
                upgrade_id=upgrade_id, status__in=FAILURE_UNRESOLVED_STATUSES), user
        )

    @staticmethod
    def blocked_phases(upgrade_id, user):
        """失败待处理（pending）的阶段名列表：这些阶段禁止普通完成/跳过与删除步骤"""
        return sorted(set(
            FailureService._unresolved_qs(upgrade_id, user)
            .filter(status='pending').values_list('phase', flat=True)
        ))

    @staticmethod
    def has_pending_failure(upgrade_id, user):
        """是否存在失败待处理（pending）——整体自动完成/手动完成门禁"""
        return FailureService._unresolved_qs(upgrade_id, user).filter(
            status='pending').exists()

    # ---------------------------------------------------------------- 标记失败
    @staticmethod
    def record_failure(upgrade_id, user, phase, reason):
        """标记阶段失败：建失败单 + 写 test_fail 事件。

        不清空步骤、不修改过去的完成事件（失败以独立单据与事件表达）。
        同阶段已有未结失败单时拒绝（防重复提交产生重复失败）。

        Returns:
            tuple: (failure, log, error)
        """
        from ..models import UpgradeRecord
        from ..models_failure import (
            UpgradeFailureHandling, FAILURE_PENDING,
        )
        from ..models_status_log import ACTION_TEST_FAIL
        from .status_log_service import StatusLogService

        phase = (phase or '').strip()
        if not phase:
            return None, None, '请指定失败阶段'
        if not (reason or '').strip():
            return None, None, '请填写失败原因'

        # 阶段顺序来自步骤数据（不根据名称猜测依赖）
        if phase not in StatusLogService._ordered_phases(upgrade_id, user):
            return None, None, f'失败阶段 [{phase}] 不存在，请从该记录的步骤阶段中选择'

        try:
            with transaction.atomic():
                # 锁升级记录行：串行化同一升级的失败/事件写入，防并发重复
                record = apply_tenant_filter(
                    UpgradeRecord.objects.select_for_update().filter(pk=upgrade_id), user
                ).first()
                if record is None:
                    return None, None, '升级表单不存在或无权限访问'

                exists = FailureService._unresolved_qs(upgrade_id, user).filter(
                    phase=phase).exists()
                if exists:
                    return None, None, f'阶段 [{phase}] 已有未处理完的失败记录，请先处理'

                now = _now()
                failure = UpgradeFailureHandling.objects.create(
                    tenant_id=getattr(user, 'tenant_id', ''),
                    upgrade_id=upgrade_id,
                    phase=phase,
                    reason=reason.strip(),
                    status=FAILURE_PENDING,
                    failed_by_name=user.nickname or user.username,
                    failed_at=now,
                )
                log, err = StatusLogService._persist_log(
                    upgrade_id=upgrade_id, user=user, action=ACTION_TEST_FAIL,
                    remark=reason.strip(), target_action='', is_override=False,
                    from_status=record.status, to_status=record.status,
                    target_main_status=None, needs_update=False, record=record,
                    phase=phase, detail={'failure_id': failure.id},
                )
                if err:
                    raise ValueError(err)
            logger.info(
                f'[Upgrade] 阶段失败待处理 upgrade_id={upgrade_id} phase={phase} '
                f'failure_id={failure.id} 用户={user.username}')
            return failure, log, None
        except ValueError as e:
            return None, None, str(e)
        except Exception as e:
            logger.error(f'[Upgrade] 标记失败失败: {e}', exc_info=True)
            return None, None, f'标记失败失败: {str(e)}'

    # ---------------------------------------------------------------- 开始重做
    @staticmethod
    def _resolve_redo_selection(steps, step_ids, all_steps):
        """解析重做范围选择。

        Returns:
            tuple: (selection, error)
        """
        if all_steps:
            return steps, None
        id_set = set(step_ids or [])
        if not id_set:
            return None, '请选择需要重新执行的步骤'
        selection = [s for s in steps if s.id in id_set]
        if len(selection) != len(id_set):
            return None, '所选步骤中包含不属于该失败阶段的步骤'
        return selection, None

    @staticmethod
    def start_redo(upgrade_id, failure_id, user, step_ids=None, all_steps=False, note=''):
        """开始重做：选定重做范围并重置所选的完成/跳过步骤，解除失败阻塞。

        - 选择数（所选步骤总数）与实际重置数（完成/跳过→待执行）分开记录；
        - 本来待执行的步骤不重复重置、不产生虚假快照；
        - 全部所选步骤均为待执行时拒绝（无状态变化）。

        Returns:
            tuple: (result_dict, error)
        """
        from ..models import UpgradeRecord
        from ..models_checklist import UpgradeRecordStep
        from ..models_failure import (
            UpgradeFailureHandling, FAILURE_PENDING, FAILURE_REDOING,
        )
        from ..models_status_log import ACTION_REDO_START
        from .step_service import RecordStepService
        from .status_log_service import StatusLogService

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    UpgradeRecord.objects.select_for_update().filter(pk=upgrade_id), user
                ).first()
                if record is None:
                    return None, '升级表单不存在或无权限访问'

                failure = apply_tenant_filter(
                    UpgradeFailureHandling.objects.select_for_update().filter(
                        pk=failure_id, upgrade_id=upgrade_id), user
                ).first()
                if failure is None:
                    return None, '失败记录不存在或无权限访问'
                if failure.status == FAILURE_REDOING:
                    return None, '该失败已进入重做，请继续完成重做步骤'
                if failure.status != FAILURE_PENDING:
                    return None, '该失败记录已结案，无需重做'

                steps = list(apply_tenant_filter(
                    UpgradeRecordStep.objects.filter(
                        is_deleted=False, upgrade_id=upgrade_id, phase=failure.phase),
                    user
                ).order_by('sequence', 'id'))
                if not steps:
                    return None, '该阶段没有步骤，无法重做'

                selection, error = FailureService._resolve_redo_selection(
                    steps, step_ids, all_steps)
                if error:
                    return None, error

                to_reset = [s for s in selection if s.status != 'pending']
                if not to_reset:
                    return None, '所选步骤均为待执行，无需重做，请勾选已完成或已跳过的步骤'

                snapshots = FailureService._reset_selection(
                    upgrade_id, user, failure, to_reset)

                now = _now()
                failure.status = FAILURE_REDOING
                failure.redo_selected_count = len(selection)
                failure.redo_reset_count = len(to_reset)
                failure.redo_by_name = user.nickname or user.username
                failure.redo_at = now
                failure.save(update_fields=[
                    'status', 'redo_selected_count', 'redo_reset_count',
                    'redo_by_name', 'redo_at'])

                log, err = StatusLogService._persist_log(
                    upgrade_id=upgrade_id, user=user, action=ACTION_REDO_START,
                    remark='', target_action='', is_override=False,
                    from_status=record.status, to_status=record.status,
                    target_main_status=None, needs_update=False, record=record,
                    phase=failure.phase, detail={
                        'failure_id': failure.id,
                        'phase': failure.phase,
                        'selected_count': len(selection),
                        'reset_count': len(to_reset),
                        'note': note or '',
                        'steps': snapshots,
                    })
                if err:
                    raise ValueError(err)

                RecordStepService._check_and_update_record_status(upgrade_id, user)

            logger.info(
                f'[Upgrade] 开始重做 upgrade_id={upgrade_id} failure_id={failure.id} '
                f'选择={len(selection)} 实际重置={len(to_reset)} 用户={user.username}')
            return {
                'failure_id': failure.id,
                'selected_count': len(selection),
                'reset_count': len(to_reset),
            }, None
        except ValueError as e:
            return None, str(e)
        except Exception as e:
            logger.error(f'[Upgrade] 开始重做失败: {e}', exc_info=True)
            return None, f'开始重做失败: {str(e)}'

    @staticmethod
    def _reset_selection(upgrade_id, user, failure, to_reset):
        """重置所选步骤并使失败阶段原 done phase_done 失效（时间/操作人保留原样）。

        Returns:
            list[dict]: 步骤快照
        """
        from ..models_status_log import (
            UpgradeStatusLog, ACTION_PHASE_DONE, OUTCOME_DONE, OUTCOME_FAILED,
        )
        snapshots = []
        for s in to_reset:
            snapshots.append({
                'id': s.id, 'title': s.title, 'phase': s.phase or '',
                'from_status': s.status, 'to_status': 'pending',
            })
            s.reset_status()
        apply_tenant_filter(
            UpgradeStatusLog.objects.filter(
                upgrade_id=upgrade_id, action=ACTION_PHASE_DONE,
                phase=failure.phase, outcome=OUTCOME_DONE),
            user
        ).update(outcome=OUTCOME_FAILED)
        return snapshots

    # ---------------------------------------------------------------- 更正失败
    @staticmethod
    def correct_failure(upgrade_id, failure_id, user, reason):
        """更正失败记录（误标场景）：填写原因，追加更正事件，原失败事件保留。

        Returns:
            tuple: (log, error)
        """
        from ..models import UpgradeRecord
        from ..models_failure import (
            UpgradeFailureHandling, FAILURE_PENDING, FAILURE_REDOING, FAILURE_CORRECTED,
        )
        from .status_log_service import StatusLogService
        from ..models_status_log import ACTION_FAILURE_CORRECTED

        reason = (reason or '').strip()
        if not reason:
            return None, '请填写更正原因'

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    UpgradeRecord.objects.select_for_update().filter(pk=upgrade_id), user
                ).first()
                if record is None:
                    return None, '升级表单不存在或无权限访问'

                failure = apply_tenant_filter(
                    UpgradeFailureHandling.objects.select_for_update().filter(
                        pk=failure_id, upgrade_id=upgrade_id), user
                ).first()
                if failure is None:
                    return None, '失败记录不存在或无权限访问'
                if failure.status not in (FAILURE_PENDING, FAILURE_REDOING):
                    return None, '该失败记录已结案，无需更正'

                now = _now()
                failure.status = FAILURE_CORRECTED
                failure.correct_reason = reason
                failure.correct_by_name = user.nickname or user.username
                failure.correct_at = now
                failure.save(update_fields=[
                    'status', 'correct_reason', 'correct_by_name', 'correct_at'])

                log, err = StatusLogService._persist_log(
                    upgrade_id=upgrade_id, user=user, action=ACTION_FAILURE_CORRECTED,
                    remark=reason, target_action='', is_override=False,
                    from_status=record.status, to_status=record.status,
                    target_main_status=None, needs_update=False, record=record,
                    phase=failure.phase,
                    detail={'failure_id': failure.id, 'phase': failure.phase},
                )
                if err:
                    raise ValueError(err)

                from .step_service import RecordStepService
                RecordStepService._check_and_update_record_status(upgrade_id, user)
            logger.info(
                f'[Upgrade] 更正失败记录 upgrade_id={upgrade_id} '
                f'failure_id={failure.id} 用户={user.username}')
            return log, None
        except ValueError as e:
            return None, str(e)
        except Exception as e:
            logger.error(f'[Upgrade] 更正失败失败: {e}', exc_info=True)
            return None, f'更正失败失败: {str(e)}'

    # ---------------------------------------------------------------- 阶段完成解除
    @staticmethod
    def resolve_for_phase(upgrade_id, phase, user, note=''):
        """失败阶段重新完成时结案该阶段的未结失败单（由 check_phase_completion 调用）。

        Returns:
            list[int]: 结案的失败单 id 列表
        """
        from ..models_failure import (
            FAILURE_PENDING, FAILURE_REDOING, FAILURE_RESOLVED,
        )
        now = _now()
        unresolved = list(FailureService._unresolved_qs(upgrade_id, user).filter(phase=phase))
        for f in unresolved:
            f.status = FAILURE_RESOLVED
            f.resolved_at = now
            f.resolved_note = note or '失败阶段重新完成'
            f.save(update_fields=['status', 'resolved_at', 'resolved_note'])
        if unresolved:
            logger.info(
                f'[Upgrade] 失败单随阶段完成结案 upgrade_id={upgrade_id} phase={phase} '
                f'ids={[f.id for f in unresolved]}')
        return [f.id for f in unresolved]
