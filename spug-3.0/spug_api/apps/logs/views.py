# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.db.models import Q
from django.utils import timezone
from datetime import datetime
from libs.mixins import AdminView
from libs import json_response, Argument, JsonParser
from libs.utils import get_request_real_ip
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

        # 分页参数边界保护：
        # - page 最小为 1，避免负数切片导致 Django QuerySet 异常
        # - page_size 限制在 10~100，避免一次性查询大量审计日志拖慢数据库
        page = max(form.page, 1)
        page_size = min(max(form.page_size, 10), 100)

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

        # 按时间范围筛选（created_at 已迁移为 DateTimeField，参数转为 datetime）
        if form.start_time:
            # 兼容 'YYYY-MM-DD' 和 'YYYY-MM-DD HH:MM:SS' 两种格式
            try:
                start_dt = datetime.strptime(form.start_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                start_dt = datetime.strptime(form.start_time, '%Y-%m-%d')
            queryset = queryset.filter(created_at__gte=start_dt)
        if form.end_time:
            try:
                end_dt = datetime.strptime(form.end_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                end_dt = datetime.strptime(form.end_time, '%Y-%m-%d')
            queryset = queryset.filter(created_at__lte=end_dt)

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
        start = (page - 1) * page_size
        end = start + page_size
        records = queryset[start:end]

        return json_response({
            'total': total,
            'page': page,
            'page_size': page_size,
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
            try:
                start_dt = datetime.strptime(form.start_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                start_dt = datetime.strptime(form.start_time, '%Y-%m-%d')
            queryset = queryset.filter(created_at__gte=start_dt)
        if form.end_time:
            try:
                end_dt = datetime.strptime(form.end_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                end_dt = datetime.strptime(form.end_time, '%Y-%m-%d')
            queryset = queryset.filter(created_at__lte=end_dt)
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
        result = [r.to_dict() for r in records]

        # 证据闭环：导出审计日志本身也要被审计
        # 记录导出条件、导出数量、导出人，便于追溯"谁导出了哪些审计数据"
        self._record_export_audit(request, form, len(result))

        return json_response(result)

    def _record_export_audit(self, request, form, export_count):
        """记录审计日志导出动作本身（action=export, target_type=audit）"""
        try:
            from apps.logs.audit import save_audit_log, _extract_user_agent
            # 构造导出条件摘要（仅记录筛选条件，不含数据）
            conditions = {}
            for field in ('username', 'action', 'target_type',
                          'is_success', 'start_time', 'end_time', 'keyword'):
                value = getattr(form, field, None)
                if value not in (None, ''):
                    conditions[field] = value
            save_audit_log(
                user_id=request.user.id,
                username=request.user.username,
                action='export',
                target_type='audit',
                target_name='操作审计日志',
                detail={
                    '操作': '导出审计日志',
                    '筛选条件': conditions,
                    '导出数量': export_count,
                },
                ip=get_request_real_ip(request.headers) if hasattr(request, 'headers') else '',
                is_success=True,
                tenant_id=getattr(request.user, 'tenant_id', 'default'),
                request_id=getattr(request, '_audit_request_id', None),
                user_agent=_extract_user_agent(request),
            )
        except Exception:
            # 导出审计记录失败不应阻断导出主流程
            import logging
            logging.getLogger(__name__).warning(
                '[AUDIT] 记录审计日志导出动作失败', exc_info=True
            )


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
