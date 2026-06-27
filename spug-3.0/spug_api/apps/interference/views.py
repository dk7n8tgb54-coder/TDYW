# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.utils import timezone
from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.interference.models import Interference
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class InterferenceView(View):
    @auth('interference.interference.view')
    def get(self, request):
        # 基础 QuerySet（租户隔离）
        base_qs = apply_tenant_filter(Interference.objects.all(), request.user)

        # 下拉选项基于租户全部数据，避免筛选后选项变少
        interference_types = list(base_qs.order_by('interference_type')
                                  .values_list('interference_type', flat=True)
                                  .distinct())
        report_depts = list(base_qs.order_by('report_dept')
                               .values_list('report_dept', flat=True)
                               .distinct())

        # 应用筛选条件
        records = base_qs
        frequency = request.GET.get('frequency')
        if frequency:
            records = records.filter(frequency__icontains=frequency)
        report_dept = request.GET.get('report_dept')
        if report_dept:
            records = records.filter(report_dept__icontains=report_dept)
        interference_type = request.GET.get('interference_type')
        if interference_type:
            records = records.filter(interference_type__icontains=interference_type)
        # datetime 为 CharField 存 "YYYY-MM-DD HH:MM:SS"，end_date 补 23:59:59 包含整天
        start_date = request.GET.get('start_date')
        if start_date:
            records = records.filter(datetime__gte=start_date)
        end_date = request.GET.get('end_date')
        if end_date:
            records = records.filter(datetime__lte=end_date + ' 23:59:59')

        # 先统计过滤后总数，再分页
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 100))
        total_count = records.count()
        records = records.select_related('created_by', 'updated_by')
        offset = (page - 1) * page_size
        records = records[offset:offset + page_size]

        return json_response({
            'interference_types': interference_types,
            'report_depts': report_depts,
            'records': [x.to_view() for x in records],
            'total': total_count,
            'page': page,
            'page_size': page_size
        })

    @auth('interference.interference.add|interference.interference.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('frequency', help='请输入频率'),
            Argument('report_dept', help='请输入汇报科室'),
            Argument('datetime', help='请选择日期时间'),
            Argument('coordinates', help='请输入坐标'),
            Argument('interference_type', help='请选择干扰类型'),
            Argument('phenomenon', help='请输入现象'),
            Argument('flight_number', required=False),
            Argument('aircraft_type', required=False),
            Argument('is_reported', help='请选择是否上报')
        ).parse(request.body)
        if error is None:
            # 校验 datetime 格式必须为 YYYY-MM-DD HH:MM:SS（CharField 存储依赖格式一致性）
            if form.datetime:
                try:
                    datetime.strptime(form.datetime, '%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    return json_response(error='日期时间格式必须为 YYYY-MM-DD HH:MM:SS')
            if form.id:
                if not request.user.has_perms({'interference.interference.edit'}):
                    return json_response(error='权限拒绝')
                form.updated_at = human_datetime()
                form.updated_by = request.user
                record_id = form.pop('id')
                # 使用 apply_tenant_filter 防止跨租户编辑，超管可编辑所有租户记录
                qs = apply_tenant_filter(Interference.objects.all(), request.user)
                updated_count = qs.filter(pk=record_id).update(**form)
                
                if updated_count == 0:
                    error = '编辑失败：记录不存在或无权限编辑'
            else:
                if not request.user.has_perms({'interference.interference.add'}):
                    return json_response(error='权限拒绝')
                form.created_by = request.user
                assign_tenant_id(form, request.user)
                Interference.objects.create(**form)
        return json_response(error=error)

    @auth('interference.interference.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            # 使用 apply_tenant_filter 防止跨租户删除，超管可删除所有租户记录
            qs = apply_tenant_filter(Interference.objects.all(), request.user)
            deleted_count, _ = qs.filter(pk=form.id).delete()
            
            if deleted_count == 0:
                error = '删除失败：记录不存在或无权限删除'
        return json_response(error=error)


class InterferenceStatisticsView(View):
    @auth('interference.statistics.view')
    def get(self, request):
        logger.info('[InterferenceStatistics] 开始获取统计数据')
        try:
            records = apply_tenant_filter(Interference.objects.all(), request.user)

            # 获取时间范围参数
            start_date_str = request.GET.get('start_date')
            end_date_str = request.GET.get('end_date')

            if start_date_str and end_date_str:
                start_date = start_date_str
                end_date = end_date_str + ' 23:59:59'
                filtered_records = records.filter(datetime__gte=start_date, datetime__lte=end_date)
            else:
                now = timezone.now()
                year_start = now.strftime('%Y-01-01')
                year_end = now.strftime('%Y-12-31 23:59:59')
                filtered_records = records.filter(datetime__gte=year_start, datetime__lte=year_end)

            logger.info(f'[InterferenceStatistics] 过滤后记录数: {filtered_records.count()}')

            # 按日期前缀聚合：datetime 为 CharField 存 "YYYY-MM-DD HH:MM:SS"，
            # 用 Substr 截取前 10 位作为日期，避免同一天不同时间产生重复日期行
            from django.db.models import Count
            from django.db.models.functions import Substr

            annotated = filtered_records.annotate(date=Substr('datetime', 1, 10))

            # 按日期、频率统计
            freq_stats = annotated.values('date', 'frequency').annotate(
                count=Count('id')
            ).order_by('date', 'frequency')

            # 按日期、类型统计
            type_stats = annotated.values('date', 'interference_type').annotate(
                count=Count('id')
            ).order_by('date', 'interference_type')

            total_count = filtered_records.count()

            freq_trend = []
            type_trend = []
            seen_freq = set()
            seen_type = set()

            for stat in freq_stats:
                date_str = stat['date'] or ''
                freq_trend.append({
                    'date': date_str,
                    'frequency': stat['frequency'],
                    'count': stat['count']
                })
                seen_freq.add(stat['frequency'])

            for stat in type_stats:
                date_str = stat['date'] or ''
                type_trend.append({
                    'date': date_str,
                    'type': stat['interference_type'],
                    'count': stat['count']
                })
                seen_type.add(stat['interference_type'])

            logger.info(f'[InterferenceStatistics] 频率趋势: {len(freq_trend)} 条, 类型趋势: {len(type_trend)} 条, 总计: {total_count}')
            return json_response({
                'frequency_stats': freq_trend,
                'type_stats': type_trend,
                'total_count': total_count,
                'month_count': total_count
            })
        except Exception as e:
            logger.error(f'[InterferenceStatistics] 错误: {e}')
            import traceback
            logger.error(traceback.format_exc())
            return json_response(error=str(e))
