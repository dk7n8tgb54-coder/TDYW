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
        - 所有步骤都已完成/已跳过 → 自动将记录状态设为'已完成'
        - 存在待执行步骤且记录状态为'已完成' → 回退为'处理中'
        - 无步骤时不自动变更状态
        """
        from ..models_checklist import UpgradeRecordStep
        from ..models import UpgradeRecord
        from ..constants import UpgradeStatus

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
            # 所有步骤已执行完毕，自动标记为已完成
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
            'progress': round(completed / total * 100, 1) if total > 0 else 0,
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

        # 自动计算序号
        max_seq = UpgradeRecordStep.objects.filter(is_deleted=False, upgrade_id=upgrade_id).count()

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
        return step, None

    @staticmethod
    def update_step_status(step_id, user, data):
        """更新步骤执行状态"""
        from ..models_checklist import UpgradeRecordStep

        step = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, pk=step_id), user
        ).first()
        if not step:
            return None, '步骤不存在或无权限'

        action = getattr(data, 'action', None)
        remark = getattr(data, 'remark', '') or ''

        from ..services.status_log_service import StatusLogService
        phase = step.phase or ''
        if action == 'complete':
            step.mark_completed(user, remark)
            StatusLogService.check_phase_completion(step.upgrade_id, user, phase)
        elif action == 'reset':
            step.reset_status()
            StatusLogService.on_step_reset(step.upgrade_id, user, phase)
        else:
            return None, '无效操作，支持: complete/reset'

        # 检查是否所有步骤已完成，自动更新升级记录状态
        RecordStepService._check_and_update_record_status(step.upgrade_id, user)

        return step, None

    @staticmethod
    def delete_step(step_id, user):
        """删除升级记录的步骤"""
        from ..models_checklist import UpgradeRecordStep

        step = apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, pk=step_id), user
        ).first()
        if not step:
            return '步骤不存在或无权限'

        upgrade_id = step.upgrade_id
        from django.utils import timezone
        step.is_deleted = True
        step.deleted_at = timezone.now()
        step.save(update_fields=['is_deleted', 'deleted_at'])

        # 删除步骤后检查剩余步骤完成情况
        RecordStepService._check_and_update_record_status(upgrade_id, user)

        return None

    @staticmethod
    def batch_update_status(upgrade_id, user, steps_data):
        """批量更新步骤状态

        Args:
            upgrade_id: 升级表单ID
            user: 当前用户
            steps_data: list of {step_id, action, remark}
        """
        from ..models_checklist import UpgradeRecordStep
        from ..services.status_log_service import StatusLogService
        affected = []  # [(phase, is_reset), ...]
        try:
            with transaction.atomic():
                for item in steps_data:
                    step_id = item.get('step_id')
                    action = item.get('action')
                    remark = item.get('remark', '')

                    step = apply_tenant_filter(
                        UpgradeRecordStep.objects.filter(
                            pk=step_id, upgrade_id=upgrade_id
                        ), user
                    ).first()
                    if not step:
                        continue

                    phase = step.phase or ''
                    if action == 'complete':
                        step.mark_completed(user, remark)
                        affected.append((phase, False))
                    elif action == 'reset':
                        step.reset_status()
                        affected.append((phase, True))

                # 状态日志写入在事务内，确保步骤状态与日志一致
                reset_phases = {ph for ph, is_reset in affected if is_reset}
                done_phases = {ph for ph, is_reset in affected if not is_reset}
                for ph in reset_phases:
                    StatusLogService.on_step_reset(upgrade_id, user, ph)
                for ph in done_phases:
                    StatusLogService.check_phase_completion(upgrade_id, user, ph)

            # 事务成功后检查是否所有步骤已完成，自动更新升级记录状态
            RecordStepService._check_and_update_record_status(upgrade_id, user)
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 批量更新步骤状态失败: {e}', exc_info=True)
            return f'批量更新失败: {str(e)}'

    @staticmethod
    def clear_record_steps(upgrade_id, user):
        """清空升级表单的所有步骤"""
        from ..models_checklist import UpgradeRecordStep
        from ..models import UpgradeRecord

        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(is_deleted=False, pk=upgrade_id), user
        ).first()
        if not record:
            return '升级表单不存在或无权限'

        from django.utils import timezone
        now = timezone.now()
        apply_tenant_filter(
            UpgradeRecordStep.objects.filter(is_deleted=False, upgrade_id=upgrade_id), user
        ).update(is_deleted=True, deleted_at=now)
        return None
