# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 路线维护台账服务（创建/填写/提交/历史/导出，2026-09-28）。

- 台账行复用正式 OperationLedger（ledger_no/状态机/执行日期/执行人），
  created_from='excel_template'；填写值与所用模板版本保存在
  OperationLedgerExcelRecord（与台账一对一）；
- 版本不可变：台账创建即固定引用某已发布版本（PROTECT），历史详情
  据版本快照回放当时的字段、绑定与版式，导出读取该版本原始 .xlsx 副本；
- 周期边界：台账类型取自版本所属模板（week_month/seasonal），请求显式
  携带 ledger_type 时必须与模板一致（另一种类型在此校验拦截）；
- 提交：状态机校验（草稿/已退回 → 已提交）+ 必填字段校验（类型校验
  在保存填写值时已完成）；
- 导出前必填校验与原型一致：必填未填拦截导出（设计行为，不伪造输出）；
- PDF 参数与预检（2026-09-30）：导出 PDF 默认使用版本快照的模板级参数，
  可显式覆盖（仅当次）；export_check 依据布局与参数估算溢出/空白页/
  分页越界等提示（estimate_pdf_warnings），不落库无副作用。

业务错误统一抛 ExcelLedgerError，View 层转 json_response(error=...)。
"""
import json
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from libs.pagination import paginate
from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle import excel_pdf_service, excel_template_manage, excel_template_storage
from apps.equipment_lifecycle.excel_models import OperationLedgerExcelRecord
from apps.equipment_lifecycle.excel_pdf_params import estimate_pdf_warnings
from apps.equipment_lifecycle.excel_template_services import (
    ExcelLayoutError,
    export_filled_excel,
    export_pdf,
    validate_values,
)
from apps.equipment_lifecycle.ledger_services import (
    LEDGER_STATUS_SUBMITTED,
    generate_ledger_no,
)
from apps.equipment_lifecycle.models import (
    ENTRY_CHANNEL_WEB,
    LEDGER_FROM_EXCEL,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_VOID,
    OperationLedger,
)

EDITABLE_STATUSES = {LEDGER_STATUS_DRAFT, LEDGER_STATUS_RETURNED}


class ExcelLedgerError(Exception):
    """Excel 台账业务校验错误（View 层转业务错误响应）。"""


def _fail(message):
    raise ExcelLedgerError(message)


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def get_ledger(pk, user, for_update=False):
    """按租户取 Excel 路线台账（须存在填写记录）；非 Excel 路线按不存在处理。"""
    query = apply_tenant_filter(
        OperationLedger.objects.filter(created_from=LEDGER_FROM_EXCEL), user)
    if for_update:
        query = query.select_for_update()
    return query.select_related('excel_record__version__template') \
        .filter(pk=pk).first()


def create_ledger(user, body):
    """按已发布 Excel 模板版本创建台账（表头 + 填写记录一次写入）。

    client_token 命中同租户已有台账时直接返回该台账（创建防重复）。
    返回 (ledger, None) 或 (None, error_message)。
    """
    version = excel_template_manage.get_version(body.get('version_id'), user)
    if version is None:
        return None, '模板版本不存在或未发布'
    template = version.template
    if template is None or not template.is_active:
        return None, '模板已停用，不能用于新台账'
    requested_type = body.get('ledger_type')
    if requested_type and requested_type != template.ledger_type:
        return None, '模板「%s」为%s模板，与所选台账类型不一致' % (
            template.name, _type_label(template.ledger_type))
    try:
        executed_date = _parse_executed_date(body.get('executed_date'))
    except ExcelLedgerError as e:
        return None, str(e)
    client_token = str(body.get('client_token') or '')[:64]
    if client_token:
        exists = apply_tenant_filter(OperationLedger.objects.all(), user) \
            .filter(client_token=client_token).first()
        if exists:
            return exists, None
    executor_names = str(body.get('executor_names') or '').strip()
    try:
        ledger = _create_ledger_row(
            user, template, version, executed_date, executor_names, client_token)
    except ExcelLedgerError as e:
        return None, str(e)
    return ledger, None


def _type_label(ledger_type):
    return {'week_month': '周月维护', 'seasonal': '季维护'}.get(ledger_type, ledger_type)


def _parse_executed_date(raw):
    if not raw:
        _fail('请填写实际执行日期')
    try:
        return datetime.strptime(str(raw)[:10], '%Y-%m-%d').date()
    except ValueError:
        _fail('实际执行日期格式不正确')


@transaction.atomic
def _create_ledger_row(user, template, version, executed_date, executor_names, client_token):
    bindings = version.get_bindings()
    ledger = OperationLedger(
        tenant_id=user.tenant_id,
        ledger_no=generate_ledger_no(user.tenant_id, template.ledger_type, executed_date),
        ledger_type=template.ledger_type,
        executed_date=executed_date,
        executor_names=executor_names,
        status=LEDGER_STATUS_DRAFT,
        entry_channel=ENTRY_CHANNEL_WEB,
        created_from=LEDGER_FROM_EXCEL,
        client_token=client_token,
        created_by=user,
    )
    ledger.save()
    prefill = excel_template_manage.default_prefill(bindings)
    OperationLedgerExcelRecord.objects.create(
        tenant_id=user.tenant_id,
        ledger=ledger,
        version=version,
        values=_canonical(prefill),
    )
    return ledger


def _require_record(ledger):
    record = getattr(ledger, 'excel_record', None)
    if record is None:
        _fail('台账缺少 Excel 填写记录')
    return record


def update_values(user, ledger, values):
    """保存填写值（整体替换；可编辑状态限定草稿/已退回）。"""
    record = _require_record(ledger)
    if ledger.status not in EDITABLE_STATUSES:
        _fail('当前状态不允许修改填写值')
    bindings = record.version.get_bindings()
    try:
        normalized = validate_values(bindings, values)
    except ExcelLayoutError as e:
        _fail(str(e))
    record.values = _canonical(normalized)
    record.updated_at = timezone.now()
    record.save(update_fields=['values', 'updated_at'])
    return record


def update_header(user, ledger, header):
    """录入/修正表头执行信息（实际执行日期/执行人；可编辑状态限定草稿/已退回）。

    - 周期生成的应填台账 executed_date 为空，由填写人在执行后录入；提前
      生成不把创建当天伪装成实际维护日期（计划填写期次见 maintenance_period）；
    - 字段缺省表示不修改；executed_date 传空串显式清空（回退未录入）；
    - 台账编号创建后不变，不随执行日期重算。
    """
    if ledger.status not in EDITABLE_STATUSES:
        _fail('当前状态不允许修改表头信息')
    if not isinstance(header, dict):
        _fail('表头参数格式不正确')
    updates = {}
    if 'executed_date' in header:
        raw = header.get('executed_date')
        if raw in (None, ''):
            updates['executed_date'] = None
        else:
            try:
                updates['executed_date'] = datetime.strptime(
                    str(raw)[:10], '%Y-%m-%d').date()
            except ValueError:
                _fail('实际执行日期格式不正确')
    if 'executor_names' in header:
        updates['executor_names'] = str(header.get('executor_names') or '').strip()
    if not updates:
        return ledger
    for field, value in updates.items():
        setattr(ledger, field, value)
    ledger.save(update_fields=list(updates.keys()))
    return ledger


@transaction.atomic
def submit_ledger(user, pk):
    """提交：草稿/已退回 → 已提交；必填字段未填写拦截。"""
    ledger = get_ledger(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    record = _require_record(ledger)
    if not ledger.can_transition_to(LEDGER_STATUS_SUBMITTED):
        return None, '当前状态不允许提交（已提交或已复核台账请勿重复操作）'
    bindings = record.version.get_bindings()
    values = record.get_values()
    missing = [b['field_name'] for b in bindings
               if b.get('is_required') and not values.get(b['field_id'])]
    if missing:
        return None, '必填字段未填写：%s' % '、'.join(missing)
    ledger.status = LEDGER_STATUS_SUBMITTED
    ledger.submitted_at = timezone.now()
    ledger.submitted_by = user
    ledger.save(update_fields=['status', 'submitted_at', 'submitted_by'])
    return ledger, None


def ledger_detail(ledger):
    """台账详情：表头 + 版本快照（字段/绑定/版式）+ 填写值。"""
    record = _require_record(ledger)
    version = record.version
    view = ledger.to_view()
    view['excel'] = {
        'record_id': record.id,
        'values': record.get_values(),
        'editable': ledger.status in EDITABLE_STATUSES,
        'voided': ledger.status == LEDGER_STATUS_VOID,
        'version': version.to_view(with_content=True),
    }
    return view


def list_ledgers(user, request):
    """Excel 路线台账列表（created_from=excel_template），支持类型/状态/日期/编号筛选。"""
    params = request.GET
    query = apply_tenant_filter(
        OperationLedger.objects.filter(created_from=LEDGER_FROM_EXCEL), user)
    ledger_type = params.get('ledger_type')
    if ledger_type:
        query = query.filter(ledger_type=ledger_type)
    status = params.get('status')
    if status:
        query = query.filter(status=status)
    keyword = params.get('keyword')
    if keyword:
        query = query.filter(ledger_no__icontains=keyword)
    executed_from = params.get('executed_from')
    if executed_from:
        query = query.filter(executed_date__gte=executed_from)
    executed_to = params.get('executed_to')
    if executed_to:
        query = query.filter(executed_date__lte=executed_to)
    page, page_size = paginate(request)
    total = query.count()
    records = query[(page - 1) * page_size: page * page_size] if total else []
    data = []
    for ledger in records:
        view = ledger.to_view()
        record = getattr(ledger, 'excel_record', None)
        version = record.version if record else None
        view['excel'] = {
            'version_id': version.pk if version else None,
            'version_no': version.version_no if version else None,
            'template_name': version.template_name_snapshot if version else '',
            'source_filename': version.source_filename if version else '',
        }
        data.append(view)
    return {'data': data, 'total': total, 'page': page, 'page_size': page_size}


def _export_meta(ledger):
    record = _require_record(ledger)
    version = record.version
    return record, version, excel_template_manage._version_meta(version)


def export_excel(user, ledger):
    """导出填充后的 Excel：读取台账引用版本的原始 .xlsx 副本填入单元格。"""
    record, version, meta = _export_meta(ledger)
    path = excel_template_storage.version_path(version.template_id, version.version_no)
    try:
        return export_filled_excel(meta, path, record.get_values())
    except ExcelLayoutError as e:
        _fail(str(e))


def export_pdf_file(user, ledger, pdf_params=None):
    """导出 PDF：填充后的 Excel 经 LibreOffice headless 转换。

    pdf_params 显式传入时优先生效（导出高级设置覆盖，仅当次），否则使用
    台账引用版本快照中的模板级参数（旧版本无参数时按内置缺省）。
    LibreOffice 不可用/转换失败转为业务错误，绝不返回伪造 PDF。
    """
    record, version, meta = _export_meta(ledger)
    path = excel_template_storage.version_path(version.template_id, version.version_no)
    try:
        return export_pdf(meta, path, record.get_values(), pdf_params=pdf_params)
    except ExcelLayoutError as e:
        _fail(str(e))
    except excel_pdf_service.PdfConversionError as e:
        _fail(str(e))


def export_check(user, ledger, pdf_params=None):
    """导出前版式预检：返回 warnings 中文提示列表（只读，无副作用）。

    与导出同一 meta 组装路径，默认按版本快照参数估算，传入 pdf_params
    时按覆盖参数估算（与高级设置导出所见一致）。
    """
    record, version, meta = _export_meta(ledger)
    effective = pdf_params if pdf_params is not None else meta.get('pdf_params')
    try:
        return estimate_pdf_warnings(meta, record.get_values(), effective)
    except ExcelLayoutError as e:
        _fail(str(e))


def export_base_name(ledger):
    record = getattr(ledger, 'excel_record', None)
    version = record.version if record else None
    name = version.source_filename if version else '维护台账'
    return (name or '维护台账').rsplit('.', 1)[0]
