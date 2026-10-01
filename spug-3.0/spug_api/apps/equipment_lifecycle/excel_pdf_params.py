# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 台账模板级 PDF 打印参数（2026-09-30；2026-10-01 扩展）。

参数随模板草稿保存在 draft_layout JSON 的 pdf_params 键内（零迁移），
发布时随版本快照固定，历史台账导出继续使用创建时版本的参数；导出接口
可显式传入覆盖参数（仅当次导出生效，不改模板）。

- default_pdf_params：上传解析时按打印模式播种缺省值——源文件带显式
  页面设置（纸张/方向/缩放任一）播种为「原始 Excel 打印设置」模式，
  完全尊重上传文件的打印版式；无任何打印设置播种为「A4 自动适配」
  模式（按内容宽度自动选纵向/横向，宽度适合 1 页，高度自动分页）；
- validate_pdf_params：全量校验并归一化（未知键剔除、边界与格式检查），
  非法直接抛 ExcelLayoutError；preset 支持 original（原始打印设置）/
  a4_auto（A4 自动适配）/ single_page（单页表单）/ custom（逐项自定义，
  历史快照缺省值，行为与 2026-09-30 版本一致）；
- apply_pdf_params：把参数写入工作簿打印设置（就地修改），只作用于 PDF
  转换副本——导出 Excel 与服务端源文件字节不动。preset=original 时整体
  跳过（源文件页面设置原样交给 LibreOffice）；orientation=auto 逐工作表
  按内容宽度解析实际方向（纵向放不下则横向）；页面设置（纸张/方向/
  边距/缩放/页序/水平垂直居中）作用于全部工作表，重复表头行、手动
  分页行与打印区域只作用于绑定主工作表（多工作表文件的其余表结构
  不可预知）；
- estimate_pdf_warnings：导出前版式预检（横向溢出/单页缩放过小/空白
  工作表/分页行越界/打印区域越界/必填未填），只依据服务端保存的布局
  meta 与参数估算，给出中文提示，不阻断导出（阻断类问题由导出自身
  校验拦截）。

缩放换算说明：Excel 列宽字符单位近似 (chars*7+5) 像素（96dpi），像素转
厘米 = px/96*2.54；行高单位 pt，厘米 = pt/72*2.54；估算用于提示，非
精确排版。
"""
import copy
import re

from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.pagebreak import Break, RowBreak
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties

from apps.equipment_lifecycle.excel_template_services import (
    MAX_COLUMNS,
    MAX_ROWS,
    ExcelLayoutError,
)

# openpyxl paperSize 编号（与 Worksheet.PAPERSIZE_* 常量同值）
PAPER_SIZE_CODES = {
    'A4': 9, 'A3': 8, 'A5': 11, 'B4': 12, 'B5': 13,
    'letter': 1, 'legal': 5,
}
# 纸张物理尺寸 mm（纵向）：(宽, 高)
PAPER_SIZE_MM = {
    'A4': (210, 297), 'A3': (297, 420), 'A5': (148, 210),
    'B4': (257, 364), 'B5': (176, 250),
    'letter': (216, 279), 'legal': (216, 356),
}
PAGE_ORDER_CODES = {
    'down_then_over': 'downThenOver',
    'over_then_down': 'overThenDown',
}
SCALE_MODES = ('actual', 'percent', 'fit_width', 'fit_page')
# auto = 按内容宽度逐工作表解析（纵向放不下自动转横向）
ORIENTATIONS = ('auto', 'portrait', 'landscape')
# 打印模式：原始 Excel 打印设置 / A4 自动适配 / 单页表单 / 自定义
PRESETS = ('original', 'a4_auto', 'single_page', 'custom')
MARGIN_KEYS = ('top', 'bottom', 'left', 'right', 'header', 'footer')
MAX_ROW_BREAKS = 100
MAX_SCALE_PERCENT = 400
MIN_SCALE_PERCENT = 10

DEFAULT_PDF_PARAMS = {
    'preset': 'custom',
    'paper_size': 'A4',
    'orientation': 'portrait',
    'margins': {
        'top': 1.91, 'bottom': 1.91, 'left': 1.78, 'right': 1.78,
        'header': 0.76, 'footer': 0.76,
    },
    'scale_mode': 'fit_width',
    'scale_percent': 100,
    'repeat_header_rows': '',
    'row_breaks': [],
    'page_order': 'down_then_over',
    'print_area': '',
    'horizontal_centered': False,
    'vertical_centered': False,
}

_REPEAT_ROWS_PATTERN = re.compile(r'^(\d+):(\d+)$')
_PRINT_AREA_PART_PATTERN = re.compile(
    r'^\$?([A-Z]{1,3})\$?([1-9]\d*):\$?([A-Z]{1,3})\$?([1-9]\d*)$')
# 列宽字符单位近似像素（Calibri 11 / 96dpi），用于宽度估算
_DEFAULT_COLUMN_CHARS = 8.43
# 未显式设置行高时的缺省行高（pt），用于单页缩放估算
_DEFAULT_ROW_HEIGHT_PT = 14.25
_CM_PER_PIXEL = 2.54 / 96
_CM_PER_PT = 2.54 / 72
# 宽度比较容差（cm），避免边界值误报
_WIDTH_EPSILON_CM = 0.3
# 单页适配缩放低于该比例视为「字号可能过小」
_MIN_READABLE_SCALE = 0.5


def _fail(message):
    raise ExcelLayoutError(message)


def _in_to_cm(value):
    return round(value * 2.54, 2) if value is not None else None


def _char_width_to_cm(chars):
    return (chars * 7 + 5) * _CM_PER_PIXEL


def _has_real_print_config(sheet, setup):
    """源文件是否存在用户真实配置过的打印版式（fit/缩放/打印区域）。

    纸张编号与方向是 WPS/Excel 保存时总会序列化的样板值，不作为
    配置过打印的证据；fit 缩放、百分比缩放或打印区域才是。
    """
    return bool(setup.fitToWidth is not None or setup.fitToHeight is not None
                or setup.scale is not None or sheet.print_area)


def _seed_original_params(params, sheet):
    """original 模式播种：把源文件页面设置抄录为展示字段。"""
    setup = sheet.page_setup
    orientation = str(setup.orientation or '').lower()
    params['orientation'] = orientation \
        if orientation in ('portrait', 'landscape') else 'portrait'
    for key, code in PAPER_SIZE_CODES.items():
        if setup.paperSize is not None and int(setup.paperSize) == code:
            params['paper_size'] = key
            break
    params['scale_mode'], params['scale_percent'] = _scale_info(setup)


def _seed_file_margins(params, sheet):
    """页边距为物理值：从源文件播种，缺省回落内置值。"""
    margins = sheet.page_margins
    if margins is None:
        return
    converted = {key: _in_to_cm(getattr(margins, key)) for key in MARGIN_KEYS}
    params['margins'] = {key: value if value is not None else
                         DEFAULT_PDF_PARAMS['margins'][key]
                         for key, value in converted.items()}


def default_pdf_params(workbook):
    """按源文件打印设置播种模板级 PDF 参数（深拷贝，可独立修改）。

    「原始 Excel 打印设置」只在源文件存在真实打印配置时播种：fit 缩放
    （fitToWidth/fitToHeight）、百分比缩放或打印区域任一存在——这些是
    用户在 Excel/WPS 中实际调整过打印版式的标志。仅有样板值（纸张/
    方向）的文件播种为「A4 自动适配」（A4 + 方向自动 + 宽度适合 1 页
    + 高度自动分页），避免样板 A4 无缩放导致宽表横向溢出分页。
    """
    params = copy.deepcopy(DEFAULT_PDF_PARAMS)
    params['preset'] = 'a4_auto'
    params['orientation'] = 'auto'
    sheet = workbook.active
    if sheet is None:
        return params
    if _has_real_print_config(sheet, sheet.page_setup):
        params['preset'] = 'original'
        _seed_original_params(params, sheet)
    _seed_file_margins(params, sheet)
    return params


def _scale_info(setup):
    """由打印设置推导缩放方式（fit 优先；无设置回落 fit_width）。"""
    if setup.fitToWidth is not None or setup.fitToHeight is not None:
        fit_height = setup.fitToHeight or 0
        return ('fit_page' if fit_height > 0 else 'fit_width'), 100
    if setup.scale is not None:
        return 'percent', max(MIN_SCALE_PERCENT,
                              min(MAX_SCALE_PERCENT, int(setup.scale)))
    return 'fit_width', 100


def validate_pdf_params(raw, max_row=None, max_column=None):
    """校验并归一化 PDF 参数；非法抛 ExcelLayoutError，返回完整参数 dict。

    max_row/max_column 为主工作表尺寸（打印区域越界校验；缺失则不校验）。
    """
    if raw is None:
        return copy.deepcopy(DEFAULT_PDF_PARAMS)
    if not isinstance(raw, dict):
        _fail('PDF 参数必须是对象')
    params = copy.deepcopy(DEFAULT_PDF_PARAMS)
    params['preset'] = _validate_choice(raw.get('preset'), PRESETS, '打印模式',
                                        params['preset'])
    params['paper_size'] = _validate_choice(raw.get('paper_size'),
                                            PAPER_SIZE_CODES, '纸张大小',
                                            params['paper_size'])
    params['orientation'] = _validate_choice(raw.get('orientation'),
                                             ORIENTATIONS, '纸张方向',
                                             params['orientation'])
    params['page_order'] = _validate_choice(raw.get('page_order'),
                                            PAGE_ORDER_CODES, '页面顺序',
                                            params['page_order'])
    params['margins'] = _validate_margins(raw.get('margins'))
    params['scale_mode'] = _validate_scale_mode(raw.get('scale_mode'))
    params['scale_percent'] = _validate_scale_percent(raw.get('scale_percent'))
    params['repeat_header_rows'] = _validate_repeat_rows(
        raw.get('repeat_header_rows'), max_row)
    params['row_breaks'] = _validate_row_breaks(raw.get('row_breaks'), max_row)
    params['print_area'] = _validate_print_area(
        raw.get('print_area'), max_row, max_column)
    params['horizontal_centered'] = _validate_bool(raw.get('horizontal_centered'))
    params['vertical_centered'] = _validate_bool(raw.get('vertical_centered'))
    return params


def _validate_choice(value, choices, label, default):
    if value is None:
        value = default
    if value not in choices:
        _fail('%s必须是：%s' % (label, '、'.join(str(k) for k in choices)))
    return value


def _validate_margins(raw):
    margins = copy.deepcopy(DEFAULT_PDF_PARAMS['margins'])
    if raw is None:
        return margins
    if not isinstance(raw, dict):
        _fail('页边距必须是对象')
    for key in MARGIN_KEYS:
        if raw.get(key) is None:
            continue
        value = _validate_number(raw.get(key), '页边距（%s）' % key)
        if not 0 <= value <= 10:
            _fail('页边距（%s）须在 0-10 厘米之间' % key)
        margins[key] = round(value, 2)
    return margins


def _validate_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail('%s必须是数字' % label)
    return float(value)


def _validate_scale_mode(value):
    if value is None:
        return DEFAULT_PDF_PARAMS['scale_mode']
    if value not in SCALE_MODES:
        _fail('缩放方式不支持：%s' % value)
    return value


def _validate_scale_percent(value):
    if value is None:
        return DEFAULT_PDF_PARAMS['scale_percent']
    percent = _validate_number(value, '缩放百分比')
    percent = int(round(percent))
    if not MIN_SCALE_PERCENT <= percent <= MAX_SCALE_PERCENT:
        _fail('缩放百分比须在 %d-%d 之间' % (MIN_SCALE_PERCENT, MAX_SCALE_PERCENT))
    return percent


def _validate_repeat_rows(raw, max_row):
    if raw is None or raw == '':
        return ''
    match = _REPEAT_ROWS_PATTERN.match(str(raw).strip())
    if not match:
        _fail('重复表头行格式必须是「起始行:结束行」，如 1:2')
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1 or start > end or end > MAX_ROWS:
        _fail('重复表头行行号不合法（1-%d 且起始行不大于结束行）' % MAX_ROWS)
    if max_row is not None and end > max_row:
        _fail('重复表头行 %d:%d 超出工作表行数（%d 行）' % (start, end, max_row))
    return '%d:%d' % (start, end)


def _validate_row_breaks(raw, max_row):
    if raw is None:
        return []
    if not isinstance(raw, list):
        _fail('手动分页行必须是行号列表')
    if len(raw) > MAX_ROW_BREAKS:
        _fail('手动分页行数量超过上限（%d）' % MAX_ROW_BREAKS)
    rows = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)) \
                or int(item) != item:
            _fail('手动分页行必须是整数行号')
        row = int(item)
        if row < 1 or row > MAX_ROWS:
            _fail('手动分页行 %d 超出范围（1-%d）' % (row, MAX_ROWS))
        if max_row is not None and row > max_row:
            _fail('手动分页行 %d 超出工作表行数（%d 行）' % (row, max_row))
        if row not in rows:
            rows.append(row)
    return sorted(rows)


def _validate_bool(raw):
    return bool(raw) if raw is not None else False


def _validate_print_area(raw, max_row, max_column):
    """打印区域：空串 = 保持源文件设置；否则 A1:E25 或逗号分隔多段。"""
    if raw is None:
        return ''
    text = str(raw).strip()
    if not text:
        return ''
    parts = []
    for part in text.split(','):
        plain = part.strip().upper().replace('$', '')
        if not plain:
            continue
        match = _PRINT_AREA_PART_PATTERN.match(plain)
        if not match:
            _fail('打印区域格式必须是「起始单元格:结束单元格」，如 A1:E25')
        min_col = column_index_from_string(match.group(1))
        min_row, max_col = int(match.group(2)), column_index_from_string(match.group(3))
        end_row = int(match.group(4))
        if min_col > max_col or min_row > end_row:
            _fail('打印区域 %s 的起止单元格颠倒' % plain)
        if max_row is not None and end_row > max_row:
            _fail('打印区域 %s 超出工作表行数（%d 行）' % (plain, max_row))
        if max_column is not None and max_col > max_column:
            _fail('打印区域 %s 超出工作表列数（%d 列）' % (plain, max_column))
        if end_row > MAX_ROWS or max_col > MAX_COLUMNS:
            _fail('打印区域 %s 超出支持范围（%d 行 × %d 列）'
                  % (plain, MAX_ROWS, MAX_COLUMNS))
        parts.append('%s%d:%s%d' % (get_column_letter(min_col), min_row,
                                    get_column_letter(max_col), end_row))
    return ','.join(parts)


def apply_pdf_params(workbook, pdf_params, sheet_name=None):
    """把模板级 PDF 参数写入工作簿打印设置（就地修改，仅用于转换副本）。

    preset='original'（原始 Excel 打印设置）时整体跳过：纸张/方向/边距/
    缩放/居中/分页全部沿用源文件自身页面设置。orientation='auto' 时逐
    工作表按内容宽度解析实际方向（纵向一页放不下则转横向）。
    """
    params = pdf_params or {}
    if params.get('preset') == 'original':
        return
    margins = params.get('margins') or DEFAULT_PDF_PARAMS['margins']
    for worksheet in workbook.worksheets:
        orientation = params.get('orientation') or 'portrait'
        if orientation == 'auto':
            orientation = _resolve_orientation(worksheet, params)
        setup = worksheet.page_setup
        setup.paperSize = PAPER_SIZE_CODES.get(params.get('paper_size'), 9)
        setup.orientation = orientation
        setup.pageOrder = PAGE_ORDER_CODES.get(
            params.get('page_order'), 'downThenOver')
        _apply_scale_setup(worksheet, params)
        worksheet.page_margins = PageMargins(
            top=_cm_to_inch(margins.get('top')),
            bottom=_cm_to_inch(margins.get('bottom')),
            left=_cm_to_inch(margins.get('left')),
            right=_cm_to_inch(margins.get('right')),
            header=_cm_to_inch(margins.get('header')),
            footer=_cm_to_inch(margins.get('footer')),
        )
        worksheet.print_options.horizontalCentered = bool(
            params.get('horizontal_centered'))
        worksheet.print_options.verticalCentered = bool(
            params.get('vertical_centered'))
        if sheet_name and worksheet.title == sheet_name:
            _apply_sheet_pagination(worksheet, params)


def _resolve_orientation(worksheet, params):
    """方向自动：内容宽度纵向一页放不下（含容差）则转横向。"""
    margins = params.get('margins') or DEFAULT_PDF_PARAMS['margins']
    size = PAPER_SIZE_MM.get(params.get('paper_size'), PAPER_SIZE_MM['A4'])
    portrait_width_cm = max(2.0, size[0] / 10.0
                            - float(margins.get('left') or 0)
                            - float(margins.get('right') or 0))
    content_cm = _worksheet_content_width_cm(worksheet)
    return 'landscape' if content_cm > portrait_width_cm + _WIDTH_EPSILON_CM \
        else 'portrait'


def _worksheet_content_width_cm(worksheet):
    """工作表内容总宽度估算（cm）：显式列宽 + 未设置列的缺省宽度。"""
    dimensions = worksheet.column_dimensions
    total = 0.0
    unspecified = 0
    for idx in range(1, worksheet.max_column + 1):
        letter = get_column_letter(idx)
        dim = dimensions.get(letter)
        width = dim.width if dim is not None else None
        if dim is not None and dim.hidden:
            continue
        if width is None:
            unspecified += 1
        else:
            total += _char_width_to_cm(width)
    return total + unspecified * _char_width_to_cm(_DEFAULT_COLUMN_CHARS)


def _cm_to_inch(value):
    try:
        return round(float(value) / 2.54, 4) if value is not None else None
    except (TypeError, ValueError):
        return None


def _apply_scale_setup(worksheet, params):
    """缩放方式：fit 模式启用 fitToPage，actual/percent 显式关闭 fit。"""
    setup = worksheet.page_setup
    mode = params.get('scale_mode') or DEFAULT_PDF_PARAMS['scale_mode']
    if mode in ('fit_width', 'fit_page'):
        worksheet.sheet_properties.pageSetUpPr = PageSetupProperties(
            fitToPage=True)
        setup.fitToWidth = 1
        setup.fitToHeight = 1 if mode == 'fit_page' else 0
        setup.scale = None
    else:
        worksheet.sheet_properties.pageSetUpPr = None
        setup.fitToWidth = None
        setup.fitToHeight = None
        setup.scale = (int(params.get('scale_percent') or 100)
                       if mode == 'percent' else None)


def _apply_sheet_pagination(worksheet, params):
    """主工作表分页细节：重复表头行（打印标题）+ 手动分页行 + 打印区域。

    打印区域仅在参数显式配置（非空串）时覆盖源文件设置；空串保持
    「净化后保留源文件打印区域」的既有行为。
    """
    titles = params.get('repeat_header_rows') or ''
    if titles:
        worksheet.print_title_rows = titles
    rows = params.get('row_breaks') or []
    if rows:
        worksheet.row_breaks = RowBreak()
        for row in rows:
            worksheet.row_breaks.append(Break(id=int(row)))
    print_area = params.get('print_area') or ''
    if print_area:
        worksheet.print_area = print_area


def estimate_pdf_warnings(meta, values=None, pdf_params=None):
    """导出前版式预检：返回中文提示列表（不阻断，阻断由导出自身校验）。"""
    params = copy.deepcopy(DEFAULT_PDF_PARAMS)
    params.update(pdf_params or {})
    warnings = []
    missing = [b['field_name'] for b in meta.get('field_bindings') or []
               if b.get('is_required') and not (values or {}).get(b['field_id'])]
    if missing:
        warnings.append('必填字段未填写：%s（导出会被拦截，请先填写）'
                        % '、'.join(missing))
    for sheet_meta in (meta.get('layout') or {}).get('sheets') or []:
        _estimate_sheet_warnings(sheet_meta, params, warnings)
    _estimate_pagination_warnings(meta, params, warnings)
    return warnings


def _resolve_meta_orientation(sheet_meta, params):
    """auto 方向按该工作表内容宽度解析（纵向一页放不下则横向）。"""
    orientation = params.get('orientation') or 'portrait'
    if orientation != 'auto':
        return orientation
    size = PAPER_SIZE_MM.get(params.get('paper_size'), PAPER_SIZE_MM['A4'])
    margins = params.get('margins') or {}
    portrait_cm = max(2.0, size[0] / 10.0
                      - float(margins.get('left') or 0)
                      - float(margins.get('right') or 0))
    content = _sheet_content_width_cm(sheet_meta)
    return 'landscape' if content > portrait_cm + _WIDTH_EPSILON_CM \
        else 'portrait'


def _estimate_sheet_warnings(sheet_meta, params, warnings):
    name = sheet_meta.get('name') or ''
    cells = sheet_meta.get('cells') or {}
    if not any(cell.get('v') not in (None, '') for cell in cells.values()):
        warnings.append('工作表「%s」没有可打印内容，可能产生空白页' % name)
        return
    content = _sheet_content_width_cm(sheet_meta)
    if content <= 0:
        return
    orientation = _resolve_meta_orientation(sheet_meta, params)
    printable = _printable_width_cm(params, orientation)
    mode = params.get('scale_mode') or 'fit_width'
    if mode in ('actual', 'percent'):
        factor = (params.get('scale_percent') or 100) / 100.0
        if content > printable * factor + _WIDTH_EPSILON_CM:
            warnings.append(
                '工作表「%s」内容宽度约 %.0fcm，超过一页可打印宽度 %.0fcm，'
                '导出 PDF 时将横向分页' % (name, content, printable * factor))
    elif mode == 'fit_page':
        scale = printable / content
        height = _sheet_content_height_cm(sheet_meta)
        printable_height = _printable_height_cm(params, orientation)
        if height > 0:
            scale = min(scale, printable_height / height)
        if scale < _MIN_READABLE_SCALE:
            warnings.append(
                '工作表「%s」按单页适配后缩放约 %d%%，打印字号可能过小'
                % (name, round(scale * 100)))
    else:
        scale = printable / content
        if scale < _MIN_READABLE_SCALE:
            warnings.append(
                '工作表「%s」内容较宽，按当前纸张适配后缩放约 %d%%，'
                '打印字号可能过小' % (name, round(scale * 100)))


def _sheet_content_width_cm(sheet_meta):
    """工作表内容总宽度估算（cm）：显式列宽 + 未设置列的缺省宽度。"""
    widths = sheet_meta.get('column_widths') or {}
    hidden = set(sheet_meta.get('hidden_columns') or [])
    total = sum(_char_width_to_cm(width) for letter, width in widths.items()
                if letter not in hidden)
    unspecified = (sheet_meta.get('max_column') or 0) - len(widths)
    if unspecified > 0:
        total += unspecified * _char_width_to_cm(_DEFAULT_COLUMN_CHARS)
    return total


def _sheet_content_height_cm(sheet_meta):
    """工作表内容总高度估算（cm）：显式行高（pt）+ 未设置行的缺省行高。"""
    heights = sheet_meta.get('row_heights') or {}
    hidden = set(sheet_meta.get('hidden_rows') or [])
    max_row = sheet_meta.get('max_row') or 0
    total = 0.0
    for idx in range(1, max_row + 1):
        if str(idx) in hidden:
            continue
        total += float(heights.get(str(idx)) or _DEFAULT_ROW_HEIGHT_PT)
    return total * _CM_PER_PT


def _printable_width_cm(params, orientation=None):
    """单页可打印宽度（cm）：纸张宽 - 左右边距（横向时交换宽高）。"""
    size = PAPER_SIZE_MM.get(params.get('paper_size'), PAPER_SIZE_MM['A4'])
    effective = orientation or params.get('orientation') or 'portrait'
    width_mm = size[1] if effective == 'landscape' else size[0]
    margins = params.get('margins') or {}
    return max(2.0, width_mm / 10.0
               - float(margins.get('left') or 0) - float(margins.get('right') or 0))


def _printable_height_cm(params, orientation=None):
    """单页可打印高度（cm）：纸张高 - 上下边距（横向时交换宽高）。"""
    size = PAPER_SIZE_MM.get(params.get('paper_size'), PAPER_SIZE_MM['A4'])
    effective = orientation or params.get('orientation') or 'portrait'
    height_mm = size[0] if effective == 'landscape' else size[1]
    margins = params.get('margins') or {}
    return max(2.0, height_mm / 10.0
               - float(margins.get('top') or 0) - float(margins.get('bottom') or 0))


def _check_print_area_bounds(active, params, warnings):
    """打印区域越界检查（历史快照防御；保存时已按主工作表校验）。"""
    area = params.get('print_area') or ''
    if not area:
        return
    active_name = active.get('name') or ''
    max_row = active.get('max_row') or 0
    max_column = active.get('max_column') or 0
    for part in [p for p in area.split(',') if p]:
        try:
            _min_col, _min_row, part_max_col, part_max_row = \
                range_boundaries(part)
        except Exception:
            continue
        if part_max_row > max_row or part_max_col > max_column:
            warnings.append('打印区域 %s 超出工作表「%s」范围（%d 行 × %d 列）'
                            % (part, active_name, max_row, max_column))


def _estimate_pagination_warnings(meta, params, warnings):
    """主工作表分页参数越界检查（历史快照防御，保存时已校验）。"""
    active_name = meta.get('sheet_name')
    active = next((s for s in (meta.get('layout') or {}).get('sheets') or []
                   if s.get('name') == active_name), None)
    if active is None:
        return
    max_row = active.get('max_row') or 0
    titles = params.get('repeat_header_rows') or ''
    match = _REPEAT_ROWS_PATTERN.match(titles)
    if match and int(match.group(2)) > max_row:
        warnings.append('重复表头行 %s 超出工作表「%s」行数（%d 行）'
                        % (titles, active_name, max_row))
    breaks = params.get('row_breaks') or []
    overflow = [str(row) for row in breaks if row > max_row]
    if overflow:
        warnings.append('手动分页行 %s 超出工作表「%s」行数（%d 行）'
                        % ('、'.join(overflow), active_name, max_row))
    _check_print_area_bounds(active, params, warnings)
