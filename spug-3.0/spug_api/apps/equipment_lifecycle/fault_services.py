# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统健康状态统一计算服务（步骤 3.1，单系统简化）。

规则：
- 系统健康状态只允许由本服务计算写入，故障/工单 View 不得直接改写状态；
- 计算范围只看本系统自己的业务记录（不查询任何跨系统关联表）：
  本系统的有效故障（排除已作废与已关闭，且仅限明确选择"影响系统运行"的故障；
  部件故障/离线维修默认不影响运行，不参与计算），
  以及本系统上"执行中且影响系统运行"的故障维修工单（步骤 3.3）；
- 优先级：中断 > 维修中 > 故障 > 降级（多张故障/工单并存时取最高影响，
  一张故障关闭不会覆盖本系统其他未恢复故障/工单的影响）；
- 无有效影响 → 正常；
- 「未知 unknown」为预留状态，本服务不产生该状态（无法可靠判断时由调用方处理）；
- 仅"故障维修"类型且"执行中"且 affects_system_operation=True 的工单产生
  "维修中" repairing；系统已恢复后的离线部件维修（不影响运行）不改变系统状态；
- 系统状态更新与故障/工单业务操作处于同一数据库事务，且必须在
  health_recalc_lock 全局锁内执行，保证并发操作的重算结果
  以"所有有效影响（故障+执行中影响运行的维修工单）的重新查询结果"为准，
  不允许最后请求直接覆盖。

锁说明：MySQL/MariaDB GET_LOCK 连接级命名锁。所有改变有效影响集合的
故障/工单操作在事务外获取锁、事务提交后释放，使并发重算段完全串行：
后执行者的重算查询必然看到先提交事务的最新数据。
"""
from contextlib import contextmanager

from django.db import connection
from django.utils import timezone

from apps.equipment_lifecycle import event_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemFault,
    SystemWorkOrder,
    WORK_ORDER_STATUS_EXECUTING,
    WORK_TYPE_REPAIR,
)

# 有效影响优先级（高 → 低）
HEALTH_IMPACT_PRIORITY = (
    SystemFault.IMPACT_INTERRUPTED,
    SystemFault.IMPACT_FAULT,
    SystemFault.IMPACT_DEGRADED,
)

# 仍会产生健康影响的故障状态：尚未完成恢复确认的故障。
# recovered（已完成恢复确认）/closed/cancelled 均不再产生影响。
ACTIVE_FAULT_STATUSES = (SystemFault.STATUS_PENDING, SystemFault.STATUS_HANDLING)

# 产生"维修中"状态的工单条件：故障维修类型 + 执行中 + 作业期间影响系统运行
REPAIRING_WORK_ORDER_FILTER = {
    'work_type': WORK_TYPE_REPAIR,
    'status': WORK_ORDER_STATUS_EXECUTING,
    'affects_system_operation': True,
}

HEALTH_RECALC_LOCK_NAME = 'el_health_recalc'
HEALTH_RECALC_LOCK_TIMEOUT = 10

AUDIT_TARGET_HEALTH = 'el_system_health'


class HealthRecalcLockTimeout(Exception):
    """健康重算锁获取超时：并发过高时 fail-closed，避免状态覆盖。"""


def collect_active_impacts(tenant_id, system_ids):
    """查询系统自身的有效故障影响，返回 {system_id: set(impact)}。

    单系统简化：只按本系统 ID 查询 SystemFault.impact_status
    （status ∈ ACTIVE_FAULT_STATUSES），不查询任何受影响系统关联表。
    部件故障但不影响系统运行（affects_system_operation=False，默认值）
    不参与系统健康状态计算；只有明确选择影响系统运行的故障才计入。
    """
    system_ids = [int(i) for i in system_ids]
    impacts = {}
    if not system_ids or not tenant_id:
        return impacts
    fault_rows = SystemFault.objects.filter(
        tenant_id=tenant_id,
        status__in=ACTIVE_FAULT_STATUSES,
        affects_system_operation=True,
        system_id__in=system_ids,
    ).values_list('system_id', 'impact_status')
    for system_id, impact in fault_rows:
        impacts.setdefault(system_id, set()).add(impact)
    return impacts


def collect_repairing_system_ids(tenant_id, system_ids):
    """查询本系统上执行中且影响运行的故障维修工单，返回 set(system_id)。

    仅"故障维修"类型 + "执行中" + affects_system_operation=True 的工单
    参与"维修中"状态计算。
    """
    if not system_ids or not tenant_id:
        return set()
    rows = SystemWorkOrder.objects.filter(
        tenant_id=tenant_id,
        system_id__in=[int(i) for i in system_ids],
        **REPAIRING_WORK_ORDER_FILTER,
    ).values_list('system_id', flat=True)
    return {int(i) for i in rows}


def derive_health_status(impacts, repairing=False):
    """由影响集合推导健康状态：中断 > 维修中 > 故障 > 降级，无影响 → 正常。

    - impacts 为该系统自身的有效故障影响集合；
    - repairing 表示该系统存在执行中且影响运行的故障维修工单（步骤 3.3）。
    """
    if SystemFault.IMPACT_INTERRUPTED in impacts:
        return LifecycleSystem.HEALTH_INTERRUPTED
    if repairing:
        return LifecycleSystem.HEALTH_REPAIRING
    for impact in HEALTH_IMPACT_PRIORITY[1:]:
        if impact in impacts:
            return impact
    return LifecycleSystem.HEALTH_NORMAL


def compute_health_status(tenant_id, system_ids):
    """只读计算（不落库）：返回 {system_id: health_status}。幂等、可重复调用。"""
    impacts = collect_active_impacts(tenant_id, system_ids)
    repairing = collect_repairing_system_ids(tenant_id, system_ids)
    result = {}
    for system_id in system_ids:
        result[int(system_id)] = derive_health_status(
            impacts.get(int(system_id), set()), int(system_id) in repairing)
    return result


@contextmanager
def health_recalc_lock():
    """健康状态重算全局串行锁（GET_LOCK）。

    用法（视图层）：在事务外获取锁 → 事务内完成故障变更 + 重算 → 事务提交 → 释放锁。
    """
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT GET_LOCK(%s, %s)', [HEALTH_RECALC_LOCK_NAME, HEALTH_RECALC_LOCK_TIMEOUT])
        got = cursor.fetchone()[0]
        if got != 1:
            raise HealthRecalcLockTimeout('系统繁忙，请稍后重试')
        try:
            yield
        finally:
            try:
                cursor.execute('SELECT RELEASE_LOCK(%s)', [HEALTH_RECALC_LOCK_NAME])
            except Exception:
                connection.close()
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def recompute_systems_health(tenant_id, system_ids, request=None, audit_reason=None):
    """重算并写入给定系统的健康状态（必须在持锁+事务内调用）。

    - 以"所有有效故障 + 执行中影响运行的维修工单的重新查询结果"为准，
      重复调用结果一致（幂等）；
    - 仅写发生变化的系统，状态变化记录审计（request 为 None 时跳过审计，
      供服务内部/测试直接调用）；状态实际未变化不重复生成履历；
    - 返回 {system_id: 最终状态}。
    """
    from apps.logs.audit import record_audit_event

    ids = sorted({int(i) for i in system_ids})
    if not ids or not tenant_id:
        return {}
    impacts = collect_active_impacts(tenant_id, ids)
    repairing = collect_repairing_system_ids(tenant_id, ids)
    result = {}
    # 行锁锁定系统记录（按 id 排序加锁，避免并发事务交叉死锁），
    # 同时避免与并发系统编辑交错写同一行
    systems = LifecycleSystem.objects.select_for_update().order_by('id').filter(
        tenant_id=tenant_id, pk__in=ids)
    for system in systems:
        new_status = derive_health_status(
            impacts.get(system.id, set()), system.id in repairing)
        result[system.id] = new_status
        if system.health_status == new_status:
            continue
        old_status = system.health_status
        system.health_status = new_status
        system.save(update_fields=['health_status'])
        # 步骤 3.4：状态实际变化才生成一次履历事件（重复计算且结果不变不生成）
        event_services.record_health_change_event(
            system, old_status, new_status, reason=audit_reason or '',
            created_by=request.user if request is not None else None)
        if request is not None:
            record_audit_event(
                request, 'other', AUDIT_TARGET_HEALTH, system.id, system.name,
                before_value={'health_status': old_status},
                after_value={'health_status': new_status, 'reason': audit_reason or ''})
    return result


def create_fault_record(*, tenant_id, created_by, system, impact_status,
                        occurred_at, discovery, level, phenomenon, handler=None,
                        affects_system_operation=False,
                        impact_scope='', fault_location='', fault_object_name='',
                        fault_object_model='', fault_object_sn='', reason_analysis='',
                        source_type=None, source_ledger_item=None,
                        source_inspection_record=None, request=None):
    """正式故障创建服务（单系统简化，台账/巡检异常转故障复用）。

    须在 health_recalc_lock + transaction.atomic 内调用（调用方负责锁与事务）：
    - 创建故障主单（一个故障系统外键 + 发生时快照，无受影响系统）；
    - 默认"部件故障但不影响系统运行"（affects_system_operation=False），
      此时 impact_status 强制存空串且不参与健康状态计算；
      仅调用方明确传 affects_system_operation=True 时按 impact_status 参与计算；
    - 同事务生成故障发生履历事件（只落故障所属系统，步骤 3.4 统一履历）；
    - 同事务重算故障系统健康状态（request 透传以记录状态变化审计）；
    - source_type/source_ledger_item/source_inspection_record 供异常转故障写入
      来源关系，转换与来源关系保存处于同一事务。

    返回 SystemFault 实例。
    """
    if not affects_system_operation:
        impact_status = ''
    fault = SystemFault.objects.create(
        tenant_id=tenant_id,
        fault_no=generate_fault_no(tenant_id),
        system=system,
        impact_status=impact_status,
        affects_system_operation=bool(affects_system_operation),
        system_code=system.system_code,
        system_name=system.name,
        system_location=system.install_location,
        occurred_at=occurred_at,
        discovery=discovery,
        level=level,
        phenomenon=phenomenon[:2000],
        impact_scope=(impact_scope or '').strip()[:1000],
        fault_location=(fault_location or '').strip()[:200],
        fault_object_name=(fault_object_name or '').strip()[:100],
        fault_object_model=(fault_object_model or '').strip()[:100],
        fault_object_sn=(fault_object_sn or '').strip()[:100],
        reason_analysis=(reason_analysis or '').strip()[:2000],
        status=SystemFault.STATUS_PENDING,
        source_type=source_type or SystemFault.SOURCE_MANUAL,
        source_id=str(source_ledger_item.id) if source_ledger_item else (
            str(source_inspection_record.id) if source_inspection_record else ''),
        source_ledger_item=source_ledger_item,
        source_inspection_record=source_inspection_record,
        created_by=created_by,
        handler=handler,
    )
    # 步骤 3.4：故障发生履历（只落故障所属系统，同一事务）
    event_services.record_fault_lifecycle_events(
        fault, 'create', occurred_at=fault.occurred_at, created_by=created_by,
        detail={'source_ledger_item_id': source_ledger_item.id} if source_ledger_item else (
            {'source_inspection_record_id': source_inspection_record.id}
            if source_inspection_record else None))
    recompute_systems_health(tenant_id, [system.id], request=request)
    return fault


def generate_fault_no(tenant_id):
    """生成租户内当日序号故障编号 GZ{yyyymmdd}-{seq:04d}（须在持锁事务内调用）。"""
    # USE_TZ=False 下 timezone.localdate() 会对 naive now 抛错，直接取本地日期
    prefix = 'GZ' + timezone.now().date().strftime('%Y%m%d') + '-'
    existing = set(SystemFault.objects.filter(
        tenant_id=tenant_id, fault_no__startswith=prefix).values_list('fault_no', flat=True))
    index = len(existing) + 1
    while f'{prefix}{index:04d}' in existing:
        index += 1
    return f'{prefix}{index:04d}'
