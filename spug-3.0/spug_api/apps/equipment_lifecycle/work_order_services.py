# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统工单服务层（步骤 3.3，单系统简化；单账号协同流程）。

职责：
- 工单编号生成（租户内当日序号，须在持锁事务内调用）；
- 工单创建核心（人工创建 / 故障生成维修工单 / 台账异常转工单等路径共用）：
  创建即执行中并自动记录实际开始时间，不再有派发/接单/复核环节；
- 台账异常明细处置状态计算（由来源关系动态推导，事实依据不落库）；
- 幂等令牌查询（同租户 + 同来源 + 同 client_token 视为同一请求）。

约定：
- 一张工单只关联一个作业系统，不建设跨系统影响关系；
- 健康状态重算统一走 fault_services.recompute_systems_health（不另写第二套）；
- 来源对象（故障/台账明细/巡检明细）使用真实外键（PROTECT），后端根据来源类型重新
  查询真实对象并校验租户，不信任前端传来的名称或快照。
"""
from django.utils import timezone

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
    WORK_ORDER_NO_PREFIX,
    WORK_ORDER_SOURCE_FAULT,
    WORK_ORDER_SOURCE_INSPECTION_RECORD,
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
    elif source_type == WORK_ORDER_SOURCE_INSPECTION_RECORD and source_object is not None:
        qs = qs.filter(source_inspection_record=source_object)
    return qs.order_by('id').first()


def _clean_text(value, limit):
    """可选文本字段规范化（None 视为空串，去首尾空白并限长）。"""
    return (value or '').strip()[:limit]


def create_work_order_record(*, tenant_id, created_by, title, work_type, system,
                             priority=SystemWorkOrder.PRIORITY_NORMAL,
                             source_type=WORK_ORDER_SOURCE_MANUAL, source_fault=None,
                             source_ledger_item=None, source_inspection_record=None,
                             source_no='',
                             affects_system_operation=False,
                             work_location='', work_object_desc='',
                             planned_start=None, planned_end=None, work_requirement='',
                             work_steps='', material_note='', client_token='',
                             status=None, request=None):
    """工单创建核心（人工创建/故障转单/台账转单/巡检转单路径共用，单账号协同流程）。

    须在 health_recalc_lock + transaction.atomic 内调用（调用方负责锁与事务、
    字段校验与审计）。创建即执行中并自动记录实际开始时间；不要求负责人与
    参与人，不创建参与人员记录（历史工单的参与人记录保留展示）。

    - affects_system_operation：作业期间是否影响系统运行（后端保存前重新校验）；
    - source_type/source_fault/source_ledger_item/source_inspection_record/source_no
      由调用方按来源写入；
    - status 允许显式指定（普通创建缺省执行中）；
    - request 透传给健康重算以便状态变化审计与履历归属到人。
    """
    if status is None:
        status = SystemWorkOrder.STATUS_EXECUTING
    work_order = SystemWorkOrder.objects.create(
        tenant_id=tenant_id,
        work_no=generate_work_no(tenant_id),
        title=_clean_text(title, 100),
        work_type=work_type,
        priority=priority,
        source_type=source_type,
        source_fault=source_fault,
        source_ledger_item=source_ledger_item,
        source_inspection_record=source_inspection_record,
        source_no=_clean_text(source_no, 50),
        system=system,
        system_code=system.system_code,
        system_name=system.name,
        system_location=system.install_location,
        affects_system_operation=bool(affects_system_operation),
        work_location=_clean_text(work_location, 200),
        work_object_desc=_clean_text(work_object_desc, 1000),
        planned_start=planned_start,
        planned_end=planned_end,
        work_requirement=_clean_text(work_requirement, 2000),
        work_steps=_clean_text(work_steps, 2000),
        material_note=_clean_text(material_note, 500),
        status=status,
        actual_start=timezone.now(),
        client_token=_clean_text(client_token, 64),
        created_by=created_by,
    )
    # 步骤 3.4：工单登记履历（只落作业系统，同一事务）
    event_services.record_work_order_lifecycle_events(
        work_order, 'create', created_by=created_by)
    recompute_systems_health(tenant_id, [system.id], request=request)
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
