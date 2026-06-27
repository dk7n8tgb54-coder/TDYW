# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.db.models import Q
from libs.mixins import AdminView
from libs import json_response, Argument, JsonParser
from apps.logs.models import AuditLog


class AuditLogView(AdminView):
    PERM_MAP = {
        'GET': 'system.audit.view',
    }

    def get(self, request):
        """查询审计日志，支持多条件筛选和分页"""
        form, error = JsonParser(
            Argument('page', type=int, default=1, required=False),
            Argument('page_size', type=int, default=20, required=False),
            Argument('username', type=str, required=False),
            Argument('action', type=str, required=False),
            Argument('target_type', type=str, required=False),
            Argument('is_success', type=bool, required=False),
            Argument('start_time', type=str, required=False),
            Argument('end_time', type=str, required=False),
            Argument('keyword', type=str, required=False),
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        queryset = AuditLog.objects.all()

        # 按用户名筛选
        if form.username:
            queryset = queryset.filter(username__icontains=form.username)

        # 按操作类型筛选
        if form.action:
            queryset = queryset.filter(action=form.action)

        # 按对象类型筛选
        if form.target_type:
            queryset = queryset.filter(target_type=form.target_type)

        # 按操作结果筛选
        if form.is_success is not None:
            queryset = queryset.filter(is_success=form.is_success)

        # 按时间范围筛选
        if form.start_time:
            queryset = queryset.filter(created_at__gte=form.start_time)
        if form.end_time:
            queryset = queryset.filter(created_at__lte=form.end_time)

        # 关键词搜索（搜索用户名、对象名称、详情）
        if form.keyword:
            queryset = queryset.filter(
                Q(username__icontains=form.keyword) |
                Q(target_name__icontains=form.keyword) |
                Q(detail__icontains=form.keyword)
            )

        # 非超管只能看自己租户的日志
        if not request.user.is_supper:
            tenant_id = getattr(request.user, 'tenant_id', 'default')
            queryset = queryset.filter(tenant_id=tenant_id)

        # 分页
        total = queryset.count()
        start = (form.page - 1) * form.page_size
        end = start + form.page_size
        records = queryset[start:end]

        return json_response({
            'total': total,
            'page': form.page,
            'page_size': form.page_size,
            'records': [r.to_dict() for r in records],
        })


class AuditLogExportView(AdminView):
    """审计日志导出视图（用于打印/导出）"""
    PERM_MAP = {
        'GET': 'system.audit.view',
    }

    def get(self, request):
        """导出审计日志（不分页，返回全部匹配记录）"""
        form, error = JsonParser(
            Argument('username', type=str, required=False),
            Argument('action', type=str, required=False),
            Argument('target_type', type=str, required=False),
            Argument('is_success', type=bool, required=False),
            Argument('start_time', type=str, required=False),
            Argument('end_time', type=str, required=False),
            Argument('keyword', type=str, required=False),
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        queryset = AuditLog.objects.all()

        # 与查询视图相同的筛选逻辑
        if form.username:
            queryset = queryset.filter(username__icontains=form.username)
        if form.action:
            queryset = queryset.filter(action=form.action)
        if form.target_type:
            queryset = queryset.filter(target_type=form.target_type)
        if form.is_success is not None:
            queryset = queryset.filter(is_success=form.is_success)
        if form.start_time:
            queryset = queryset.filter(created_at__gte=form.start_time)
        if form.end_time:
            queryset = queryset.filter(created_at__lte=form.end_time)
        if form.keyword:
            queryset = queryset.filter(
                Q(username__icontains=form.keyword) |
                Q(target_name__icontains=form.keyword) |
                Q(detail__icontains=form.keyword)
            )

        # 非超管只能看自己租户的日志
        if not request.user.is_supper:
            tenant_id = getattr(request.user, 'tenant_id', 'default')
            queryset = queryset.filter(tenant_id=tenant_id)

        # 限制最大导出数量
        records = queryset[:5000]

        return json_response([r.to_dict() for r in records])


class AuditLogTargetTypesView(AdminView):
    """获取所有操作对象类型（用于前端筛选下拉框）"""
    PERM_MAP = {
        'GET': 'system.audit.view',
    }

    def get(self, request):
        from apps.logs.audit import TARGET_MAP
        types = [
            {'value': info['type'], 'label': info['name']}
            for info in TARGET_MAP.values()
        ]
        # 去重
        seen = set()
        unique_types = []
        for t in types:
            if t['value'] not in seen:
                seen.add(t['value'])
                unique_types.append(t)
        return json_response(unique_types)


class AuditLogActionsView(AdminView):
    """获取所有操作类型（用于前端筛选下拉框）"""
    PERM_MAP = {
        'GET': 'system.audit.view',
    }

    def get(self, request):
        from apps.logs.models import AuditLog
        actions = [
            {'value': choice[0], 'label': choice[1]}
            for choice in AuditLog.ACTION_CHOICES
        ]
        return json_response(actions)
