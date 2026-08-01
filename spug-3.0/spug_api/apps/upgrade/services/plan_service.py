# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级方案服务 - 合并原「升级模板」与「步骤清单」能力

提供：
- 方案 CRUD（基本信息 + 预设步骤整体编辑）
- 应用方案到升级记录（实例化预设步骤为 UpgradeRecordStep）
- 步骤重排
"""
import logging
from django.db import transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


class PlanService:
    """升级方案服务"""

    # ========== 查询 ==========

    @staticmethod
    def get_list(user):
        """获取方案列表（含步骤数量）"""
        from ..models_template import UpgradeTemplate, UpgradePlanStep

        templates = apply_tenant_filter(
            UpgradeTemplate.objects.all(), user
        ).order_by('name', '-id')

        result = []
        for t in templates:
            step_count = apply_tenant_filter(
                UpgradePlanStep.objects.filter(template_id=t.id), user
            ).count()
            result.append({
                'id': t.id,
                'name': t.name,
                'description': t.description,
                'system': t.system,
                'upgrade_type': t.upgrade_type,
                'step_count': step_count,
                'created_at': t.created_at,
                'updated_at': t.updated_at,
            })
        return result

    @staticmethod
    def get_detail(plan_id, user):
        """获取方案详情（含预设步骤列表）"""
        from ..models_template import UpgradeTemplate, UpgradePlanStep

        template = apply_tenant_filter(
            UpgradeTemplate.objects.filter(pk=plan_id), user
        ).first()
        if not template:
            return None, '方案不存在或无权限'

        steps = apply_tenant_filter(
            UpgradePlanStep.objects.filter(template_id=plan_id), user
        ).order_by('sequence', 'id')

        return {
            'id': template.id,
            'name': template.name,
            'description': template.description,
            'system': template.system,
            'upgrade_type': template.upgrade_type,
            'steps': [
                {
                    'id': s.id,
                    'template_id': s.template_id,
                    'phase': s.phase,
                    'title': s.title,
                    'description': s.description,
                    'sequence': s.sequence,
                    'is_required': s.is_required,
                }
                for s in steps
            ],
            'created_at': template.created_at,
            'updated_at': template.updated_at,
        }, None

    # ========== 步骤批量创建辅助 ==========

    @staticmethod
    def _bulk_create_steps(template_id, tenant_id, steps_data, now_str):
        """批量创建预设步骤（跳过无标题项），返回创建数量"""
        from ..models_template import UpgradePlanStep
        created = 0
        for idx, step_item in enumerate(steps_data):
            if not isinstance(step_item, dict):
                continue
            title = (step_item.get('title') or '').strip()
            if not title:
                continue
            UpgradePlanStep.objects.create(
                tenant_id=tenant_id,
                template_id=template_id,
                phase=step_item.get('phase', '') or '',
                title=title,
                description=step_item.get('description', '') or '',
                sequence=idx + 1,
                is_required=step_item.get('is_required', True),
            )
            created += 1
        return created

    # ========== 创建 / 更新 / 删除 ==========

    @staticmethod
    def create_plan(user, data):
        """创建方案（基本信息 + 预设步骤）"""
        from ..models_template import UpgradeTemplate

        name = getattr(data, 'name', None)
        if not name:
            return None, '请输入方案名称'

        # 同租户内方案名称唯一
        if UpgradeTemplate.objects.filter(
            tenant_id=user.tenant_id, name=name
        ).exists():
            return None, f'方案名称 [{name}] 已存在'

        try:
            now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            with transaction.atomic():
                template = UpgradeTemplate.objects.create(
                    tenant_id=user.tenant_id,
                    name=name,
                    description=getattr(data, 'description', '') or '',
                    system=getattr(data, 'system', '') or '',
                    upgrade_type=getattr(data, 'upgrade_type', '') or '',
                    created_by=user,
                )
                steps_data = getattr(data, 'steps', None) or []
                PlanService._bulk_create_steps(template.id, user.tenant_id, steps_data, now_str)
            return template, None
        except Exception as e:
            logger.error(f'[Upgrade] 创建方案失败: {e}', exc_info=True)
            return None, f'创建方案失败: {str(e)}'

    @staticmethod
    def update_plan(plan_id, user, data):
        """更新方案（基本信息 + 整体替换预设步骤）

        步骤采用整体替换策略：删除原有步骤，按提交顺序重建。
        预设步骤无执行状态，替换安全。
        """
        from ..models_template import UpgradeTemplate, UpgradePlanStep

        template = apply_tenant_filter(
            UpgradeTemplate.objects.filter(pk=plan_id), user
        ).first()
        if not template:
            return None, '方案不存在或无权限'

        # 名称唯一校验
        new_name = getattr(data, 'name', None)
        if new_name and new_name != template.name:
            if UpgradeTemplate.objects.filter(
                tenant_id=user.tenant_id, name=new_name
            ).exists():
                return None, f'方案名称 [{new_name}] 已存在'

        steps_data = getattr(data, 'steps', None)

        try:
            now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            with transaction.atomic():
                editable_fields = ['name', 'description', 'system', 'upgrade_type']
                for field in editable_fields:
                    value = getattr(data, field, None)
                    if value is not None:
                        setattr(template, field, value)

                template.updated_at = now_str
                template.save(update_fields=['name', 'description', 'system', 'upgrade_type', 'updated_at'])

                # 若提交了 steps，则整体替换
                if steps_data is not None:
                    apply_tenant_filter(
                        UpgradePlanStep.objects.filter(template_id=plan_id), user
                    ).delete()
                    PlanService._bulk_create_steps(plan_id, user.tenant_id, steps_data, now_str)
            return template, None
        except Exception as e:
            logger.error(f'[Upgrade] 更新方案失败: {e}', exc_info=True)
            return None, f'更新方案失败: {str(e)}'

    @staticmethod
    def delete_plan(plan_id, user):
        """删除方案（级联删除预设步骤）"""
        from ..models_template import UpgradeTemplate, UpgradePlanStep

        template = apply_tenant_filter(
            UpgradeTemplate.objects.filter(pk=plan_id), user
        ).first()
        if not template:
            return '方案不存在或无权限'

        try:
            with transaction.atomic():
                apply_tenant_filter(
                    UpgradePlanStep.objects.filter(template_id=plan_id), user
                ).delete()
                template.delete()
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 删除方案失败: {e}', exc_info=True)
            return f'删除方案失败: {str(e)}'

    @staticmethod
    def reorder_steps(plan_id, user, step_ids):
        """重排方案预设步骤顺序"""
        from ..models_template import UpgradeTemplate, UpgradePlanStep

        template = apply_tenant_filter(
            UpgradeTemplate.objects.filter(pk=plan_id), user
        ).first()
        if not template:
            return '方案不存在或无权限'

        try:
            with transaction.atomic():
                for idx, step_id in enumerate(step_ids, 1):
                    step = apply_tenant_filter(
                        UpgradePlanStep.objects.filter(
                            pk=step_id, template_id=plan_id
                        ), user
                    ).first()
                    if step:
                        step.sequence = idx
                        step.save(update_fields=['sequence'])
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 重排方案步骤失败: {e}', exc_info=True)
            return f'重排步骤失败: {str(e)}'

    # ========== 应用到升级记录 ==========

    @staticmethod
    def apply_to_record(plan_id, upgrade_id, user, replace=False):
        """将方案预设步骤实例化到升级记录（创建 UpgradeRecordStep）

        Args:
            plan_id: 方案ID（UpgradeTemplate.id）
            upgrade_id: 升级表单ID
            user: 当前用户
            replace: 是否替换现有步骤（True=先清空再创建，False=追加）

        Returns:
            tuple: (result_dict, error)
                result_dict: {'created_count': int, 'deleted_count': int}
        """
        from ..models_template import UpgradeTemplate, UpgradePlanStep
        from ..models_checklist import UpgradeRecordStep
        from ..models import UpgradeRecord

        # 校验升级表单
        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(pk=upgrade_id), user
        ).first()
        if not record:
            return None, '升级表单不存在或无权限'

        # 校验方案
        template = apply_tenant_filter(
            UpgradeTemplate.objects.filter(pk=plan_id), user
        ).first()
        if not template:
            return None, '方案不存在或无权限'

        steps = apply_tenant_filter(
            UpgradePlanStep.objects.filter(template_id=plan_id), user
        ).order_by('sequence', 'id')

        if not steps.exists():
            return None, '该方案没有预设步骤'

        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            with transaction.atomic():
                deleted_count = 0

                if replace:
                    # 替换模式：软删除所有已有步骤（Manager 已自动过滤 is_deleted=False）
                    from django.utils import timezone as _tz
                    _now = _tz.now()
                    existing = UpgradeRecordStep.objects.filter(
                        upgrade_id=upgrade_id
                    )
                    deleted_count = existing.count()
                    existing.update(is_deleted=True, deleted_at=_now)
                    start_seq = 1
                else:
                    # 追加模式：接在已有步骤之后
                    start_seq = UpgradeRecordStep.objects.filter(
                        upgrade_id=upgrade_id
                    ).count() + 1

                created = []
                for idx, step in enumerate(steps, start_seq):
                    # checklist_id 字段复用，存来源方案ID（template_id）
                    record_step = UpgradeRecordStep.objects.create(
                        tenant_id=user.tenant_id,
                        upgrade_id=upgrade_id,
                        checklist_id=plan_id,
                        phase=step.phase,
                        title=step.title,
                        description=step.description,
                        sequence=idx,
                        is_required=step.is_required,
                    )
                    created.append(record_step)

            return {'created_count': len(created), 'deleted_count': deleted_count}, None
        except Exception as e:
            logger.error(f'[Upgrade] 应用方案失败: {e}', exc_info=True)
            return None, f'应用方案失败: {str(e)}'
