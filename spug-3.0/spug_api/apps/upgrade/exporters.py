# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级管理导出服务

复用 RecordService 的筛选逻辑，保证导出结果与列表筛选一致。
导出基于当前筛选条件下的全部数据，而非当前页。
"""
import logging
from datetime import datetime

from django.views.generic import View
from libs import auth
from libs.export_utils import build_excel_response, check_export_limit, build_export_error_response
from libs.tenant_utils import apply_tenant_filter
from apps.upgrade.models import UpgradeRecord
from apps.upgrade.services.record_service import RecordService

logger = logging.getLogger(__name__)

# 导出列定义：(字段, 表头)
EXCEL_COLUMNS = [
    ('upgrade_no', '升级单号'),
    ('system', '系统'),
    ('upgrade_type', '升级类型'),
    ('version', '版本'),
    ('upgrade_time', '升级时间'),
    ('status', '状态'),
    ('owner', '负责人'),
    ('created_at', '创建时间'),
]

SHEET_NAME = '升级表单'


def _build_filters(request):
    """从请求参数构建 filters 字典，与列表接口一致"""
    filters = {}
    if request.GET.get('status'):
        filters['status'] = request.GET.get('status')
    if request.GET.get('system'):
        filters['system'] = request.GET.get('system')
    if request.GET.get('upgrade_type'):
        filters['upgrade_type'] = request.GET.get('upgrade_type')
    if request.GET.get('owner'):
        filters['owner'] = request.GET.get('owner')
    if request.GET.get('start_date') and request.GET.get('end_date'):
        filters['start_date'] = request.GET.get('start_date')
        filters['end_date'] = request.GET.get('end_date')
    return filters


def _build_filename(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date and end_date:
        scope = '%s-%s' % (start_date, end_date)
    else:
        scope = 'all'
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    return '升级表单_%s_%s.xlsx' % (scope, now)


class RecordExportView(View):
    """升级表单 Excel 导出"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        qs = apply_tenant_filter(UpgradeRecord.objects.all(), request.user)
        filters = _build_filters(request)
        qs = RecordService._apply_filters(qs, filters)
        qs = qs.order_by('-upgrade_time', '-id')

        count, error_resp = check_export_limit(qs)
        if error_resp:
            return error_resp
        if count == 0:
            return build_export_error_response('当前筛选条件下没有可导出的数据')

        records = qs.select_related('created_by', 'updated_by')
        filename = _build_filename(request)
        return build_excel_response(filename, SHEET_NAME, EXCEL_COLUMNS, list(records.iterator()))
