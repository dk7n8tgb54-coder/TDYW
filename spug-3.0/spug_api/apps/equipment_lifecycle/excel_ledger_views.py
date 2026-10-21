# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 路线维护台账视图（创建/填写/完成/更正/历史/导出）。

权限域（复用既有台账权限码，不新增）：
- equipment_lifecycle.ledger.view：列表 / 详情
- equipment_lifecycle.ledger.add：按模板版本创建台账
- equipment_lifecycle.ledger.edit：保存填写值 / 完成后更正
- equipment_lifecycle.ledger.submit：完成填写（流程终点）
- equipment_lifecycle.ledger.export：导出 Excel / PDF

约定：
- Excel 路线台账 created_from='excel_template'，由本组视图接入；
- 流程简化（2026-10-16）：完成填写（complete，草稿 → 已完成）替代原
  "提交"；已完成台账修改走 correct/ 更正（须填原因，记录前后值）；
  作废/删除沿用既有 /ledgers/<pk>/ 端点（作废须填原因，删除仅草稿与
  旧流程历史状态）；
- 导出为文件副作用视图，使用 transaction.non_atomic_requests；
- 导出文件名取版本源文件名（去扩展名）+ 状态后缀，二进制直接下发。
"""
from django.db import transaction
from django.http import HttpResponse
from django.utils.encoding import quote
from django.views.generic import View

from libs import auth, json_response

from apps.logs.audit import record_audit_event
from apps.equipment_lifecycle import (
    excel_ledger_services,
    excel_pdf_service,
    ledger_template_group_services,
)
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
    'draft': '草稿', 'completed': '已完成', 'void': '已作废',
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
        try:
            # 填写值整体替换（仅草稿可编辑）
            if 'values' in body:
                excel_ledger_services.update_values(request.user, ledger, body.get('values'))
        except ExcelLedgerError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'action_kind': 'save_excel_values',
                         'version_id': ledger.excel_record.version_id})
        return json_response({'data': excel_ledger_services.ledger_detail(ledger)})


class ExcelLedgerCompleteView(View):
    """完成填写（流程终点）：必填校验通过后 草稿 → 已完成。"""

    @auth('equipment_lifecycle.ledger.submit')
    def post(self, request, pk):
        ledger, error = excel_ledger_services.complete_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'action_kind': 'complete_excel_ledger',
                         'status': ledger.status})
        return json_response({'data': excel_ledger_services.ledger_detail(ledger)})


class ExcelLedgerCorrectView(View):
    """已完成台账更正：POST /excel-ledgers/<pk>/correct/。

    body: {"reason": 必填原因, "values"?: 整体填写值}。
    变更前后值逐项写入更正记录（修改人/时间由更正记录承载），无实际变更拒绝。
    """

    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger = excel_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        ledger, correction, changes, error = excel_ledger_services.correct_completed_ledger(
            request.user, ledger, body)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'action_kind': 'correct_excel_ledger',
                         'reason': correction.reason, 'changes': changes})
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


class ExcelLedgerPrintPreviewView(View):
    """打印预览 PDF（详情"打印预览"页签 / 翻阅真实打印预览）。

    URL：POST /excel-ledgers/<pk>/print-preview/。与导出 PDF 同一生成
    服务与同一模板级参数（保证「预览 = 下载」一致），Content-Disposition
    inline 供 iframe/新窗口展示；带 X-El-Pdf-Pages/X-El-Pdf-Paper 真实
    反馈头（pypdf 读取生成结果）。结果按内容寻址缓存，台账值、版本或
    参数变化自然失效。
    """

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def post(self, request, pk):
        ledger = excel_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        try:
            content, cached = excel_ledger_services.print_preview_pdf(
                request.user, ledger)
        except ExcelLedgerError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'export', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'format': 'pdf', 'preview': True, 'cached': cached,
                         'version_id': ledger.excel_record.version_id})
        base_name = excel_ledger_services.export_base_name(ledger)
        response = HttpResponse(content, content_type=PDF_CONTENT_TYPE)
        response['Content-Disposition'] = "inline; filename*=UTF-8''%s" % quote(
            '%s-打印预览.pdf' % base_name)
        info = excel_pdf_service.pdf_page_info(content)
        if info.get('pages') is not None:
            response['X-El-Pdf-Pages'] = str(info['pages'])
        if info.get('paper'):
            response['X-El-Pdf-Paper'] = info['paper']
        return response


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
    query string 传入（与组内列表同口径：status/keyword/ledger_type）：
    - GET：确认框数据（模板名/匹配数/状态范围/涉及版本），
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
                         'status': filters['status']})
        return file_response(filename, content, PDF_CONTENT_TYPE)


class LedgerMultiTemplatePdfExportView(View):
    """台账列表"批量导出 PDF"（按模板多选，2026-10-21）。

    URL：/ledgers/export-pdf/，替换原"导出明细 CSV"入口（周月维护/季维护
    两个列表的"按维护周期"与"按模板查看"视图共用）：
    - GET：模板候选清单（本租户、指定台账类型，含已停用但有历史台账的
      模板；各状态数量与版本分布供弹窗预览与选择）；
    - POST：实际导出。请求体 JSON {ledger_type, template_ids, status,
      expected_totals}：后端按模板 ID 重新查询完整记录（不信任前端数量），
      每模板一份合并 PDF，多模板打包 ZIP；expected_totals 与当前数量不一致
      时明确报错要求重新确认；任一条生成失败整体失败，不返回部分产物。
    导出为文件副作用视图，使用 transaction.non_atomic_requests。
    """

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def get(self, request):
        try:
            data = ledger_template_group_services.list_export_templates(
                request.user, request.GET.get('ledger_type') or '')
        except LedgerValidationError as e:
            return json_response(error=str(e))
        return json_response({'data': data})

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def post(self, request):
        body = _read_json_body(request)
        if not isinstance(body, dict):
            return json_response(error='请先选择要导出的模板')
        try:
            filename, content, count = ledger_template_group_services.export_templates_pdfs(
                request.user,
                body.get('ledger_type') or '',
                body.get('template_ids'),
                status=body.get('status') or '',
                expected_totals=body.get('expected_totals'),
            )
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'export', AUDIT_TARGET_LEDGER, None, filename,
            after_value={'action_kind': 'batch_templates_pdf',
                         'ledger_type': body.get('ledger_type') or '',
                         'templates': len(body.get('template_ids') or []),
                         'count': count, 'status': body.get('status') or ''})
        content_type = (ledger_template_group_services.ZIP_CONTENT_TYPE
                        if filename.endswith('.zip') else PDF_CONTENT_TYPE)
        return file_response(filename, content, content_type)
