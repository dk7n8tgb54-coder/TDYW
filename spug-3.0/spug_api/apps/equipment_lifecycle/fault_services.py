# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统健康状态统一计算服务（步骤 3.1）。

规则：
- 系统健康状态只允许由本服务计算写入，故障 View 不得直接改写状态；
- 计算范围：系统作为主故障系统/受影响系统的全部有效故障，排除已作废与已关闭；
- 优先级：中断 > 故障 > 降级（多张故障并存时取最高影响）；
- 无有效影响 → 正常；
- 「维修中 repairing」「未知 unknown」为后续工单步骤预留，本步骤计算不产生
  这两个状态（无有效影响即恢复为 normal，不伪造维修工单逻辑）；
- 系统状态更新与故障业务操作处于同一数据库事务，且必须在
  health_recalc_lock 全局锁内执行，保证并发故障操作的重算结果
  以"所有有效故障的重新查询结果"为准，不允许最后请求直接覆盖。

锁说明：MySQL/MariaDB GET_LOCK 连接级命名锁。所有改变有效影响集合的
故障操作在事务外获取锁、事务提交后释放，使并发重算段完全串行：
后执行者的重算查询必然看到先提交事务的最新数据。
"""
from contextlib import contextmanager

from django.db import connection

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemFault,
    SystemFaultAffectedSystem,
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

HEALTH_RECALC_LOCK_NAME = 'el_health_recalc'
HEALTH_RECALC_LOCK_TIMEOUT = 10

AUDIT_TARGET_HEALTH = 'el_system_health'


class HealthRecalcLockTimeout(Exception):
    """健康重算锁获取超时：并发过高时 fail-closed，避免状态覆盖。"""


def collect_active_impacts(tenant_id, system_ids):
    """查询系统当前承担的全部有效故障影响，返回 {system_id: set(impact)}。

    来源：
    - 主故障系统：SystemFault.primary_impact_status（status ∈ ACTIVE_FAULT_STATUSES）；
    - 受影响系统：SystemFaultAffectedSystem.impact_status（同上）。
    """
    system_ids = [int(i) for i in system_ids]
    impacts = {}
    if not system_ids or not tenant_id:
        return impacts
    fault_rows = SystemFault.objects.filter(
        tenant_id=tenant_id,
        status__in=ACTIVE_FAULT_STATUSES,
        primary_system_id__in=system_ids,
    ).values_list('primary_system_id', 'primary_impact_status')
    for system_id, impact in fault_rows:
        impacts.setdefault(system_id, set()).add(impact)
    affected_rows = SystemFaultAffectedSystem.objects.filter(
        tenant_id=tenant_id,
        fault__status__in=ACTIVE_FAULT_STATUSES,
        fault__tenant_id=tenant_id,
        system_id__in=system_ids,
    ).values_list('system_id', 'impact_status')
    for system_id, impact in affected_rows:
        impacts.setdefault(system_id, set()).add(impact)
    return impacts


def derive_health_status(impacts):
    """由影响集合推导健康状态：取最高优先级影响，无影响 → 正常。"""
    for impact in HEALTH_IMPACT_PRIORITY:
        if impact in impacts:
            return impact
    return LifecycleSystem.HEALTH_NORMAL


def compute_health_status(tenant_id, system_ids):
    """只读计算（不落库）：返回 {system_id: health_status}。幂等、可重复调用。"""
    impacts = collect_active_impacts(tenant_id, system_ids)
    result = {}
    for system_id in system_ids:
        result[int(system_id)] = derive_health_status(impacts.get(int(system_id), set()))
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

    - 以"所有有效故障的重新查询结果"为准，重复调用结果一致（幂等）；
    - 仅写发生变化的系统，状态变化记录审计（request 为 None 时跳过审计，
      供服务内部/测试直接调用）；
    - 返回 {system_id: 最终状态}。
    """
    from apps.logs.audit import record_audit_event

    ids = sorted({int(i) for i in system_ids})
    if not ids or not tenant_id:
        return {}
    impacts = collect_active_impacts(tenant_id, ids)
    result = {}
    # 行锁锁定系统记录（按 id 排序加锁，避免并发事务交叉死锁），
    # 同时避免与并发系统编辑交错写同一行
    systems = LifecycleSystem.objects.select_for_update().order_by('id').filter(
        tenant_id=tenant_id, pk__in=ids)
    for system in systems:
        new_status = derive_health_status(impacts.get(system.id, set()))
        result[system.id] = new_status
        if system.health_status == new_status:
            continue
        old_status = system.health_status
        system.health_status = new_status
        system.save(update_fields=['health_status'])
        if request is not None:
            record_audit_event(
                request, 'other', AUDIT_TARGET_HEALTH, system.id, system.name,
                before_value={'health_status': old_status},
                after_value={'health_status': new_status, 'reason': audit_reason or ''})
    return result
