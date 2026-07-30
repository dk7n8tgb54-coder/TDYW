# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
故障管理导出服务

导出字段配置与查询逻辑集中在此，与 views 解耦。
导出基于当前筛选条件下的全部数据，而非当前页。
"""
import logging
import re
from datetime import datetime
from calendar import monthrange

from django.views.generic import View
from libs import auth
from libs.export_utils import build_excel_response, check_export_limit, build_export_error_response
from libs.tenant_utils import apply_tenant_filter
from apps.fault.models import FaultRecord

logger = logging.getLogger(__name__)

# 导出列定义：(字段, 表头)
EXCEL_COLUMNS = [
    ('system_name', '系统名称'),
    ('device_code', '设备编号'),
    ('fault_date', '故障日期'),
    ('handler', '处置人员'),
    ('recorder', '记录人员'),
    ('fault_level', '故障评级'),
    ('fault_phenomenon', '故障现象'),
    ('handling_process', '处置过程'),
    ('created_at', '创建时间'),
]

SHEET_NAME = '故障处置记录'


def _parse_fault_date_filter(fault_date_str):
    """将前端传入的 fault_date 搜索串转为日期范围 (start, end)。
    
    支持 YYYY / YYYY-MM / YYYY-MM-DD 三种前缀格式，
    返回 (start_str, end_str) 用于 __gte/__lt 查询。
    无法识别时返回 None。
    """
    s = fault_date_str.strip()
    # YYYY-MM-DD
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            start = datetime(y, mo, d).date()
            end = start.replace(day=start.day + 1) if start.day < monthrange(y, mo)[1] else (
                datetime(y, mo + 1, 1).date() if mo < 12 else datetime(y + 1, 1, 1).date()
            )
            return start.isoformat(), end.isoformat()
        except (ValueError, OverflowError):
            return None
    # YYYY-MM
    m = re.match(r'^(\d{4})-(\d{1,2})$', s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            start = datetime(y, mo, 1).date()
            end = datetime(y + 1, 1, 1).date() if mo == 12 else datetime(y, mo + 1, 1).date()
            return start.isoformat(), end.isoformat()
    # YYYY
    m = re.match(r'^(\d{4})$', s)
    if m:
        y = int(m.group(1))
        return f'{y}-01-01', f'{y + 1}-01-01'
    return None


def get_export_queryset(request):
    """按当前筛选条件查询数据，与前端 store 的过滤规则保持一致。"""
    qs = apply_tenant_filter(FaultRecord.objects.filter(is_deleted=False), request.user)
    # 前端 store 用字符串 includes 模糊匹配，后端用 contains 等价
    system_name = request.GET.get('system_name')
    if system_name:
        qs = qs.filter(system_name__icontains=system_name)
    fault_date = request.GET.get('fault_date')
    if fault_date:
        # P1(R1): 优先将日期搜索串解析为范围查询以走索引；
        # 无法解析时回退 icontains（兼容用户输入部分文本）
        date_range = _parse_fault_date_filter(fault_date)
        if date_range:
            qs = qs.filter(fault_date__gte=date_range[0], fault_date__lt=date_range[1])
        else:
            qs = qs.filter(fault_date__icontains=fault_date)
    handler = request.GET.get('handler')
    if handler:
        qs = qs.filter(handler__icontains=handler)
    fault_level = request.GET.get('fault_level')
    if fault_level:
        qs = qs.filter(fault_level__icontains=fault_level)
    # 精确日期范围（用于导出文件名标注与范围控制）
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date:
        qs = qs.filter(fault_date__gte=start_date)
    if end_date:
        qs = qs.filter(fault_date__lte=end_date)
    return qs


def _build_filename(request):
    """生成文件名：故障处置记录_筛选范围_导出时间.xlsx"""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date and end_date:
        scope = '%s-%s' % (start_date, end_date)
    else:
        scope = 'all'
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    return '故障处置记录_%s_%s.xlsx' % (scope, now)


class FaultRecordExportView(View):
    """故障处置记录 Excel 导出"""

    @auth('fault.faultrecord.view')
    def get(self, request):
        qs = get_export_queryset(request)
        count, error_resp = check_export_limit(qs)
        if error_resp:
            return error_resp
        if count == 0:
            return build_export_error_response('当前筛选条件下没有可导出的数据')

        # 使用 to_dict 获取字段值，配合 created_by 等外键避免 N+1
        records = qs.select_related('created_by', 'updated_by')
        rows = [obj.to_dict() for obj in records.iterator()]
        filename = _build_filename(request)
        return build_excel_response(filename, SHEET_NAME, EXCEL_COLUMNS, rows)
