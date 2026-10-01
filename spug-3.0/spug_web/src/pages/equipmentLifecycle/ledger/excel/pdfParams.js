/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * PDF 打印参数（模板级，2026-09-30；2026-10-01 打印模式扩展）共享常量与表单换算。
 *
 * 协议与后端 excel_pdf_params.py 对齐：preset（打印模式）/paper_size/
 * orientation(auto|portrait|landscape)/margins(cm)/scale_mode/scale_percent/
 * repeat_header_rows('起:止')/row_breaks(行号数组)/page_order/print_area/
 * horizontal_centered/vertical_centered。表单态用逗号分隔文本编辑手动分页行，
 * 提交前序列化为数组；序列化遇到非法行号返回 {error}，由调用方 warning
 * 提示并中止。
 *
 * preset 四档（与后端 PRESETS 一致）：
 * - original：原始 Excel 打印设置——导出完全沿用上传文件已有页面设置，
 *   详细字段失效（表单禁用）；
 * - a4_auto：A4 自动适配——A4 + 方向自动（按内容宽度选纵向/横向）+
 *   宽度适合 1 页 + 高度自动分页；
 * - single_page：单页表单——宽度 1 页 + 高度 1 页（缩放过小时导出前
 *   预检给出警告）；
 * - custom：逐项自定义（历史快照缺省值，与 2026-09-30 行为一致）。
 */
export const PAPER_SIZE_OPTIONS = [
  {value: 'A4', label: 'A4'},
  {value: 'A3', label: 'A3'},
  {value: 'A5', label: 'A5'},
  {value: 'B4', label: 'B4'},
  {value: 'B5', label: 'B5'},
  {value: 'letter', label: 'Letter'},
  {value: 'legal', label: 'Legal'},
];

export const ORIENTATION_OPTIONS = [
  {value: 'auto', label: '自动（按内容宽度）'},
  {value: 'portrait', label: '纵向'},
  {value: 'landscape', label: '横向'},
];

export const SCALE_MODE_OPTIONS = [
  {value: 'fit_width', label: '按宽度适配一页'},
  {value: 'fit_page', label: '整表适配一页'},
  {value: 'percent', label: '按百分比缩放'},
  {value: 'actual', label: '按原尺寸（100%）'},
];

export const PAGE_ORDER_OPTIONS = [
  {value: 'down_then_over', label: '先下后右'},
  {value: 'over_then_down', label: '先右后下'},
];

export const PRESET_OPTIONS = [
  {value: 'a4_auto', label: 'A4 自动适配（推荐）'},
  {value: 'original', label: '原始 Excel 打印设置'},
  {value: 'single_page', label: '单页表单'},
  {value: 'custom', label: '自定义'},
];

export const MARGIN_FIELDS = [
  {key: 'top', label: '上'},
  {key: 'bottom', label: '下'},
  {key: 'left', label: '左'},
  {key: 'right', label: '右'},
  {key: 'header', label: '页眉'},
  {key: 'footer', label: '页脚'},
];

const DEFAULTS = {
  preset: 'custom',
  paper_size: 'A4',
  orientation: 'portrait',
  margins: {
    top: 1.91, bottom: 1.91, left: 1.78, right: 1.78, header: 0.76, footer: 0.76,
  },
  scale_mode: 'fit_width',
  scale_percent: 100,
  repeat_header_rows: '',
  row_breaks: [],
  page_order: 'down_then_over',
  print_area: '',
  horizontal_centered: false,
  vertical_centered: false,
};

/** 选择打印模式时填充的对应字段（original 不改字段：详细字段禁用）。 */
export function presetFieldValues(preset) {
  if (preset === 'a4_auto') {
    return {paper_size: 'A4', orientation: 'auto', scale_mode: 'fit_width'};
  }
  if (preset === 'single_page') {
    return {paper_size: 'A4', orientation: 'auto', scale_mode: 'fit_page'};
  }
  return {};
}

/** 后端参数 → 表单态（缺省补全；手动分页行数组转逗号文本）。 */
export function normalizePdfParams(raw) {
  const params = {...DEFAULTS, ...(raw || {})};
  return {
    ...params,
    margins: {...DEFAULTS.margins, ...((raw && raw.margins) || {})},
    repeat_header_rows: params.repeat_header_rows || '',
    row_breaks_text: (params.row_breaks || []).join(','),
    print_area: params.print_area || '',
  };
}

/** 表单态 → 后端载荷；手动分页行文本非法时返回 {error}。 */
export function serializePdfParams(form) {
  const rows = [];
  const text = (form.row_breaks_text || '').trim();
  if (text) {
    const tokens = text.split(/[,，\s]+/);
    for (const token of tokens) {
      const row = Number(token);
      if (!token || !Number.isInteger(row) || row < 1) {
        return {error: `手动分页行「${token}」不是正整数行号`};
      }
      rows.push(row);
    }
  }
  return {
    payload: {
      preset: form.preset || 'custom',
      paper_size: form.paper_size,
      orientation: form.orientation,
      margins: form.margins,
      scale_mode: form.scale_mode,
      scale_percent: Number(form.scale_percent) || 100,
      repeat_header_rows: (form.repeat_header_rows || '').trim(),
      row_breaks: rows,
      page_order: form.page_order,
      print_area: (form.print_area || '').trim(),
      horizontal_centered: !!form.horizontal_centered,
      vertical_centered: !!form.vertical_centered,
    },
  };
}
