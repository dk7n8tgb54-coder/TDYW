# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""运行日志模块对外服务接口。

本文件只暴露稳定的、面向其他模块的查询能力，调用方（如值班日志模块）
不应直接引入 ``apps.runlog.models``，统一通过这里的接口获取数据。

详见项目根目录《模块间调用规范方案.md》。
"""
import logging

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


def get_duty_import_items(date, user):
    """获取指定日期可引入值班日志的运行日志动态。

    将本模块内部的 ``RunLog`` / ``RunLogUpdate`` 查询、租户过滤、字段映射
    全部封装在此，调用方只能拿到稳定的字典列表，不接触模型对象。

    Args:
        date (str): 目标日期，格式 ``YYYY-MM-DD``，按动态的 ``update_date`` 精确匹配。
        user: 当前请求用户，用于租户过滤。

    Returns:
        list[dict]: 每条记录形如::

            {
                'id': 'runlog_<动态ID>',
                'source': 'runlog',
                'title': '事件标题',
                'sequence': 1,
                'recorder': '记录人',
                'content': '动态内容',
            }
    """
    from .models import RunLog, RunLogUpdate

    # 1. 查询当日动态（按 update_date 精确匹配，保持原有排序）
    updates = apply_tenant_filter(
        RunLogUpdate.objects.filter(update_date=date), user
    ).order_by('update_date', 'sequence', 'id')

    if not updates:
        return []

    # 2. 批量查询关联事件，构建 id -> event_title 映射，避免 N+1
    runlog_ids = [u.runlog_id for u in updates]
    events = apply_tenant_filter(
        RunLog.objects.filter(pk__in=runlog_ids), user
    )
    title_map = {e.id: e.event_title for e in events}

    # 3. 组装稳定 DTO，标题优先取事件表（事件可能被改名），兜底用动态冗余字段
    return [
        {
            'id': f'runlog_{u.id}',
            'source': 'runlog',
            'title': title_map.get(u.runlog_id, u.event_title),
            'sequence': u.sequence,
            'recorder': u.recorder,
            'content': u.detail_content,
        }
        for u in updates
    ]
