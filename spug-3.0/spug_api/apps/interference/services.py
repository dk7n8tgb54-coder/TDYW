"""干扰模块对其他业务公开的只读服务。"""

from datetime import datetime, timedelta

from libs.tenant_utils import apply_tenant_filter

from apps.interference.models import InterferenceEvent


def get_duty_import_items(date, user):
    """返回指定日期可引入值班日志的事件摘要。"""
    if isinstance(date, str):
        day = datetime.strptime(date, '%Y-%m-%d')
    else:
        day = datetime.combine(date, datetime.min.time())
    events = apply_tenant_filter(
        InterferenceEvent.objects.filter(is_deleted=False), user
    ).filter(datetime__gte=day, datetime__lt=day + timedelta(days=1)).order_by('-id')
    return [
        {
            'id': f'interference_event_{event.id}',
            'source': 'interference',
            'title': event.interference_kind_code,
            'sub_title': event.flight_number or event.aircraft_no,
            'content': event.phenomenon,
        }
        for event in events
    ]
