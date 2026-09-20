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

AUDIT_TARGET_EVENT = 'el_system_event'

SOURCE_TYPE_TEXT = {
    'fault': '故障',
    'work_order': '工单',
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


def _filtered_events(request):
    """公共过滤：租户 + 事件类型/来源/关键词/时间范围，返回 QuerySet。"""
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
    if form.event_type:
        if form.event_type not in SystemEvent.EVENT_TYPE_TEXT_MAP:
            return None, '事件类型筛选值不合法'
        query = query.filter(event_type=form.event_type)
    if form.source_type:
        if form.source_type not in SystemEvent.EVENT_SOURCE_TYPE_VALUES:
            return None, '来源类型筛选值不合法'
        query = query.filter(source_type=form.source_type)
    if form.keyword:
        query = query.filter(
            Q(title__icontains=form.keyword) | Q(source_no__icontains=form.keyword) |
            Q(system_code__icontains=form.keyword) | Q(system_name__icontains=form.keyword))
    # 时间筛选用 __gte/__lt（项目禁用 DateTimeField __date 等查询）
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
