# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提醒事项模块接口"""
import json
import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.views import View

from libs import json_response, JsonParser, Argument
from apps.account.models import User
from apps.logs.audit import record_audit_event

from .models import Reminder, ReminderLog

logger = logging.getLogger(__name__)

MODULE = 'reminder'

PERM_VIEW = 'home.reminder.view'
PERM_ADD = 'home.reminder.add'
PERM_EDIT = 'home.reminder.edit'
PERM_DELETE = 'home.reminder.delete'


def _can_manage(user, perm=PERM_VIEW):
    return bool(user.is_supper or user.has_perms([perm]))


def _current_date_key(now=None):
    now = now or timezone.now()
    return now.strftime('%Y-%m-%d')


def _validate_reminder_form(form):
    """校验提醒规则表单，返回 ((target_date, recipients), None) 或 (None, error_str)"""
    if len(form.name or '') > 100:
        return None, '事件名称长度不能超过100个字符'
    try:
        target_date = datetime.strptime(form.target_date, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None, '目标日格式错误，应为 YYYY-MM-DD'

    valid_types = ['none', 'daily', 'weekly', 'monthly', 'yearly']
    if form.repeat_type not in valid_types:
        return None, '重复类型错误'
    # 数据库 CheckConstraint 要求 >=1、列为 INT；上限与前端 InputNumber max 对齐，
    # 任何重复类型都不得越界，否则将触发 IntegrityError/Out of range 落入全局异常处理
    if not 1 <= form.repeat_interval <= 365:
        return None, '重复间隔必须在 1-365 之间'

    try:
        recipients = json.loads(form.recipient_users) if isinstance(form.recipient_users, str) else form.recipient_users
    except (json.JSONDecodeError, TypeError):
        return None, '接收人列表格式错误'
    if not recipients or not isinstance(recipients, list):
        return None, '请至少选择一个接收人'
    for r in recipients:
        if not isinstance(r, dict) or not r.get('id'):
            return None, '接收人列表格式错误'

    return (target_date, recipients), None


class ReminderView(View):
    """提醒事项规则 CRUD"""

    def get(self, request, pk=None):
        if not _can_manage(request.user, PERM_VIEW):
            return json_response(error='权限拒绝')
        if pk:
            obj = Reminder.objects.filter(pk=pk, is_deleted=False)
            if not request.user.is_supper:
                obj = obj.filter(tenant_id=request.user.tenant_id)
            obj = obj.first()
            if not obj:
                return json_response(error='提醒规则不存在')
            return json_response(obj.to_view())
        # 列表：超级管理员看全部，普通管理员按租户隔离
        qs = Reminder.objects.filter(is_deleted=False)
        if not request.user.is_supper:
            qs = qs.filter(tenant_id=request.user.tenant_id)
        qs = qs.order_by('-id')
        return json_response([r.to_view() for r in qs])

    @transaction.atomic()
    def post(self, request, pk=None):
        if not _can_manage(request.user, PERM_ADD if not pk else PERM_EDIT):
            return json_response(error='权限拒绝')
        form, error = JsonParser(
            Argument('name', required=True, help='事件名称'),
            Argument('enabled', type=bool, default=True),
            Argument('target_date', required=True, help='目标日'),
            Argument('repeat_type', default='none'),
            Argument('repeat_interval', type=int, default=1),
            Argument('content', default=''),
            Argument('recipient_users', required=True, help='接收人列表'),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        # 校验函数错误路径返回 (None, error_str)，不能嵌套解包，
        # 否则对 None 解包会抛 TypeError 落入全局异常处理
        result, error = _validate_reminder_form(form)
        if error:
            return json_response(error=error)
        target_date, recipients = result

        if pk:
            return self._save_update(request, pk, form, target_date, recipients)
        return self._save_create(request, form, target_date, recipients)

    def _save_update(self, request, pk, form, target_date, recipients):
        user = request.user
        obj_qs = Reminder.objects.filter(pk=pk, is_deleted=False)
        if not user.is_supper:
            obj_qs = obj_qs.filter(tenant_id=user.tenant_id)
        obj = obj_qs.first()
        if not obj:
            return json_response(error='提醒规则不存在')
        obj.name = form.name
        obj.enabled = form.enabled
        obj.target_date = target_date
        obj.repeat_type = form.repeat_type
        obj.repeat_interval = form.repeat_interval
        obj.content = form.content
        obj.recipient_users = json.dumps(recipients, ensure_ascii=False)
        obj.updated_at = timezone.now()
        obj.updated_by_id = user.id
        obj.updated_by_name = user.nickname or user.username
        obj.save(update_fields=[
            'name', 'enabled', 'target_date', 'repeat_type', 'repeat_interval',
            'content', 'recipient_users', 'updated_at', 'updated_by_id', 'updated_by_name',
        ])
        record_audit_event(request, 'update', MODULE, obj.id, obj.name, {
            'name': obj.name, 'enabled': obj.enabled, 'target_date': str(obj.target_date),
        })
        return json_response(obj.to_view())

    def _save_create(self, request, form, target_date, recipients):
        user = request.user
        obj = Reminder.objects.create(
            name=form.name,
            enabled=form.enabled,
            target_date=target_date,
            repeat_type=form.repeat_type,
            repeat_interval=form.repeat_interval,
            content=form.content,
            recipient_users=json.dumps(recipients, ensure_ascii=False),
            created_by_id=user.id,
            created_by_name=user.nickname or user.username,
            tenant_id=getattr(user, 'tenant_id', ''),
        )
        record_audit_event(request, 'create', MODULE, obj.id, obj.name, {
            'name': obj.name, 'target_date': str(obj.target_date),
        })
        return json_response(obj.to_view())

    def patch(self, request, pk=None):
        return self.post(request, pk)

    @transaction.atomic()
    def delete(self, request, pk):
        if not _can_manage(request.user, PERM_DELETE):
            return json_response(error='权限拒绝')
        obj_qs = Reminder.objects.filter(pk=pk, is_deleted=False)
        if not request.user.is_supper:
            obj_qs = obj_qs.filter(tenant_id=request.user.tenant_id)
        obj = obj_qs.first()
        if not obj:
            return json_response(error='提醒规则不存在')
        user = request.user
        obj.is_deleted = True
        obj.deleted_at = timezone.now()
        obj.deleted_by_id = user.id
        obj.deleted_by_name = user.nickname or user.username
        obj.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by_id', 'deleted_by_name'])
        record_audit_event(request, 'delete', MODULE, obj.id, obj.name, {
            'name': obj.name,
        })
        return json_response({})


class ReminderUsersView(View):
    """可选接收人列表

    刻意返回所有租户（科室）的用户：业务上科室A可以提醒科室B/C提交材料，
    需要跨科室选择接收人。 
    """

    def get(self, request):
        if not _can_manage(request.user, PERM_VIEW):
            return json_response(error='权限拒绝')
        users = User.objects.filter(
            is_active=True, deleted_at__isnull=True
        ).order_by('nickname', 'username')
        return json_response([
            {
                'id': u.id,
                'nickname': u.nickname or u.username,
                'username': u.username,
                'tenant_id': u.tenant_id,
            }
            for u in users
        ])


class ReminderPendingView(View):
    """获取当前用户未确认的提醒（懒创建）"""

    @transaction.atomic()
    def get(self, request):
        user = request.user
        today = timezone.now().date()
        date_key = _current_date_key()

        reminders = Reminder.objects.filter(enabled=True, is_deleted=False)
        for r in reminders:
            if not r.matches_today(today):
                continue
            recipients = r.get_recipients()
            if not any(u.get('id') == user.id for u in recipients):
                continue
            user_info = next((u for u in recipients if u.get('id') == user.id), {})
            ReminderLog.objects.get_or_create(
                reminder_id=r.id,
                user_id=user.id,
                date_key=date_key,
                defaults={
                    'user_name': user_info.get('nickname', user.nickname or user.username),
                    'is_acked': False,
                }
            )

        logs = ReminderLog.objects.select_related('reminder').filter(
            user_id=user.id, is_acked=False,
        ).order_by('-sent_at')
        result = []
        for log in logs:
            if log.reminder and not log.reminder.is_deleted and log.reminder.enabled:
                result.append(log.to_view())
        return json_response(result)


class ReminderAckView(View):
    """确认提醒"""

    @transaction.atomic()
    def post(self, request):
        form, error = JsonParser(
            Argument('log_id', type=int, required=True, help='提醒记录ID'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        user = request.user
        log = ReminderLog.objects.select_related('reminder').filter(
            pk=form.log_id, user_id=user.id, is_acked=False
        ).first()
        if not log:
            return json_response(error='提醒记录不存在或已确认')
        log.is_acked = True
        log.acked_at = timezone.now()
        log.save(update_fields=['is_acked', 'acked_at'])
        return json_response({'id': log.id, 'is_acked': True})


class ReminderStatusView(View):
    """今日确认状态看板"""

    def get(self, request):
        if not _can_manage(request.user, PERM_VIEW):
            return json_response(error='权限拒绝')
        date_key = _current_date_key()
        today = timezone.now().date()
        reminders = Reminder.objects.filter(is_deleted=False, enabled=True)
        if not request.user.is_supper:
            reminders = reminders.filter(tenant_id=request.user.tenant_id)
        reminders = reminders.order_by('-id')
        result = []
        for r in reminders:
            if not r.matches_today(today):
                continue
            recipients = r.get_recipients()
            logs = ReminderLog.objects.filter(
                reminder_id=r.id, date_key=date_key
            ).values_list('user_id', 'is_acked', 'acked_at', 'user_name')
            acked_ids = {log[0]: {'is_acked': log[1], 'acked_at': log[2], 'user_name': log[3]} for log in logs}
            recipient_status = []
            for rec in recipients:
                uid = rec.get('id')
                info = acked_ids.get(uid)
                recipient_status.append({
                    'id': uid,
                    'nickname': rec.get('nickname', ''),
                    'is_acked': info['is_acked'] if info else False,
                    'acked_at': info['acked_at'] if info else None,
                })
            result.append({
                'id': r.id,
                'name': r.name,
                'date_key': date_key,
                'total': len(recipients),
                'acked': len([s for s in recipient_status if s['is_acked']]),
                'recipients': recipient_status,
            })
        return json_response(result)
