# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""替班业务服务"""

from django.db import transaction
import logging

from ..models import Schedule, ScheduleSubstitute, ScheduleStaff

logger = logging.getLogger(__name__)


class SubstituteService:
    """替班业务服务类"""

    @staticmethod
    def prepare_substitute_data(form, user):
        """
        准备替班数据

        Args:
            form: 表单数据
            user: 当前用户

        Returns:
            dict: 完整的替班数据
        """
        form_data = dict(form)
        form_data['created_by'] = user

        if not getattr(user, 'is_supper', False):
            form_data['tenant_id'] = getattr(user, 'tenant_id', 'admin')

        return form_data

    @staticmethod
    def check_substitute_conflict(substitute_staff_id, schedule_date, exclude_substitute_id=None):
        """
        检查替班冲突

        Args:
            substitute_staff_id: 替班人员ID
            schedule_date: 日期
            exclude_substitute_id: 排除的替班ID

        Returns:
            Schedule or None: 如果存在冲突返回排班对象
        """
        query = Schedule.objects.filter(
            staff_id=substitute_staff_id,
            schedule_date=schedule_date
        )
        if exclude_substitute_id:
            # 排除当前替班记录对应的排班
            pass  # 可以根据需要添加逻辑

        return query.first()

    @staticmethod
    @transaction.atomic
    def process_substitute_approval(record, form, user):
        """
        处理替班审批

        Args:
            record: ScheduleSubstitute记录
            form: 表单数据
            user: 当前用户

        Returns:
            tuple: (success, error_message)
        """
        from libs import human_datetime
        from libs.tenant_utils import apply_tenant_filter

        logger.info(f'Processing substitute approval: record_id={record.id}')

        schedule_date = record.schedule_date

        # 查找原值班人的排班记录
        original_schedule = apply_tenant_filter(
            Schedule.objects.filter(
                staff_id=record.original_staff_id,
                schedule_date=schedule_date
            ),
            user
        ).first()

        # 查找替班人的排班记录
        substitute_schedule = apply_tenant_filter(
            Schedule.objects.filter(
                staff_id=record.substitute_staff_id,
                schedule_date=schedule_date
            ),
            user
        ).first()

        # 检查替班冲突
        if substitute_schedule:
            error_msg = f'替班人"{record.substitute_staff_name}"在{schedule_date}已有排班，请先处理冲突后再审批'
            logger.warning(f'Substitute conflict: {error_msg}')
            return False, error_msg

        # 更新排班
        if original_schedule:
            Schedule.objects.filter(pk=original_schedule.pk).update(
                staff_id=record.substitute_staff_id,
                staff_name=record.substitute_staff_name,
                shift_id=record.shift_id,
                shift_name=record.shift_name,
                updated_at=human_datetime(),
                updated_by=user
            )
            logger.info(f'Updated schedule for substitute: {schedule_date}, {record.original_staff_name} -> {record.substitute_staff_name}')
        else:
            # 原值班人没有排班，为替班人创建排班
            tenant_id = getattr(user, 'tenant_id', 'admin')
            Schedule.objects.create(
                tenant_id=tenant_id,
                staff_id=record.substitute_staff_id,
                staff_name=record.substitute_staff_name,
                schedule_date=schedule_date,
                shift_id=record.shift_id,
                shift_name=record.shift_name,
                created_by=user
            )
            logger.info(f'Created new schedule for substitute: {schedule_date}, {record.substitute_staff_name}')

        # 更新替班记录
        update_data = {
            'status': form.status,
            'updated_at': human_datetime(),
            'updated_by': user,
            'approved_by': user,
            'approved_by_name': user.username if user else '',
            'approved_at': human_datetime()
        }

        if hasattr(form, 'remarks') and form.remarks is not None:
            update_data['remarks'] = form.remarks

        ScheduleSubstitute.objects.filter(pk=form.id).update(**update_data)
        logger.info(f'Substitute approved: record_id={record.id}')
        return True, None

    @staticmethod
    def restore_substitute_schedule(record, user):
        """
        恢复替班前的排班状态

        Args:
            record: ScheduleSubstitute记录
            user: 当前用户

        Returns:
            bool: 是否成功恢复
        """
        from libs import human_datetime
        from libs.tenant_utils import apply_tenant_filter

        logger.info(f'Restoring substitute schedule: record_id={record.id}')

        schedule_date = record.schedule_date

        # 查找替班人的排班记录
        schedule = apply_tenant_filter(
            Schedule.objects.filter(
                staff_id=record.substitute_staff_id,
                schedule_date=schedule_date
            ),
            user
        ).first()

        if schedule:
            schedule.staff_id = record.original_staff_id
            schedule.staff_name = record.original_staff_name
            schedule.updated_at = human_datetime()
            schedule.updated_by = user
            schedule.save()
            logger.info(f'Restored original staff: {record.substitute_staff_name} -> {record.original_staff_name}')
            return True
        else:
            logger.warning(f'No schedule found to restore for staff_id={record.substitute_staff_id}, date={schedule_date}')
            return False

    @staticmethod
    def get_update_data(form, user):
        """
        构建替班更新数据

        Args:
            form: 表单数据
            user: 当前用户

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

        if form.status in ['approved', 'rejected']:
            update_data['approved_by'] = user
            update_data['approved_by_name'] = user.username if user else ''
            update_data['approved_at'] = human_datetime()

        return update_data

    @staticmethod
    def validate_staff(staff_id, user):
        """
        验证人员是否属于当前租户

        Args:
            staff_id: 人员ID
            user: 当前用户

        Returns:
            bool: 是否有效
        """
        from libs.tenant_utils import apply_tenant_filter

        if not staff_id:
            return False

        exists = apply_tenant_filter(
            ScheduleStaff.objects.filter(pk=staff_id),
            user
        ).exists()

        if not exists:
            logger.warning(f'User {user.username} attempted to use cross-tenant staff_id {staff_id}')

        return exists
