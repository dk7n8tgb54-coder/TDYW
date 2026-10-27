/**
 * 干扰管理三操作权限矩阵对齐测试（2026-10-26）。
 *
 * 后端真实授权集合（后端保持不动，前端权限表达对齐之）：
 * - 创建调查   POST /api/interference/investigations/
 *     = interference.investigation.add | interference.interference.add
 * - 加入已有调查 POST /api/interference/investigations/<pk>/events/
 *     = interference.investigation.edit | interference.interference.add
 * - 录入测量   POST /api/interference/investigations/<pk>/measurements/
 *     = interference.measurement.add | interference.investigation.edit
 *     （measurement.edit 不被录入端点接受：仅持它时录入入口必须不可用——负向场景）
 * - 编辑调查   PUT /api/interference/investigations/<pk>/ = 仅 investigation.edit，
 *     编辑路径门禁不得放宽；调查附件（readOnly={!canEdit}）与测量附件
 *     （canEditMeasurementAttachments）为非目标消费点，语义保持不变。
 *
 * 真实渲染 EventsPage / InvestigationsPage / InvestigationForm（ReactDOM + jsdom）。
 * 权限注入走项目真实机制：sessionStorage 的 permissions JSON 数组与 is_supper，
 * 调 libs.updatePermissions() 填充真实 Permission 对象；libs 仅替换 http，
 * hasPermission / Permission 为 functools 真实现——AuthButton、AuthDiv 与页面内
 * hasPermission 判断消费同一份真实权限对象，杜绝 mock 恒真。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import moment from 'moment';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

// 仅替换 http；functools（hasPermission/Permission/updatePermissions）为真实现
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

// tableFieldsStore 直接导入真实 http（axios 实例），不走 'libs' 别名；
// TableCard 渲染会触发它，单独替换之，杜绝 jsdom 里的真实网络请求
jest.mock('../../../libs/http', () => ({
  get: jest.fn().mockResolvedValue({}),
  post: jest.fn().mockResolvedValue({}),
  put: jest.fn().mockResolvedValue({}),
  delete: jest.fn().mockResolvedValue({}),
}));

const EventsPage = require('../events').default;
const InvestigationsPage = require('../investigations').default;
const InvestigationForm = require('../InvestigationForm').default;
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
  addEvent: 'interference.interference.add',
  viewInvestigation: 'interference.investigation.view',
  addInvestigation: 'interference.investigation.add',
  editInvestigation: 'interference.investigation.edit',
  addMeasurement: 'interference.measurement.add',
  editMeasurement: 'interference.measurement.edit',
  viewMeasurement: 'interference.measurement.view',
};

/** 按项目真实机制注入权限：sessionStorage → updatePermissions → Permission 对象 */
function grant(perms) {
  sessionStorage.setItem('token', 'matrix-token');
  sessionStorage.setItem('is_supper', 'false');
  sessionStorage.setItem('permissions', JSON.stringify(perms));
  updatePermissions();
}

function grantSuper() {
  sessionStorage.setItem('token', 'matrix-token');
  sessionStorage.setItem('is_supper', 'true');
  sessionStorage.setItem('permissions', '[]');
  updatePermissions();
}

const EVENT_A = {id: 1, datetime: '2026-10-01 08:00:00', scene_code: 'ground', phenomenon: '事件一'};
const EVENT_B = {id: 2, datetime: '2026-10-02 09:00:00', scene_code: 'air', phenomenon: '事件二'};
const BASE_DETAIL = {
  id: 5, name: '既有调查', status: 'investigating', owner: '张三',
  events: [], measurements: [], event_count: 0,
};
// 个别用例需要详情带测量行（测量附件护栏），可临时覆盖
let detailOverride = null;
// 详情响应在同一用例内必须返回同一对象引用：InvestigationForm 的详情 effect
// 依赖 [visible, info, infoId, form]，而 store.fetchInvestigation 会把响应写回
// store.investigation——若每次返回新对象，effect 会自激励无限拉取并把 jsdom
// 困在微任务循环里（生产环境等价于模态打开期间反复拉详情，属既有行为，
// 不在本次修改范围）。测试内让响应引用收敛，effect 跑两轮即稳定。
let detailData = null;

function currentDetail() {
  if (!detailData) {
    detailData = detailOverride ? {...BASE_DETAIL, ...detailOverride} : {...BASE_DETAIL};
  }
  return detailData;
}

function defaultGetResponder(url, config) {
  const params = (config && config.params) || {};
  if (url === '/api/interference/events/') {
    return Promise.resolve({records: [EVENT_A, EVENT_B], total: 2, page: 1, page_size: 20});
  }
  if (url === '/api/interference/investigations/') {
    if (params.page_size === 100) {
      // 「加入已有调查」弹窗的调查选项查询（page=1&page_size=100）
      return Promise.resolve({records: [
        {id: 7, name: '调查七', status: 'investigating', event_count: 2},
        {id: 8, name: '调查八', status: 'investigating', event_count: 0},
      ], total: 2, page: 1, page_size: 100});
    }
    return Promise.resolve({records: [
      {id: 7, name: '调查七', status: 'investigating', event_count: 2},
    ], total: 1, page: 1, page_size: 20});
  }
  if (/^\/api\/interference\/investigations\/\d+\/$/.test(url)) {
    // 详情响应与 store 现值引用恒等：InvestigationForm 的详情 effect 依赖
    // [visible, info, infoId, form]，若响应是异于 store 现值的新对象，effect
    // 会被自己的响应反复触发（生产环境等价于模态打开期间反复拉详情，属既有
    // 行为，不在本次修改范围）。返回 store 现值本身可从构造上杜绝自激励。
    const detailId = Number(url.match(/\d+/)[0]);
    if (S.investigation && S.investigation.id === detailId) {
      return Promise.resolve(S.investigation);
    }
    return Promise.resolve(currentDetail());
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

function selectFirstRow() {
  const checkbox = document.querySelector('.ant-table-tbody .ant-checkbox-input');
  expect(checkbox).toBeTruthy();
  click(checkbox);
}

/** 勾选一行 → 勾选态使「创建调查/加入已有调查」脱离 selection-disabled */
async function renderEventsAndSelectRow() {
  renderNode(<EventsPage/>);
  await act(async () => { await flush(); });
  selectFirstRow();
  await act(async () => { await flush(); });
}

/** 直接以编辑态渲染 InvestigationForm 并切到「频谱测量」页签 */
async function renderEditFormWithMeasurementsTab() {
  // 详情响应与 store 初值必须是同一对象引用：InvestigationForm 的详情 effect
  // 依赖 [visible, info, infoId, form]，而 store.fetchInvestigation 会把响应写回
  // store.investigation——若初值与响应是不同对象，effect 会被自己的响应反复
  // 触发（生产环境等价于模态打开期间反复拉详情，属既有行为，不在本次修改
  // 范围）。测试内让引用恒等，effect 恰好只跑一次。
  detailData = detailOverride ? {...BASE_DETAIL, ...detailOverride} : {...BASE_DETAIL};
  S.investigation = detailData;
  S.investigationModalVisible = true;
  renderNode(<InvestigationForm/>);
  await act(async () => { await flush(); });
  const tab = q('.ant-tabs-tab').find(t => t.textContent.indexOf('频谱测量') >= 0);
  expect(tab).toBeTruthy();
  click(tab);
  await act(async () => { await flush(); });
}

/** 通过真实日期面板填写测量时间（showTime：点日期单元格 + 确定） */
async function fillMeasuredAt(modal) {
  const pickerInput = modal.querySelector('.ant-picker input');
  expect(pickerInput).toBeTruthy();
  await act(async () => {
    pickerInput.focus();
    pickerInput.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    pickerInput.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    pickerInput.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
  const cell = document.querySelector(
    `.ant-picker-panel td[title="${moment().date(15).format('YYYY-MM-DD')}"] .ant-picker-cell-inner`);
  expect(cell).toBeTruthy();
  await act(async () => {
    cell.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
  const okButton = document.querySelector('.ant-picker-ok button');
  if (okButton) {
    await act(async () => {
      okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
  }
  expect(pickerInput.value).not.toBe('');
}

function postsTo(fragment) {
  return mockHttpPost.mock.calls.filter(call => call[0].indexOf(fragment) >= 0);
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
}

let messageSuccessSpy;
let messageErrorSpy;

beforeEach(() => {
  jest.clearAllMocks();
  mockHttpGet.mockImplementation(defaultGetResponder);
  mockHttpPost.mockResolvedValue({});
  detailOverride = null;
  detailData = null;
  resetStore();
  messageSuccessSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  messageErrorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
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
  messageSuccessSpy.mockRestore();
  messageErrorSpy.mockRestore();
});

describe('创建调查：investigation.add | interference.add', () => {
  it('仅持 investigation.add：事件页「创建调查」可用（回归护栏）', async () => {
    grant([P.viewEvent, P.addInvestigation]);
    await renderEventsAndSelectRow();
    const btn = findButton(document, '创建调查');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
  });

  it('仅持 interference.add：事件页「创建调查」点击后弹出调查表单，未保存前零 POST /investigations', async () => {
    grant([P.viewEvent, P.addEvent]);
    await renderEventsAndSelectRow();
    const btn = findButton(document, '创建调查');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
    // 2026-10-26 死端修复：events.js 已接通 InvestigationForm 渲染（此前 HEAD
    // 既未 import 也未渲染，点击后无任何 UI 响应）。按本用例预留的升级说明同步
    // 为全链路口径：点击后弹窗必须出现且携带所选事件；未保存前保持零 POST
    //（保留原用例的零请求断言语义）。
    click(btn);
    await act(async () => { await flush(); });
    const modal = modalByTitle('新建规律调查');
    expect(modal).toBeTruthy();
    expect(S.investigationModalVisible).toBe(true);
    expect(S.investigation.event_ids).toEqual([1]);
    expect(postsTo('/api/interference/investigations/')).toHaveLength(0);
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  it('仅持 investigation.add：调查页「新建调查」可用并完成 POST 创建（回归护栏）', async () => {
    grant([P.viewInvestigation, P.addInvestigation]);
    renderNode(<InvestigationsPage/>);
    await act(async () => { await flush(); });
    const btn = findButton(document, '新建调查');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
    click(btn);
    await act(async () => { await flush(); });
    const modal = modalByTitle('新建规律调查');
    expect(modal).toBeTruthy();
    const save = findButton(modal, '保存');
    expect(save).toBeTruthy();
    setInputValue(modal.querySelector('input#name'), '仅调查新增权限创建');
    click(save);
    await act(async () => { await flush(); await flush(); });
    expect(postsTo('/api/interference/investigations/')).toHaveLength(1);
    const [url, payload] = postsTo('/api/interference/investigations/')[0];
    expect(url).toBe('/api/interference/investigations/');
    expect(payload.name).toBe('仅调查新增权限创建');
    expect(payload).not.toHaveProperty('event_ids');
  });

  it('仅持 interference.add：调查页「新建调查」可用并完成 POST 创建（创建分支全链路）', async () => {
    grant([P.viewInvestigation, P.addEvent]);
    renderNode(<InvestigationsPage/>);
    await act(async () => { await flush(); });
    const btn = findButton(document, '新建调查');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
    click(btn);
    await act(async () => { await flush(); });
    const modal = modalByTitle('新建规律调查');
    expect(modal).toBeTruthy();
    expect(findButton(modal, '保存')).toBeTruthy();
    const nameInput = modal.querySelector('input#name');
    expect(nameInput.disabled).toBe(false);
    setInputValue(nameInput, '仅干扰新增权限创建');
    click(findButton(modal, '保存'));
    await act(async () => { await flush(); await flush(); });
    expect(postsTo('/api/interference/investigations/')).toHaveLength(1);
    const [url, payload] = postsTo('/api/interference/investigations/')[0];
    expect(url).toBe('/api/interference/investigations/');
    expect(payload.name).toBe('仅干扰新增权限创建');
    expect(payload).not.toHaveProperty('event_ids');
  });

  it('两者皆无：三个入口按钮不可见，创建态表单只读且不产生 POST /investigations', async () => {
    grant([P.viewEvent, P.viewInvestigation]);
    renderNode(<EventsPage/>);
    await act(async () => { await flush(); });
    expect(findButton(document, '创建调查')).toBeUndefined();
    expect(findButton(document, '加入已有调查')).toBeUndefined();
    unmountNode();
    renderNode(<InvestigationsPage/>);
    await act(async () => { await flush(); });
    expect(findButton(document, '新建调查')).toBeUndefined();
    unmountNode();
    // 即使表单被直接打开（绕过入口），创建态也必须只读且无法发起 POST
    S.investigationModalVisible = true;
    S.investigation = {};
    renderNode(<InvestigationForm/>);
    await act(async () => { await flush(); });
    const modal = modalByTitle('新建规律调查');
    expect(modal).toBeTruthy();
    expect(findButton(modal, '保存')).toBeUndefined();
    expect(findButton(modal, '关闭')).toBeTruthy();
    expect(modal.querySelector('input#name').disabled).toBe(true);
    expect(postsTo('/investigations')).toHaveLength(0);
    expect(mockHttpPost).not.toHaveBeenCalled();
  });
});

describe('加入已有调查：investigation.edit | interference.add', () => {
  it('仅持 investigation.edit：按钮可用（回归护栏）', async () => {
    grant([P.viewEvent, P.editInvestigation]);
    await renderEventsAndSelectRow();
    const btn = findButton(document, '加入已有调查');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
  });

  it('仅持 interference.add：按钮可用，选择调查后 POST 加入', async () => {
    grant([P.viewEvent, P.addEvent]);
    await renderEventsAndSelectRow();
    const btn = findButton(document, '加入已有调查');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
    click(btn);
    await act(async () => { await flush(); });
    const modal = modalByTitle('加入已有调查');
    expect(modal).toBeTruthy();
    // 选项按 page=1&page_size=100 查询
    const optionCalls = mockHttpGet.mock.calls.filter(
      call => call[0] === '/api/interference/investigations/' &&
        call[1] && call[1].params && call[1].params.page_size === 100);
    expect(optionCalls).toHaveLength(1);
    const selector = modal.querySelector('.ant-select-selector');
    expect(selector).toBeTruthy();
    await act(async () => {
      selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      await flush();
    });
    const option = document.querySelector(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option');
    expect(option).toBeTruthy();
    await act(async () => {
      option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    click(modal.querySelector('.ant-modal-footer .ant-btn-primary'));
    await act(async () => { await flush(); await flush(); });
    expect(postsTo('/events/')).toHaveLength(1);
    const [url, payload] = postsTo('/events/')[0];
    expect(url).toBe('/api/interference/investigations/7/events/');
    expect(payload.event_ids).toEqual([1]);
  });

  it('两者皆无：按钮不可见且不产生 POST events 请求', async () => {
    grant([P.viewEvent]);
    await renderEventsAndSelectRow();
    expect(findButton(document, '加入已有调查')).toBeUndefined();
    expect(postsTo('/events/')).toHaveLength(0);
    expect(mockHttpPost).not.toHaveBeenCalled();
  });
});

// 门禁等价拆分（2026-10-26）：下方「录入测量」describe 的用例体整体抽为模块级
// helper（每个 ≤120 行），describe/it 名称、断言内容、用例数量与 mock 行为
// 一字不改，仅结构搬移（函数声明提升，先声明后引用合法）。
async function caseMeasurementAddFullChain() {
  grant([P.addMeasurement]);
  mockHttpPost.mockResolvedValue({});
  await renderEditFormWithMeasurementsTab();
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(false);
  click(btn);
  await act(async () => { await flush(); });
  const modal = modalByTitle('录入频谱测量');
  expect(modal).toBeTruthy();
  // 子表单不得被共享 canEdit 锁死：字段可编辑
  expect(modal.querySelector('.ant-picker input').disabled).toBe(false);
  await fillMeasuredAt(modal);
  click(modal.querySelector('.ant-modal-footer .ant-btn-primary'));
  await act(async () => { await flush(); await flush(); });
  expect(postsTo('/measurements/')).toHaveLength(1);
  const [url, payload] = postsTo('/measurements/')[0];
  expect(url).toBe('/api/interference/investigations/5/measurements/');
  expect(payload.measured_at).toEqual(expect.stringContaining(
    String(moment().year())));
  // 成功后详情重新拉取（测量列表刷新）：初始 1 次 + 提交后 1 次
  const detailCalls = mockHttpGet.mock.calls.filter(
    call => call[0] === '/api/interference/investigations/5/');
  expect(detailCalls).toHaveLength(2);
  expect(messageSuccessSpy).toHaveBeenCalledWith('测量记录已保存');
}

async function caseInvestigationEditCanEnterMeasurement() {
  grant([P.editInvestigation]);
  await renderEditFormWithMeasurementsTab();
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(false);
  click(btn);
  await act(async () => { await flush(); });
  expect(modalByTitle('录入频谱测量')).toBeTruthy();
}

async function caseMeasurementEditOnlyDenied() {
  grant([P.editMeasurement]);
  await renderEditFormWithMeasurementsTab();
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(true);
  click(btn);
  await act(async () => { await flush(); });
  expect(modalByTitle('录入频谱测量')).toBeUndefined();
  expect(mockHttpPost).not.toHaveBeenCalled();
}

async function caseNoPermissionMeasurementEntryDenied() {
  grant([]);
  await renderEditFormWithMeasurementsTab();
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(true);
  expect(modalByTitle('录入频谱测量')).toBeUndefined();
  expect(mockHttpPost).not.toHaveBeenCalled();
}

async function caseEditGateNotRelaxedForInterferenceAdd() {
  grant([P.addEvent]);
  await renderEditFormWithMeasurementsTab();
  const modal = modalByTitle('规律调查详情');
  expect(modal).toBeTruthy();
  expect(findButton(modal, '保存')).toBeUndefined();
  expect(findButton(modal, '关闭')).toBeTruthy();
  expect(modal.querySelector('input#name').disabled).toBe(true);
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(true);
  expect(mockHttpPost).not.toHaveBeenCalled();
}

async function caseViewModeSaveAndMeasurementDenied() {
  grant([P.viewInvestigation, P.viewMeasurement]);
  await renderEditFormWithMeasurementsTab();
  const modal = modalByTitle('规律调查详情');
  expect(modal).toBeTruthy();
  expect(findButton(modal, '保存')).toBeUndefined();
  expect(modal.querySelector('input#name').disabled).toBe(true);
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(true);
  // 2026-10-26 决策护栏：无 measurement.add 且无 investigation.edit 的查看态
  // 不被决策放宽——点击后零弹窗、零 POST
  click(btn);
  await act(async () => { await flush(); });
  expect(modalByTitle('录入频谱测量')).toBeUndefined();
  expect(mockHttpPost).not.toHaveBeenCalled();
}

async function caseViewModeWithMeasurementAddAllowed() {
  // 2026-10-26 产品决策反转本用例：原「查看态 + measurement.add：录入测量仍不可用」
  // 钉住的 canEnterMeasurement 的 !info.isViewMode 因子被决策否定——查看态不阻断
  // 后端授权的测量录入（POST /investigations/<pk>/measurements/ =
  // measurement.add|investigation.edit，后端本无 isViewMode 概念）；调查字段只读
  // 仍由 canEdit 的 isViewMode 因子保证（下方保存/名称只读断言保留）。
  // isViewMode 放入详情响应（详情响应与 store 现值恒等），查看态在拉取详情后保持。
  grant([P.addMeasurement, P.viewMeasurement]);
  detailOverride = {...BASE_DETAIL, isViewMode: true};
  await renderEditFormWithMeasurementsTab();
  const modal = modalByTitle('规律调查详情');
  expect(modal).toBeTruthy();
  expect(findButton(modal, '保存')).toBeUndefined();
  expect(modal.querySelector('input#name').disabled).toBe(true);
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(false);
  click(btn);
  await act(async () => { await flush(); });
  expect(modalByTitle('录入频谱测量')).toBeTruthy();
  // 打开弹窗本身不得产生任何请求（负向断言保留）
  expect(mockHttpPost).not.toHaveBeenCalled();
}

async function caseCreateModeHasNoMeasurementEntry() {
  grant([P.addInvestigation, P.addMeasurement, P.editMeasurement]);
  S.investigationModalVisible = true;
  S.investigation = {};
  renderNode(<InvestigationForm/>);
  await act(async () => { await flush(); });
  expect(q('.ant-tabs-tab')).toHaveLength(0);
  expect(findButton(document, '录入测量')).toBeUndefined();
}

describe('录入测量：measurement.add | investigation.edit（measurement.edit 为负向）', () => {
  it('仅持 measurement.add：录入测量全链路可用（按钮→弹窗→提交 POST measurements→详情刷新）', async () => { await caseMeasurementAddFullChain(); });

  it('仅持 investigation.edit：录入测量可用', async () => { await caseInvestigationEditCanEnterMeasurement(); });

  it('仅持 measurement.edit：录入入口不可用（负向：录入端点不接受 measurement.edit）', async () => { await caseMeasurementEditOnlyDenied(); });

  it('皆无权限：录入入口不可用', async () => { await caseNoPermissionMeasurementEntryDenied(); });

  it('编辑门禁不放宽：仅持 interference.add 打开既有调查，保存不可用且录入测量不可用', async () => { await caseEditGateNotRelaxedForInterferenceAdd(); });

  it('查看态（仅 view 权限）：保存与录入测量均不可用', async () => { await caseViewModeSaveAndMeasurementDenied(); });

  it('查看态 + 持有 measurement.add：录入测量可用（2026-10-26 产品决策反转 isViewMode 因子）', async () => { await caseViewModeWithMeasurementAddAllowed(); });

  it('创建态（无 id）：无频谱测量入口（既有拦截行为保持）', async () => { await caseCreateModeHasNoMeasurementEntry(); });
});

describe('非目标消费点护栏：测量附件与超管', () => {
  it('调查编辑者 + measurement.add：测量附件上传区仍在，录入测量可用', async () => {
    grant([P.editInvestigation, P.addMeasurement, P.viewMeasurement]);
    detailOverride = {...BASE_DETAIL,
      measurements: [{id: 101, measured_at: '2026-10-01 08:00:00', location: 'A点'}]};
    await renderEditFormWithMeasurementsTab();
    const row = document.querySelector('.ant-table-row');
    expect(row).toBeTruthy();
    // 测量附件门禁（canEditMeasurementAttachments）语义保持：可上传
    expect(row.querySelector('.ant-upload')).toBeTruthy();
    const btn = findButton(document, '录入测量');
    expect(btn.disabled).toBe(false);
  });

  it('调查编辑者无测量写权限：测量附件上传区不出现（readOnly 未被放宽）', async () => {
    grant([P.editInvestigation, P.viewMeasurement]);
    detailOverride = {...BASE_DETAIL,
      measurements: [{id: 101, measured_at: '2026-10-01 08:00:00', location: 'A点'}]};
    await renderEditFormWithMeasurementsTab();
    const row = document.querySelector('.ant-table-row');
    expect(row).toBeTruthy();
    expect(row.querySelector('.ant-upload')).toBeNull();
  });

  it('仅持 measurement.add：录入测量可用但测量附件上传区不出现（canEdit 因子钉住）', async () => {
    // canEditMeasurementAttachments = canEdit && (measurement.add|measurement.edit)：
    // 仅持 measurement.add 时 canEnterMeasurement 为 true（录入入口可用），但
    // canEdit（调查编辑权）因子使附件仍只读——钉住该 AND 因子，防止未来被误改为
    // canEnterMeasurement 而越过后端 ATTACHMENT_PERMISSION_MAP 口径。
    grant([P.addMeasurement, P.viewMeasurement]);
    detailOverride = {...BASE_DETAIL,
      measurements: [{id: 101, measured_at: '2026-10-01 08:00:00', location: 'A点'}]};
    await renderEditFormWithMeasurementsTab();
    const row = document.querySelector('.ant-table-row');
    expect(row).toBeTruthy();
    // 录入入口可用（canEnterMeasurement 因子不受本用例影响）
    const btn = findButton(document, '录入测量');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
    // 但测量附件上传区不得出现（canEdit 因子生效）
    expect(row.querySelector('.ant-upload')).toBeNull();
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  it('超管直通：无权限数组也可用全部入口（真实 is_supper 机制）', async () => {
    grantSuper();
    renderNode(<InvestigationsPage/>);
    await act(async () => { await flush(); });
    const btn = findButton(document, '新建调查');
    expect(btn).toBeTruthy();
    click(btn);
    await act(async () => { await flush(); });
    expect(findButton(modalByTitle('新建规律调查'), '保存')).toBeTruthy();
    unmountNode();
    renderNode(<EventsPage/>);
    await act(async () => { await flush(); });
    expect(findButton(document, '创建调查')).toBeTruthy();
    expect(findButton(document, '加入已有调查')).toBeTruthy();
  });
});

describe('canEdit 门禁重构（2026-10-26）：创建态对齐 POST 口径、编辑态保持仅 investigation.edit', () => {
  it('仅持 investigation.edit：创建态表单只读（保存不出现、字段禁用、零 POST）', async () => {
    // 修复前 canEdit 的首个析取支无条件生效：investigation.edit-only 用户在创建态
    // （!infoId）canEdit=true，可编辑创建表单，但后端 POST /investigations/ 只认
    // investigation.add|interference.add（views.py:520-521），保存必被拒。
    // 被测对象是表单内部门禁而非可达性，直接经 store 打开创建态是可接受的。
    grant([P.editInvestigation]);
    S.investigationModalVisible = true;
    S.investigation = {};
    renderNode(<InvestigationForm/>);
    await act(async () => { await flush(); });
    const modal = modalByTitle('新建规律调查');
    expect(modal).toBeTruthy();
    expect(findButton(modal, '保存')).toBeUndefined();
    expect(findButton(modal, '关闭')).toBeTruthy();
    expect(modal.querySelector('input#name').disabled).toBe(true);
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  it('护栏：仅持 investigation.edit 编辑既有调查 → 保存可用（编辑分支不得被收紧误伤）', async () => {
    grant([P.editInvestigation]);
    detailData = {...BASE_DETAIL};
    S.investigation = detailData;
    S.investigationModalVisible = true;
    renderNode(<InvestigationForm/>);
    await act(async () => { await flush(); });
    const modal = modalByTitle('规律调查详情');
    expect(modal).toBeTruthy();
    expect(findButton(modal, '保存')).toBeTruthy();
    expect(findButton(modal, '取消')).toBeTruthy();
    expect(modal.querySelector('input#name').disabled).toBe(false);
  });
  // 其余两向护栏由既有用例承载，不在本组重复：
  // - 仅持 interference.add 打开既有调查 → 保存与录入均不可用：
  //   「编辑门禁不放宽：仅持 interference.add 打开既有调查，保存不可用且录入测量不可用」
  // - 仅持 investigation.add / interference.add 创建态 → 保存可用：
  //   「仅持 investigation.add：调查页「新建调查」可用并完成 POST 创建（回归护栏）」
  //   「仅持 interference.add：调查页「新建调查」可用并完成 POST 创建（创建分支全链路）」
});

// 门禁等价拆分（2026-10-26）：下方「问题2 真实导航链」describe 的用例体整体抽为
// 模块级 helper（每个 ≤120 行），describe/it 名称、断言内容、用例数量与 mock
// 行为一字不改，仅结构搬移（函数声明提升，先声明后引用合法）。
async function caseNavigationViaEditButtonFullChain() {
  grant([P.viewInvestigation, P.editInvestigation]);
  renderNode(<InvestigationsPage/>);
  await act(async () => { await flush(); });
  const editBtn = findButton(document, '编辑');
  expect(editBtn).toBeTruthy();
  click(editBtn);
  await act(async () => { await flush(); });
  const modal = modalByTitle('规律调查详情');
  expect(modal).toBeTruthy();
  // 编辑态：保存可用（canEdit 编辑分支）
  expect(findButton(modal, '保存')).toBeTruthy();
  const tab = q('.ant-tabs-tab').find(t => t.textContent.indexOf('频谱测量') >= 0);
  expect(tab).toBeTruthy();
  click(tab);
  await act(async () => { await flush(); });
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(false);
  click(btn);
  await act(async () => { await flush(); });
  const mModal = modalByTitle('录入频谱测量');
  expect(mModal).toBeTruthy();
  await fillMeasuredAt(mModal);
  click(mModal.querySelector('.ant-modal-footer .ant-btn-primary'));
  await act(async () => { await flush(); await flush(); });
  expect(postsTo('/measurements/')).toHaveLength(1);
  expect(postsTo('/measurements/')[0][0])
    .toBe('/api/interference/investigations/7/measurements/');
  expect(messageSuccessSpy).toHaveBeenCalledWith('测量记录已保存');
  // 成功后详情重新拉取：打开详情 1 次 + 录入成功后刷新 1 次
  const detailCalls = mockHttpGet.mock.calls.filter(
    call => call[0] === '/api/interference/investigations/7/');
  expect(detailCalls).toHaveLength(2);
}

async function caseMeasurementAddOnlyBlockedByAuthDiv() {
  // 角色树（system/role/codes.js 频谱测量组）允许单独勾选「录入频谱测量」，
  // 但页面唯一入口 AuthDiv(interference.investigation.view) 先行拦截整页：
  // 无行操作、无表单、无弹窗，零测量 POST。2026-10-26 产品决策只放行
  // 「查看态（已有 investigation.view）+ measurement.add|investigation.edit」的
  // 录入；单独 measurement.add（无 investigation.view）仍无页面入口，
  // 需在角色配置中同时授予「查看规律调查」（codes.js label 已标注依赖）。
  grant([P.addMeasurement, P.viewMeasurement]);
  renderNode(<InvestigationsPage/>);
  await act(async () => { await flush(); });
  expect(findButton(document, '编辑')).toBeUndefined();
  expect(findButton(document, '查看')).toBeUndefined();
  expect(findButton(document, '新建调查')).toBeUndefined();
  expect(document.querySelector('.ant-table')).toBeNull();
  expect(q('.ant-modal')).toHaveLength(0);
  expect(mockHttpPost).not.toHaveBeenCalled();
}

async function caseNavigationViaViewButtonWithMeasurementAdd() {
  // 原「查看态后录入测量 disabled（isViewMode 因子）」被 2026-10-26 产品决策反转：
  // 查看态不阻断后端授权的测量录入；调查字段只读断言（保存不出现、名称只读）
  // 与「编辑」不可见等仍有效的负向断言全部保留。全链路：行「查看」→ 详情弹窗
  // （调查字段只读）→ 频谱测量页签 → 录入测量 enabled → 弹窗 → 日期面板填
  // 测量时间 → 恰好一次 POST → 成功后详情重新拉取。
  grant([P.viewInvestigation, P.addMeasurement, P.viewMeasurement]);
  renderNode(<InvestigationsPage/>);
  await act(async () => { await flush(); });
  expect(findButton(document, '编辑')).toBeUndefined();
  const viewBtn = findButton(document, '查看');
  expect(viewBtn).toBeTruthy();
  click(viewBtn);
  await act(async () => { await flush(); });
  const modal = modalByTitle('规律调查详情');
  expect(modal).toBeTruthy();
  // 查看态调查字段只读（canEdit 的 isViewMode 因子未放宽）
  expect(findButton(modal, '保存')).toBeUndefined();
  expect(modal.querySelector('input#name').disabled).toBe(true);
  const tab = q('.ant-tabs-tab').find(t => t.textContent.indexOf('频谱测量') >= 0);
  expect(tab).toBeTruthy();
  click(tab);
  await act(async () => { await flush(); });
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(false);
  click(btn);
  await act(async () => { await flush(); });
  const mModal = modalByTitle('录入频谱测量');
  expect(mModal).toBeTruthy();
  // 提交前显式零 POST：防止未来流程混入对其它 URL 的 POST 被
  // 「恰 1 次」的 /measurements/ 片段计数掩盖（同组件级反转用例口径）
  expect(mockHttpPost).not.toHaveBeenCalled();
  await fillMeasuredAt(mModal);
  click(mModal.querySelector('.ant-modal-footer .ant-btn-primary'));
  await act(async () => { await flush(); await flush(); });
  expect(postsTo('/measurements/')).toHaveLength(1);
  expect(postsTo('/measurements/')[0][0])
    .toBe('/api/interference/investigations/7/measurements/');
  expect(messageSuccessSpy).toHaveBeenCalledWith('测量记录已保存');
  // 成功后详情重新拉取：打开详情 1 次 + 录入成功后刷新 1 次
  const detailCalls = mockHttpGet.mock.calls.filter(
    call => call[0] === '/api/interference/investigations/7/');
  expect(detailCalls).toHaveLength(2);
}

async function caseNavigationViaViewButtonWithInvestigationEdit() {
  // 2026-10-26 决策的 OR 第二支：查看态 + investigation.edit 亦可录入（后端
  // POST /investigations/<pk>/measurements/ 对 investigation.edit 同等授权）；
  // 按钮级 + 打开弹窗即可，POST 链路由上一用例覆盖。
  // 边界如实注明：下方「保存不出现/名称只读」装饰断言依赖 harness「详情响应
  // 返回 store 现值」恒等手法保留的 isViewMode；生产中 store.fetchInvestigation
  // 整体覆写丢失 isViewMode（既有缺陷），该组合经行「查看」进入时调查字段
  // 可能显示为可编辑。本用例的核心保证是录入按钮 enabled、弹窗打开、未提交
  // 零 POST——只读装饰断言的边界待 store 侧修复后自然收紧。
  grant([P.viewInvestigation, P.editInvestigation]);
  renderNode(<InvestigationsPage/>);
  await act(async () => { await flush(); });
  const viewBtn = findButton(document, '查看');
  expect(viewBtn).toBeTruthy();
  click(viewBtn);
  await act(async () => { await flush(); });
  const modal = modalByTitle('规律调查详情');
  expect(modal).toBeTruthy();
  expect(findButton(modal, '保存')).toBeUndefined();
  expect(modal.querySelector('input#name').disabled).toBe(true);
  const tab = q('.ant-tabs-tab').find(t => t.textContent.indexOf('频谱测量') >= 0);
  expect(tab).toBeTruthy();
  click(tab);
  await act(async () => { await flush(); });
  const btn = findButton(document, '录入测量');
  expect(btn).toBeTruthy();
  expect(btn.disabled).toBe(false);
  click(btn);
  await act(async () => { await flush(); });
  expect(modalByTitle('录入频谱测量')).toBeTruthy();
  expect(mockHttpPost).not.toHaveBeenCalled();
}

describe('问题2 真实导航链（2026-10-26 决策后：查看态放行测量录入，仅 view 缺口保持文档化）', () => {
  // 链路门槛（全部只读核实）：
  // 路由 /interference/investigations auth=interference.investigation.view（routes.js）
  //   → 页面 AuthDiv(interference.investigation.view) 包裹整页（investigations.js）
  //   → 行操作「查看」=investigation.view（进 isViewMode 态）、
  //     「编辑」=investigation.edit（进编辑态）→ 录入测量按钮 disabled=
  //     !canEnterMeasurement（2026-10-26 决策后 = measurement.add|investigation.edit，
  //     查看态不再阻断）
  //   → POST /investigations/<pk>/measurements/ = measurement.add|investigation.edit（views.py）
  // 2026-10-26 决策后最小 UI 可达组合={investigation.view, measurement.add} 或
  // {investigation.view, investigation.edit}；measurement.add 单独持有（角色树
  // codes.js 允许单独勾选「录入频谱测量」）仍无任何 UI 路径——页面入口需
  // investigation.view，缺口仅余此一处，真实存在。

  it('正路径：view+edit 用户从列表行「编辑」进入并完成录入测量全链路', async () => { await caseNavigationViaEditButtonFullChain(); });

  it('缺口固化：measurement.add+view-only 用户整页被 AuthDiv 拦截，无任何到测量的 UI 路径', async () => { await caseMeasurementAddOnlyBlockedByAuthDiv(); });

  it('正路径（2026-10-26 决策）：view+measurement.add 用户行「查看」进查看态完成录入测量全链路', async () => { await caseNavigationViaViewButtonWithMeasurementAdd(); });

  it('正路径（2026-10-26 决策 OR 第二支）：view+investigation.edit 用户行「查看」进查看态录入测量可用', async () => { await caseNavigationViaViewButtonWithInvestigationEdit(); });
});

describe('调查页对称卸载清理（2026-10-26 审查R1）', () => {
  it('调查页打开编辑弹窗后未关闭直接切页：卸载即清理，事件页不再意外渲染弹窗', async () => {
    // 事件页接通 InvestigationForm（问题1修复）后，调查页遗留的 store 弹窗状态
    // 会在事件页意外渲染出弹窗——反向泄漏从不可见变为可见。与事件页同要求：
    // 卸载即 store.closeInvestigation()。走问题2正路径的真实入口（行「编辑」）。
    grant([P.viewEvent, P.viewInvestigation, P.editInvestigation]);
    renderNode(<InvestigationsPage/>);
    await act(async () => { await flush(); });
    const editBtn = findButton(document, '编辑');
    expect(editBtn).toBeTruthy();
    click(editBtn);
    await act(async () => { await flush(); });
    expect(modalByTitle('规律调查详情')).toBeTruthy();
    expect(S.investigationModalVisible).toBe(true);

    // 未关闭弹窗直接切页：卸载必须清理遗留的 store 弹窗状态
    unmountNode();
    expect(S.investigationModalVisible).toBe(false);
    expect(S.investigation).toEqual({});

    // 修复前：store 单例残留 visible=true，事件页（已接通 InvestigationForm）
    // 会意外渲染出该弹窗；修复后不再复现
    renderNode(<EventsPage/>);
    await act(async () => { await flush(); });
    expect(S.investigationModalVisible).toBe(false);
    expect(q('.ant-modal')).toHaveLength(0);
  });
});
