# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统履历事项聚合服务（履历页面改造：事件流水 → 按系统分组的业务事项）。

边界：
- 纯只读查询聚合：不写 SystemEvent、不修改事件写入逻辑、不新增迁移，
  复用既有索引 (tenant_id, system, -occurred_at, -id) 与
  (tenant_id, source_type, source_id)；
- 聚合键 = 系统 + source_type + source_id；主列表只纳入业务事项类事件
  （fault/work_order/ledger/upgrade/inspection 存量），健康状态与配置快照
  事件默认排除（健康状态走分组头 + 独立历史面板，数据原样保留）；
- 台账转换节点（ledger_item）按 detail.target_no 归并进同系统的故障/工单
  事项，未命中目标时独立成项；节点级查询接口返回同样的归并结果；
- 分页按系统分组：先按"该系统筛选后最近事项时间"倒序切页，再仅对本页
  系统做事件级聚合，避免一次加载全部系统的节点；
- 事项当前状态/标题优先取业务表真实数据（故障、工单，同 app 内批量查询）；
  升级记录不反向依赖 apps.upgrade（upgrade 已正向依赖本 app），
  状态/标题取最新节点事件快照；
- 筛选条件（事件类型/来源/关键词/时间范围）由视图层构造 QuerySet 后传入，
  作用于节点级决定事项是否入选；事项汇总字段（节点数/首末时间/持续时间）
  基于该事项全部节点，与展开后的节点时间线一致。
"""
from collections import defaultdict

from django.db.models import Count, Max

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemEvent,
    SystemFault,
    SystemWorkOrder,
)

# 参与主履历事项聚合的事件类型（排除健康状态/配置快照，二者不按事项聚合）
MAIN_EVENT_TYPES = ('fault', 'work_order', 'ledger', 'upgrade', 'inspection')
# 主列表事项的来源类型（健康状态/配置快照来源不参与）
GROUP_SOURCE_TYPES = ('fault', 'work_order', 'ledger_item', 'upgrade', 'inspection_record')

SOURCE_TYPE_TO_EVENT_TYPE = {
    'fault': 'fault',
    'work_order': 'work_order',
    'ledger_item': 'ledger',
    'upgrade': 'upgrade',
    'inspection_record': 'inspection',
}

# 未关闭故障（当前状态口径，不随列表筛选变化）
OPEN_FAULT_STATUSES = (
    SystemFault.STATUS_PENDING, SystemFault.STATUS_HANDLING, SystemFault.STATUS_RECOVERED,
)

# 业务对象缺失时由最新节点动作派生状态文案（防御路径，正常数据取业务表）
_ACTION_STATUS_FALLBACK = {
    'fault': {'create': '待处置', 'recover': '已恢复', 'close': '已关闭', 'cancel': '已作废'},
    'work_order': {'create': '待派发', 'complete': '已完成', 'cancel': '已取消'},
    'upgrade': {'create': '处理中', 'complete': '已完成', 'rollback': '已回退'},
}


def _item_key(event):
    """事项聚合键：来源类型 + 来源对象 ID（缺省时退化为单事件独立事项）。"""
    return (event.source_type, event.source_id or '#%s' % event.id)


def _new_item(event):
    return {
        'source_type': event.source_type,
        'source_id': event.source_id,
        'event_type': SOURCE_TYPE_TO_EVENT_TYPE.get(event.source_type, event.event_type),
        'item_no': event.source_no,
        'nodes': [event],
        'ledger_sources': [],
    }


def _append_event(items, event):
    key = _item_key(event)
    item = items.get(key)
    if item is None:
        item = _new_item(event)
        items[key] = item
    else:
        item['nodes'].append(event)
    return item


def _aggregate_system_events(events):
    """把同一系统的事件（时间升序）聚合为事项；台账转换节点待归并。"""
    items = {}
    ledger_events = []
    for event in events:
        if event.source_type == 'ledger_item':
            ledger_events.append(event)
        else:
            _append_event(items, event)
    return items, ledger_events


def _merge_ledger_events(items, ledger_events):
    """台账异常转故障/工单节点归并：按 detail.target_no 匹配同系统事项编号。

    - 命中则并入目标事项（记录来源台账，节点计入目标事项时间线）；
    - 未命中目标（历史数据/目标缺失）保持独立事项。
    """
    no_index = {}
    for key, item in items.items():
        if key[0] in ('fault', 'work_order') and item['item_no']:
            no_index.setdefault(item['item_no'], key)
    for event in ledger_events:
        target_no = (event.get_detail().get('target_no') or '').strip()
        target_key = no_index.get(target_no) if target_no else None
        if target_key:
            item = items[target_key]
            item['nodes'].append(event)
            detail = event.get_detail()
            item['ledger_sources'].append({
                'ledger_no': detail.get('ledger_no', ''),
                'ledger_type': detail.get('ledger_type', ''),
                'item_name': detail.get('item_name', ''),
            })
        else:
            _append_event(items, event)


def _fault_level_text(item, fault_map):
    source_id = item['source_id']
    fault = fault_map.get(int(source_id)) if source_id.isdigit() else None
    if fault:
        return fault.level, SystemFault.LEVEL_TEXT_MAP.get(fault.level, fault.level)
    for node in item['nodes']:
        if node.source_type == 'fault':
            level = node.get_detail().get('level')
            if level:
                return level, SystemFault.LEVEL_TEXT_MAP.get(level, level)
    return '', ''


def _item_status(item, business_map):
    """事项当前状态：故障/工单取业务表真实状态，其余按事件快照派生。"""
    source_type, source_id = item['source_type'], item['source_id']
    business = None
    if source_id.isdigit():
        business = business_map.get(int(source_id))
    if business is not None:
        text_map = business.STATUS_TEXT_MAP
        return business.status, text_map.get(business.status, business.status)
    last = item['nodes'][-1]
    if source_type == 'upgrade':
        snapshot = last.get_detail().get('status')
        if snapshot:
            return '', snapshot
    fallback = _ACTION_STATUS_FALLBACK.get(source_type, {})
    return '', fallback.get(last.action, '')


def _item_title(item, business_map):
    source_type, source_id = item['source_type'], item['source_id']
    first = item['nodes'][0]
    if source_id.isdigit():
        business = business_map.get(int(source_id))
        if business is not None:
            if source_type == 'fault':
                return (business.phenomenon or first.title)[:100]
            if source_type == 'work_order':
                return (business.title or first.title)[:200]
    if source_type == 'upgrade':
        return (first.get_detail().get('upgrade_title') or first.title)[:200]
    return first.title


def _serialize_item(item, fault_map, order_map):
    nodes = item['nodes']
    first, last = nodes[0], nodes[-1]
    # 业务表按来源类型取，避免不同业务主键撞号（升级/台账 id 不查业务表）
    business_map = {}
    if item['source_type'] == 'work_order':
        business_map = order_map
    elif item['source_type'] == 'fault':
        business_map = fault_map
    status, status_text = _item_status(item, business_map)
    item_view = {
        'source_type': item['source_type'],
        'source_id': item['source_id'],
        'event_type': item['event_type'],
        'event_type_text': SystemEvent.EVENT_TYPE_TEXT_MAP.get(
            item['event_type'], item['event_type']),
        'item_no': item['item_no'],
        'title': _item_title(item, business_map),
        'status': status,
        'status_text': status_text or '',
        'first_occurred_at': first.occurred_at,
        'last_occurred_at': last.occurred_at,
        'node_count': len(nodes),
        'ledger_sources': item['ledger_sources'],
        'detail': first.get_detail(),
    }
    if item['source_type'] == 'fault':
        level, level_text = _fault_level_text(item, fault_map)
        item_view['level'] = level
        item_view['level_text'] = level_text
        # 故障持续时间口径：发生 → 恢复确认；未恢复（含已作废）为 null
        recover_at = next(
            (n.occurred_at for n in nodes if n.action == 'recover'), None)
        if recover_at and first.occurred_at:
            item_view['duration_seconds'] = max(
                int((recover_at - first.occurred_at).total_seconds()), 0)
    return item_view


def _business_maps(user, items_by_system):
    """批量取本页事项对应的故障/工单业务对象（同 app 内，租户过滤）。"""
    fault_ids, order_ids = set(), set()
    for items in items_by_system.values():
        for item in items:
            if item['source_id'].isdigit():
                if item['source_type'] == 'fault':
                    fault_ids.add(int(item['source_id']))
                elif item['source_type'] == 'work_order':
                    order_ids.add(int(item['source_id']))
    fault_map = order_map = {}
    if fault_ids:
        fault_map = {f.id: f for f in apply_tenant_filter(
            SystemFault.objects.all(), user).filter(pk__in=fault_ids)}
    if order_ids:
        order_map = {o.id: o for o in apply_tenant_filter(
            SystemWorkOrder.objects.all(), user).filter(pk__in=order_ids)}
    return fault_map, order_map


def _open_fault_counts(user, system_ids):
    """各系统未关闭故障数量（业务表当前状态口径，不随列表筛选变化）。"""
    if not system_ids:
        return {}
    rows = apply_tenant_filter(SystemFault.objects.all(), user).filter(
        system_id__in=system_ids, status__in=OPEN_FAULT_STATUSES,
    ).values('system_id').annotate(total=Count('id'))
    return {row['system_id']: row['total'] for row in rows}


def _system_header(system, events):
    if system is not None:
        return {
            'id': system.id,
            'system_code': system.system_code,
            'name': system.name,
            'health_status': system.health_status,
            'health_status_text': system.HEALTH_STATUS_TEXT_MAP.get(
                system.health_status, system.health_status),
        }
    # 防御路径：系统记录缺失时退回事件快照（正式外键 PROTECT，正常不触发）
    event = events[0]
    return {
        'id': event.system_id,
        'system_code': event.system_code,
        'name': event.system_name,
        'health_status': '',
        'health_status_text': '',
    }


def _build_page_groups(user, base_queryset, system_ids, last_at_map):
    """对已确定的一组系统做事件级聚合（按传入系统顺序输出）。"""
    events = list(base_queryset.filter(system_id__in=system_ids).order_by(
        'system_id', 'occurred_at', 'id'))
    events_by_system = defaultdict(list)
    for event in events:
        events_by_system[event.system_id].append(event)
    items_by_system = {}
    for system_id, system_events in events_by_system.items():
        items, ledger_events = _aggregate_system_events(system_events)
        _merge_ledger_events(items, ledger_events)
        items_by_system[system_id] = sorted(
            items.values(),
            key=lambda item: (item['nodes'][-1].occurred_at, item['nodes'][-1].id),
            reverse=True)
    fault_map, order_map = _business_maps(user, items_by_system)
    open_faults = _open_fault_counts(user, system_ids)
    system_map = {s.id: s for s in apply_tenant_filter(
        LifecycleSystem.objects.all(), user).filter(pk__in=system_ids)}
    groups = []
    for system_id in system_ids:
        system_events = events_by_system.get(system_id, [])
        items = items_by_system.get(system_id, [])
        groups.append({
            'system': _system_header(system_map.get(system_id), system_events),
            'item_count': len(items),
            'open_fault_count': open_faults.get(system_id, 0),
            'last_event_at': last_at_map[system_id],
            'items': [_serialize_item(item, fault_map, order_map) for item in items],
        })
    return groups


def list_system_groups(user, base_queryset, page, page_size):
    """按系统分组的事项列表：分组按筛选后最近事项时间倒序，分页以系统为单位。"""
    order_rows = base_queryset.values('system').annotate(
        last_at=Max('occurred_at')).order_by('-last_at', '-system')
    total = order_rows.count()
    start = (page - 1) * page_size
    page_rows = list(order_rows[start: start + page_size])
    system_ids = [row['system'] for row in page_rows]
    last_at_map = {row['system']: row['last_at'] for row in page_rows}
    if not system_ids:
        return {'data': [], 'total': total, 'page': page, 'page_size': page_size}
    groups = _build_page_groups(user, base_queryset, system_ids, last_at_map)
    return {'data': groups, 'total': total, 'page': page, 'page_size': page_size}


def build_group_export_rows(user, base_queryset):
    """导出全部匹配分组（不分页）：系统 → 事项按最近更新倒序，同系统连续。"""
    order_rows = list(base_queryset.values('system').annotate(
        last_at=Max('occurred_at')).order_by('-last_at', '-system'))
    if not order_rows:
        return []
    system_ids = [row['system'] for row in order_rows]
    last_at_map = {row['system']: row['last_at'] for row in order_rows}
    groups = _build_page_groups(user, base_queryset, system_ids, last_at_map)
    rows = []
    for group in groups:
        system_label = group['system']['name']
        for item in group['items']:
            rows.append([
                system_label,
                item['last_occurred_at'],
                item['event_type_text'],
                item['item_no'],
                item['status_text'],
                item['title'],
                item['first_occurred_at'],
                item['node_count'],
            ])
    return rows


def collect_item_nodes(user, system_id, source_type, source_id):
    """单个事项的完整节点时间线（升序），含归并进来的台账转换节点。"""
    system = apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
        pk=system_id).first()
    if not system:
        return None, '系统不存在'
    base = apply_tenant_filter(SystemEvent.objects.all(), user).filter(system=system)
    nodes = list(base.filter(source_type=source_type, source_id=str(source_id)))
    if source_type in ('fault', 'work_order') and nodes:
        item_no = nodes[0].source_no
        if item_no:
            ledger_nodes = base.filter(source_type='ledger_item')
            for event in ledger_nodes:
                detail = event.get_detail()
                if (detail.get('target_no') or '').strip() == item_no:
                    nodes.append(event)
    nodes.sort(key=lambda event: (event.occurred_at, event.id))
    return nodes, None
