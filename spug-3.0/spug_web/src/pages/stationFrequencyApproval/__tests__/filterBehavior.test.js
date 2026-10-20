/**
 * 台站频率批复——顶部筛选区统一交互行为测试（2026-10-20）。
 *
 * 真实渲染页面组件（ReactDOM + jsdom，仓库惯例），仅 mock libs.http，
 * 参照运行处置记录 RecordFilters 的统一口径验证：
 * - 文件名称/文件编号为文本草稿：输入不触发查询，查询按钮/回车提交后生效；
 * - 状态下拉、截止日期（折叠区）变更即查询，但不代提交文本草稿；
 * - 查询或条件变更后回到第 1 页；翻页取数使用已提交条件；
 * - "更多筛选"收起时显示已启用条件数量（日期范围按一个条件计数）；
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
  // 返回一条记录：store 的空页回退（空页>1 回退上一页）不干扰翻页断言
  mockHttpGet.mockResolvedValue({records: [{id: 1}], total: 1});
  store = require('../store').default;
  store.records = [];
  store.total = 0;
  store.pageNum = 1;
  store.pageSize = 20;
  store.f_name = undefined;
  store.f_doc_no = undefined;
  store.f_status = undefined;
  store.f_valid_to_range = undefined;
  store.input_name = '';
  store.input_doc_no = '';
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
    ReactDOM.render(React.createElement(Index, {location: {search: ''}}), container);
  });
  await act(async () => {
    await flush();
  });
}

function listCalls() {
  return mockHttpGet.mock.calls.filter(([url]) => url.endsWith('/api/radio-license/approvals/'));
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

describe('台站频率批复筛选区统一交互', () => {
  it('挂载即无筛选请求列表', async () => {
    await renderPage();
    expect(listCalls().length).toBe(1);
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
  });

  it('文件名称/文件编号为草稿：输入不请求，查询按钮提交后生效', async () => {
    await renderPage();
    await typeText('文件名称', '频率批复');
    await typeText('文件编号', 'PF-2026-01');
    expect(listCalls().length).toBe(1);
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams().name).toBe('频率批复');
    expect(lastListParams().doc_no).toBe('PF-2026-01');
    expect(lastListParams().page).toBe(1);
  });

  it('状态变更即查询，但不代提交未执行的文本草稿', async () => {
    await renderPage();
    await typeText('文件名称', '未提交草稿');
    await pickOption('状态', '已过期');
    expect(listCalls().length).toBe(2);
    expect(lastListParams().status).toBe('expired');
    expect(lastListParams().name).toBeUndefined();
    expect(store.input_name).toBe('未提交草稿');
  });

  it('截止日期（折叠区）清空即查询；展开收起本身不请求且计数保持', async () => {
    store.f_valid_to_range = ['2026-09-01', '2026-09-30'];
    await renderPage();
    expect(moreFilterLink().textContent).toBe('更多筛选（1）');
    await toggleAdvanced();
    expect(listCalls().length).toBe(1);
    const clear = container.querySelector('.ant-picker-clear');
    await act(async () => {
      clear.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      clear.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      clear.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams().valid_to_start).toBeUndefined();
    expect(lastListParams().page).toBe(1);
    // 折叠区日期清空后收起：计数归零
    await toggleAdvanced();
    expect(moreFilterLink().textContent).toBe('更多筛选');
  });

  it('翻页取数使用已提交条件，草稿不混入', async () => {
    await renderPage();
    await typeText('文件编号', 'PF-2026-02');
    await pressEnter(controlOf('文件编号').querySelector('input'));
    store.input_doc_no = '未提交草稿';
    store.pageNum = 2;
    await act(async () => {
      store.fetchRecords();
      await flush();
    });
    expect(lastListParams().page).toBe(2);
    expect(lastListParams().doc_no).toBe('PF-2026-02');
  });

  it('重置清空全部条件及草稿并回到第 1 页刷新', async () => {
    store.f_status = 'expiring';
    store.f_doc_no = 'PF-OLD';
    store.pageNum = 5;
    await renderPage();
    await typeText('文件名称', '新草稿');
    await act(async () => {
      findButton('重置').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
    expect(controlOf('文件名称').querySelector('input').value).toBe('');
    expect(controlOf('文件编号').querySelector('input').value).toBe('');
    expect(store.f_status).toBeUndefined();
    expect(store.input_name).toBe('');
    expect(store.input_doc_no).toBe('');
  });
});
