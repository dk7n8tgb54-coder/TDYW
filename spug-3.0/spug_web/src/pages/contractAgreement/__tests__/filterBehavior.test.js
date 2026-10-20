/**
 * 合同协议——顶部筛选区统一交互行为测试（2026-10-20）。
 *
 * 真实渲染页面组件（ReactDOM + jsdom，仓库惯例），仅 mock libs.http，
 * 参照运行处置记录 RecordFilters 的统一口径验证：
 * - 合同名称为常驻文本草稿；合同编号/签约方为折叠区文本草稿，查询按钮/
 *   回车提交后才生效；
 * - 类型/状态/费用下拉与截止日期变更即查询，但不代提交文本草稿；
 * - 费用"无"（false）是有效布尔条件：请求携带 has_fee=false 且计入
 *   "更多筛选"数量；
 * - 查询或条件变更后回到第 1 页；翻页取数使用已提交条件；
 * - 重置清空常驻与折叠区全部条件及草稿，回到第 1 页并刷新。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
  syncAttachmentCount: jest.fn(),
}));

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;
let store = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockReset();
  mockHttpGet.mockResolvedValue({records: [], total: 0});
  store = require('../store').default;
  store.records = [];
  store.total = 0;
  store.pageNum = 1;
  store.pageSize = 20;
  store.f_contract_name = undefined;
  store.f_contract_no = undefined;
  store.f_contract_type = undefined;
  store.f_status = undefined;
  store.f_signing_party = undefined;
  store.f_has_fee = undefined;
  store.f_valid_end_range = undefined;
  store.input_contract_name = '';
  store.input_contract_no = '';
  store.input_signing_party = '';
  store.formVisible = false;
  store.detailVisible = false;
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  document.querySelectorAll('.ant-select-dropdown').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function renderPage() {
  const Index = require('../index').default;
  await act(async () => {
    ReactDOM.render(React.createElement(Index), container);
  });
  await act(async () => {
    await flush();
  });
}

function listCalls() {
  return mockHttpGet.mock.calls.filter(([url]) => url.endsWith('/api/contract-agreement/'));
}

function lastListParams() {
  const calls = listCalls();
  return calls[calls.length - 1][1].params;
}

function findButton(label) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === label);
}

function controlOf(label) {
  const item = Array.from(container.querySelectorAll('.ant-form-item'))
    .find(n => {
      const labelEl = n.querySelector('.ant-form-item-label label');
      return labelEl && labelEl.textContent === label;
    });
  return item ? item.querySelector('.ant-form-item-control') : null;
}

async function typeText(label, value) {
  const input = controlOf(label).querySelector('input');
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    await flush();
  });
  return input;
}

async function pressEnter(input) {
  const enterEvent = new KeyboardEvent('keydown', {bubbles: true});
  Object.defineProperty(enterEvent, 'keyCode', {get: () => 13});
  Object.defineProperty(enterEvent, 'which', {get: () => 13});
  await act(async () => {
    input.dispatchEvent(enterEvent);
    await flush();
  });
}

async function pickOption(label, optionText) {
  const selector = controlOf(label).querySelector('.ant-select-selector');
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    selector.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    await flush();
  });
  const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
    .find(o => o.textContent === optionText);
  await act(async () => {
    option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

function moreFilterLink() {
  return Array.from(container.querySelectorAll('a'))
    .find(a => (a.textContent || '').includes('更多筛选') ||
      (a.textContent || '').includes('收起筛选'));
}

async function toggleAdvanced() {
  await act(async () => {
    moreFilterLink().dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

describe('合同协议筛选区统一交互', () => {
  it('挂载即无筛选请求列表', async () => {
    await renderPage();
    expect(listCalls().length).toBe(1);
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
  });

  it('常驻/折叠区文本均为草稿：输入不请求，查询提交后生效', async () => {
    await renderPage();
    await typeText('合同名称', '通信设备采购');
    expect(listCalls().length).toBe(1);
    await toggleAdvanced();
    await typeText('合同编号', 'HT-2026-08');
    await typeText('签约方', '某通信公司');
    expect(listCalls().length).toBe(1);
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams().contract_name).toBe('通信设备采购');
    expect(lastListParams().contract_no).toBe('HT-2026-08');
    expect(lastListParams().signing_party).toBe('某通信公司');
    expect(lastListParams().page).toBe(1);
  });

  it('费用"无"（false）为有效条件：请求携带 has_fee=false 且计数为 1', async () => {
    await renderPage();
    await toggleAdvanced();
    await pickOption('费用', '无');
    expect(listCalls().length).toBe(2);
    expect(lastListParams().has_fee).toBe(false);
    // 收起后 false 条件计入更多筛选数量
    await toggleAdvanced();
    expect(moreFilterLink().textContent).toBe('更多筛选（1）');
  });

  it('状态下拉变更即查询，但不代提交未执行的文本草稿', async () => {
    await renderPage();
    await typeText('合同名称', '未提交草稿');
    await pickOption('状态', '即将到期');
    expect(listCalls().length).toBe(2);
    expect(lastListParams().status).toBe('expiring');
    expect(lastListParams().contract_name).toBeUndefined();
    expect(store.input_contract_name).toBe('未提交草稿');
  });

  it('翻页取数使用已提交条件，草稿不混入', async () => {
    await renderPage();
    await typeText('合同名称', '已提交名称');
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    store.input_contract_name = '翻页时的未提交草稿';
    store.pageNum = 2;
    await act(async () => {
      store.fetchRecords();
      await flush();
    });
    expect(lastListParams().page).toBe(2);
    expect(lastListParams().contract_name).toBe('已提交名称');
  });

  it('重置清空常驻与折叠区全部条件及草稿并回到第 1 页', async () => {
    store.f_status = 'normal';
    store.f_has_fee = false;
    store.f_contract_no = 'HT-OLD';
    store.pageNum = 2;
    await renderPage();
    await typeText('合同名称', '新草稿');
    await act(async () => {
      findButton('重置').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
    expect(controlOf('合同名称').querySelector('input').value).toBe('');
    expect(store.f_has_fee).toBeUndefined();
    expect(store.f_contract_no).toBeUndefined();
    expect(store.input_contract_name).toBe('');
    expect(store.input_contract_no).toBe('');
    expect(store.input_signing_party).toBe('');
    expect(moreFilterLink().textContent).toBe('更多筛选');
  });
});
