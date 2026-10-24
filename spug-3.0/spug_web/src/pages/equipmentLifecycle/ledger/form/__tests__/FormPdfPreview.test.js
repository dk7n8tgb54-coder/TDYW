/**
 * 数字表单 PDF 预览/导出行为测试（2026-10-22）。
 *
 * 真实渲染（ReactDOM + jsdom）+ mock libs/http，验证：
 * - 模板编辑器"预览 PDF"：无未保存修改直接 POST preview/pdf（arraybuffer），
 *   blob URL 进 iframe 并展示页数/纸张反馈头；
 * - 模板编辑器有未保存修改：先确认（文案说明基于已保存草稿），确认后才 POST；
 * - 样张生成失败：显示失败态与重新生成入口（重试再次 POST）；
 * - 台账详情"预览 PDF"：无未保存直接生成；有未保存修改先确认
 *   （PDF 基于最近一次保存的内容，不静默导出未保存数据）；
 * - 台账详情"导出 PDF"：走公共 exportFile 下载（POST export/pdf/）；
 * - 详情刷新（保存/完成回写）后旧预览 blob URL 释放（不展示陈旧预览）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockExportFile = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: (...args) => mockExportFile(...args),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell,
    AuthButton: (props) => React.createElement('button', {
      type: 'button', 'data-testid': props['data-testid'], onClick: props.onClick,
    }, props.children),
    AuthCard: Shell, AuthFragment: Shell, Breadcrumb: Shell, SearchForm: Shell,
  };
});

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}
window.URL.createObjectURL = jest.fn(() => 'blob:mock');
window.URL.revokeObjectURL = jest.fn();

const FormTemplateEditor = require('../FormTemplateEditor').default;
const FormLedgerDetail = require('../FormLedgerDetail').default;
const {formTemplateStore} = require('../formTemplateStore');
const {FormLedgerStore} = require('../formLedgerStore');

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const flushAll = async () => { await flush(); await flush(); await flush(); };

const PDF_BYTES = new Uint8Array([37, 80, 68, 70, 45]); // %PDF-

function mockPdfPost() {
  mockHttpPost.mockResolvedValue({
    data: PDF_BYTES.buffer,
    headers: {'x-el-pdf-pages': '2', 'x-el-pdf-paper': 'A4 210x297mm'},
  });
}

function render(node) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  ReactDOM.render(node, container);
  return {container, cleanup: () => {
    ReactDOM.unmountComponentAtNode(container);
    document.querySelectorAll('.ant-modal-root, .ant-drawer-root, .ant-modal-confirm')
      .forEach(node => node.remove());
    container.remove();
  }};
}

function setText(input, value) {
  const proto = input.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

/** date 字段 DatePicker 面板点选（jsdom 真实交互路径）。 */
async function pickDate(input) {
  await act(async () => {
    input.focus();
    input.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    input.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    input.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
  const cell = document.querySelector('.ant-picker-cell-in-view .ant-picker-cell-inner');
  expect(cell).toBeTruthy();
  await act(async () => {
    cell.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

function removeConfirmModals() {
  document.querySelectorAll('.ant-modal-confirm, .ant-modal-root')
    .forEach(node => node.remove());
}

/** 点击确认弹窗中指定文案的按钮（文案忽略空白差异）。 */
async function clickConfirmButton(text) {
  const confirm = document.querySelector('.ant-modal-confirm');
  expect(confirm).toBeTruthy();
  const btn = Array.from(confirm.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text);
  expect(btn).toBeTruthy();
  await act(async () => { btn.click(); });
  await flush();
}

// —— 模板编辑器夹具 ——

const DRAFT_FORM = {
  protocol_version: 2,
  groups: [
    {id: 'gbaseinfo01', name: '基本信息', description: '', kind: 'fields',
     item_name: '', columns: [], fields: [
       {id: 'fmaintdate1', name: '维护日期', type: 'date', required: true,
        description: '', unit: '', options: []}]},
  ],
};

function makeTemplateDetail() {
  return {
    id: 12, name: '周维护数字表单', ledger_type: 'week_month',
    description: '', system: null, system_name: '', generation_period: '',
    generation_period_text: '待配置', is_active: true,
    has_draft: true, latest_version_no: 0, versions_count: 0, ledgers_count: 0,
    status: 'draft',
    draft: {form: DRAFT_FORM, updated_at: '2026-10-21T10:00:00', updated_by: '张三'},
    draft_state: {relation: 'identical', latest_version_no: 0, versions_count: 0,
                  field_count: 1, updated_at: '2026-10-21T10:00:00'},
  };
}

function resetTemplateStore() {
  const store = formTemplateStore;
  store.list = []; store.detail = null; store.editorVisible = false;
  store.editorTemplate = null; store.editorLoading = false;
  store.editorLoadError = ''; store.savingDraft = false; store.publishing = false;
  store.samplePdfUrl = ''; store.samplePdfMeta = null;
  store.samplePdfLoading = false; store.samplePdfError = '';
}

async function openEditorWithDraft() {
  mockHttpGet.mockResolvedValue({data: makeTemplateDetail()});
  act(() => {
    formTemplateStore.openEditor({id: 12, name: '周维护数字表单'});
  });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  return view;
}

describe('模板编辑器：预览 PDF 样张', () => {
  beforeEach(() => {
    mockHttpGet.mockReset();
    mockHttpPost.mockReset();
    mockHttpPut.mockReset();
    mockExportFile.mockReset();
    window.URL.createObjectURL.mockClear();
    window.URL.revokeObjectURL.mockClear();
    removeConfirmModals();
    resetTemplateStore();
  });

  test('无未保存修改：直接 POST preview/pdf，iframe 展示并记录反馈头', async () => {
    const view = await openEditorWithDraft();
    mockPdfPost();
    await act(async () => {
      document.querySelector('[data-testid="editor-preview-pdf"]').click();
    });
    await flushAll();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/preview/pdf/', {},
      {responseType: 'arraybuffer', timeout: 180000});
    expect(window.URL.createObjectURL).toHaveBeenCalled();
    expect(document.querySelector('[data-testid="form-sample-pdf-iframe"]')).toBeTruthy();
    const meta = document.querySelector('[data-testid="form-sample-pdf-meta"]');
    expect(meta.textContent).toContain('共 2 页');
    expect(meta.textContent).toContain('A4 210x297mm');
    // 关闭弹窗释放 blob URL
    await act(async () => {
      document.querySelector('.ant-modal-close').click();
    });
    await flush();
    expect(window.URL.revokeObjectURL).toHaveBeenCalled();
    expect(formTemplateStore.samplePdfUrl).toBe('');
    view.cleanup();
  });

  test('有未保存修改：先确认"基于已保存草稿"，确认后才请求', async () => {
    const view = await openEditorWithDraft();
    // 在画布上修改分组名制造脏状态
    const nameInput = document.querySelector(
      '[data-testid="canvas-group-name-gbaseinfo01"]');
    setText(nameInput, '登记信息');
    expect(formTemplateStore.editorTemplate).toBeTruthy();
    mockPdfPost();
    await act(async () => {
      document.querySelector('[data-testid="editor-preview-pdf"]').click();
    });
    await flush();
    expect(mockHttpPost).not.toHaveBeenCalled();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    expect(confirm.textContent).toContain('基于已保存的草稿生成');
    await clickConfirmButton('继续预览');
    await flushAll();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    view.cleanup();
  });

  test('生成失败：显示失败态，重新生成再次 POST', async () => {
    const view = await openEditorWithDraft();
    mockHttpPost.mockRejectedValue('生成失败');
    await act(async () => {
      document.querySelector('[data-testid="editor-preview-pdf"]').click();
    });
    await flushAll();
    expect(document.querySelector('[data-testid="form-sample-pdf-iframe"]')).toBeNull();
    const retry = document.querySelector('[data-testid="form-sample-pdf-retry"]');
    expect(retry).toBeTruthy();
    mockPdfPost();
    await act(async () => { retry.click(); });
    await flushAll();
    expect(mockHttpPost).toHaveBeenCalledTimes(2);
    expect(document.querySelector('[data-testid="form-sample-pdf-iframe"]')).toBeTruthy();
    view.cleanup();
  });
});

// —— 台账详情夹具 ——

const LEDGER_FORM = {
  protocol_version: 1,
  groups: [
    {id: 'g_base', name: '基本信息', kind: 'fields', fields: [
      {id: 'f_date', name: '维护日期', type: 'date', required: true,
       description: '', unit: '', options: []}]},
  ],
};

function makeLedgerDetail(status = 'draft', values = {}) {
  return {
    id: 55, ledger_no: 'EL-WM-20261019-0001', ledger_type: 'week_month',
    status, system_name: 'ILS 系统', maintenance_period: '2026-10-19',
    created_by_name: '李四', completed_at: null, void_reason: '',
    corrections: [],
    form: {
      record_id: 9, values,
      editable: status === 'draft', voided: status === 'void',
      version: {
        id: 3, template: 12, version_no: 2, template_name: '周维护数字表单',
        ledger_type: 'week_month', field_count: 1,
        published_at: '2026-10-19T08:00:00', form: LEDGER_FORM,
      },
    },
  };
}

async function createDraftStore(values = {}) {
  mockHttpGet.mockResolvedValue({data: makeLedgerDetail('draft', values)});
  const store = new FormLedgerStore();
  await store.fetchDetail(55);
  return store;
}

describe('数字表单台账详情：PDF 预览与导出', () => {
  beforeEach(() => {
    mockHttpGet.mockReset();
    mockHttpPost.mockReset();
    mockHttpPut.mockReset();
    mockExportFile.mockReset();
    window.URL.createObjectURL.mockClear();
    window.URL.revokeObjectURL.mockClear();
    removeConfirmModals();
  });

  test('详情页展示预览/导出按钮；无未保存修改直接生成预览', async () => {
    const store = await createDraftStore();
    const view = render(h(FormLedgerDetail, {store, onBack: jest.fn()}));
    expect(document.querySelector('[data-testid="form-pdf-preview"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="form-pdf-export"]')).toBeTruthy();
    mockPdfPost();
    await act(async () => {
      document.querySelector('[data-testid="form-pdf-preview"]').click();
    });
    await flushAll();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-ledgers/55/preview/pdf/', {},
      {responseType: 'arraybuffer', timeout: 180000});
    expect(document.querySelector('[data-testid="form-pdf-preview-iframe"]')).toBeTruthy();
    const meta = document.querySelector('[data-testid="form-pdf-preview-meta"]');
    expect(meta.textContent).toContain('共 2 页');
    expect(meta.textContent).toContain('基于最近一次保存的填写内容生成');
    view.cleanup();
  });

  test('有未保存修改：预览先确认"基于最近一次保存的内容"，确认后才请求', async () => {
    const store = await createDraftStore();
    const view = render(h(FormLedgerDetail, {store, onBack: jest.fn()}));
    const dateInput = view.container.querySelector('#anchor-f_date input');
    await pickDate(dateInput);
    expect(store.hasUnsaved).toBe(true);
    mockPdfPost();
    await act(async () => {
      document.querySelector('[data-testid="form-pdf-preview"]').click();
    });
    await flush();
    expect(mockHttpPost).not.toHaveBeenCalled();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    expect(confirm.textContent).toContain('基于最近一次保存的填写内容生成');
    await clickConfirmButton('继续生成');
    await flushAll();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    view.cleanup();
  });

  test('导出 PDF：未保存先确认，确认后走公共 exportFile 下载', async () => {
    const store = await createDraftStore();
    const view = render(h(FormLedgerDetail, {store, onBack: jest.fn()}));
    const dateInput = view.container.querySelector('#anchor-f_date input');
    await pickDate(dateInput);
    expect(store.hasUnsaved).toBe(true);
    mockExportFile.mockResolvedValue(undefined);
    await act(async () => {
      document.querySelector('[data-testid="form-pdf-export"]').click();
    });
    await flush();
    expect(mockExportFile).not.toHaveBeenCalled();
    await clickConfirmButton('继续生成');
    await flushAll();
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/equipment-lifecycle/form-ledgers/55/export/pdf/',
      method: 'post',
    }));
    view.cleanup();
  });

  test('详情刷新（保存回写）后旧预览失效：blob URL 释放', async () => {
    const store = await createDraftStore();
    const view = render(h(FormLedgerDetail, {store, onBack: jest.fn()}));
    mockPdfPost();
    await act(async () => {
      store.fetchPdfPreview().catch(() => {});
    });
    await flushAll();
    expect(store.pdfPreviewUrl).toBe('blob:mock');
    // 修改值 → 保存回写新详情 → 旧预览必须失效
    act(() => {
      store.edit('field', 'f_date', '2026-10-21');
    });
    mockHttpPut.mockResolvedValue({data: makeLedgerDetail(
      'draft', {f_date: '2026-10-21'})});
    await act(async () => {
      store.saveValues().catch(() => {});
    });
    await flushAll();
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock');
    expect(store.pdfPreviewUrl).toBe('');
    expect(store.pdfPreviewMeta).toBeNull();
    view.cleanup();
  });
});
