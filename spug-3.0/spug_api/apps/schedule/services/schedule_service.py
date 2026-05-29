# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""排班业务服务"""

from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import Q
import logging

from ..models import Schedule, ScheduleShift, ScheduleStaff
from ..exceptions import RecordNotFoundError, ScheduleConflictError

logger = logging.getLogger(__name__)


class ScheduleService:
    """排班业务服务类"""

    @staticmethod
    def get_schedules_with_colors(queryset, user):
        """
        获取排班列表并附加班次颜色信息

        Args:
            queryset: Schedule查询集
            user: 当前用户

        Returns:
            list: 包含颜色信息的排班字典列表
        """
        from libs.tenant_utils import apply_tenant_filter

        shift_dict = {
            x.id: x for x in apply_tenant_filter(ScheduleShift.objects.all(), user)
        }

        schedules = []
        for s in queryset.order_by('schedule_date', 'staff_id'):
            s_dict = s.to_dict()
            s_dict['shift_color'] = shift_dict.get(s.shift_id, {}).color if s.shift_id in shift_dict else None
            schedules.append(s_dict)

        return schedules

    @staticmethod
    def _normalize_date(date_val):
        """标准化日期格式"""
        if isinstance(date_val, str):
            return datetime.strptime(date_val, '%Y-%m-%d').date()
        return date_val

    @staticmethod
    def _check_conflict(staff_id, date_str, existing_schedules):
        """检查指定日期是否有排班冲突"""
        return any(
            s.get('staff_id') == staff_id and s.get('schedule_date') == date_str
            for s in existing_schedules
        )

    @staticmethod
    def _create_schedule_entry(staff, shift, date_str):
        """创建排班记录"""
        return {
            'staff_id': staff.id,
            'staff_name': staff.user_name,
            'schedule_date': date_str,
            'shift_id': shift.id,
            'shift_name': shift.name,
        }

    @classmethod
    def _generate_work_rest_schedule(cls, staff, shift, start_date, end_date, existing_schedules):
        """生成上X休Y模式的排班"""
        schedules = []
        conflicts = []
        work_count = 0
        rest_count = 0
        is_work_cycle = True
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')

            if is_work_cycle:
                if cls._check_conflict(staff.id, date_str, existing_schedules):
                    conflicts.append(date_str)
                else:
                    schedules.append(cls._create_schedule_entry(staff, shift, date_str))

                work_count += 1
                if work_count >= shift.work_days:
                    work_count = 0
                    is_work_cycle = False
            else:
                rest_count += 1
                if rest_count >= shift.rest_days:
                    rest_count = 0
                    is_work_cycle = True

            current_date += timedelta(days=1)

        return schedules, conflicts

    @classmethod
    def _generate_daily_schedule(cls, staff, shift, start_date, end_date, existing_schedules):
        """生成每日排班（自定义模式）"""
        schedules = []
        conflicts = []
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')

            if cls._check_conflict(staff.id, date_str, existing_schedules):
                conflicts.append(date_str)
            else:
                schedules.append(cls._create_schedule_entry(staff, shift, date_str))

            current_date += timedelta(days=1)

        return schedules, conflicts

    @classmethod
    def generate_auto_schedule(cls, staff, shift, start_date, end_date, existing_schedules=None):
        """
        自动生成排班

        Args:
            staff: 排班人员 (ScheduleStaff对象或包含id/user_name的字典)
            shift: 班次规则 (ScheduleShift对象)
            start_date: 开始日期 (datetime或date对象)
            end_date: 结束日期 (datetime或date对象)
            existing_schedules: 已有排班列表，用于冲突检测

        Returns:
            dict: {
                'schedules': list,  # 生成的排班列表
                'conflicts': list   # 冲突日期列表
            }
        """
        existing_schedules = existing_schedules or []
        start_date = cls._normalize_date(start_date)
        end_date = cls._normalize_date(end_date)

        if shift.shift_type == 'work_rest' and shift.work_days and shift.rest_days:
            schedules, conflicts = cls._generate_work_rest_schedule(
                staff, shift, start_date, end_date, existing_schedules
            )
        else:
            schedules, conflicts = cls._generate_daily_schedule(
                staff, shift, start_date, end_date, existing_schedules
            )

        return {'schedules': schedules, 'conflicts': conflicts}

    @staticmethod
    def check_schedule_conflict(staff_id, schedule_date, exclude_id=None):
        """
        检查排班冲突

        Args:
            staff_id: 人员ID
            schedule_date: 日期
            exclude_id: 排除的排班ID（用于更新时）

        Returns:
            Schedule or None: 如果存在冲突返回排班对象，否则None
        """
        query = Schedule.objects.filter(
            staff_id=staff_id,
            schedule_date=schedule_date
        )
        if exclude_id:
            query = query.exclude(pk=exclude_id)
        return query.first()

    @staticmethod
    def create_or_update_schedule(form_data, user, existing_id=None):
        """
        创建或更新排班

        Args:
            form_data: 表单数据
            user: 当前用户
            existing_id: 现有排班ID（更新时）

        Returns:
            Schedule: 创建或更新的排班对象
        """
        from libs import human_datetime

        if existing_id:
            # 更新现有记录
            schedule = Schedule.objects.filter(pk=existing_id).first()
            if schedule:
                for key, value in form_data.items():
                    setattr(schedule, key, value)
                schedule.updated_at = human_datetime()
                schedule.updated_by = user
                schedule.save()
                logger.info(f'Updated schedule: staff_id={form_data.get("staff_id")}, date={form_data.get("schedule_date")}')
                return schedule
        else:
            # 创建新记录
            form_data['created_by'] = user
            if not getattr(user, 'is_supper', False):
                form_data['tenant_id'] = getattr(user, 'tenant_id', 'admin')
            schedule = Schedule.objects.create(**form_data)
            logger.info(f'Created schedule: staff_id={form_data.get("staff_id")}, date={form_data.get("schedule_date")}')
            return schedule

    @staticmethod
    def batch_adjust_schedules(adjustments, user):
        """
        批量调整排班日期

        Args:
            adjustments: 调整列表 [{'id': int, 'schedule_date': str}, ...]
            user: 当前用户

        Returns:
            tuple: (success_count, error_count)
        """
        from libs import human_datetime
        from libs.tenant_utils import apply_tenant_filter

        success_count = 0
        error_count = 0

        for adjustment in adjustments:
            schedule_id = adjustment.get('id')
            new_date = adjustment.get('schedule_date')

            if not schedule_id or not new_date:
                error_count += 1
                continue

            schedule = apply_tenant_filter(
                Schedule.objects.filter(pk=schedule_id),
                user
            ).first()

            if schedule:
                schedule.schedule_date = new_date
                schedule.updated_at = human_datetime()
                schedule.updated_by = user
                schedule.save()
                success_count += 1
                logger.info(f'Adjusted schedule {schedule_id} to {new_date}')
            else:
                error_count += 1

        return success_count, error_count

    @staticmethod
    def filter_schedules_by_month(queryset, year, month):
        """
        按月过滤排班

        Args:
            queryset: Schedule查询集
            year: 年份
            month: 月份

        Returns:
            QuerySet: 过滤后的查询集
        """
        if year:
            queryset = queryset.filter(schedule_date__startswith=f'{year}-')
        if month:
            month_str = str(month).zfill(2)
            queryset = queryset.filter(schedule_date__startswith=f'{year}-{month_str}-')
        return queryset

    @staticmethod
    def filter_schedules_by_staff_and_date(queryset, staff_ids, start_date, end_date):
        """
        按人员和日期范围过滤排班

        Args:
            queryset: Schedule查询集
            staff_ids: 人员ID列表
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            QuerySet: 过滤后的查询集
        """
        if staff_ids:
            queryset = queryset.filter(staff_id__in=staff_ids)
        if start_date:
            queryset = queryset.filter(schedule_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(schedule_date__lte=end_date)
        return queryset
