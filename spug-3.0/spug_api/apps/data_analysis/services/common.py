"""共享工具：日期解析、区间过滤、分布格式化、月份填充。"""
import datetime
from django.db.models import Q
from django.db.models.functions import TruncMonth


def parse_date_range(request):
    """从 request.GET 解析日期范围，返回 (start_date, end_date, error_msg)。
    默认取最近 365 天，最大跨度 366 天。
    """
    today = datetime.date.today()
    default_start = today - datetime.timedelta(days=364)

    start_str = request.GET.get('start_date', '').strip()
    end_str = request.GET.get('end_date', '').strip()

    if not start_str:
        start_date = default_start
    else:
        try:
            start_date = datetime.datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            return None, None, 'start_date 格式应为 YYYY-MM-DD'

    if not end_str:
        end_date = today
    else:
        try:
            end_date = datetime.datetime.strptime(end_str, '%Y-%m-%d').date()
        except ValueError:
            return None, None, 'end_date 格式应为 YYYY-MM-DD'

    if start_date > end_date:
        return None, None, 'start_date 不能晚于 end_date'

    if (end_date - start_date).days > 365:
        return None, None, '日期范围不能超过 366 天'

    return start_date, end_date, None


def make_range_filter(start_date, end_date, field_name):
    """生成半开区间 [start 00:00:00, end+1day 00:00:00) 的 Q 过滤器。"""
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(
        end_date + datetime.timedelta(days=1), datetime.time.min
    )
    return Q(**{f'{field_name}__gte': start_dt, f'{field_name}__lt': end_dt})


def build_distribution(qs, field_name, top_n=10):
    """按字段值分组计数，返回分布列表。
    - 空值/空字符串归入 "未填写"
    - 取 Top N，其余归入 "其他"
    - percent 保留 1 位小数
    """
    # 先统计空值数量
    empty_count = qs.filter(
        Q(**{f'{field_name}__isnull': True}) | Q(**{f'{field_name}__exact': ''})
    ).count()

    # 非空值分组计数
    non_empty_qs = qs.exclude(
        Q(**{f'{field_name}__isnull': True}) | Q(**{f'{field_name}__exact': ''})
    )
    raw = _annotate_count(non_empty_qs, field_name)

    items = [{'name': str(row[field_name]), 'count': row['count']} for row in raw]

    if empty_count > 0:
        items.append({'name': '未填写', 'count': empty_count})

    # 重新排序
    items.sort(key=lambda x: x['count'], reverse=True)

    total = sum(item['count'] for item in items)
    result = []
    if len(items) <= top_n:
        for item in items:
            result.append({
                'name': item['name'],
                'count': item['count'],
                'percent': round(item['count'] / total * 100, 1) if total > 0 else 0.0,
            })
    else:
        top_items = items[:top_n]
        other_count = sum(item['count'] for item in items[top_n:])
        for item in top_items:
            result.append({
                'name': item['name'],
                'count': item['count'],
                'percent': round(item['count'] / total * 100, 1) if total > 0 else 0.0,
            })
        result.append({
            'name': '其他',
            'count': other_count,
            'percent': round(other_count / total * 100, 1) if total > 0 else 0.0,
        })

    return result


def _annotate_count(qs, field_name):
    """辅助函数：按字段值分组计数。"""
    from django.db.models import Count
    return (
        qs.values(field_name)
        .annotate(count=Count('id'))
        .order_by('-count')
    )


def build_monthly_trend(qs, date_field, start_date, end_date):
    """构建按月趋势数据，填充缺失月份为 0。
    返回 [{"month": "2026-01", "count": 0}, ...]
    """
    from django.db.models import Count
    qs = qs.exclude(**{f'{date_field}__isnull': True})
    raw_data = (
        qs.annotate(month=TruncMonth(date_field))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )
    raw_map = {}
    for row in raw_data:
        m = row['month']
        if m:
            key = m.strftime('%Y-%m') if hasattr(m, 'strftime') else str(m)[:7]
            raw_map[key] = row['count']

    # 生成完整月份序列
    result = []
    cur = datetime.date(start_date.year, start_date.month, 1)
    end_month = datetime.date(end_date.year, end_date.month, 1)
    while cur <= end_month:
        key = cur.strftime('%Y-%m')
        result.append({'month': key, 'count': raw_map.get(key, 0)})
        # 下个月
        if cur.month == 12:
            cur = datetime.date(cur.year + 1, 1, 1)
        else:
            cur = datetime.date(cur.year, cur.month + 1, 1)

    return result


def build_meta(start_date, end_date):
    """构建响应元数据。"""
    return {
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'timezone': 'Asia/Shanghai',
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def calc_rate(numerator, denominator):
    """计算百分比，返回字符串如 '66.7%'。"""
    if denominator == 0:
        return '0.0%'
    return f'{round(numerator / denominator * 100, 1)}%'
