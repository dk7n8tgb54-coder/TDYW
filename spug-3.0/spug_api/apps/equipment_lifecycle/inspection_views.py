# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""值班巡检视图（今日巡检改造）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.inspection.view|add|edit|submit|del|export
- equipment_lifecycle.inspection_template.view|add|edit|del

业务规则（与 inspection_services 一致）：
- 巡检单唯一范围 = 值班日 + 巡检模板，值班人员登记在单上；
- 四个固定轮次（第四轮次日 6:30-6:50 归属前一值班日），不记录实际填写时间；
- 巡检单只负责记录巡检结果、异常内容和现场处理，不提供转故障/转工单接口；
  故障统一在故障处置模块创建，维修执行事项统一在工单管理模块创建；
- 历史巡检异常的处置状态（已转故障/已转工单）由来源关系动态推导、只读展示。
"""
import json as _json
from datetime import datetime

from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.export_utils import (
    build_excel_response,
    build_export_error_response,
    check_export_limit,
)
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import inspection_services
from apps.equipment_lifecycle import inspection_export
from apps.equipment_lifecycle.inspection_services import InspectionValidationError
from apps.equipment_lifecycle.models import InspectionDutySheet

AUDIT_TARGET_INSPECTION_SHEET = 'el_inspection_sheet'
AUDIT_TARGET_INSPECTION_TEMPLATE = 'el_inspection_template'

DATETIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%dT%H:%M', '%Y-%m-%d')


def _read_json_body(request):
    try:
        return _json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        return None


def _parse_dt(value):
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _error(exc):
    return json_response(error=str(exc))


class InspectionTemplateView(View):
    """巡检模板列表 / 聚合创建（模板 → 设备名称 → 检查内容）。"""

    @auth('equipment_lifecycle.inspection_template.view')
    def get(self, request):
        keyword = (request.GET.get('keyword') or '').strip()
        qs = inspection_services.get_templates_for_user(request.user)
        if keyword:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = qs.count()
        templates = qs[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [t.to_view(with_counts=True) for t in templates],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.inspection_template.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            template = inspection_services.create_template(request.user, body)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'create', AUDIT_TARGET_INSPECTION_TEMPLATE,
                           template.id, template.name, after_value=template.to_view())
        return json_response(inspection_services.get_template_tree(template))


class InspectionTemplateDetailView(View):
    """巡检模板详情 / 聚合编辑 / 删除。"""

    @auth('equipment_lifecycle.inspection_template.view')
    def get(self, request, pk):
        template = inspection_services.get_templates_for_user(request.user).filter(pk=pk).first()
        if not template:
            return json_response(error='巡检模板不存在')
        return json_response(inspection_services.get_template_tree(template))

    @auth('equipment_lifecycle.inspection_template.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            template = inspection_services.update_template(request.user, pk, body)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'update', AUDIT_TARGET_INSPECTION_TEMPLATE,
                           template.id, template.name, after_value=template.to_view())
        return json_response(inspection_services.get_template_tree(template))

    @auth('equipment_lifecycle.inspection_template.del')
    def delete(self, request, pk):
        try:
            template = inspection_services.get_templates_for_user(request.user).filter(
                pk=pk).first()
            if not template:
                return json_response(error='巡检模板不存在')
            used = InspectionDutySheet.objects.filter(template=template).exists()
            if used:
                return json_response(error='该模板已被巡检单引用，请停用而非删除')
            template.delete()
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'delete', AUDIT_TARGET_INSPECTION_TEMPLATE,
                           pk, template.name)
        return json_response()


class InspectionTemplateActiveView(View):
    """巡检模板启用/停用。"""

    @auth('equipment_lifecycle.inspection_template.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            template = inspection_services.toggle_template_active(
                request.user, pk, bool(body.get('is_active')))
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'other', AUDIT_TARGET_INSPECTION_TEMPLATE,
                           template.id, template.name,
                           after_value={'is_active': template.is_active})
        return json_response(template.to_view())


class InspectionTemplateAvailableView(View):
    """可用巡检模板树（巡检工作台渲染设备/检查内容，仅启用模板与启用条目）。"""

    @auth('equipment_lifecycle.inspection.view')
    def get(self, request):
        templates = inspection_services.get_templates_for_user(
            request.user, only_active=True).order_by('name')
        return json_response({
            'data': [inspection_services.get_template_tree(t, only_active=True)
                     for t in templates],
        })


class InspectionSheetView(View):
    """值班巡检单列表 / 创建（值班日 + 模板 唯一，client_token 幂等）。"""

    @auth('equipment_lifecycle.inspection.view')
    def get(self, request):
        from libs.pagination import paginate
        form, error = JsonParser(
            Argument('duty_from', type=str, required=False),
            Argument('duty_to', type=str, required=False),
            Argument('duty_date', type=str, required=False),
            Argument('template', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('keyword', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        qs = apply_tenant_filter(
            InspectionDutySheet.objects.select_related('template'), request.user)
        qs, error = _filter_sheet_queryset(qs, form)
        if error:
            return json_response(error=error)
        page, page_size = paginate(request)
        total = qs.count()
        sheets = qs[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [s.to_view() for s in sheets],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.inspection.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            sheet = inspection_services.create_sheet(request.user, body)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'create', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no, after_value={
                               'sheet_no': sheet.sheet_no,
                               'duty_date': str(sheet.duty_date),
                               'template': sheet.template.name,
                           })
        return json_response(sheet.to_detail_view())


def _sheet_keyword_q(keyword):
    from django.db.models import Q
    return Q(sheet_no__icontains=keyword) | Q(template__name__icontains=keyword)


def _filter_sheet_queryset(qs, form):
    """按查询参数过滤巡检单列表，返回 (queryset, error)。"""
    if form.duty_date:
        qs = qs.filter(duty_date=inspection_services.parse_duty_date(form.duty_date))
    duty_from = _parse_dt(form.duty_from + ' 00:00') if form.duty_from else None
    duty_to = _parse_dt(form.duty_to + ' 00:00') if form.duty_to else None
    if form.duty_from and not duty_from:
        return None, '值班日起始格式不正确'
    if form.duty_to and not duty_to:
        return None, '值班日截止格式不正确'
    if duty_from:
        qs = qs.filter(duty_date__gte=duty_from.date())
    if duty_to:
        qs = qs.filter(duty_date__lte=duty_to.date())
    if form.template:
        qs = qs.filter(template_id=form.template)
    if form.status:
        if form.status not in ('draft', 'submitted', 'returned', 'void'):
            return None, '状态筛选值不合法'
        qs = qs.filter(status=form.status)
    if form.keyword:
        qs = qs.filter(_sheet_keyword_q(form.keyword))
    return qs, None


class InspectionSheetDetailView(View):
    """巡检单详情 / 草稿编辑（值班人员 + 单轮记录 upsert，version 乐观锁；
    一次请求只允许提交一个轮次，已记录轮次由后端拒绝再次修改）。"""

    @auth('equipment_lifecycle.inspection.view')
    def get(self, request, pk):
        try:
            sheet = inspection_services.get_sheet_for_user(request.user, pk)
        except InspectionValidationError as exc:
            return _error(exc)
        data = sheet.to_detail_view()
        data['records'] = inspection_services.append_record_disposition(
            request.user.tenant_id, data['records'])
        return json_response(data)

    @auth('equipment_lifecycle.inspection.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            sheet = inspection_services.update_sheet(request.user, pk, body)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'update', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no, after_value={
                               'version': sheet.version,
                               'record_count': sheet.records.count(),
                           })
        data = sheet.to_detail_view()
        data['records'] = inspection_services.append_record_disposition(
            request.user.tenant_id, data['records'])
        return json_response(data)


class InspectionSheetSubmitView(View):
    """提交巡检单（记录/提交分离，提交后不可再修改）。"""

    @auth('equipment_lifecycle.inspection.submit')
    def post(self, request, pk):
        try:
            sheet = inspection_services.submit_sheet(request.user, pk)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'other', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no,
                           after_value={'status': sheet.status})
        return json_response(sheet.to_detail_view())


class InspectionSheetVoidView(View):
    """受控作废巡检单（留档可查，释放当日唯一占用）。"""

    @auth('equipment_lifecycle.inspection.del')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        try:
            sheet = inspection_services.void_sheet(request.user, pk, body.get('void_reason'))
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'other', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no,
                           after_value={'status': sheet.status,
                                        'void_reason': sheet.void_reason})
        return json_response(sheet.to_detail_view())


class InspectionSheetReturnView(View):
    """超级管理员退回整改：已提交 → 已退回（原因必填）。

    权限双层校验（后端独立，不依赖前端隐藏按钮）：
    - @auth 要求巡检编辑权限（超管恒通过）；
    - 视图内显式校验 request.user.is_supper，普通管理员/普通用户
      即使持有权限码直接调用接口也被拒绝。
    """

    @auth('equipment_lifecycle.inspection.edit')
    def post(self, request, pk):
        if not request.user.is_supper:
            return json_response(error='仅超级管理员可以退回整改巡检单')
        body = _read_json_body(request) or {}
        try:
            sheet = inspection_services.return_sheet(
                request.user, pk, body.get('return_reason'))
        except InspectionValidationError as exc:
            return _error(exc)
        # 状态机保证退回前必为 submitted，before/after 一并留痕
        record_audit_event(request, 'update', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no,
                           before_value={'status': 'submitted'},
                           after_value={'action_kind': 'return_for_rectification',
                                        'status': sheet.status,
                                        'return_reason': sheet.return_reason})
        return json_response(sheet.to_detail_view())


# ----------------------------------------------------------------------
# 巡检单导出（独立 export 权限，后端独立校验；导出为只读行为）
# ----------------------------------------------------------------------

class InspectionSheetExportView(View):
    """巡检单列表 Excel 导出：复用列表筛选条件，导出筛选范围内全部数据。"""

    @auth('equipment_lifecycle.inspection.export')
    def get(self, request):
        form, error = JsonParser(
            Argument('duty_from', type=str, required=False),
            Argument('duty_to', type=str, required=False),
            Argument('duty_date', type=str, required=False),
            Argument('template', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('keyword', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        qs = apply_tenant_filter(
            InspectionDutySheet.objects.select_related('template')
                .prefetch_related('persons', 'records'), request.user)
        qs, error = _filter_sheet_queryset(qs, form)
        if error:
            return json_response(error=error)
        count, error_resp = check_export_limit(qs)
        if error_resp:
            return error_resp
        if count == 0:
            return build_export_error_response('当前筛选条件下没有可导出的数据')
        record_audit_event(request, 'export', AUDIT_TARGET_INSPECTION_SHEET, '', '',
                           after_value={
                               'export_type': 'list_xlsx',
                               'count': count,
                               'filters': {
                                   'duty_from': form.duty_from or '',
                                   'duty_to': form.duty_to or '',
                                   'duty_date': form.duty_date or '',
                                   'template': form.template or '',
                                   'status': form.status or '',
                                   'keyword': form.keyword or '',
                               },
                           })
        return build_excel_response(
            inspection_export.export_filename('巡检单记录', 'xlsx'),
            inspection_export.LIST_SHEET_NAME,
            inspection_export.LIST_COLUMNS,
            inspection_export.build_list_rows(qs))


class InspectionSheetDetailExportBaseView(View):
    """巡检单详情导出基类：Excel（四轮矩阵双工作表）与 PDF（A4 纵向）。

    导出内容以巡检单已保存数据为准（快照 + recorded_rounds 最终状态），
    不包含明细实际填写时间，也没有迟填/逾期标记。
    """

    export_format = 'xlsx'

    @auth('equipment_lifecycle.inspection.export')
    def get(self, request, pk):
        try:
            sheet = inspection_services.get_sheet_for_user(request.user, pk)
        except InspectionValidationError as exc:
            return _error(exc)
        detail = sheet.to_detail_view()
        detail['records'] = inspection_services.append_record_disposition(
            request.user.tenant_id, detail['records'])
        response = inspection_export.build_detail_response(detail, self.export_format)
        record_audit_event(request, 'export', AUDIT_TARGET_INSPECTION_SHEET, sheet.id,
                           sheet.sheet_no,
                           after_value={'export_type': self.export_format,
                                        'duty_date': str(sheet.duty_date)})
        return response


class InspectionSheetDetailExportXlsxView(InspectionSheetDetailExportBaseView):
    """巡检单详情 Excel 导出（巡查单信息 + 四轮巡检明细）。"""

    export_format = 'xlsx'


class InspectionSheetDetailExportPdfView(InspectionSheetDetailExportBaseView):
    """巡检单详情 PDF 导出（巡检单专用 ReportLab 版式）。"""

    export_format = 'pdf'


class InspectionSheetBatchExportBaseView(View):
    """巡检单批量详情导出基类：按列表筛选条件导出全部匹配巡检单。

    - Excel：一个工作簿（巡检单汇总 + 每单"信息_单号/明细_单号"两个工作表）；
    - PDF：一个 ReportLab 文档流连续生成的合并 PDF（每单从新页开始）；
    - 后端重新执行筛选与租户隔离，不受分页参数影响，不信任前端详情数据；
    - Excel/PDF 数量上限分别校验（inspection_export.batch_export_limit）；
    - 无匹配数据返回统一业务错误；导出为只读行为，不修改任何业务数据。
    """

    export_format = 'xlsx'

    @auth('equipment_lifecycle.inspection.export')
    def get(self, request):
        form, error = JsonParser(
            Argument('duty_from', type=str, required=False),
            Argument('duty_to', type=str, required=False),
            Argument('duty_date', type=str, required=False),
            Argument('template', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('keyword', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        qs = apply_tenant_filter(
            InspectionDutySheet.objects.select_related(
                'template', 'submitted_by', 'created_by')
                .prefetch_related('persons', 'records'), request.user)
        qs, error = _filter_sheet_queryset(qs, form)
        if error:
            return json_response(error=error)
        count = qs.count()
        limit_error = inspection_export.check_batch_export_limit(
            count, self.export_format)
        if limit_error:
            return build_export_error_response(limit_error)
        if count == 0:
            return build_export_error_response('当前筛选条件下没有可导出的数据')
        sheets = list(qs)
        details = [sheet.to_detail_view() for sheet in sheets]
        inspection_services.append_batch_record_disposition(
            request.user.tenant_id, details)
        response = inspection_export.build_batch_detail_response(
            sheets, details, self.export_format)
        record_audit_event(request, 'export', AUDIT_TARGET_INSPECTION_SHEET, '', '',
                           after_value={
                               'export_type': f'batch_detail_{self.export_format}',
                               'count': len(sheets),
                               'filters': {
                                   'duty_from': form.duty_from or '',
                                   'duty_to': form.duty_to or '',
                                   'duty_date': form.duty_date or '',
                                   'template': form.template or '',
                                   'status': form.status or '',
                                   'keyword': form.keyword or '',
                               },
                           })
        return response


class InspectionSheetBatchExportXlsxView(InspectionSheetBatchExportBaseView):
    """巡检单批量详情 Excel 导出（汇总 + 每单双工作表，上限默认 500 条）。"""

    export_format = 'xlsx'


class InspectionSheetBatchExportPdfView(InspectionSheetBatchExportBaseView):
    """巡检单批量详情 PDF 导出（合并文档流，上限默认 100 条）。"""

    export_format = 'pdf'
