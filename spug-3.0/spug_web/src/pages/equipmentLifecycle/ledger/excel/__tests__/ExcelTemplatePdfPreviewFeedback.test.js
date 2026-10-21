/**
 * 打印设置「应用当前设置并预览」+ 临时样例数据 + 预览反馈测试
 * （真实渲染 + jsdom + http mock，2026-10-19）。
 *
 * 覆盖：parsePdfMetaHeaders/formatPaperText（响应头解析与纸张文本格式化，
 * 异常兜底不伪造）→ store 预览反馈（previewPdf 标注已保存参数来源；
 * previewWithFormParams 携带表单当前值与临时样例数据、序列化失败不发
 * 请求）→ pdfFormDirty 未保存修改判定 → 打印设置抽屉渲染（预览视图
 * 入口、临时预览数据区按字段类型渲染、样例值回传 store、反馈 Alert 与
 * 参数来源文案）→ 打印预览视图页内展示真实 PDF 并标注已保存参数来源
 * （2026-10-21 统一观感）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: jest.fn()},
  exportFile: jest.fn(),
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

const {ExcelTemplateStore, parsePdfMetaHeaders, formatPaperText} =
  require('../excelTemplateStore');
const {normalizePdfParams} = require('../pdfParams');

const SHEET = {
  name: '信道维护记录', max_row: 6, max_column: 8,
  merged_ranges: ['A1:H1'], row_heights: {'1': 30},
  column_widths: {A: 12},
  cells: {A1: {v: '信道维护记录表'}},
};

const BINDINGS = [
  {
    field_id: 'aaaaaaaa-1111-4aaa-8aaa-000000000001',
    sheet_name: '信道维护记录', cell_coordinate: 'C4',
    field_name: '维护记录', input_type: 'text', is_required: true,
    unit: '', options: [],
  },
  {
    field_id: 'aaaaaaaa-1111-4aaa-8aaa-000000000002',
    sheet_name: '信道维护记录', cell_coordinate: 'D4',
    field_name: '结论', input_type: 'status', is_required: false,
    unit: '', options: ['正常', '异常'],
  },
];

function makeDetail(overrides = {}) {
  return {
    id: 11,
    name: '信道Excel维护台账',
    ledger_type: 'week_month',
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
      field_bindings: BINDINGS,
      pdf_params: {},
      draft_updated_at: '2026-10-19 10:00:00',
    },
    ...overrides,
  };
}

const PDF_RESPONSE_HEADERS = {
  'content-type': 'application/pdf',
  'x-el-pdf-pages': '3',
  'x-el-pdf-paper': 'A4 297x210mm',
  'x-el-pdf-warnings': encodeURIComponent(
    JSON.stringify(['工作表「信道维护记录」按单页适配后缩放约 40%，打印字号可能过小'])),
};

let container = null;

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

function stubPdfWindow() {
  const openMock = jest.fn().mockReturnValue({});
  window.open = openMock;
  window.URL.createObjectURL = jest.fn(() => 'blob:preview-url');
  window.URL.revokeObjectURL = jest.fn();
  return openMock;
}

const setInputValue = async (node, value) => {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value').set;
  await act(async () => {
    setter.call(node, value);
    node.dispatchEvent(new Event('change', {bubbles: true}));
  });
};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    document.body.removeChild(container);
  }
  container = null;
});

test('parsePdfMetaHeaders 解析反馈响应头，异常兜底不伪造', () => {
  const parsed = parsePdfMetaHeaders({headers: PDF_RESPONSE_HEADERS});
  expect(parsed.pages).toBe(3);
  expect(parsed.paper).toBe('A4 297x210mm');
  expect(parsed.warnings).toHaveLength(1);
  expect(parsed.warnings[0]).toContain('字号');
  const empty = parsePdfMetaHeaders({headers: {}});
  expect(empty).toEqual({pages: null, paper: '', warnings: []});
  const broken = parsePdfMetaHeaders({headers: {
    'x-el-pdf-pages': 'abc',
    'x-el-pdf-warnings': encodeURIComponent('not-json%'),
  }});
  expect(broken.pages).toBeNull();
  expect(broken.warnings).toEqual([]);
});

test('formatPaperText 纸张文本格式化，未匹配原样兜底', () => {
  expect(formatPaperText('A4 210x297mm')).toBe('A4（210×297 mm）');
  expect(formatPaperText('297x210mm')).toBe('297×210 mm');
  expect(formatPaperText('')).toBe('');
  expect(formatPaperText('odd-text')).toBe('odd-text');
});

test('previewPdf（已保存参数）成功后反馈来源标注已保存参数', async () => {
  stubPdfWindow();
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeDetail()});
  mockHttpPost.mockResolvedValue({
    data: new ArrayBuffer(16), headers: PDF_RESPONSE_HEADERS,
  });
  await store.previewPdf();
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/preview/pdf/', null,
    expect.objectContaining({responseType: 'arraybuffer'}));
  expect(store.previewInfo.source).toBe('saved');
  expect(store.previewInfo.pages).toBe(3);
  expect(store.previewInfo.warnings).toHaveLength(1);
  expect(store.previewing).toBe(false);
});

test('previewWithFormParams 携带表单当前值与样例数据，来源标注未保存', async () => {
  stubPdfWindow();
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeDetail()});
  store.openPdfDrawer();
  store.setPdfForm({...store.pdfForm, orientation: 'landscape',
    row_breaks_text: '8'});
  store.setSampleValue(BINDINGS[0].field_id, '长文本样例内容');
  mockHttpPost.mockResolvedValue({
    data: new ArrayBuffer(16), headers: PDF_RESPONSE_HEADERS,
  });
  const result = await store.previewWithFormParams();
  expect(result).toBe(true);
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/preview/pdf/',
    {pdf_params: expect.objectContaining({orientation: 'landscape',
      row_breaks: [8]}),
     sample_values: {[BINDINGS[0].field_id]: '长文本样例内容'}},
    expect.objectContaining({responseType: 'arraybuffer'}));
  expect(store.previewInfo.source).toBe('form');
  expect(store.previewInfo.paper).toBe('A4 297x210mm');
  expect(store.previewing).toBe(false);
});

test('previewWithFormParams 序列化失败 warning 且不发请求', async () => {
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeDetail()});
  store.openPdfDrawer();
  store.setPdfForm({...store.pdfForm, row_breaks_text: 'abc'});
  const result = await store.previewWithFormParams();
  expect(result).toBe(false);
  expect(message.warning).toHaveBeenCalledWith(expect.stringContaining('不是正整数'));
  expect(mockHttpPost).not.toHaveBeenCalled();
  expect(store.previewInfo).toBeNull();
});

test('pdfFormDirty 判定未保存修改（打开时与草稿一致，改动后为真）', () => {
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeDetail({
    draft: {...makeDetail().draft, pdf_params: {orientation: 'landscape'}},
  })});
  store.openPdfDrawer();
  expect(store.pdfFormDirty).toBe(false);
  store.setPdfForm({...store.pdfForm, orientation: 'portrait'});
  expect(store.pdfFormDirty).toBe(true);
  store.closePdfDrawer();
  expect(store.pdfForm).toBeNull();
  expect(store.sampleForm).toBeNull();
  expect(store.pdfFormDirty).toBe(false);
});

async function renderPage(store) {
  const ExcelTemplatePage = require('../ExcelTemplatePage').default;
  await act(async () => {
    ReactDOM.render(<ExcelTemplatePage store={store}/>, container);
  });
  await flush();
}

async function openPdfDrawer(store) {
  const trigger = container.querySelector('[data-testid="tpl-more-actions"]');
  await act(async () => {
    trigger.click();
  });
  await flush();
  const dropdown = document.body.querySelector(
    '.ant-dropdown:not(.ant-dropdown-hidden)');
  const menuItem = dropdown.querySelector('[data-testid="tpl-pdf-params"]');
  await act(async () => {
    menuItem.click();
  });
  await flush();
}

test('打印设置抽屉：预览视图入口与临时样例数据区按字段类型渲染', async () => {
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeDetail()});
  await renderPage(store);
  // 工作区提供「字段绑定 / 打印预览」双视图（2026-10-21 统一观感，
  // 预览使用模板已保存打印参数，随预览视图内展示参数来源）
  expect(container.querySelector('[data-testid="tpl-view-mode"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="tpl-view-mode-preview"]'))
    .toBeTruthy();
  await openPdfDrawer(store);
  expect(store.pdfDrawerVisible).toBe(true);
  expect(document.querySelector('[data-testid="tpl-pdf-preview-form"]'))
    .toBeTruthy();
  expect(document.body.textContent).toContain('应用当前设置并预览');
  expect(document.body.textContent).toContain('临时预览数据（可选）');
  // 长文本字段（维护记录）渲染多行文本框，status 字段渲染选择器
  const textarea = document.querySelector(
    `[data-testid="tpl-sample-${BINDINGS[0].field_id}"]`);
  expect(textarea).toBeTruthy();
  expect(textarea.tagName).toBe('TEXTAREA');
  const select = document.querySelector(
    `[data-testid="tpl-sample-${BINDINGS[1].field_id}"]`);
  expect(select).toBeTruthy();
  await setInputValue(textarea, '临时维护记录样例');
  expect(store.sampleForm[BINDINGS[0].field_id]).toBe('临时维护记录样例');
});

test('抽屉预览后渲染反馈 Alert：页数/纸张/提示/参数来源', async () => {
  stubPdfWindow();
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeDetail()});
  mockHttpPost.mockResolvedValue({
    data: new ArrayBuffer(16), headers: PDF_RESPONSE_HEADERS,
  });
  await renderPage(store);
  await openPdfDrawer(store);
  const previewButton = document.querySelector(
    '[data-testid="tpl-pdf-preview-form"]');
  await act(async () => {
    previewButton.click();
  });
  await flush();
  expect(store.previewInfo.source).toBe('form');
  const alert = document.body.querySelector(
    '[data-testid="tpl-pdf-preview-info"]');
  expect(alert).toBeTruthy();
  expect(alert.textContent).toContain('当前未保存参数');
  expect(alert.textContent).toContain('共 3 页');
  expect(alert.textContent).toContain('A4（297×210 mm）');
  expect(alert.textContent).toContain('字号可能过小');
  expect(alert.className).toContain('ant-alert-warning');
});

test('打印预览视图：页内展示真实 PDF 并标注已保存参数来源', async () => {
  window.URL.createObjectURL = jest.fn(() => 'blob:preview-url');
  window.URL.revokeObjectURL = jest.fn();
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeDetail()});
  mockHttpPost.mockResolvedValue({
    data: new ArrayBuffer(16), headers: PDF_RESPONSE_HEADERS,
  });
  await renderPage(store);
  // 切到打印预览视图：自动请求预览接口（与「预览空白打印稿」同一服务）
  const previewInput = Array.from(
    container.querySelectorAll('[data-testid="tpl-view-mode"] input'))
    .find(node => node.value === 'preview');
  await act(async () => {
    previewInput.click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/preview/pdf/', null,
    expect.objectContaining({responseType: 'arraybuffer'}));
  const iframe = container.querySelector('[data-testid="tpl-preview-iframe"]');
  expect(iframe).toBeTruthy();
  expect(store.printPreviewMeta.source).toBe('saved');
  expect(store.printPreviewMeta.pages).toBe(3);
  // 预览内反馈：页数/纸张/参数来源（与抽屉反馈 Alert 区分入口）
  const meta = container.querySelector('[data-testid="tpl-preview-meta"]');
  expect(meta.textContent).toContain('3 页');
  expect(meta.textContent).toContain('A4（297×210 mm）');
  expect(meta.textContent).toContain('模板已保存的打印参数');
});

test('无绑定字段时样例数据区提示空白打印稿', async () => {
  const store = new ExcelTemplateStore();
  store.applyDetail({data: makeDetail({
    draft: {...makeDetail().draft, field_bindings: []},
  })});
  await renderPage(store);
  await openPdfDrawer(store);
  const section = document.querySelector('[data-testid="tpl-pdf-sample"]');
  expect(section.textContent).toContain('暂无绑定字段，预览为空白打印稿');
});

test('normalizePdfParams 兼容：抽屉打开预填不回归（打印参数主流程不变）', () => {
  const form = normalizePdfParams({preset: 'a4_auto'});
  expect(form.preset).toBe('a4_auto');
  expect(form.paper_size).toBe('A4');
  expect(form.margins.top).toBeGreaterThan(0);
});
