# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""运行记录服务层（2026-10，第一版 + 第二版闭环）。

职责：
- generate_runtime_record_no：运行记录编号生成（YX+日期+当日序号，口径与故障编号一致）；
- create_runtime_record：运行记录创建服务；
- convert_runtime_record_to_fault：运行记录转正式故障服务（须在
  health_recalc_lock + transaction.atomic 内调用，调用方负责锁与事务）；
- compute_runtime_statistics：运行记录只读统计（第二版，仅使用运行记录数据）。

履历规则（2026-10-05 第四版起：运行记录不再纳入系统履历）：
- 运行记录的创建、研判升级影响、转为故障均不再写 SystemEvent
  （历史已写入的履历事件保留原样，仅供回溯展示）；
- 正式故障进入系统履历：转为故障后故障侧"发生故障"履历由
  fault_services.create_fault_record 生成，后续处理状态以 SystemFault 为准。
"""
from contextlib import contextmanager
from datetime import timedelta

from django.db import connection
from django.utils import timezone

from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import (
    RUNTIME_RECORD_NO_PREFIX,
    RUNTIME_RECORD_NO_SEQ_LIMIT,
    RUNTIME_RECORD_STATUS_CONVERTED_FAULT,
    RUNTIME_RECORD_STATUS_FOLLOWING_UP,
    RUNTIME_RECORD_STATUS_RECORDED,
    RUNTIME_RECORD_TYPE_ABNORMAL,
    RUNTIME_RECORD_TYPE_ROUTINE,
    SystemFault,
    SystemRuntimeRecord,
)


class RuntimeRecordNoExhausted(Exception):
    """当日运行记录编号序号已用尽（YXyyyymmdd-9999 已占用）：
    fail-closed，不产生五位序号或重复编号，由调用方转为业务错误。"""


class RuntimeRecordLockTimeout(Exception):
    """运行记录编号锁获取超时：并发过高时 fail-closed，避免并发撞号。"""


class RuntimeRecordConvertError(Exception):
    """运行记录转故障业务校验失败（重复转换/缺少重新处置原因等）。"""


RUNTIME_RECORD_NO_LOCK_NAME = 'el_runtime_record_no'
RUNTIME_RECORD_NO_LOCK_TIMEOUT = 10


@contextmanager
def runtime_record_no_lock():
    """运行记录编号生成全局串行锁（GET_LOCK，防并发创建撞号）。

    用法（视图层）：在事务外获取锁 → 事务内完成查重 + 创建 → 事务提交 → 释放锁。
    ATOMIC_REQUESTS 下持锁视图必须以 non_atomic_requests 装配并在视图内
    显式开启事务（同故障视图的锁提交顺序约定）。
    """
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT GET_LOCK(%s, %s)',
                       [RUNTIME_RECORD_NO_LOCK_NAME, RUNTIME_RECORD_NO_LOCK_TIMEOUT])
        got = cursor.fetchone()[0]
        if got != 1:
            raise RuntimeRecordLockTimeout('系统繁忙，请稍后重试')
        try:
            yield
        finally:
            try:
                cursor.execute('SELECT RELEASE_LOCK(%s)', [RUNTIME_RECORD_NO_LOCK_NAME])
            except Exception:
                connection.close()
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def generate_runtime_record_no():
    """生成运行记录编号 YX{yyyymmdd}-{seq:04d}（须在创建事务内调用）。

    编号规则与故障编号（generate_fault_no）一致：
    - 日期取创建当天（不取用户填写的发生时间 occurred_at）；
    - 当日序号跨租户共享：按有效四位数字后缀的最大值加一（缺口不回填）；
    - 序号达 9999 后抛出 RuntimeRecordNoExhausted，整个创建事务回滚。
    """
    # USE_TZ=False 下 timezone.localdate() 会对 naive now 抛错，直接取本地日期
    prefix = RUNTIME_RECORD_NO_PREFIX + timezone.now().date().strftime('%Y%m%d') + '-'
    max_seq = 0
    existing = SystemRuntimeRecord.objects.filter(record_no__startswith=prefix).values_list(
        'record_no', flat=True)
    for record_no in existing:
        suffix = record_no[len(prefix):]
        if len(suffix) == 4 and suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    if max_seq >= RUNTIME_RECORD_NO_SEQ_LIMIT:
        raise RuntimeRecordNoExhausted(
            f'当日运行记录编号已达上限（{prefix}9999），请明日再创建')
    return f'{prefix}{max_seq + 1:04d}'


def _clean(value, limit):
    """文本入参清洗：None 视为空串、去首尾空白、截断到 limit。"""
    return (value or '').strip()[:limit]


def create_runtime_record(*, tenant_id, created_by, system, occurred_at, title,
                          description, registrar_name='', client_token='',
                          needs_follow_up=False,
                          measures_taken='', handling_result='', request=None,
                          category='', initial_reason='', impact_scope='',
                          record_type=RUNTIME_RECORD_TYPE_ABNORMAL):
    """运行记录创建服务（唯一创建入口，视图与潜在程序化入口共用）。

    - 新建要求 系统/发生时间/标题/情况描述/登记人（视图层校验必填），
      其余选填或默认值；
    - registrar_name 为登记人（手动输入的登记人姓名，多人以顿号分隔，
      参照故障登记人口径），与登录账号 created_by 独立；
    - 新建默认状态 recorded；needs_follow_up 仅作表单标记，跟进状态由
      追加处理进展触发（首条跟进记录进入跟进中）；
    - record_type 记录类型（routine 日常运行 / abnormal 异常事件，缺省
      abnormal 兼容旧请求）；routine 不进入异常流程，needs_follow_up
      强制 False；
    - 结构化补充字段（第二版）全部选填，默认空串，不增加录入负担；
    - 具体对象名称/对象型号/影响系统运行/标记重要字段已删除（2026-10-06）；
    - 运行记录不写系统履历（2026-10-05 第四版，历史事件保留）。
    """
    if record_type not in (RUNTIME_RECORD_TYPE_ROUTINE, RUNTIME_RECORD_TYPE_ABNORMAL):
        raise ValueError('记录类型取值不合法')
    is_routine = record_type == RUNTIME_RECORD_TYPE_ROUTINE
    record = SystemRuntimeRecord.objects.create(
        tenant_id=tenant_id,
        record_no=generate_runtime_record_no(),
        record_type=record_type,
        system=system,
        system_code=system.system_code,
        system_name=system.name,
        system_location=system.install_location,
        occurred_at=occurred_at,
        title=_clean(title, 200),
        description=_clean(description, 2000),
        registrar_name=_clean(registrar_name, 200),
        needs_follow_up=False if is_routine else bool(needs_follow_up),
        measures_taken=_clean(measures_taken, 1000),
        handling_result=_clean(handling_result, 1000),
        category=_clean(category, 20),
        initial_reason='' if is_routine else _clean(initial_reason, 500),
        impact_scope='' if is_routine else _clean(impact_scope, 200),
        status=SystemRuntimeRecord.STATUS_RECORDED,
        client_token=_clean(client_token, 64),
        created_by=created_by,
    )
    return record


def get_active_converted_fault(record):
    """记录已转换且未作废的正式故障（防重复转换判定）。"""
    return record.generated_faults.exclude(
        status=SystemFault.STATUS_CANCELLED).order_by('-id').first()


def convert_runtime_record_to_fault(*, record, created_by, request=None,
                                    occurred_at=None, phenomenon=None,
                                    re_dispose_reason=''):
    """运行记录转正式故障（须在 health_recalc_lock + transaction.atomic 内调用）。

    - record 必须已加行锁（select_for_update），防并发重复转换；
    - 转故障为独立动作，已记录（recorded）与跟进中（following_up）均可直接
      转换（第四版 2026-10-05，不再要求先研判）；
    - 已存在未作废故障 → 拒绝（不能静默重复创建）；仅存在已作废故障 →
      须填写重新处置原因（与台账异常转故障同一规则）；
    - 故障初始字段由运行记录带入：系统（外键+快照）、发生时间、标题+描述
      组装现象；故障影响属性按故障默认值（不影响系统运行，可在故障模块调整）；
    - source_type='runtime_record' + source_runtime_record 正式外键 +
      source_id 冗余，防同一记录重复转故障；
    - 转换与记录状态流转（→ converted_fault）同一事务；故障侧履历
      与健康重算由 create_fault_record 完成（运行记录不写履历）。

    返回 SystemFault 实例。
    """
    active_fault = get_active_converted_fault(record)
    if active_fault:
        raise RuntimeRecordConvertError(
            f'该运行记录已转故障（{active_fault.fault_no}），不能重复转换')
    cancelled_fault = record.generated_faults.order_by('-id').first()
    if cancelled_fault and not (re_dispose_reason or '').strip():
        raise RuntimeRecordConvertError(
            f'该运行记录曾转故障（{cancelled_fault.fault_no}，已撤销）。'
            f'如需重新处置请填写重新处置原因')

    if occurred_at is None:
        occurred_at = record.occurred_at
    if not phenomenon:
        phenomenon = f'[运行记录 {record.record_no}] {record.title}；{record.description}'

    fault = fault_services.create_fault_record(
        tenant_id=record.tenant_id,
        created_by=created_by,
        system=record.system,
        impact_status='',
        occurred_at=occurred_at,
        phenomenon=str(phenomenon)[:2000],
        reason_analysis=record.initial_reason,
        source_type=SystemFault.SOURCE_RUNTIME_RECORD,
        source_runtime_record=record,
        request=request,
    )
    record.status = SystemRuntimeRecord.STATUS_CONVERTED_FAULT
    record.needs_follow_up = False
    record.updated_at = timezone.now()
    record.updated_by = created_by
    record.save(update_fields=['status', 'needs_follow_up', 'updated_at', 'updated_by'])
    # 故障侧"发生故障"履历已在 create_fault_record 生成（运行记录本身
    # 不写履历，2026-10-05 第四版；历史记录侧事件保留仅供回溯）
    return fault


# "长期未关闭"判定天数：创建超过该天数仍未关闭的跟进中记录
RUNTIME_RECORD_STALE_DAYS = 7

# 长期未关闭口径与跟进待办一致：只统计"跟进中"（唯一需要用户持续处理的
# 状态）。已记录（留痕，含历史无需跟进）同为合法稳定状态，可长期保留，
# 不因未研判/未关闭计入积压；已完成/转故障/已关闭不产生后续动作。
RUNTIME_STAT_OPEN_STATUSES = [
    RUNTIME_RECORD_STATUS_FOLLOWING_UP,
]


def compute_runtime_statistics(tenant_id, occurred_from, occurred_to,
                               now=None, with_trend=True, trend_limit_days=62,
                               record_type=RUNTIME_RECORD_TYPE_ABNORMAL):
    """运行记录只读统计（租户内，时间范围用 __gte/__lt）。

    record_type 统计口径筛选：abnormal（默认，原有异常统计口径不变）/
    routine（日常运行统计）/ None（不限类型）。非法值由视图层校验。

    返回：
    - totals：总数/跟进中/转故障/长期未关闭（跟进中超 7 天）/平均处理时长（小时）；
    - by_status：状态维度计数（四状态原值：recorded/following_up/completed/
      converted_fault）；
    - by_system：按系统计数（数量倒序，最多 50 个系统）；
    - trend：按自然日计数（total/converted），范围超过 trend_limit_days 天时为空。
    平均处理时长 = 首次完成跟进时间 - 创建时间（仅有 resolved_at 的记录参与）。
    """
    from django.db.models import Count, Q

    now = now or timezone.now()
    query = SystemRuntimeRecord.objects.filter(
        tenant_id=tenant_id, occurred_at__gte=occurred_from, occurred_at__lt=occurred_to)
    if record_type:
        query = query.filter(record_type=record_type)
    totals = query.aggregate(
        total=Count('id'),
        following_up=Count('id', filter=Q(status=RUNTIME_RECORD_STATUS_FOLLOWING_UP)),
        converted_fault=Count('id', filter=Q(status=RUNTIME_RECORD_STATUS_CONVERTED_FAULT)),
    )
    # 长期未关闭：不限统计时间范围（问题积压跨范围仍需暴露），只看未终态 + 创建时长
    stale_boundary = now - timedelta(days=RUNTIME_RECORD_STALE_DAYS)
    stale_query = SystemRuntimeRecord.objects.filter(
        tenant_id=tenant_id,
        status__in=RUNTIME_STAT_OPEN_STATUSES,
        created_at__lt=stale_boundary,
    )
    if record_type:
        stale_query = stale_query.filter(record_type=record_type)
    totals['stale_open'] = stale_query.count()

    # 状态维度：四状态原值计数（旧状态已由迁移 0007 归一，无需再分组归并）
    by_status = dict(
        query.values_list('status').annotate(total=Count('id')).order_by())

    by_system = [
        {
            'system': row['system_id'],
            'system_name': row['system_name'],
            'total': row['total'],
            'following_up': row['following_up'],
            'converted_fault': row['converted_fault'],
        }
        for row in query.values(
            'system_id', 'system_name',
        ).annotate(
            total=Count('id'),
            following_up=Count('id', filter=Q(status=RUNTIME_RECORD_STATUS_FOLLOWING_UP)),
            converted_fault=Count('id', filter=Q(status=RUNTIME_RECORD_STATUS_CONVERTED_FAULT)),
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
            for occurred_at, status in query.values_list('occurred_at', 'status'):
                day = occurred_at.date().isoformat()
                bucket = buckets.setdefault(day, {'total': 0, 'converted_fault': 0})
                bucket['total'] += 1
                if status == RUNTIME_RECORD_STATUS_CONVERTED_FAULT:
                    bucket['converted_fault'] += 1
            day = occurred_from.date()
            while day < occurred_to.date():
                key = day.isoformat()
                trend.append({
                    'date': key,
                    'total': buckets.get(key, {}).get('total', 0),
                    'converted_fault': buckets.get(key, {}).get('converted_fault', 0),
                })
                day += timedelta(days=1)
    return {
        'totals': totals,
        'by_status': by_status,
        'by_system': by_system,
        'trend': trend,
    }
