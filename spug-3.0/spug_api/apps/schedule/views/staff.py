# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""排班人员管理视图"""

import json
from django.views.generic import View
from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id

from ..models import ScheduleStaff
from ..cache_utils import (
    get_cache_key, get_cached_list, invalidate_model_cache, CACHE_TTL
)
import logging

logger = logging.getLogger(__name__)


class ScheduleStaffView(View):
    """排班人员管理视图"""

    @auth('schedule.schedule.view')
    def get(self, request):
        """获取人员列表 - P2-1: 添加缓存"""
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        cache_key = get_cache_key('staff', tenant_id)
        
        def fetch_staff_list():
            staff_list = apply_tenant_filter(
                ScheduleStaff.objects.filter(is_active=True),
                request.user
            )
            return [x.to_view() for x in staff_list]
        
        data = get_cached_list(
            cache_key,
            CACHE_TTL['staff_list'],
            fetch_staff_list
        )
        return json_response(data)

    @auth('schedule.schedule.add|schedule.schedule.edit')
    def post(self, request):
        """创建或更新人员 - P2-1: 更新后清除缓存"""
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('user_id', type=int, required=False),
            Argument('user_name', help='请输入值班人员姓名'),
            Argument('department', required=False),
            Argument('phone', required=False),
            Argument('is_active', type=bool, default=True),
            Argument('unavailable_dates', type=list, handler=json.dumps, default=[])
        ).parse(request.body)

        if error:
            return json_response(error=error)

        tenant_id = getattr(request.user, 'tenant_id', 'admin')

        if form.id:
            # 更新模式
            queryset = apply_tenant_filter(
                ScheduleStaff.objects.filter(pk=form.id),
                request.user
            )
            if not queryset.exists():
                return json_response(error='记录不存在或无权操作')

            form.updated_at = human_datetime()
            form.updated_by = request.user
            queryset.update(**form)
            logger.info(f'Updated staff: id={form.id}, name={form.user_name}')
        else:
            # 创建模式
            form.created_by = request.user
            assign_tenant_id(form, request.user)
            ScheduleStaff.objects.create(**form)
            logger.info(f'Created staff: name={form.user_name}')

        # P2-1: 清除人员缓存
        invalidate_model_cache('staff', tenant_id)
        return json_response()

    @auth('schedule.schedule.del')
    def patch(self, request):
        """更新人员状态（启用/禁用）- P2-1: 更新后清除缓存"""
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('is_active', type=bool, help='请选择状态')
        ).parse(request.body)

        if error:
            return json_response(error=error)

        queryset = apply_tenant_filter(
            ScheduleStaff.objects.filter(pk=form.id),
            request.user
        )
        if not queryset.exists():
            return json_response(error='记录不存在或无权操作')

        queryset.update(**form)
        logger.info(f'Updated staff status: id={form.id}, is_active={form.is_active}')

        # P2-1: 清除人员缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('staff', tenant_id)
        return json_response()
