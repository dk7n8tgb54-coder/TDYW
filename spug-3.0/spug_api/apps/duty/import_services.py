# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""值班日志引入数据聚合层。

本文件负责聚合多个业务模块中可引入值班日志的摘要数据，按《模块间调用规范方案.md》
要求，所有跨模块调用必须走对方模块公开的 ``services.py``，禁止在此直接 import
其他业务模块的 models。

当前已接入的来源：
    - 运行日志：``apps.runlog.services.get_duty_import_items``

后续待接入（按规范方案第一阶段未覆盖，待对应模块提供 services 后再迁移）：
    - 干扰记录：``apps.interference.services.get_duty_import_items``
"""
import logging

from apps.runlog.services import get_duty_import_items as get_runlog_items

logger = logging.getLogger(__name__)


def get_import_records(date, user):
    """获取指定日期可引入值班日志的全部数据。

    Args:
        date (str): 目标日期，格式 ``YYYY-MM-DD``。
        user: 当前请求用户，用于各模块内部租户过滤。

    Returns:
        dict: ``{'date': date, 'runlog': [...], 'interference': [...]}``
    """
    return {
        'date': date,
        'runlog': get_runlog_items(date, user),
        # 干扰记录暂保留在视图层直接查询，待 interference 模块提供 services 后迁移
        'interference': _get_interference_items(date, user),
    }


def _get_interference_items(date, user):
    """获取指定日期可引入值班日志的干扰记录。

    TODO: 按《模块间调用规范方案.md》应迁移到 ``apps/interference/services.py``
    的 ``get_duty_import_items``。当前为兼容现状的过渡实现，待干扰记录模块
    提供 services 后替换为 ``get_interference_items(date, user)``。
    """
    from apps.interference.models import Interference
    from libs.tenant_utils import apply_tenant_filter
    from datetime import datetime as _dt, timedelta as _td

    # 用 datetime 范围替代 __startswith，确保走 B-tree 索引
    if isinstance(date, str):
        _d = _dt.strptime(date, '%Y-%m-%d')
    else:
        _d = _dt.combine(date, _dt.min.time())
    interferences = apply_tenant_filter(
        Interference.objects.all(), user
    ).filter(datetime__gte=_d, datetime__lt=_d + _td(days=1)).order_by('-id')

    return [
        {
            'id': f'interference_{r.id}',
            'source': 'interference',
            'title': f'{r.interference_type} - {r.frequency}',
            'sub_title': r.report_dept,
            'content': r.phenomenon,
        }
        for r in interferences
    ]
