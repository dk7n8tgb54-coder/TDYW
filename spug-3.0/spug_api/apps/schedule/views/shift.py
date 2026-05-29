# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""班次管理视图"""

from django.views.generic import View
from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id

from ..models import ScheduleShift, ScheduleShiftTime
from ..cache_utils import (
    get_cache_key, get_cached_list, invalidate_model_cache, CACHE_TTL
)
import logging

logger = logging.getLogger(__name__)


class ScheduleShiftView(View):
    """班次管理视图"""

    @auth('schedule.schedule.view')
    def get(self, request):
        """获取班次列表 - 修复P1-1 N+1查询 + P2-1 添加缓存"""
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        cache_key = get_cache_key('shift', tenant_id)

        def fetch_shift_list():
            # 批量查询优化
            shift_list = apply_tenant_filter(
                ScheduleShift.objects.all().order_by('-id'),
                request.user
            )

            # 获取所有shift_id
            shift_ids = [shift.id for shift in shift_list]

            # 批量查询所有班次时间（避免N+1查询）
            shift_times = apply_tenant_filter(
                ScheduleShiftTime.objects.filter(shift_id__in=shift_ids),
                request.user
            )

            # 构建shift_id到times的映射字典
            times_map = {}
            for st in shift_times:
                if st.shift_id not in times_map:
                    times_map[st.shift_id] = []
                times_map[st.shift_id].append(st.to_view())

            # 组装结果
            result = []
            for shift in shift_list:
                shift_dict = shift.to_dict()
                shift_dict['times'] = times_map.get(shift.id, [])
                result.append(shift_dict)

            return result

        data = get_cached_list(
            cache_key,
            CACHE_TTL['shift_list'],
            fetch_shift_list
        )
        return json_response(data)

    @auth('schedule.schedule.add|schedule.schedule.edit')
    def post(self, request):
        """创建或更新班次 - P2-1: 更新后清除缓存"""
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入班次名称'),
            Argument('work_days', type=int, required=False),
            Argument('rest_days', type=int, required=False),
            Argument('shift_type', help='请选择班次类型'),
            Argument('description', required=False),
            Argument('color', required=False),
            Argument('is_default', type=bool, default=False)
        ).parse(request.body)

        if error:
            return json_response(error=error)

        tenant_id = getattr(request.user, 'tenant_id', 'admin')

        if form.id:
            # 更新模式
            queryset = apply_tenant_filter(
                ScheduleShift.objects.filter(pk=form.id),
                request.user
            )
            if not queryset.exists():
                return json_response(error='记录不存在或无权操作')

            form.updated_at = human_datetime()
            form.updated_by = request.user
            queryset.update(**form)
            logger.info(f'Updated shift: id={form.id}, name={form.name}')
        else:
            # 创建模式
            form.created_by = request.user
            assign_tenant_id(form, request.user)
            ScheduleShift.objects.create(**form)
            logger.info(f'Created shift: name={form.name}')

        # P2-1: 清除班次缓存
        invalidate_model_cache('shift', tenant_id)
        return json_response()

    @auth('schedule.schedule.del')
    def delete(self, request):
        """删除班次 - P2-1: 删除后清除缓存"""
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        queryset = apply_tenant_filter(
            ScheduleShift.objects.filter(pk=form.id),
            request.user
        )
        if not queryset.exists():
            return json_response(error='记录不存在或无权操作')

        queryset.delete()
        logger.info(f'Deleted shift: id={form.id}')

        # P2-1: 清除班次缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('shift', tenant_id)
        return json_response()
