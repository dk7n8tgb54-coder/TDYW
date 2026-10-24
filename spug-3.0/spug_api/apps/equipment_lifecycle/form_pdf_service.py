# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——数字表单台账 PDF 版式服务（2026-10-22）。

把结构化表单（版本快照）+ 填写值渲染成便于阅读的维护报告式 PDF：标题、
系统与周期信息、各检查分组、填写结果、异常说明；矩阵保留行列对照关系，
可重复明细完整展开。模板样张与真实台账共用同一套版式与渲染函数
（render_form_html），仅标注与取值不同——看到的就是下载的结果。

版式规则：
- A4 纵向缺省；任一矩阵分组的列数 ≥ LANDSCAPE_MATRIX_COLUMNS 时整份改用
  A4 横向（矩阵行列对照是硬要求，横向优先；这是唯一的方向切换规则）；
- 内容自动分页：纸张/方向/内容边距经 Chromium 打印参数定义（HTML 不携带 @page 规则——@page margin 会覆盖打印 margin），
  行/明细条目 break-inside avoid 不跨页裁切，分组标题 break-after avoid
  不落单，行数少的表格整表不跨页，长表按行切页并自动重复表头；
- 页脚（Chromium footerTemplate）：台账标识（样张=模板名；台账=编号+模板
  版本）+ 页码，多页可溯源；
- 空值语义：样张中显示「待填写」（清楚的待填写区域），真实台账显示
  「未填写」——绝不把空值伪装成「正常」或「已完成」；矩阵空单元格保留
  边框空白（即待填写区域）；normal_abnormal 的异常说明与判定值渲染在
  同一行/同一单元格内，结构上保证不与对应检查项分离；
- 文字为真实文本层（非整页截图），可选择、可搜索。

生成链路：结构化数据 → 报告 HTML → 公共适配器 libs.html_pdf（无头
Chromium，worker 子进程隔离）→ PDF 字节。不依赖 Excel 文件、Excel 的
print_plan 或 LibreOffice；不修改 Excel 路线的预览与导出。
"""
import html as html_lib
import json
import tempfile

from apps.equipment_lifecycle.excel_models import TEMPLATE_PERIOD_TEXT
from apps.equipment_lifecycle.excel_pdf_service import pdf_page_info
from apps.equipment_lifecycle.form_template_manage import (
    FIELD_NORMAL_ABNORMAL,
    FIELD_NUMBER,
    GROUP_KIND_MATRIX,
    GROUP_KIND_REPEAT,
    LANDSCAPE_MATRIX_COLUMNS,
    count_form_fields,
)
from apps.equipment_lifecycle.form_ledger_services import FormLedgerError, _type_label
from libs import html_pdf

# 行数不超过该值的表格整表不跨页（消除"标题/表头落在页底"的孤行），
# 更长的表格按行切页并自动重复表头
TABLE_KEEP_TOGETHER_ROWS = 10
# 内容边距（经 Chromium 打印参数定义；下边距须容纳页脚）
PDF_MARGINS = {'top': '16mm', 'bottom': '18mm', 'left': '14mm', 'right': '14mm'}
# 网页与打印共用字体栈（与 excel_print_html 同源，中文落 Noto Sans CJK SC）
BASE_FONT_STACK = (
    '"Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", '
    '"WenQuanYi Micro Hei", "Helvetica Neue", Arial, sans-serif')

LEDGER_STATUS_TEXT = {'draft': '草稿', 'completed': '已完成', 'void': '已作废'}

# 分组种类的中文角标（2026-10-23 与编辑器/填写页统一词汇，设计方案 2.3：
# fields 为默认形态不出角标；网页 FormFillRenderer 分组角标同文本）
_KIND_TAG = {GROUP_KIND_REPEAT: '可重复明细', GROUP_KIND_MATRIX: '检查对比表'}
_CN_NUMS = [
    '', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
    '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九',
    '二十', '二十一', '二十二', '二十三', '二十四', '二十五', '二十六',
    '二十七', '二十八', '二十九', '三十',
]


class FormPdfError(Exception):
    """数字表单 PDF 生成失败（引擎不可用/渲染出错；视图层转业务错误）。"""


def _escape(text):
    return html_lib.escape('' if text is None else str(text), quote=True)


def _cn_num(index):
    return _CN_NUMS[index] if 0 < index < len(_CN_NUMS) else str(index)


def _is_empty_value(raw):
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _format_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _escape(value)
    if number.is_integer():
        return str(int(number))
    return '%g' % number


def _empty_placeholder(sample):
    return '<span class="fb-empty">%s</span>' % ('待填写' if sample else '未填写')


def _desc_html(desc):
    if not desc or not isinstance(desc, str):
        return ''
    return '<div class="fb-desc">异常说明：%s</div>' % _escape(desc)


def _field_value_html(field, raw, desc, sample):
    """单个字段值 → HTML（normal_abnormal 的异常说明渲染在同一值块内）。"""
    if field.get('type') == FIELD_NORMAL_ABNORMAL:
        if raw == 'abnormal':
            value = '<span class="fb-abnormal">异常</span>'
        elif raw == 'normal':
            value = '<span class="fb-normal">正常</span>'
        else:
            value = _empty_placeholder(sample)
        return value + _desc_html(desc)
    if _is_empty_value(raw):
        return _empty_placeholder(sample)
    if field.get('type') == FIELD_NUMBER:
        text = _escape(_format_number(raw))
        return '%s %s' % (text, _escape(field['unit'])) if field.get('unit') \
            else text
    return _escape(raw)


def _field_label_html(field):
    """字段标签：必填标记 + 名称 + 单位 + 字段说明（说明随标签列呈现）。"""
    label = _escape(field.get('name') or '')
    if field.get('unit'):
        label += ' <span class="fb-hint">(%s)</span>' % _escape(field['unit'])
    hint = ('<div class="fb-hint">%s</div>' % _escape(field['description'])
            if field.get('description') else '')
    required = '<span class="fb-req">*</span>' if field.get('required') else ''
    return '%s%s%s' % (required, label, hint)


def _field_row_html(field, row_values, sample):
    """普通分组/明细条目的一个字段行（标签列 + 值列；行级不跨页）。"""
    field_id = field.get('id')
    value = row_values.get(field_id)
    desc = row_values.get('%s__desc' % field_id)
    cell = _field_value_html(field, value,
                             desc if isinstance(desc, str) else '', sample)
    return (
        '<tr><th class="fb-label">%s</th><td class="fb-value">%s</td></tr>'
        % (_field_label_html(field), cell))


def _fields_table_html(group, row_values, sample):
    """明细条目的字段表（条目卡整体 avoid，表本身无需 keep）。"""
    rows = ''.join(
        _field_row_html(field, row_values, sample)
        for field in group.get('fields') or [])
    return '<table class="fb-fields"><tbody>%s</tbody></table>' % rows


def _group_title_nodes(group, index):
    """分组标题与说明节点。

    Chromium 打印不支持 break-after: avoid（标题无法与后续块绑定），
    因此标题不独立成块：表格类分组把它放进 <caption>（随表格整体分页，
    结构上不可能落单页底），明细组把它与首条明细卡放进同一 avoid 块。
    """
    kind_tag = _KIND_TAG.get(group.get('kind'))
    tag = ('<span class="fb-kindtag">%s</span>' % kind_tag) if kind_tag else ''
    desc = ('<div class="fb-group-desc">%s</div>' % _escape(group['description'])
            if group.get('description') else '')
    return (
        '<div class="fb-group-title">%s、%s%s</div>%s'
        % (_cn_num(index), _escape(group.get('name') or '未命名分组'), tag,
           desc))


def _fields_group_html(group, values, sample, index):
    """普通分组：字段两列表格，标题作为 caption 随表格分页。"""
    fields = group.get('fields') or []
    rows = ''.join(_field_row_html(field, values, sample) for field in fields)
    keep = ' fb-keep' if len(fields) <= TABLE_KEEP_TOGETHER_ROWS else ''
    return (
        '<section class="fb-group"><table class="fb-fields%s">'
        '<caption class="fb-caption">%s</caption><tbody>%s</tbody></table>'
        '</section>'
        % (keep, _group_title_nodes(group, index), rows))


def _repeat_group_html(group, values, sample, index):
    """可重复明细组：逐条完整展开（样张空组给一张空白卡表达填写方式）。

    标题与首条明细卡绑定在同一 avoid 块，标题不落单页底。
    """
    rows = values.get(group.get('id')) or []
    item_name = _escape(group.get('item_name') or '明细条目')
    items = []
    if not rows and sample:
        items.append(
            '<div class="fb-repeat-item"><div class="fb-repeat-caption">'
            '%s 1（待填写）</div>%s</div>'
            % (item_name, _fields_table_html(group, {}, True)))
    elif not rows:
        items.append('<p class="fb-none">（无明细记录）</p>')
    for row_index, row in enumerate(rows, 1):
        items.append(
            '<div class="fb-repeat-item"><div class="fb-repeat-caption">%s %d'
            '</div>%s</div>'
            % (item_name, row_index, _fields_table_html(group, row, sample)))
    head = '<div class="fb-keep">%s%s</div>' % (
        _group_title_nodes(group, index), items.pop(0))
    return (
        '<section class="fb-group">%s%s</section>' % (head, ''.join(items)))


def _matrix_cell_html(field, cell_value, cell_desc, sample):
    """矩阵单元格：值 + 异常说明同格渲染（保证说明不离开对应检查项）。"""
    if field.get('type') == FIELD_NORMAL_ABNORMAL:
        return _field_value_html(field, cell_value, cell_desc, sample)
    if _is_empty_value(cell_value):
        return ''  # 边框空白单元格 = 待填写区域（两种模式一致，不伪装已填）
    return _field_value_html(field, cell_value, cell_desc, sample)


def _matrix_group_html(group, values, sample, index):
    """矩阵组：行=检查项、列=对比对象，保留行列对照（表头跨页重复）。

    标题作为 caption 随表格分页（结构上不落单页底）。
    """
    columns = group.get('columns') or []
    fields = group.get('fields') or []
    matrix = values.get(group.get('id')) or {}
    head_cells = ''.join('<th>%s</th>' % _escape(c.get('name') or '')
                         for c in columns)
    body_rows = []
    for field in fields:
        row_cells = matrix.get(field.get('id')) or {}
        cells = []
        for column in columns:
            column_id = column.get('id')
            cells.append(
                '<td class="fb-value">%s</td>' % _matrix_cell_html(
                    field, row_cells.get(column_id),
                    row_cells.get('%s__desc' % column_id) or '', sample))
        body_rows.append(
            '<tr><th class="fb-matrix-rowhead">%s</th>%s</tr>'
            % (_field_label_html(field), ''.join(cells)))
    keep = ' fb-keep' if len(fields) <= TABLE_KEEP_TOGETHER_ROWS else ''
    return (
        '<section class="fb-group"><table class="fb-matrix%s">'
        '<caption class="fb-caption">%s</caption>'
        '<thead><tr><th class="fb-matrix-rowhead">%s</th>%s</tr></thead>'
        '<tbody>%s</tbody></table></section>'
        % (keep, _group_title_nodes(group, index),
           _escape(group.get('name') or '检查项'), head_cells,
           ''.join(body_rows)))


def render_form_html(*, title, badge_html, meta_pairs, form, values, sample):
    """报告正文 HTML（模板样张与真实台账共用的唯一版式实现）。

    未知填写值键不渲染（只按表单结构取值）；结构损坏时按空结构渲染，
    不抛异常（防御性分支，正常数据在保存/发布前已校验）。
    """
    groups = (form.get('groups') or []) if isinstance(form, dict) else []
    sections = []
    for index, group in enumerate(groups, 1):
        if not isinstance(group, dict):
            continue
        kind = group.get('kind')
        if kind == GROUP_KIND_REPEAT:
            sections.append(_repeat_group_html(group, values, sample, index))
        elif kind == GROUP_KIND_MATRIX:
            sections.append(_matrix_group_html(group, values, sample, index))
        else:
            sections.append(_fields_group_html(group, values, sample, index))
    body = (
        '<article class="fb-doc"><div class="fb-title">%s</div>'
        '<div class="fb-badge">%s</div>%s%s</article>'
        % (_escape(title), badge_html, _meta_table_html(meta_pairs),
           ''.join(sections)))
    # 纸张/方向/边距全部经打印参数定义（paper={'format':'A4',...}）：
    # @page CSS 会覆盖 printToPDF 的 margin 参数（置 0 即全出血），
    # 因此本渲染器的 HTML 不携带任何 @page 规则
    return _document(body)


def _meta_table_html(pairs):
    """表头信息表（每行两组：标签 20% + 值 30%，与 CSS 列宽规则严格对应；
    空值统一显示 —；cells 元素=一对 label/value 的 td 片段）。"""
    cells = []
    for label, value in pairs:
        shown = '—' if value in (None, '') else value
        cells.append(
            '<td class="fb-meta-label">%s</td><td>%s</td>'
            % (_escape(label), _escape(shown)))
    rows = [cells[i:i + 2] for i in range(0, len(cells), 2)]
    rows_html = ''.join('<tr>%s</tr>' % ''.join(row) for row in rows)
    return '<table class="fb-meta">%s</table>' % rows_html


def _document(body):
    css = _DOCUMENT_CSS % BASE_FONT_STACK
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<title>数字表单台账</title><style>%s</style></head><body>%s</body>'
        '</html>' % (css, body))


_DOCUMENT_CSS = (
    # 无 @page 规则：纸张/方向/边距由 libs.html_pdf 打印参数唯一定义
    # （@page margin 会覆盖 printToPDF margin 参数）
    'html, body { margin: 0; padding: 0; }\n'
    'body { font-family: %s; color: #262626; font-size: 10.5pt; '
    'line-height: 1.55; }\n'
    '.fb-title { font-size: 18pt; font-weight: 700; text-align: center; '
    'margin: 0 0 6px; }\n'
    '.fb-badge { text-align: center; margin-bottom: 10px; }\n'
    '.fb-badge span { display: inline-block; font-size: 9pt; '
    'padding: 1px 12px; border-radius: 2px; color: #8c8c8c; '
    'border: 1px solid #d9d9d9; }\n'
    '.fb-badge .fb-sample-tag { color: #d46b08; background: #fff7e6; '
    'border-color: #ffd591; }\n'
    'table.fb-meta { width: 100%%; border-collapse: collapse; '
    'table-layout: fixed; margin-bottom: 16px; }\n'
    'table.fb-meta td { border: 1px solid #d9d9d9; padding: 4px 8px; '
    'font-size: 9.5pt; word-break: break-word; }\n'
    'table.fb-meta td.fb-meta-label { background: #fafafa; '
    'color: #595959; width: 20%%; white-space: nowrap; }\n'
    # 打印引擎对 fixed 表未指定宽度的列按 min-content 分配（值列坍缩到
    # 单字符），四列宽度必须全部显式声明
    'table.fb-meta td:nth-child(even) { width: 30%%; }\n'
    '.fb-group { margin-bottom: 16px; }\n'
    'caption.fb-caption { caption-side: top; text-align: left; }\n'
    '.fb-group-title { font-size: 12pt; font-weight: 700; margin: 0 0 8px; '
    'padding: 4px 8px; background: #f5f5f5; '
    'border-left: 3px solid #1890ff; }\n'
    '.fb-kindtag { font-size: 9pt; font-weight: 400; color: #8c8c8c; '
    'margin-left: 8px; }\n'
    '.fb-group-desc { color: #8c8c8c; font-size: 9pt; margin: 0 0 6px; }\n'
    'table.fb-fields, table.fb-matrix { width: 100%%; '
    'border-collapse: collapse; }\n'
    '.fb-keep { break-inside: avoid; page-break-inside: avoid; }\n'
    'table.fb-fields tr, table.fb-matrix tr { break-inside: avoid; '
    'page-break-inside: avoid; }\n'
    'table.fb-matrix thead { display: table-header-group; }\n'
    'table.fb-fields th, table.fb-fields td, table.fb-matrix th, '
    'table.fb-matrix td { border: 1px solid #bfbfbf; padding: 5px 8px; '
    'vertical-align: top; word-break: break-word; text-align: left; }\n'
    'th.fb-label { width: 30%%; background: #fafafa; font-weight: 500; }\n'
    'th.fb-matrix-rowhead { width: 22%%; background: #fafafa; '
    'font-weight: 500; }\n'
    'td.fb-value { white-space: pre-wrap; }\n'
    '.fb-empty { color: #bfbfbf; font-style: italic; }\n'
    '.fb-desc { color: #8c8c8c; font-size: 9pt; margin-top: 2px; '
    'white-space: pre-wrap; }\n'
    '.fb-hint { color: #8c8c8c; font-size: 8.5pt; font-weight: 400; }\n'
    '.fb-req { color: #cf1322; margin-right: 2px; }\n'
    '.fb-normal { color: #389e0d; font-weight: 600; }\n'
    '.fb-abnormal { color: #cf1322; font-weight: 700; }\n'
    '.fb-repeat-item { break-inside: avoid; page-break-inside: avoid; '
    'border: 1px solid #e8e8e8; border-radius: 2px; '
    'padding: 6px 10px 2px; margin-bottom: 8px; }\n'
    '.fb-repeat-caption { color: #8c8c8c; font-size: 9pt; '
    'margin-bottom: 4px; }\n'
    '.fb-none { color: #8c8c8c; font-style: italic; margin: 4px 0; }\n'
)


def _footer_template(identity):
    """Chromium 页脚：台账标识 + 页码（页脚模板须自带内联样式与字号）。"""
    return (
        '<div style="width:100%%; text-align:center; font-size:8px; '
        'color:#8c8c8c;">%s　第 <span class="pageNumber"></span> 页 / '
        '共 <span class="totalPages"></span> 页</div>' % _escape(identity))


def landscape_needed(form):
    """方向规则：任一矩阵分组列数 ≥ LANDSCAPE_MATRIX_COLUMNS → 横向。"""
    groups = (form.get('groups') or []) if isinstance(form, dict) else []
    for group in groups:
        if isinstance(group, dict) \
                and group.get('kind') == GROUP_KIND_MATRIX \
                and len(group.get('columns') or []) >= LANDSCAPE_MATRIX_COLUMNS:
            return True
    return False


def _generate(html, identity, landscape):
    """HTML → PDF 字节（公共适配器；引擎不可用转业务错误，绝不伪造）。

    显式纸张模式（format + landscape + 内容边距）：打印引擎在
    prefer_css_page_size 下会忽略 margin 参数（内容全出血、页脚与内容
    重叠），需要内容边距/页脚的场景必须走显式纸张；HTML 不携带
    @page 规则，纸张与边距以此参数为唯一事实来源。
    """
    if html_pdf.detect_browser() is None:
        raise FormPdfError(
            'PDF 生成依赖浏览器打印引擎（未检测到 Chromium），'
            '请联系管理员在部署环境安装（playwright + chromium + 中文字体）')
    try:
        with tempfile.TemporaryDirectory(prefix='el_form_pdf_') as tmp_dir:
            pdf_path = html_pdf.render_html_to_pdf(
                html, tmp_dir, footer_template=_footer_template(identity),
                margin=PDF_MARGINS,
                paper={'format': 'A4', 'landscape': landscape})
            with open(pdf_path, 'rb') as f:
                content = f.read()
    except html_pdf.HtmlPdfConversionError as e:
        raise FormPdfError(str(e))
    return content, pdf_page_info(content)


def system_label(template):
    return template.system.name if template.system_id else ''


def period_label(template):
    return TEMPLATE_PERIOD_TEXT.get(
        template.generation_period, template.generation_period or '')


def template_sample_pdf(user, template):
    """模板样张 PDF：当前草稿结构的空白样例（不要求先发布，不混入真实数据）。

    返回 (pdf 字节, 页面信息)；无草稿/草稿损坏抛 FormTemplateError（与
    模板管理同一错误语义），生成失败抛 FormPdfError。只读：不写草稿、
    不创建版本、不产生任何写库副作用。
    """
    from apps.equipment_lifecycle import form_template_manage

    if not template.draft_form:
        raise form_template_manage.FormTemplateError(
            '尚未编辑表单草稿，无法生成样张（请先编辑并保存表单）')
    try:
        form = json.loads(template.draft_form)
    except (ValueError, TypeError):
        form = None
    if not isinstance(form, dict) or not (form.get('groups') or []):
        raise form_template_manage.FormTemplateError(
            '草稿表单内容已损坏，请重新编辑保存后再预览')
    badge = '<span class="fb-sample-tag">模板样张 · 空白样例（不含真实台账数据）</span>'
    meta_pairs = [
        ('维护类型', _type_label(template.ledger_type)),
        ('适用系统', system_label(template) or '未配置'),
        ('生成周期', period_label(template) or '待配置'),
        ('可填写项', '%d 个' % count_form_fields(form)),
    ]
    if template.description:
        meta_pairs.append(('模板说明', template.description))
    html = render_form_html(
        title=template.name, badge_html=badge, meta_pairs=meta_pairs,
        form=form, values={}, sample=True)
    return _generate(html, '模板样张 · %s' % template.name,
                     landscape_needed(form))


def ledger_pdf(user, ledger):
    """数字表单台账 PDF：绑定版本快照 + 已保存填写值。

    预览与导出调用同一函数（看到的就是下载的结果）；填写值取台账填写
    记录最近一次保存的服务端值（未保存修改由前端明确提示）。返回
    (pdf 字节, 页面信息)；记录缺失抛 FormLedgerError，生成失败抛
    FormPdfError。
    """
    record = getattr(ledger, 'form_record', None)
    if record is None:
        raise FormLedgerError('台账缺少数字表单填写记录')
    version = record.version
    form = version.get_form()
    if not (form.get('groups') or []):
        raise FormPdfError('模板版本表单内容为空或已损坏，无法生成 PDF')
    template = version.template
    completed_at = ledger.completed_at.strftime('%Y-%m-%d %H:%M') \
        if ledger.completed_at else ''
    badge = ('<span>数字表单台账 · 依据模板版本 v%d（不可变快照）生成</span>'
             % version.version_no)
    meta_pairs = [
        ('台账编号', ledger.ledger_no),
        ('维护类型', _type_label(ledger.ledger_type)),
        ('适用系统', system_label(template)),
        ('计划期次', ledger.maintenance_period),
        ('状态', LEDGER_STATUS_TEXT.get(ledger.status, ledger.status)),
        ('录入人', ledger.created_by.username if ledger.created_by_id else ''),
        ('完成填写', completed_at),
    ]
    html = render_form_html(
        title=version.template_name_snapshot, badge_html=badge,
        meta_pairs=meta_pairs, form=form, values=record.get_values(),
        sample=False)
    identity = '%s · %s v%d' % (
        ledger.ledger_no, version.template_name_snapshot, version.version_no)
    return _generate(html, identity, landscape_needed(form))
