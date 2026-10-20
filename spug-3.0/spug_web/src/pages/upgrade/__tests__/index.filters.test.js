/**
 * 系统升级管理（升级表单页）——顶部筛选区统一交互行为测试（2026-10-20）。
 *
 * 真实渲染页面组件（ReactDOM + jsdom，仓库惯例），仅 mock libs.http，
 * 参照运行处置记录 RecordFilters 的统一口径验证：
 * - 系统/状态/升级类型下拉变更即查询并回到第 1 页；
 * - 计划升级时间收入"更多筛选"，清空即查询；展开收起本身不请求；
 * - 查询按钮对列表视图真实生效（条件不变也重取）；
 * - 日历视图：取数窗口为当前浏览月份（计划升级时间筛选仅作用于列表，
 *   不参与日历取数的业务语义固化）；系统/状态/升级类型与查询/重置
 *   （filterCommitSeq）对日历真实生效；
 * - 重置清空全部条件，列表与日历均重取，回到第 1 页。
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
  history: {push: jest.fn(), replace: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
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
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/api/upgrade/filter-options/')) {
      return Promise.resolve({
        systems: [{id: 3, name: '通信系统丙'}],
        upgrade_types: ['软件升级'],
        statuses: ['处理中', '已完成'],
        phases: [], milestones: [], standard_flow: [],
      });
    }
    if (url.includes('/api/upgrade/records/')) {
      return Promise.resolve({records: [], total: 0});
    }
    return Promise.resolve({});
  });
  store = require('../store').default;
  store.records = [];
  store.total = 0;
  store.page = 1;
  store.pageSize = 20;
  store.f_system = undefined;
  store.f_status = undefined;
  store.f_start_date = undefined;
  store.f_end_date = undefined;
  store.f_upgrade_type = undefined;
  store.filterCommitSeq = 0;
  store.viewMode = 'list';
  store.createVisible = false;
  store.formVisible = false;
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
    ReactDOM.render(React.createElement(Index, {embedded: true}), container);
  });
  await act(async () => {
    await flush();
  });
}

function recordCalls() {
  return mockHttpGet.mock.calls.filter(([url]) => url.includes('/api/upgrade/records/'));
}

function lastRecordParams() {
  const calls = recordCalls();
  return calls[calls.length - 1][1].params;
}

function calendarCallCount() {
  return recordCalls().filter(([, config]) => config.params.page_size === 999).length;
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

async function switchToCalendar() {
  const radios = container.querySelectorAll('.ant-radio-button-input');
  await act(async () => {
    radios[1].click();
    await flush();
  });
}

describe('升级表单筛选区统一交互', () => {
  it('状态下拉变更即查询并回到第 1 页；查询按钮条件不变也真实重取列表', async () => {
    await renderPage();
    expect(recordCalls().length).toBe(1);
    await pickOption('状态', '处理中');
    expect(lastRecordParams().status).toBe('处理中');
    expect(lastRecordParams().page).toBe(1);
    store.page = 3;
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastRecordParams().page).toBe(1);
    expect(lastRecordParams().status).toBe('处理中');
    expect(recordCalls().length).toBe(3);
  });

  it('计划升级时间收入更多筛选：清空即查询；展开收起本身不请求', async () => {
    store.f_start_date = '2026-10-01';
    store.f_end_date = '2026-10-31';
    await renderPage();
    expect(moreFilterLink().textContent).toBe('更多筛选（1）');
    const before = recordCalls().length;
    await toggleAdvanced();
    expect(recordCalls().length).toBe(before);
    expect(container.textContent).toContain('计划升级时间');
    const clear = container.querySelector('.ant-picker-clear');
    await act(async () => {
      clear.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      clear.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      clear.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastRecordParams().start_date).toBeUndefined();
    expect(lastRecordParams().end_date).toBeUndefined();
    expect(lastRecordParams().page).toBe(1);
  });

  it('日历视图按当前月份取数：计划升级时间不参与日历取数（语义差异固化）', async () => {
    // 预置一个远离当前月的计划升级时间：列表会带上，日历仍取当月窗口
    store.f_start_date = '2026-01-01';
    store.f_end_date = '2026-01-31';
    await renderPage();
    await switchToCalendar();
    expect(calendarCallCount()).toBe(1);
    const params = lastRecordParams();
    expect(params.page_size).toBe(999);
    expect(params.start_date).toBe(moment().startOf('month').format('YYYY-MM-DD'));
    expect(params.end_date).toBe(moment().endOf('month').format('YYYY-MM-DD'));
  });

  it('日历视图：下拉条件与查询按钮（filterCommitSeq）真实触发重取', async () => {
    await renderPage();
    await switchToCalendar();
    expect(calendarCallCount()).toBe(1);
    // 系统下拉变更：日历重取并携带 system
    await pickOption('系统', '通信系统丙');
    expect(lastRecordParams().page_size).toBe(999);
    expect(lastRecordParams().system).toBe(3);
    // 条件不变点查询：提交序号驱动日历真实重取
    const before = calendarCallCount();
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(calendarCallCount()).toBe(before + 1);
    expect(lastRecordParams().system).toBe(3);
  });

  it('日历视图重置：清空全部条件后列表与日历均重取，日历请求不再带条件', async () => {
    store.f_system = 3;
    store.f_status = '处理中';
    await renderPage();
    await switchToCalendar();
    await act(async () => {
      findButton('重置').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    // 日历重取：不带 system/status；日期窗口仍为当月
    const calendarParams = lastRecordParams();
    expect(calendarParams.page_size).toBe(999);
    expect(calendarParams.system).toBeUndefined();
    expect(calendarParams.status).toBeUndefined();
    expect(calendarParams.start_date).toBe(moment().startOf('month').format('YYYY-MM-DD'));
    // 列表也已重取且回到第 1 页（供切回列表视图时呈现最新结果）
    const listCalls = recordCalls().filter(([, config]) => config.params.page_size === 20);
    const lastList = listCalls[listCalls.length - 1][1].params;
    expect(lastList.page).toBe(1);
    expect(lastList.system).toBeUndefined();
    expect(store.f_system).toBeUndefined();
    expect(store.f_status).toBeUndefined();
    expect(store.f_start_date).toBeUndefined();
  });
});
