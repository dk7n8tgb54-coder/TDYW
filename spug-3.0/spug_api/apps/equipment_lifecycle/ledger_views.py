# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——周月维护/季维护台账视图（步骤 3.2）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.ledger.view|add|edit|submit|review|del|export
- Excel 模板管理使用 equipment_lifecycle.ledger_template.view|add|edit|del
  （见 excel_template_views），旧可视化模板台账路线已删除（2026-10）

约定：
- 台账系统关联通过系统 ID，后端重新查询系统，不信任前端传来的名称；
- 正式新增台账统一走 Excel/WPS 模板路线（/excel-ledgers/），
  POST /ledgers/ 仅保留手工补录（created_from=manual）能力；
- 台账创建/提交/复核/退回/作废均考虑重复请求（状态机 + client_token）；
- HTTP 200 + error 为业务失败；写操作记录业务审计并使用状态动作接口；
- 附件走 evidence 体系，访问前校验所属台账/明细与租户归属。
"""
import csv
import io

from django.db.models import Q
from django.http import HttpResponse
from django.views.generic import View

from libs import json_response, auth
from libs.pagination import paginate
from libs.tenant_utils import apply_tenant_filter

from apps.logs.audit import record_audit_event
from apps.evidence.attachment_service import (
    AttachmentService, DefaultAttachmentConfig,
    ATTACHMENT_ACCESS_DENIED_ERROR, ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment

from apps.equipment_lifecycle import ledger_services
from apps.equipment_lifecycle.ledger_services import (
    LedgerValidationError, legacy_inspection_error,
    append_item_disposition,
)
from apps.equipment_lifecycle.models import (
    ITEM_RESULT_ABNORMAL,
    ITEM_RESULT_TEXT_MAP_FULL,
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_MANUAL,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_TEXT,
    LifecycleSystem,
    OperationLedger,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.views import (
    EL_ATTACHMENT_MODULE,
    _read_json_body,
)

AUDIT_TARGET_LEDGER = 'el_operation_ledger'

# 附件归属标识：台账表头 / 台账明细
LEDGER_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger'
LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger_item'

# 统一列表详情路由（与前端 routes.js 的正式台账路径一致）
LEDGER_TYPE_DETAIL_PATH = {
    'week_month': '/el/week-month-ledgers',
    'seasonal': '/el/seasonal-ledgers',
}

# 统一列表来源类型（由 created_from 派生；旧可视化模板来源已随路线删除）
LEDGER_FROM_SOURCE_TYPE = {
    LEDGER_FROM_MANUAL: 'manual',
    LEDGER_FROM_EXCEL: 'excel',
}


# ======================================================================
# 台账
# ======================================================================

def _get_ledger_for_user(pk, user):
    return apply_tenant_filter(OperationLedger.objects.all(), user).filter(pk=pk).first()


def _ledger_detail(ledger, user=None):
    if ledger.created_from == LEDGER_FROM_EXCEL:
        # Excel 路线台账没有普通 OperationLedgerItem 明细，按 created_from
        # 分支返回 Excel 详情（版本快照 + 绑定 + 布局 + 填写值 + 编辑状态）
        from apps.equipment_lifecycle import excel_ledger_services

        try:
            return excel_ledger_services.ledger_detail(ledger)
        except excel_ledger_services.ExcelLedgerError:
            # 缺少填写记录的异常数据降级为基础视图，不让统一详情整体失败
            pass
    view = ledger.to_view(with_counts=True)
    items = [it.to_view() for it in ledger.items.all()]
    if user is not None:
        # 异常明细处置状态：由来源故障关系动态计算，事实依据不落库
        append_item_disposition(ledger.tenant_id, items)
    view['items'] = items
    view['corrections'] = [c.to_view() for c in ledger.corrections.all()]
    return view


def _ledger_source_fields(ledger):
    """统一列表来源字段：source_type + Excel 路线模板/版本 + 详情路由。

    Excel 路线台账的来源版本经 select_related('excel_record__version')
    读取；记录缺失（异常数据）时来源信息降级为空，不影响列表返回。
    """
    source_type = LEDGER_FROM_SOURCE_TYPE.get(ledger.created_from, ledger.created_from)
    fields = {
        'source_type': source_type,
        'source_template_name': '',
        'source_version_no': None,
        'detail_route': '',
    }
    if source_type == 'excel':
        record = getattr(ledger, 'excel_record', None)
        version = record.version if record is not None else None
        fields['source_template_name'] = version.template_name_snapshot if version else ''
        fields['source_version_no'] = version.version_no if version else None
    path = LEDGER_TYPE_DETAIL_PATH.get(ledger.ledger_type)
    if path:
        fields['detail_route'] = '%s?detail=%d&source=%s' % (
            path, ledger.id, source_type)
    return fields


class LedgerView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        query = apply_tenant_filter(OperationLedger.objects.all(), request.user)
        # 统一维护台账列表（2026-10）：Excel 模板 / 手工补录一并返回，
        # 前端按 source_type 区分来源与详情路由（旧可视化模板路线已删除）
        ledger_type = request.GET.get('ledger_type')
        if ledger_type:
            query = query.filter(ledger_type=ledger_type)
        status = request.GET.get('status')
        if status:
            query = query.filter(status=status)
        system_id = request.GET.get('system')
        if system_id and str(system_id).isdigit():
            # 表头级系统（周期批量台账）与明细系统（手工/历史台账）均命中
            query = query.filter(
                Q(items__system_id=system_id) | Q(system_id=system_id)).distinct()
        keyword = request.GET.get('keyword')
        if keyword:
            query = query.filter(ledger_no__icontains=keyword)
        executed_from = request.GET.get('executed_from')
        if executed_from:
            query = query.filter(executed_date__gte=executed_from)
        executed_to = request.GET.get('executed_to')
        if executed_to:
            query = query.filter(executed_date__lte=executed_to)
        query = query.select_related('system', 'excel_record__version')
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size] if total else []
        data = []
        for record in records:
            view = record.to_view()
            view.update(_ledger_source_fields(record))
            data.append(view)
        return json_response({
            'data': data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.ledger.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = ledger_services.create_ledger(request.user, body)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'ledger_type': ledger.ledger_type,
                                        'created_from': ledger.created_from,
                                        'items_count': ledger.items.count()})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerBatchCreateView(View):
    """周期台账一键新增：GET 返回本租户系统范围，POST 按类型+周期批量创建草稿台账。

    - 范围依据本租户在用系统（后端独立查询，不信任前端传入名单）；
    - 幂等：同类型+同周期+同系统已存在有效台账时跳过（作废不占名额）；
    - 成功响应携带 created/existed，由前端如实展示"实际新增/已存在"。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        systems = apply_tenant_filter(LifecycleSystem.objects.all(), request.user).order_by(
            '-is_active', 'system_code', 'id')
        return json_response({'data': [{
            'id': s.id,
            'system_code': s.system_code,
            'name': s.name,
            'install_location': s.install_location,
            'is_active': s.is_active,
        } for s in systems]})

    @auth('equipment_lifecycle.ledger.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        result, error = ledger_services.batch_create_period_ledgers(request.user, body)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_LEDGER, None,
                           '周期批量新增%s台账' % result['period_text'],
                           after_value={'ledger_type': result['ledger_type'],
                                        'maintenance_period': result['maintenance_period'],
                                        'created': result['created'],
                                        'existed': result['existed'],
                                        'existed_systems': result['existed_systems']})
        return json_response(result)


class LedgerPeriodGroupsView(View):
    """按 维护类型+周期 分组的台账列表：组内含各系统台账、来源与填写状态。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        try:
            data = ledger_services.list_period_groups(
                request.user, request.GET.get('ledger_type'),
                status=request.GET.get('status') or '',
                system_id=request.GET.get('system'),
                row_serializer=_ledger_source_fields)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        return json_response({'data': data})


class LedgerDetailView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        return json_response(_ledger_detail(ledger, request.user))

    @auth('equipment_lifecycle.ledger.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, changed, error = ledger_services.update_ledger(request.user, pk, body)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           before_value={'version': ledger.version - 1},
                           after_value={'version': ledger.version, 'changes': changed})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerSubmitView(View):
    @auth('equipment_lifecycle.ledger.submit')
    def post(self, request, pk):
        ledger, error = ledger_services.submit_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'submit', 'status': ledger.status})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerReturnView(View):
    @auth('equipment_lifecycle.ledger.review')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        ledger, error = ledger_services.return_ledger(request.user, pk, body.get('reason'))
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'return', 'status': ledger.status,
                                        'reason': ledger.return_reason})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerReviewView(View):
    @auth('equipment_lifecycle.ledger.review')
    def post(self, request, pk):
        ledger, error = ledger_services.review_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'approve', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'review', 'status': ledger.status,
                                        'reviewer_name': ledger.reviewer_name})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerVoidView(View):
    @auth('equipment_lifecycle.ledger.del')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        ledger, error = ledger_services.void_ledger(request.user, pk, body.get('reason'))
        if error:
            return json_response(error=error)
        # 受控作废（不物理删除），审计用 delete 大类 + action_kind 标注
        record_audit_event(request, 'delete', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'void_ledger', 'status': ledger.status,
                                        'reason': ledger.void_reason})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerCorrectView(View):
    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        correction, changes, error = ledger_services.correct_ledger(request.user, pk, body)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, correction.ledger_id,
                           correction.ledger.ledger_no,
                           after_value={'action_kind': 'correct', 'reason': correction.reason,
                                        'changes': changes})
        return json_response(correction.to_view())


class LedgerConfirmNormalView(View):
    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = ledger_services.confirm_normal(request.user, pk, body.get('item_ids'))
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'confirm_normal',
                                        'item_ids': body.get('item_ids')})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerAbnormalItemsView(View):
    """异常明细查询（排除已作废台账；支持类型/系统/日期范围过滤）。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        query = OperationLedgerItem.objects.filter(
            tenant_id=request.user.tenant_id, result=ITEM_RESULT_ABNORMAL,
            ledger__isnull=False).exclude(ledger__status=LEDGER_STATUS_VOID)
        ledger_type = request.GET.get('ledger_type')
        if ledger_type:
            query = query.filter(ledger__ledger_type=ledger_type)
        system_id = request.GET.get('system')
        if system_id and str(system_id).isdigit():
            query = query.filter(system_id=system_id)
        date_from = request.GET.get('date_from')
        if date_from:
            query = query.filter(ledger__executed_date__gte=date_from)
        date_to = request.GET.get('date_to')
        if date_to:
            query = query.filter(ledger__executed_date__lte=date_to)
        query = query.select_related('ledger', 'system').order_by('-ledger__executed_date', '-id')
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size] if total else []
        data = []
        for item in records:
            view = item.to_view()
            view['ledger_no'] = item.ledger.ledger_no
            view['ledger_type'] = item.ledger.ledger_type
            view['ledger_executed_date'] = item.ledger.executed_date
            view['ledger_status'] = item.ledger.status
            data.append(view)
        # 异常明细处置状态：由来源故障关系动态计算
        append_item_disposition(request.user.tenant_id, data)
        return json_response({'data': data, 'total': total, 'page': page, 'page_size': page_size})


def _apply_ledger_item_filters(query, params):
    """导出/明细查询共用过滤（GET 参数 → ORM 条件，日期用范围查询）。"""
    ledger_type = params.get('ledger_type')
    if ledger_type:
        query = query.filter(ledger__ledger_type=ledger_type)
    status = params.get('status')
    if status:
        query = query.filter(ledger__status=status)
    system_id = params.get('system')
    if system_id and str(system_id).isdigit():
        query = query.filter(system_id=system_id)
    date_from = params.get('executed_from')
    if date_from:
        query = query.filter(ledger__executed_date__gte=date_from)
    date_to = params.get('executed_to')
    if date_to:
        query = query.filter(ledger__executed_date__lte=date_to)
    keyword = params.get('keyword')
    if keyword:
        query = query.filter(ledger__ledger_no__icontains=keyword)
    return query


def _format_ledger_item_value(item):
    """明细填写值的 CSV 展示文本（按录入类型分列取值）。"""
    if item.input_type == 'number':
        return '' if item.value_number is None else item.value_number
    if item.input_type == 'boolean':
        return '' if item.value_bool is None else ('是' if item.value_bool else '否')
    value = item.get_value_list() if item.input_type == 'multi_choice' and item.value_text \
        else item.value_text
    if isinstance(value, list):
        return '、'.join(map(str, value))
    return value


class LedgerExportView(View):
    """台账明细级 CSV 导出：重新执行查询与租户过滤，不信任前端明细 ID。"""

    @auth('equipment_lifecycle.ledger.export')
    def get(self, request):
        query = _apply_ledger_item_filters(
            OperationLedgerItem.objects.filter(
                tenant_id=request.user.tenant_id, ledger__isnull=False),
            request.GET)
        rows = query.select_related('ledger', 'system').order_by('-ledger__executed_date', '-id')
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            '台账编号', '台账类型', '实际执行日期', '状态', '系统编号', '系统名称',
            '项目名称', '录入类型', '填写值', '单位',
            '结果', '异常说明', '不适用原因', '现场处理内容', '明细执行人',
            '明细执行时间', '录入渠道', '录入时间'])
        count = 0
        for item in rows:
            ledger = item.ledger
            value = _format_ledger_item_value(item)
            writer.writerow([
                ledger.ledger_no, LEDGER_TYPE_TEXT.get(ledger.ledger_type, ledger.ledger_type),
                ledger.executed_date,
                ledger.status, item.system_code_snapshot, item.system_name_snapshot,
                item.item_name_snapshot,
                item.input_type, value, item.unit_snapshot,
                ITEM_RESULT_TEXT_MAP_FULL.get(item.result, item.result),
                item.abnormal_desc, item.na_reason, item.onsite_action, item.executor_name,
                item.executed_at or '', ledger.entry_channel,
                ledger.created_at])
            count += 1
        response = HttpResponse(buffer.getvalue().encode('utf-8-sig'), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=operation_ledgers.csv'
        record_audit_event(request, 'export', AUDIT_TARGET_LEDGER, None, '运维台账明细',
                           after_value={'rows': count, 'ledger_type': ledger_type or 'all'})
        return response


# ======================================================================
# 台账附件（表头 / 明细）
# ======================================================================

def _get_ledger_item_for_user(ledger, item_pk):
    return ledger.items.filter(pk=item_pk).first()


def _reject_inspection_ledger(ledger):
    """已删除的旧巡检类型统一拦截：附件上传/删除等写操作在此拒绝（查看/下载不受限）。"""
    return legacy_inspection_error(ledger)


def _attachment_for_user(user, attachment_id, object_type, object_id):
    """附件归属校验：存在、未删除、module/object_type/object_id 与租户全部匹配。"""
    return apply_tenant_filter(
        EvidenceAttachment.objects.filter(is_deleted=False), user
    ).filter(pk=attachment_id, module=EL_ATTACHMENT_MODULE, object_type=object_type,
             object_id=str(object_id)).first()


class LedgerAttachmentView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        return json_response({'data': AttachmentService.list(
            request.user, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE, ledger.id)})

    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        error = _reject_inspection_ledger(ledger)
        if error:
            return json_response(error=error)
        if ledger.status not in OperationLedger.EDITABLE_STATUSES:
            return json_response(error='当前状态不允许上传台账附件')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='缺少上传文件')
        att, error = AttachmentService.upload(
            file, request.user, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE,
            ledger.id, config=DefaultAttachmentConfig, owner_tenant_id=ledger.tenant_id)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'upload_ledger_attachment',
                                        'file_name': att.file_name})
        return json_response(att.to_view())


class LedgerAttachmentDetailView(View):
    @auth('equipment_lifecycle.ledger.edit')
    def delete(self, request, pk, aid):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        error = _reject_inspection_ledger(ledger)
        if error:
            return json_response(error=error)
        if ledger.status not in OperationLedger.EDITABLE_STATUSES:
            return json_response(error='当前状态不允许删除台账附件')
        att = _attachment_for_user(request.user, aid, LEDGER_ATTACHMENT_OBJECT_TYPE, ledger.id)
        if not att:
            return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
        error = AttachmentService.soft_delete(
            request.user, aid, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE,
            reason='运维台账附件删除')
        if error:
            return json_response(error=error)
        record_audit_event(request, 'delete', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           before_value={'action_kind': 'delete_ledger_attachment',
                                         'file_name': att.file_name})
        return json_response({})


class LedgerAttachmentDownloadView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk, aid):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        att = _attachment_for_user(request.user, aid, LEDGER_ATTACHMENT_OBJECT_TYPE, ledger.id)
        if not att:
            return json_response(error=ATTACHMENT_ACCESS_DENIED_ERROR)
        response, error = AttachmentService.download_response(
            request.user, aid, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response


class LedgerItemAttachmentView(View):
    def _check(self, request, pk, item_pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return None, None, '台账不存在'
        item = _get_ledger_item_for_user(ledger, item_pk)
        if not item:
            return None, None, '台账明细不存在'
        return ledger, item, None

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk, item_pk):
        ledger, item, error = self._check(request, pk, item_pk)
        if error:
            return json_response(error=error)
        return json_response({'data': AttachmentService.list(
            request.user, EL_ATTACHMENT_MODULE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE, item.id)})

    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk, item_pk):
        ledger, item, error = self._check(request, pk, item_pk)
        if error:
            return json_response(error=error)
        error = _reject_inspection_ledger(ledger)
        if error:
            return json_response(error=error)
        if ledger.status not in OperationLedger.EDITABLE_STATUSES:
            return json_response(error='当前状态不允许上传明细附件')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='缺少上传文件')
        att, error = AttachmentService.upload(
            file, request.user, EL_ATTACHMENT_MODULE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE,
            item.id, config=DefaultAttachmentConfig, owner_tenant_id=ledger.tenant_id)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'upload_ledger_item_attachment',
                                        'item': item.item_name_snapshot, 'file_name': att.file_name})
        return json_response(att.to_view())


class LedgerItemAttachmentDetailView(View):
    def _check(self, request, pk, item_pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return None, None, '台账不存在'
        item = _get_ledger_item_for_user(ledger, item_pk)
        if not item:
            return None, None, '台账明细不存在'
        return ledger, item, None

    @auth('equipment_lifecycle.ledger.edit')
    def delete(self, request, pk, item_pk, aid):
        ledger, item, error = self._check(request, pk, item_pk)
        if error:
            return json_response(error=error)
        error = _reject_inspection_ledger(ledger)
        if error:
            return json_response(error=error)
        if ledger.status not in OperationLedger.EDITABLE_STATUSES:
            return json_response(error='当前状态不允许删除明细附件')
        att = _attachment_for_user(request.user, aid, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE, item.id)
        if not att:
            return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
        error = AttachmentService.soft_delete(
            request.user, aid, EL_ATTACHMENT_MODULE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE,
            reason='运维台账明细附件删除')
        if error:
            return json_response(error=error)
        record_audit_event(request, 'delete', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           before_value={'action_kind': 'delete_ledger_item_attachment',
                                         'item': item.item_name_snapshot, 'file_name': att.file_name})
        return json_response({})


class LedgerItemAttachmentDownloadView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk, item_pk, aid):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        item = _get_ledger_item_for_user(ledger, item_pk)
        if not item:
            return json_response(error='台账明细不存在')
        att = _attachment_for_user(request.user, aid, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE, item.id)
        if not att:
            return json_response(error=ATTACHMENT_ACCESS_DENIED_ERROR)
        response, error = AttachmentService.download_response(
            request.user, aid, EL_ATTACHMENT_MODULE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response
