/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel/WPS 维护台账路线工具函数（2026-10-01 自模板导入验证原型
 * prototypeStore 迁出，实现保持不变）。
 *
 * 生成稳定 field_id（UUID v4）：field_id 不由单元格坐标充当，
 * 服务端按原样存储并在发布版本快照中保持稳定。
 *
 * 坐标解析与填写区几何（2026-10-14）：colLetter/parseCoord/coordName
 * 自 LayoutTable 下沉到本模块（供组件与几何计算共用，避免循环依赖，
 * LayoutTable 原样再导出保持既有导入路径）；填写区几何由布局 meta
 * 推导绑定格的纵向填写空间——只按行方向累计（行高 × 跨行数），
 * 横向合并不增加高度（与 Excel 中"行高决定单元格高度"一致），
 * 隐藏行计 0。供填写输入控件选择（LayoutTable）与单行高合并格的
 * 尺寸提示（ExcelTemplatePage）共用。
 *
 * 显示几何（2026-10-19）：「适合页宽/原始尺寸」缩放与纸张显示信息
 * 纯函数（fitPageWidthScale/defaultDisplayMode/paperViewInfo），缩放
 * 只作用于网页显示（乘在布局像素上，不进版本快照、不改变导出）。
 */

/** Excel 缺省行高（pt）；布局 meta 未记录行高时按此值。 */
export const DEFAULT_ROW_HEIGHT_PT = 14.25;
/** 纵向"足够高"阈值：≥2 行默认高度（28.5pt ≈ 38px）按多行填写。 */
export const TALL_FILL_THRESHOLD_PT = DEFAULT_ROW_HEIGHT_PT * 2;
/** Excel 缺省字号（pt）：网页与浏览器 PDF 打印共用（Excel 内置缺省 11pt），
 * 模板未显式设置字号时两端渲染一致。 */
export const DEFAULT_FONT_SIZE_PT = 11;

/** 96dpi 网页显示换算（仅网页显示用，不改变导出版式）。 */
export const PX_PER_MM = 96 / 25.4;
export const PX_PER_CM = 96 / 2.54;

/** 纸张尺寸（短边, 长边 mm；与 excel_pdf_params.PAPER_SIZE_MM 同源）。 */
const PAPER_SIZE_MM = {
  A4: [210, 297], A3: [297, 420], A5: [148, 210],
  B4: [250, 353], B5: [176, 250], letter: [216, 279], legal: [216, 356],
};

/** openpyxl paperSize 编号 → 名称（excel_pdf_params.PAPER_SIZE_CODES 同源）。 */
const PAPER_CODE_NAME = {9: 'A4', 8: 'A3', 11: 'A5', 12: 'B4', 13: 'B5', 1: 'letter', 5: 'legal'};

/** 显示模式缩放上下限：适合页宽过小不可读、过大失真，均夹取。 */
export const FIT_MIN_SCALE = 0.4;
export const FIT_MAX_SCALE = 2.5;

/** 「适合页宽」缩放值：可用宽度 / 表格自然宽度，夹取在上下限内。 */
export function fitPageWidthScale(naturalWidth, availableWidth,
                                  minScale = FIT_MIN_SCALE, maxScale = FIT_MAX_SCALE) {
  if (!naturalWidth || !availableWidth) return 1;
  return Math.min(maxScale, Math.max(minScale, availableWidth / naturalWidth));
}

/** 默认显示模式：宽表超出可用宽度选「适合页宽」，否则「原始尺寸」（100%）。 */
export function defaultDisplayMode(naturalWidth, availableWidth) {
  if (!naturalWidth || !availableWidth) return 'original';
  return naturalWidth > availableWidth ? 'fit_width' : 'original';
}

/** 常规页边距（cm，A4 文档默认值；打印参数缺页边距时的近似显示值）。 */
const NOMINAL_MARGINS_CM = {top: 1.91, bottom: 1.91, left: 1.78, right: 1.78};

/**
 * 纸张显示信息（仅网页显示参考，不影响模板与导出版式）。
 *
 * 版本打印参数 pdf_params（2026-09-30 起版本快照携带，含页边距）优先；
 * 缺失回退布局 meta 的工作表打印设置（无页边距，按常规页边距近似）。
 * 两处都无纸张信息返回 null（不画纸张边界）。
 * orientation=auto：按表格自然宽度是否超出纵向可打印宽度选横向，
 * 与后端 _resolve_orientation 的判定意图一致。
 * 返回 caption（纸张说明 + 横向溢出提示）、纸张像素尺寸、页边距像素。
 */
export function paperViewInfo(pdfParams, sheet, naturalWidthPx) {
  let paperName = null;
  let orientation = null;
  let margins = null;
  const params = pdfParams || {};
  if (params.paper_size && PAPER_SIZE_MM[params.paper_size]) {
    paperName = params.paper_size;
    orientation = params.orientation || 'portrait';
    margins = params.margins || null;
  } else {
    const print = (sheet && sheet.print) || {};
    const name = PAPER_CODE_NAME[Number(print.paper_size)];
    if (name) {
      paperName = name;
      orientation = print.orientation && print.orientation !== 'default'
        ? print.orientation : 'portrait';
    }
  }
  if (!paperName) return null;
  const shortMm = PAPER_SIZE_MM[paperName][0];
  const longMm = PAPER_SIZE_MM[paperName][1];
  let landscape = orientation === 'landscape';
  if (!landscape && orientation === 'auto') {
    const printablePortraitPx = (shortMm - (NOMINAL_MARGINS_CM.left + NOMINAL_MARGINS_CM.right) * 10)
      * PX_PER_MM;
    landscape = naturalWidthPx > printablePortraitPx;
  }
  const m = {...NOMINAL_MARGINS_CM, ...(margins || {})};
  const pageWidthMm = landscape ? longMm : shortMm;
  const pageHeightMm = landscape ? shortMm : longMm;
  const printableWidthPx = Math.round(
    pageWidthMm * PX_PER_MM - (Number(m.left) + Number(m.right)) * PX_PER_CM);
  const printableHeightPx = Math.round(
    pageHeightMm * PX_PER_MM - (Number(m.top) + Number(m.bottom)) * PX_PER_CM);
  const overflow = naturalWidthPx > printableWidthPx;
  const caption = `纸张：${paperName} · ${landscape ? '横向' : '纵向'}`
    + (overflow ? ' · 表格宽度超出可打印区域，导出打印时将横向分页' : '');
  return {
    paperName, landscape, caption, overflow,
    widthPx: Math.round(pageWidthMm * PX_PER_MM),
    heightPx: Math.round(pageHeightMm * PX_PER_MM),
    marginLeftPx: Math.round(Number(m.left) * PX_PER_CM),
    marginRightPx: Math.round(Number(m.right) * PX_PER_CM),
    marginTopPx: Math.round(Number(m.top) * PX_PER_CM),
    marginBottomPx: Math.round(Number(m.bottom) * PX_PER_CM),
    printableWidthPx,
    printableHeightPx,
  };
}

/**
 * 统一打印计划的网页视图信息（2026-10-21）。
 *
 * print_plan 是后端 excel_print_layout 计算的权威分页计划（网页与浏览器
 * PDF 共用，随版本快照下发），本函数只做像素换算与展示封装：纸张尺寸、
 * 页边距（含下边距——页高计算必须包含底部留白）、缩放倍率、分页参考线
 * （行/列断点索引，前端按布局行高列宽累计成像素）与计划页数/告警。
 * print_plan 缺失返回 null（调用方回落 paperViewInfo 近似显示）。
 */
export function printPlanViewInfo(plan, sheetName) {
  if (!plan || !plan.plan_version || !plan.sheets) return null;
  const sheet = plan.sheets[sheetName] || Object.values(plan.sheets)[0];
  if (!sheet) return null;
  const paper = plan.paper || {};
  const margins = plan.margins_mm || {};
  const landscape = paper.orientation === 'landscape';
  const widthPx = Math.round((paper.width_mm || 210) * PX_PER_MM);
  const heightPx = Math.round((paper.height_mm || 297) * PX_PER_MM);
  // 页边距（mm）→ 像素：print_plan 的边距单位是毫米（与 PAPER_SIZE_MM 同源）
  const marginLeftPx = Math.round((margins.left || 0) * PX_PER_MM);
  const marginRightPx = Math.round((margins.right || 0) * PX_PER_MM);
  const marginTopPx = Math.round((margins.top || 0) * PX_PER_MM);
  const marginBottomPx = Math.round((margins.bottom || 0) * PX_PER_MM);
  const printableWidthPx = Math.max(0, widthPx - marginLeftPx - marginRightPx);
  const printableHeightPx = Math.max(0, heightPx - marginTopPx - marginBottomPx);
  const overflow = (sheet.col_breaks || []).length > 0;
  const caption = `纸张：${paper.name || 'A4'} · ${landscape ? '横向' : '纵向'}`
    + (plan.page_count ? ` · 共 ${plan.page_count} 页` : '')
    + (overflow ? ' · 表格宽度超出可打印区域，导出时将横向分页' : '');
  return {
    paperName: paper.name || 'A4',
    landscape,
    caption,
    overflow,
    widthPx,
    heightPx,
    marginLeftPx,
    marginRightPx,
    marginTopPx,
    marginBottomPx,
    printableWidthPx,
    printableHeightPx,
    scale: sheet.scale || 1,
    rowBreaks: sheet.row_breaks || [],
    colBreaks: sheet.col_breaks || [],
    pageCount: sheet.page_count || 0,
    horizontalCentered: !!plan.horizontal_centered,
    verticalCentered: !!plan.vertical_centered,
    warnings: plan.warnings || [],
  };
}

/** 行高像素（与 LayoutTable 渲染同一公式：Math.round(pt*4/3)，隐藏行 0）。 */
function _rowDisplayPx(sheet, row) {
  const height = (sheet.row_heights || {})[String(row)];
  if ((sheet.hidden_rows || []).indexOf(String(row)) !== -1) return 0;
  return Math.round((height === undefined || height === null
    ? DEFAULT_ROW_HEIGHT_PT : Number(height)) * 4 / 3);
}

/** 列宽像素（与 LayoutTable 渲染同一公式：Math.round(chars*7+5)，隐藏列 0）。 */
function _colDisplayPx(sheet, col) {
  const letter = colLetter(col);
  if ((sheet.hidden_columns || []).indexOf(letter) !== -1) return 0;
  const width = (sheet.column_widths || {})[letter];
  return Math.round((width || 8.43) * 7 + 5);
}

/**
 * 分页参考线像素位置（相对表格原点）：后端计划给出每页起始行/列索引，
 * 前端按布局行列尺寸累计出参考线应在的偏移（与 DOM 累计一致）。
 * 返回 [{row, offsetPx}] / [{col, offsetPx}]。
 */
export function rowGuideOffsets(sheet, breakRows) {
  const list = [];
  let acc = 0;
  for (let row = 1; row <= (sheet.max_row || 0); row++) {
    if ((breakRows || []).indexOf(row) !== -1) list.push({row, offsetPx: acc});
    acc += _rowDisplayPx(sheet, row);
  }
  return list;
}

export function colGuideOffsets(sheet, breakCols) {
  const list = [];
  let acc = 0;
  for (let col = 1; col <= (sheet.max_column || 0); col++) {
    if ((breakCols || []).indexOf(col) !== -1) list.push({col, offsetPx: acc});
    acc += _colDisplayPx(sheet, col);
  }
  return list;
}

/**
 * 填写工作区的纸张视图模型（FillWorkspace useMemo 的纯函数化）：
 * print_plan 优先，缺失回落 paperViewInfo 近似；在纸张基础信息上叠加：
 * - 打印缩放层：表格在纸张内先乘 plan.scale（与浏览器 PDF 同源，保证
 *   「原始尺寸」模式下表格与纸张的比例 = 打印真实比例），参考线偏移
 *   同步缩放到同一坐标系；
 * - tableOffsetX/Y：horizontal/vertical_centered 时表格在可打印区内的
 *   居中偏移（与打印 HTML 的居中偏移同一算法）；
 * - totalWidthPx/totalHeightPx：纸张卡片总尺寸（border-box：含页边距
 *   padding 与 1px 边框）——页宽与缩放后表格 + 左右边距取大（宽表超出
 *   页宽时保持可视可填写，参考线提示导出时的横向分块）；高度为整页
 *   倍数（含下边距），内容更高时向下延展整页。
 * store 只取 version|draft 与 activeSheet（便于 useMemo 依赖收敛）：
 * version（台账填写）优先，缺失回落 draft（模板编辑，2026-10-21 共用）。
 */
/** 纸张卡片边框（上下/左右各 1px，计入总尺寸）。 */
const PAPER_BORDER_PX = 2;

export function paperViewModel(store, sheet, naturalSize) {
  if (!sheet) return null;
  // 计划/参数来源：台账填写取版本快照（version.print_plan/pdf_params），
  // 模板编辑取草稿（draft.print_plan/pdf_params，2026-10-21 统一观感），
  // 两者字段同构
  const source = store.version || store.draft || {};
  const base = source.print_plan
    ? printPlanViewInfo(source.print_plan, store.activeSheet)
    : paperViewInfo(source.pdf_params || {}, sheet, naturalSize.width);
  if (!base) return null;
  const printScale = base.scale || 1;
  const scaledTableW = Math.round(naturalSize.width * printScale * 100) / 100;
  const scaledTableH = Math.round(naturalSize.height * printScale * 100) / 100;
  const rowGuides = base.rowBreaks && base.rowBreaks.length
    ? rowGuideOffsets(sheet, base.rowBreaks)
      .map(g => ({row: g.row, offsetPx: Math.round(g.offsetPx * printScale * 100) / 100}))
    : [];
  const colGuides = base.colBreaks && base.colBreaks.length
    ? colGuideOffsets(sheet, base.colBreaks)
      .map(g => ({col: g.col, offsetPx: Math.round(g.offsetPx * printScale * 100) / 100}))
    : [];
  const contentWidth = naturalSize.width
    ? base.marginLeftPx + scaledTableW + base.marginRightPx + PAPER_BORDER_PX : 0;
  const totalWidthPx = Math.max(base.widthPx, contentWidth);
  const contentHeight = base.marginTopPx + scaledTableH + base.marginBottomPx
    + PAPER_BORDER_PX;
  const pages = Math.max(1, Math.ceil(contentHeight / base.heightPx));
  const totalHeightPx = Math.max(base.heightPx, pages * base.heightPx);
  const tableOffsetX = base.horizontalCentered
    ? Math.max(0, Math.round((base.printableWidthPx - scaledTableW) / 2)) : 0;
  const tableOffsetY = base.verticalCentered
    ? Math.max(0, Math.round((base.printableHeightPx - scaledTableH) / 2)) : 0;
  return {...base, printScale, rowGuides, colGuides, totalWidthPx,
    totalHeightPx, tableOffsetX, tableOffsetY};
}

export function colLetter(col) {
  let letters = '';
  while (col > 0) {
    const rest = (col - 1) % 26;
    letters = String.fromCharCode(65 + rest) + letters;
    col = Math.floor((col - 1) / 26);
  }
  return letters;
}

export function parseCoord(name) {
  const match = /^([A-Z]+)([0-9]+)$/.exec(String(name).toUpperCase());
  if (!match) return {row: 0, col: 0};
  let col = 0;
  for (const ch of match[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
  return {row: parseInt(match[2], 10), col};
}

export function coordName(row, col) {
  return colLetter(col) + row;
}

/** 坐标所在合并区域边界 {minCol,minRow,maxCol,maxRow}；不在合并区域内返回 null。 */
export function mergedRangeOf(sheet, coordinate) {
  if (!sheet || !coordinate) return null;
  const {row, col} = parseCoord(coordinate);
  for (const range of sheet.merged_ranges || []) {
    const parts = String(range).split(':');
    const start = parseCoord(parts[0]);
    const end = parseCoord(parts[1] || parts[0]);
    if (row >= start.row && row <= end.row && col >= start.col && col <= end.col) {
      return {minCol: start.col, minRow: start.row, maxCol: end.col, maxRow: end.row};
    }
  }
  return null;
}

function rowPt(sheet, row) {
  const height = (sheet.row_heights || {})[String(row)];
  return height === undefined || height === null ? DEFAULT_ROW_HEIGHT_PT : Number(height);
}

/** 绑定格跨行范围（合并取区域行界，隐藏行计 0 后逐行累计）。 */
function fillRows(sheet, coordinate) {
  const merged = mergedRangeOf(sheet, coordinate);
  const startRow = merged ? merged.minRow : parseCoord(coordinate).row;
  const endRow = merged ? merged.maxRow : startRow;
  const hidden = new Set(sheet.hidden_rows || []);
  const rows = [];
  for (let row = startRow; row <= endRow; row++) {
    if (!hidden.has(String(row))) rows.push(row);
  }
  return rows;
}

/** 绑定格的纵向填写高度（px）：跨行逐行换算累计（与渲染逐行取整一致）。 */
export function effectiveFillHeightPx(sheet, coordinate) {
  return fillRows(sheet, coordinate)
    .reduce((total, row) => total + Math.round(rowPt(sheet, row) * 4 / 3), 0);
}

/** 绑定格的纵向填写高度（pt，原始值累计）：用于"是否足够高"判定。 */
export function effectiveFillHeightPt(sheet, coordinate) {
  return fillRows(sheet, coordinate)
    .reduce((total, row) => total + rowPt(sheet, row), 0);
}

/**
 * 纵向只有一行默认高度的合并文本填写格（绑定工作台尺寸提示用）。
 * 仅限：文本类型 + 位于合并区域 + 跨 1 行 + 行高不足阈值——横向合并
 * 多列不会增加填写高度，需在 Excel/WPS 中显式设置行高。
 */
export function tightMergedTextBindings(sheet, bindings) {
  if (!sheet || !bindings || !bindings.length) return [];
  const hidden = new Set(sheet.hidden_rows || []);
  return bindings
    .filter(binding => {
      if (binding.sheet_name !== sheet.name || binding.input_type !== 'text') return false;
      const merged = mergedRangeOf(sheet, binding.cell_coordinate);
      if (!merged || merged.maxRow - merged.minRow !== 0) return false;
      if (hidden.has(String(merged.minRow))) return false;
      return rowPt(sheet, merged.minRow) < TALL_FILL_THRESHOLD_PT;
    })
    .map(binding => ({coordinate: binding.cell_coordinate, field_name: binding.field_name}));
}

export function uuidv4() {
  if (window.crypto && window.crypto.getRandomValues) {
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, ch => {
    const rand = Math.random() * 16 | 0;
    return (ch === 'x' ? rand : (rand & 0x3) | 0x8).toString(16);
  });
}
