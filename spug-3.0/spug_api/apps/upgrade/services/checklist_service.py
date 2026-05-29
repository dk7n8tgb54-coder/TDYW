# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级步骤清单服务 - 清单模板 CRUD + 应用清单到升级表单
"""
import logging
from django.db import transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


class ChecklistService:
    """升级步骤清单服务"""

    @staticmethod
    def get_list(user):
        """获取清单列表（含步骤数量统计）"""
        from ..models_checklist import UpgradeChecklist, UpgradeChecklistStep

        checklists = apply_tenant_filter(
            UpgradeChecklist.objects.all(), user
        ).order_by('-is_default', 'name', '-id')

        result = []
        for cl in checklists:
            step_count = apply_tenant_filter(
                UpgradeChecklistStep.objects.filter(checklist_id=cl.id), user
            ).count()
            result.append({
                'id': cl.id,
                'name': cl.name,
                'description': cl.description,
                'is_default': cl.is_default,
                'step_count': step_count,
                'created_at': cl.created_at,
                'updated_at': cl.updated_at,
            })
        return result

    @staticmethod
    def get_detail(checklist_id, user):
        """获取清单详情（含步骤列表）"""
        from ..models_checklist import UpgradeChecklist, UpgradeChecklistStep

        checklist = apply_tenant_filter(
            UpgradeChecklist.objects.filter(pk=checklist_id), user
        ).first()
        if not checklist:
            return None, '清单不存在或无权限'

        steps = apply_tenant_filter(
            UpgradeChecklistStep.objects.filter(checklist_id=checklist_id), user
        ).order_by('sequence', 'id')

        return {
            'id': checklist.id,
            'name': checklist.name,
            'description': checklist.description,
            'is_default': checklist.is_default,
            'steps': [
                {
                    'id': s.id,
                    'title': s.title,
                    'description': s.description,
                    'sequence': s.sequence,
                    'is_required': s.is_required,
                }
                for s in steps
            ],
            'created_at': checklist.created_at,
            'updated_at': checklist.updated_at,
        }, None

    @staticmethod
    def create_checklist(user, data):
        """创建清单（含步骤）"""
        from ..models_checklist import UpgradeChecklist, UpgradeChecklistStep

        name = getattr(data, 'name', None)
        if not name:
            return None, '请输入清单名称'

        # 同租户内清单名称唯一
        if UpgradeChecklist.objects.filter(
            tenant_id=user.tenant_id, name=name
        ).exists():
            return None, f'清单名称 [{name}] 已存在'

        steps_data = getattr(data, 'steps', None) or []

        try:
            now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            with transaction.atomic():
                checklist = UpgradeChecklist.objects.create(
                    tenant_id=user.tenant_id,
                    name=name,
                    description=getattr(data, 'description', '') or '',
                    is_default=getattr(data, 'is_default', False) or False,
                    created_at=now_str,
                    created_by=user,
                )
                # 创建步骤
                for idx, step_item in enumerate(steps_data):
                    if isinstance(step_item, dict):
                        UpgradeChecklistStep.objects.create(
                            tenant_id=user.tenant_id,
                            checklist_id=checklist.id,
                            title=step_item.get('title', ''),
                            description=step_item.get('description', ''),
                            sequence=step_item.get('sequence', idx + 1),
                            is_required=step_item.get('is_required', True),
                            created_at=now_str,
                        )

            return checklist, None
        except Exception as e:
            logger.error(f'[Upgrade] 创建清单失败: {e}', exc_info=True)
            return None, f'创建清单失败: {str(e)}'

    @staticmethod
    def update_checklist(checklist_id, user, data):
        """更新清单基本信息"""
        from ..models_checklist import UpgradeChecklist

        checklist = apply_tenant_filter(
            UpgradeChecklist.objects.filter(pk=checklist_id), user
        ).first()
        if not checklist:
            return None, '清单不存在或无权限'

        # 名称唯一校验
        new_name = getattr(data, 'name', None)
        if new_name and new_name != checklist.name:
            if UpgradeChecklist.objects.filter(
                tenant_id=user.tenant_id, name=new_name
            ).exists():
                return None, f'清单名称 [{new_name}] 已存在'

        editable_fields = ['name', 'description', 'is_default']
        for field in editable_fields:
            value = getattr(data, field, None)
            if value is not None:
                setattr(checklist, field, value)

        checklist.updated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        checklist.save()

        return checklist, None

    @staticmethod
    def delete_checklist(checklist_id, user):
        """删除清单（级联删除步骤）"""
        from ..models_checklist import UpgradeChecklist, UpgradeChecklistStep

        checklist = apply_tenant_filter(
            UpgradeChecklist.objects.filter(pk=checklist_id), user
        ).first()
        if not checklist:
            return '清单不存在或无权限'

        try:
            with transaction.atomic():
                apply_tenant_filter(
                    UpgradeChecklistStep.objects.filter(checklist_id=checklist_id), user
                ).delete()
                checklist.delete()
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 删除清单失败: {e}', exc_info=True)
            return f'删除清单失败: {str(e)}'

    @staticmethod
    def add_step(checklist_id, user, data):
        """向清单添加步骤"""
        from ..models_checklist import UpgradeChecklist, UpgradeChecklistStep

        checklist = apply_tenant_filter(
            UpgradeChecklist.objects.filter(pk=checklist_id), user
        ).first()
        if not checklist:
            return None, '清单不存在或无权限'

        title = getattr(data, 'title', None)
        if not title:
            return None, '请输入步骤标题'

        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

        # 自动计算序号
        max_seq = apply_tenant_filter(
            UpgradeChecklistStep.objects.filter(checklist_id=checklist_id), user
        ).count()

        step = UpgradeChecklistStep.objects.create(
            tenant_id=user.tenant_id,
            checklist_id=checklist_id,
            title=title,
            description=getattr(data, 'description', '') or '',
            sequence=getattr(data, 'sequence', None) or (max_seq + 1),
            is_required=getattr(data, 'is_required', True) if getattr(data, 'is_required', None) is not None else True,
            created_at=now_str,
        )
        return step, None

    @staticmethod
    def update_step(step_id, user, data):
        """更新步骤"""
        from ..models_checklist import UpgradeChecklistStep

        step = apply_tenant_filter(
            UpgradeChecklistStep.objects.filter(pk=step_id), user
        ).first()
        if not step:
            return None, '步骤不存在或无权限'

        editable_fields = ['title', 'description', 'sequence', 'is_required']
        for field in editable_fields:
            value = getattr(data, field, None)
            if value is not None:
                setattr(step, field, value)

        step.save()
        return step, None

    @staticmethod
    def delete_step(step_id, user):
        """删除步骤"""
        from ..models_checklist import UpgradeChecklistStep

        step = apply_tenant_filter(
            UpgradeChecklistStep.objects.filter(pk=step_id), user
        ).first()
        if not step:
            return '步骤不存在或无权限'

        step.delete()
        return None

    @staticmethod
    def reorder_steps(checklist_id, user, step_ids):
        """重排步骤顺序"""
        from ..models_checklist import UpgradeChecklist, UpgradeChecklistStep

        checklist = apply_tenant_filter(
            UpgradeChecklist.objects.filter(pk=checklist_id), user
        ).first()
        if not checklist:
            return '清单不存在或无权限'

        try:
            with transaction.atomic():
                for idx, step_id in enumerate(step_ids, 1):
                    step = apply_tenant_filter(
                        UpgradeChecklistStep.objects.filter(pk=step_id, checklist_id=checklist_id), user
                    ).first()
                    if step:
                        step.sequence = idx
                        step.save(update_fields=['sequence'])
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 重排步骤失败: {e}', exc_info=True)
            return f'重排步骤失败: {str(e)}'

    @staticmethod
    def apply_to_record(checklist_id, upgrade_id, user):
        """将清单应用到升级表单（实例化步骤为 UpgradeRecordStep）

        Args:
            checklist_id: 清单ID
            upgrade_id: 升级表单ID
            user: 当前用户

        Returns:
            tuple: (created_count, error)
        """
        from ..models_checklist import UpgradeChecklist, UpgradeChecklistStep, UpgradeRecordStep
        from ..models import UpgradeRecord

        # 校验升级表单
        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if not record:
            return 0, '升级表单不存在或无权限'

        # 校验清单
        checklist = apply_tenant_filter(
            UpgradeChecklist.objects.filter(pk=checklist_id), user
        ).first()
        if not checklist:
            return 0, '清单不存在或无权限'

        # 获取清单步骤
        steps = apply_tenant_filter(
            UpgradeChecklistStep.objects.filter(checklist_id=checklist_id), user
        ).order_by('sequence', 'id')

        if not steps.exists():
            return 0, '该清单没有步骤'

        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            # 获取当前已有步骤最大序号
            max_seq = UpgradeRecordStep.objects.filter(
                upgrade_id=upgrade_id
            ).count()

            created = []
            with transaction.atomic():
                for idx, step in enumerate(steps, max_seq + 1):
                    record_step = UpgradeRecordStep.objects.create(
                        tenant_id=user.tenant_id,
                        upgrade_id=upgrade_id,
                        checklist_id=checklist_id,
                        title=step.title,
                        description=step.description,
                        sequence=idx,
                        is_required=step.is_required,
                        created_at=now_str,
                    )
                    created.append(record_step)

            return len(created), None
        except Exception as e:
            logger.error(f'[Upgrade] 应用清单失败: {e}', exc_info=True)
            return 0, f'应用清单失败: {str(e)}'
