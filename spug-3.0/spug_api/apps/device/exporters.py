# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
设备管理导出服务

设备列表 Excel 导出，基于当前筛选条件下的全部数据。
单台设备履历 PDF 导出保留在 views.DeviceResumeExportView 中。
"""
import logging
from datetime import datetime

from django.db.models import Q
from django.views.generic import View
from libs import auth
from libs.export_utils import build_excel_response, check_export_limit, build_export_error_response
from libs.tenant_utils import apply_tenant_filter
from apps.device.models import DeviceResume
from apps.logs.audit import record_audit_event

logger = logging.getLogger(__name__)

# 导出列定义：(字段, 表头)
# current_status_text 由 to_view() 生成（'正常'/'故障'等中文）
EXCEL_COLUMNS = [
    ('device_sn', '设备编号'),
    ('device_name', '设备名称'),
    ('device_model', '设备型号'),
    ('call_sign', '设备呼号'),
    ('use_unit', '使用单位'),
    ('responsible_user_name', '设备负责人'),
    ('current_status_text', '当前设备状态'),
    ('device_purpose', '设备用途'),
    ('created_at', '创建时间'),
]

SHEET_NAME = '设备列表'


def get_export_queryset(request):
    """按当前筛选条件查询数据，与 DeviceResumeView 列表筛选规则一致。"""
    qs = apply_tenant_filter(DeviceResume.objects.all(), request.user)
    # 统一关键字搜索：同时匹配设备编号或设备名称（与列表接口 DeviceResumeView 一致）
    keyword = request.GET.get('keyword')
    if keyword:
        qs = qs.filter(
            Q(device_sn__icontains=keyword) | Q(device_name__icontains=keyword)
        )
    # 兼容旧参数：单独传 device_sn / device_name 时仍按精确字段模糊匹配
    device_sn = request.GET.get('device_sn')
    if device_sn:
        qs = qs.filter(device_sn__icontains=device_sn)
    device_name = request.GET.get('device_name')
    if device_name:
        qs = qs.filter(device_name__icontains=device_name)
    device_model = request.GET.get('device_model')
    if device_model:
        qs = qs.filter(device_model__icontains=device_model)
    # current_status 支持多选，前端以数组传递
    current_status = request.GET.getlist('current_status')
    if current_status:
        qs = qs.filter(current_status__in=current_status)
    use_unit = request.GET.get('use_unit')
    if use_unit:
        qs = qs.filter(use_unit__icontains=use_unit)
    manufacturer = request.GET.get('manufacturer')
    if manufacturer:
        qs = qs.filter(manufacturer__icontains=manufacturer)
    return qs


def _build_filename():
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    return '设备台账_%s.xlsx' % now


class DeviceListExportView(View):
    """设备列表 Excel 导出"""

    @auth('device.device_resume.view')
    def get(self, request):
        qs = get_export_queryset(request)
        count, error_resp = check_export_limit(qs)
        if error_resp:
            return error_resp
        if count == 0:
            return build_export_error_response('当前筛选条件下没有可导出的数据')

        records = qs.select_related('created_by', 'updated_by')
        # to_view() 包含 current_status_text 中文状态
        rows = [obj.to_view() for obj in records.iterator()]
        filename = _build_filename()
        record_audit_event(request, 'export', 'device',
                           target_name=filename,
                           detail={'count': len(rows), 'format': 'xlsx'})
        return build_excel_response(filename, SHEET_NAME, EXCEL_COLUMNS, rows)
