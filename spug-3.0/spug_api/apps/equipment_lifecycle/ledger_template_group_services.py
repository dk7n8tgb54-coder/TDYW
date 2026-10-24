# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——维护台账"按模板查看"分组服务（2026-10-11）。

分组身份 = 台账创建来源 + 来源模板主键，稳定可追溯、不依赖模板名称字符串：
- Excel 模板台账（created_from=excel_template）：组键 = 填写记录引用版本的
  template_id；同一模板 v1/v2… 各发布版本创建的台账归同一组（版本不可变，
  每条台账仍用创建时版本快照展示与导出）；
- 数字表单模板台账（created_from=form_template，2026-10-21）：组键 =
  'form:<模板主键>' 前缀形态（与 Excel 组键的纯数字、manual 保留字互不
  冲突）；组内列表/详情走数字表单台账接口；版式类能力（批量 PDF 导出、
  翻阅回放）为 Excel 版式专属，数字表单组显式拒绝并提示；
- 手工补录台账（created_from=manual）：单独归入"无模板/临时补录"组，不同
  来源类型即使模板 ID 相同也不混组；
- 模板只有逻辑删除（停用，is_active=False），无物理删除路径（被引用时），
  分组键与组名永远可解析；模板改名后组名取当前名，行内"模板版本"继续
  展示各台账创建时的 template_name_snapshot + version_no；
- 模板 ledger_type 创建后不可修改，组内台账类型与模板类型一致；
- 组列表统计在数据库端按组聚合（GROUP BY 单条 SQL），组列表与组内列表共用
  同一筛选口径（状态/编号关键词），统计不受组内分页影响；
- 组内批量 PDF 导出（2026-10-11）：预览与实际导出共用 _group_export_query
  筛选口径，后端重查固定 ID 清单后逐条用创建时模板版本生成 PDF 并依序
  合并（复用单条导出服务与 pypdf 合并），manual 组无模板版式不支持导出；
- 多模板批量 PDF 导出（2026-10-21，"批量导出 PDF"入口）：按模板 ID 跨组
  导出，每模板一份合并 PDF、多模板打包 ZIP，状态口径与组内导出一致，
  模板内按维护期次从早到晚排序。
"""
import io
import re
import zipfile
from datetime import date

from django.db.models import Count, Max, Q

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle import excel_ledger_services, excel_pdf_service, ledger_period_services
from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
from apps.equipment_lifecycle.form_models import OperationLedgerFormTemplate
from apps.equipment_lifecycle.ledger_services import (
    LEDGER_STATUS_FILTER_ALL,
    LedgerValidationError, apply_ledger_status_filter, validate_ledger_type,
)
from apps.equipment_lifecycle.models import (
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_FORM,
    LEDGER_FROM_MANUAL,
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_TEXT,
    OperationLedger,
)

# 无模板/临时补录组的 URL 组键（模板组键为模板主键数字字符串）
MANUAL_GROUP_KEY = 'manual'
MANUAL_GROUP_NAME = '无模板/临时补录'

# 数字表单模板组键前缀：'form:<模板主键>'（Excel 组键为纯数字字符串，
# manual 为保留字，三者互不冲突）
FORM_GROUP_KEY_PREFIX = 'form:'

# 组统计口径：total + 各状态数量 + 最近录入时间
# （executed_date 已于 2026-10-19 删除，组排序/展示改用平台录入时间）
_GROUP_ANNOTATIONS = dict(
    total=Count('id'),
    draft=Count('id', filter=Q(status=LEDGER_STATUS_DRAFT)),
    completed=Count('id', filter=Q(status=LEDGER_STATUS_COMPLETED)),
    void=Count('id', filter=Q(status=LEDGER_STATUS_VOID)),
    last_created_at=Max('created_at'),
)

_TEMPLATE_NOT_FOUND = '模板不存在或无权限访问'


def _apply_group_filters(query, status='', keyword=''):
    """组统计与组内列表共用筛选（与统一列表 /ledgers/ 同口径）。

    状态口径与统一列表一致（apply_ledger_status_filter）：默认视图不含
    已作废，组统计数量与可见行保持一致。
    """
    query = apply_ledger_status_filter(query, status)
    if keyword:
        query = query.filter(ledger_no__icontains=keyword)
    return query


def _group_view(group_key, source_type, template, counts):
    return {
        'group_key': group_key,
        'source_type': source_type,
        'template_id': template.pk if template is not None else None,
        'template_name': template.name if template is not None else MANUAL_GROUP_NAME,
        'is_active': template.is_active if template is not None else None,
        'ledger_type': template.ledger_type if template is not None else '',
        'total': counts['total'],
        'draft': counts['draft'],
        'completed': counts['completed'],
        'void': counts['void'],
        'last_created_at': counts['last_created_at'],
    }


def list_template_groups(user, ledger_type, status='', keyword='',
                         page=1, page_size=20):
    """按模板身份分组返回台账统计（仅含有历史台账的组，分页由本函数切片）。

    - Excel 组：按填写记录引用版本的所属模板 GROUP BY 聚合（单条 SQL）；
    - 数字表单组（2026-10-21）：按 form_record 引用版本的所属模板聚合，
      组键 'form:<id>'；
    - 手工补录组：created_from=manual 全量聚合为一组；
    - 组按最近录入时间倒序（无记录靠后），同时间按组键稳定排序。
    """
    validate_ledger_type(ledger_type)
    base = _apply_group_filters(
        apply_tenant_filter(OperationLedger.objects.all(), user).filter(ledger_type=ledger_type),
        status, keyword)
    template_counts = list(
        base.filter(created_from=LEDGER_FROM_EXCEL, excel_record__isnull=False)
        .values('excel_record__version__template_id')
        .annotate(**_GROUP_ANNOTATIONS)
        .order_by())
    template_map = {}
    template_ids = [row['excel_record__version__template_id'] for row in template_counts]
    if template_ids:
        templates = apply_tenant_filter(
            OperationLedgerExcelTemplate.objects.all(), user).filter(pk__in=template_ids)
        template_map = {t.id: t for t in templates}
    groups = []
    for row in template_counts:
        template = template_map.get(row['excel_record__version__template_id'])
        if template is None:
            # 填写记录缺失或模板行缺失的异常数据不进组（组名不可解析）
            continue
        groups.append(_group_view(str(template.id), 'excel', template, row))
    form_counts = list(
        base.filter(created_from=LEDGER_FROM_FORM, form_record__isnull=False)
        .values('form_record__version__template_id')
        .annotate(**_GROUP_ANNOTATIONS)
        .order_by())
    form_template_map = {}
    form_template_ids = [row['form_record__version__template_id'] for row in form_counts]
    if form_template_ids:
        form_templates = apply_tenant_filter(
            OperationLedgerFormTemplate.objects.all(), user).filter(pk__in=form_template_ids)
        form_template_map = {t.id: t for t in form_templates}
    for row in form_counts:
        template = form_template_map.get(row['form_record__version__template_id'])
        if template is None:
            continue
        groups.append(_group_view(
            FORM_GROUP_KEY_PREFIX + str(template.id), 'form', template, row))
    manual_counts = base.filter(created_from=LEDGER_FROM_MANUAL).aggregate(**_GROUP_ANNOTATIONS)
    if manual_counts['total']:
        groups.append(_group_view(MANUAL_GROUP_KEY, 'manual', None, manual_counts))
    groups.sort(key=lambda g: (
        g['last_created_at'] or date.min,
        g['group_key'],
    ), reverse=True)
    total = len(groups)
    start = (page - 1) * page_size
    return {
        'data': groups[start: start + page_size],
        'total': total, 'page': page, 'page_size': page_size,
    }


def _get_group_template(user, group_key):
    """解析 Excel 模板组（租户内），不存在返回 None（不区分不存在与跨租户）。"""
    return apply_tenant_filter(
        OperationLedgerExcelTemplate.objects.all(), user
    ).filter(pk=int(group_key)).first()


def _get_group_form_template(user, group_key):
    """解析数字表单模板组（form:<id>），不存在返回 None。"""
    raw = str(group_key)[len(FORM_GROUP_KEY_PREFIX):]
    if not raw.isdigit():
        return None
    return apply_tenant_filter(
        OperationLedgerFormTemplate.objects.all(), user
    ).filter(pk=int(raw)).first()


def list_group_ledgers(user, group_key, ledger_type='', status='', keyword='',
                       page=1, page_size=20,
                       row_serializer=None):
    """返回模板组内台账分页列表（组键 manual=无模板/临时补录组，
    form:<id>=数字表单模板组）。

    - 行结构与统一列表 /ledgers/ 一致（row_serializer 注入来源字段，
      source_version_no 为台账创建时引用的模板版本号）；
    - 台账类型以模板为准：传入 ledger_type 与模板类型不一致时拒绝
      （防 URL 参数篡改造成跨类型误读）；
    - 组内按录入时间倒序 + ID 倒序。
    """
    query = apply_tenant_filter(OperationLedger.objects.all(), user)
    if str(group_key) == MANUAL_GROUP_KEY:
        validate_ledger_type(ledger_type)
        group_name = MANUAL_GROUP_NAME
        query = query.filter(created_from=LEDGER_FROM_MANUAL, ledger_type=ledger_type)
    elif str(group_key).startswith(FORM_GROUP_KEY_PREFIX):
        template = _get_group_form_template(user, group_key)
        if template is None:
            raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
        if ledger_type and ledger_type != template.ledger_type:
            raise LedgerValidationError('台账类型与模板不匹配')
        group_name = template.name
        query = query.filter(
            created_from=LEDGER_FROM_FORM,
            form_record__version__template_id=template.id,
            ledger_type=template.ledger_type)
    else:
        if not str(group_key).isdigit():
            raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
        template = _get_group_template(user, group_key)
        if template is None:
            raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
        if ledger_type and ledger_type != template.ledger_type:
            raise LedgerValidationError('台账类型与模板不匹配')
        group_name = template.name
        query = query.filter(
            created_from=LEDGER_FROM_EXCEL,
            excel_record__version__template_id=template.id,
            ledger_type=template.ledger_type)
    query = _apply_group_filters(query, status, keyword)
    query = query.select_related(
        'system', 'excel_record__version', 'form_record__version') \
        .order_by('-created_at', '-id')
    total = query.count()
    records = query[(page - 1) * page_size: page * page_size] if total else []
    data = []
    for record in records:
        view = record.to_view()
        if row_serializer is not None:
            view.update(row_serializer(record))
        data.append(view)
    return {
        'group_key': str(group_key), 'group_name': group_name,
        'data': data, 'total': total, 'page': page, 'page_size': page_size,
    }


# ======================================================================
# 组内批量 PDF 导出（"导出本模板台账"，2026-10-11）
# ======================================================================

# 默认导出状态范围：已完成（草稿/已作废不默认纳入；用户可通过组内状态
# 筛选显式调整到业务允许的范围，与单条导出一致）
DEFAULT_EXPORT_STATUSES = [LEDGER_STATUS_COMPLETED]

# 单次批量导出条数上限：每条台账一次 LibreOffice 转换（约 2~5 秒），
# 50 条在 gunicorn 300 秒超时内可同步完成，超过时提示缩小筛选范围
MAX_BATCH_EXPORT_RECORDS = 50

LEDGER_STATUS_LABELS = {
    'draft': '草稿', 'completed': '已完成', 'void': '已作废',
}

_FILE_NAME_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n]')


def _safe_file_name(name):
    """导出文件名净化：模板名来自用户输入，去除文件系统非法字符。"""
    cleaned = _FILE_NAME_ILLEGAL.sub('', str(name)).strip()
    return cleaned or '维护台账'


def _resolve_export_template(user, group_key, ledger_type):
    """解析可导出的模板组（租户内）；manual 组与数字表单组按支持范围明确拒绝。"""
    if str(group_key) == MANUAL_GROUP_KEY:
        raise LedgerValidationError('无模板/临时补录台账没有模板版式，不支持批量 PDF 导出')
    if str(group_key).startswith(FORM_GROUP_KEY_PREFIX):
        raise LedgerValidationError('数字表单台账暂不支持批量 PDF 导出')
    if not str(group_key).isdigit():
        raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
    template = _get_group_template(user, group_key)
    if template is None:
        raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
    if ledger_type and ledger_type != template.ledger_type:
        raise LedgerValidationError('台账类型与模板不匹配')
    return template


def _group_export_query(user, group_key, ledger_type='', status='', keyword=''):
    """导出预览与实际导出共用的组内筛选查询（与组内列表同口径）。

    状态未显式筛选时默认取已完成及后续有效状态（不含草稿/已作废）；
    status='all'（全部）明确包含草稿与已作废，status=void 仅导出已作废。
    返回 (template, query)。
    """
    template = _resolve_export_template(user, group_key, ledger_type)
    query = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        created_from=LEDGER_FROM_EXCEL,
        excel_record__version__template_id=template.id,
        ledger_type=template.ledger_type)
    if not status:
        query = query.filter(status__in=DEFAULT_EXPORT_STATUSES)
    return template, _apply_group_filters(query, status=status, keyword=keyword)


def preview_group_pdf_export(user, group_key, ledger_type='', status='', keyword=''):
    """导出确认框数据（只读）：模板名/匹配数/状态范围/涉及版本。

    与实际导出走同一 _group_export_query，保证确认与生成口径一致；状态
    范围返回状态编码列表（前端做文本映射）。预计页数依赖逐条 LibreOffice
    转换，无可靠估算口径，不返回。
    """
    template, query = _group_export_query(
        user, group_key, ledger_type, status, keyword)
    total = query.count()
    versions = []
    if total:
        version_rows = query.values('excel_record__version__version_no') \
            .annotate(count=Count('id')) \
            .order_by('excel_record__version__version_no')
        versions = [{'version_no': row['excel_record__version__version_no'],
                     'count': row['count']} for row in version_rows]
    return {
        'group_key': str(group_key),
        'template_id': template.id,
        'template_name': template.name,
        'ledger_type': template.ledger_type,
        'total': total,
        'status_scope': [status] if status else list(DEFAULT_EXPORT_STATUSES),
        'versions': versions,
        'max_records': MAX_BATCH_EXPORT_RECORDS,
    }


def export_group_pdfs(user, group_key, ledger_type='', status='', keyword=''):
    """模板组内批量 PDF 导出：重查 → 固定 ID 清单 → 逐条复核 → 生成 → 合并。

    - 后端按与预览一致的筛选重新查询（租户 + 模板归属），不信任前端传入
      的台账 ID、模板名称或记录数；
    - 生成前固定本次记录 ID 清单，逐条复核访问权限（租户 + Excel 来源 +
      填写记录）与状态漂移；按 台账编号→ID 升序稳定排序；
    - 每条台账用其创建时引用的模板版本与打印参数生成 PDF（复用单条导出
      服务 export_pdf_file），pypdf 依序合并，页面尺寸/方向原样保留；
    - 任一条生成失败立即终止并抛出携带台账编号的错误，绝不返回部分 PDF；
      单条转换临时文件由既有临时目录机制自清理，合并在内存完成，无持久化
      中间产物。

    返回 (filename, content, count)。
    """
    template, query = _group_export_query(
        user, group_key, ledger_type, status, keyword)
    query = query.select_related('excel_record__version__template') \
        .order_by('ledger_no', 'id')
    record_ids = list(query.values_list('id', flat=True))
    if not record_ids:
        raise LedgerValidationError('没有符合条件的台账，请调整筛选条件后重试')
    if len(record_ids) > MAX_BATCH_EXPORT_RECORDS:
        raise LedgerValidationError(
            '符合条件的台账共 %d 条，超过单次导出上限 %d 条，请调整筛选条件缩小范围'
            % (len(record_ids), MAX_BATCH_EXPORT_RECORDS))
    if status == LEDGER_STATUS_FILTER_ALL:
        allowed_statuses = None  # "全部"：不限制状态（含草稿/已作废）
    else:
        allowed_statuses = {status} if status else set(DEFAULT_EXPORT_STATUSES)
    # 固定 ID 清单后逐条实时复核：租户过滤 + Excel 来源 + 填写记录存在 +
    # 状态漂移（查询与生成之间状态变化的记录在此拒绝）
    parts = []
    for record_id in record_ids:
        ledger = apply_tenant_filter(
            OperationLedger.objects.filter(created_from=LEDGER_FROM_EXCEL), user
        ).filter(pk=record_id, excel_record__isnull=False) \
            .select_related('excel_record__version__template').first()
        if ledger is None:
            raise LedgerValidationError('台账不存在或已被删除，导出已终止')
        if allowed_statuses is not None and ledger.status not in allowed_statuses:
            raise LedgerValidationError(
                '台账 %s 状态已变化（%s），请重新确认后导出'
                % (ledger.ledger_no,
                   LEDGER_STATUS_LABELS.get(ledger.status, ledger.status)))
        try:
            parts.append(excel_ledger_services.export_pdf_file(user, ledger))
        except (excel_ledger_services.ExcelLedgerError,
                excel_pdf_service.PdfConversionError) as e:
            raise LedgerValidationError('台账 %s 生成 PDF 失败：%s' % (ledger.ledger_no, e))
    try:
        content = excel_pdf_service.merge_pdf_bytes(parts)
    except excel_pdf_service.PdfConversionError as e:
        raise LedgerValidationError('PDF 合并失败：%s' % e)
    filename = '%s-批量导出-%s.pdf' % (
        _safe_file_name(template.name), date.today().strftime('%Y%m%d'))
    return filename, content, len(parts)


# ======================================================================
# 模板组翻阅（"翻阅台账"，2026-10-18）
# ----------------------------------------------------------------------
# 网页内像翻同一本纸质台账一样连续查看某模板的历次记录：
# - 本服务只提供"翻阅清单"（一次性返回组内符合筛选的台账 ID 与展示元数据），
#   每张台账的版式回放仍走既有 Excel 详情端点（创建时版本快照不变）；
# - 翻页由前端在该清单内移动，不受组内列表分页（page_size=20）限制，
#   跨分页边界、同一期次补建并存的多张台账都能逐张查看；
# - manual 组无模板版式，不提供翻阅（与批量 PDF 导出同口径拒绝）。
# ======================================================================

def _browse_sort_key(ledger):
    """翻阅排序键（升序，像翻纸质台账从最早一张开始）：

    - 主序 = 计划维护期次的起始日期（表头期次标记，与周期分组同口径）；
    - 回退 = 无期次标记（或标记不可解析）的记录排在最后；
    - 同键内以 ID 升序兜底（= 创建顺序）保证顺序稳定；同一期次的多张
      台账（补建并存）相邻排列、先建先翻，逐张可翻不漏。
    """
    period_key = ledger_period_services.ledger_period_key(ledger)
    if period_key:
        try:
            _, start, _ = ledger_period_services.parse_maintenance_period(
                ledger.ledger_type, period_key)
            return (start, ledger.id)
        except ledger_period_services.LedgerValidationError:
            pass
    return (date.max, ledger.id)


def browse_group_ledgers(user, group_key, ledger_type='', status='', keyword=''):
    """模板组翻阅清单（只读）：组内符合筛选的台账按翻阅顺序一次性返回。

    - 筛选口径与组内列表完全一致（_apply_group_filters：默认不含已作废，
      status=void 仅已作废，status=all 全部；keyword 编号模糊），
      用户以什么筛选范围进入组内就按什么范围翻阅；
    - 每条条目仅含 ID 与展示元数据（编号/状态/期次标签/版本号），量级为
      组内台账数；期次标签由 ledger_period_display 下发（无期次标记的
      台账展示"未标注期次"）；
    - 每张台账的版式回放由前端按条目 ID 调既有 Excel 详情端点完成，创建
      时固定的版本快照不受模板改名/更新/停用影响。
    """
    if str(group_key) == MANUAL_GROUP_KEY:
        raise LedgerValidationError('无模板/临时补录台账没有模板版式，不支持翻阅')
    if str(group_key).startswith(FORM_GROUP_KEY_PREFIX):
        raise LedgerValidationError('数字表单台账暂不支持翻阅查看')
    if not str(group_key).isdigit():
        raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
    template = _get_group_template(user, group_key)
    if template is None:
        raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
    if ledger_type and ledger_type != template.ledger_type:
        raise LedgerValidationError('台账类型与模板不匹配')
    query = _apply_group_filters(
        apply_tenant_filter(OperationLedger.objects.all(), user).filter(
            created_from=LEDGER_FROM_EXCEL,
            excel_record__version__template_id=template.id,
            ledger_type=template.ledger_type),
        status, keyword)
    ledgers = sorted(
        query.select_related('system', 'excel_record__version'),
        key=_browse_sort_key)
    entries = []
    for ledger in ledgers:
        display = ledger_period_services.ledger_period_display(ledger)
        record = getattr(ledger, 'excel_record', None)
        version = record.version if record is not None else None
        entries.append({
            'id': ledger.id,
            'ledger_no': ledger.ledger_no,
            'status': ledger.status,
            'maintenance_period': ledger.maintenance_period,
            'period_key': ledger_period_services.ledger_period_key(ledger),
            'period_label': display['period_label'],
            'period_is_derived': display['period_is_derived'],
            'source_version_no': version.version_no if version else None,
        })
    return {
        'group_key': str(group_key),
        'template_id': template.id,
        'group_name': template.name,
        'ledger_type': template.ledger_type,
        'total': len(entries),
        'entries': entries,
    }


# ======================================================================
# 多模板批量 PDF 导出（"批量导出 PDF"，2026-10-21）
# ----------------------------------------------------------------------
# 台账列表页（按维护周期 / 按模板查看）的"批量导出 PDF"入口：用户勾选
# 若干模板后按模板身份导出。与组内批量导出（"导出本模板台账"）的区别：
# - 范围由弹窗中的模板与状态选择明确决定，不继承列表的日期/本周/本月/
#   航季筛选，也不按当前分页截取；
# - 按模板 ID 组织导出（同一模板各版本台账归同一模板），每个模板一份
#   合并 PDF，多模板打包 ZIP，不同模板不混成一个 PDF；
# - 模板内排序按维护期次从早到晚（与"翻阅台账"同口径），无可靠期次的
#   排最后按创建顺序兜底；组内导出仍按台账编号排序（既有交互保留）。
# ======================================================================

# 已知台账状态集合（三状态简化后固定）；counts 聚合兜底未知状态
_EXPORT_STATUS_KEYS = (LEDGER_STATUS_COMPLETED, LEDGER_STATUS_DRAFT, LEDGER_STATUS_VOID)

ZIP_CONTENT_TYPE = 'application/zip'


def _export_scope_statuses(status):
    """状态范围 → 参与导出的状态集合（与 _group_export_query 同口径）。

    - ''（默认）：仅已完成（不含草稿/已作废）；
    - 'all'：全部（含草稿/已作废）；
    - 其他值：精确匹配该状态（draft/void）。
    """
    if not status:
        return set(DEFAULT_EXPORT_STATUSES)
    if status == LEDGER_STATUS_FILTER_ALL:
        return None
    return {status}


def list_export_templates(user, ledger_type):
    """"批量导出 PDF"模板候选清单（只读，弹窗打开时拉取一次）。

    - 仅本租户、指定台账类型的 Excel 模板（含已停用——停用只禁止用于
      新建，仍有历史台账的模板可正常导出）；manual 补录无模板版式不提供；
    - 仅有历史台账（任意状态）的模板进入清单，无任何台账的模板不出现；
    - 每模板下发各状态数量与"版本 × 状态"分布，前端据此计算所选状态
      范围下的可导出数量、涉及版本与合计（与实际导出共用 _group_export_query
      筛选定义，实际导出时后端重查并做数量一致性复核）。
    """
    validate_ledger_type(ledger_type)
    rows = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        created_from=LEDGER_FROM_EXCEL, ledger_type=ledger_type,
        excel_record__version__template_id__isnull=False,
    ).values(
        'excel_record__version__template_id',
        'excel_record__version__version_no', 'status',
    ).annotate(count=Count('id')).order_by()
    template_ids = sorted({row['excel_record__version__template_id'] for row in rows})
    templates_out = []
    if template_ids:
        template_map = {
            t.id: t for t in apply_tenant_filter(
                OperationLedgerExcelTemplate.objects.all(), user).filter(
                pk__in=template_ids)}
        grouped = {}
        for row in rows:
            template = template_map.get(row['excel_record__version__template_id'])
            if template is None:
                # 填写记录缺失或模板行缺失的异常数据不进清单（组名不可解析）
                continue
            item = grouped.setdefault(template.id, {
                'template_id': template.id,
                'template_name': template.name,
                'is_active': template.is_active,
                'ledger_type': template.ledger_type,
                'counts': {key: 0 for key in _EXPORT_STATUS_KEYS},
                'versions': {},
            })
            item['counts'][row['status']] = \
                item['counts'].get(row['status'], 0) + row['count']
            version_key = str(row['excel_record__version__version_no'])
            version_entry = item['versions'].setdefault(
                version_key, {key: 0 for key in _EXPORT_STATUS_KEYS})
            version_entry[row['status']] = \
                version_entry.get(row['status'], 0) + row['count']
        templates_out = sorted(
            grouped.values(), key=lambda item: (item['template_name'], item['template_id']))
    return {
        'ledger_type': ledger_type,
        'templates': templates_out,
        'default_statuses': list(DEFAULT_EXPORT_STATUSES),
        'max_records': MAX_BATCH_EXPORT_RECORDS,
    }


def _parse_template_ids(template_ids):
    """导出模板 ID 清单解析：非空、整数、不重复（防模板混选与重复提交）。"""
    if not isinstance(template_ids, (list, tuple)) or not template_ids:
        raise LedgerValidationError('请先选择要导出的模板')
    parsed = []
    for value in template_ids:
        text = str(value).strip()
        if not text.isdigit():
            raise LedgerValidationError('模板选择参数不正确：%s' % value)
        parsed.append(int(text))
    if len(set(parsed)) != len(parsed):
        raise LedgerValidationError('模板选择包含重复项，请检查后重试')
    return parsed


def _check_expected_totals(expected_totals, template, count):
    """预览一致性守卫：导出数量与确认时不一致须重新确认，不静默漏导。

    expected_totals 为前端预览时各模板的数量（键为模板 ID 字符串）；预览后
    数据变化（新完成/被作废/删除等）导致数量漂移时明确报错。
    """
    if not isinstance(expected_totals, dict):
        return
    expected = expected_totals.get(str(template.id))
    if expected is None:
        return
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        raise LedgerValidationError('导出确认数量参数不正确，请重新打开导出确认后重试')
    if expected != count:
        raise LedgerValidationError(
            '模板「%s」当前可导出 %d 条，与确认时（%d 条）不一致，'
            '数据可能已变化，请重新确认后导出' % (template.name, count, expected))


def _collect_template_export_plan(user, template_id, ledger_type, status,
                                  expected_totals):
    """解析单个导出模板并生成记录计划（数量校验 + 期次排序）。

    返回 (template, ledgers)；无可导出记录 / 跨类型 / 跨租户 / 数量漂移
    均在此明确报错。排序 = 维护期次从早到晚（_browse_sort_key：期次起始
    日期升序，无可靠期次的排最后按创建顺序），每条台账生成时仍逐条复核。
    """
    template = _resolve_export_template(user, str(template_id), ledger_type)
    _, query = _group_export_query(
        user, str(template_id), ledger_type, status=status, keyword='')
    count = query.count()
    if not count:
        raise LedgerValidationError(
            '模板「%s」在所选状态范围内没有可导出的台账' % template.name)
    _check_expected_totals(expected_totals, template, count)
    ledgers = sorted(
        query.select_related('system', 'excel_record__version'),
        key=_browse_sort_key)
    return template, ledgers


def _dedupe_pdf_names(templates):
    """各模板合并 PDF 的文件名（同名模板以模板 ID 区分，非法字符净化）。"""
    names = [_safe_file_name(template.name) for template in templates]
    duplicated = {name for name in names if names.count(name) > 1}
    stamp = date.today().strftime('%Y%m%d')
    filenames = []
    for name, template in zip(names, templates):
        if name in duplicated:
            name = '%s-%d' % (name, template.id)
        filenames.append('%s-批量导出-%s.pdf' % (name, stamp))
    return filenames


def export_templates_pdfs(user, ledger_type, template_ids, status='',
                          expected_totals=None):
    """多模板批量导出：每模板一份合并 PDF，多模板打包 ZIP 下载。

    - 后端按模板 ID 重新查询完整记录（租户 + 台账类型 + Excel 来源），
      不信任前端传入的数量；expected_totals 与预览数量不一致时明确报错；
    - 状态范围由 status 决定（默认已完成；all 含草稿/已作废），与预览、
      组内导出同口径；导出不受列表筛选与分页影响；
    - 每条台账用创建时引用的模板版本与打印参数生成 PDF（复用单条导出
      服务），模板内依期次排序后 pypdf 合并；任一条失败立即终止并抛出
      携带模板名与台账编号的错误，绝不返回部分产物；单条转换临时文件由
      既有临时目录机制自清理，合并与 ZIP 打包在内存完成，无持久化中间产物；
    - 单模板返回 (pdf文件名, pdf内容, 条数)；多模板返回
      (zip文件名, zip内容, 条数)，ZIP 内各 PDF 文件名含模板名与导出日期，
      同名模板以模板 ID 区分。

    状态范围允许的模板台账总量受 MAX_BATCH_EXPORT_RECORDS 约束（与组内
    导出同一上限，同步生成在请求超时内可完成；LibreOffice 单条约 2~5 秒）。
    """
    validate_ledger_type(ledger_type)
    ids = _parse_template_ids(template_ids)
    allowed_statuses = _export_scope_statuses(status)
    resolved = [_collect_template_export_plan(
        user, template_id, ledger_type, status, expected_totals)
        for template_id in ids]
    total = sum(len(ledgers) for _, ledgers in resolved)
    if total > MAX_BATCH_EXPORT_RECORDS:
        raise LedgerValidationError(
            '所选模板可导出台账共 %d 条，超过单次导出上限 %d 条，'
            '请减少模板或缩小状态范围' % (total, MAX_BATCH_EXPORT_RECORDS))
    # 生成顺序与 ZIP 内顺序 = 模板名称 → ID（与弹窗清单一致，稳定可复现）
    resolved.sort(key=lambda pair: (pair[0].name, pair[0].id))
    template_pdfs = []
    generated = 0
    for template, ledgers in resolved:
        parts = []
        for ledger in ledgers:
            # 固定清单后逐条实时复核：租户过滤 + Excel 来源 + 填写记录存在
            # + 状态漂移（查询与生成之间状态变化的记录在此拒绝）
            fresh = apply_tenant_filter(
                OperationLedger.objects.filter(created_from=LEDGER_FROM_EXCEL), user
            ).filter(pk=ledger.id, excel_record__isnull=False) \
                .select_related('excel_record__version__template').first()
            if fresh is None:
                raise LedgerValidationError(
                    '模板「%s」的台账已不存在或已被删除，导出已终止' % template.name)
            if allowed_statuses is not None and fresh.status not in allowed_statuses:
                raise LedgerValidationError(
                    '模板「%s」的台账 %s 状态已变化（%s），请重新确认后导出'
                    % (template.name, fresh.ledger_no,
                       LEDGER_STATUS_LABELS.get(fresh.status, fresh.status)))
            try:
                parts.append(excel_ledger_services.export_pdf_file(user, fresh))
            except (excel_ledger_services.ExcelLedgerError,
                    excel_pdf_service.PdfConversionError) as e:
                raise LedgerValidationError(
                    '模板「%s」的台账 %s 生成 PDF 失败：%s'
                    % (template.name, fresh.ledger_no, e))
            generated += 1
        try:
            template_pdfs.append(excel_pdf_service.merge_pdf_bytes(parts))
        except excel_pdf_service.PdfConversionError as e:
            raise LedgerValidationError('模板「%s」PDF 合并失败：%s' % (template.name, e))
    if len(template_pdfs) == 1:
        return _dedupe_pdf_names([resolved[0][0]])[0], template_pdfs[0], generated
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, content in zip(_dedupe_pdf_names(
                [template for template, _ in resolved]), template_pdfs):
            zf.writestr(filename, content)
    zip_name = '%s台账批量导出-%s.zip' % (
        LEDGER_TYPE_TEXT.get(ledger_type, ''), date.today().strftime('%Y%m%d'))
    return zip_name, buffer.getvalue(), generated
