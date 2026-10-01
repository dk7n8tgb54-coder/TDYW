# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""统一系统履历视图（步骤 3.4）。

边界：
- 只读：全局列表、按系统列表与导出；不提供新增、修改、删除接口——
  履历由业务动作经 event_services 自动生成（append-only），
  普通用户不能手工新增，已生成事件不能普通修改或物理删除；
- 事件通过正式系统 ID 关联并保存系统快照，列表仅返回事件自身内容；
  来源详情由前端按 source_type/source_id 跳转对应业务页面，
  来源页面独立重新校验对象权限与租户，履历接口不代理来源内容，
  不通过履历泄露敏感配置或其他租户数据；
- 导出需独立 export 权限并记录审计。
"""
import csv
import io
from datetime import datetime

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.pagination import paginate
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemEvent,
)
from apps.equipment_lifecycle.event_group_services import (
    GROUP_SOURCE_TYPES,
    MAIN_EVENT_TYPES,
    build_group_export_rows,
    collect_item_nodes,
    list_system_groups,
)

AUDIT_TARGET_EVENT = 'el_system_event'

SOURCE_TYPE_TEXT = {
    'fault': '故障',
    'ledger_item': '台账异常',
    'health': '健康状态',
    'config_snapshot': '配置快照',
}

DATETIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%dT%H:%M', '%Y-%m-%d')


def _parse_dt(value):
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _apply_type_filters(query, form, allowed_event_types, allowed_source_types):
    """事件类型/来源类型筛选：校验可选值并过滤（None 表示不限定类型集合）。"""
    if form.event_type:
        if form.event_type not in (allowed_event_types or SystemEvent.EVENT_TYPE_TEXT_MAP):
            return None, '事件类型筛选值不合法'
        query = query.filter(event_type=form.event_type)
    if form.source_type:
        if form.source_type not in (allowed_source_types or SystemEvent.EVENT_SOURCE_TYPE_VALUES):
            return None, '来源类型筛选值不合法'
        query = query.filter(source_type=form.source_type)
    return query, None


def _apply_time_filters(query, form):
    """发生时间范围筛选：用 __gte/__lt（项目禁用 DateTimeField __date 等查询）。"""
    occurred_from = _parse_dt(form.occurred_from) if form.occurred_from else None
    occurred_to = _parse_dt(form.occurred_to) if form.occurred_to else None
    if form.occurred_from and not occurred_from:
        return None, '发生时间起始格式不正确'
    if form.occurred_to and not occurred_to:
        return None, '发生时间截止格式不正确'
    if occurred_from:
        query = query.filter(occurred_at__gte=occurred_from)
    if occurred_to:
        query = query.filter(occurred_at__lt=occurred_to)
    return query, None


def _filtered_events(request, allowed_event_types=None, allowed_source_types=None):
    """公共过滤：租户 + 事件类型/来源/关键词/时间范围，返回 QuerySet。

    - allowed_event_types / allowed_source_types 提供时作为可选值校验集合，
      并将基础查询限定在这些类型内（事项聚合视图用它排除健康状态与
      配置快照事件）；缺省 None 保持原行为（全部事件类型，平铺接口不变）。
    """
    form, error = JsonParser(
        Argument('event_type', type=str, required=False),
        Argument('source_type', type=str, required=False),
        Argument('keyword', type=str, required=False),
        Argument('occurred_from', type=str, required=False),
        Argument('occurred_to', type=str, required=False),
    ).parse(request.GET)
    if error:
        return None, error
    query = apply_tenant_filter(SystemEvent.objects.all(), request.user)
    if allowed_event_types is not None:
        query = query.filter(event_type__in=allowed_event_types)
    if allowed_source_types is not None:
        query = query.filter(source_type__in=allowed_source_types)
    query, error = _apply_type_filters(
        query, form, allowed_event_types, allowed_source_types)
    if error:
        return None, error
    if form.keyword:
        query = query.filter(
            Q(title__icontains=form.keyword) | Q(source_no__icontains=form.keyword) |
            Q(system_code__icontains=form.keyword) | Q(system_name__icontains=form.keyword))
    return _apply_time_filters(query, form)


class SystemEventView(View):
    """全局系统履历列表（系统履历页面）。"""

    @auth('equipment_lifecycle.system_event.view')
    def get(self, request):
        query, error = _filtered_events(request)
        if error:
            return json_response(error=error)
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })


class SystemEventsUnderSystemView(View):
    """按系统查询履历（系统详情"系统履历"页签，单系统简化）。

    系统必须属于当前用户租户；只返回该系统自己的事件。
    """

    @auth('equipment_lifecycle.system_event.view')
    def get(self, request, pk):
        system = apply_tenant_filter(LifecycleSystem.objects.all(), request.user).filter(
            pk=pk).first()
        if not system:
            return json_response(error='系统不存在')
        form, error = JsonParser(
            Argument('event_type', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query = apply_tenant_filter(SystemEvent.objects.all(), request.user).filter(
            system=system)
        if form.event_type:
            if form.event_type not in SystemEvent.EVENT_TYPE_TEXT_MAP:
                return json_response(error='事件类型筛选值不合法')
            query = query.filter(event_type=form.event_type)
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })


class SystemEventExportView(View):
    @auth('equipment_lifecycle.system_event.export')
    def get(self, request):
        query, error = _filtered_events(request)
        if error:
            return json_response(error=error)
        headers = ['发生时间', '系统编号', '系统名称', '事件类型',
                   '来源类型', '来源编号', '事件摘要', '记录人']
        rows = []
        for item in query:
            rows.append([
                item.occurred_at.strftime('%Y-%m-%d %H:%M') if item.occurred_at else '',
                item.system_code,
                item.system_name,
                item.EVENT_TYPE_TEXT_MAP.get(item.event_type, item.event_type),
                SOURCE_TYPE_TEXT.get(item.source_type, item.source_type),
                item.source_no,
                item.title,
                item.created_by.username if item.created_by_id else '',
            ])
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        writer.writerows(rows)
        response = HttpResponse('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8')
        stamp = timezone.now().strftime('%Y%m%d%H%M%S')
        response['Content-Disposition'] = f'attachment; filename=el_system_events_{stamp}.csv'
        record_audit_event(request, 'export', AUDIT_TARGET_EVENT, '', '',
                           after_value={'total': len(rows)})
        return response


class SystemEventGroupView(View):
    """系统履历事项分组列表（按系统分组、按业务事项聚合，只读）。

    - 聚合在后端完成后分页（page 为系统分组页，默认每页 10 个系统）；
    - 健康状态与配置快照事件不参与事项聚合：健康状态经分组头当前状态与
      /systems/<pk>/system-events/?event_type=health 历史面板查看，
      SystemEvent 原始数据不变；
    - 事项节点时间线经 /system-event-groups/nodes/ 按需加载。
    """

    @auth('equipment_lifecycle.system_event.view')
    def get(self, request):
        query, error = _filtered_events(
            request, allowed_event_types=MAIN_EVENT_TYPES,
            allowed_source_types=GROUP_SOURCE_TYPES)
        if error:
            return json_response(error=error)
        page, page_size = paginate(request, default_page_size=10)
        return json_response(list_system_groups(request.user, query, page, page_size))


class SystemEventGroupNodesView(View):
    """单个事项的完整节点时间线（展开事项时按需加载，按发生时间升序）。

    台账异常转换节点已按 target_no 归并进故障事项，本接口返回与
    分组列表一致的归并结果，前端不需要自行拼接多个来源的节点。
    """

    @auth('equipment_lifecycle.system_event.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('system', type=int, required=True),
            Argument('source_type', type=str, required=True),
            Argument('source_id', type=str, required=True),
        ).parse(request.GET)
        if error:
            return json_response(error='参数不完整')
        if form.source_type not in GROUP_SOURCE_TYPES:
            return json_response(error='来源类型不合法')
        nodes, error = collect_item_nodes(
            request.user, form.system, form.source_type, form.source_id)
        if error:
            return json_response(error=error)
        return json_response({'data': [n.to_view() for n in nodes]})


class SystemEventGroupExportView(View):
    """系统履历事项分组导出（CSV，同一系统的事项连续输出）。

    列序：系统/事项最近更新时间/事项类型/事项编号/事项当前状态/事项摘要/
    首次发生时间/节点数量；节点级明细仍可用原 /system-events/export/。
    复用 system_event.export 权限并记录审计。
    """

    @auth('equipment_lifecycle.system_event.export')
    def get(self, request):
        query, error = _filtered_events(
            request, allowed_event_types=MAIN_EVENT_TYPES,
            allowed_source_types=GROUP_SOURCE_TYPES)
        if error:
            return json_response(error=error)
        rows = build_group_export_rows(request.user, query)
        headers = ['系统', '事项最近更新时间', '事项类型', '事项编号',
                   '事项当前状态', '事项摘要', '首次发生时间', '节点数量']
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([
                row[0],
                row[1].strftime('%Y-%m-%d %H:%M') if row[1] else '',
                row[2], row[3], row[4], row[5],
                row[6].strftime('%Y-%m-%d %H:%M') if row[6] else '',
                row[7],
            ])
        response = HttpResponse('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8')
        stamp = timezone.now().strftime('%Y%m%d%H%M%S')
        response['Content-Disposition'] = f'attachment; filename=el_system_event_groups_{stamp}.csv'
        record_audit_event(request, 'export', AUDIT_TARGET_EVENT, '', '',
                           after_value={'total': len(rows), 'kind': 'event_groups'})
        return response
