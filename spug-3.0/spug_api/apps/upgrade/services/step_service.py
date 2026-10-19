# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级记录步骤服务 - 步骤执行状态管理
"""
import logging
from django.db import transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


class RecordStepService:
    """升级记录步骤服务"""

    @staticmethod
    def _check_and_update_record_status(upgrade_id, user):
        """检查步骤完成情况，自动更新升级记录状态

        规则：
        - 所有步骤都已完成/已跳过，且不存在失败待处理 → 自动将记录状态设为'已完成'
          （存在失败待处理时不自动完成，须先在"处理失败"中重做或更正）
        - 存在待执行步骤且记录状态为'已完成' → 回退为'处理中'
        - 无步骤时不自动变更状态
        """
        from ..models_checklist import UpgradeRecordStep
        from ..models import UpgradeRecord
        from ..constants import UpgradeStatus
        from .failure_service import FailureService

        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if not record:
            return

        steps = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, upgrade_id=upgrade_id), user
        )
        total = steps.count()
        if total == 0:
            return

        pending_count = steps.filter(status='pending').count()

        if pending_count == 0 and record.status != UpgradeStatus.COMPLETED:
            if FailureService.has_pending_failure(upgrade_id, user):
                logger.info(
                    f'[Upgrade] 升级表单 {record.title} 存在失败待处理，'
                    f'不自动完成（须先处理失败）')
                return
            # 所有步骤已执行完毕且无失败待处理，自动标记为已完成
            record.status = UpgradeStatus.COMPLETED
            record.updated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            record.updated_by = user
            record.save(update_fields=['status', 'updated_at', 'updated_by'])
            logger.info(f'[Upgrade] 升级表单 {record.title} 所有步骤已完成，自动更新状态为已完成')
        elif pending_count > 0 and record.status == UpgradeStatus.COMPLETED:
            # 有步骤被重置为待执行，回退状态为处理中
            record.status = UpgradeStatus.IN_PROGRESS
            record.updated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            record.updated_by = user
            record.save(update_fields=['status', 'updated_at', 'updated_by'])
            logger.info(f'[Upgrade] 升级表单 {record.title} 存在待执行步骤，回退状态为处理中')

    @staticmethod
    def get_record_steps(upgrade_id, user):
        """获取升级表单的步骤列表"""
        from ..models_checklist import UpgradeRecordStep

        steps = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, upgrade_id=upgrade_id), user
        ).order_by('sequence', 'id')

        return [
            {
                'id': s.id,
                'upgrade_id': s.upgrade_id,
                'checklist_id': s.checklist_id,
                'phase': s.phase,
                'title': s.title,
                'description': s.description,
                'sequence': s.sequence,
                'is_required': s.is_required,
                'status': s.status,
                'status_display': s.get_status_display(),
                'completed_by': s.completed_by,
                'completed_at': s.completed_at,
                'remark': s.remark,
                'created_at': s.created_at,
            }
            for s in steps
        ]

    @staticmethod
    def get_record_step_stats(upgrade_id, user):
        """获取升级表单的步骤统计"""
        from ..models_checklist import UpgradeRecordStep

        steps = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, upgrade_id=upgrade_id), user
        )

        total = steps.count()
        completed = steps.filter(status='completed').count()
        skipped = steps.filter(status='skipped').count()
        pending = steps.filter(status='pending').count()

        return {
            'total': total,
            'completed': completed,
            'skipped': skipped,
            'pending': pending,
            # 完成度与主表自动完成判定一致：completed/skipped 均视为已处理
            'progress': round((completed + skipped) / total * 100, 1) if total > 0 else 0,
        }

    @staticmethod
    def add_manual_step(upgrade_id, user, data):
        """手动添加步骤到升级表单"""
        from ..models_checklist import UpgradeRecordStep
        from ..models import UpgradeRecord

        # 校验升级表单
        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if not record:
            return None, '升级表单不存在或无权限'

        title = getattr(data, 'title', None)
        if not title:
            return None, '请输入步骤标题'

        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

        # 自动计算序号：取当前最大 sequence + 1（软删除步骤不再参与计数，
        # 避免与现存步骤序号重复）
        from django.db.models import Max
        max_seq = UpgradeRecordStep.objects.filter(
            is_deleted=False, upgrade_id=upgrade_id
        ).aggregate(max_seq=Max('sequence'))['max_seq'] or 0

        step = UpgradeRecordStep.objects.create(
            tenant_id=user.tenant_id,
            upgrade_id=upgrade_id,
            checklist_id=0,  # 手动添加
            phase=getattr(data, 'phase', '') or '',
            title=title,
            description=getattr(data, 'description', '') or '',
            sequence=getattr(data, 'sequence', None) or (max_seq + 1),
            is_required=getattr(data, 'is_required', True) if getattr(data, 'is_required', None) is not None else True,
        )

        # 新增待执行步骤后检查主表状态（已完成存在待执行步骤 → 回退处理中）
        RecordStepService._check_and_update_record_status(upgrade_id, user)

        return step, None

    @staticmethod
    def update_step_status(step_id, user, data):
        """更新步骤执行状态（complete/skip/reset）

        - 失败待处理（pending）阶段禁止普通完成/跳过，须先走"处理失败"；
        - 已是待执行的步骤重置拒绝（无状态变化，不制造虚假事件）；
        - 状态变更、阶段完成联动与步骤事件写入在同一事务，
          事件带步骤快照（id/标题/阶段/变更前后状态），锁升级记录行防并发覆盖。
        """
        from ..models_checklist import UpgradeRecordStep
        from ..models import UpgradeRecord
        from ..models_status_log import ACTION_STEP_DONE, ACTION_STEP_SKIP, ACTION_STEP_RESET
        from ..services.status_log_service import StatusLogService
        from ..services.failure_service import FailureService

        step = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, pk=step_id), user
        ).first()
        if not step:
            return None, '步骤不存在或无权限'

        action = getattr(data, 'action', None)
        remark = getattr(data, 'remark', '') or ''
        phase = step.phase or ''
        upgrade_id = step.upgrade_id

        if action not in ('complete', 'skip', 'reset'):
            return None, '无效操作，支持: complete/skip/reset'

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    UpgradeRecord.objects.select_for_update().filter(pk=upgrade_id), user
                ).first()
                if record is None:
                    return None, '升级表单不存在或无权限访问'

                # 事务内加锁重取步骤，防止并发下用过期状态覆盖
                locked_step = apply_tenant_filter(
                    UpgradeRecordStep.objects.select_for_update().filter(pk=step.pk), user
                ).first()
                if locked_step is None:
                    return None, '步骤不存在或无权限'
                step = locked_step

                blocked = FailureService.blocked_phases(upgrade_id, user)
                from_status = step.status
                if action == 'complete':
                    if phase in blocked:
                        return None, (f'阶段【{phase}】有未处理完的失败，'
                                      f'请先在"处理失败"中选择重做范围')
                    step.mark_completed(user, remark)
                    event_action = ACTION_STEP_DONE
                elif action == 'skip':
                    if phase in blocked:
                        return None, (f'阶段【{phase}】有未处理完的失败，'
                                      f'请先在"处理失败"中选择重做范围')
                    step.mark_skipped(user, remark)
                    event_action = ACTION_STEP_SKIP
                else:
                    if step.status == 'pending':
                        return None, '该步骤已是待执行状态，无需重置'
                    step.reset_status()
                    event_action = ACTION_STEP_RESET

                if action == 'reset':
                    StatusLogService.on_step_reset(upgrade_id, user, phase)
                else:
                    StatusLogService.check_phase_completion(upgrade_id, user, phase)

                StatusLogService._persist_log(
                    upgrade_id=upgrade_id, user=user, action=event_action,
                    remark=remark, target_action='', is_override=False,
                    from_status='', to_status='', target_main_status=None,
                    needs_update=False, record=record, phase=phase,
                    detail={'steps': [{
                        'id': step.id, 'title': step.title, 'phase': phase,
                        'from_status': from_status, 'to_status': step.status,
                    }]},
                )
                RecordStepService._check_and_update_record_status(upgrade_id, user)
            return step, None
        except Exception as e:
            logger.error(f'[Upgrade] 步骤操作失败: {e}', exc_info=True)
            return None, f'步骤操作失败: {str(e)}'

    @staticmethod
    def delete_step(step_id, user):
        """删除升级记录的步骤

        失败待处理阶段禁止删除步骤（保留失败发生时的现场，防止绕过失败处理）。
        """
        from ..models_checklist import UpgradeRecordStep
        from ..services.failure_service import FailureService

        step = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, pk=step_id), user
        ).first()
        if not step:
            return '步骤不存在或无权限'

        phase = step.phase or ''
        blocked = FailureService.blocked_phases(step.upgrade_id, user)
        if phase and phase in blocked:
            return (f'阶段【{phase}】有未处理完的失败，删除步骤会破坏失败现场，'
                    f'请先在"处理失败"中完成重做或更正')

        upgrade_id = step.upgrade_id
        from django.utils import timezone
        step.is_deleted = True
        step.deleted_at = timezone.now()
        step.save(update_fields=['is_deleted', 'deleted_at'])

        # 删除步骤后检查剩余步骤完成情况
        RecordStepService._check_and_update_record_status(upgrade_id, user)

        return None

    @staticmethod
    def _apply_batch_item(user, step, action, remark, blocked, done_events,
                          reset_snapshots, reset_phases, done_phases):
        """处理单条批量项并归类（事件由调用方统一写入）。

        - complete/skip：失败待处理阶段拒绝；逐条记 done_events；
        - reset：待执行步骤视为无变化跳过；其余记 reset_snapshots。

        Returns:
            str: 错误消息，None 表示成功
        """
        from ..models_status_log import ACTION_STEP_DONE, ACTION_STEP_SKIP
        phase = step.phase or ''
        from_status = step.status
        if action in ('complete', 'skip'):
            if phase and phase in blocked:
                return (f'批量更新失败: 阶段【{phase}】有未处理完的失败，'
                        f'请先在"处理失败"中选择重做范围')
            if action == 'complete':
                step.mark_completed(user, remark)
                done_events.append((step, from_status, ACTION_STEP_DONE, remark))
            else:
                step.mark_skipped(user, remark)
                done_events.append((step, from_status, ACTION_STEP_SKIP, remark))
            done_phases.add(phase)
        else:
            if step.status == 'pending':
                return None  # 无状态变化：不重复重置、不制造虚假事件
            reset_snapshots.append({
                'id': step.id, 'title': step.title, 'phase': phase,
                'from_status': from_status, 'to_status': 'pending',
            })
            step.reset_status()
            reset_phases.add(phase)
        return None

    @staticmethod
    def _persist_batch_events(user, record, upgrade_id, done_events, reset_snapshots):
        """批量事件写入：complete/skip 逐条 step_done/step_skip；
        reset 组合写一条摘要事件（detail.batch + 步骤快照，前端可展开）。"""
        from ..models_status_log import ACTION_STEP_RESET
        from ..services.status_log_service import StatusLogService

        for step, from_status, event_action, remark in done_events:
            StatusLogService._persist_log(
                upgrade_id=upgrade_id, user=user, action=event_action,
                remark=remark, target_action='', is_override=False,
                from_status='', to_status='', target_main_status=None,
                needs_update=False, record=record, phase=step.phase or '',
                detail={'steps': [{
                    'id': step.id, 'title': step.title,
                    'phase': step.phase or '',
                    'from_status': from_status, 'to_status': step.status,
                }]},
            )
        if reset_snapshots:
            StatusLogService._persist_log(
                upgrade_id=upgrade_id, user=user, action=ACTION_STEP_RESET,
                remark='批量重置', target_action='', is_override=False,
                from_status='', to_status='', target_main_status=None,
                needs_update=False, record=record,
                phase=reset_snapshots[0].get('phase', ''),
                detail={'steps': reset_snapshots, 'batch': True,
                        'reset_count': len(reset_snapshots)},
            )

    @staticmethod
    def batch_update_status(upgrade_id, user, steps_data):
        """批量更新步骤状态

        - 失败待处理阶段禁止 complete/skip（整体拒绝，不产生部分变更）；
        - reset 本来就是待执行的步骤视为无变化，跳过且不产生事件；
        - reset 组合写一条摘要事件（detail.steps 可展开受影响步骤）；
        - complete/skip 逐条写事件；全部变更与事件同事务。

        Args:
            upgrade_id: 升级表单ID
            user: 当前用户
            steps_data: list of {step_id, action, remark}
        """
        from ..models_checklist import UpgradeRecordStep
        from ..models import UpgradeRecord
        from ..models_status_log import ACTION_STEP_DONE, ACTION_STEP_RESET, ACTION_STEP_SKIP
        from ..services.status_log_service import StatusLogService
        from ..services.failure_service import FailureService

        # 预校验：任一无效 action 直接拒绝（与单步接口一致），不产生部分变更
        valid_actions = ('complete', 'skip', 'reset')
        for item in steps_data:
            action = (item or {}).get('action')
            if action not in valid_actions:
                return (f'批量更新失败: 无效操作 [{action}]，'
                        f'支持: {"/".join(valid_actions)}')

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    UpgradeRecord.objects.select_for_update().filter(pk=upgrade_id), user
                ).first()
                if record is None:
                    return '升级表单不存在或无权限'

                blocked = set(FailureService.blocked_phases(upgrade_id, user))
                done_events = []   # [(step, from_status, event_action, remark)]
                reset_snapshots = []
                reset_phases = set()
                done_phases = set()

                for item in steps_data:
                    step = apply_tenant_filter(
                        UpgradeRecordStep.objects.filter(
                            pk=item.get('step_id'), upgrade_id=upgrade_id, is_deleted=False
                        ), user
                    ).first()
                    if not step:
                        continue
                    error = RecordStepService._apply_batch_item(
                        user, step, item.get('action'), item.get('remark', '') or '',
                        blocked, done_events, reset_snapshots, reset_phases, done_phases)
                    if error:
                        return error

                for ph in reset_phases:
                    StatusLogService.on_step_reset(upgrade_id, user, ph)
                for ph in done_phases:
                    StatusLogService.check_phase_completion(upgrade_id, user, ph)

                RecordStepService._persist_batch_events(
                    user, record, upgrade_id, done_events, reset_snapshots)

                RecordStepService._check_and_update_record_status(upgrade_id, user)
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 批量更新步骤状态失败: {e}', exc_info=True)
            return f'批量更新失败: {str(e)}'

    @staticmethod
    def clear_record_steps(upgrade_id, user):
        """清空升级表单的所有步骤

        存在未结失败单（失败待处理/重做中）时拒绝：
        清空会丢失失败现场与重做进度，须先在"处理失败"中完成重做或更正。
        """
        from ..models_checklist import UpgradeRecordStep
        from ..models import UpgradeRecord
        from ..models_failure import FAILURE_UNRESOLVED_STATUSES

        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(is_deleted=False, pk=upgrade_id), user
        ).first()
        if not record:
            return '升级表单不存在或无权限'

        from ..models_failure import UpgradeFailureHandling
        unresolved = apply_tenant_filter(
            UpgradeFailureHandling.objects.filter(
                upgrade_id=upgrade_id, status__in=FAILURE_UNRESOLVED_STATUSES), user
        ).exists()
        if unresolved:
            return ('存在未处理完的失败记录，清空步骤会丢失失败现场与重做进度，'
                    '请先在"处理失败"中完成重做或更正')

        from django.utils import timezone
        now = timezone.now()
        apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, upgrade_id=upgrade_id), user
        ).update(is_deleted=True, deleted_at=now)
        return None
