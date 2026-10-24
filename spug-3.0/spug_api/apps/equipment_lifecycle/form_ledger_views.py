# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""数字表单路线台账视图（2026-10-21）。

权限域与 Excel 台账一致（不新增权限码）：equipment_lifecycle.ledger.view
|add|edit|submit|export。列表不设独立端点：数字表单台账与 Excel/手工台账
一并出现在统一列表（/ledgers/，source_type=form 区分来源）；作废/删除
沿用既有 /ledgers/<pk>/void|DELETE 端点（通用状态机，服务层独立校验）。

PDF 预览/导出（2026-10-22）：预览与下载调用同一生成函数
（form_pdf_service.ledger_pdf，版本快照 + 已保存填写值），保证看到的
就是下载的结果；导出不做必填拦截（必填终验由"完成填写"承载，空值在
PDF 中如实显示"未填写"，不伪装已填）。
"""
from django.http import HttpResponse
from django.utils.encoding import quote
from django.views.generic import View

from libs import json_response, auth

from apps.logs.audit import record_audit_event
from apps.equipment_lifecycle import form_ledger_services, form_pdf_service
from apps.equipment_lifecycle.excel_ledger_views import LEDGER_STATUS_SUFFIX
from apps.equipment_lifecycle.excel_template_views import _na, file_response
from apps.equipment_lifecycle.ledger_views import AUDIT_TARGET_LEDGER, _ledger_detail
from apps.equipment_lifecycle.views import _read_json_body

PDF_CONTENT_TYPE = 'application/pdf'


class FormLedgerView(View):
    @auth('equipment_lifecycle.ledger.add')
    def post(self, request):
        """按已发布数字表单模板版本创建台账（表头 + 填写记录一次写入）。"""
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = form_ledger_services.create_ledger(request.user, body)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_LEDGER, ledger.id,
                           ledger.ledger_no,
                           after_value={'ledger_type': ledger.ledger_type,
                                        'created_from': ledger.created_from,
                                        'source_form_template': ledger.source_form_template_id})
        return json_response(_ledger_detail(ledger, request.user))


class FormLedgerDetailView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        ledger = form_ledger_services.get_form_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        return json_response(_ledger_detail(ledger, request.user))

    @auth('equipment_lifecycle.ledger.edit')
    def put(self, request, pk):
        """保存填写值（整体替换；仅草稿可编辑，完成后修改走更正流程）。"""
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger = form_ledger_services.get_form_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        try:
            form_ledger_services.update_values(request.user, ledger, body.get('values'))
        except form_ledger_services.FormLedgerError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id,
                           ledger.ledger_no,
                           after_value={'action_kind': 'save_form_values'})
        return json_response(_ledger_detail(ledger, request.user))


class FormLedgerCompleteView(View):
    """完成填写（流程终点）：先保存未保存内容（前端保证），后端必填终验。"""

    @auth('equipment_lifecycle.ledger.submit')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        ledger, error = form_ledger_services.complete_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id,
                           ledger.ledger_no,
                           after_value={'action_kind': 'complete_form_ledger',
                                        'status': ledger.status,
                                        'source': body.get('source') or ''})
        return json_response(_ledger_detail(ledger, request.user))


def _form_ledger_pdf(request, pk):
    """取台账并生成 PDF 字节（预览与导出共用的唯一生成入口）。

    返回 (ledger, content, info, error_response)；权限域内按租户过滤，
    跨租户与其他路线台账一律按不存在处理（get_form_ledger）。
    """
    ledger = form_ledger_services.get_form_ledger(pk, request.user)
    if not ledger:
        return None, None, None, json_response(error='台账不存在')
    try:
        content, info = form_pdf_service.ledger_pdf(request.user, ledger)
    except (form_ledger_services.FormLedgerError,
            form_pdf_service.FormPdfError) as e:
        return None, None, None, json_response(error=str(e))
    return ledger, content, info, None


def _pdf_filename(ledger):
    """导出文件名：台账编号-模板名-状态后缀（与 Excel 路线同口径）。"""
    version = ledger.form_record.version if ledger.form_record else None
    template_name = version.template_name_snapshot if version else '数字表单台账'
    suffix = LEDGER_STATUS_SUFFIX.get(ledger.status, ledger.status)
    return '%s-%s-%s.pdf' % (ledger.ledger_no, template_name, suffix)


class FormLedgerPdfPreviewView(View):
    """数字表单台账 PDF 预览（与导出同一生成逻辑；inline 下发）。

    URL：POST /form-ledgers/<pk>/preview/pdf/。使用台账绑定的模板版本
    （不可变快照）与最近一次保存的填写值；未保存修改由前端明确提示
    （PDF 基于已保存数据）。响应 inline PDF（浏览器内嵌展示）并携带
    真实反馈头 X-El-Pdf-Pages / X-El-Pdf-Paper；文件副作用仅限临时
    目录（自动清理）。
    """

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def post(self, request, pk):
        ledger, content, info, error = _form_ledger_pdf(request, pk)
        if error:
            return error
        record_audit_event(
            request, 'export', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'format': 'pdf', 'preview': True,
                         'version_id': ledger.form_record.version_id})
        response = HttpResponse(content, content_type=PDF_CONTENT_TYPE)
        response['Content-Disposition'] = "inline; filename*=UTF-8''%s" % quote(
            _pdf_filename(ledger).replace('.pdf', '-预览.pdf'))
        if info.get('pages') is not None:
            response['X-El-Pdf-Pages'] = str(info['pages'])
        if info.get('paper'):
            response['X-El-Pdf-Paper'] = info['paper']
        return response


class FormLedgerPdfExportView(View):
    """数字表单台账 PDF 导出（与预览同一生成函数；附件下发）。

    URL：POST /form-ledgers/<pk>/export/pdf/。不做必填拦截：必填终验由
    "完成填写"承载，导出只是版式呈现，空值如实显示"未填写"。
    """

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def post(self, request, pk):
        ledger, content, info, error = _form_ledger_pdf(request, pk)
        if error:
            return error
        record_audit_event(
            request, 'export', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'format': 'pdf',
                         'version_id': ledger.form_record.version_id})
        return file_response(_pdf_filename(ledger), content, PDF_CONTENT_TYPE)
