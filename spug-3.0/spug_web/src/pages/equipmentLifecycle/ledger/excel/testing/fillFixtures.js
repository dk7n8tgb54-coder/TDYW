/**
 * Excel 台账填写工作区测试共享夹具（2026-10-19，仅供测试使用，不参与
 * 生产打包；置于 testing/ 而非 __tests__/，避免被 jest testMatch 当作
 * 独立测试套件）。
 *
 * 双工作表 + 合并格 + 不同列宽行高 + 必填/选填绑定，与 Docker 内
 * parse_workbook/validate_bindings 实证的结构同构：
 * - 维护记录（主工作表）：A1:F1 标题合并，B2:D2 横向合并（绑定锚点 B2），
 *   B4 文本格配 45pt 大行高，列宽 A=12.5/B=20；
 * - 签名页：无合并、无打印设置（print 纸张信息为 null），含跨表绑定
 *   字段「签名」（旧版填写页不可见该字段的缺口回归点）。
 */

export const FIELD_NAME = '7c9e6679-8420-4f14-b9d1-c1a1e5f0a101';
export const FIELD_STATUS = '7c9e6679-8420-4f14-b9d1-c1a1e5f0a102';
export const FIELD_CONTENT = '7c9e6679-8420-4f14-b9d1-c1a1e5f0a103';
export const FIELD_SIGN = '7c9e6679-8420-4f14-b9d1-c1a1e5f0a104';

export const SHEETS = [
  {
    name: '维护记录', max_row: 6, max_column: 6,
    merged_ranges: ['A1:F1', 'B2:D2'],
    row_heights: {'4': 45},
    column_widths: {A: 12.5, B: 20},
    hidden_rows: [], hidden_columns: [],
    cells: {
      A1: {v: '设备维护记录表'},
      A2: {v: '设备名称'},
      A3: {v: '巡检结论'},
      A4: {v: '维护内容'},
      B2: {s: {border: {top: {style: 'thin'}}}},
      B3: {s: {border: {top: {style: 'thin'}}}},
      B4: {s: {border: {top: {style: 'thin'}}}},
    },
    print: {orientation: 'portrait', paper_size: 9, fit_to_width: null, fit_to_height: null},
  },
  {
    name: '签名页', max_row: 2, max_column: 3,
    merged_ranges: [],
    row_heights: {}, column_widths: {},
    hidden_rows: [], hidden_columns: [],
    cells: {
      A1: {v: '签名确认'},
      A2: {v: '签名'},
      B2: {s: {border: {top: {style: 'thin'}}}},
    },
    print: {orientation: 'default', paper_size: null, fit_to_width: null, fit_to_height: null},
  },
];

export const BINDINGS = [
  {field_id: FIELD_NAME, sheet_name: '维护记录', cell_coordinate: 'B2',
   field_name: '设备名称', input_type: 'text', is_required: true, unit: '', options: []},
  {field_id: FIELD_STATUS, sheet_name: '维护记录', cell_coordinate: 'B3',
   field_name: '巡检结论', input_type: 'status', is_required: true, unit: '',
   options: ['正常', '异常']},
  {field_id: FIELD_CONTENT, sheet_name: '维护记录', cell_coordinate: 'B4',
   field_name: '维护内容', input_type: 'text', is_required: false, unit: '', options: []},
  {field_id: FIELD_SIGN, sheet_name: '签名页', cell_coordinate: 'B2',
   field_name: '签名', input_type: 'text', is_required: true, unit: '', options: []},
];

/** 纸张显示信息用打印参数（A4 纵向，含页边距）。 */
export const PDF_PARAMS = {
  preset: 'a4_auto', paper_size: 'A4', orientation: 'portrait',
  margins: {top: 1.91, bottom: 1.91, left: 1.78, right: 1.78, header: 0.76, footer: 0.76},
  scale_mode: 'fit_width', scale_percent: 100,
  repeat_header_rows: '', row_breaks: [], page_order: 'down_then_over',
  print_area: '', horizontal_centered: false, vertical_centered: false,
};

/** 组装 Excel 台账详情（草稿可编辑；overrides 覆盖顶层/Excel 字段）。 */
export function makeDetail(overrides = {}) {
  const {excel: excelOverrides, ...rest} = overrides;
  return {
    id: 71,
    ledger_no: 'EL-WM-20261019-001',
    ledger_type: 'week_month',
    status: 'draft',
    created_from: 'excel_template',
    ...rest,
    excel: {
      record_id: 9,
      values: {},
      editable: true,
      ...excelOverrides,
      version: {
        id: 5, version_no: 1, template_name: '双表维护模板',
        ledger_type: 'week_month', sheet_name: '维护记录',
        source_filename: 'multi-sheet.xlsx', source_hash: 'a'.repeat(64),
        field_count: 4, published_at: '2026-10-19 09:00:00',
        layout: {active_sheet: '维护记录', sheets: SHEETS},
        bindings: BINDINGS,
        pdf_params: PDF_PARAMS,
        ...(excelOverrides && excelOverrides.version ? excelOverrides.version : {}),
      },
    },
  };
}
