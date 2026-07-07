# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views import View
from django.http import HttpResponse
from django.conf import settings
from django.db.models import Max, Count, Q
from django.db import DatabaseError
from django.utils.encoding import escape_uri_path
from django.utils import timezone
from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from libs import Argument, JsonParser
from datetime import datetime, timedelta
from collections import defaultdict
import os
import json
import logging

logger = logging.getLogger(__name__)


def media_url_to_path(url):
    """将附件 URL 转换为磁盘绝对路径，并校验路径安全（防止路径穿越）。

    附件 URL 形如 ``/media/runlog/images/xxx.png``，对应磁盘路径
    ``MEDIA_ROOT/runlog/images/xxx.png``。

    Raises:
        ValueError: URL 不是合法的媒体地址，或解析后的路径不在
            ``MEDIA_ROOT/runlog`` 目录下。
    """
    if not url or not url.startswith(settings.MEDIA_URL):
        raise ValueError('invalid media url')
    relative_path = url[len(settings.MEDIA_URL):].lstrip('/')
    full_path = os.path.abspath(os.path.join(settings.MEDIA_ROOT, relative_path))
    base_dir = os.path.abspath(os.path.join(settings.MEDIA_ROOT, 'runlog'))
    if not (full_path == base_dir or full_path.startswith(base_dir + os.sep)):
        raise ValueError('path outside runlog directory')
    return full_path


def clean_update_attachments(update):
    """删除单条动态关联的附件文件。

    供删除事件（级联）和删除单条动态共用。失败仅记录日志，不抛异常，
    以确保数据库清理不被文件清理失败阻塞。
    """
    if not update.attachments:
        return
    try:
        attachments = json.loads(update.attachments)
        for attachment_path in attachments:
            try:
                full_path = media_url_to_path(attachment_path)
            except ValueError:
                logger.warning(f'[RunLog] 跳过非法附件路径: {attachment_path}')
                continue
            if os.path.exists(full_path):
                os.remove(full_path)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f'[RunLog] 清理附件失败: {e}')


class RunLogView(View):
    """运行日志事件视图"""

    @auth('runlog.runlog.view')
    def get(self, request):
        """获取事件列表"""
        from .models import RunLog

        logs = apply_tenant_filter(RunLog.objects.all(), request.user)

        # 筛选参数 - 从 request.GET 获取
        filters = request.GET.dict()
        if filters.get('status'):
            logs = logs.filter(status=filters['status'])
        if filters.get('severity'):
            logs = logs.filter(severity=filters['severity'])
        if filters.get('event_type'):
            logs = logs.filter(event_type=filters['event_type'])
        if filters.get('responsible_user_name'):
            logs = logs.filter(responsible_user_name__icontains=filters['responsible_user_name'])
        if filters.get('system_name'):
            logs = logs.filter(system_name__icontains=filters['system_name'])
        if filters.get('date'):
            logs = logs.filter(created_at__date=filters['date'])
        # 日期范围筛选：使用明确的 start_date/end_date 字段，与 PDF 导出接口保持一致
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        if start_date:
            logs = logs.filter(created_at__date__gte=start_date)
        if end_date:
            logs = logs.filter(created_at__date__lte=end_date)

        # 分页参数
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))

        # 排序和分页
        logs = logs.order_by('-created_at', '-id')

        # 获取系统名称列表（用于筛选）- 必须在切片前
        system_names = [x['system_name'] for x in logs.order_by('system_name').values('system_name').distinct()]

        # 分页处理
        total_count = logs.count()
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        logs = logs[start_index:end_index]

        return json_response({
            'system_names': system_names,
            'logs': [x.to_view() for x in logs],
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_count': total_count,
                'total_pages': (total_count + page_size - 1) // page_size
            }
        })
    
    @auth('runlog.runlog.add')
    def post(self, request):
        """创建事件（必须包含首次动态）"""
        from .models import RunLog, RunLogUpdate
        
        form, error = JsonParser(
            Argument('event_title', help='事件标题不能为空'),
            Argument('event_type', help='事件类型不能为空'),
            Argument('system_name', help='系统名称不能为空'),
            Argument('severity', required=False, default='P2'),
            Argument('responsible_user_id', type=int, required=False),
            Argument('responsible_user_name', required=False),
            Argument('first_update', type=dict, required=False, default={}),
        ).parse(request.body)
        
        if error is None:
            # 验证首次动态必填
            first_update = form.first_update
            if not first_update.get('update_date'):
                return json_response(error='首次动态内容不能为空')
            
            # 创建事件
            log_data = {
                'event_title': form.event_title,
                'event_type': form.event_type,
                'system_name': form.system_name,
                'severity': form.severity,
                'responsible_user_id': form.responsible_user_id,
                'responsible_user_name': form.responsible_user_name,
                'status': 'in_progress',
                'created_by': request.user,
            }
            assign_tenant_id(log_data, request.user)
            event = RunLog.objects.create(**log_data)
            
            # 创建首次动态
            editable_until = timezone.now() + timedelta(hours=24)
            
            # 计算序号
            max_seq = RunLogUpdate.objects.filter(
                runlog_id=event.id,
                update_date=first_update['update_date']
            ).aggregate(Max('sequence'))['sequence__max'] or 0
            
            # duty_person 空字符串按 None 处理
            first_duty_person = first_update.get('duty_person')
            if first_duty_person:
                first_duty_person = first_duty_person.strip()
            RunLogUpdate.objects.create(
                runlog_id=event.id,
                event_title=event.event_title,
                update_date=first_update['update_date'],
                sequence=1,
                recorder=request.user.nickname,
                detail_content=first_update.get('detail_content', ''),
                duty_person=first_duty_person or None,
                editable_until=editable_until,
                created_by=request.user,
                tenant_id=request.user.tenant_id,
            )
            
            # 更新统计信息
            event.update_count = 1
            event.first_update_date = first_update['update_date']
            event.last_update_date = first_update['update_date']
            event.save()
        
        return json_response(error=error)
    
    @auth('runlog.runlog.edit')
    def put(self, request):
        """更新事件（含状态流转）"""
        from .models import RunLog
        
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('event_type', required=False),
            Argument('system_name', required=False),
            Argument('severity', required=False),
            Argument('responsible_user_id', type=int, required=False),
            Argument('responsible_user_name', required=False),
            Argument('status', required=False),
            Argument('resolution', required=False),
        ).parse(request.body)
        
        if error is None:
            event = apply_tenant_filter(RunLog.objects.filter(pk=form.id), request.user).first()
            if not event:
                return json_response(error='无权限操作')
            
            # 可编辑字段
            editable_fields = ['event_type', 'system_name', 'severity',
                             'responsible_user_id', 'responsible_user_name']
            for field in editable_fields:
                if hasattr(form, field) and getattr(form, field) is not None:
                    setattr(event, field, getattr(form, field))
            
            # 状态流转控制
            if form.status and form.status != event.status:
                status_rules = {
                    'in_progress': ['resolved'],
                    'resolved': ['in_progress', 'verified', 'closed'],  # 允许回退 + 验证/归档
                    'verified': ['closed', 'in_progress'],
                    'closed': ['voided'],
                    'voided': [],
                }
                
                if form.status not in status_rules.get(event.status, []):
                    return json_response(error='不允许的状态流转')

                old_status = event.status

                # 如果填写了处理措施，更新相关信息
                if form.resolution:
                    event.resolution = form.resolution
                    event.verifier_id = request.user.id
                    event.verifier_name = request.user.username
                    event.verified_at = timezone.now()
                    event.closed_at = timezone.now()

                event.status = form.status

                # 证据闭环：resolved/verified/closed/voided 时写证据事件 + 快照哈希
                if form.status in ('resolved', 'verified', 'closed', 'voided'):
                    _record_runlog_evidence(event, form.status, request.user)
            
            event.updated_by = request.user
            event.updated_at = timezone.now()
            event.save()
        
        return json_response(error=error)
    
    @auth('runlog.runlog.del')
    def delete(self, request):
        """删除事件（级联删除动态及附件）"""
        from .models import RunLog, RunLogUpdate

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)

        if error is None:
            event = apply_tenant_filter(RunLog.objects.filter(pk=form.id), request.user).first()
            if not event:
                return json_response(error='无权限操作')

            # 获取关联的所有动态记录（需租户过滤）
            updates = apply_tenant_filter(
                RunLogUpdate.objects.filter(runlog_id=event.id),
                request.user
            )

            logger.info(f'[RunLog] 删除事件 ID={event.id}, 关联动态数={updates.count()}')

            # 清理附件文件（复用共享函数）
            for update in updates:
                clean_update_attachments(update)

            # 级联删除动态记录
            updates.delete()

            # 删除主表单
            event.delete()

        return json_response(error=error)


class RunLogUpdateView(View):
    """运行日志动态视图"""
    
    @auth('runlog.runlog.update_add')
    def post(self, request):
        """添加动态"""
        from .models import RunLog, RunLogUpdate

        form, error = JsonParser(
            Argument('runlog_id', type=int, help='请指定关联事件'),
            Argument('update_date', help='请选择日期'),
            Argument('recorder', required=False),
            Argument('detail_content', help='请输入详细记录'),
            Argument('duty_person', required=False),
            # attachments 字段已废弃，即使前端传入也会被忽略（兜底防绕过）
        ).parse(request.body)

        if error is None:
            # 验证事件存在且有权限
            event = apply_tenant_filter(RunLog.objects.filter(pk=form.runlog_id), request.user).first()
            if not event:
                return json_response(error='无权限操作')

            # 计算序号（同一天内的序号）
            max_seq = apply_tenant_filter(
                RunLogUpdate.objects.filter(
                    runlog_id=form.runlog_id,
                    update_date=form.update_date
                ),
                request.user
            ).aggregate(Max('sequence'))['sequence__max'] or 0

            # 设置可修改截止时间（24小时）
            editable_until = timezone.now() + timedelta(hours=24)

            # 创建动态（不再保存 attachments，历史数据保留不动）
            # duty_person 空字符串按 None 处理
            duty_person = form.duty_person.strip() if form.duty_person else None
            update_data = {
                'runlog_id': form.runlog_id,
                'event_title': event.event_title,
                'update_date': form.update_date,
                'sequence': max_seq + 1,
                'recorder': request.user.nickname,
                'detail_content': form.detail_content,
                'duty_person': duty_person or None,
                'editable_until': editable_until,
                'created_by': request.user,
            }
            assign_tenant_id(update_data, request.user)
            update = RunLogUpdate.objects.create(**update_data)

            # 更新事件统计信息
            # 注意：直接统计该事件的所有动态，不使用租户过滤
            # 因为动态已经通过 runlog_id 关联到事件，runlog_id 本身已受租户控制
            event.update_count = RunLogUpdate.objects.filter(runlog_id=form.runlog_id).count()

            # 如果是第一条动态，更新首次动态日期
            if event.update_count == 1:
                event.first_update_date = form.update_date

            event.last_update_date = form.update_date
            event.save()

        return json_response(error=error)

    @auth('runlog.runlog.update_edit')
    def put(self, request):
        """编辑动态（24小时内）"""
        from .models import RunLog, RunLogUpdate

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('update_date', required=False),
            Argument('recorder', required=False),
            Argument('detail_content', help='请输入详细记录'),
            Argument('duty_person', required=False),
            # attachments 字段已废弃，即使前端传入也会被忽略（兜底防绕过）
        ).parse(request.body)

        if error is None:
            update = RunLogUpdate.objects.filter(pk=form.id).first()
            if not update:
                return json_response(error='动态不存在', code=404)

            # 租户过滤
            update = apply_tenant_filter(
                RunLogUpdate.objects.filter(pk=update.id),
                request.user
            ).first()
            if not update:
                return json_response(error='无权限操作', code=403)

            # 检查是否可修改：创建者或超级管理员在24小时内可编辑
            if not update.can_edit(request.user):
                return json_response(error='该动态不可编辑（仅创建者或管理员在24小时内可修改）', code=403)

            # 更新字段（不再更新 attachments，历史数据保留不动）
            # duty_person 空字符串按 None 处理
            if form.update_date:
                update.update_date = form.update_date
            update.recorder = request.user.nickname
            update.detail_content = form.detail_content
            if hasattr(form, 'duty_person'):
                duty_person = form.duty_person.strip() if form.duty_person else None
                update.duty_person = duty_person or None
            update.save()

            event = apply_tenant_filter(RunLog.objects.filter(pk=update.runlog_id), request.user).first()
            if event:
                latest_update = apply_tenant_filter(
                    RunLogUpdate.objects.filter(runlog_id=update.runlog_id),
                    request.user
                ).order_by('-update_date', '-sequence', '-id').first()
                event.update_count = apply_tenant_filter(
                    RunLogUpdate.objects.filter(runlog_id=update.runlog_id),
                    request.user
                ).count()
                event.last_update_date = latest_update.update_date if latest_update else None
                event.updated_at = timezone.now()
                event.updated_by = request.user
                event.save()

        return json_response(error=error)
    
    @auth('runlog.runlog.update_del')
    def delete(self, request):
        """删除动态"""
        from .models import RunLogUpdate, RunLog
        
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        
        if error is None:
            update = RunLogUpdate.objects.filter(pk=form.id).first()
            if not update:
                return json_response(error='动态不存在', code=404)

            # 租户过滤
            update = apply_tenant_filter(
                RunLogUpdate.objects.filter(pk=update.id),
                request.user
            ).first()
            if not update:
                return json_response(error='无权限操作', code=403)

            # 清理该动态的附件文件（在删除数据库记录前）
            clean_update_attachments(update)

            runlog_id = update.runlog_id
            update.delete()

            # 更新事件统计信息
            event = apply_tenant_filter(RunLog.objects.filter(pk=runlog_id), request.user).first()
            if not event:
                return json_response(error='事件不存在', code=404)

            # 使用租户过滤查询动态记录
            updates = apply_tenant_filter(
                RunLogUpdate.objects.filter(runlog_id=runlog_id),
                request.user
            )

            event.update_count = updates.count()
            if event.update_count > 0:
                last_update = updates.order_by('-update_date', '-sequence').first()
                event.last_update_date = last_update.update_date
                # 更新首次动态日期
                first_update = updates.order_by('update_date', 'sequence').first()
                event.first_update_date = first_update.update_date
            else:
                event.last_update_date = None
                event.first_update_date = None
            event.save()

        return json_response(error=error)


class RunLogRepairView(View):
    """运行日志修复视图 - 修复 update_count 和 tenant_id 不一致问题"""

    @auth('runlog.runlog.edit')
    def post(self, request):
        """
        修复所有事件的 update_count 统计，以及动态记录的 tenant_id 不一致问题
        - 如果动态的 tenant_id 与关联事件的 tenant_id 不一致，修正为与事件一致
        - 同时重新计算 update_count
        """
        from .models import RunLog, RunLogUpdate

        try:
            # 获取所有事件
            events = apply_tenant_filter(RunLog.objects.all(), request.user)
            fixed_count = 0
            fixed_tenant_count = 0
            error_count = 0

            for event in events:
                try:
                    # 1. 先修正 tenant_id 不一致的动态记录
                    mismatched_updates = RunLogUpdate.objects.filter(
                        runlog_id=event.id,
                    ).exclude(tenant_id=event.tenant_id)

                    for update in mismatched_updates:
                        old_tenant = update.tenant_id
                        update.tenant_id = event.tenant_id
                        update.save()
                        fixed_tenant_count += 1
                        logger.info(f'[RunLog修复] 动态ID={update.id}, tenant_id: {old_tenant} -> {event.tenant_id} (关联事件ID={event.id})')

                    # 2. 重新计算 update_count
                    actual_count = RunLogUpdate.objects.filter(runlog_id=event.id).count()

                    # 如果不一致，则修复
                    if event.update_count != actual_count:
                        old_count = event.update_count
                        event.update_count = actual_count

                        # 同时更新首尾日期
                        if actual_count > 0:
                            updates = RunLogUpdate.objects.filter(runlog_id=event.id).order_by('update_date', 'sequence', 'id')

                            first_update = updates.first()
                            last_update = updates.last()

                            if first_update:
                                event.first_update_date = first_update.update_date
                            if last_update:
                                event.last_update_date = last_update.update_date
                        else:
                            event.first_update_date = None
                            event.last_update_date = None

                        event.save()
                        fixed_count += 1
                        logger.info(f'[RunLog修复] 事件ID={event.id}, update_count: {old_count} -> {actual_count}')

                except Exception as e:
                    error_count += 1
                    logger.warning(f'[RunLog修复] 事件ID={event.id} 修复失败: {str(e)}')

            return json_response({
                'status': 'ok',
                'message': f'修复完成: 修正租户 {fixed_tenant_count} 条, 修复计数 {fixed_count} 条, 失败 {error_count} 条'
            })

        except Exception as e:
            logger.error(f'[RunLog修复] 修复过程出错: {str(e)}', exc_info=True)
            return json_response(error=f'修复失败: {str(e)}')


class EventTypeConfigView(View):
    """事件类型配置视图（全局配置，所有租户共享，仅超级管理员可管理）"""

    def get(self, request):
        """获取所有启用的的事件类型"""
        from .models import EventTypeConfig

        # 全局查询，不再租户过滤
        items = EventTypeConfig.objects.filter(is_active=True).order_by('id')
        return json_response([x.to_view() for x in items])

    def post(self, request):
        """新增事件类型（仅超级管理员）"""
        from .models import EventTypeConfig
        from libs.tenant_utils import is_superuser

        # 权限检查：仅超级管理员
        if not is_superuser(request.user):
            return json_response(error='无权限操作，仅超级管理员可管理事件类型', code=403)

        form, error = JsonParser(
            Argument('name', help='类型名称不能为空'),
        ).parse(request.body)

        if error is None:
            # 检查名称是否重复
            existing = EventTypeConfig.objects.filter(name=form.name)
            if existing.exists():
                return json_response(error='该类型名称已存在')

            data = {
                'name': form.name,
                'is_active': True,
                'created_by': request.user,
            }
            obj = EventTypeConfig.objects.create(**data)
            return json_response(obj.to_view())

        return json_response(error=error)

    def put(self, request):
        """编辑事件类型（仅超级管理员）"""
        from .models import EventTypeConfig
        from libs.tenant_utils import is_superuser

        # 权限检查：仅超级管理员
        if not is_superuser(request.user):
            return json_response(error='无权限操作，仅超级管理员可管理事件类型', code=403)

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('name', required=False),
            Argument('is_active', type=bool, required=False),
        ).parse(request.body)

        if error is None:
            obj = EventTypeConfig.objects.filter(pk=form.id).first()
            if not obj:
                return json_response(error='类型不存在', code=404)

            if form.name and form.name != obj.name:
                # 检查新名称是否重复
                if EventTypeConfig.objects.filter(name=form.name).exclude(pk=form.id).exists():
                    return json_response(error='该类型名称已存在')
                obj.name = form.name
            if form.is_active is not None:
                obj.is_active = form.is_active
            obj.save()
            return json_response(obj.to_view())

        return json_response(error=error)

    def delete(self, request):
        """删除事件类型（软删除：仅超级管理员）"""
        from .models import EventTypeConfig
        from libs.tenant_utils import is_superuser

        # 权限检查：仅超级管理员
        if not is_superuser(request.user):
            return json_response(error='无权限操作，仅超级管理员可管理事件类型', code=403)

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)

        if error is None:
            obj = EventTypeConfig.objects.filter(pk=form.id).first()
            if not obj:
                return json_response(error='类型不存在', code=404)

            # 软删除：设为非活跃
            obj.is_active = False
            obj.save()
            return json_response({'status': 'ok'})

        return json_response(error=error)


class RunLogStatisticsView(View):
    """运行日志统计视图（已优化）"""

    @auth('runlog.runlog.view')
    def get(self, request):
        """
        获取统计数据（优化版本）

        优化内容：
        - 2次聚合查询替代12次独立查询
        - 租户ID有效性校验
        - 7天内无数据时的边界处理
        - 数据库异常分类处理
        - 详细的日志记录
        """
        from .models import RunLog

        # 在try外定义tenant_id，避免异常处理时NameError
        tenant_id = request.user.tenant_id

        try:
            logs = apply_tenant_filter(RunLog.objects.all(), request.user)

            # 边界条件1：校验租户ID有效性
            if not tenant_id:
                logger.warning(f"无效的租户ID: {tenant_id}, 请求来源: {request.META.get('REMOTE_ADDR')}")
                return json_response(error='无效的租户ID')

            now = datetime.now()

            # 边界条件2：初始化统计结果，避免KeyError（7天内无数据时）
            status_stats = {}
            for status, text in [('in_progress', '处理中'), ('resolved', '已解决')]:
                status_stats[status] = {'count': 0, 'text': text}

            severity_stats = {}
            for severity, text in [('P0', '紧急'), ('P1', '重要'), ('P2', '一般')]:
                severity_stats[severity] = {'count': 0, 'text': text}

            date_stats = defaultdict(int)
            for i in range(7):
                date = (now - timedelta(days=i)).strftime('%Y-%m-%d')
                date_stats[date] = 0

            # 边界条件3：异常捕获（数据库查询失败）
            # 查询1：聚合统计状态和级别
            agg_stats = logs.aggregate(
                in_progress_count=Count('id', filter=Q(status='in_progress')),
                resolved_count=Count('id', filter=Q(status='resolved')),
                p0_count=Count('id', filter=Q(severity='P0')),
                p1_count=Count('id', filter=Q(severity='P1')),
                p2_count=Count('id', filter=Q(severity='P2'))
            )

            # 更新状态统计
            status_stats['in_progress']['count'] = agg_stats['in_progress_count'] or 0
            status_stats['resolved']['count'] = agg_stats['resolved_count'] or 0

            # 更新级别统计
            severity_stats['P0']['count'] = agg_stats['p0_count'] or 0
            severity_stats['P1']['count'] = agg_stats['p1_count'] or 0
            severity_stats['P2']['count'] = agg_stats['p2_count'] or 0

            # 查询2：日期分组统计（created_at 已迁移为 DateTimeField，用 __date 查找）
            start_date = (now - timedelta(days=6)).date()
            end_date = now.date()
            logs_by_date = logs.filter(
                created_at__date__gte=start_date,
                created_at__date__lte=end_date,
            ).values('created_at__date').annotate(count=Count('id'))

            for item in logs_by_date:
                day = item['created_at__date']
                date_str = day.strftime('%Y-%m-%d') if hasattr(day, 'strftime') else str(day)
                date_stats[date_str] = item['count']

            logger.info(f"[统计查询成功] tenant_id={tenant_id}, "
                       f"in_progress={status_stats['in_progress']['count']}, "
                       f"resolved={status_stats['resolved']['count']}")

            # 构建趋势数据（按日期正序）
            trend_data = [
                {'date': date, 'count': date_stats[date]}
                for date in sorted(date_stats.keys())
            ]

            return json_response({
                'status_stats': status_stats,
                'severity_stats': severity_stats,
                'trend_data': trend_data,
            })

        except DatabaseError as e:
            # 数据库异常
            logger.error(f"[统计接口数据库查询失败] tenant_id={tenant_id}, 错误={str(e)}", exc_info=True)
            return json_response(error='数据库查询失败')
        except Exception as e:
            # 其他未捕获异常
            logger.error(f"[统计接口未知错误] tenant_id={tenant_id}, 错误={str(e)}", exc_info=True)
            return json_response(error='服务器内部错误')


class RunLogExportView(View):
    """运行日志PDF导出视图"""

    @auth('runlog.runlog.view')
    def post(self, request):
        """导出运行日志PDF

        前端传入筛选条件，后端查询数据并生成PDF返回
        """
        from .models import RunLog, RunLogUpdate

        try:
            data = json.loads(request.body) if request.body else {}
        except (json.JSONDecodeError, ValueError):
            data = {}

        try:
            # 租户过滤
            logs = apply_tenant_filter(RunLog.objects.all(), request.user)

            # 筛选条件
            if data.get('status'):
                logs = logs.filter(status=data['status'])
            if data.get('severity'):
                logs = logs.filter(severity=data['severity'])
            if data.get('event_type'):
                logs = logs.filter(event_type=data['event_type'])
            if data.get('system_name'):
                logs = logs.filter(system_name__icontains=data['system_name'])

            # 日期范围
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            date_range_text = ''
            if start_date and end_date:
                logs = logs.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
                date_range_text = f'{start_date}-{end_date}'
            elif start_date:
                logs = logs.filter(created_at__date__gte=start_date)
                date_range_text = f'{start_date}起'
            elif end_date:
                logs = logs.filter(created_at__date__lte=end_date)
                date_range_text = f'至{end_date}'

            logs = logs.order_by('-created_at', '-id')

            if not logs.exists():
                return json_response(error='没有可导出的数据')

            # 限制最大导出条数，防止超时
            MAX_EXPORT_COUNT = 500
            logs = logs[:MAX_EXPORT_COUNT]

            # 序列化事件数据
            events_data = []
            for log in logs:
                event_dict = log.to_view()
                # 批量查询关联动态
                updates = apply_tenant_filter(
                    RunLogUpdate.objects.filter(runlog_id=log.id),
                    request.user
                ).order_by('update_date', 'sequence', 'id')
                event_dict['updates'] = [u.to_view() for u in updates]
                events_data.append(event_dict)

            # 生成PDF
            from .pdf_export import generate_runlog_pdf
            pdf_output = generate_runlog_pdf(events_data, date_range_text)

            # 构建文件名
            now = datetime.now().strftime('%Y%m%d_%H%M%S')
            if date_range_text:
                filename = f'运行日志报告_{date_range_text}_{now}.pdf'
            else:
                filename = f'运行日志报告_{now}.pdf'
            safe_filename = escape_uri_path(filename)

            response = HttpResponse(
                pdf_output.getvalue(),
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe_filename}"
            return response

        except Exception as e:
            import traceback
            logger.error(f'导出运行日志PDF失败｜用户：{request.user.username}｜错误：{e}\n{traceback.format_exc()}')
            return json_response(error=f'导出PDF失败：{type(e).__name__}: {str(e)[:80]}')


# ==================== 证据闭环第三阶段：证据事件 + 证据包 ====================

def _build_runlog_snapshot(event):
    """构建运行日志事件快照（用于证据事件 + 证据包）"""
    from .models import RunLogUpdate
    updates = RunLogUpdate.objects.filter(runlog_id=event.id).order_by('update_date', 'sequence', 'id')
    return {
        'event': {
            'id': event.id, 'event_title': event.event_title,
            'event_type': event.event_type, 'system_name': event.system_name,
            'severity': event.severity, 'status': event.status,
            'responsible_user_id': event.responsible_user_id,
            'responsible_user_name': event.responsible_user_name,
            'resolution': event.resolution,
            'verifier_id': event.verifier_id, 'verifier_name': event.verifier_name,
            'verified_at': event.verified_at, 'closed_at': event.closed_at,
            'snapshot_hash': event.snapshot_hash,
            'created_at': event.created_at, 'created_by_id': event.created_by_id,
        },
        'updates': [
            {
                'id': u.id, 'update_date': u.update_date, 'sequence': u.sequence,
                'recorder': u.recorder, 'detail_content': u.detail_content,
                'duty_person': u.duty_person, 'update_type': u.update_type,
                'is_voided': u.is_voided, 'void_reason': u.void_reason,
                'corrected_update_id': u.corrected_update_id,
                'created_at': u.created_at, 'created_by_id': u.created_by_id,
            }
            for u in updates
        ],
    }


def _record_runlog_evidence(event, event_type, user):
    """写入运行日志证据事件"""
    from apps.evidence.services import record_evidence_event
    from libs.utils import get_request_real_ip
    snapshot = _build_runlog_snapshot(event)

    # closed 时计算快照哈希
    if event_type == 'closed':
        import hashlib
        import json as _json
        payload = _json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        event.snapshot_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        event.save(update_fields=['snapshot_hash'])

    ev_type_map = {
        'resolved': 'submit', 'verified': 'approve',
        'closed': 'close', 'voided': 'void',
    }
    record_evidence_event(
        tenant_id=getattr(user, 'tenant_id', 'default'),
        module='runlog',
        object_type='runlog',
        object_id=event.id,
        event_type=ev_type_map.get(event_type, 'other'),
        actor_user_id=getattr(user, 'id', None),
        actor_username=getattr(user, 'username', ''),
        actor_name=getattr(user, 'nickname', '') or getattr(user, 'username', ''),
        object_snapshot=snapshot,
        event_title=f'{event.event_title} {event_type}',
    )


class RunLogEvidencePackageView(View):
    """运行日志证据包导出 - 包含业务快照/证据事件/审计日志/附件哈希清单"""

    @auth('runlog.runlog.view')
    def get(self, request):
        import json as _json
        import zipfile
        from io import BytesIO
        from .models import RunLog, RunLogUpdate
        from apps.evidence.models import EvidenceEvent, EvidenceAttachment
        from apps.logs.models import AuditLog

        log_id = request.GET.get('id')
        if not log_id:
            return json_response(error='缺少 id 参数')

        event = apply_tenant_filter(RunLog.objects.filter(pk=log_id), request.user).first()
        if not event:
            return json_response(error='事件不存在或无权限')

        tenant_id = getattr(request.user, 'tenant_id', 'default')
        snapshot = _build_runlog_snapshot(event)

        events = list(EvidenceEvent.objects.filter(
            tenant_id=tenant_id, module='runlog',
            object_type='runlog', object_id=str(event.id),
        ).order_by('id'))
        events_data = [e.to_dict() for e in events]

        audit_logs = list(AuditLog.objects.filter(
            tenant_id=tenant_id, target_type='runlog',
        ).order_by('id'))
        audit_data = [l.to_dict() for l in audit_logs]

        atts = EvidenceAttachment.objects.filter(
            tenant_id=tenant_id, module='runlog',
            object_type='runlog', object_id=str(event.id), is_deleted=False,
        )
        att_hashes = [
            {'file_name': a.file_name, 'sha256': a.file_hash_sha256, 'size': a.file_size}
            for a in atts
        ]

        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('object_snapshot.json', _json.dumps(snapshot, ensure_ascii=False, indent=2))
            zf.writestr('evidence_events.json', _json.dumps(events_data, ensure_ascii=False, indent=2))
            zf.writestr('audit_logs.json', _json.dumps(audit_data, ensure_ascii=False, indent=2))
            zf.writestr('hashes.json', _json.dumps({
                'module': 'runlog', 'object_id': event.id,
                'event_status': event.status,
                'snapshot_hash': event.snapshot_hash,
                'attachments': att_hashes,
                'events_count': len(events_data),
                'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            }, ensure_ascii=False, indent=2))

        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/zip')
        resp['Content-Disposition'] = f'attachment; filename="evidence_runlog_{event.id}.zip"'
        return resp


class RunLogOverviewView(View):
    """运行日志统计概览视图（第一阶段轻量统计）。

    只读接口，复用 runlog.runlog.view 权限与租户隔离，不修改任何业务数据。
    返回 KPI / 分布 / 趋势 / 未闭环列表，全部数据库聚合查询。
    """

    @auth('runlog.runlog.view')
    def get(self, request):
        from .statistics_service import RunLogStatisticsService

        # 收集筛选参数
        filters = {
            'start_date': request.GET.get('start_date'),
            'end_date': request.GET.get('end_date'),
            'event_type': request.GET.get('event_type'),
            'system_name': request.GET.get('system_name'),
            'severity': request.GET.get('severity'),
            'status': request.GET.get('status'),
        }
        # 去除空值
        filters = {k: v for k, v in filters.items() if v}

        try:
            data = RunLogStatisticsService.get_overview(request.user, filters)
            return json_response(data)
        except Exception as e:
            logger.error(f'[RunLog统计概览] 查询失败: {e}', exc_info=True)
            return json_response(error='统计查询失败')
