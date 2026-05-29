# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""替班管理视图"""

import json
from django.views.generic import View
from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter

from ..models import ScheduleSubstitute
from ..services import SubstituteService
from ..cache_utils import (
    get_cache_key, get_cached_list, invalidate_model_cache, CACHE_TTL
)
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ScheduleSubstituteView(View):
    """替班管理视图"""

    @auth('schedule.substitute.view')
    def get(self, request):
        """获取替班列表 - 支持日期筛选"""
        # 获取日期筛选参数
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        tenant_id = getattr(request.user, 'tenant_id', 'admin')

        # 构建缓存键（包含日期参数）
        date_suffix = ''
        if start_date or end_date:
            date_suffix = f"{start_date or 'all'}_{end_date or 'all'}"
        cache_key = get_cache_key('substitute', tenant_id, date_suffix)

        def fetch_substitute_list():
            queryset = apply_tenant_filter(ScheduleSubstitute.objects.all(), request.user)

            # 应用日期筛选
            if start_date:
                queryset = queryset.filter(schedule_date__gte=start_date)
            if end_date:
                queryset = queryset.filter(schedule_date__lte=end_date)

            return [x.to_view() for x in queryset]

        data = get_cached_list(
            cache_key,
            CACHE_TTL['substitute_list'],
            fetch_substitute_list
        )
        return json_response(data)

    @auth('schedule.substitute.add')
    def post(self, request):
        """创建替班申请"""
        form, error = JsonParser(
            Argument('original_staff_id', help='请选择原值班人'),
            Argument('original_staff_name', help='请输入原值班人姓名'),
            Argument('substitute_staff_id', help='请选择替班人'),
            Argument('substitute_staff_name', help='请输入替班人姓名'),
            Argument('schedule_date', help='请选择替班日期'),
            Argument('shift_id', help='请选择班次'),
            Argument('shift_name', help='请输入班次名称'),
            Argument('reason', required=False)
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # P1-001: 验证替班日期不能是过去日期
        today = datetime.now().date()
        schedule_date_obj = datetime.strptime(form.schedule_date, '%Y-%m-%d').date()

        if schedule_date_obj < today:
            return json_response(error='替班日期不能是过去日期')

        # 准备数据并创建
        form_data = SubstituteService.prepare_substitute_data(form, request.user)
        ScheduleSubstitute.objects.create(**form_data)

        # P2-1: 清除替班和排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('substitute', tenant_id)
        invalidate_model_cache('schedule', tenant_id)

        logger.info(f'Created substitute record: original={form.original_staff_name}, '
                   f'substitute={form.substitute_staff_name}')

        return json_response()

    @auth('schedule.substitute.edit')
    def patch(self, request):
        """更新替班状态（审批）"""
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('status', help='请选择状态'),
            Argument('remarks', required=False)
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 获取记录
        record = apply_tenant_filter(
            ScheduleSubstitute.objects.filter(pk=form.id),
            request.user
        ).first()

        if not record:
            return json_response(error='记录不存在或无权操作')

        if record.status != 'pending':
            return json_response(error='只能审批待处理状态的记录')

        # 如果审批通过，处理替班逻辑
        if form.status == 'approved':
            success, error_msg = SubstituteService.process_substitute_approval(
                record, form, request.user
            )
            if not success:
                return json_response(error=error_msg)
        else:
            # 拒绝或其他状态，仅更新记录
            update_data = SubstituteService.get_update_data(form, request.user)
            ScheduleSubstitute.objects.filter(pk=form.id).update(**update_data)

        # P2-1: 清除替班和排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('substitute', tenant_id)
        invalidate_model_cache('schedule', tenant_id)

        return json_response()

    @auth('schedule.substitute.del')
    def delete(self, request):
        """删除替班记录"""
        # 兼容两种请求方式
        logger.info(f'Substitute DELETE request - GET params: {request.GET.dict()}, Body: {request.body}')

        request_data = {}
        if request.body:
            try:
                request_data = json.loads(request.body)
            except (json.JSONDecodeError, TypeError) as e:
                # 修复P0-3：添加明确的错误处理，不再静默忽略
                logger.warning(f'Invalid JSON in request body: {e}')
                return json_response(error='请求数据格式错误，请检查JSON格式')

        query_params = request.GET.dict()
        combined_data = {**query_params, **request_data}

        logger.info(f'Substitute DELETE combined data: {combined_data}')

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
        ).parse(combined_data)

        if error:
            return json_response(error=error)

        # 获取记录
        record = apply_tenant_filter(
            ScheduleSubstitute.objects.filter(pk=form.id),
            request.user
        ).first()

        if not record:
            return json_response(error='记录不存在或无权操作')

        # 如果替班已通过，恢复原排班
        if record.status == 'approved':
            SubstituteService.restore_substitute_schedule(record, request.user)

        # 删除记录
        apply_tenant_filter(
            ScheduleSubstitute.objects.filter(pk=form.id),
            request.user
        ).delete()

        logger.info(f'Deleted substitute record: {form.id}')
        # P2-1: 清除替班和排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('substitute', tenant_id)
        invalidate_model_cache('schedule', tenant_id)

        return json_response()
