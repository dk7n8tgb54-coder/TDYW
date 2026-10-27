/**
 * 2026-10-26 用户实测缺陷回归：规律调查「编辑」后表单全空、点击无响应。
 *
 * 根因（行点击真实入口实证）：store.fetchInvestigation/fetchEvent 在每次响应
 * 到达后把「新对象」写回 store.investigation/store.event；InvestigationForm
 * /EventForm 的详情 effect 依赖数组含 info（= store.investigation/store.event
 * 引用）→ 响应写入 → info 引用变化 → 先执行 cleanup（form.resetFields() 清空
 * 表单）再重跑 effect → 再次 fetch → 无限循环。用户症状 = 表单在「填入→清空」
 * 间循环（看起来全空、点击无响应、接口重复请求）；查看态同样中招，且旧实现
 * 会把 showInvestigation/showEvent 注入的 isViewMode 随首次响应覆写丢失，
 * 查看态静默翻成可编辑。
 *
 * 本文件的详情 mock 一律「每次返回全新对象」——既有套件让详情响应返回
 * store 现值的恒等手法恰好使 info 引用不变，从构造上掩盖了生产循环，此处
 * 明确禁止。详情响应时序由手动 deferred 控制，配合固定次数的有界 flush：
 * 修复前循环停在第二个挂起请求上（GET 恰好增长到 2、表单停在清空态），
 * 断言完全确定，jsdom 也不会被无限微任务挂死。
 *
 * 事件侧列表行不带明细（后端 EventListView 用 to_view(include_details=False)），
 * 行 fixture 如实省略 ground_detail/air_detail；详情响应按 EventDetailView
 * 真实形态（to_view() 含 ground_detail/air_detail，unknown 场景两者为 null）
 * 返回——EventForm 的 !info.ground_detail && !info.air_detail 守卫在该形态下
 * 恒真，与生产一致地暴露循环。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

// 仅替换 http；hasPermission/Permission/updatePermissions 为 functools 真实现
jest.mock('libs', () => ({
  ...jest.requireActual('../../../libs/functools'),
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  syncAttachmentCount: jest.fn(),
}));

// tableFieldsStore 直接导入真实 http（axios 实例），TableCard 渲染会触发它，
// jsdom 内单独替换（同 permissionMatrix.test.js）
jest.mock('../../../libs/http', () => ({
  get: jest.fn().mockResolvedValue({}),
  post: jest.fn().mockResolvedValue({}),
  put: jest.fn().mockResolvedValue({}),
  delete: jest.fn().mockResolvedValue({}),
}));

const EventsPage = require('../events').default;
const InvestigationsPage = require('../investigations').default;
const S = require('../store').default;
const {updatePermissions} = require('libs');

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

const P = {
  viewEvent: 'interference.interference.view',
  editEvent: 'interference.interference.edit',
  viewInvestigation: 'interference.investigation.view',
  editInvestigation: 'interference.investigation.edit',
};

/** 按项目真实机制注入权限：sessionStorage → updatePermissions → Permission 对象 */
function grant(perms) {
  sessionStorage.setItem('token', 'loop-test-token');
  sessionStorage.setItem('is_supper', 'false');
  sessionStorage.setItem('permissions', JSON.stringify(perms));
  updatePermissions();
}

// 列表行口径（后端 EventListView 用 to_view(include_details=False)：事件行
// 不带 ground_detail/air_detail；调查行仅有列表字段）
const INV_ROW = {id: 7, name: '列表行口径名称', status: 'investigating', owner: '张三', event_count: 3};
const EVENT_ROW = {
  id: 9, datetime: '2026-10-01 08:00:00', scene_code: 'unknown',
  flight_number: 'CA0000', aircraft_no: 'B-20AB', phenomenon: '窄带扫频干扰',
};
// 详情模板：与列表行同 id 但关键字段值不同——表单值是否来自详情响应可判别；
// 每次响应经 {...} 展开生成全新对象（生产 GET 详情每次反序列化出新对象的
// 引用行为）。事件详情 ground_detail/air_detail=null 与后端 EventDetailView
// 对 unknown 场景事件的真实返回一致。
const INV_DETAIL = {...INV_ROW, name: '详情接口回填名称', scope: '重点频段核查'};
const EVENT_DETAIL = {...EVENT_ROW, flight_number: 'CA1234', ground_detail: null, air_detail: null};

let investigationDetailResolvers = [];
let eventDetailResolvers = [];

// 每次调用都返回全新对象，绝不复用引用（恒等手法在本文件禁止）
const makeInvestigationDetail = () => ({...INV_DETAIL});
const makeEventDetail = () => ({...EVENT_DETAIL});

function investigationDetailCalls() {
  return mockHttpGet.mock.calls.filter(call => call[0] === '/api/interference/investigations/7/');
}

function eventDetailCalls() {
  return mockHttpGet.mock.calls.filter(call => call[0] === '/api/interference/events/9/');
}

function resolveInvestigationDetail() {
  const resolve = investigationDetailResolvers.shift();
  expect(resolve).toBeTruthy();
  resolve(makeInvestigationDetail());
}

function resolveEventDetail() {
  const resolve = eventDetailResolvers.shift();
  expect(resolve).toBeTruthy();
  resolve(makeEventDetail());
}

function defaultGetResponder(url) {
  if (url === '/api/interference/events/') {
    return Promise.resolve({records: [{...EVENT_ROW}], total: 1, page: 1, page_size: 20});
  }
  if (/^\/api\/interference\/events\/\d+\/$/.test(url)) {
    // 详情 GET：挂起 deferred，由用例手动以「全新对象」放行
    return new Promise(resolve => { eventDetailResolvers.push(resolve); });
  }
  if (url === '/api/interference/categories/') {
    return Promise.resolve({records: []});
  }
  if (url === '/api/interference/investigations/') {
    return Promise.resolve({records: [{...INV_ROW}], total: 1, page: 1, page_size: 20});
  }
  if (/^\/api\/interference\/investigations\/\d+\/$/.test(url)) {
    return new Promise(resolve => { investigationDetailResolvers.push(resolve); });
  }
  if (url.indexOf('/attachments/') >= 0) {
    return Promise.resolve({records: [], total: 0});
  }
  return Promise.resolve({});
}

let container = null;

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function renderNode(element) {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(element, container);
  });
}

function unmountNode() {
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

function findButton(scope, text) {
  const root = scope || document;
  return Array.from(root.querySelectorAll('.ant-btn'))
    .find(b => b.textContent.replace(/\s+/g, '') === text);
}

function modalByTitle(title) {
  return q('.ant-modal').find(m => {
    const t = m.querySelector('.ant-modal-title');
    return !!t && t.textContent === title;
  });
}

function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

/** 渲染列表页并等待列表加载完成（真实行点击入口的前置步骤） */
async function renderListPage(Page) {
  renderNode(<Page/>);
  await act(async () => { await flush(); await flush(); });
}

/** 点击列表行操作按钮并等待详情 effect 首次执行（恰好 1 个挂起详情请求） */
async function clickRowAction(buttonText) {
  const btn = findButton(document, buttonText);
  expect(btn).toBeTruthy();
  click(btn);
  await act(async () => { await flush(); await flush(); });
}

function resetStore() {
  S.page = 1;
  S.pageSize = 20;
  S.total = 0;
  S.investigationPage = 1;
  S.investigationPageSize = 20;
  S.investigationTotal = 0;
  S.events = [];
  S.event = {};
  S.investigations = [];
  S.investigation = {};
  S.eventFilters = {};
  S.investigationName = '';
  S.investigationStatus = undefined;
  S.eventModalVisible = false;
  S.investigationModalVisible = false;
  S.eventsLoading = false;
  S.investigationsLoading = false;
  S.categoryOptions = {
    interference_kind_code: [],
    affected_system_code: [],
    source_type_code: [],
  };
}

let messageSuccessSpy;

beforeEach(() => {
  jest.clearAllMocks();
  investigationDetailResolvers = [];
  eventDetailResolvers = [];
  mockHttpGet.mockImplementation(defaultGetResponder);
  mockHttpPost.mockResolvedValue({});
  mockHttpPut.mockResolvedValue({});
  mockHttpDelete.mockResolvedValue({});
  resetStore();
  messageSuccessSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
});

afterEach(async () => {
  unmountNode();
  // antd 弹窗/面板关闭动画的卸载定时器若提前摘除节点，会在下一个用例的
  // 时间窗内抛 jsdom NotFoundError；先等它完成再清理（同既有套件）
  await new Promise(resolve => setTimeout(resolve, 400));
  document.querySelectorAll(
    '.ant-modal-root, .ant-modal-confirm, .ant-select-dropdown, .ant-picker-dropdown',
  ).forEach(n => n.remove());
  resetStore();
  investigationDetailResolvers = [];
  eventDetailResolvers = [];
  messageSuccessSpy.mockRestore();
});

describe('2026-10-26 用户实测缺陷：规律调查「编辑」后表单全空（详情 fetch 循环）', () => {
  it('行「编辑」：详情 GET 恰好 1 次且表单以详情响应回填（修复前循环再拉并清空）', async () => {
    grant([P.viewInvestigation, P.editInvestigation]);
    await renderListPage(InvestigationsPage);
    expect(investigationDetailCalls()).toHaveLength(0);

    await clickRowAction('编辑');
    const modal = modalByTitle('规律调查详情');
    expect(modal).toBeTruthy();
    // 首次详情请求已发出且挂起（deferred），此刻恰好 1 次
    expect(investigationDetailCalls()).toHaveLength(1);

    // 放行详情响应（全新对象）→ 有界 flush：详情 effect 依赖的 store.investigation
    // 引用不得再变化，否则 cleanup(resetFields)+重跑 effect 会再发一次请求
    await act(async () => {
      resolveInvestigationDetail();
      await flush();
      await flush();
    });

    // 修复前：响应写入 store → info 引用变化 → effect 重跑 → GET 增长到 2
    expect(investigationDetailCalls()).toHaveLength(1);
    // 修复前：第二次 effect 的 cleanup 先 resetFields，第二次响应仍挂起，
    // 表单停在清空态（用户看到的「表单全空」）
    const nameInput = modal.querySelector('input#name');
    expect(nameInput).toBeTruthy();
    expect(nameInput.value).toBe('详情接口回填名称');
  });

  it('行「查看」：详情加载后查看态只读持久（isViewMode 不被 fetch 覆写丢失）', async () => {
    // grant 含 investigation.edit：修复前首个详情响应把 showInvestigation 注入的
    // isViewMode 覆写丢失，canEdit 翻真 → 保存按钮出现、字段解除禁用（红灯面）
    grant([P.viewInvestigation, P.editInvestigation]);
    await renderListPage(InvestigationsPage);
    await clickRowAction('查看');
    const modal = modalByTitle('规律调查详情');
    expect(modal).toBeTruthy();
    expect(investigationDetailCalls()).toHaveLength(1);

    await act(async () => {
      resolveInvestigationDetail();
      await flush();
      await flush();
    });

    expect(investigationDetailCalls()).toHaveLength(1);
    expect(findButton(modal, '保存')).toBeUndefined();
    expect(findButton(modal, '关闭')).toBeTruthy();
    const nameInput = modal.querySelector('input#name');
    expect(nameInput.disabled).toBe(true);
    // 查看态同样以详情响应回填（只读展示完整详情）
    expect(nameInput.value).toBe('详情接口回填名称');
  });

  it('行「编辑」保存链路回归：修改名称保存，恰好一次 PUT 且携带修改值', async () => {
    grant([P.viewInvestigation, P.editInvestigation]);
    await renderListPage(InvestigationsPage);
    await clickRowAction('编辑');
    await act(async () => {
      resolveInvestigationDetail();
      await flush();
      await flush();
    });
    const modal = modalByTitle('规律调查详情');
    expect(modal).toBeTruthy();
    expect(investigationDetailCalls()).toHaveLength(1);
    const nameInput = modal.querySelector('input#name');
    expect(nameInput.value).toBe('详情接口回填名称');

    setInputValue(nameInput, '修改后的调查名');
    const save = findButton(modal, '保存');
    expect(save).toBeTruthy();
    click(save);
    await act(async () => { await flush(); await flush(); });

    const puts = mockHttpPut.mock.calls.filter(call => call[0] === '/api/interference/investigations/7/');
    expect(puts).toHaveLength(1);
    expect(puts[0][1].name).toBe('修改后的调查名');
    expect(puts[0][1].id).toBe(7);
    expect(S.investigationModalVisible).toBe(false);
  });
});

describe('2026-10-26 用户实测缺陷：干扰事件「编辑」同型循环（行不带明细）', () => {
  it('行「编辑」：事件详情 GET 恰好 1 次且字段以详情响应回填', async () => {
    grant([P.viewEvent, P.editEvent]);
    await renderListPage(EventsPage);
    expect(eventDetailCalls()).toHaveLength(0);

    await clickRowAction('编辑');
    const modal = modalByTitle('编辑干扰事件');
    expect(modal).toBeTruthy();
    // 行 fixture 不带 ground_detail/air_detail（真实列表口径）→ EventForm
    // 守卫放行详情拉取；挂起 deferred 下此刻恰好 1 次
    expect(eventDetailCalls()).toHaveLength(1);

    // 详情响应 unknown 场景真实形态（ground_detail/air_detail=null，全新对象）：
    // 修复前守卫恒真 → effect 重跑 → GET 增长到 2 并清空表单
    await act(async () => {
      resolveEventDetail();
      await flush();
      await flush();
    });

    expect(eventDetailCalls()).toHaveLength(1);
    const flightInput = modal.querySelector('input#flight_number');
    expect(flightInput).toBeTruthy();
    expect(flightInput.value).toBe('CA1234');
  });

  it('行「查看」：详情加载后查看态只读持久（isViewMode 存活、字段回填）', async () => {
    grant([P.viewEvent, P.editEvent]);
    await renderListPage(EventsPage);
    await clickRowAction('查看');
    const modal = modalByTitle('干扰事件详情');
    expect(modal).toBeTruthy();
    expect(eventDetailCalls()).toHaveLength(1);

    await act(async () => {
      resolveEventDetail();
      await flush();
      await flush();
    });

    expect(eventDetailCalls()).toHaveLength(1);
    expect(findButton(modal, '保存')).toBeUndefined();
    expect(findButton(modal, '关闭')).toBeTruthy();
    const flightInput = modal.querySelector('input#flight_number');
    expect(flightInput.disabled).toBe(true);
    expect(flightInput.value).toBe('CA1234');
  });

  it('行「编辑」保存链路回归：恰好一次 POST 且携带事件 id', async () => {
    grant([P.viewEvent, P.editEvent]);
    await renderListPage(EventsPage);
    await clickRowAction('编辑');
    await act(async () => {
      resolveEventDetail();
      await flush();
      await flush();
    });
    const modal = modalByTitle('编辑干扰事件');
    expect(modal).toBeTruthy();
    expect(eventDetailCalls()).toHaveLength(1);
    const flightInput = modal.querySelector('input#flight_number');
    expect(flightInput.value).toBe('CA1234');

    const save = findButton(modal, '保存');
    expect(save).toBeTruthy();
    click(save);
    await act(async () => { await flush(); await flush(); });

    const posts = mockHttpPost.mock.calls.filter(call => call[0] === '/api/interference/events/');
    expect(posts).toHaveLength(1);
    expect(posts[0][1].id).toBe(9);
    expect(S.eventModalVisible).toBe(false);
  });
});
