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
 */

/** Excel 缺省行高（pt）；布局 meta 未记录行高时按此值。 */
export const DEFAULT_ROW_HEIGHT_PT = 14.25;
/** 纵向"足够高"阈值：≥2 行默认高度（28.5pt ≈ 38px）按多行填写。 */
export const TALL_FILL_THRESHOLD_PT = DEFAULT_ROW_HEIGHT_PT * 2;

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
