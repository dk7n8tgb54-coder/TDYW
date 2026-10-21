/**
 * Excel 台账打印预览与未保存导出确认测试（2026-10-21 统一打印布局）。
 *
 * 覆盖（真实 store 行为 + jsdom 组件交互 + http mock）：
 * - 打印预览：fetchPrintPreview POST print-preview/（arraybuffer）→
 *   blob URL + X-El-Pdf-Pages/Paper 反馈头；失败置错误态可重试；
 *   切换台账详情（applyDetail）重置预览并释放 blob URL；
 * - 详情视图模式：可编辑台账默认「填写」，历史台账默认「打印预览」，
 *   可切换；预览页签存在未保存修改时横幅明确提示（预览显示最近保存
 *   的服务端值，不静默使用旧值）；
 * - 未保存导出确认：导出 Excel/PDF 在有未保存修改时先弹窗（存在未保存
 *   的修改），「保存并导出」先 PUT 保存成功再导出，取消不导出。
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

const {ExcelLedgerStore} = require('../excelLedgerStore');
const ExcelLedgerDetail = require('../ExcelLedgerDetail').default;

const FIELD_PS = 'bbbbbbbb-2222-4bbb-8bbb-000000000001';
const FIELD_REMARK = 'bbbbbbbb-2222-4bbb-8bbb-000000000002';

const SHEET = {
  name: '信道维护记录', max_row: 4, max_column: 8, merged_ranges: [],
  row_heights: {}, column_widths: {},
  cells: {A1: {v: '信道维护记录表'}, C3: {v: ''}, H3: {v: ''}},
};

const BINDINGS = [
  {field_id: FIELD_PS, sheet_name: '信道维护记录', cell_coordinate: 'C3',
   field_name: 'PS模块', input_type: 'status', is_required: true,
   unit: '', options: ['正常', '异常']},
  {field_id: FIELD_REMARK, sheet_name: '信道维护记录', cell_coordinate: 'H3',
   field_name: '备注', input_type: 'text', is_required: false,
   unit: '', options: []},
];

function makeDetail(overrides = {}) {
  const {
    status = 'draft', values = {}, editable = status === 'draft',
    ...rest
  } = overrides;
  return {
    id: 77,
    ledger_no: 'EL-WM-20261021-001',
    ledger_type: 'week_month',
    status,
    created_from: 'excel_template',
    excel: {
      record_id: 9,
      values,
      editable,
      version: {
        id: 5, version_no: 1, template_name: '信道Excel维护台账',
        ledger_type: 'week_month', source_filename: 'channel.xlsx',
        source_hash: 'a'.repeat(64), field_count: 2,
        published_at: '2026-10-21 09:00:00',
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
        bindings: BINDINGS,
      },
    },
    ...rest,
  };
}

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

function removeModals() {
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask')
    .forEach(node => node.remove());
}

function buttonByText(text, root) {
  const scope = root || document.body;
  return Array.from(scope.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
}

let container = null;

beforeAll(() => {
  window.URL.createObjectURL = jest.fn(() => 'blob:mock-preview');
  window.URL.revokeObjectURL = jest.fn();
});

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockExportFile].forEach(fn => fn.mockReset());
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  container = null;
  removeModals();
  jest.restoreAllMocks();
});

async function renderDetail(store) {
  await act(async () => {
    ReactDOM.render(<ExcelLedgerDetail store={store} onBack={() => {}}/>, container);
  });
  await flush();
}

// ===== Store：打印预览 =====

describe('ExcelLedgerStore 打印预览', () => {
  test('fetchPrintPreview 成功：blob URL + 反馈头；重复获取释放旧 URL', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail()});
    mockHttpPost.mockResolvedValue({
      data: new ArrayBuffer(16),
      headers: {'x-el-pdf-pages': '2', 'x-el-pdf-paper': 'A4 210x297mm'},
    });
    const url = await store.fetchPrintPreview();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/77/print-preview/', {},
      expect.objectContaining({responseType: 'arraybuffer'}));
    expect(url).toBe('blob:mock-preview');
    expect(store.printPreviewUrl).toBe('blob:mock-preview');
    expect(store.printPreviewMeta).toEqual({pages: '2', paper: 'A4 210x297mm'});
    expect(store.printPreviewError).toBe('');
    // 再次获取：旧 blob URL 先释放
    await store.fetchPrintPreview();
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-preview');
  });

  test('fetchPrintPreview 失败：置错误态（可重试），不残留旧预览判定', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail()});
    mockHttpPost.mockRejectedValue(new Error('boom'));
    await expect(store.fetchPrintPreview()).rejects.toBeTruthy();
    expect(store.printPreviewUrl).toBe('');
    expect(store.printPreviewError).toContain('预览生成失败');
    expect(store.printPreviewLoading).toBe(false);
  });

  test('applyDetail 切换台账重置预览并释放 blob URL', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail()});
    mockHttpPost.mockResolvedValue({data: new ArrayBuffer(8), headers: {}});
    await store.fetchPrintPreview();
    expect(store.printPreviewUrl).toBe('blob:mock-preview');
    store.applyDetail({data: makeDetail({id: 78})});
    expect(store.printPreviewUrl).toBe('');
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-preview');
  });
});

// ===== 组件：视图模式与预览页签 =====

describe('ExcelLedgerDetail 视图模式与打印预览页签', () => {
  test('可编辑台账默认「填写」，历史台账默认「打印预览」，可互相切换', async () => {
    const draftStore = new ExcelLedgerStore();
    draftStore.applyDetail({data: makeDetail()});
    await renderDetail(draftStore);
    const modes = container.querySelectorAll(
      '[data-testid="ledger-view-mode"] .ant-radio-button-wrapper');
    expect(modes.length).toBe(2);
    expect([...modes].find(el => el.classList.contains('ant-radio-button-wrapper-checked'))
      .textContent).toContain('填写');
    expect(container.querySelector('[data-testid="fill-workspace"]')).toBeTruthy();

    // 卸载后重渲染（避免 React 复用同一组件实例保留视图模式 state）
    await act(async () => { ReactDOM.unmountComponentAtNode(container); });
    const doneStore = new ExcelLedgerStore();
    doneStore.applyDetail({data: makeDetail({status: 'completed', editable: false})});
    await renderDetail(doneStore);
    const checked = [...container.querySelectorAll(
      '[data-testid="ledger-view-mode"] .ant-radio-button-wrapper')]
      .find(el => el.classList.contains('ant-radio-button-wrapper-checked'));
    expect(checked.textContent).toContain('打印预览');
    expect(container.querySelector('[data-testid="ledger-print-preview"]')).toBeTruthy();
  });

  test('预览页签展示生成的 PDF（iframe）与页数/纸张反馈', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({status: 'completed', editable: false})});
    mockHttpPost.mockResolvedValue({
      data: new ArrayBuffer(16),
      headers: {'x-el-pdf-pages': '3', 'x-el-pdf-paper': 'A4 297x210mm'},
    });
    await renderDetail(store);
    expect(container.querySelector('[data-testid="preview-iframe"]')).toBeNull();
    await act(async () => {
      container.querySelector('[data-testid="preview-refresh"]').click();
    });
    await flush();
    const iframe = container.querySelector('[data-testid="preview-iframe"]');
    expect(iframe).toBeTruthy();
    expect(iframe.src).toBe('blob:mock-preview');
    expect(container.querySelector('[data-testid="preview-meta"]').textContent)
      .toContain('3 页');
  });

  test('存在未保存修改时预览页签显示明确横幅（预览用已保存值）', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail()});
    store.setValue(FIELD_REMARK, '未保存内容');
    await renderDetail(store);
    await act(async () => {
      [...container.querySelectorAll('.ant-radio-button-wrapper')]
        .find(el => el.textContent.includes('打印预览'))
        .querySelector('input').click();
    });
    expect(container.querySelector('[data-testid="preview-unsaved-banner"]').textContent)
      .toContain('未保存');
    expect(container.querySelector('[data-testid="preview-unsaved-banner"]').textContent)
      .toContain('最近保存');
  });
});

// ===== 组件：未保存导出确认 =====

describe('ExcelLedgerDetail 未保存导出确认', () => {
  test('导出 PDF 有未保存修改：先弹窗，「保存并导出」先保存再导出', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({values: {[FIELD_PS]: '正常'}})});
    store.setValue(FIELD_REMARK, '未保存备注');
    await renderDetail(store);
    await act(async () => { buttonByText('导出PDF', container).click(); });
    await flush();
    const modalText = document.body.querySelector('.ant-modal-confirm')?.textContent || '';
    expect(modalText).toContain('存在未保存的修改');
    expect(modalText).toContain('最近保存的填写值');
    // 主操作：保存并导出 → PUT 保存成功（返回新详情）→ 预检 → exportFile
    mockHttpPut.mockResolvedValue({
      data: makeDetail({values: {[FIELD_PS]: '正常', [FIELD_REMARK]: '未保存备注'}}),
    });
    mockHttpPost.mockResolvedValue({data: {warnings: []}});
    await act(async () => { buttonByText('保存并导出').click(); });
    await flush();
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/77/',
      expect.objectContaining({values: expect.objectContaining({})}));
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/77/export/check/', {});
    expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/equipment-lifecycle/excel-ledgers/77/export/pdf/',
      method: 'post',
    }));
  });

  test('无未保存修改时直接进入预检，不再弹未保存确认', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({values: {[FIELD_PS]: '正常'}})});
    await renderDetail(store);
    mockHttpPost.mockResolvedValue({data: {warnings: []}});
    await act(async () => { buttonByText('导出PDF', container).click(); });
    await flush();
    expect(document.body.querySelector('.ant-modal-confirm-title')?.textContent)
      .not.toBe('存在未保存的修改');
    expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/equipment-lifecycle/excel-ledgers/77/export/pdf/',
    }));
  });
});
