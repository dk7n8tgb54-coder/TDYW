# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""换班管理视图"""

import json
from django.views.generic import View
from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter

from ..models import ScheduleSwap
from ..services import SwapService
from ..cache_utils import (
    get_cache_key, get_cached_list, invalidate_model_cache, CACHE_TTL
)
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ScheduleSwapView(View):
    """换班管理视图"""

    @auth('schedule.swap.view')
    def get(self, request):
        """获取换班列表 - 支持日期筛选"""
        # 获取日期筛选参数
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        tenant_id = getattr(request.user, 'tenant_id', 'admin')

        # 构建缓存键（包含日期参数）
        date_suffix = ''
        if start_date or end_date:
            date_suffix = f"{start_date or 'all'}_{end_date or 'all'}"
        cache_key = get_cache_key('swap', tenant_id, date_suffix)

        def fetch_swap_list():
            queryset = apply_tenant_filter(ScheduleSwap.objects.all(), request.user)

            # 应用日期筛选（筛选 from_date 和 to_date 字段）
            if start_date:
                queryset = queryset.filter(from_date__gte=start_date)
            if end_date:
                queryset = queryset.filter(to_date__lte=end_date)

            return [x.to_view() for x in queryset]

        data = get_cached_list(
            cache_key,
            CACHE_TTL['swap_list'],
            fetch_swap_list
        )
        return json_response(data)

    @auth('schedule.swap.add')
    def post(self, request):
        """创建换班申请 - P2-1: 创建后清除缓存"""
        logger.info(f'Swap POST request body: {request.body}')

        form, error = JsonParser(
            Argument('from_staff_id', help='请选择申请人'),
            Argument('from_staff_name', help='请输入申请人姓名'),
            Argument('to_staff_id', help='请选择被换人'),
            Argument('to_staff_name', help='请输入被换人姓名'),
            Argument('from_date', required=True, help='请选择申请人换班日期'),
            Argument('to_date', required=True, help='请选择被换人换班日期'),
            Argument('from_shift_id', help='请输入申请人班次'),
            Argument('from_shift_name', help='请输入申请人班次名称'),
            Argument('to_shift_id', help='请输入被换人班次'),
            Argument('to_shift_name', help='请输入被换人班次名称'),
            Argument('reason', required=False)
        ).parse(request.body)

        if error:
            return json_response(error=error)

        logger.info(f'Swap POST form: {form}')

        # P1-001: 验证换班日期不能是过去日期
        today = datetime.now().date()
        from_date_obj = datetime.strptime(form.from_date, '%Y-%m-%d').date()
        to_date_obj = datetime.strptime(form.to_date, '%Y-%m-%d').date()

        if from_date_obj < today:
            return json_response(error='申请人换班日期不能是过去日期')
        if to_date_obj < today:
            return json_response(error='被换人换班日期不能是过去日期')

        # 准备数据并创建
        form_data = SwapService.prepare_swap_data(form, request.user)
        ScheduleSwap.objects.create(**form_data)

        # P2-1: 清除换班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('swap', tenant_id)
        invalidate_model_cache('schedule', tenant_id)  # 排班也可能变化

        logger.info(f'Created swap record: from={form.from_staff_name}, to={form.to_staff_name}')
        return json_response()

    @auth('schedule.swap.edit')
    def patch(self, request):
        """更新换班状态（审批/撤销）"""
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('status', help='请选择状态'),
            Argument('remarks', required=False),
            Argument('cancel_swap', type=bool, required=False, default=False)
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 获取记录
        record = apply_tenant_filter(
            ScheduleSwap.objects.filter(pk=form.id),
            request.user
        ).first()

        if not record:
            return json_response(error='记录不存在或无权操作')

        # 处理撤销已通过的换班
        if record.status == 'approved' and form.status == 'cancelled' and form.cancel_swap:
            SwapService.cancel_approved_swap(record, form, request.user)
            return json_response()

        # 正常审批流程
        if record.status != 'pending':
            return json_response(error='只能审批待处理状态的记录')

        # 处理审批
        SwapService.process_swap_approval(record, form, request.user)

        # P2-1: 清除换班和排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('swap', tenant_id)
        invalidate_model_cache('schedule', tenant_id)
        return json_response()

    @auth('schedule.swap.del')
    def delete(self, request):
        """删除换班记录"""
        # 兼容两种请求方式：body 和 query string
        logger.info(f'Swap DELETE request - GET params: {request.GET.dict()}, Body: {request.body}')

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

        logger.info(f'Swap DELETE combined data: {combined_data}')

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
        ).parse(combined_data)

        if error:
            return json_response(error=error)

        # 获取记录
        record = apply_tenant_filter(
            ScheduleSwap.objects.filter(pk=form.id),
            request.user
        ).first()

        if not record:
            return json_response(error='记录不存在或无权操作')

        # 如果换班已通过，恢复原排班
        if record.status == 'approved':
            SwapService.restore_swap_schedules(record, request.user)

        # 删除记录
        apply_tenant_filter(
            ScheduleSwap.objects.filter(pk=form.id),
            request.user
        ).delete()

        # P2-1: 清除换班和排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('swap', tenant_id)
        invalidate_model_cache('schedule', tenant_id)

        logger.info(f'Deleted swap record: {form.id}')
        return json_response()
