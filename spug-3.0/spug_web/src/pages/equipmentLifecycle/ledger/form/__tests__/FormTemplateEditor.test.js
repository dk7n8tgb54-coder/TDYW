/**
 * 数字表单模板编辑器草稿加载与保存闭环行为测试（2026-10-22 三栏改版；
 * 2026-10-23 P1 交互整理）。
 *
 * 真实渲染（ReactDOM + jsdom）+ mock libs/http，验证：
 * - 从列表摘要打开编辑器时按 id 拉取完整详情（列表行无 draft）；
 * - 加载中 / 加载失败 / 无草稿 三态分离；失败禁用保存/发布/预览/载入示例；
 * - 快速切换模板时旧请求不覆盖新模板内容（竞态防护）；
 * - 保存→关闭→重新打开后分组、字段、矩阵行列与稳定 id 完整保留；
 * - 发布（先保存再 POST publish）、载入示例、模板管理页列表行操作；
 * - 撤销回基线视为干净、无 dirty 不发保存请求（dirty 短路）；
 * - 关闭编辑器确认丢弃后清除工作页签未保存登记（真实 workTabStore）；
 * - PUT 成功即更新基线：列表刷新失败不把已保存内容判成未保存，
 *   随后发布不再重复 PUT。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement('button', {
    type: 'button', 'data-testid': props['data-testid'],
    'data-btn-type': props.type, onClick: props.onClick, disabled: props.disabled,
  }, props.children);
  const SearchForm = (props) => React.createElement('div', null, props.children);
  SearchForm.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell, AuthButton, AuthCard: Shell, AuthFragment: Shell,
    Breadcrumb, SearchForm, ExportButton: AuthButton, TableCard: Shell,
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

const FormTemplateEditor = require('../FormTemplateEditor').default;
const FormTemplatePage = require('../FormTemplatePage').default;
const {formTemplateStore} = require('../formTemplateStore');
const workTabStore = require('layout/workTabStore').default;

const DRAFT_FORM = {
  protocol_version: 2,
  groups: [
    {id: 'gbaseinfo01', name: '基本信息', description: '', kind: 'fields',
     item_name: '', columns: [], fields: [
       {id: 'fmaintdate1', name: '维护日期', type: 'date', required: true,
        description: '', unit: '', options: []},
       {id: 'fremark001', name: '备注', type: 'textarea', required: false,
        description: '', unit: '', options: []},
     ]},
    {id: 'gmultidev01', name: '多机运行对比', description: '', kind: 'matrix',
     item_name: '', columns: [
       {id: 'cdevicema01', name: 'A 机'}, {id: 'cdevicemb01', name: 'B 机'}],
     fields: [
       {id: 'rvoltage001', name: '输出电压', type: 'number', required: false,
        description: '', unit: 'V', options: []},
       {id: 'rlinkstate1', name: '通讯状态', type: 'normal_abnormal', required: false,
        description: '', unit: '', options: []},
     ]},
  ],
};

const SAMPLE_FORM = {
  protocol_version: 2,
  groups: [
    {id: 'gbaseinfo01', name: '基本信息', description: '', kind: 'fields',
     item_name: '', columns: [], fields: [
       {id: 'fmaintdate1', name: '维护日期', type: 'date', required: true,
        description: '', unit: '', options: []}]},
    {id: 'gmeasuremt1', name: '电气参数测量', description: '', kind: 'repeat',
     item_name: '测量项目', columns: [], fields: [
       {id: 'fitemname01', name: '项目名称', type: 'text', required: true,
        description: '', unit: '', options: []}]},
    {id: 'gmultidev01', name: '多机运行对比', description: '', kind: 'matrix',
     item_name: '', columns: [{id: 'cdevicema01', name: 'A 机'}],
     fields: [{id: 'rvoltage001', name: '输出电压', type: 'number', required: false,
               description: '', unit: 'V', options: []}]},
  ],
};

/** 模板列表行摘要：与后端 list_templates 同构，不含 draft/draft_state。 */
function makeSummary(overrides) {
  return Object.assign({
    id: 12, name: '周维护数字表单', ledger_type: 'week_month',
    description: '', system: null, system_name: '', generation_period: '',
    generation_period_text: '待配置', is_active: true,
    has_draft: true, latest_version_no: 0, versions_count: 0, ledgers_count: 0,
    status: 'draft',
  }, overrides);
}

/** 模板完整详情：与后端 template_detail 同构（含 draft.form 与 draft_state）。
 * opts: {form: 覆盖草稿表单, id/name: 覆盖模板标识}。 */
function makeDetail(opts) {
  opts = opts || {};
  const identity = (opts.id !== undefined || opts.name !== undefined)
    ? {id: opts.id, name: opts.name} : undefined;
  return Object.assign(makeSummary(identity), {
    draft: {form: opts.form || DRAFT_FORM, updated_at: '2026-10-21T10:00:00',
            updated_by: '张三'},
    draft_state: {relation: 'modified', latest_version_no: 0, versions_count: 0,
                  field_count: 4, updated_at: '2026-10-21T10:00:00'},
  });
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const flushAll = async () => { await flush(); await flush(); await flush(); };

function render(node) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  ReactDOM.render(node, container);
  return {container, cleanup: () => {
    ReactDOM.unmountComponentAtNode(container);
    document.querySelectorAll('.ant-modal-root, .ant-drawer-root, .ant-modal-confirm, .ant-popover')
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

function resetStore() {
  const store = formTemplateStore;
  store.list = []; store.isFetching = false; store.detail = null;
  store.createVisible = false; store.createOptions = null; store.creating = false;
  store.editorVisible = false; store.editorTemplate = null;
  store.editorLoading = false; store.editorLoadError = '';
  store.savingDraft = false; store.publishing = false;
  store.versionsVisible = false; store.versionsTemplate = null;
  store.versions = []; store.versionDetail = null;
  store.keyword = ''; store.ledgerTypeFilter = '';
}

function mockDetailGet(detail) {
  mockHttpGet.mockImplementation(url => {
    if (String(url).endsWith('/form-templates/12/')) {
      return Promise.resolve({data: detail});
    }
    return Promise.reject('意外请求：' + url);
  });
}

beforeEach(() => {
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
  mockHttpDelete.mockReset();
  resetStore();
});

test('从列表摘要打开编辑器：按 id 拉完整详情，加载中不渲染可编辑内容', async () => {
  resetStore();
  mockDetailGet(makeDetail());
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/form-templates/12/');
  expect(document.body.textContent).toContain('正在加载模板草稿');
  expect(document.querySelector('[data-testid="form-template-canvas"]')).toBeNull();
  await act(flushAll);
  expect(document.body.textContent).toContain('基本信息');
  expect(document.body.textContent).toContain('多机运行对比');
  const nameInput = document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]');
  expect(nameInput.value).toBe('维护日期');
  expect(document.querySelector('[data-testid="canvas-matrix-row-name-rvoltage001"]')).toBeTruthy();
  expect(document.querySelector('[data-testid="editor-save-draft"]').disabled).toBe(false);
  view.cleanup();
});

test('确实没有草稿：空画布可编辑并给出引导，添加分组后保存', async () => {
  resetStore();
  const detail = makeDetail();
  detail.draft = null;
  detail.draft_state = {relation: 'no_draft', latest_version_no: 0,
                        versions_count: 0, field_count: 0};
  mockDetailGet(detail);
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  expect(document.body.textContent).toContain('尚未编辑过表单内容');
  expect(document.querySelector('[data-testid="form-template-canvas"]')).toBeTruthy();
  await act(async () => {
    document.querySelector('[data-testid="editor-add-group-fields"]').click();
  });
  await act(flushAll);
  const groupInput = document.querySelector('[data-testid^="canvas-group-name-"]');
  expect(groupInput.value).toBe('填写项目');
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  const form = mockHttpPut.mock.calls[0][1].form;
  expect(form.groups.length).toBe(1);
  expect(form.groups[0].kind).toBe('fields');
  expect(form.groups[0].fields[0].name).toBe('填写内容 1');
  view.cleanup();
});

test('加载失败：错误页禁用保存/发布/预览/载入示例，重试成功后恢复', async () => {
  resetStore();
  mockHttpGet.mockImplementation(url =>
    String(url).endsWith('/form-templates/12/')
      ? Promise.reject('模板不存在') : Promise.reject('意外请求'));
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  expect(document.body.textContent).toContain('模板草稿加载失败');
  expect(document.body.textContent).toContain('模板不存在');
  expect(document.querySelector('[data-testid="form-template-canvas"]')).toBeNull();
  expect(document.querySelector('[data-testid="editor-save-draft"]').disabled).toBe(true);
  expect(document.querySelector('[data-testid="editor-publish"]').disabled).toBe(true);
  expect(document.querySelector('[data-testid="editor-preview"]').disabled).toBe(true);
  expect(document.querySelector('[data-testid="editor-load-sample"]').disabled).toBe(true);
  mockDetailGet(makeDetail());
  await act(async () => {
    document.querySelector('[data-testid="editor-load-retry"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="form-template-canvas"]')).toBeTruthy();
  expect(document.querySelector('[data-testid="editor-save-draft"]').disabled).toBe(false);
  view.cleanup();
});

test('快速切换模板：先打开的慢请求不覆盖后打开的模板内容', async () => {
  resetStore();
  let resolveA;
  const detailB = makeDetail({id: 12, name: '乙模板'});
  mockHttpGet.mockImplementation(url => {
    const target = String(url);
    if (target.endsWith('/form-templates/11/')) {
      return new Promise(resolve => { resolveA = resolve; });
    }
    if (target.endsWith('/form-templates/12/')) {
      return Promise.resolve({data: detailB});
    }
    return Promise.reject('意外请求：' + target);
  });
  act(() => { formTemplateStore.openEditor(makeSummary({id: 11, name: '甲模板'})); });
  act(() => { formTemplateStore.openEditor(makeSummary({id: 12, name: '乙模板'})); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  expect(formTemplateStore.editorTemplate.id).toBe(12);
  expect(document.querySelector('[data-testid="form-template-canvas"]')).toBeTruthy();
  await act(async () => {
    resolveA({data: makeDetail({id: 11, name: '甲模板'})});
  });
  await act(flushAll);
  expect(formTemplateStore.editorTemplate.id).toBe(12);
  expect(formTemplateStore.editorTemplate.name).toBe('乙模板');
  expect(formTemplateStore.editorLoadError).toBe('');
  expect(document.body.textContent).toContain('编辑表单：乙模板');
  view.cleanup();
});

test('保存后关闭重新打开：结构与稳定 id 完整保留，改名结果一致', async () => {
  resetStore();
  mockDetailGet(makeDetail());
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  setText(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]'),
          '维护日期（当月）');
  await act(async () => {
    document.querySelector('[data-testid="canvas-add-field-gbaseinfo01"]').click();
  });
  await act(flushAll);
  const savedForm = JSON.parse(JSON.stringify(DRAFT_FORM));
  savedForm.groups[0].fields[0].name = '维护日期（当月）';
  savedForm.groups[0].fields.push({id: 'fnewadded1', name: '新填写项', type: 'text',
                                   required: false, description: '', unit: '', options: []});
  mockHttpPut.mockResolvedValue({data: makeDetail({form: savedForm})});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const putForm = mockHttpPut.mock.calls[0][1].form;
  expect(putForm.groups[0].fields[0].name).toBe('维护日期（当月）');
  expect(putForm.groups[0].fields[0].id).toBe('fmaintdate1');
  // 关闭后重开：以保存后的草稿为基线
  act(() => { formTemplateStore.closeEditor(); });
  view.cleanup();
  mockDetailGet(makeDetail({form: savedForm}));
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view2 = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  expect(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]').value)
    .toBe('维护日期（当月）');
  expect(document.querySelector('[data-testid="canvas-field-name-fnewadded1"]')).toBeTruthy();
  expect(document.querySelector('[data-testid="canvas-matrix-col-name-cdevicema01"]')).toBeTruthy();
  expect(document.querySelector('[data-testid="canvas-matrix-row-name-rlinkstate1"]')).toBeTruthy();
  view2.cleanup();
});

test('发布：先 publish-check 无阻断，再 PUT 保存，弹窗确认才 POST publish', async () => {
  resetStore();
  act(() => { formTemplateStore.openEditor(makeDetail()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="editor-add-group-fields"]').click();
  });
  await act(flushAll);
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  mockHttpPost.mockImplementation(url => {
    if (String(url).endsWith('/publish-check/')) {
      return Promise.resolve({data: {errors: [], warnings: []}});
    }
    return Promise.resolve({data: {version_no: 1, field_count: 5}});
  });
  await act(async () => {
    document.querySelector('[data-testid="editor-publish"]').click();
  });
  await act(flushAll);
  // 先对当前（未保存）内容无状态预检，无阻断错误后才保存未保存内容
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/form-templates/12/publish-check/',
    expect.objectContaining({
      form: expect.objectContaining({protocol_version: 2})}));
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  // 弹窗确认前不发布
  expect(mockHttpPost).not.toHaveBeenCalledWith(
    '/api/equipment-lifecycle/form-templates/12/publish/');
  expect(document.querySelector('[data-testid="publish-check-confirm"]').disabled)
    .toBe(false);
  await act(async () => {
    document.querySelector('[data-testid="publish-check-confirm"]').click();
  });
  await act(flushAll);
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/form-templates/12/publish/');
  view.cleanup();
});

test('载入示例：GET sample 并填充为当前草稿', async () => {
  resetStore();
  const empty = makeDetail();
  empty.draft = null;
  mockHttpGet.mockImplementation(url => {
    const target = String(url);
    if (target.endsWith('/form-templates/12/')) return Promise.resolve({data: empty});
    if (target.endsWith('/form-templates/sample/')) {
      return Promise.resolve({data: SAMPLE_FORM});
    }
    return Promise.reject('意外请求：' + target);
  });
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="editor-load-sample"]').click();
  });
  await act(flushAll);
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/form-templates/sample/');
  mockHttpPut.mockResolvedValue({data: empty});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const form = mockHttpPut.mock.calls[0][1].form;
  expect(form.groups.map(g => g.kind)).toEqual(['fields', 'repeat', 'matrix']);
  view.cleanup();
});

test('模板管理列表：编辑表单按钮按 id 拉取详情并打开编辑器', async () => {
  resetStore();
  const rows = [makeSummary()];
  mockHttpGet.mockImplementation(url => {
    const target = String(url);
    if (target.endsWith('/form-templates/12/')) {
      return Promise.resolve({data: makeDetail()});
    }
    if (target.includes('create-options')) {
      return Promise.resolve({data: {systems: [], periods: {}}});
    }
    return Promise.resolve({data: rows});
  });
  const view = render(h(FormTemplatePage));
  await act(flushAll);
  expect(document.body.textContent).toContain('周维护数字表单');
  const editButtons = Array.from(document.querySelectorAll('button'))
    .filter(node => node.textContent.includes('编辑表单'));
  expect(editButtons.length).toBe(1);
  await act(async () => { editButtons[0].click(); });
  await act(flushAll);
  expect(formTemplateStore.editorVisible).toBe(true);
  expect(formTemplateStore.editorTemplate.draft).toBeTruthy();
  view.cleanup();
  act(() => { formTemplateStore.closeEditor(); });
});

test('创建模板：响应已是完整详情，直接进入编辑器不再重复拉取', async () => {
  resetStore();
  mockHttpGet.mockImplementation(url => {
    if (String(url).includes('create-options')) {
      return Promise.resolve({data: {systems: [], periods: {}}});
    }
    return Promise.resolve({data: []});
  });
  const view = render(h(FormTemplatePage));
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="form-tpl-create"]').click();
  });
  await act(flushAll);
  const modal = document.querySelector('.ant-modal');
  setText(modal.querySelector('input'), '新模板');
  const created = makeDetail({name: '新模板'});
  created.draft = null;
  created.draft_state = {relation: 'no_draft', latest_version_no: 0,
                         versions_count: 0, field_count: 0};
  mockHttpPost.mockResolvedValue({data: created});
  const okButton = Array.from(modal.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === '创建并编辑表单');
  await act(async () => { okButton.click(); });
  await act(flushAll);
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/form-templates/', expect.objectContaining({
      name: '新模板', ledger_type: 'week_month'}));
  // 创建响应含 draft_state → 免二次详情拉取，直接进入无草稿空画布
  expect(formTemplateStore.editorVisible).toBe(true);
  expect(formTemplateStore.editorLoading).toBe(false);
  expect(document.body.textContent).toContain('尚未编辑过表单内容');
  view.cleanup();
  act(() => { formTemplateStore.closeEditor(); });
});

test('保存草稿 dirty 短路：无修改不发请求；撤销回基线视为干净', async () => {
  resetStore();
  // 保存草稿成功后会刷新列表（GET /form-templates/），一并 mock 返回
  mockHttpGet.mockImplementation(url => {
    const target = String(url);
    if (target.endsWith('/form-templates/12/')) {
      return Promise.resolve({data: makeDetail()});
    }
    if (target.endsWith('/form-templates/')) {
      return Promise.resolve({data: []});
    }
    return Promise.reject('意外请求：' + target);
  });
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  // 无 dirty 修改：不发送保存请求
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  expect(mockHttpPut).not.toHaveBeenCalled();
  // 修改后显示未保存标记，保存成功一次
  setText(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]'),
          '维护日期（修订）');
  expect(document.body.textContent).toContain('有未保存修改');
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).not.toContain('有未保存修改');
  // 已保存基线上再次点击保存：dirty 短路，不重复发送
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  // 修改后撤销回保存基线 → dirty 归零，保存仍不发请求
  setText(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]'),
          '维护日期（修订二）');
  await act(async () => {
    document.querySelector('[data-testid="editor-undo"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]').value)
    .toBe('维护日期（修订）');
  expect(document.body.textContent).not.toContain('有未保存修改');
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  view.cleanup();
});

test('关闭编辑器确认丢弃修改后，清除工作页签未保存登记', async () => {
  resetStore();
  mockDetailGet(makeDetail());
  const libs = require('libs');
  libs.history.location = {pathname: '/el/form-ledger-templates'};
  workTabStore.unsavedSources = {};
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  // 修改 → dirty → 页签登记出现
  setText(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]'),
          '维护日期（未保存）');
  await act(flushAll);
  expect(workTabStore.hasUnsaved('/el/form-ledger-templates')).toBe(true);
  // 点击抽屉关闭 → 确认弹窗 →「不保存并关闭」
  await act(async () => {
    document.querySelector('.ant-drawer-close').click();
  });
  await act(flushAll);
  const discard = Array.from(document.querySelectorAll('.ant-modal-confirm button'))
    .find(node => node.textContent.replace(/\s/g, '') === '不保存并关闭');
  expect(discard).toBeTruthy();
  await act(async () => { discard.click(); });
  await act(flushAll);
  expect(formTemplateStore.editorVisible).toBe(false);
  // 本地草稿已丢弃：dirty 归零，页签未保存登记随之清除
  expect(workTabStore.hasUnsaved('/el/form-ledger-templates')).toBe(false);
  libs.history.location = undefined;
  view.cleanup();
});

test('保存：PUT 成功即更新基线（列表刷新失败不判未保存），随后发布不再重复保存', async () => {
  resetStore();
  mockHttpGet.mockImplementation(url => {
    const target = String(url);
    if (target.endsWith('/form-templates/12/')) {
      return Promise.resolve({data: makeDetail()});
    }
    // 列表接口持续失败：只影响列表展示，不影响保存与发布
    return Promise.reject('列表服务不可用');
  });
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  setText(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]'),
          '维护日期（修订）');
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  mockHttpPost.mockImplementation(url => {
    if (String(url).endsWith('/publish-check/')) {
      return Promise.resolve({data: {errors: [], warnings: []}});
    }
    return Promise.resolve({data: {version_no: 1, field_count: 5}});
  });
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  // PUT 成功即视为已保存：列表刷新失败也不把已保存内容判成未保存
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).not.toContain('有未保存修改');
  // 发布：dirty 已归零不再重复 PUT；publish-check 通过后弹窗确认才发布
  await act(async () => {
    document.querySelector('[data-testid="editor-publish"]').click();
  });
  await act(flushAll);
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/form-templates/12/publish-check/',
    expect.anything());
  await act(async () => {
    document.querySelector('[data-testid="publish-check-confirm"]').click();
  });
  await act(flushAll);
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/form-templates/12/publish/');
  view.cleanup();
});

test('保存中关闭编辑器：过期保存回调不更新基线、不重新登记未保存', async () => {
  resetStore();
  mockDetailGet(makeDetail());
  const libs = require('libs');
  libs.history.location = {pathname: '/el/form-ledger-templates'};
  workTabStore.unsavedSources = {};
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  // 修改 → dirty → 页签登记
  setText(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]'),
          '维护日期（保存中）');
  await act(flushAll);
  expect(workTabStore.hasUnsaved('/el/form-ledger-templates')).toBe(true);
  // 保存请求挂起（PUT 尚未返回）
  let resolveSave;
  mockHttpPut.mockImplementation(
    () => new Promise(resolve => { resolveSave = resolve; }));
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  // 保存未结束时确认关闭（丢弃修改）
  await act(async () => {
    document.querySelector('.ant-drawer-close').click();
  });
  await act(flushAll);
  const discard = Array.from(document.querySelectorAll('.ant-modal-confirm button'))
    .find(node => node.textContent.replace(/\s/g, '') === '不保存并关闭');
  await act(async () => { discard.click(); });
  await act(flushAll);
  expect(formTemplateStore.editorVisible).toBe(false);
  expect(workTabStore.hasUnsaved('/el/form-ledger-templates')).toBe(false);
  // 随后 PUT 返回成功：过期回调不得更新基线、不得重新登记未保存
  await act(async () => { resolveSave({data: makeDetail()}); });
  await act(flushAll);
  expect(workTabStore.hasUnsaved('/el/form-ledger-templates')).toBe(false);
  // 重新打开：以服务端草稿干净载入
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  await act(flushAll);
  expect(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]').value)
    .toBe('维护日期');
  expect(document.body.textContent).not.toContain('有未保存修改');
  expect(workTabStore.hasUnsaved('/el/form-ledger-templates')).toBe(false);
  libs.history.location = undefined;
  view.cleanup();
});

test('列表刷新挂起不阻塞保存结果与基线更新', async () => {
  resetStore();
  mockHttpGet.mockImplementation(url => {
    const target = String(url);
    if (target.endsWith('/form-templates/12/')) {
      return Promise.resolve({data: makeDetail()});
    }
    // 列表请求挂起迟迟不返回
    return new Promise(() => {});
  });
  act(() => { formTemplateStore.openEditor(makeSummary()); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  setText(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]'),
          '维护日期（修订）');
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  // PUT 成功即保存成功：列表挂起不拖住保存 Promise，基线照常更新
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).not.toContain('有未保存修改');
  view.cleanup();
});
