# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
干扰管理导出服务

导出基于当前筛选条件下的全部数据，而非当前页。
序号按导出顺序动态生成，与前端列表展示一致。
"""
import logging
from datetime import datetime

from django.views.generic import View
from libs import auth
from libs.export_utils import build_excel_response, check_export_limit, build_export_error_response
from libs.tenant_utils import apply_tenant_filter
from apps.interference.models import Interference

logger = logging.getLogger(__name__)

# 导出列定义：(字段, 表头)，序号为动态生成字段
EXCEL_COLUMNS = [
    ('export_serial', '序号'),
    ('frequency', '频率'),
    ('report_dept', '汇报科室'),
    ('datetime', '日期时间'),
    ('coordinates', '坐标'),
    ('interference_type', '干扰类型'),
    ('phenomenon', '现象'),
    ('flight_number', '航班号'),
    ('aircraft_type', '机型'),
    ('is_reported', '是否上报'),
    ('created_at', '创建时间'),
]

SHEET_NAME = '干扰信息统计'


def get_export_queryset(request):
    """按当前筛选条件查询数据，与前端 store 的过滤规则保持一致。"""
    qs = apply_tenant_filter(Interference.objects.all(), request.user)
    frequency = request.GET.get('frequency')
    if frequency:
        qs = qs.filter(frequency__icontains=frequency)
    report_dept = request.GET.get('report_dept')
    if report_dept:
        qs = qs.filter(report_dept__icontains=report_dept)
    interference_type = request.GET.get('interference_type')
    if interference_type:
        qs = qs.filter(interference_type__icontains=interference_type)
    # 日期范围（datetime 为 CharField 存 "YYYY-MM-DD HH:MM:SS"，end_date 补 23:59:59 包含整天）
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date:
        qs = qs.filter(datetime__gte=start_date)
    if end_date:
        qs = qs.filter(datetime__lte=end_date + ' 23:59:59')
    return qs


def _build_filename(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date and end_date:
        scope = '%s-%s' % (start_date, end_date)
    else:
        scope = 'all'
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    return '干扰信息统计_%s_%s.xlsx' % (scope, now)


class InterferenceExportView(View):
    """干扰信息 Excel 导出"""

    @auth('interference.interference.view')
    def get(self, request):
        qs = get_export_queryset(request)
        count, error_resp = check_export_limit(qs)
        if error_resp:
            return error_resp
        if count == 0:
            return build_export_error_response('当前筛选条件下没有可导出的数据')

        records = qs.select_related('created_by', 'updated_by')
        rows = []
        for idx, obj in enumerate(records.iterator(), start=1):
            row = obj.to_dict()
            row['export_serial'] = idx
            rows.append(row)
        filename = _build_filename(request)
        return build_excel_response(filename, SHEET_NAME, EXCEL_COLUMNS, rows)
