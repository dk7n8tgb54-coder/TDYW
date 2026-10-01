/**
 * Excel 路线 PDF 打印参数测试（真实渲染 + jsdom + http mock，2026-09-30；
 * 2026-10-01 打印模式扩展）。
 *
 * 覆盖：pdfParams 序列化（缺省补全/手动分页行换算与非法拦截/preset 贯穿
 * 与预设字段填充）→ PdfParamsForm 受控渲染与方向切换（自动/纵向/横向）、
 * original 禁用详细字段、打印区域与居中交互 → 模板 store 打开抽屉预填
 * 草稿参数、保存 PUT 载荷与失败不发请求 → 模板页 PDF参数 按钮打开抽屉 →
 * 台账页高级设置弹窗预填版本参数、确认后按覆盖参数预检并导出 → Excel
 * 路线不依赖 FortuneSheet（依赖已整体移除，require.resolve 必须失败）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockExportFile = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: jest.fn()},
  exportFile: mockExportFile,
  history: {location: {search: ''}, replace: jest.fn(), push: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const {
  normalizePdfParams,
  serializePdfParams,
  presetFieldValues,
} = require('../pdfParams');
const {ExcelTemplateStore} = require('../excelTemplateStore');
const {ExcelLedgerStore} = require('../excelLedgerStore');

const SHEET = {
  name: '信道维护记录', max_row: 6, max_column: 8,
  merged_ranges: ['A1:H1'],
  row_heights: {'1': 30},
  column_widths: {A: 12},
  cells: {
    A1: {v: '信道维护记录表'}, C2: {v: 'PS模块'},
    A3: {v: '第1信道'}, C4: {s: {border: {top: {style: 'thin'}}}},
  },
};

const BINDING = {
  field_id: 'aaaaaaaa-1111-4aaa-8aaa-000000000001',
  sheet_name: '信道维护记录', cell_coordinate: 'C4',
  field_name: 'PS模块', input_type: 'status', is_required: false,
  unit: '', options: ['正常', '异常'],
};

function makeTplDetail(overrides = {}) {
  return {
    id: 11,
    name: '信道Excel维护台账',
    ledger_type: 'week_month',
    description: '',
    is_active: true,
    latest_version_no: 0,
    versions_count: 0,
    ledgers_count: 0,
    status: 'draft',
    draft_source_filename: 'channel.xlsx',
    draft_source_hash: 'a'.repeat(64),
    draft: {
      sheet_name: '信道维护记录',
      source_filename: 'channel.xlsx',
      source_hash: 'a'.repeat(64),
      layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
      field_bindings: [BINDING],
      pdf_params: {},
      draft_updated_at: '2026-09-30 10:00:00',
    },
    ...overrides,
  };
}

function makeLedgerDetail() {
  return {
    id: 33,
    ledger_no: 'EL-WM-20260930-001',
    ledger_type: 'week_month',
    executed_date: '2026-09-30',
    executor_names: '验收人',
    status: 'draft',
    created_from: 'excel_template',
    excel: {
      record_id: 7,
      values: {},
      editable: true,
      version: {
        id: 5, version_no: 1, template_name: '信道Excel维护台账',
        ledger_type: 'week_month', source_filename: 'channel.xlsx',
        source_hash: 'a'.repeat(64), field_count: 1,
        published_at: '2026-09-30 09:00:00',
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
        bindings: [BINDING],
        pdf_params: {paper_size: 'A3', orientation: 'landscape'},
      },
    },
  };
}

let container = null;

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

function buttonByText(text, root) {
  const scope = root || container;
  return Array.from(scope.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  mockExportFile.mockResolvedValue(undefined);
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    document.body.removeChild(container);
  }
  // Modal.confirm 的 portal 不随容器卸载，手动清理避免跨用例残留
  document.querySelectorAll('.ant-modal-confirm').forEach(node => {
    if (node.parentNode) node.parentNode.remove();
  });
  container = null;
});

test('pdfParams 序列化：缺省补全与手动分页行换算', () => {
  const form = normalizePdfParams(null);
  expect(form.paper_size).toBe('A4');
  expect(form.scale_mode).toBe('fit_width');
  expect(form.margins.top).toBeGreaterThan(0);
  expect(form.row_breaks_text).toBe('');
  const {payload} = serializePdfParams({...form, row_breaks_text: '20,40，60'});
  expect(payload.row_breaks).toEqual([20, 40, 60]);
  expect(payload.page_order).toBe('down_then_over');
  const bad = serializePdfParams({...form, row_breaks_text: '20,x'});
  expect(bad.error).toContain('不是正整数');
  const prefill = normalizePdfParams({
    margins: {top: 2.5}, repeat_header_rows: '1:2', row_breaks: [12],
  });
  expect(prefill.margins.top).toBe(2.5);
  expect(prefill.margins.left).toBe(1.78);
  expect(prefill.repeat_header_rows).toBe('1:2');
  expect(prefill.row_breaks_text).toBe('12');
});

test('PdfParamsForm 受控渲染：方向切换回传新表单态', async () => {
  const PdfParamsForm = require('../PdfParamsForm').default;
  const onChange = jest.fn();
  const value = normalizePdfParams({orientation: 'portrait'});
  await act(async () => {
    ReactDOM.render(<PdfParamsForm value={value} onChange={onChange}/>, container);
  });
  expect(container.textContent).toContain('打印模式');
  expect(container.textContent).toContain('纸张大小');
  expect(container.textContent).toContain('页边距');
  expect(container.textContent).toContain('重复表头行');
  expect(container.textContent).toContain('分页顺序');
  expect(container.textContent).toContain('页面居中');
  const radios = container.querySelectorAll('input[type="radio"]');
  // 自动（按内容宽度）/纵向/横向 三个方向选项
  expect(radios.length).toBe(3);
  // React 对 radio 监听 click（ChangeEventPlugin），用真实点击触发
  await act(async () => {
    radios[2].click();
  });
  expect(onChange).toHaveBeenCalled();
  expect(onChange.mock.calls[0][0].orientation).toBe('landscape');
});

test('pdfParams 打印模式：preset 贯穿序列化，预设填充字段', () => {
  const form = normalizePdfParams({preset: 'a4_auto', orientation: 'auto'});
  expect(form.preset).toBe('a4_auto');
  expect(form.orientation).toBe('auto');
  expect(form.print_area).toBe('');
  expect(form.horizontal_centered).toBe(false);
  const {payload} = serializePdfParams({
    ...form, print_area: ' a1:e25 ', horizontal_centered: true,
  });
  expect(payload.preset).toBe('a4_auto');
  expect(payload.print_area).toBe('a1:e25');
  expect(payload.horizontal_centered).toBe(true);
  expect(payload.vertical_centered).toBe(false);
  expect(presetFieldValues('single_page')).toEqual(
    {paper_size: 'A4', orientation: 'auto', scale_mode: 'fit_page'});
  expect(presetFieldValues('a4_auto')).toEqual(
    {paper_size: 'A4', orientation: 'auto', scale_mode: 'fit_width'});
  expect(presetFieldValues('original')).toEqual({});
  // 历史快照（无 preset 键）缺省 custom，行为与 2026-09-30 一致
  expect(normalizePdfParams({}).preset).toBe('custom');
});

test('PdfParamsForm original 模式：提示并禁用详细字段', async () => {
  const PdfParamsForm = require('../PdfParamsForm').default;
  const onChange = jest.fn();
  const value = normalizePdfParams({preset: 'original'});
  await act(async () => {
    ReactDOM.render(<PdfParamsForm value={value} onChange={onChange}/>, container);
  });
  expect(container.textContent).toContain('使用上传文件已有的页面设置');
  const areaInput = container.querySelector('input[placeholder="如 A1:E25"]');
  expect(areaInput).toBeTruthy();
  expect(areaInput.disabled).toBe(true);
  const checkboxes = Array.from(container.querySelectorAll('input[type="checkbox"]'));
  expect(checkboxes.length).toBe(2);
  expect(checkboxes.every(node => node.disabled)).toBe(true);
});

test('PdfParamsForm 自定义模式：打印区域与水平居中可编辑并回传', async () => {
  const PdfParamsForm = require('../PdfParamsForm').default;
  const onChange = jest.fn();
  const value = normalizePdfParams({preset: 'custom'});
  await act(async () => {
    ReactDOM.render(<PdfParamsForm value={value} onChange={onChange}/>, container);
  });
  const areaInput = container.querySelector('input[placeholder="如 A1:E25"]');
  expect(areaInput.disabled).toBe(false);
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(areaInput, 'A1:E25');
    areaInput.dispatchEvent(new Event('change', {bubbles: true}));
  });
  expect(onChange).toHaveBeenCalled();
  expect(onChange.mock.calls[0][0].print_area).toBe('A1:E25');
  const checkbox = Array.from(
    container.querySelectorAll('input[type="checkbox"]'))[0];
  await act(async () => {
    checkbox.click();
  });
  expect(onChange.mock.calls[1][0].horizontal_centered).toBe(true);
});

test('模板 PDF 参数：打开抽屉预填草稿参数，保存 PUT 并关闭抽屉', async () => {
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeTplDetail({
    draft: {
      ...makeTplDetail().draft,
      pdf_params: {orientation: 'landscape', paper_size: 'A3'},
    },
  })});
  mockHttpPut.mockResolvedValue({data: makeTplDetail()});
  store.openPdfDrawer();
  expect(store.pdfDrawerVisible).toBe(true);
  expect(store.pdfForm.orientation).toBe('landscape');
  expect(store.pdfForm.paper_size).toBe('A3');
  expect(store.pdfForm.margins.top).toBeGreaterThan(0);
  store.setPdfForm({...store.pdfForm, row_breaks_text: '10, 20'});
  await store.savePdfParams();
  expect(mockHttpPut).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/pdf-params/',
    {pdf_params: expect.objectContaining({
      orientation: 'landscape', paper_size: 'A3', row_breaks: [10, 20],
    })});
  expect(message.success).toHaveBeenCalledWith('PDF 参数已保存');
  expect(store.pdfDrawerVisible).toBe(false);
  expect(store.pdfForm).toBeNull();
});

test('模板 PDF 参数：手动分页行非法时 warning 且不发请求', async () => {
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeTplDetail()});
  store.openPdfDrawer();
  store.setPdfForm({...store.pdfForm, row_breaks_text: 'abc'});
  const result = await store.savePdfParams();
  expect(result).toBe(false);
  expect(message.warning).toHaveBeenCalledWith(expect.stringContaining('不是正整数'));
  expect(mockHttpPut).not.toHaveBeenCalled();
  expect(store.pdfDrawerVisible).toBe(true);
});

test('模板工作区：PDF参数 按钮打开抽屉并渲染表单', async () => {
  const ExcelTemplatePage = require('../ExcelTemplatePage').default;
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeTplDetail()});
  mockHttpGet.mockResolvedValue({data: makeTplDetail()});
  await act(async () => {
    ReactDOM.render(<ExcelTemplatePage store={store}/>, container);
  });
  await flush();
  const button = buttonByText('PDF参数');
  expect(button).toBeTruthy();
  await act(async () => {
    button.click();
  });
  await flush();
  expect(store.pdfDrawerVisible).toBe(true);
  const formNode = document.querySelector('.pdf-params-form');
  expect(formNode).toBeTruthy();
  expect(formNode.textContent).toContain('纸张大小');
});

test('台账高级 PDF 设置：预填版本参数，确认后按覆盖参数预检并导出', async () => {
  const ExcelLedgerPage = require('../ExcelLedgerPage').default;
  const store = new ExcelLedgerStore();
  const detail = makeLedgerDetail();
  store.applyDetail({data: detail});
  mockHttpGet.mockResolvedValue({data: detail});
  mockHttpPost.mockResolvedValue({data: {warnings: []}});
  const ref = React.createRef();
  await act(async () => {
    ReactDOM.render(<ExcelLedgerPage store={store} ref={ref}/>, container);
  });
  await flush();
  await act(async () => {
    ref.current.handleOpenPdfAdvanced();
  });
  await flush();
  const modal = document.querySelector('.ant-modal');
  expect(modal).toBeTruthy();
  expect(modal.textContent).toContain('高级 PDF 设置');
  const okButton = Array.from(modal.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === '确定');
  await act(async () => {
    okButton.click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-ledgers/33/export/check/',
    {pdf_params: expect.objectContaining({paper_size: 'A3', orientation: 'landscape'})});
  expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
    url: '/api/equipment-lifecycle/excel-ledgers/33/export/pdf/',
    method: 'post',
    data: {pdf_params: expect.objectContaining({paper_size: 'A3'})},
  }));
});

test('Excel 路线不依赖 FortuneSheet（在线设计器依赖已整体移除）', () => {
  expect(() => require.resolve('fortune-sheet')).toThrow();
  expect(() => require.resolve('@fortune-sheet/react')).toThrow();
});
