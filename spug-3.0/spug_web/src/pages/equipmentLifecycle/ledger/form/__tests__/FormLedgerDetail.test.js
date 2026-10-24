/**
 * 数字表单台账填写页行为测试（2026-10-21 数字表单路线）。
 *
 * 真实渲染（ReactDOM + jsdom）+ mock libs/http，验证：
 * - 详情按版本快照渲染表单（分组/字段/矩阵），草稿可编辑、已完成只读；
 * - 编辑 → 保存草稿 PUT values；完成填写先保存再 POST complete
 *   （脏值保存成功后才发起完成）；
 * - 必填未填时"完成填写"不发起请求，弹确认定位第一项；
 * - 进度条与"必填未填 N 项"真实统计；
 * - 返回列表前未保存修改先确认（不保存并返回才清空）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

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
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell, AuthButton: (props) => React.createElement('button', {
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

const FormLedgerDetail = require('../FormLedgerDetail').default;
const {FormLedgerStore} = require('../formLedgerStore');

const FORM = {
  protocol_version: 1,
  groups: [
    {id: 'g_base', name: '基本信息', kind: 'fields', fields: [
      {id: 'f_date', name: '维护日期', type: 'date', required: true,
       description: '', unit: '', options: []},
      {id: 'f_abn', name: '外观', type: 'normal_abnormal', required: true,
       description: '', unit: '', options: []},
    ]},
    {id: 'g_matrix', name: '多机对比', kind: 'matrix',
     columns: [{id: 'c_a', name: 'A 机'}, {id: 'c_b', name: 'B 机'}],
     fields: [
       {id: 'r_volt', name: '电压', type: 'number', required: false,
        description: '', unit: 'V', options: []},
     ]},
  ],
};

function makeDetail(status = 'draft', values = {}) {
  return {
    id: 55, ledger_no: 'EL-WM-20261019-0001', ledger_type: 'week_month',
    status, system_name: 'ILS 系统', maintenance_period: '2026-10-19',
    created_by_name: '张三', completed_at: status === 'completed' ? '2026-10-21T08:00:00' : null,
    void_reason: '',
    form: {
      record_id: 9, values, editable: status === 'draft', voided: status === 'void',
      version: {id: 3, version_no: 2, template_name: '周维护数字表单', form: FORM},
    },
  };
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function renderDetail(store, onBack = jest.fn()) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const view = ReactDOM.render(
    h(FormLedgerDetail, {store, onBack}), container);
  return {container, view, onBack, cleanup: () => {
    ReactDOM.unmountComponentAtNode(container);
    removeConfirmModals();
    container.remove();
  }};
}

function removeConfirmModals() {
  document.querySelectorAll('.ant-modal-confirm, .ant-modal-root')
    .forEach(node => node.remove());
}

function setText(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

/** date 字段 DatePicker 面板点选（jsdom 真实交互路径），返回所选日期串。 */
async function pickDate(input, title) {
  await act(async () => {
    input.focus();
    input.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    input.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    input.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
  const cell = title
    ? document.querySelector(`.ant-picker-cell-in-view td[title="${title}"] .ant-picker-cell-inner`)
    : document.querySelector('.ant-picker-cell-in-view .ant-picker-cell-inner');
  expect(cell).toBeTruthy();
  const cellDate = cell.closest('td').getAttribute('title');
  await act(async () => {
    cell.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
  return cellDate;
}

async function createDraftStore(values = {}) {
  mockHttpGet.mockResolvedValue({data: makeDetail('draft', values)});
  const store = new FormLedgerStore();
  await store.fetchDetail(55);
  return store;
}

describe('FormLedgerDetail 填写页：渲染与进度', () => {
  test('按版本快照渲染分组/字段/矩阵，草稿可编辑且进度真实统计', async () => {
    const store = await createDraftStore();
    const view = renderDetail(store);
    expect(document.body.textContent).toContain('数字表单台账：EL-WM-20261019-0001');
    expect(document.body.textContent).toContain('基本信息');
    expect(document.body.textContent).toContain('多机对比');
    expect(document.body.textContent).toContain('周维护数字表单');
    expect(document.body.textContent).toContain('v2');
    // 进度：普通 2 项 + 矩阵 2 格 = 4 单元，全部未填
    expect(document.querySelector('[data-testid="form-fill-progress"]')).toBeTruthy();
    expect(document.body.textContent).toContain('已填 0/4');
    // 必填未填 2 项（f_date + f_abn），提供定位入口
    const locate = document.querySelector('[data-testid="form-locate-missing"]');
    expect(locate).toBeTruthy();
    expect(locate.textContent).toContain('必填未填 2 项');
    // 保存/完成按钮在位
    expect(document.querySelector('[data-testid="form-save-draft"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="form-complete"]')).toBeTruthy();
    view.cleanup();
  });

  test('编辑字段后保存：PUT 携带整体 values，保存后脏值清零', async () => {
    const store = await createDraftStore();
    const view = renderDetail(store);
    const dateInput = view.container.querySelector('#anchor-f_date input');
    // date 字段为 DatePicker：面板点选提交（仍以 YYYY-MM-DD 字符串入 values）
    const picked = await pickDate(dateInput);
    expect(store.values.f_date).toBe(picked);
    expect(picked).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    mockHttpPut.mockResolvedValue({data: makeDetail(
      'draft', {f_date: picked})});
    await act(async () => {
      document.querySelector('[data-testid="form-save-draft"]').click();
    });
    await flush();
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-ledgers/55/', {
        values: expect.objectContaining({f_date: picked})});
    expect(store.valuesDirty).toBe(false);
    view.cleanup();
  });
});

describe('FormLedgerDetail 填写页：保存/完成/返回流程', () => {

  test('必填未填时完成填写不发起请求，弹确认提示定位', async () => {
    const store = await createDraftStore();
    const view = renderDetail(store);
    await act(async () => {
      document.querySelector('[data-testid="form-complete"]').click();
    });
    await flush();
    expect(mockHttpPost).not.toHaveBeenCalled();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    expect(confirm.textContent).toContain('还有 2 项必填未填写');
    view.cleanup();
  });

  test('必填填齐后完成填写：先 PUT 保存未保存值再 POST complete', async () => {
    const store = await createDraftStore();
    const view = renderDetail(store);
    const dateInput = view.container.querySelector('#anchor-f_date input');
    const picked = await pickDate(dateInput);
    const radio = view.container.querySelector('#anchor-f_abn input[value="normal"]');
    await act(async () => { radio.click(); });
    mockHttpPut.mockResolvedValue({data: makeDetail(
      'draft', {f_date: picked, f_abn: 'normal'})});
    mockHttpPost.mockResolvedValue({data: makeDetail(
      'completed', {f_date: picked, f_abn: 'normal'})});
    await act(async () => {
      document.querySelector('[data-testid="form-complete"]').click();
    });
    await flush();
    expect(mockHttpPut).toHaveBeenCalled();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-ledgers/55/complete/', {source: 'form-detail'});
    expect(store.detail.status).toBe('completed');
    view.cleanup();
  });

  test('已完成台账只读：输入禁用、无保存/完成按钮', async () => {
    mockHttpGet.mockResolvedValue({data: makeDetail('completed', {f_date: '2026-10-20'})});
    const store = new FormLedgerStore();
    await store.fetchDetail(55);
    const view = renderDetail(store);
    await act(async () => { await flush(); });
    expect(document.querySelector('[data-testid="form-save-draft"]')).toBeNull();
    expect(document.querySelector('[data-testid="form-complete"]')).toBeNull();
    const dateInput = view.container.querySelector('#anchor-f_date input');
    expect(dateInput.disabled).toBe(true);
    expect(dateInput.value).toBe('2026-10-20');
    view.cleanup();
  });

  test('返回列表前有未保存修改先确认（确认后不保存直接返回）', async () => {
    const store = await createDraftStore();
    const onBack = jest.fn();
    const view = renderDetail(store, onBack);
    const dateInput = view.container.querySelector('#anchor-f_date input');
    await pickDate(dateInput);
    await act(async () => {
      document.querySelector('[data-testid="form-detail-back"]').click();
    });
    await flush();
    expect(onBack).not.toHaveBeenCalled();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    expect(confirm.textContent).toContain('有未保存的修改');
    const okBtn = Array.from(confirm.querySelectorAll('button'))
      .find(node => node.textContent.replace(/\s/g, '') === '不保存并返回');
    await act(async () => { okBtn.click(); });
    await flush();
    expect(onBack).toHaveBeenCalled();
    view.cleanup();
  });

  test('无未保存修改时返回列表直接返回', async () => {
    const store = await createDraftStore();
    const onBack = jest.fn();
    const view = renderDetail(store, onBack);
    await act(async () => {
      document.querySelector('[data-testid="form-detail-back"]').click();
    });
    await flush();
    expect(onBack).toHaveBeenCalled();
    view.cleanup();
  });
});
