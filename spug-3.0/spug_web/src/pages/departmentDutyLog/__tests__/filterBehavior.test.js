/**
 * 部门值班日志——顶部筛选区统一交互行为测试（2026-10-20）。
 *
 * 真实渲染页面组件（ReactDOM + jsdom，仓库惯例），仅 mock libs.http，
 * 参照运行处置记录 RecordFilters 的统一口径验证：
 * - 关键字/值班人员为文本草稿：输入不触发查询，查询按钮/回车提交后才生效；
 * - 状态下拉、日期范围变更即查询，但不代提交未执行的文本草稿；
 * - 查询或条件变更后回到第 1 页；翻页取数使用已提交条件（草稿不混入）；
 * - "更多筛选"收起时保留条件并显示已启用条件数量；展开收起本身不请求；
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
    if (url.includes('/records/')) {
      return Promise.resolve({records: [], total: 0});
    }
    return Promise.resolve({current_user: '管理员'});
  });
  store = require('../departmentDutyLogStore').default;
  store.records = [];
  store.total = 0;
  store.pageNum = 1;
  store.pageSize = 20;
  store.f_start_date = undefined;
  store.f_end_date = undefined;
  store.f_duty_person_name = undefined;
  store.f_status = undefined;
  store.f_keyword = undefined;
  store.input_keyword = '';
  store.input_duty_person_name = '';
  store.formVisible = false;
  store.detailVisible = false;
  store.signVisible = false;
  store.returnVisible = false;
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
  return mockHttpGet.mock.calls.filter(([url]) => url.includes('/records/'));
}

function lastListParams() {
  const calls = listCalls();
  return calls[calls.length - 1][1].params;
}

function findButton(label) {
  // antd 对两字中文按钮自动插空格（"查 询"），匹配前去掉空白
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === label);
}

// 真实 SearchForm（antd Form.Item）：按标签文本定位表单项的控件区
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
  // React 合成事件 keyCode 取自原生事件（jsdom 构造器不收 keyCode，须补定义）
  Object.defineProperty(enterEvent, 'keyCode', {get: () => 13});
  Object.defineProperty(enterEvent, 'which', {get: () => 13});
  await act(async () => {
    input.dispatchEvent(enterEvent);
    await flush();
  });
}

// antd4 Select：mousedown 落在 .ant-select-selector 上，选项渲染在 body dropdown
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

describe('部门值班日志筛选区统一交互（草稿与即时查询）', () => {
  it('挂载即无筛选请求列表', async () => {
    await renderPage();
    expect(listCalls().length).toBe(1);
    expect(lastListParams()).toEqual({page: 1, page_size: 20});
  });

  it('关键字为草稿：输入不请求，查询按钮提交后才生效', async () => {
    await renderPage();
    await typeText('关键字', '机房巡检');
    expect(listCalls().length).toBe(1);
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(listCalls().length).toBe(2);
    expect(lastListParams().keyword).toBe('机房巡检');
    expect(lastListParams().page).toBe(1);
  });

  it('关键字回车提交草稿；值班人员在折叠区同样草稿提交', async () => {
    await renderPage();
    // 展开更多筛选后填写值班人员草稿
    await act(async () => {
      moreFilterLink().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const personInput = await typeText('值班人员', '张三');
    const keywordInput = await typeText('关键字', '上级要求');
    expect(listCalls().length).toBe(1);
    // 回车提交全部文本草稿
    await pressEnter(keywordInput);
    expect(listCalls().length).toBe(2);
    expect(lastListParams().keyword).toBe('上级要求');
    expect(lastListParams().duty_person_name).toBe('张三');
    expect(lastListParams().page).toBe(1);
    // 回车在值班人员输入框同样触发提交
    await pressEnter(personInput);
    expect(listCalls().length).toBe(3);
    expect(lastListParams().duty_person_name).toBe('张三');
  });

  it('状态下拉变更即查询，但不代提交未执行的文本草稿', async () => {
    await renderPage();
    await typeText('关键字', '未提交草稿');
    await pickOption('状态', '已签署');
    expect(listCalls().length).toBe(2);
    expect(lastListParams().status).toBe('signed');
    expect(lastListParams().keyword).toBeUndefined();
    expect(store.input_keyword).toBe('未提交草稿');
  });

});

describe('部门值班日志筛选区统一交互（折叠计数、分页与重置）', () => {
  it('日期范围清空即查询；翻页取数使用已提交条件', async () => {
    store.f_start_date = moment('2026-10-01');
    store.f_end_date = moment('2026-10-15');
    store.f_keyword = '已提交条件';
    await renderPage();
    expect(lastListParams().start_date).toBe('2026-10-01');
    // 清空日期范围触发即时查询
    const clear = container.querySelector('.ant-picker-clear');
    await act(async () => {
      clear.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      clear.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      clear.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(lastListParams().start_date).toBeUndefined();
    expect(lastListParams().end_date).toBeUndefined();
    expect(lastListParams().keyword).toBe('已提交条件');
    // 翻页取数使用已提交条件，草稿（未执行）不混入
    store.input_keyword = '翻页时的未提交草稿';
    store.pageNum = 2;
    await act(async () => {
      store.fetchRecords();
      await flush();
    });
    expect(lastListParams().page).toBe(2);
    expect(lastListParams().keyword).toBe('已提交条件');
  });

  it('更多筛选收起时显示已启用条件数量，展开收起本身不请求', async () => {
    await renderPage();
    expect(moreFilterLink().textContent).toBe('更多筛选');
    // 展开填写值班人员草稿后收起：草稿保留、计数显示
    await act(async () => {
      moreFilterLink().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    await typeText('值班人员', '李四');
    expect(listCalls().length).toBe(1);
    await act(async () => {
      moreFilterLink().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(moreFilterLink().textContent).toBe('更多筛选（1）');
    expect(container.textContent).not.toContain('值班人员姓名');
    expect(listCalls().length).toBe(1);
    // 重新展开：草稿仍在
    await act(async () => {
      moreFilterLink().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(controlOf('值班人员').querySelector('input').value).toBe('李四');
  });

  it('重置清空全部条件及草稿并回到第 1 页刷新', async () => {
    store.f_status = 'signed';
    store.f_keyword = '旧条件';
    store.pageNum = 3;
    await renderPage();
    await typeText('关键字', '新草稿');
    await act(async () => {
      findButton('重置').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const params = lastListParams();
    expect(params).toEqual({page: 1, page_size: 20});
    expect(controlOf('关键字').querySelector('input').value).toBe('');
    expect(store.f_status).toBeUndefined();
    expect(store.f_keyword).toBeUndefined();
    expect(store.input_keyword).toBe('');
    expect(store.input_duty_person_name).toBe('');
    expect(moreFilterLink().textContent).toBe('更多筛选');
  });
});
