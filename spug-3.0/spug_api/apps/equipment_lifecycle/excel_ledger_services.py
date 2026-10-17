# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 路线维护台账服务（创建/填写/提交/历史/导出，2026-09-28）。

- 台账行复用正式 OperationLedger（ledger_no/状态机/执行日期），
  created_from='excel_template'；填写值与所用模板版本保存在
  OperationLedgerExcelRecord（与台账一对一）；
- 版本不可变：台账创建即固定引用某已发布版本（PROTECT），历史详情
  据版本快照回放当时的字段、绑定与版式，导出读取该版本原始 .xlsx 副本；
- 周期边界：台账类型取自版本所属模板（week_month/seasonal），请求显式
  携带 ledger_type 时必须与模板一致（另一种类型在此校验拦截）；
- 完成填写（2026-10-16 流程简化，原"提交"）：状态机校验（草稿 → 已完成）
  + 必填字段校验（类型校验在保存填写值时已完成）+ 实际执行日期校验；
  已完成后如需修改走 /excel-ledgers/<pk>/correct/ 更正（须填原因，
  记录修改人/时间/前后值）；
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
    EXECUTOR_FIELD_REMOVED_ERROR,
    LEDGER_STATUS_COMPLETED,
    generate_ledger_no,
)
from apps.equipment_lifecycle.models import (
    ENTRY_CHANNEL_WEB,
    LEDGER_FROM_EXCEL,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_VOID,
    OperationLedger,
    OperationLedgerCorrection,
)

EDITABLE_STATUSES = {LEDGER_STATUS_DRAFT}


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
    if 'executor_names' in body:
        return None, EXECUTOR_FIELD_REMOVED_ERROR
    try:
        ledger = _create_ledger_row(
            user, template, version, executed_date, client_token)
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
def _create_ledger_row(user, template, version, executed_date, client_token):
    bindings = version.get_bindings()
    ledger = OperationLedger(
        tenant_id=user.tenant_id,
        ledger_no=generate_ledger_no(user.tenant_id, template.ledger_type, executed_date),
        ledger_type=template.ledger_type,
        executed_date=executed_date,
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
    """保存填写值（整体替换；仅草稿可编辑，完成后修改走更正接口）。"""
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
    """录入/修正表头执行信息（实际执行日期；仅草稿可编辑）。

    - 周期生成的应填台账 executed_date 为空，由填写人在执行后录入；提前
      生成不把创建当天伪装成实际维护日期（计划填写期次见 maintenance_period）；
    - 字段缺省表示不修改；executed_date 传空串显式清空（回退未录入）；
    - 台账编号创建后不变，不随执行日期重算。
    """
    if ledger.status not in EDITABLE_STATUSES:
        _fail('当前状态不允许修改表头信息')
    if not isinstance(header, dict):
        _fail('表头参数格式不正确')
    if 'executor_names' in header:
        _fail(EXECUTOR_FIELD_REMOVED_ERROR)
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
    if not updates:
        return ledger
    for field, value in updates.items():
        setattr(ledger, field, value)
    ledger.save(update_fields=list(updates.keys()))
    return ledger


@transaction.atomic
def complete_ledger(user, pk):
    """完成填写（流程终点）：草稿 → 已完成；必填字段与执行日期未填拦截。

    - 状态机校验（重复完成/历史状态进入均被拦截，无重复副作用）；
    - 必填校验按台账创建时固定的版本绑定执行；周期生成的应填台账
      executed_date 为空，须先录入实际执行日期再完成填写；
    - 填写值与执行日期的保存由前端在完成前先行调用保存接口（保存失败
      不进入完成步骤），此处再做一次服务端终验。
    """
    ledger = get_ledger(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    record = _require_record(ledger)
    if not ledger.can_transition_to(LEDGER_STATUS_COMPLETED):
        return None, '当前状态不允许完成填写'
    if ledger.executed_date is None:
        return None, '请先填写实际执行日期'
    bindings = record.version.get_bindings()
    values = record.get_values()
    missing = [b['field_name'] for b in bindings
               if b.get('is_required') and not values.get(b['field_id'])]
    if missing:
        return None, '必填字段未填写：%s' % '、'.join(missing)
    ledger.status = LEDGER_STATUS_COMPLETED
    ledger.completed_at = timezone.now()
    ledger.completed_by = user
    ledger.save(update_fields=['status', 'completed_at', 'completed_by'])
    return ledger, None


# Excel 路线已完成台账允许更正的表头字段（值前后差异进入更正记录）
EXCEL_CORRECTABLE_HEADER_FIELDS = {'executed_date': '实际执行日期'}


def _correct_value_changes(bindings, old_values, new_values):
    """填写值前后差异（field_id 排序；不在当前绑定内的键跳过）。"""
    binding_by_id = {b['field_id']: b for b in bindings}
    changes = []
    for field_id in sorted(set(old_values) | set(new_values)):
        old = old_values.get(field_id)
        new = new_values.get(field_id)
        if old == new or field_id not in binding_by_id:
            continue
        changes.append({
            'field': field_id,
            'label': binding_by_id[field_id].get('field_name', field_id),
            'old': old, 'new': new,
        })
    return changes


def _parse_correction_header(ledger, body):
    """解析更正请求的表头执行日期，返回 (header_updates, change, error)。"""
    if not isinstance(body.get('header'), dict) or 'executed_date' not in body['header']:
        return {}, None, None
    raw = body['header'].get('executed_date')
    if raw in (None, ''):
        return None, None, '实际执行日期不能为空'
    try:
        value = datetime.strptime(str(raw)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None, None, '实际执行日期格式不正确'
    if ledger.executed_date == value:
        return {}, None, None
    return {'executed_date': value}, {
        'field': 'executed_date', 'label': '实际执行日期',
        'old': str(ledger.executed_date or ''), 'new': str(value),
    }, None


@transaction.atomic
def correct_completed_ledger(user, ledger, body):
    """已完成 Excel 台账更正：必须填写原因，记录修改人/时间/前后值。

    - 仅已完成状态可更正；填写值整体校验后替换，实际执行日期可选修正；
    - 变更前后值逐项写入 OperationLedgerCorrection（item 为空，表头级更正），
      无实际变化时拒绝（"没有需要更正的内容"），不产生空更正记录。
    返回 (ledger, correction, changes, None) 或 (None, None, None, error)。
    """
    if ledger.status != LEDGER_STATUS_COMPLETED:
        return None, None, None, '只有已完成台账可以进行更正'
    reason = str(body.get('reason') or '').strip()
    if not reason:
        return None, None, None, '更正必须填写原因'
    record = _require_record(ledger)
    bindings = record.version.get_bindings()
    changes = []
    new_values = record.get_values()
    if 'values' in body:
        submitted = body.get('values')
        if not isinstance(submitted, dict):
            return None, None, None, '填写值参数格式不正确'
        try:
            new_values = validate_values(bindings, submitted)
        except ExcelLayoutError as e:
            return None, None, None, str(e)
        changes.extend(_correct_value_changes(
            bindings, record.get_values(), new_values))
    header_updates, header_change, error = _parse_correction_header(ledger, body)
    if error:
        return None, None, None, error
    if header_change:
        changes.append(header_change)
    if not changes:
        return None, None, None, '没有需要更正的内容'
    if header_updates:
        for field, value in header_updates.items():
            setattr(ledger, field, value)
        ledger.save(update_fields=list(header_updates.keys()))
    record.values = _canonical(new_values)
    record.updated_at = timezone.now()
    record.save(update_fields=['values', 'updated_at'])
    correction = OperationLedgerCorrection.objects.create(
        ledger=ledger, item=None, reason=reason,
        changes=json.dumps(changes, ensure_ascii=False, default=str), corrected_by=user)
    return ledger, correction, changes, None


def ledger_detail(ledger):
    """台账详情：表头 + 版本快照（字段/绑定/版式）+ 填写值 + 更正记录。"""
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
    # 更正记录（已完成台账的修改留痕；旧流程历史数据同样透出）
    view['corrections'] = [c.to_view() for c in ledger.corrections.all()]
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
