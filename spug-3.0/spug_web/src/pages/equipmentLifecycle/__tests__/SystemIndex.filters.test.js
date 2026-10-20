/**
 * 系统档案（设备全生命周期）——顶部筛选区统一交互行为测试（2026-10-20）。
 *
 * 真实渲染页面组件（ReactDOM + jsdom，仓库惯例），仅 mock libs.http，
 * 参照运行处置记录 RecordFilters 的统一口径验证：
 * - 系统名称为常驻文本草稿；使用单位/安装地点为折叠区文本草稿，查询
 *   按钮/回车提交后才生效；
 * - 运行健康状态/是否可用下拉变更即查询，但不代提交文本草稿；
 * - "是否可用"选"已停用"（false）为有效条件：请求携带 is_active=false；
 * - "更多筛选"收起时显示已启用条件数量；展开收起本身不请求；
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
  mockHttpGet.mockResolvedValue({data: [], total: 0});
  store = require('../store').default;
  store.records = [];
  store.total = 0;
  store.page = 1;
  store.pageSize = 20;
  store.f_keyword = undefined;
  store.f_health_status = undefined;
  store.f_is_active = undefined;
  store.f_use_unit = undefined;
  store.f_install_location = undefined;
  store.input_keyword = '';
  store.input_use_unit = '';
  store.input_install_location = '';
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
  return mockHttpGet.mock.calls.filter(([url]) => url.endsWith('/systems/'));
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

describe('系统档案筛选区统一交互', () => {
  it('挂载即无筛选请求列表', async () => {
    await renderPage();
    expect(listCalls().length).toBe(1);
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
  });

  it('系统名称为草稿：输入不请求，查询按钮提交后生效', async () => {
    await renderPage();
    await typeText('系统名称', '通信系统');
    expect(listCalls().length).toBe(1);
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams().keyword).toBe('通信系统');
    expect(lastListParams().page).toBe(1);
  });

  it('健康状态/是否可用变更即查询；false 布尔条件请求携带 is_active=false', async () => {
    await renderPage();
    await typeText('系统名称', '未提交草稿');
    await pickOption('是否可用', '已停用');
    expect(listCalls().length).toBe(2);
    expect(lastListParams().is_active).toBe(false);
    expect(lastListParams().keyword).toBeUndefined();
    expect(store.input_keyword).toBe('未提交草稿');
  });

  it('折叠区草稿计数：使用单位/安装地点 → 更多筛选（2）', async () => {
    await renderPage();
    expect(moreFilterLink().textContent).toBe('更多筛选');
    await toggleAdvanced();
    expect(listCalls().length).toBe(1);
    await typeText('使用单位', '运行一科');
    await typeText('安装地点', '机房A');
    await toggleAdvanced();
    expect(moreFilterLink().textContent).toBe('更多筛选（2）');
    expect(listCalls().length).toBe(1);
    // 草稿尚未提交：取数仍无这两个条件
    expect(lastListParams().use_unit).toBeUndefined();
  });

  it('翻页取数使用已提交条件，草稿不混入', async () => {
    await renderPage();
    await typeText('系统名称', '已提交名称');
    await pressEnter(controlOf('系统名称').querySelector('input'));
    store.input_keyword = '未提交草稿';
    store.page = 2;
    await act(async () => {
      store.fetchRecords();
      await flush();
    });
    expect(lastListParams().page).toBe(2);
    expect(lastListParams().keyword).toBe('已提交名称');
  });

  it('重置清空常驻与折叠区全部条件及草稿并回到第 1 页', async () => {
    store.f_health_status = 'fault';
    store.f_use_unit = '旧单位';
    store.page = 3;
    await renderPage();
    await typeText('系统名称', '新草稿');
    await act(async () => {
      findButton('重置').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
    expect(controlOf('系统名称').querySelector('input').value).toBe('');
    expect(store.f_health_status).toBeUndefined();
    expect(store.f_is_active).toBeUndefined();
    expect(store.f_use_unit).toBeUndefined();
    expect(store.f_install_location).toBeUndefined();
    expect(store.input_keyword).toBe('');
    expect(store.input_use_unit).toBe('');
    expect(store.input_install_location).toBe('');
  });
});
