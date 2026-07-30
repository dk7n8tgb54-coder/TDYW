# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级表单服务 - 创建/更新/删除/列表/详情

当前模型使用 CharField 存储日期时间、IntegerField 存储关联ID。
"""
import logging
from django.db import transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter
from ..validators import RecordValidator
from ..serializers import UpgradeRecordSerializer
from ..constants import PRESET_SYSTEMS, UPGRADE_PHASES, RESULT_MILESTONES, STANDARD_FLOW_ORDER

logger = logging.getLogger(__name__)


class RecordService:
    """升级表单服务 - 对外统一门面"""

    @staticmethod
    def create_record(user, record_data):
        """创建升级表单

        Args:
            user: 当前请求用户
            record_data: 表单数据对象

        Returns:
            tuple: (record, error)
        """
        from ..models import UpgradeRecord

        # 1. 校验
        error = RecordValidator.validate_create(record_data, user)
        if error:
            return None, error

        try:
            with transaction.atomic():
                # 2. 创建主表
                now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

                # upgrade_time 转为字符串
                upgrade_time_val = getattr(record_data, 'upgrade_time', '')
                if hasattr(upgrade_time_val, 'strftime'):
                    upgrade_time_val = upgrade_time_val.strftime('%Y-%m-%d %H:%M:%S')

                record = UpgradeRecord.objects.create(
                    tenant_id=user.tenant_id,
                    title=getattr(record_data, 'title', '') or '',
                    system=record_data.system,
                    upgrade_type=record_data.upgrade_type,
                    upgrade_time=upgrade_time_val,
                    status=getattr(record_data, 'status', '处理中') or '处理中',
                    owner=record_data.owner,
                    upgrade_content=getattr(record_data, 'upgrade_content', '') or '',
                    impact_scope=getattr(record_data, 'impact_scope', '') or '',
                    risk_desc=getattr(record_data, 'risk_desc', '') or '',
                    rollback_plan=getattr(record_data, 'rollback_plan', '') or '',
                    created_at=now_str,
                    created_by=user,
                )

            return record, None

        except Exception as e:
            logger.error(f'[Upgrade] 创建升级表单失败: {e}', exc_info=True)
            return None, f'创建升级表单失败: {str(e)}'

    @staticmethod
    def update_record(record_id, user, data):
        """更新升级表单

        Args:
            record_id: 升级表单ID
            user: 当前请求用户
            data: 更新数据对象

        Returns:
            tuple: (record, error)
        """
        from ..models import UpgradeRecord

        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(is_deleted=False, pk=record_id), user
        ).first()
        if not record:
            return None, '升级表单不存在或无权限'

        # 校验
        error = RecordValidator.validate_update(record, data, user)
        if error:
            return None, error

        # 更新可编辑字段
        editable_fields = ['title', 'system', 'upgrade_type', 'status', 'owner',
                           'upgrade_content', 'impact_scope', 'risk_desc', 'rollback_plan']
        for field in editable_fields:
            value = getattr(data, field, None)
            if value is not None:
                setattr(record, field, value)

        # upgrade_time 特殊处理：datetime → 字符串
        upgrade_time = getattr(data, 'upgrade_time', None)
        if upgrade_time is not None:
            if hasattr(upgrade_time, 'strftime'):
                record.upgrade_time = upgrade_time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                record.upgrade_time = upgrade_time

        record.updated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        record.updated_by = user
        record.save()

        return record, None

    @staticmethod
    def delete_record(record_id, request):
        """删除升级表单

        联动处理：
        1. 软删除该表单下的所有附件（附件存于 evidence 通用表）
        2. 级联清理子表（UpgradeRecordStep / UpgradeStatusLog，二者用 IntegerField
           upgrade_id 关联主表，DB 不会自动级联，必须手动清理避免孤儿数据）
        3. 物理删除主表记录
        4. 写入删除审计日志（record_audit_event 标记 request._audit_handled，
           避免中间件重复记录）

        Args:
            record_id: 升级表单ID
            request: 当前请求对象（用于权限过滤与审计日志）

        Returns:
            str: 错误消息，None 表示成功
        """
        from ..models import UpgradeRecord
        from ..models_checklist import UpgradeRecordStep
        from ..models_status_log import UpgradeStatusLog
        from apps.evidence.attachment_service import AttachmentService
        from apps.logs.audit import record_audit_event

        user = request.user
        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(is_deleted=False, pk=record_id), user
        ).first()
        if not record:
            return '升级表单不存在或无权限'

        try:
            with transaction.atomic():
                # 软删除关联附件（evidence 通用表，通过 module/object_type/object_id 关联）
                AttachmentService.soft_delete_by_object(
                    user=user,
                    module='upgrade',
                    object_type='record',
                    object_id=record_id,
                    reason='升级表单已删除',
                    delete_file=True,
                )

                # 级联清理子表：UpgradeRecordStep 逻辑删除
                from django.utils import timezone
                now = timezone.now()
                UpgradeRecordStep.objects.filter(upgrade_id=record_id).update(is_deleted=True, deleted_at=now)
                # UpgradeStatusLog 无 is_deleted 字段，保持物理删除
                UpgradeStatusLog.objects.filter(upgrade_id=record_id).delete()

                # 写入删除审计日志（在主表删除前调用，record 字段仍可读取）
                record_audit_event(
                    request, 'delete', 'upgrade',
                    target_id=record.id, target_name=record.title,
                    detail={'title': record.title, 'system': record.system,
                            'upgrade_type': record.upgrade_type},
                )

                # 逻辑删除主表
                record.is_deleted = True
                record.deleted_at = now
                record.save()
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 删除升级表单失败: {e}', exc_info=True)
            return f'删除升级表单失败: {str(e)}'

    @staticmethod
    def get_detail(record_id, user):
        """获取升级表单详情

        Args:
            record_id: 升级表单ID
            user: 当前请求用户

        Returns:
            tuple: (data, error)
        """
        from ..models import UpgradeRecord

        record = apply_tenant_filter(
            UpgradeRecord.objects.filter(is_deleted=False, pk=record_id), user
        ).first()
        if not record:
            return None, '升级表单不存在'

        data = UpgradeRecordSerializer.to_detail_view(record)
        return data, None

    @staticmethod
    def get_list(user, filters=None, page=1, page_size=20):
        """获取分页列表（含统计注解 + 附件计数）

        Args:
            user: 当前请求用户
            filters: 筛选参数字典
            page: 页码
            page_size: 每页数量

        Returns:
            dict: {records, total, page, page_size}
        """
        from ..models import UpgradeRecord
        from apps.evidence.models import EvidenceAttachment
        from django.db.models import Count

        queryset = apply_tenant_filter(UpgradeRecord.objects.filter(is_deleted=False), user)

        # 应用筛选
        if filters:
            queryset = RecordService._apply_filters(queryset, filters)

        # 排序
        queryset = queryset.order_by('-upgrade_time', '-id')

        # 分页
        total = queryset.count()
        start = (page - 1) * page_size
        end = start + page_size
        records = queryset[start:end]

        # 批量查询当前页各记录的附件数（避免 N+1），附件存于 evidence 通用表
        record_ids = [r.id for r in records]
        att_counts = {}
        if record_ids:
            att_qs = apply_tenant_filter(
                EvidenceAttachment.objects.filter(
                    module='upgrade', object_type='record',
                    object_id__in=[str(rid) for rid in record_ids],
                    is_deleted=False,
                ),
                user,
            ).values_list('object_id').annotate(c=Count('id'))
            att_counts = {oid: cnt for oid, cnt in att_qs}

        items = [UpgradeRecordSerializer.to_list_view(r) for r in records]
        for item in items:
            item['attachment_count'] = att_counts.get(str(item['id']), 0)

        return {
            'records': items,
            'total': total,
            'page': page,
            'page_size': page_size,
        }

    @staticmethod
    def get_filter_options(user):
        """获取筛选选项（去重值列表 + 系统字典合并）

        系统候选项来源（均按当前租户过滤）：
        1. 升级系统字典表（UpgradeSystem，is_active=True）— 主源，租户隔离
        2. 历史升级记录中出现过的系统 — 兜底，保证旧记录的系统仍可筛选/选择

        Args:
            user: 当前请求用户

        Returns:
            dict: {systems, statuses, upgrade_types}
        """
        from ..models import UpgradeRecord, UpgradeSystem

        queryset = apply_tenant_filter(UpgradeRecord.objects.filter(is_deleted=False), user)

        # 字典表 active 项（按当前租户过滤，租户隔离）
        tenant_id = getattr(user, 'tenant_id', '')
        dict_systems = list(
            UpgradeSystem.objects.filter(tenant_id=tenant_id, is_active=True, is_deleted=False)
            .order_by('sort_order', 'name')
            .values_list('name', flat=True)
        )

        # 历史系统列表（兜底，保证旧记录系统仍可见）
        history_systems = list(
            queryset.values_list('system', flat=True)
            .distinct()
            .order_by('system')
        )

        # 合并：字典表在前，历史系统中不在字典表的追加在后
        all_systems = list(dict_systems)
        dict_set_lower = {s.lower() for s in dict_systems}
        for sys in history_systems:
            if sys and sys.lower() not in dict_set_lower:
                all_systems.append(sys)
                dict_set_lower.add(sys.lower())

        statuses = list(
            queryset.values_list('status', flat=True)
            .distinct()
            .order_by('status')
        )
        upgrade_types = list(
            queryset.values_list('upgrade_type', flat=True)
            .distinct()
            .order_by('upgrade_type')
        )

        # 阶段候选：预设阶段显示名 + 历史步骤中出现的自定义阶段名（去重合并）
        # phase 字段已改为存显示名，故候选直接为字符串列表
        from ..models_template import UpgradePlanStep
        from ..models_checklist import UpgradeRecordStep

        preset_phase_labels = [p['label'] for p in UPGRADE_PHASES]
        history_phase_qs = (
            list(UpgradePlanStep.objects.filter(tenant_id=tenant_id)
                 .exclude(phase='').values_list('phase', flat=True).distinct())
            + list(UpgradeRecordStep.objects.filter(tenant_id=tenant_id)
                   .exclude(phase='').values_list('phase', flat=True).distinct())
        )
        all_phases = list(preset_phase_labels)
        phase_seen = {p.lower() for p in preset_phase_labels}
        for ph in history_phase_qs:
            if ph and ph.lower() not in phase_seen:
                all_phases.append(ph)
                phase_seen.add(ph.lower())

        return {
            'systems': all_systems,
            'statuses': statuses,
            'upgrade_types': upgrade_types,
            'phases': all_phases,
            'milestones': RESULT_MILESTONES,
            'standard_flow': STANDARD_FLOW_ORDER,
        }

    @staticmethod
    def _apply_filters(queryset, filters):
        """应用筛选条件"""
        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])
        if filters.get('system'):
            queryset = queryset.filter(system__icontains=filters['system'])
        if filters.get('upgrade_type'):
            queryset = queryset.filter(upgrade_type=filters['upgrade_type'])
        if filters.get('owner'):
            queryset = queryset.filter(owner__icontains=filters['owner'])
        if filters.get('start_date') and filters.get('end_date'):
            queryset = queryset.filter(
                upgrade_time__gte=filters['start_date'],
                upgrade_time__lte=filters['end_date'],
            )
        return queryset
