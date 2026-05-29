# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""换班业务服务"""

from django.db import transaction
import logging

from ..models import Schedule, ScheduleSwap, ScheduleStaff
from ..exceptions import RecordNotFoundError

logger = logging.getLogger(__name__)


class SwapService:
    """换班业务服务类"""

    @staticmethod
    def execute_swap(record, user):
        """
        执行排班交换（审批通过时调用）

        Args:
            record: ScheduleSwap记录
            user: 操作用户

        Returns:
            bool: 是否成功执行
        """
        from libs import human_datetime

        # 获取换班日期(优先使用新字段,兼容旧字段)
        from_date = record.from_date or record.schedule_date
        to_date = record.to_date or record.schedule_date

        logger.info(f'Executing swap: record_id={record.id}, from_date={from_date}, to_date={to_date}')

        # 查找申请人的排班记录
        from_schedule = Schedule.objects.filter(
            staff_id=record.from_staff_id,
            schedule_date=from_date
        ).first()

        # 查找被换人的排班记录
        to_schedule = Schedule.objects.filter(
            staff_id=record.to_staff_id,
            schedule_date=to_date
        ).first()

        if from_schedule and to_schedule:
            # 交换两人的排班信息（使用update方法避免唯一键冲突）
            Schedule.objects.filter(pk=from_schedule.pk).update(
                staff_id=record.to_staff_id,
                staff_name=record.to_staff_name,
                shift_id=record.to_shift_id,
                shift_name=record.to_shift_name,
                updated_at=human_datetime(),
                updated_by=user
            )
            Schedule.objects.filter(pk=to_schedule.pk).update(
                staff_id=record.from_staff_id,
                staff_name=record.from_staff_name,
                shift_id=record.from_shift_id,
                shift_name=record.from_shift_name,
                updated_at=human_datetime(),
                updated_by=user
            )
            logger.info(f'Swapped schedules: {from_schedule.pk} <-> {to_schedule.pk}')
            return True

        elif from_schedule:
            # 只有申请人有排班,删除申请人的排班
            from_schedule.delete()
            logger.info(f'Deleted from_schedule only: {from_schedule.pk}')
            return True

        elif to_schedule:
            # 只有被换人有排班,删除被换人的排班
            to_schedule.delete()
            logger.info(f'Deleted to_schedule only: {to_schedule.pk}')
            return True

        logger.warning(f'No schedules found for swap: record_id={record.id}')
        return False

    @staticmethod
    def restore_swap_schedules(record, user):
        """
        恢复换班前的排班状态（撤销或删除时调用）

        Args:
            record: ScheduleSwap记录
            user: 操作用户

        Returns:
            bool: 是否成功恢复
        """
        from libs import human_datetime

        from_date = record.from_date or record.schedule_date
        to_date = record.to_date or record.schedule_date

        logger.info(f'Restoring swap schedules: record_id={record.id}')

        # 查找申请人的排班记录（现在在被换人的日期）
        from_schedule = Schedule.objects.filter(
            staff_id=record.from_staff_id,
            schedule_date=to_date
        ).first()

        # 查找被换人的排班记录（现在在申请人的日期）
        to_schedule = Schedule.objects.filter(
            staff_id=record.to_staff_id,
            schedule_date=from_date
        ).first()

        if from_schedule and to_schedule:
            # 恢复原排班
            from_schedule.schedule_date = from_date
            from_schedule.staff_name = record.from_staff_name
            from_schedule.shift_id = record.from_shift_id
            from_schedule.shift_name = record.from_shift_name
            from_schedule.updated_at = human_datetime()
            from_schedule.updated_by = user
            from_schedule.save()

            to_schedule.schedule_date = to_date
            to_schedule.staff_name = record.to_staff_name
            to_schedule.shift_id = record.to_shift_id
            to_schedule.shift_name = record.to_shift_name
            to_schedule.updated_at = human_datetime()
            to_schedule.updated_by = user
            to_schedule.save()

            logger.info(f'Restored swap schedules: record_id={record.id}')
            return True

        logger.warning(f'Could not restore swap schedules: record_id={record.id}')
        return False

    @staticmethod
    def prepare_swap_data(form, user):
        """
        准备换班数据

        Args:
            form: 表单数据
            user: 当前用户

        Returns:
            dict: 完整的换班数据
        """
        form_data = dict(form)

        # 兼容旧字段,设置schedule_date为from_date
        if 'from_date' not in form_data:
            form_data['from_date'] = form_data.get('schedule_date', '')
        if 'to_date' not in form_data:
            form_data['to_date'] = form_data.get('schedule_date', '')
        form_data['schedule_date'] = form_data.get('from_date', '')
        form_data['created_by'] = user

        if not getattr(user, 'is_supper', False):
            form_data['tenant_id'] = getattr(user, 'tenant_id', 'admin')

        return form_data

    @staticmethod
    def validate_staff_ids(staff_ids, user):
        """
        验证人员ID是否属于当前租户

        Args:
            staff_ids: 人员ID列表或单个ID
            user: 当前用户

        Returns:
            tuple: (valid_ids, invalid_ids)
        """
        from libs.tenant_utils import apply_tenant_filter

        if not isinstance(staff_ids, (list, tuple)):
            staff_ids = [staff_ids]

        valid_ids = []
        invalid_ids = []

        for staff_id in staff_ids:
            if staff_id and apply_tenant_filter(
                ScheduleStaff.objects.filter(pk=staff_id),
                user
            ).exists():
                valid_ids.append(staff_id)
            else:
                invalid_ids.append(staff_id)
                logger.warning(f'User {user.username} attempted to use cross-tenant staff_id {staff_id}')

        return valid_ids, invalid_ids

    @staticmethod
    def get_update_data(form, user, is_approval=False):
        """
        构建换班更新数据

        Args:
            form: 表单数据
            user: 当前用户
            is_approval: 是否为审批操作

        Returns:
            dict: 更新数据字典
        """
        from libs import human_datetime

        update_data = {
            'status': form.status,
            'updated_at': human_datetime(),
            'updated_by': user
        }

        if hasattr(form, 'remarks') and form.remarks is not None:
            update_data['remarks'] = form.remarks

        if is_approval and form.status in ['approved', 'rejected']:
            update_data['approved_by'] = user
            update_data['approved_by_name'] = user.username if user else ''
            update_data['approved_at'] = human_datetime()

        return update_data

    @staticmethod
    @transaction.atomic
    def process_swap_approval(record, form, user):
        """
        处理换班审批（带事务）

        Args:
            record: ScheduleSwap记录
            form: 表单数据
            user: 当前用户

        Returns:
            bool: 是否成功
        """
        update_data = SwapService.get_update_data(form, user, is_approval=True)

        # 如果审批通过，执行排班交换
        if form.status == 'approved':
            SwapService.execute_swap(record, user)

        ScheduleSwap.objects.filter(pk=form.id).update(**update_data)
        logger.info(f'Processed swap approval: record_id={record.id}, status={form.status}')
        return True

    @staticmethod
    @transaction.atomic
    def cancel_approved_swap(record, form, user):
        """
        撤销已通过的换班

        Args:
            record: ScheduleSwap记录
            form: 表单数据
            user: 当前用户

        Returns:
            bool: 是否成功
        """
        from libs import human_datetime

        # 恢复原排班
        SwapService.restore_swap_schedules(record, user)

        # 更新记录状态
        update_data = {
            'status': form.status,
            'updated_at': human_datetime(),
            'updated_by': user
        }

        if hasattr(form, 'remarks') and form.remarks is not None:
            update_data['remarks'] = form.remarks

        ScheduleSwap.objects.filter(pk=form.id).update(**update_data)
        logger.info(f'Cancelled approved swap: record_id={record.id}')
        return True
