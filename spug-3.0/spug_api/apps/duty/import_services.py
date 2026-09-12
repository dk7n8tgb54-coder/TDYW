# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""值班日志引入数据聚合层。

本文件负责聚合多个业务模块中可引入值班日志的摘要数据，按《模块间调用规范方案.md》
要求，所有跨模块调用必须走对方模块公开的 ``services.py``，禁止在此直接 import
其他业务模块的 models。

当前已接入的来源：
    - 运行日志：``apps.runlog.services.get_duty_import_items``
    - 干扰事件：``apps.interference.services.get_duty_import_items``
"""
import logging

from apps.runlog.services import get_duty_import_items as get_runlog_items
from apps.interference.services import get_duty_import_items as get_interference_items

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
        'interference': get_interference_items(date, user),
    }
