/**
 * 事件列表页回归测试（2026-10-25 前端批：问题4/问题6）。
 *
 * 真实渲染 EventsPage / InvestigationsPage（ReactDOM + jsdom），mock
 * libs.http，驱动真实 store 单例（MobX），验证：
 * - 问题4：打开「加入已有调查」弹窗加载调查选项不得改变事件列表分页
 *   状态（事件/调查各自独立分页字段）；
 * - 问题4：调查列表翻页不得窜到事件列表请求参数（互踩的另一路径）；
 * - 问题4：乱序响应下旧请求不得覆盖新请求的列表状态（请求代次守卫）；
 * - 问题6：RangePicker 选择完整范围只触发一次列表请求且同时携带起止；
 * - 问题6：清空范围后 datetime_start/datetime_end 都不残留；
 * - 问题6：重置按钮清空筛选并同步 RangePicker 显示（护栏）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import moment from 'moment';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true, permissions: []},
  syncAttachmentCount: jest.fn(),
}));

const EventsPage = require('../events').default;
const InvestigationsPage = require('../investigations').default;
const S = require('../store').default;

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  });
}

const EVENTS_TOTAL = 25;
const INVESTIGATIONS_TOTAL = 3;

function pagedPayload(params, total, namePrefix) {
  const page = params.page || 1;
  const size = params.page_size || 20;
  const records = [];
  const begin = (page - 1) * size;
  for (let i = begin; i < Math.min(begin + size, total); i++) {
    records.push({
      id: i + 1,
      name: namePrefix + (i + 1),
      status: 'investigating',
      datetime: '2026-10-01 08:00:00',
      scene_code: 'ground',
      phenomenon: namePrefix + (i + 1),
      investigations: [],
    });
  }
  return {records, total, page, page_size: size};
}

function defaultResponder(url, config) {
  const params = (config && config.params) || {};
  if (url.indexOf('/events/') >= 0) {
    return Promise.resolve(pagedPayload(params, EVENTS_TOTAL, '事件'));
  }
  if (url.indexOf('/investigations/') >= 0) {
    return Promise.resolve(pagedPayload(params, INVESTIGATIONS_TOTAL, '调查'));
  }
  return Promise.resolve({});
}

let container = null;

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function renderPage(element) {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(element, container);
  });
}

function unmountPage() {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
}

function q(selector) {
  return Array.from(document.querySelectorAll(selector));
}

function click(node) {
  act(() => {
    node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

function callsTo(url) {
  return mockHttpGet.mock.calls.filter(call => call[0] === url);
}

function lastEventsParams() {
  const calls = callsTo('/api/interference/events/');
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][1].params;
}

/** 打开 RangePicker 面板（第一个输入框 focus + 完整鼠标序列）。 */
async function openRangePicker() {
  const input = document.querySelector('.ant-picker input');
  await act(async () => {
    input.focus();
    input.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    input.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    input.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

/** 点选面板中的日期单元格（title 为 YYYY-MM-DD）。 */
async function pickCell(title) {
  const cell = document.querySelector(
    `.ant-picker-panel td[title="${title}"] .ant-picker-cell-inner`);
  expect(cell).toBeTruthy();
  await act(async () => {
    cell.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

async function selectRange() {
  const startTitle = moment().date(10).format('YYYY-MM-DD');
  const endTitle = moment().date(15).format('YYYY-MM-DD');
  await openRangePicker();
  await pickCell(startTitle);
  await pickCell(endTitle);
  return {startTitle, endTitle};
}

async function clearRange() {
  // antd4 清空图标动作绑定在 mouseup（仓库既有先例：regulation/Form.payload.test.js）
  const clearIcon = document.querySelector('.ant-picker-clear');
  expect(clearIcon).toBeTruthy();
  await act(async () => {
    clearIcon.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    await flush();
  });
}

function resetStore() {
  S.page = 1;
  S.pageSize = 20;
  S.total = 0;
  S.investigationPage = 1;
  S.investigationPageSize = 20;
  S.investigationTotal = 0;
  S.events = [];
  S.investigations = [];
  S.investigation = {};
  S.eventFilters = {};
  S.investigationName = '';
  S.investigationStatus = undefined;
  S.eventModalVisible = false;
  S.investigationModalVisible = false;
  S.eventsLoading = false;
  S.investigationsLoading = false;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockHttpGet.mockImplementation(defaultResponder);
  resetStore();
});

afterEach(async () => {
  unmountPage();
  // antd 弹窗关闭动画的卸载定时器若提前摘除节点，会在下一个用例的
  // 时间窗内抛 jsdom NotFoundError；先等它完成再清理（同 categories.test.js）
  await new Promise(resolve => setTimeout(resolve, 400));
  document.querySelectorAll(
    '.ant-modal-root, .ant-modal-confirm, .ant-select-dropdown, .ant-picker-dropdown',
  ).forEach(n => n.remove());
  resetStore();
});

// 门禁等价拆分（2026-10-26）：下方「问题4」describe 的用例体整体抽为模块级
// helper（每个 ≤120 行），describe/it 名称、断言内容、用例数量与 mock 行为
// 一字不改，仅结构搬移（函数声明提升，先声明后引用合法）。
async function caseJoinDialogLoadsOptionsWithoutTouchingEventPagination() {
  renderPage(<EventsPage/>);
  await act(async () => { await flush(); });
  // 事件列表翻到第 2 页（真实 antd 分页交互）
  const page2Item = document.querySelector('.ant-pagination-item-2');
  expect(page2Item).toBeTruthy();
  click(page2Item);
  await act(async () => { await flush(); });
  expect(S.page).toBe(2);

  // 勾选一行使「加入已有调查」可用，然后打开弹窗
  const firstCheckbox = document.querySelector(
    '.ant-table-tbody .ant-checkbox-input');
  expect(firstCheckbox).toBeTruthy();
  click(firstCheckbox);
  await act(async () => { await flush(); });
  const joinButton = q('.ant-btn').find(
    btn => btn.textContent.indexOf('加入已有调查') >= 0);
  expect(joinButton).toBeTruthy();
  expect(joinButton.disabled).toBe(false);
  click(joinButton);
  await act(async () => { await flush(); });

  // 弹窗内的调查选择项按 page=1&page_size=100 请求
  const invCalls = callsTo('/api/interference/investigations/');
  expect(invCalls).toHaveLength(1);
  expect(invCalls[0][1].params).toEqual({page: 1, page_size: 100});

  // 事件列表分页状态必须保持 2/20/25（修复前被改成 1/100/3）
  expect(S.page).toBe(2);
  expect(S.pageSize).toBe(20);
  expect(S.total).toBe(EVENTS_TOTAL);
  const activeItem = document.querySelector('.ant-pagination-item-active');
  expect(activeItem.textContent).toBe('2');
  // 选择器口径（100/页）也不得残留进调查列表分页状态
  expect(S.investigationPage).toBe(1);
  expect(S.investigationPageSize).toBe(20);
  expect(S.investigationTotal).toBe(0);
}

async function caseInvestigationPagingDoesNotLeakIntoEventRequests() {
  mockHttpGet.mockImplementation((url, config) => {
    const params = (config && config.params) || {};
    if (url.indexOf('/events/') >= 0) {
      return Promise.resolve(pagedPayload(params, EVENTS_TOTAL, '事件'));
    }
    if (url.indexOf('/investigations/') >= 0) {
      return Promise.resolve(pagedPayload(params, EVENTS_TOTAL, '调查'));
    }
    return Promise.resolve({});
  });
  renderPage(<InvestigationsPage/>);
  await act(async () => { await flush(); });
  // 调查列表翻到第 2 页（真实 antd 分页交互）
  const page2Item = document.querySelector('.ant-pagination-item-2');
  expect(page2Item).toBeTruthy();
  click(page2Item);
  await act(async () => { await flush(); });
  expect(mockHttpGet.mock.calls[
    mockHttpGet.mock.calls.length - 1][1].params.page).toBe(2);

  // 事件列表刷新（如 EventForm 保存后的 fetchEvents）不得带上调查页码
  mockHttpGet.mockClear();
  mockHttpGet.mockImplementation((url, config) => {
    const params = (config && config.params) || {};
    if (url.indexOf('/events/') >= 0) {
      return Promise.resolve(pagedPayload(params, EVENTS_TOTAL, '事件'));
    }
    return Promise.resolve({});
  });
  await act(async () => { await S.fetchEvents(); });
  expect(lastEventsParams().page).toBe(1);
  expect(S.page).toBe(1);
}

async function caseStaleEventResponseDoesNotOverwriteNewListState() {
  let resolveOld;
  let resolveNew;
  const oldPromise = new Promise(resolve => { resolveOld = resolve; });
  const newPromise = new Promise(resolve => { resolveNew = resolve; });
  let callCount = 0;
  mockHttpGet.mockImplementation(() => {
    callCount += 1;
    return callCount === 1 ? oldPromise : newPromise;
  });

  let firstCall;
  let secondCall;
  await act(async () => {
    firstCall = S.fetchEvents({page: 2});
    secondCall = S.fetchEvents({page: 3});
  });
  expect(callCount).toBe(2);

  // 新请求先返回，旧请求后返回（乱序）
  await act(async () => {
    resolveNew({records: [{id: 30, phenomenon: '新请求结果'}],
      total: 30, page: 3, page_size: 20});
    await Promise.all([secondCall, flush()]);
  });
  expect(S.events[0].id).toBe(30);

  await act(async () => {
    resolveOld({records: [{id: 2, phenomenon: '旧请求结果'}],
      total: 10, page: 2, page_size: 20});
    await Promise.all([firstCall, flush()]);
  });

  // 最终状态必须与新请求对应（修复前旧响应后到覆盖一切）
  expect(S.events[0].id).toBe(30);
  expect(S.events[0].phenomenon).toBe('新请求结果');
  expect(S.total).toBe(30);
  expect(S.page).toBe(3);
  expect(S.pageSize).toBe(20);
  expect(S.eventsLoading).toBe(false);
}

async function caseStaleEventRequestDoesNotResetEventsLoading() {
  let resolveOld;
  let resolveNew;
  const oldPromise = new Promise(resolve => { resolveOld = resolve; });
  const newPromise = new Promise(resolve => { resolveNew = resolve; });
  let callCount = 0;
  mockHttpGet.mockImplementation(() => {
    callCount += 1;
    return callCount === 1 ? oldPromise : newPromise;
  });

  let firstCall;
  let secondCall;
  await act(async () => {
    firstCall = S.fetchEvents({page: 2});
    secondCall = S.fetchEvents({page: 3});
  });
  expect(S.eventsLoading).toBe(true);

  // 旧请求先完成、新请求仍在途：旧响应既不得写入列表状态，
  // 其 finally 也不得复位 loading
  await act(async () => {
    resolveOld({records: [{id: 2, phenomenon: '旧请求结果'}],
      total: 10, page: 2, page_size: 20});
    await Promise.all([firstCall, flush()]);
  });
  expect(S.eventsLoading).toBe(true);
  expect(S.events).toEqual([]);

  // 新响应到达后 loading 才复位，且状态与新请求对应
  await act(async () => {
    resolveNew({records: [{id: 30, phenomenon: '新请求结果'}],
      total: 30, page: 3, page_size: 20});
    await Promise.all([secondCall, flush()]);
  });
  expect(S.eventsLoading).toBe(false);
  expect(S.events[0].id).toBe(30);
  expect(S.page).toBe(3);
}

async function caseStaleInvestigationResponseDoesNotOverwriteNewListState() {
  let resolveOld;
  let resolveNew;
  const oldPromise = new Promise(resolve => { resolveOld = resolve; });
  const newPromise = new Promise(resolve => { resolveNew = resolve; });
  let callCount = 0;
  mockHttpGet.mockImplementation(() => {
    callCount += 1;
    return callCount === 1 ? oldPromise : newPromise;
  });

  let firstCall;
  let secondCall;
  // 两次列表刷新间翻页（page 2 → 3）：不携带显式分页参数，
  // 响应需回写调查分页字段，守卫必须拦下后到的旧响应
  await act(async () => {
    S.investigationPage = 2;
    firstCall = S.fetchInvestigations();
  });
  await act(async () => {
    S.investigationPage = 3;
    secondCall = S.fetchInvestigations();
  });
  expect(callCount).toBe(2);

  await act(async () => {
    resolveNew({records: [{id: 30, name: '新请求调查'}],
      total: 30, page: 3, page_size: 20});
    await Promise.all([secondCall, flush()]);
  });
  await act(async () => {
    resolveOld({records: [{id: 2, name: '旧请求调查'}],
      total: 10, page: 2, page_size: 20});
    await Promise.all([firstCall, flush()]);
  });

  expect(S.investigations[0].id).toBe(30);
  expect(S.investigations[0].name).toBe('新请求调查');
  expect(S.investigationTotal).toBe(30);
  expect(S.investigationPage).toBe(3);
  expect(S.investigationPageSize).toBe(20);
  expect(S.investigationsLoading).toBe(false);
}

describe('问题4：事件/调查分页互不干扰', () => {
  it('打开加入已有调查弹窗：调查选项按 page=1&page_size=100 加载，事件分页不被改动', async () => { await caseJoinDialogLoadsOptionsWithoutTouchingEventPagination(); });

  it('调查列表翻页后事件请求仍使用事件自己的页码', async () => { await caseInvestigationPagingDoesNotLeakIntoEventRequests(); });

  it('乱序响应：旧请求不得覆盖新请求的列表状态', async () => { await caseStaleEventResponseDoesNotOverwriteNewListState(); });

  it('旧请求先完成时不得提前复位 eventsLoading（仅最新请求有权复位）', async () => { await caseStaleEventRequestDoesNotResetEventsLoading(); });

  it('调查列表乱序响应：旧请求不得覆盖新请求的列表状态', async () => { await caseStaleInvestigationResponseDoesNotOverwriteNewListState(); });
});

describe('问题6：发生时间范围筛选', () => {
  it('选择完整范围只触发一次请求、同时携带起止并回到第 1 页', async () => {
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });
    // 先真实翻到第 2 页，使「选范围后回到第 1 页」成为可失败断言
    //（若 onChange 丢失 store.page=1 重置，本用例必失败）
    const page2Item = document.querySelector('.ant-pagination-item-2');
    expect(page2Item).toBeTruthy();
    click(page2Item);
    await act(async () => { await flush(); });
    expect(S.page).toBe(2);
    mockHttpGet.mockClear();
    mockHttpGet.mockImplementation(defaultResponder);

    const {startTitle, endTitle} = await selectRange();

    const eventCalls = callsTo('/api/interference/events/');
    expect(eventCalls).toHaveLength(1);
    const params = eventCalls[0][1].params;
    expect(params.datetime_start).toBe(startTitle);
    expect(params.datetime_end).toBe(endTitle);
    expect(params.page).toBe(1);
    expect(S.eventFilters.datetime_start).toBe(startTitle);
    expect(S.eventFilters.datetime_end).toBe(endTitle);
    expect(S.page).toBe(1);
    const activeItem = document.querySelector('.ant-pagination-item-active');
    expect(activeItem.textContent).toBe('1');
  });

  it('清空范围后起止筛选都不残留且只发一次请求', async () => {
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });
    mockHttpGet.mockClear();
    mockHttpGet.mockImplementation(defaultResponder);

    await selectRange();
    expect(S.eventFilters.datetime_start).toBeTruthy();
    // 计数窗口从"已选中范围"之后开始：若清空路径回归为逐键 updateFilter
    // 双发（start 一次、end 一次），本断言必失败
    mockHttpGet.mockClear();
    mockHttpGet.mockImplementation(defaultResponder);
    await clearRange();

    const clearCalls = callsTo('/api/interference/events/');
    expect(clearCalls).toHaveLength(1);
    expect(S.eventFilters.datetime_start).toBeUndefined();
    expect(S.eventFilters.datetime_end).toBeUndefined();
    const params = clearCalls[0][1].params;
    expect(params.datetime_start).toBeUndefined();
    expect(params.datetime_end).toBeUndefined();
  });

  it('重置按钮清空筛选并同步 RangePicker 显示', async () => {
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });
    mockHttpGet.mockClear();
    mockHttpGet.mockImplementation(defaultResponder);

    await selectRange();
    expect(S.eventFilters.datetime_start).toBeTruthy();
    // antd4 两个汉字的按钮文案会插入空格（渲染为「重 置」），匹配前去空白
    const resetButton = q('.ant-btn').find(
      btn => btn.textContent.replace(/\s+/g, '').indexOf('重置') >= 0);
    expect(resetButton).toBeTruthy();
    click(resetButton);
    await act(async () => { await flush(); });

    expect(S.eventFilters).toEqual({});
    const params = lastEventsParams();
    expect(params.datetime_start).toBeUndefined();
    expect(params.datetime_end).toBeUndefined();
    // RangePicker 显示与筛选状态保持同步（输入框清空）
    const inputs = q('.ant-picker input');
    expect(inputs.length).toBeGreaterThan(0);
    inputs.forEach(input => expect(input.value).toBe(''));
  });
});

/** 按去空白后的文案在指定范围（默认 document）内找按钮 */
function findButton(scope, text) {
  const root = scope || document;
  return Array.from(root.querySelectorAll('.ant-btn'))
    .find(b => b.textContent.replace(/\s+/g, '') === text);
}

/** 按弹窗标题在 document 中找 antd Modal 节点 */
function modalByTitle(title) {
  return q('.ant-modal').find(m => {
    const t = m.querySelector('.ant-modal-title');
    return !!t && t.textContent === title;
  });
}

/** 以真实 input 事件设置受控输入框的值 */
function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

function postsTo(fragment) {
  return mockHttpPost.mock.calls.filter(call => call[0].indexOf(fragment) >= 0);
}

/** 勾选前两行（rowKey 1、2）并点击「创建调查」，返回调查弹窗节点 */
async function openCreateInvestigationModal() {
  const boxes = q('.ant-table-tbody .ant-checkbox-input');
  expect(boxes.length).toBeGreaterThanOrEqual(2);
  click(boxes[0]);
  click(boxes[1]);
  await act(async () => { await flush(); });
  const btn = findButton(document, '创建调查');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(false);
  click(btn);
  await act(async () => { await flush(); });
  return modalByTitle('新建规律调查');
}

describe('问题1：事件页「创建调查」直通调查表单（死端修复）', () => {
  it('选中 2 行点击「创建调查」：调查表单弹窗出现且携带所选事件键', async () => {
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });

    const modal = await openCreateInvestigationModal();
    // 修复前：events.js 未渲染 InvestigationForm，点击后无任何 UI 响应
    expect(modal).toBeTruthy();
    expect(modal.querySelector('input#name')).toBeTruthy();
    expect(S.investigation.event_ids).toEqual([1, 2]);
  });

  it('弹窗内保存：恰好一次 POST 且携带 event_ids，成功后关闭并刷新事件列表', async () => {
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });

    const modal = await openCreateInvestigationModal();
    expect(modal).toBeTruthy();
    mockHttpPost.mockResolvedValue({});
    const eventsCallsBeforeSave = callsTo('/api/interference/events/').length;
    setInputValue(modal.querySelector('input#name'), '事件页创建的调查');
    const save = findButton(modal, '保存');
    expect(save).toBeTruthy();
    click(save);
    await act(async () => { await flush(); await flush(); });

    // 恰好一次创建 POST，payload 携带正确 event_ids（修复前根本走不到）
    const posts = postsTo('/api/interference/investigations/');
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe('/api/interference/investigations/');
    expect(posts[0][1].name).toBe('事件页创建的调查');
    expect(posts[0][1].event_ids).toEqual([1, 2]);
    // 成功后弹窗关闭、store 清理
    expect(S.investigationModalVisible).toBe(false);
    expect(S.investigation).toEqual({});
    // onSaved 回调生效：保存成功后事件列表重新拉取（调查状态列刷新）
    expect(callsTo('/api/interference/events/').length)
      .toBe(eventsCallsBeforeSave + 1);
  });

  it('卸载事件页清理遗留调查弹窗状态：切到规律调查页不再意外弹出', async () => {
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });

    const modal = await openCreateInvestigationModal();
    expect(modal).toBeTruthy();
    expect(S.investigationModalVisible).toBe(true);

    // 卸载即清理：弹窗状态与携带的 event_ids 都不得遗留
    unmountPage();
    expect(S.investigationModalVisible).toBe(false);
    expect(S.investigation).toEqual({});

    // 修复前：store 单例残留 investigationModalVisible=true，切到规律调查页
    // 会意外弹出携带 event_ids 的表单；修复后不再复现
    renderPage(<InvestigationsPage/>);
    await act(async () => { await flush(); });
    expect(S.investigationModalVisible).toBe(false);
    expect(q('.ant-modal')).toHaveLength(0);
  });

  it('「取消」关闭后 store.investigation 清空，再次打开不残留旧 event_ids', async () => {
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });

    const modal = await openCreateInvestigationModal();
    expect(modal).toBeTruthy();
    const cancel = findButton(modal, '取消');
    expect(cancel).toBeTruthy();
    click(cancel);
    await act(async () => { await flush(); });

    expect(S.investigationModalVisible).toBe(false);
    expect(S.investigation).toEqual({});
    expect(S.investigation.event_ids).toBeUndefined();

    // 再次打开（行勾选仍在，直接点按钮）：全新状态，event_ids 来自当前勾选
    const btn = findButton(document, '创建调查');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
    click(btn);
    await act(async () => { await flush(); });
    const reopened = modalByTitle('新建规律调查');
    expect(reopened).toBeTruthy();
    expect(S.investigation.event_ids).toEqual([1, 2]);
  });
});

describe('关联调查列（生命周期改造 2026-10-26）：调查状态 raw 码列退役', () => {
  it('无关联行显示「未关联」，旧「调查状态」列名与 raw 状态码不再出现', async () => {
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });
    const tbody = document.querySelector('.ant-table-tbody');
    expect(tbody).toBeTruthy();
    expect(tbody.textContent).toContain('未关联');
    // 修复前列名「调查状态」+ render raw 英文码（如 draft）
    expect(tbody.textContent).not.toContain('调查状态');
    expect(tbody.textContent).not.toContain('draft');
  });

  it('有关联行显示「名称（状态文本）」并以、连接多条', async () => {
    mockHttpGet.mockImplementation(url => {
      if (url.indexOf('/events/') >= 0) {
        return Promise.resolve({records: [
          {id: 1, datetime: '2026-10-01 08:00:00', scene_code: 'ground', phenomenon: '事件一',
            investigations: [
              {id: 7, name: '调查七', status: 'investigating', status_text: '调查中'},
              {id: 8, name: '调查八', status: 'ended', status_text: '已结束'},
            ]},
          {id: 2, datetime: '2026-10-02 08:00:00', scene_code: 'air', phenomenon: '事件二',
            investigations: []},
        ], total: 2, page: 1, page_size: 20});
      }
      return Promise.resolve({});
    });
    renderPage(<EventsPage/>);
    await act(async () => { await flush(); });
    const tbody = document.querySelector('.ant-table-tbody');
    expect(tbody.textContent).toContain('调查七（调查中）、调查八（已结束）');
    expect(tbody.textContent).toContain('未关联');
  });
});
