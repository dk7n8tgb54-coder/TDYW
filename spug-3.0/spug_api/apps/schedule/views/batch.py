# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""批量操作视图"""

from django.views.generic import View
from django.db import transaction
from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id

from ..models import Schedule, ScheduleSwap, ScheduleSubstitute, ScheduleStaff
from ..services import ScheduleService, SwapService
from ..cache_utils import invalidate_model_cache
import logging

logger = logging.getLogger(__name__)


class ScheduleBatchDeleteView(View):
    """批量删除排班 - 修复P0-2：添加事务保护"""

    @auth('schedule.schedule.del')
    @transaction.atomic
    def post(self, request):
        """批量删除排班（带事务保护）"""
        form, error = JsonParser(
            Argument('ids', type=list, help='请提供要删除的排班ID列表')
        ).parse(request.body)

        if error:
            return json_response(error=error)

        if not form.ids:
            return json_response(error='删除列表不能为空')

        # 验证所有ID是否属于当前租户
        queryset = apply_tenant_filter(
            Schedule.objects.filter(pk__in=form.ids),
            request.user
        )

        found_ids = set(queryset.values_list('id', flat=True))
        requested_ids = set(form.ids)

        # 检查是否有跨租户ID
        invalid_ids = requested_ids - found_ids
        if invalid_ids:
            logger.warning(
                f'User {request.user.username} attempted to delete cross-tenant schedules: {invalid_ids}'
            )
            return json_response(error='部分记录不存在或无权操作')

        # 事务保护下的批量删除
        deleted_count = queryset.delete()[0]
        logger.info(f'Batch deleted {deleted_count} schedules for user {request.user.username}')

        # P2-1: 清除排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('schedule', tenant_id)

        return json_response({
            'deleted_count': deleted_count,
            'requested_count': len(form.ids)
        })


class ScheduleBatchAdjustView(View):
    """批量调整排班 - 修复P0-2：添加事务保护"""

    @auth('schedule.schedule.edit')
    @transaction.atomic
    def post(self, request):
        """批量调整排班日期（带事务保护）"""
        form, error = JsonParser(
            Argument('adjustments', type=list, help='请提供调整的排班列表')
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 事务保护：全部成功或全部失败
        try:
            success_count, error_count = ScheduleService.batch_adjust_schedules(
                form.adjustments, request.user
            )
        except Exception as e:
            logger.error(f'Batch adjust failed: {e}')
            return json_response(error='批量调整失败，请重试')

        logger.info(f'Batch adjust schedules: success={success_count}, errors={error_count}')

        # P2-1: 清除排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('schedule', tenant_id)

        return json_response({
            'success_count': success_count,
            'error_count': error_count
        })


class ScheduleBatchSwapView(View):
    """批量创建换班记录 - 修复P0-2：添加事务保护"""

    @auth('schedule.schedule.add|schedule.schedule.edit')
    @transaction.atomic
    def post(self, request):
        """批量创建换班（带事务保护）"""
        form, error = JsonParser(
            Argument('records', type=list, help='请提供换班记录列表')
        ).parse(request.body)

        if error:
            return json_response(error=error)

        valid_records = []
        skipped_count = 0

        # 第一阶段：验证所有记录
        for record_data in form.records:
            from_staff_id = record_data.get('from_staff_id')
            to_staff_id = record_data.get('to_staff_id')

            valid_ids, invalid_ids = SwapService.validate_staff_ids(
                [from_staff_id, to_staff_id], request.user
            )

            if invalid_ids:
                logger.warning(
                    f'User {request.user.username} attempted to use cross-tenant staff_ids: {invalid_ids}'
                )
                skipped_count += 1
                continue

            # 准备数据
            record_data['created_by'] = request.user
            assign_tenant_id(record_data, request.user)

            valid_records.append(record_data)

        # 第二阶段：事务保护下的批量创建
        created_records = ScheduleSwap.objects.bulk_create([
            ScheduleSwap(**record_data) for record_data in valid_records
        ])

        created_count = len(created_records)
        logger.info(f'Batch created {created_count} swap records for user {request.user.username}')

        # P2-1: 清除换班和排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('swap', tenant_id)
        invalidate_model_cache('schedule', tenant_id)

        return json_response({
            'created_count': created_count,
            'skipped_count': skipped_count
        })


class ScheduleBatchSubstituteView(View):
    """批量创建替班记录 - 修复P0-2：添加事务保护"""

    @auth('schedule.schedule.add|schedule.schedule.edit')
    @transaction.atomic
    def post(self, request):
        """批量创建替班（带事务保护）"""
        form, error = JsonParser(
            Argument('records', type=list, help='请提供替班记录列表')
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 准备所有记录数据
        prepared_records = []
        for record_data in form.records:
            record_data['created_by'] = request.user
            assign_tenant_id(record_data, request.user)
            prepared_records.append(record_data)

        # 事务保护下的批量创建
        created_records = ScheduleSubstitute.objects.bulk_create([
            ScheduleSubstitute(**record_data) for record_data in prepared_records
        ])

        created_count = len(created_records)
        logger.info(f'Batch created {created_count} substitute records for user {request.user.username}')

        # P2-1: 清除替班和排班缓存
        tenant_id = getattr(request.user, 'tenant_id', 'admin')
        invalidate_model_cache('substitute', tenant_id)
        invalidate_model_cache('schedule', tenant_id)

        return json_response({
            'created_count': created_count
        })
