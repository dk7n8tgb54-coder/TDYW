# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""排班管理视图"""

from django.views.generic import View
from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter

from ..models import Schedule, ScheduleShift
from ..services import ScheduleService
from ..cache_utils import (
    get_cache_key, get_cached_list, invalidate_model_cache,
    invalidate_schedule_cache, CACHE_TTL
)
import logging

logger = logging.getLogger(__name__)


class ScheduleView(View):
    """排班CRUD视图"""

    @auth('schedule.schedule.view')
    def get(self, request):
        """获取排班列表 - P2-1: 添加缓存"""
        year = request.GET.get('year')
        month = request.GET.get('month')
        tenant_id = getattr(request.user, 'tenant_id', 'admin')

        # 生成带年月后缀的缓存Key
        cache_suffix = f"{year}-{month}" if year and month else "all"
        cache_key = get_cache_key('schedule', tenant_id, cache_suffix)

        def fetch_schedules():
            queryset = apply_tenant_filter(Schedule.objects.all(), request.user)
            queryset = ScheduleService.filter_schedules_by_month(queryset, year, month)
            return ScheduleService.get_schedules_with_colors(queryset, request.user)

        data = get_cached_list(
            cache_key,
            CACHE_TTL['schedule_calendar'],
            fetch_schedules
        )
        return json_response(data)

    @auth('schedule.schedule.add|schedule.schedule.edit')
    def post(self, request):
        """创建或更新排班 - P2-1: 更新后清除缓存"""
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('staff_id', type=int, required=False, help='请选择值班人员'),
            Argument('staff_name', help='请输入值班人员姓名'),
            Argument('schedule_date', help='请选择排班日期'),
            Argument('shift_id', help='请选择班次'),
            Argument('shift_name', help='请输入班次名称'),
            Argument('shift_time_id', required=False),
            Argument('notes', required=False)
        ).parse(request.body)

        if error:
            return json_response(error=error)

        tenant_id = getattr(request.user, 'tenant_id', 'admin')

        if form.id:
            # 更新模式
            queryset = apply_tenant_filter(
                Schedule.objects.filter(pk=form.id),
                request.user
            )
            if not queryset.exists():
                return json_response(error='记录不存在或无权操作')

            form.updated_at = human_datetime()
            form.updated_by = request.user
            queryset.update(**form)
        else:
            # 创建模式 - 检查冲突
            existing = apply_tenant_filter(Schedule.objects.all(), request.user).filter(
                staff_id=form.staff_id,
                schedule_date=form.schedule_date
            ).first()

            if existing:
                # 更新现有记录
                form.updated_at = human_datetime()
                form.updated_by = request.user
                apply_tenant_filter(
                    Schedule.objects.filter(pk=existing.id),
                    request.user
                ).update(**form)
                logger.info(f'Updated existing schedule: staff_id={form.staff_id}, date={form.schedule_date}')
            else:
                # 创建新记录
                ScheduleService.create_or_update_schedule(form, request.user)

        # P2-1: 清除排班缓存（按年月缓存的，需要清除所有）
        invalidate_model_cache('schedule', tenant_id)
        return json_response()

    @auth('schedule.schedule.del')
    def delete(self, request):
        """删除排班 - P2-1: 删除后清除缓存"""
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        queryset = apply_tenant_filter(
            Schedule.objects.filter(pk=form.id),
            request.user
        )
        if not queryset.exists():
            return json_response(error='记录不存在或无权操作')

        queryset.delete()

        # P2-1: 清除排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('schedule', tenant_id)
        return json_response()


class ScheduleBatchQueryView(View):
    """批量查询排班记录（用于批量删除预览）"""

    @auth('schedule.schedule.view')
    def post(self, request):
        """批量查询排班"""
        form, error = JsonParser(
            Argument('staff_ids', type=list, help='请选择值班人员ID列表'),
            Argument('start_date', help='请选择开始日期(YYYY-MM-DD)'),
            Argument('end_date', help='请选择结束日期(YYYY-MM-DD)')
        ).parse(request.body)

        if error:
            return json_response(error=error)

        queryset = apply_tenant_filter(Schedule.objects.all(), request.user)
        queryset = ScheduleService.filter_schedules_by_staff_and_date(
            queryset, form.staff_ids, form.start_date, form.end_date
        )

        schedules = ScheduleService.get_schedules_with_colors(queryset, request.user)
        logger.info(f'Batch query schedules: staff_ids={form.staff_ids}, '
                   f'range={form.start_date}~{form.end_date}, count={len(schedules)}')

        return json_response(schedules)
