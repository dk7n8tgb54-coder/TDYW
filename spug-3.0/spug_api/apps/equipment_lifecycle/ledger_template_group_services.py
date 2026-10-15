# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——维护台账"按模板查看"分组服务（2026-10-11）。

分组身份 = 台账创建来源 + 来源模板主键，稳定可追溯、不依赖模板名称字符串：
- Excel 模板台账（created_from=excel_template）：组键 = 填写记录引用版本的
  template_id；同一模板 v1/v2… 各发布版本创建的台账归同一组（版本不可变，
  每条台账仍用创建时版本快照展示与导出）；
- 手工补录台账（created_from=manual）：单独归入"无模板/临时补录"组，不同
  来源类型即使模板 ID 相同也不混组；
- 模板只有逻辑删除（停用，is_active=False），无物理删除路径，分组键与组名
  永远可解析；模板改名后组名取当前名，行内"模板版本"继续展示各台账创建
  时的 template_name_snapshot + version_no；
- 模板 ledger_type 创建后不可修改，组内台账类型与模板类型一致；
- 组列表统计在数据库端按组聚合（GROUP BY 单条 SQL），组列表与组内列表共用
  同一筛选口径（状态/编号关键词/执行日期范围），统计不受组内分页影响；
- 组内批量 PDF 导出（2026-10-11）：预览与实际导出共用 _group_export_query
  筛选口径，后端重查固定 ID 清单后逐条用创建时模板版本生成 PDF 并依序
  合并（复用单条导出服务与 pypdf 合并），manual 组无模板版式不支持导出。
"""
import re
from datetime import date

from django.db.models import Count, Max, Min, Q

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle import excel_ledger_services, excel_pdf_service
from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
from apps.equipment_lifecycle.ledger_services import LedgerValidationError, validate_ledger_type
from apps.equipment_lifecycle.models import (
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_MANUAL,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_REVIEWED,
    LEDGER_STATUS_SUBMITTED,
    LEDGER_STATUS_VOID,
    OperationLedger,
)

# 无模板/临时补录组的 URL 组键（模板组键为模板主键数字字符串）
MANUAL_GROUP_KEY = 'manual'
MANUAL_GROUP_NAME = '无模板/临时补录'

# 组统计口径：total + 各状态数量（项目现有五状态）+ 最近执行日期
_GROUP_ANNOTATIONS = dict(
    total=Count('id'),
    draft=Count('id', filter=Q(status=LEDGER_STATUS_DRAFT)),
    submitted=Count('id', filter=Q(status=LEDGER_STATUS_SUBMITTED)),
    returned=Count('id', filter=Q(status=LEDGER_STATUS_RETURNED)),
    reviewed=Count('id', filter=Q(status=LEDGER_STATUS_REVIEWED)),
    void=Count('id', filter=Q(status=LEDGER_STATUS_VOID)),
    last_executed_date=Max('executed_date'),
)

_TEMPLATE_NOT_FOUND = '模板不存在或无权限访问'


def _apply_group_filters(query, status='', keyword='', executed_from='', executed_to=''):
    """组统计与组内列表共用筛选（与统一列表 /ledgers/ 同口径，日期用范围查询）。"""
    if status:
        query = query.filter(status=status)
    if keyword:
        query = query.filter(ledger_no__icontains=keyword)
    if executed_from:
        query = query.filter(executed_date__gte=executed_from)
    if executed_to:
        query = query.filter(executed_date__lte=executed_to)
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
        'submitted': counts['submitted'],
        'returned': counts['returned'],
        'reviewed': counts['reviewed'],
        'void': counts['void'],
        'last_executed_date': counts['last_executed_date'],
    }


def list_template_groups(user, ledger_type, status='', keyword='',
                         executed_from='', executed_to='', page=1, page_size=20):
    """按模板身份分组返回台账统计（仅含有历史台账的组，分页由本函数切片）。

    - Excel 组：按填写记录引用版本的所属模板 GROUP BY 聚合（单条 SQL）；
    - 手工补录组：created_from=manual 全量聚合为一组；
    - 组按最近执行日期倒序（无记录日期靠后），同日期按组键稳定排序。
    """
    validate_ledger_type(ledger_type)
    base = _apply_group_filters(
        apply_tenant_filter(OperationLedger.objects.all(), user).filter(ledger_type=ledger_type),
        status, keyword, executed_from, executed_to)
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
    manual_counts = base.filter(created_from=LEDGER_FROM_MANUAL).aggregate(**_GROUP_ANNOTATIONS)
    if manual_counts['total']:
        groups.append(_group_view(MANUAL_GROUP_KEY, 'manual', None, manual_counts))
    groups.sort(key=lambda g: (
        g['last_executed_date'] or date.min,
        g['group_key'],
    ), reverse=True)
    total = len(groups)
    start = (page - 1) * page_size
    return {
        'data': groups[start: start + page_size],
        'total': total, 'page': page, 'page_size': page_size,
    }


def _get_group_template(user, group_key):
    """解析模板组（租户内），不存在返回 None（不区分不存在与跨租户）。"""
    return apply_tenant_filter(
        OperationLedgerExcelTemplate.objects.all(), user
    ).filter(pk=int(group_key)).first()


def list_group_ledgers(user, group_key, ledger_type='', status='', keyword='',
                       executed_from='', executed_to='', page=1, page_size=20,
                       row_serializer=None):
    """返回模板组内台账分页列表（组键 manual=无模板/临时补录组）。

    - 行结构与统一列表 /ledgers/ 一致（row_serializer 注入来源字段，
      source_version_no 为台账创建时引用的模板版本号）；
    - 台账类型以模板为准：传入 ledger_type 与模板类型不一致时拒绝
      （防 URL 参数篡改造成跨类型误读）；
    - 组内按执行日期倒序 + ID 倒序。
    """
    query = apply_tenant_filter(OperationLedger.objects.all(), user)
    if str(group_key) == MANUAL_GROUP_KEY:
        validate_ledger_type(ledger_type)
        group_name = MANUAL_GROUP_NAME
        query = query.filter(created_from=LEDGER_FROM_MANUAL, ledger_type=ledger_type)
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
    query = _apply_group_filters(query, status, keyword, executed_from, executed_to)
    query = query.select_related('system', 'excel_record__version').order_by('-executed_date', '-id')
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

# 默认导出状态范围：已提交及后续有效状态（草稿/已作废不默认纳入；
# 用户可通过组内状态筛选显式调整到业务允许的范围，与单条导出一致）
DEFAULT_EXPORT_STATUSES = [
    LEDGER_STATUS_SUBMITTED, LEDGER_STATUS_RETURNED, LEDGER_STATUS_REVIEWED]

# 单次批量导出条数上限：每条台账一次 LibreOffice 转换（约 2~5 秒），
# 50 条在 gunicorn 300 秒超时内可同步完成，超过时提示缩小筛选范围
MAX_BATCH_EXPORT_RECORDS = 50

LEDGER_STATUS_LABELS = {
    'draft': '草稿', 'submitted': '已提交', 'returned': '已退回',
    'reviewed': '已复核', 'void': '已作废',
}

_FILE_NAME_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n]')


def _safe_file_name(name):
    """导出文件名净化：模板名来自用户输入，去除文件系统非法字符。"""
    cleaned = _FILE_NAME_ILLEGAL.sub('', str(name)).strip()
    return cleaned or '维护台账'


def _resolve_export_template(user, group_key, ledger_type):
    """解析可导出的模板组（租户内）；manual 组无模板版式统一拒绝。"""
    if str(group_key) == MANUAL_GROUP_KEY:
        raise LedgerValidationError('无模板/临时补录台账没有模板版式，不支持批量 PDF 导出')
    if not str(group_key).isdigit():
        raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
    template = _get_group_template(user, group_key)
    if template is None:
        raise LedgerValidationError(_TEMPLATE_NOT_FOUND)
    if ledger_type and ledger_type != template.ledger_type:
        raise LedgerValidationError('台账类型与模板不匹配')
    return template


def _group_export_query(user, group_key, ledger_type='', status='', keyword='',
                        executed_from='', executed_to=''):
    """导出预览与实际导出共用的组内筛选查询（与组内列表同口径）。

    状态未显式筛选时默认取已提交及后续有效状态（不含草稿/已作废）。
    返回 (template, query)。
    """
    template = _resolve_export_template(user, group_key, ledger_type)
    query = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        created_from=LEDGER_FROM_EXCEL,
        excel_record__version__template_id=template.id,
        ledger_type=template.ledger_type)
    if status:
        query = query.filter(status=status)
    else:
        query = query.filter(status__in=DEFAULT_EXPORT_STATUSES)
    return template, _apply_group_filters(
        query, status='', keyword=keyword,
        executed_from=executed_from, executed_to=executed_to)


def preview_group_pdf_export(user, group_key, ledger_type='', status='', keyword='',
                             executed_from='', executed_to=''):
    """导出确认框数据（只读）：模板名/匹配数/实际日期范围/状态范围/涉及版本。

    与实际导出走同一 _group_export_query，保证确认与生成口径一致；状态
    范围返回状态编码列表（前端做文本映射）。预计页数依赖逐条 LibreOffice
    转换，无可靠估算口径，不返回。
    """
    template, query = _group_export_query(
        user, group_key, ledger_type, status, keyword, executed_from, executed_to)
    total = query.count()
    stats = query.aggregate(
        first_executed=Min('executed_date'), last_executed=Max('executed_date'))
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
        'executed_from': stats['first_executed'],
        'executed_to': stats['last_executed'],
        'versions': versions,
        'max_records': MAX_BATCH_EXPORT_RECORDS,
    }


def export_group_pdfs(user, group_key, ledger_type='', status='', keyword='',
                      executed_from='', executed_to=''):
    """模板组内批量 PDF 导出：重查 → 固定 ID 清单 → 逐条复核 → 生成 → 合并。

    - 后端按与预览一致的筛选重新查询（租户 + 模板归属），不信任前端传入
      的台账 ID、模板名称或记录数；
    - 生成前固定本次记录 ID 清单，逐条复核访问权限（租户 + Excel 来源 +
      填写记录）与状态漂移；按 实际执行日期→台账编号→ID 升序稳定排序；
    - 每条台账用其创建时引用的模板版本与打印参数生成 PDF（复用单条导出
      服务 export_pdf_file），pypdf 依序合并，页面尺寸/方向原样保留；
    - 任一条生成失败立即终止并抛出携带台账编号的错误，绝不返回部分 PDF；
      单条转换临时文件由既有临时目录机制自清理，合并在内存完成，无持久化
      中间产物。

    返回 (filename, content, count)。
    """
    template, query = _group_export_query(
        user, group_key, ledger_type, status, keyword, executed_from, executed_to)
    query = query.select_related('excel_record__version__template') \
        .order_by('executed_date', 'ledger_no', 'id')
    record_ids = list(query.values_list('id', flat=True))
    if not record_ids:
        raise LedgerValidationError('没有符合条件的台账，请调整筛选条件后重试')
    if len(record_ids) > MAX_BATCH_EXPORT_RECORDS:
        raise LedgerValidationError(
            '符合条件的台账共 %d 条，超过单次导出上限 %d 条，请缩小日期范围或筛选条件'
            % (len(record_ids), MAX_BATCH_EXPORT_RECORDS))
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
        if ledger.status not in allowed_statuses:
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
