# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""运行与故障记录统一服务层（2026-10-11 合并改造）。

职责：
- 统一记录编号生成（JL+日期+当日序号，全局锁防撞号）；
- create_operation_record：三种记录类型的唯一创建入口（正式故障可直接登记）；
- identify_record_as_fault：异常事件在原记录上认定为正式故障
  （更新同一条主记录的类型与状态，保留描述/登记人/附件/全部进展，
  不创建第二张单）；
- 系统健康状态统一计算（原 fault_services 口径收窄为统一主表）：
  只有 正式故障 + 处置中（有效未关闭）+ 明确影响系统运行 的记录参与计算；
  日常运行/异常事件/已关闭/已撤销一律不影响健康状态；
- progress_overview_map：列表聚合统一进展概览（单次查询，无 N+1）；
- compute_operation_statistics：只读统计。

履历说明：原 SystemEvent 系统履历已整体退役（2026-10-11），本服务不再写任何
履历事件；系统档案直接查询统一主表等业务表。健康状态变化留痕由业务审计
（record_audit_event）承载。
"""
from contextlib import contextmanager
from datetime import timedelta

from django.db import connection
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone

from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.operation_models import (
    FAULT_IMPACT_VALUES,
    RECORD_NO_PREFIX,
    RECORD_NO_SEQ_LIMIT,
    RECORD_STATUS_FOLLOWING_UP,
    RECORD_STATUS_HANDLING,
    RECORD_STATUS_RECORDED,
    RECORD_TYPE_ABNORMAL,
    RECORD_TYPE_FAULT,
    RECORD_TYPE_VALUES,
    SystemOperationProgress,
    SystemOperationRecord,
)

# 有效影响优先级（高 → 低）：中断 > 故障 > 降级
HEALTH_IMPACT_PRIORITY = tuple(reversed(FAULT_IMPACT_VALUES))

# 仍会产生健康影响的记录状态：正式故障的处置中（唯一未结案的进行态）。
# closed/cancelled 不再产生影响；日常运行与异常事件不参与健康状态计算。
ACTIVE_FAULT_STATUSES = (RECORD_STATUS_HANDLING,)

HEALTH_RECALC_LOCK_NAME = 'el_health_recalc'
HEALTH_RECALC_LOCK_TIMEOUT = 10

RECORD_NO_LOCK_NAME = 'el_operation_record_no'
RECORD_NO_LOCK_TIMEOUT = 10

AUDIT_TARGET_HEALTH = 'el_system_health'
AUDIT_TARGET_RECORD = 'el_operation_record'


class HealthRecalcLockTimeout(Exception):
    """健康重算锁获取超时：并发过高时 fail-closed，避免状态覆盖。"""


class RecordNoExhausted(Exception):
    """当日记录编号序号已用尽（JLyyyymmdd-9999 已占用）：
    fail-closed，不产生五位序号或重复编号，由调用方转为业务错误。"""


class RecordLockTimeout(Exception):
    """记录编号锁获取超时：并发过高时 fail-closed，避免并发撞号。"""


class IdentifyFaultError(Exception):
    """异常事件认定正式故障业务校验失败（类型/状态不满足等）。"""


@contextmanager
def health_recalc_lock():
    """健康状态重算全局串行锁（GET_LOCK）。

    用法（视图层）：在事务外获取锁 → 事务内完成记录变更 + 重算 → 事务提交 → 释放锁。
    """
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT GET_LOCK(%s, %s)',
                       [HEALTH_RECALC_LOCK_NAME, HEALTH_RECALC_LOCK_TIMEOUT])
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


@contextmanager
def record_no_lock():
    """统一记录编号生成全局串行锁（GET_LOCK，防并发创建撞号）。

    用法（视图层）：在事务外获取锁 → 事务内完成查重 + 创建 → 事务提交 → 释放锁。
    ATOMIC_REQUESTS 下持锁视图必须以 non_atomic_requests 装配并在视图内
    显式开启事务。
    """
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT GET_LOCK(%s, %s)',
                       [RECORD_NO_LOCK_NAME, RECORD_NO_LOCK_TIMEOUT])
        got = cursor.fetchone()[0]
        if got != 1:
            raise RecordLockTimeout('系统繁忙，请稍后重试')
        try:
            yield
        finally:
            try:
                cursor.execute('SELECT RELEASE_LOCK(%s)', [RECORD_NO_LOCK_NAME])
            except Exception:
                connection.close()
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def generate_record_no():
    """生成统一记录编号 JL{yyyymmdd}-{seq:04d}（须在编号锁 + 创建事务内调用）。

    - 日期取创建当天（不取用户填写的发生时间 occurred_at）；
    - 当日序号跨租户共享：按有效四位数字后缀的最大值加一（缺口不回填）；
    - 序号达 9999 后抛出 RecordNoExhausted，整个创建事务回滚。
    """
    # USE_TZ=False 下 timezone.localdate() 会对 naive now 抛错，直接取本地日期
    prefix = RECORD_NO_PREFIX + timezone.now().date().strftime('%Y%m%d') + '-'
    max_seq = 0
    existing = SystemOperationRecord.objects.filter(
        record_no__startswith=prefix).values_list('record_no', flat=True)
    for record_no in existing:
        suffix = record_no[len(prefix):]
        if len(suffix) == 4 and suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    if max_seq >= RECORD_NO_SEQ_LIMIT:
        raise RecordNoExhausted(f'当日记录编号已达上限（{prefix}9999），请明日再创建')
    return f'{prefix}{max_seq + 1:04d}'


def user_display_name(user):
    """用户展示姓名：昵称优先、回落用户名（登记人/记录人缺省姓名取此口径）。"""
    if not user:
        return ''
    return (getattr(user, 'nickname', '') or user.username)


def _clean(value, limit):
    """文本入参清洗：None 视为空串、去首尾空白、截断到 limit。"""
    return (value or '').strip()[:limit]


def collect_active_impacts(tenant_id, system_ids):
    """查询系统自身的有效故障影响，返回 {system_id: set(impact)}。

    只按本系统 ID 查询统一主表（record_type=fault、status=处置中、
    affects_system_operation=True）；日常运行/异常事件/已关闭/已撤销
    一律不参与系统健康状态计算。
    """
    system_ids = [int(i) for i in system_ids]
    impacts = {}
    if not system_ids or not tenant_id:
        return impacts
    fault_rows = SystemOperationRecord.objects.filter(
        tenant_id=tenant_id,
        record_type=RECORD_TYPE_FAULT,
        status__in=ACTIVE_FAULT_STATUSES,
        affects_system_operation=True,
        system_id__in=system_ids,
    ).values_list('system_id', 'impact_status')
    for system_id, impact in fault_rows:
        impacts.setdefault(system_id, set()).add(impact)
    return impacts


def derive_health_status(impacts):
    """由影响集合推导健康状态：中断 > 故障 > 降级，无影响 → 正常。"""
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


def recompute_systems_health(tenant_id, system_ids, request=None, audit_reason=None):
    """重算并写入给定系统的健康状态（必须在持锁+事务内调用）。

    - 以"所有有效故障影响的重新查询结果"为准，重复调用结果一致（幂等）；
    - 仅写发生变化的系统，状态变化记录审计（request 为 None 时跳过审计）；
    - 原系统履历（SystemEvent）已退役，不再生成履历事件。
    """
    from apps.logs.audit import record_audit_event

    ids = sorted({int(i) for i in system_ids})
    if not ids or not tenant_id:
        return {}
    impacts = collect_active_impacts(tenant_id, ids)
    result = {}
    # 行锁锁定系统记录（按 id 排序加锁，避免并发事务交叉死锁）
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


def create_operation_record(*, tenant_id, created_by, system, record_type,
                            occurred_at, title, description,
                            registrar_name='', client_token='',
                            category='',
                            affects_system_operation=False, impact_status='',
                            fault_object_name='', fault_object_model='',
                            fault_object_sn='', reason_analysis='',
                            source_type=None, source_ledger_item=None,
                            request=None):
    """统一记录创建服务（唯一创建入口，直接登记故障/台账异常转故障复用）。

    - record_type 必须为三种合法类型之一；fault 默认"部件故障但不影响系统
      运行"（affects=False 时 impact_status 强制空串且不参与健康计算），
      创建即处置中；routine/abnormal 创建即已记录；
    - registrar_name 为登记人（手动输入姓名），缺省取创建人显示姓名
      （台账异常转故障等程序化入口由操作人登记）；
    - source_type/source_ledger_item 供台账异常转故障写入来源关系，
      转换与来源关系保存处于同一事务；
    - 编号由 generate_record_no 在编号锁 + 本事务内分配；
    - 正式故障创建后同事务重算系统健康状态（request 透传以记录审计）。

    返回 SystemOperationRecord 实例。
    """
    if record_type not in RECORD_TYPE_VALUES:
        raise ValueError('记录类型取值不合法')
    is_fault = record_type == RECORD_TYPE_FAULT
    if not is_fault:
        # 非故障记录不携带故障专用字段（后端独立兜底，视图层已拒绝）
        affects_system_operation = False
        impact_status = ''
        fault_object_name = fault_object_model = fault_object_sn = ''
        reason_analysis = ''
    elif not affects_system_operation:
        impact_status = ''
    record = SystemOperationRecord.objects.create(
        tenant_id=tenant_id,
        record_no=generate_record_no(),
        record_type=record_type,
        system=system,
        system_code=system.system_code,
        system_name=system.name,
        system_location=system.install_location,
        occurred_at=occurred_at,
        title=_clean(title, 200),
        description=_clean(description, 2000),
        registrar_name=_clean(registrar_name, 200) or user_display_name(created_by),
        status=RECORD_STATUS_HANDLING if is_fault else RECORD_STATUS_RECORDED,
        category='' if is_fault else _clean(category, 20),
        fault_object_name=_clean(fault_object_name, 100),
        fault_object_model=_clean(fault_object_model, 100),
        fault_object_sn=_clean(fault_object_sn, 100),
        affects_system_operation=bool(affects_system_operation),
        impact_status=_clean(impact_status, 20),
        reason_analysis=_clean(reason_analysis, 2000),
        source_type=source_type or 'manual',
        source_id=str(source_ledger_item.id) if source_ledger_item else '',
        source_ledger_item=source_ledger_item,
        client_token=_clean(client_token, 64),
        created_by=created_by,
    )
    if is_fault:
        recompute_systems_health(tenant_id, [system.id], request=request)
    return record


def identify_record_as_fault(*, record, created_by, occurred_at=None,
                             affects_system_operation=False, impact_status='',
                             reason_analysis='', fault_object_name='',
                             fault_object_model='', fault_object_sn='',
                             request=None):
    """异常事件在原记录上认定为正式故障（须在健康锁+事务内调用，行锁已加）。

    - 仅异常事件（abnormal）且处于 已记录/跟进中 可认定；
    - 更新同一条主记录：record_type→fault、status→处置中，补充故障所需字段
      （影响系统运行/影响程度/原因分析/对象快照）；原描述、登记人、附件与
      全部进展原样保留（进展外键挂主记录，类型变更不受影响）；
    - 发生时间缺省沿用原值（可显式覆盖，不得晚于当前时间——视图层校验）；
    - 同事务重算系统健康状态（认定可能新增有效影响）。

    返回更新后的 record。
    """
    if record.record_type != RECORD_TYPE_ABNORMAL:
        raise IdentifyFaultError('只有异常事件记录可以认定为正式故障')
    if record.status not in (RECORD_STATUS_RECORDED, RECORD_STATUS_FOLLOWING_UP):
        raise IdentifyFaultError('已完成或其他状态的异常事件不能认定为正式故障')
    if affects_system_operation:
        if impact_status not in FAULT_IMPACT_VALUES:
            raise IdentifyFaultError('影响系统运行时必须选择影响程度（降级/故障/中断）')
    else:
        impact_status = ''
    record.record_type = RECORD_TYPE_FAULT
    record.status = RECORD_STATUS_HANDLING
    if occurred_at is not None:
        record.occurred_at = occurred_at
    record.affects_system_operation = bool(affects_system_operation)
    record.impact_status = impact_status or ''
    record.reason_analysis = _clean(reason_analysis, 2000)
    record.fault_object_name = _clean(fault_object_name, 100)
    record.fault_object_model = _clean(fault_object_model, 100)
    record.fault_object_sn = _clean(fault_object_sn, 100)
    record.category = ''
    record.updated_at = timezone.now()
    record.updated_by = created_by
    record.save()
    recompute_systems_health(record.tenant_id, [record.system_id], request=request)
    return record


def progress_overview_map(record_ids):
    """批量统计统一进展概览（列表聚合，单次查询，无 N+1）。

    - progress_count：SystemOperationProgress 行数（追加式时间线）；
    - latest_progress_at / latest_progress_content：按（处理时间, id）最新
      一条进展的时间与内容；无进展的记录返回零值，调用方无需再补默认值。
    返回 {record_id: {...}}。
    """
    record_ids = [int(i) for i in record_ids if i]
    if not record_ids:
        return {}
    latest_qs = SystemOperationProgress.objects.filter(
        record_id=OuterRef('record_id')).order_by('-handled_at', '-id')
    rows = (
        SystemOperationProgress.objects
        .filter(record_id__in=record_ids)
        .values('record_id')
        .annotate(
            progress_count=Count('id'),
            latest_progress_at=Subquery(latest_qs.values('handled_at')[:1]),
            latest_progress_content=Subquery(latest_qs.values('content')[:1]),
        )
    )
    overview = {
        record_id: {
            'progress_count': 0,
            'latest_progress_at': None,
            'latest_progress_content': '',
        }
        for record_id in record_ids
    }
    for row in rows:
        overview[row['record_id']] = row
    return overview


def progress_overview(record):
    """单条记录的进展概览（详情出口用），字段口径与列表聚合一致。"""
    return progress_overview_map([record.id]).get(record.id) or {
        'progress_count': 0,
        'latest_progress_at': None,
        'latest_progress_content': '',
    }


# "长期未关闭"判定天数：创建超过该天数仍未关闭的跟进中记录
STALE_OPEN_DAYS = 7

# 待办/积压口径：只统计"跟进中"（异常事件唯一需要用户持续处理的状态）。
# 已记录（留痕）同为合法稳定状态；正式故障的处置中由健康状态与故障列表暴露，
# 不混入跟进待办。
STAT_OPEN_STATUSES = [RECORD_STATUS_FOLLOWING_UP]


def compute_operation_statistics(tenant_id, occurred_from, occurred_to,
                                 now=None, with_trend=True, trend_limit_days=62,
                                 record_type=None):
    """运行与故障记录只读统计（租户内，时间范围用 __gte/__lt）。

    record_type 统计口径筛选：None（默认，全部类型）/ routine / abnormal /
    fault。返回：
    - totals：总数/跟进中/处置中故障/长期未关闭（跟进中超 7 天）/
      平均处理时长（小时，仅异常事件有 resolved_at 参与）；
    - by_status / by_type：状态与类型维度计数；
    - by_system：按系统计数（数量倒序，最多 50 个系统）；
    - trend：按自然日计数（total/fault），范围超过 trend_limit_days 天时为空。
    """
    now = now or timezone.now()
    query = SystemOperationRecord.objects.filter(
        tenant_id=tenant_id, occurred_at__gte=occurred_from, occurred_at__lt=occurred_to)
    if record_type:
        query = query.filter(record_type=record_type)
    totals = query.aggregate(
        total=Count('id'),
        following_up=Count('id', filter=Q(status=RECORD_STATUS_FOLLOWING_UP)),
        handling_fault=Count(
            'id', filter=Q(record_type=RECORD_TYPE_FAULT, status=RECORD_STATUS_HANDLING)),
    )
    # 长期未关闭：不限统计时间范围（问题积压跨范围仍需暴露），只看未终态 + 创建时长
    stale_boundary = now - timedelta(days=STALE_OPEN_DAYS)
    stale_query = SystemOperationRecord.objects.filter(
        tenant_id=tenant_id,
        status__in=STAT_OPEN_STATUSES,
        created_at__lt=stale_boundary,
    )
    if record_type:
        stale_query = stale_query.filter(record_type=record_type)
    totals['stale_open'] = stale_query.count()

    by_status = dict(
        query.values_list('status').annotate(total=Count('id')).order_by())
    by_type = dict(
        query.values_list('record_type').annotate(total=Count('id')).order_by())

    by_system = [
        {
            'system': row['system_id'],
            'system_name': row['system_name'],
            'total': row['total'],
            'following_up': row['following_up'],
            'handling_fault': row['handling_fault'],
        }
        for row in query.values(
            'system_id', 'system_name',
        ).annotate(
            total=Count('id'),
            following_up=Count('id', filter=Q(status=RECORD_STATUS_FOLLOWING_UP)),
            handling_fault=Count(
                'id', filter=Q(record_type=RECORD_TYPE_FAULT, status=RECORD_STATUS_HANDLING)),
        ).order_by('-total')[:50]
    ]

    # 平均处理时长在 Python 侧计算（DurationField 聚合在 MariaDB 上兼容性差）
    resolve_pairs = query.filter(
        resolved_at__isnull=False).values_list('resolved_at', 'created_at')
    durations = [
        (resolved - created).total_seconds()
        for resolved, created in resolve_pairs if resolved and created
    ]
    totals['avg_resolve_hours'] = (
        round(sum(durations) / len(durations) / 3600.0, 1) if durations else None)
    totals['resolved_count'] = len(durations)

    trend = []
    if with_trend:
        range_days = (occurred_to - occurred_from).days
        if 0 <= range_days <= trend_limit_days:
            buckets = {}
            for occurred_at, rec_type in query.values_list('occurred_at', 'record_type'):
                day = occurred_at.date().isoformat()
                bucket = buckets.setdefault(day, {'total': 0, 'fault': 0})
                bucket['total'] += 1
                if rec_type == RECORD_TYPE_FAULT:
                    bucket['fault'] += 1
            day = occurred_from.date()
            while day < occurred_to.date():
                key = day.isoformat()
                trend.append({
                    'date': key,
                    'total': buckets.get(key, {}).get('total', 0),
                    'fault': buckets.get(key, {}).get('fault', 0),
                })
                day += timedelta(days=1)
    return {
        'totals': totals,
        'by_status': by_status,
        'by_type': by_type,
        'by_system': by_system,
        'trend': trend,
    }
