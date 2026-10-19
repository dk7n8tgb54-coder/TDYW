# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——原生台账打印 HTML 构建与 Chromium headless PDF 转换。

分页渲染逻辑移植自原生台账样板 quality/prototypes/native_ledger/src/print.js
（同一套分页规范），并去掉样板专用假设，泛化为任意用户绘制的模板：

- 工作表 = 快照 sheetOrder 首个工作表；打印行范围 = 实际内容范围
  （cellData/合并区覆盖到的最大行），不打印空白补位行；
- 重复表头 = 快照冻结行（freeze.ySplit），跨页自动重复；
- 分页按行高累计，分页点避开纵向合并区域（合并起始行前断页）；
- 缩放：fitToWidth 时按内容宽度/可打印宽度收缩（只缩不放），字体随缩放；
- 边框：完全按快照样式 bd 声明绘制（编辑器里画了边框打印才有边框，
  与编辑器内打印预览所见一致）；合并、行高列宽、字体字号颜色背景
  对齐随快照；绑定单元格打印填写值（覆盖底表静态值）；
- 警告（不阻断导出，前端预检展示）：缩放低于 70%、未开适应页宽且内容
  超宽被裁切、纵向合并被分页切断。

PDF 转换依赖 Chromium headless（与样板的 Chromium 打印路径一致，
preferCSSPageSize 语义等价于 --print-to-pdf 尊重 @page 尺寸）：
- 环境检测：PATH 中的 chromium/chromium-browser/google-chrome/chrome 或
  Playwright 浏览器缓存目录下的 chromium 可执行文件；
- 不可用时抛 PdfConversionError，调用方返回明确业务错误，
  绝不返回伪造的 PDF 成功结果；
- 转换超时默认 120 秒；输出缺失或空文件均视为失败。

部署依赖（PDF 导出前提，生产镜像/测试容器需一并安装，见 docker/Dockerfile）：
- chromium（headless 打印引擎）+ 中文字体（fonts-noto-cijk，未安装时中文
  渲染为方框，不产生报错）。
"""
import glob
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from html import escape

from django.conf import settings

MM_TO_PX = 96 / 25.4
CONVERT_TIMEOUT_SECONDS = 120
FOOTER_HEIGHT_PX = 22
LOW_SCALE_WARN = 0.7

_CHROMIUM_NAMES = ('chromium', 'chromium-browser', 'google-chrome', 'chrome')
# Playwright 浏览器缓存目录（1.x 老布局 chrome-linux/ 与 1.60+ 新布局
# chrome-linux64/ 并存，headless shell 目录结构随版本不同）
_PLAYWRIGHT_GLOBS = (
    os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome'),
    os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux/chrome'),
    os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-*/'
                       'chrome-headless-shell-linux64/chrome-headless-shell'),
    os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-*/'
                       'chrome-linux/headless_shell'),
)


class PdfConversionError(Exception):
    """原生台账 PDF 转换失败（环境不可用 / 转换出错 / 输出为空）。"""


# ======================================================================
# Chromium 环境检测与转换
# ======================================================================

def detect_chromium():
    """返回可用的 Chromium 可执行文件路径；不可用返回 None。"""
    for name in _CHROMIUM_NAMES:
        path = shutil.which(name)
        if path:
            return path
    for pattern in _PLAYWRIGHT_GLOBS:
        candidates = sorted(glob.glob(pattern), reverse=True)
        if candidates and os.access(candidates[0], os.X_OK):
            return candidates[0]
    return None


def convert_html_file_to_pdf(html_path, out_dir, timeout=CONVERT_TIMEOUT_SECONDS,
                             detector=None):
    """把分页打印 HTML 文件转换为 PDF（同目录同名 .pdf），返回 PDF 路径。"""
    chromium = (detector or detect_chromium)()
    if not chromium:
        raise PdfConversionError(
            'Chromium 不可用，无法生成 PDF（请在部署环境中安装 chromium 与中文字体）')
    out_path = os.path.join(out_dir, 'native-ledger.pdf')
    command = [
        chromium,
        '--headless=new',
        '--no-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        '--disable-extensions',
        '--no-pdf-header-footer',
        '--print-to-pdf=%s' % out_path,
        'file://%s' % html_path,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise PdfConversionError('PDF 转换超时（%d 秒），请稍后重试' % timeout)
    if result.returncode != 0 or not os.path.isfile(out_path) \
            or os.path.getsize(out_path) == 0:
        raise PdfConversionError(
            'PDF 转换失败（Chromium 退出码 %s），请检查部署环境字体与 Chromium 版本'
            % result.returncode)
    return out_path


def export_ledger_pdf(version, values):
    """由版本快照 + 填写值生成 PDF 字节（临时文件转换，结束自动清理）。"""
    snapshot = version.get_snapshot()
    if not snapshot:
        raise PdfConversionError('模板版本快照缺失，无法生成 PDF')
    paper = version.get_paper()
    html, _info = build_print_html(
        snapshot, version.get_bindings(), values, paper,
        meta={'template_name': version.template_name_snapshot})
    with tempfile.TemporaryDirectory(prefix='native_pdf_') as tmp_dir:
        html_path = os.path.join(tmp_dir, 'print.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        pdf_path = convert_html_file_to_pdf(html_path, tmp_dir)
        with open(pdf_path, 'rb') as f:
            return f.read()


# ======================================================================
# 打印 HTML 构建（分页规范移植自样板 print.js）
# ======================================================================

def _sheet_of(snapshot):
    sheet_id = (snapshot.get('sheetOrder') or [None])[0]
    sheets = snapshot.get('sheets') or {}
    if sheet_id and sheet_id in sheets:
        return sheets[sheet_id]
    for value in sheets.values():
        return value
    return {}


def _row_height(sheet, row):
    data = sheet.get('rowData') or {}
    entry = data.get(row) or data.get(str(row)) or {}
    try:
        return float(entry.get('h', sheet.get('defaultRowHeight', 32)))
    except (TypeError, ValueError):
        return 32.0


def _col_width(sheet, col):
    data = sheet.get('columnData') or {}
    entry = data.get(col) or data.get(str(col)) or {}
    try:
        return float(entry.get('w', sheet.get('defaultColumnWidth', 88)))
    except (TypeError, ValueError):
        return 88.0


def col_name(index):
    """0 起列索引 → A1 列字母。"""
    number = index + 1
    out = ''
    while number > 0:
        remainder = (number - 1) % 26
        out = chr(65 + remainder) + out
        number //= 26
    return out


def _style_of(snapshot, sheet, row, col):
    ref = _cell_entry(sheet, row, col).get('s')
    if ref is None:
        return {}
    if isinstance(ref, str):
        return (snapshot.get('styles') or {}).get(ref) or {}
    return ref if isinstance(ref, dict) else {}


def _cell_entry(sheet, row, col):
    """cellData 单元格（JSON 对象键为字符串，整数/字符串键双兼容）。"""
    cells = sheet.get('cellData') or {}
    row_data = cells.get(row) or cells.get(str(row)) or {}
    return row_data.get(col) or row_data.get(str(col)) or {}


def _parse_a1(range_str):
    """A1 单元格引用 → 0 起 (row, col)；非法返回 None。"""
    if not range_str:
        return None
    letters, digits = '', ''
    for ch in str(range_str).strip().upper():
        if ch.isalpha():
            letters += ch
        elif ch.isdigit():
            digits += ch
        else:
            return None
    if not letters or not digits or len(letters) > 3:
        return None
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    try:
        row = int(digits)
    except ValueError:
        return None
    if row < 1:
        return None
    return row - 1, col - 1


def _content_extent(sheet, bindings=None):
    """打印行/列范围：cellData、合并区与绑定单元格覆盖到的最大行/列。

    绑定单元格必须计入范围：填写格可能没有任何底表静态内容
    （空格子绑定），不参与范围会被整列/整行裁掉。
    """
    max_row = max_col = 0
    for row_key, cols in (sheet.get('cellData') or {}).items():
        try:
            row = int(row_key)
        except (TypeError, ValueError):
            continue
        max_row = max(max_row, row)
        for col_key in cols:
            try:
                max_col = max(max_col, int(col_key))
            except (TypeError, ValueError):
                continue
    for merge in sheet.get('mergeData') or []:
        max_row = max(max_row, int(merge.get('endRow', 0)))
        max_col = max(max_col, int(merge.get('endColumn', 0)))
    for binding in bindings or []:
        if not isinstance(binding, dict):
            continue
        parsed = _parse_a1(binding.get('range'))
        if parsed is None:
            continue
        max_row = max(max_row, parsed[0])
        max_col = max(max_col, parsed[1])
    return max_row, max_col


def _paper_geometry(paper):
    """纸张几何：页面宽高（mm）、内容宽高（px）、缩放系数、警告列表。"""
    dims = _paper_size_mm(paper)
    margins = paper.get('margins') or {}
    page_w, page_h = dims
    if paper.get('orientation') == 'landscape':
        page_w, page_h = page_h, page_w
    margin = {side: float(margins.get(side, 10)) for side in ('top', 'right', 'bottom', 'left')}
    content_w = (page_w - margin['left'] - margin['right']) * MM_TO_PX
    content_h = (page_h - margin['top'] - margin['bottom']) * MM_TO_PX
    return page_w, page_h, margin, content_w, content_h


def _paper_size_mm(paper):
    from apps.equipment_lifecycle.native_models import NATIVE_PAPER_SIZES
    size = NATIVE_PAPER_SIZES.get(paper.get('size') or 'A4')
    if not size:
        size = NATIVE_PAPER_SIZES['A4']
    return size


def _compute_scale(sheet, content_w, paper, max_col):
    raw_w = sum(_col_width(sheet, c) for c in range(max_col + 1))
    scale = min(1.0, content_w / raw_w) if paper.get('fitToWidth') and raw_w > 0 else 1.0
    return raw_w, scale


def _paginate(sheet, merges, header_rows, last_row, content_h, scale):
    """按行高分页；分页点避开纵向合并（跨页合并的起始行前断页）。

    返回 (pages, warnings)；每个 page 为该页打印行号列表（含重复表头）。
    """
    pages, warnings = [], []
    available = content_h - FOOTER_HEIGHT_PX
    first_content = (header_rows[-1] + 1) if header_rows else 0
    cursor = first_content
    while cursor <= last_row:
        page_rows = list(header_rows)
        used = sum(_row_height(sheet, r) * scale for r in header_rows)
        r = cursor
        while r <= last_row:
            height = _row_height(sheet, r) * scale
            if used + height > available and len(page_rows) > len(header_rows):
                break
            page_rows.append(r)
            used += height
            r += 1
        if len(page_rows) == len(header_rows):
            # 单行超出整页可用高度：强制放行该行，避免死循环
            page_rows.append(cursor)
            r = cursor + 1
            warnings.append('第 %d 页存在超高行，内容可能溢出页面。' % (len(pages) + 1))
        elif r <= last_row:
            crossing = _crossing_merge(merges, r)
            if crossing is not None and crossing['startRow'] > cursor:
                # 分页点前移到合并区起始行之前（保证每页至少推进一行）
                kept = [x for x in page_rows
                        if cursor <= x < crossing['startRow']]
                page_rows = list(header_rows) + kept
                r = crossing['startRow']
                warnings.append('第 %d 页按行分页，分页点避开纵向合并区域。' % (len(pages) + 1))
            elif crossing is not None:
                warnings.append('第 %d 页存在超出整页高度的合并区域，跨页部分被切断。'
                                % (len(pages) + 1))
            else:
                warnings.append('第 %d 页按行分页。' % (len(pages) + 1))
        pages.append(page_rows)
        cursor = r
    if not pages:
        pages.append(list(header_rows))
    return pages, warnings


def _crossing_merge(merges, break_row):
    for merge in merges:
        if merge['startRow'] < break_row <= merge['endRow']:
            return merge
    return None


def _color_of(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get('rgb') or ''
    return ''


def _border_css(style):
    """按样式 bd 声明边框（未声明边不绘制，与编辑器所见一致）。"""
    bd = style.get('bd')
    if not isinstance(bd, dict):
        return ''
    sides = {'t': 'top', 'r': 'right', 'b': 'bottom', 'l': 'left'}
    pieces = []
    for short, side in sides.items():
        border = bd.get(short)
        if not isinstance(border, dict) or not border.get('s'):
            continue
        rgb = _color_of(border.get('cl')) or '#64748b'
        pieces.append('border-%s:0.5px solid %s' % (side, escape(rgb)))
    return ';'.join(pieces)


def _cell_css(style, scale):
    fs = float(style.get('fs') or 9) * 1.3333 * scale
    align = {1: 'left', 3: 'right'}.get(style.get('ht'), 'center')
    valign = {1: 'top', 3: 'bottom'}.get(style.get('vt'), 'middle')
    pieces = [
        'font-size:%.2fpx' % fs,
        'font-family:%s' % escape(str(style.get('ff') or 'Microsoft YaHei')
                                  + ', "Noto Sans CJK SC", "SimSun", sans-serif'),
        'color:%s' % (_color_of(style.get('cl')) or '#111827'),
        'background:%s' % (_color_of(style.get('bg')) or 'transparent'),
        'text-align:%s' % align,
        'vertical-align:%s' % valign,
        'white-space:pre-wrap',
        'word-break:break-word',
        'overflow:hidden',
        'line-height:1.25',
        'padding:2px 3px',
        'box-sizing:border-box',
    ]
    if style.get('bl') == 1:
        pieces.append('font-weight:700')
    if style.get('it') == 1:
        pieces.append('font-style:italic')
    border = _border_css(style)
    if border:
        pieces.append(border)
    return ';'.join(pieces)


def _merge_cover(merges, rows_set):
    """页内被合并覆盖的 (row, col) 集合（跨页合并不参与覆盖）。"""
    covered = set()
    for merge in merges:
        if merge['startRow'] not in rows_set or merge['endRow'] not in rows_set:
            continue
        for r in range(merge['startRow'], merge['endRow'] + 1):
            for c in range(merge['startColumn'], merge['endColumn'] + 1):
                if r != merge['startRow'] or c != merge['startColumn']:
                    covered.add((r, c))
    return covered


def _merge_span(merges, row, col, rows_set):
    """(row, col) 作为合并锚点时的 (rowspan, colspan)；非锚点返回 (1, 1)。"""
    for merge in merges:
        if merge['startRow'] == row and merge['startColumn'] == col \
                and merge['endRow'] in rows_set:
            return (merge['endRow'] - merge['startRow'] + 1,
                    merge['endColumn'] - merge['startColumn'] + 1)
    return 1, 1


def _build_table(snapshot, sheet, page_rows, merges, binding_by_range, values, scale,
                 max_col):
    """单页表格 HTML（合并单元格 rowspan/colspan，跨页合并不拆行）。"""
    widths = [_col_width(sheet, c) * scale for c in range(max_col + 1)]
    total_w = sum(widths)
    rows_set = set(page_rows)
    covered = _merge_cover(merges, rows_set)
    col_group = ''.join('<col style="width:%.2fpx">' % w for w in widths)
    body = []
    for r in page_rows:
        cells = []
        for c in range(max_col + 1):
            if (r, c) in covered:
                continue
            row_span, col_span = _merge_span(merges, r, c, rows_set)
            value = _cell_value(sheet, r, c, binding_by_range, values)
            text = escape('' if value is None else str(value)) or '&nbsp;'
            style = _cell_css(_style_of(snapshot, sheet, r, c), scale)
            cells.append(
                '<td rowspan="%d" colspan="%d" style="%s">%s</td>'
                % (row_span, col_span, style, text))
        body.append('<tr style="height:%.2fpx">%s</tr>'
                    % (_row_height(sheet, r) * scale, ''.join(cells)))
    return ('<table class="ledger-table" style="width:%.2fpx">'
            '<colgroup>%s</colgroup><tbody>%s</tbody></table>'
            % (total_w, col_group, ''.join(body)))


def _cell_value(sheet, row, col, binding_by_range, values):
    binding = binding_by_range.get('%s%d' % (col_name(col), row + 1))
    if binding is not None and binding['key'] in values:
        return values[binding['key']]
    return _cell_entry(sheet, row, col).get('v', '')


def _page_css(page_w, page_h, margin, preview_zoom=1.0):
    return """
    @page { size: %(w)smm %(h)smm; margin: 0; }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: #fff; }
    body { font-family: "Microsoft YaHei", "Noto Sans CJK SC", "SimSun", sans-serif; color: #111827; }
    .page-sheet { position: relative; background: #fff; overflow: hidden; break-after: page; page-break-after: always;
      width:%(w)smm; height:%(h)smm; padding:%(mt)smm %(mr)smm %(mb)smm %(ml)smm; }
    .page-sheet:last-child { break-after: auto; page-break-after: auto; }
    .page-inner { width: 100%%; height: 100%%; display: flex; flex-direction: column; }
    .ledger-caption { display: none; justify-content: space-between; align-items: baseline; gap: 8px;
      margin: 0 0 2mm; color: #334155; font-size: 8pt; font-weight: 600; }
    .page-sheet:not([data-page="1"]) .ledger-caption { display: flex; }
    .record-code { color: #1d4ed8; font-size: 8pt; }
    .ledger-table { border-collapse: collapse; table-layout: fixed; margin: 0 auto; }
    .ledger-table td { border: none; padding: 2px 3px; overflow: hidden; }
    .page-spacer { flex: 1 1 auto; }
    .page-foot { display: flex; justify-content: space-between; gap: 8px; padding-top: 2mm;
      color: #64748b; font-size: 7.5pt; border-top: 0.5px solid #cbd5e1; }
    @media print { html, body { background: #fff; zoom: 1 !important; } }
    @media screen { body { zoom: %(zoom)s; } .page-sheet { box-shadow: 0 2px 10px rgba(15,23,42,.18); } }
    """ % {
        'w': _fmt_mm(page_w), 'h': _fmt_mm(page_h),
        'mt': _fmt_mm(margin['top']), 'mr': _fmt_mm(margin['right']),
        'mb': _fmt_mm(margin['bottom']), 'ml': _fmt_mm(margin['left']),
        'zoom': preview_zoom,
    }


def _fmt_mm(value):
    return ('%.2f' % float(value)).rstrip('0').rstrip('.')


def _merge_specs(sheet):
    """mergeData → 规范化合并区列表（整数行列）。"""
    return [
        {'startRow': int(m['startRow']), 'startColumn': int(m['startColumn']),
         'endRow': int(m['endRow']), 'endColumn': int(m['endColumn'])}
        for m in (sheet.get('mergeData') or [])
    ]


def _layout_warnings(warnings, scale, paper, raw_w, content_w, cross_page):
    """版式警告（缩放过低/超宽裁切/纵向合并跨页），就地追加。"""
    if scale < LOW_SCALE_WARN:
        warnings.append('当前纸张下自动缩放为 %.0f%%，已低于 %.0f%% 的可读性参考线。'
                        % (scale * 100, LOW_SCALE_WARN * 100))
    if not paper.get('fitToWidth') and raw_w > content_w:
        warnings.append('表格实际宽度 %dpx，超出可打印宽度 %dpx，右侧会被裁切。'
                        % (round(raw_w), round(content_w)))
    if cross_page:
        warnings.append('%d 处纵向合并被分页切断，需要调整版式或纸张。' % len(cross_page))


def _page_section(index, total, table, caption, template_name, generated_at):
    """单页 section HTML（首页无续页页眉）。"""
    head = ''
    if index > 0:
        head = ('<div class="ledger-caption"><span>%s</span>'
                '<span class="record-code">%s</span></div>' % caption)
    return (
        '<section class="page-sheet" data-page="%d"><div class="page-inner">'
        '%s%s<div class="page-spacer"></div>'
        '<div class="page-foot"><span>制表：%s</span>'
        '<span>第 %d 页 / 共 %d 页 · %s</span></div>'
        '</div></section>'
        % (index + 1, head, table, escape(template_name),
           index + 1, total, escape(generated_at)))


def build_print_html(snapshot, bindings, values, paper, meta=None):
    """由快照/绑定/填写值/纸张构建分页打印 HTML。

    返回 (html, info)；info = {page_count, scale, warnings, cross_page_merges}。
    meta: {template_name, record_code}（页脚与续页页眉展示）。
    """
    meta = meta or {}
    paper = paper or {}
    sheet = _sheet_of(snapshot)
    bindings = bindings or []
    max_row, max_col = _content_extent(sheet, bindings)
    if max_col < 0:
        raise PdfConversionError('模板快照没有可打印内容')
    page_w, page_h, margin, content_w, content_h = _paper_geometry(paper)
    raw_w, scale = _compute_scale(sheet, content_w, paper, max_col)
    merges = _merge_specs(sheet)
    pages, warnings = _paginate(
        sheet, merges, _frozen_header_rows(sheet), max_row, content_h, scale)
    cross_page = _cross_page_merges(pages, merges)
    _layout_warnings(warnings, scale, paper, raw_w, content_w, cross_page)
    binding_by_range = {b.get('range', ''): b for b in bindings
                        if isinstance(b, dict)}
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    template_name = str(meta.get('template_name') or '维护台账')
    record_code = str(meta.get('record_code') or '')
    css = _page_css(page_w, page_h, margin)
    caption = (escape(template_name), escape(record_code))
    sections = [
        _page_section(index, len(pages),
                      _build_table(snapshot, sheet, page_rows, merges,
                                   binding_by_range, values, scale, max_col),
                      caption, template_name, generated_at)
        for index, page_rows in enumerate(pages)
    ]
    title = escape(record_code or template_name or '维护台账打印预览')
    html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>%s</title><style>%s</style></head>'
            '<body><main class="pages">%s</main></body></html>'
            % (title, css, ''.join(sections)))
    info = {
        'page_count': len(pages),
        'scale': scale,
        'warnings': warnings,
        'cross_page_merges': cross_page,
    }
    return html, info


def _frozen_header_rows(sheet):
    freeze = sheet.get('freeze') or {}
    try:
        y_split = int(freeze.get('ySplit') or 0)
    except (TypeError, ValueError):
        y_split = 0
    return list(range(min(max(y_split, 0), 10)))


def _cross_page_merges(pages, merges):
    result = []
    for index, page_rows in enumerate(pages):
        rows = set(page_rows)
        for merge in merges:
            has_start = merge['startRow'] in rows
            has_end = merge['endRow'] in rows
            if has_start != has_end:
                result.append({
                    'page': index + 1,
                    'range': '%s%d:%s%d' % (
                        col_name(merge['startColumn']), merge['startRow'] + 1,
                        col_name(merge['endColumn']), merge['endRow'] + 1),
                })
    return result
