# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统工单服务层（步骤 3.3）。

职责：
- 工单编号生成（租户内当日序号，须在持锁事务内调用）；
- 工单创建核心（人工创建 / 故障生成维修工单 / 台账异常转工单三条路径共用）；
- 台账异常明细处置状态计算（由来源关系动态推导，事实依据不落库）；
- 幂等令牌查询（同租户 + 同来源 + 同 client_token 视为同一请求）。

约定：
- 健康状态重算统一走 fault_services.recompute_systems_health（不另写第二套）；
- 来源对象（故障/台账明细）使用真实外键（PROTECT），后端根据来源类型重新
  查询真实对象并校验租户，不信任前端传来的名称或快照。
"""
from django.utils import timezone

from apps.account.models import User
from apps.equipment_lifecycle import event_services
from apps.equipment_lifecycle.fault_services import recompute_systems_health
from apps.equipment_lifecycle.models import (
    DISPOSITION_CONVERTED_FAULT,
    DISPOSITION_CONVERTED_WORK_ORDER,
    DISPOSITION_NONE,
    DISPOSITION_TARGET_CANCELLED,
    LifecycleSystem,
    SystemFault,
    SystemWorkOrder,
    SystemWorkOrderAffectedSystem,
    SystemWorkOrderParticipant,
    WORK_ORDER_NO_PREFIX,
    WORK_ORDER_ROLE_OWNER,
    WORK_ORDER_ROLE_PARTICIPANT,
    WORK_ORDER_SOURCE_FAULT,
    WORK_ORDER_SOURCE_LEDGER_ITEM,
    WORK_ORDER_SOURCE_MANUAL,
    WORK_ORDER_STATUS_CANCELLED,
)

AUDIT_TARGET_WORK_ORDER = 'el_work_order'

# 工单处理记录附件归属标识（复用 EvidenceAttachment 体系）
WORK_ORDER_ATTACHMENT_MODULE = 'equipment_lifecycle'
WORK_ORDER_ATTACHMENT_OBJECT_TYPE = 'el_work_order_handling'


class WorkOrderValidationError(Exception):
    """工单业务校验失败（视图层转为 json_response(error=...)）。"""


def generate_work_no(tenant_id):
    """生成租户内当日序号工单编号 WO{yyyymmdd}-{seq:04d}（须在持锁事务内调用）。"""
    prefix = WORK_ORDER_NO_PREFIX + timezone.now().date().strftime('%Y%m%d') + '-'
    existing = set(SystemWorkOrder.objects.filter(
        tenant_id=tenant_id, work_no__startswith=prefix).values_list('work_no', flat=True))
    index = len(existing) + 1
    while f'{prefix}{index:04d}' in existing:
        index += 1
    return f'{prefix}{index:04d}'


def get_tenant_active_user(user, pk=None, tenant_id=None):
    """校验并返回本租户内有效账户（不存在/停用/跨租户返回 None）。

    - 指定 pk 时按 pk 查询；tenant_id 缺省取请求用户租户（fail-closed，
      超级管理员也不得为本租户以外的人员指派工单角色）。
    """
    qs = User.objects.filter(
        is_active=True, deleted_at__isnull=True,
        tenant_id=tenant_id or user.tenant_id)
    if pk is None:
        return None
    return qs.filter(pk=pk).first()


def find_existing_by_token(tenant_id, client_token, source_type=None, source_object=None):
    """按幂等令牌查找已存在工单：同租户 + 同令牌（+ 同来源）视为同一请求。

    用于创建/转单接口：重复提交时返回已有工单而不新建（HTTP 层面幂等）。
    """
    if not client_token:
        return None
    qs = SystemWorkOrder.objects.filter(tenant_id=tenant_id, client_token=client_token)
    if source_type:
        qs = qs.filter(source_type=source_type)
    if source_type == WORK_ORDER_SOURCE_FAULT and source_object is not None:
        qs = qs.filter(source_fault=source_object)
    elif source_type == WORK_ORDER_SOURCE_LEDGER_ITEM and source_object is not None:
        qs = qs.filter(source_ledger_item=source_object)
    return qs.order_by('id').first()


def create_work_order_record(*, tenant_id, created_by, title, work_type, target_system,
                             priority=SystemWorkOrder.PRIORITY_NORMAL,
                             source_type=WORK_ORDER_SOURCE_MANUAL, source_fault=None,
                             source_ledger_item=None, source_no='',
                             affected_map=None, owner=None, participants=None,
                             work_location='', work_object_desc='', work_component=None,
                             planned_start=None, planned_end=None, work_requirement='',
                             work_steps='', material_note='', client_token='',
                             status=None, request=None):
    """工单创建核心（三条创建路径共用）。

    须在 health_recalc_lock + transaction.atomic 内调用（调用方负责锁与事务、
    字段校验与审计）。创建后同事务生成工单登记履历（目标系统 primary +
    受影响登记系统 related，步骤 3.4 统一履历），并重算目标系统健康状态
    （若为执行中的故障维修工单则立即生效；一般创建不改变状态，重算幂等无害）。

    - affected_map: {system_id: system}（已通过校验的受影响系统，不含目标系统）；
    - participants: [user]（不含负责人；负责人单独以 role=owner 写入）；
    - source_type/source_fault/source_ledger_item/source_no 由调用方按来源写入；
    - status 允许转换流程显式指定（普通创建缺省待派发）；
    - request 透传给健康重算以便状态变化审计与履历归属到人。
    """
    if status is None:
        status = SystemWorkOrder.STATUS_PENDING_DISPATCH
    work_order = SystemWorkOrder.objects.create(
        tenant_id=tenant_id,
        work_no=generate_work_no(tenant_id),
        title=(title or '').strip()[:100],
        work_type=work_type,
        priority=priority,
        source_type=source_type,
        source_fault=source_fault,
        source_ledger_item=source_ledger_item,
        source_no=(source_no or '').strip()[:50],
        target_system=target_system,
        target_system_code=target_system.system_code,
        target_system_name=target_system.name,
        target_system_location=target_system.install_location,
        work_location=(work_location or '').strip()[:200],
        work_object_desc=(work_object_desc or '').strip()[:1000],
        work_component=work_component,
        work_component_name=work_component.name if work_component else '',
        owner=owner,
        planned_start=planned_start,
        planned_end=planned_end,
        work_requirement=(work_requirement or '').strip()[:2000],
        work_steps=(work_steps or '').strip()[:2000],
        material_note=(material_note or '').strip()[:500],
        status=status,
        client_token=(client_token or '').strip()[:64],
        created_by=created_by,
    )
    if affected_map:
        SystemWorkOrderAffectedSystem.objects.bulk_create([
            SystemWorkOrderAffectedSystem(
                tenant_id=tenant_id,
                work_order=work_order,
                system=system,
                system_code=system.system_code,
                system_name=system.name,
                install_location=system.install_location,
            ) for system in affected_map.values()
        ])
    participant_rows = []
    if owner is not None:
        participant_rows.append(SystemWorkOrderParticipant(
            tenant_id=tenant_id, work_order=work_order, user=owner,
            role=WORK_ORDER_ROLE_OWNER))
    for user in (participants or []):
        if owner is not None and user.id == owner.id:
            continue  # 负责人兼参与人只保留一行，页面不重复显示
        participant_rows.append(SystemWorkOrderParticipant(
            tenant_id=tenant_id, work_order=work_order, user=user,
            role=WORK_ORDER_ROLE_PARTICIPANT))
    if participant_rows:
        SystemWorkOrderParticipant.objects.bulk_create(participant_rows)
    # 步骤 3.4：工单登记履历（目标系统 primary + 受影响登记系统 related，同一事务）
    event_services.record_work_order_lifecycle_events(
        work_order, 'create', created_by=created_by)
    recompute_systems_health(tenant_id, [target_system.id], request=request)
    return work_order


def compute_item_disposition(tenant_id, item_ids):
    """计算台账异常明细的处置状态（由来源关系动态推导，事实依据）。

    返回 {item_id: {'status': ..., 'fault': {...} 或 None, 'work_order': {...} 或 None}}：
    - status ∈ none / converted_fault / converted_work_order / target_cancelled；
    - 已取消/作废目标仍保留关联（历史可追溯），仅体现为 target_cancelled；
    - 台账明细本身不因转单被修改。
    """
    item_ids = [int(i) for i in item_ids]
    result = {
        i: {'status': DISPOSITION_NONE, 'fault': None, 'work_order': None}
        for i in item_ids
    }
    if not item_ids or not tenant_id:
        return result

    def _fault_brief(fault):
        return {'id': fault.id, 'fault_no': fault.fault_no, 'status': fault.status}

    def _order_brief(order):
        return {'id': order.id, 'work_no': order.work_no, 'status': order.status}

    for fault in SystemFault.objects.filter(
            tenant_id=tenant_id, source_ledger_item_id__in=item_ids).order_by('-id'):
        slot = result.get(fault.source_ledger_item_id)
        if slot is None:
            continue
        if slot['fault'] is None:
            slot['fault'] = _fault_brief(fault)
        if fault.status != WORK_ORDER_STATUS_CANCELLED and slot['status'] == DISPOSITION_NONE:
            slot['status'] = DISPOSITION_CONVERTED_FAULT

    for order in SystemWorkOrder.objects.filter(
            tenant_id=tenant_id, source_ledger_item_id__in=item_ids).order_by('-id'):
        slot = result.get(order.source_ledger_item_id)
        if slot is None:
            continue
        if slot['work_order'] is None:
            slot['work_order'] = _order_brief(order)
        if order.status == WORK_ORDER_STATUS_CANCELLED:
            continue
        # 已转故障优先展示；仅当尚无故障处置时展示已转工单
        if slot['status'] == DISPOSITION_NONE:
            slot['status'] = DISPOSITION_CONVERTED_WORK_ORDER

    # 存在历史关联但目标均已取消/作废
    for slot in result.values():
        if slot['status'] == DISPOSITION_NONE and (slot['fault'] or slot['work_order']):
            slot['status'] = DISPOSITION_TARGET_CANCELLED
    return result


def append_item_disposition(tenant_id, items):
    """把处置状态批量并入台账明细序列化结果（items 为 to_view() 后的 dict 列表）。"""
    ids = [item['id'] for item in items if isinstance(item, dict) and item.get('id')]
    if not ids:
        return items
    disposition_map = compute_item_disposition(tenant_id, ids)
    for item in items:
        item['disposition'] = disposition_map.get(item.get('id'))
    return items


def validate_affected_systems(entries, target_system, tenant_id, allow_inactive=()):
    """校验受影响系统 ID 列表，返回 ({system_id: system}, error)。

    - 全部通过系统 ID 提交并重新查询校验（租户、可用性）；
    - 目标系统不得重复出现在受影响系统中，同一系统不得重复添加；
    - allow_inactive: 允许保持关联的已停用系统 ID 集合（编辑时未变更的历史关联）。
    """
    if entries is None:
        return {}, None
    if not isinstance(entries, list):
        return None, '受影响系统格式不正确'
    result = {}
    for entry in entries:
        try:
            system_id = int(entry)
        except (TypeError, ValueError):
            return None, '受影响系统必须以系统ID提交'
        if system_id == target_system.id:
            return None, '目标系统不能同时作为受影响系统'
        if system_id in result:
            return None, '同一受影响系统不能重复添加'
        system = LifecycleSystem.objects.filter(
            tenant_id=tenant_id, pk=system_id).first()
        if not system:
            return None, f'受影响系统不存在或无权限（ID {system_id}）'
        if not system.is_active and system_id not in allow_inactive:
            return None, f'受影响系统已停用（ID {system_id}）'
        result[system_id] = system
    return result, None


def set_participants(work_order, owner, participant_users):
    """重设工单参与人员（派发时调用；须在持锁事务内）。

    - 先清后建（唯一约束防重复）；负责人以 role=owner 单独一行；
    - 负责人同时出现在参与人列表时去重，页面不重复显示。
    """
    work_order.participants.all().delete()
    rows = []
    if owner is not None:
        rows.append(SystemWorkOrderParticipant(
            tenant_id=work_order.tenant_id, work_order=work_order, user=owner,
            role=WORK_ORDER_ROLE_OWNER))
    for user in participant_users or []:
        if owner is not None and user.id == owner.id:
            continue
        rows.append(SystemWorkOrderParticipant(
            tenant_id=work_order.tenant_id, work_order=work_order, user=user,
            role=WORK_ORDER_ROLE_PARTICIPANT))
    if rows:
        SystemWorkOrderParticipant.objects.bulk_create(rows)
