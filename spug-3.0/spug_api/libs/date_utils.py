"""统一日期解析与范围过滤工具。

所有日期范围查询统一使用 __gte / __lt（B-tree 索引友好），
禁用 __date / __startswith（绕过索引，强制全表扫描）。

用法：
    from libs.date_utils import parse_date, date_range_filter, today_range, month_range

    # 解析日期字符串
    dt = parse_date('2026-07-29')

    # 对 DateTimeField 做范围过滤
    qs = date_range_filter(qs, 'created_at', start_date, end_date)

    # 获取今天的 datetime 范围
    start, end = today_range()
    qs = qs.filter(created_at__gte=start, created_at__lt=end)
"""
from datetime import datetime, timedelta, date
from typing import Optional, Tuple

from django.utils import timezone


def parse_date(s: str) -> datetime:
    """解析日期字符串为 datetime 对象。

    支持 'YYYY-MM-DD' 和 'YYYY-MM-DD HH:MM:SS' 格式。
    返回 naive datetime（项目 USE_TZ=False）。
    """
    if not s:
        raise ValueError('日期字符串不能为空')
    fmt = '%Y-%m-%d %H:%M:%S' if len(s) > 10 else '%Y-%m-%d'
    return datetime.strptime(s, fmt)


def parse_date_or_none(s: Optional[str]) -> Optional[datetime]:
    """解析日期字符串，空值返回 None 而不抛异常。"""
    if not s:
        return None
    return parse_date(s)


def date_range_filter(qs, field: str, start: Optional[str] = None, end: Optional[str] = None):
    """对 DateTimeField 做索引友好的日期范围过滤。

    使用 __gte / __lt（或 __lte）确保走 B-tree 索引，而非 DATE() 函数。

    Args:
        qs: Django QuerySet
        field: DateTimeField 字段名（如 'created_at'）
        start: 起始日期字符串 'YYYY-MM-DD'（含）或 'YYYY-MM-DD HH:MM:SS'
        end: 结束日期字符串。纯日期 'YYYY-MM-DD'（含当天，自动 +1 天转 __lt）；
             含时间 'YYYY-MM-DD HH:MM:SS'（精确到秒，用 __lte）

    Returns:
        过滤后的 QuerySet
    """
    start_dt = parse_date_or_none(start)
    if start_dt:
        qs = qs.filter(**{f'{field}__gte': start_dt})

    if end:
        end_dt = parse_date_or_none(end)
        if end_dt:
            # 纯日期（无时间）-> +1 天转 __lt（含当天所有记录）
            # 含时间 -> 直接 __lte（精确到秒）
            if len(end.strip()) <= 10:
                qs = qs.filter(**{f'{field}__lt': end_dt + timedelta(days=1)})
            else:
                qs = qs.filter(**{f'{field}__lte': end_dt})

    return qs


def today_range(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """返回今天的 datetime 范围 [start, end)。

    Returns:
        (today_00:00:00, tomorrow_00:00:00)
    """
    if now is None:
        now = timezone.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def month_range(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """返回本月的 datetime 范围 [start, end)。

    Returns:
        (本月1号_00:00:00, 下月1号_00:00:00)
    """
    if now is None:
        now = timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month


def date_to_datetime(d: date) -> datetime:
    """date 转 naive datetime（00:00:00）。"""
    return datetime.combine(d, datetime.min.time())


def date_range(d: date) -> Tuple[datetime, datetime]:
    """返回指定 date 的 datetime 范围 [start, end)。"""
    start = date_to_datetime(d)
    return start, start + timedelta(days=1)
