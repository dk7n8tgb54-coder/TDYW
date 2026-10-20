/**
 * 无线电台执照——顶部筛选区统一交互行为测试（2026-10-20）。
 *
 * 真实渲染页面组件（ReactDOM + jsdom，仓库惯例），仅 mock libs.http，
 * 参照运行处置记录 RecordFilters 的统一口径验证：
 * - 台站/用途为文本草稿：输入不触发查询，查询按钮/回车提交后才生效；
 * - 状态下拉、截止日期（更多筛选折叠区）变更即查询，但不代提交文本草稿；
 * - 查询或条件变更后回到第 1 页；翻页取数使用已提交条件；
 * - "更多筛选"收起时显示已启用条件数量（日期范围按一个条件计数）；
 * - 重置清空常驻与折叠区全部条件及草稿，回到第 1 页并刷新。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import moment from 'moment';

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
  // 返回一条记录：store 的空页回退（空页>1 回退上一页）不干扰翻页断言
  mockHttpGet.mockResolvedValue({records: [{id: 1}], total: 1});
  store = require('../store').default;
  store.records = [];
  store.total = 0;
  store.pageNum = 1;
  store.pageSize = 20;
  store.f_station_name = undefined;
  store.f_purpose = undefined;
  store.f_status = undefined;
  store.f_valid_to_range = undefined;
  store.input_station_name = '';
  store.input_purpose = '';
  store.formVisible = false;
  store.detailVisible = false;
  store.setActive(true);
});

afterEach(() => {
  store.setActive(false);
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
  return mockHttpGet.mock.calls.filter(([url]) => url.endsWith('/api/radio-license/'));
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

describe('无线电台执照筛选区统一交互', () => {
  it('挂载即无筛选请求列表', async () => {
    await renderPage();
    expect(listCalls().length).toBe(1);
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
  });

  it('台站/用途为草稿：输入不请求，查询/回车提交后生效', async () => {
    await renderPage();
    await typeText('台站', '烟台站');
    await typeText('用途', '中继');
    expect(listCalls().length).toBe(1);
    await pressEnter(controlOf('台站').querySelector('input'));
    expect(listCalls().length).toBe(2);
    expect(lastListParams().station_name).toBe('烟台站');
    expect(lastListParams().purpose).toBe('中继');
    expect(lastListParams().page).toBe(1);
  });

  it('状态变更即查询，但不代提交未执行的文本草稿', async () => {
    await renderPage();
    await typeText('用途', '未提交草稿');
    await pickOption('状态', '即将到期');
    expect(listCalls().length).toBe(2);
    expect(lastListParams().status).toBe('expiring');
    expect(lastListParams().purpose).toBeUndefined();
    expect(store.input_purpose).toBe('未提交草稿');
  });

  it('截止日期（折叠区）清空即查询并回到第 1 页；计数按一个条件', async () => {
    store.f_valid_to_range = ['2026-10-01', '2026-12-31'];
    store.pageNum = 4;
    await renderPage();
    // 已设置的条件计数为 1（日期范围按一个条件计数）
    expect(moreFilterLink().textContent).toBe('更多筛选（1）');
    await toggleAdvanced();
    const clear = container.querySelector('.ant-picker-clear');
    await act(async () => {
      clear.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      clear.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      clear.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams().valid_to_start).toBeUndefined();
    expect(lastListParams().valid_to_end).toBeUndefined();
    expect(lastListParams().page).toBe(1);
    // 收起后条件已清空、计数归零
    await toggleAdvanced();
    expect(moreFilterLink().textContent).toBe('更多筛选');
  });

  it('翻页取数使用已提交条件，草稿不混入', async () => {
    await renderPage();
    await typeText('台站', '草稿站名');
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    store.input_station_name = '未提交草稿';
    store.pageNum = 2;
    await act(async () => {
      store.fetchRecords();
      await flush();
    });
    expect(lastListParams().page).toBe(2);
    expect(lastListParams().station_name).toBe('草稿站名');
  });

  it('重置清空全部条件及草稿并回到第 1 页刷新', async () => {
    store.f_status = 'normal';
    store.f_station_name = '旧台站';
    store.pageNum = 3;
    await renderPage();
    await typeText('用途', '新草稿');
    await act(async () => {
      findButton('重置').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
    expect(controlOf('台站').querySelector('input').value).toBe('');
    expect(controlOf('用途').querySelector('input').value).toBe('');
    expect(store.f_status).toBeUndefined();
    expect(store.f_valid_to_range).toBeUndefined();
  });
});
