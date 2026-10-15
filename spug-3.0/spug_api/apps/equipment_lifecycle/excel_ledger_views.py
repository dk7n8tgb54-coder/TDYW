# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 路线维护台账视图（创建/填写/提交/历史/导出，2026-09-28 试点）。

权限域（复用既有台账权限码，不新增）：
- equipment_lifecycle.ledger.view：列表 / 详情
- equipment_lifecycle.ledger.add：按模板版本创建台账
- equipment_lifecycle.ledger.edit：保存填写值
- equipment_lifecycle.ledger.submit：提交
- equipment_lifecycle.ledger.export：导出 Excel / PDF

约定：
- Excel 路线台账 created_from='excel_template'，由本组视图接入；正式台账
  列表（LedgerView）不返回该类台账，两路互不干扰；
- 复核/退回/作废沿用既有 /ledgers/<pk>/ 端点（不涉及明细，天然兼容）；
- 导出为文件副作用视图，使用 transaction.non_atomic_requests；
- 导出文件名取版本源文件名（去扩展名）+ 状态后缀，二进制直接下发。
"""
from django.db import transaction
from django.http import HttpResponse
from django.views.generic import View

from libs import auth, json_response

from apps.logs.audit import record_audit_event
from apps.equipment_lifecycle import excel_ledger_services, ledger_template_group_services
from apps.equipment_lifecycle.excel_ledger_services import ExcelLedgerError
from apps.equipment_lifecycle.excel_template_views import (
    XLSX_CONTENT_TYPE,
    _na,
    file_response,
)
from apps.equipment_lifecycle.ledger_services import LedgerValidationError
from apps.equipment_lifecycle.ledger_views import (
    AUDIT_TARGET_LEDGER,
    _read_json_body,
)

# 导出文件名后缀（与前端 constants.js 的状态文案一致）
LEDGER_STATUS_SUFFIX = {
    'draft': '草稿', 'submitted': '已提交', 'returned': '已退回',
    'reviewed': '已复核', 'void': '已作废',
}

PDF_CONTENT_TYPE = 'application/pdf'


class ExcelLedgerView(View):
    """Excel 路线台账列表 / 按模板版本创建。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        return json_response(excel_ledger_services.list_ledgers(request.user, request))

    @auth('equipment_lifecycle.ledger.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = excel_ledger_services.create_ledger(request.user, body)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'create', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'ledger_type': ledger.ledger_type,
                         'created_from': ledger.created_from,
                         'excel_version_id': ledger.excel_record.version_id})
        return json_response({'data': excel_ledger_services.ledger_detail(ledger)})


class ExcelLedgerDetailView(View):
    """台账详情（表头 + 版本快照 + 填写值）/ 保存填写值。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        ledger = excel_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        return json_response({'data': excel_ledger_services.ledger_detail(ledger)})

    @auth('equipment_lifecycle.ledger.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger = excel_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        header_updated = False
        try:
            # 表头执行信息（实际执行日期/执行人）与填写值可同请求分别提交
            if isinstance(body.get('header'), dict):
                excel_ledger_services.update_header(request.user, ledger, body['header'])
                header_updated = True
            if 'values' in body:
                excel_ledger_services.update_values(request.user, ledger, body.get('values'))
        except ExcelLedgerError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'action_kind': 'save_excel_values' if not header_updated
                         else 'save_excel_header',
                         'version_id': ledger.excel_record.version_id,
                         'executed_date': str(ledger.executed_date or '')})
        return json_response({'data': excel_ledger_services.ledger_detail(ledger)})


class ExcelLedgerSubmitView(View):
    """提交：必填校验通过后 草稿/已退回 → 已提交。"""

    @auth('equipment_lifecycle.ledger.submit')
    def post(self, request, pk):
        ledger, error = excel_ledger_services.submit_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'action_kind': 'submit_excel_ledger',
                         'status': ledger.status})
        return json_response({'data': excel_ledger_services.ledger_detail(ledger)})


class ExcelLedgerExportView(View):
    """导出 Excel / PDF（读取台账引用版本的原始 .xlsx 副本填充）。

    URL：POST /excel-ledgers/<pk>/export/excel/ 与 /export/pdf/，
    以 path 后缀区分格式（同视图两个挂载）。PDF 导出可携带 JSON body
    {"pdf_params": {...}} 覆盖模板参数（高级设置，仅当次导出生效）。
    """

    FORMAT_FIELD_LABEL = {'excel': 'xlsx', 'pdf': 'pdf'}

    def _export(self, request, pk, fmt):
        ledger = excel_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return None, json_response(error='台账不存在')
        pdf_params = None
        if fmt == 'pdf':
            # body 可选（兼容无 body 的既有调用）：仅当解析为 dict 且携带
            # pdf_params 时应用覆盖，其余一律按默认版本参数导出
            body = _read_json_body(request)
            pdf_params = body.get('pdf_params') if isinstance(body, dict) else None
        try:
            if fmt == 'pdf':
                content = excel_ledger_services.export_pdf_file(
                    request.user, ledger, pdf_params=pdf_params)
                content_type = PDF_CONTENT_TYPE
            else:
                content = excel_ledger_services.export_excel(request.user, ledger)
                content_type = XLSX_CONTENT_TYPE
        except ExcelLedgerError as e:
            return None, json_response(error=str(e))
        record_audit_event(
            request, 'export', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'format': fmt,
                         'version_id': ledger.excel_record.version_id})
        base_name = excel_ledger_services.export_base_name(ledger)
        suffix = LEDGER_STATUS_SUFFIX.get(ledger.status, ledger.status)
        filename = '%s-%s.%s' % (base_name, suffix, fmt)
        return file_response(filename, content, content_type), None

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def post(self, request, pk, fmt):
        if fmt not in self.FORMAT_FIELD_LABEL:
            return json_response(error='不支持的导出格式')
        response, error = self._export(request, pk, fmt)
        return response if response is not None else error


class ExcelLedgerExportCheckView(View):
    """导出前版式预检：POST /excel-ledgers/<pk>/export/check/。

    只读估算（横向溢出/缩放过小/空白工作表/分页越界/必填未填），返回
    {"data": {"warnings": [...]}}；body 可选，携带 {"pdf_params": {...}}
    时按高级设置覆盖参数估算。不落库、无文件副作用。
    """

    @auth('equipment_lifecycle.ledger.export')
    def post(self, request, pk):
        body = _read_json_body(request)
        pdf_params = body.get('pdf_params') if isinstance(body, dict) else None
        ledger = excel_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        try:
            warnings = excel_ledger_services.export_check(
                request.user, ledger, pdf_params=pdf_params)
        except ExcelLedgerError as e:
            return json_response(error=str(e))
        return json_response({'data': {'warnings': warnings}})


class LedgerTemplateGroupPdfExportView(View):
    """模板组内批量 PDF 导出（"按模板查看 → 导出本模板台账"，2026-10-11）。

    URL：/ledgers/template-groups/<group_key>/export-pdf/，筛选参数经
    query string 传入（与组内列表同口径：status/keyword/executed_from/
    executed_to/ledger_type）：
    - GET：确认框数据（模板名/匹配数/实际日期范围/状态范围/涉及版本），
      状态未显式筛选时返回默认有效状态范围（不含草稿/已作废）；
    - POST：实际导出。后端按同口径重新查询并固定 ID 清单（不信任前端
      台账 ID/数量），每条台账用创建时模板版本生成 PDF 后依序合并下发，
      任一条失败整体失败；成功文件名含模板名与导出日期（非法字符净化）。
    导出为文件副作用视图，使用 transaction.non_atomic_requests。
    """

    def _filters(self, request):
        params = request.GET
        return dict(
            ledger_type=params.get('ledger_type') or '',
            status=params.get('status') or '',
            keyword=params.get('keyword') or '',
            executed_from=params.get('executed_from') or '',
            executed_to=params.get('executed_to') or '',
        )

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def get(self, request, group_key):
        try:
            data = ledger_template_group_services.preview_group_pdf_export(
                request.user, group_key, **self._filters(request))
        except LedgerValidationError as e:
            return json_response(error=str(e))
        return json_response({'data': data})

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def post(self, request, group_key):
        filters = self._filters(request)
        try:
            filename, content, count = ledger_template_group_services.export_group_pdfs(
                request.user, group_key, **filters)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'export', AUDIT_TARGET_LEDGER, None, filename,
            after_value={'action_kind': 'batch_template_pdf',
                         'group_key': str(group_key), 'count': count,
                         'status': filters['status'],
                         'executed_from': filters['executed_from'],
                         'executed_to': filters['executed_to']})
        return file_response(filename, content, PDF_CONTENT_TYPE)
