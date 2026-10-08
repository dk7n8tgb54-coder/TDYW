# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级表单服务 - 创建/更新/删除/列表/详情

升级系统通过正式外键关联系统档案（LifecycleSystem）并保存快照：
请求与存储一律用系统 ID，页面只显示名称；新建/换绑只允许可用（未停用）系统，
编辑未变更的关联允许保留已停用系统（历史单据继续可查）。
"""
import logging
from contextlib import contextmanager

from django.db import connection, transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter
from libs.idempotency import check_recent_duplicate
from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.event_services import record_upgrade_lifecycle_events
from ..validators import RecordValidator
from ..serializers import UpgradeRecordSerializer
from ..constants import UPGRADE_PHASES, RESULT_MILESTONES, STANDARD_FLOW_ORDER

logger = logging.getLogger(__name__)


class UpgradeNoExhausted(Exception):
    """当日升级编号序号已用尽（SJyyyymmdd-9999 已占用）：
    fail-closed，不产生五位序号或重复编号，由调用方转为业务错误。"""


class UpgradeNoLockTimeout(Exception):
    """升级编号锁获取超时：并发过高时 fail-closed，避免并发撞号。"""


# 升级编号规则（对齐故障编号 GZ/运行记录编号 YX 的跨租户当日序号方案）：
# SJ + 创建日期 + '-' + 当日四位序号，序号全租户共享、按最大有效后缀 +1（缺口不回填）。
UPGRADE_NO_PREFIX = 'SJ'
UPGRADE_NO_SEQ_LIMIT = 9999
UPGRADE_NO_LOCK_NAME = 'upgrade_record_no'
UPGRADE_NO_LOCK_TIMEOUT = 10


@contextmanager
def upgrade_no_lock():
    """升级编号生成全局串行锁（GET_LOCK，防并发创建撞号）。

    用法：在事务外获取锁 → 事务内完成查号 + 创建 → 事务提交 → 释放锁。
    ATOMIC_REQUESTS 下持锁的正式创建视图以 non_atomic_requests 装配
    （urls.py），保证锁释放在事务真实提交之后。
    """
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT GET_LOCK(%s, %s)',
                       [UPGRADE_NO_LOCK_NAME, UPGRADE_NO_LOCK_TIMEOUT])
        got = cursor.fetchone()[0]
        if got != 1:
            raise UpgradeNoLockTimeout('系统繁忙，请稍后重试')
        try:
            yield
        finally:
            try:
                cursor.execute('SELECT RELEASE_LOCK(%s)', [UPGRADE_NO_LOCK_NAME])
            except Exception:
                connection.close()
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def generate_upgrade_no():
    """生成升级编号 SJ{yyyymmdd}-{seq:04d}（须在 upgrade_no_lock 持锁事务内调用）。

    编号规则与故障编号（generate_fault_no）/运行记录编号（generate_runtime_record_no）
    一致：
    - 日期取创建当天（不取用户填写的计划升级时间 upgrade_time）；
    - 当日序号跨租户共享：扫描全部记录（含软删除，编号不回收复用），
      按有效四位数字后缀的最大值加一，已有缺口不回填；
    - 历史存量编号由迁移 0023 按创建日期回填，本规则保证回填之后的
      正式创建路径生成的编号跨租户唯一；
    - 序号达 9999 后抛出 UpgradeNoExhausted，不产生五位序号或重复编号。
    """
    # USE_TZ=False 下 timezone.localdate() 会对 naive now 抛错，直接取本地日期
    prefix = UPGRADE_NO_PREFIX + timezone.now().date().strftime('%Y%m%d') + '-'
    max_seq = 0
    from ..models import UpgradeRecord
    existing = UpgradeRecord.objects.all_with_deleted().filter(
        upgrade_no__startswith=prefix).values_list('upgrade_no', flat=True)
    for no in existing:
        suffix = no[len(prefix):]
        if len(suffix) == 4 and suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    if max_seq >= UPGRADE_NO_SEQ_LIMIT:
        raise UpgradeNoExhausted(f'当日升级编号已达上限（{prefix}9999），请明日再创建')
    return f'{prefix}{max_seq + 1:04d}'


def get_active_system_for_user(pk, user):
    """取本租户可用（未停用）系统：新建/换绑升级记录只允许选择可用系统。"""
    if not pk:
        return None
    return apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
        pk=pk, is_active=True).first()


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

        # 系统档案校验：新建只允许选择本租户可用系统
        system = get_active_system_for_user(record_data.system, user)
        if not system:
            return None, '升级系统不存在或已停用'

        # 幂等性检查：防止双击重复提交
        if check_recent_duplicate(UpgradeRecord, {
            'tenant_id': user.tenant_id,
            'title': getattr(record_data, 'title', '') or '',
            'system': record_data.system,
            'upgrade_type': record_data.upgrade_type,
        }):
            return None, '提交过于频繁，请勿重复提交'

        try:
            # 编号在 upgrade_record_no 全局锁内分配：锁 → 事务提交 → 释放锁
            with upgrade_no_lock():
                with transaction.atomic():
                    # 2. 创建主表
                    now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

                    # upgrade_time 转为字符串
                    upgrade_time_val = getattr(record_data, 'upgrade_time', '')
                    if hasattr(upgrade_time_val, 'strftime'):
                        upgrade_time_val = upgrade_time_val.strftime('%Y-%m-%d %H:%M:%S')

                    record = UpgradeRecord.objects.create(
                        tenant_id=user.tenant_id,
                        upgrade_no=generate_upgrade_no(),
                        title=getattr(record_data, 'title', '') or '',
                        system=system,
                        system_code=system.system_code,
                        system_name=system.name,
                        system_location=system.install_location,
                        upgrade_type=record_data.upgrade_type,
                        upgrade_time=upgrade_time_val,
                        status=getattr(record_data, 'status', '处理中') or '处理中',
                        owner=record_data.owner,
                        upgrade_content=getattr(record_data, 'upgrade_content', '') or '',
                        impact_scope=getattr(record_data, 'impact_scope', '') or '',
                        risk_desc=getattr(record_data, 'risk_desc', '') or '',
                        rollback_plan=getattr(record_data, 'rollback_plan', '') or '',
                        created_by=user,
                    )

                    # 3. 同事务写系统履历（升级登记）
                    record_upgrade_lifecycle_events(record, 'create', created_by=user)

            return record, None

        except UpgradeNoLockTimeout as e:
            return None, str(e)
        except UpgradeNoExhausted as e:
            return None, str(e)
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

        # 系统档案变更：换绑只允许选择可用系统；未变更的关联即使已停用也保留
        # （历史单据继续可查），并同步重写快照
        new_system_id = getattr(data, 'system', None)
        if new_system_id is not None and new_system_id != record.system_id:
            system = get_active_system_for_user(new_system_id, user)
            if not system:
                return None, '升级系统不存在或已停用'
            record.system = system
            record.system_code = system.system_code
            record.system_name = system.name
            record.system_location = system.install_location

        try:
            # 更新可编辑字段（system 已在上方单独处理）
            editable_fields = ['title', 'upgrade_type', 'status', 'owner',
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
            record.save(update_fields=[
                'title', 'system', 'system_code', 'system_name', 'system_location',
                'upgrade_type', 'upgrade_time', 'status', 'owner',
                'upgrade_content', 'impact_scope', 'risk_desc', 'rollback_plan',
                'updated_at', 'updated_by',
            ])
        except Exception as e:
            logger.error(f'[Upgrade] 更新升级表单失败: {e}', exc_info=True)
            return None, f'更新升级表单失败: {str(e)}'

        return record, None

    @staticmethod
    def delete_record(record_id, request):
        """删除升级表单

        联动处理：
        1. 软删除该表单下的所有附件（附件存于 evidence 通用表）
        2. 级联清理子表（UpgradeRecordStep / UpgradeStatusLog，二者用 IntegerField
           upgrade_id 关联主表，DB 不会自动级联，必须手动清理避免孤儿数据）
        3. 逻辑删除主表记录（is_deleted=True + deleted_at）
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
                    detail={'title': record.title, 'system_name': record.system_name,
                            'upgrade_type': record.upgrade_type},
                )

                # 逻辑删除主表
                record.is_deleted = True
                record.deleted_at = now
                record.save(update_fields=['is_deleted', 'deleted_at'])
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
        """获取筛选选项（去重值列表 + 系统档案可用系统）

        系统候选来源：系统档案（LifecycleSystem）本租户可用（未停用）系统，
        返回对象列表 [{id, system_code, name, install_location}]。

        Args:
            user: 当前请求用户

        Returns:
            dict: {systems, statuses, upgrade_types, phases, milestones, standard_flow}
        """
        from ..models import UpgradeRecord

        queryset = apply_tenant_filter(UpgradeRecord.objects.filter(is_deleted=False), user)

        # 系统档案可用系统（按当前租户过滤，租户隔离）
        systems = list(
            apply_tenant_filter(
                LifecycleSystem.objects.filter(is_active=True), user
            ).order_by('system_code')
            .values('id', 'system_code', 'name', 'install_location')
        )

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

        tenant_id = getattr(user, 'tenant_id', '')
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
            'systems': systems,
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
            # system 参数为系统档案 ID（正式外键精确过滤）
            queryset = queryset.filter(system_id=filters['system'])
        if filters.get('upgrade_type'):
            queryset = queryset.filter(upgrade_type=filters['upgrade_type'])
        if filters.get('owner'):
            queryset = queryset.filter(owner__startswith=filters['owner'])
        if filters.get('start_date') and filters.get('end_date'):
            # 日期范围：__gte 当天起始，__lt 次日起始（避免 __lte 只匹配午夜）
            from datetime import datetime, timedelta
            end_date = datetime.strptime(filters['end_date'], '%Y-%m-%d') + timedelta(days=1)
            queryset = queryset.filter(
                upgrade_time__gte=filters['start_date'],
                upgrade_time__lt=end_date.strftime('%Y-%m-%d'),
            )
        return queryset
