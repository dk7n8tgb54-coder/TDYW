/**
 * 规律调查生命周期动作化回归测试（2026-10-26）。
 *
 * 后端契约（后端已落地，前端对齐）：调查状态三态 investigating/ended/cancelled；
 * 新端点 POST /investigations/<pk>/finish/（{result, conclusion, end_at?}）与
 * POST /investigations/<pk>/cancel/（{cancel_reason}）；通用创建/编辑拒绝携带
 * status/result/cancel_reason 键。前端退役「列表内联状态下拉 PATCH」与表单
 * 「调查状态下拉」，改为列表行「结束调查/取消调查」动作弹窗 + 详情概览只读展示。
 *
 * 真实渲染 InvestigationsPage / InvestigationForm（ReactDOM + jsdom），mock
 * libs.http，驱动真实 store 单例（MobX）；权限注入走项目真实机制
 * （sessionStorage → updatePermissions → Permission 对象），AuthButton/Action
 * 与页面内 hasPermission 消费同一份真实权限对象，杜绝 mock 恒真。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import moment from 'moment';
import {message} from 'antd';

const mockGet = jest.fn();
const mockPost = jest.fn();

jest.mock('libs', () => ({
  ...jest.requireActual('../../../libs/functools'),
  http: {get: mockGet, post: mockPost, put: jest.fn(), patch: jest.fn(), delete: jest.fn()},
}));
// tableFieldsStore 直接导入真实 http（axios 实例），TableCard 渲染会触发它，
// jsdom 内单独替换（同 permissionMatrix.test.js）
jest.mock('../../../libs/http', () => ({get: jest.fn().mockResolvedValue({})}));

const InvestigationsPage = require('../investigations').default;
const InvestigationForm = require('../InvestigationForm').default;
const store = require('../store').default;
const {updatePermissions} = require('libs');

if (!window.matchMedia) {
  window.matchMedia = query => ({matches: false, media: query, addListener() {}, removeListener() {}});
}

const LIST_URL = '/api/interference/investigations/';
const ROW_INVESTIGATING = {
  id: 7, name: '调查甲', status: 'investigating', status_text: '调查中', event_count: 1,
};
const ROW_ENDED = {
  id: 8, name: '调查乙', status: 'ended', status_text: '已结束', event_count: 0,
  result: 'found', result_text: '发现规律',
};
const ROW_CANCELLED = {
  id: 9, name: '调查丙', status: 'cancelled', status_text: '已取消', event_count: 0,
  cancel_reason: '与另一调查重复',
};
const ROWS = [ROW_INVESTIGATING, ROW_ENDED, ROW_CANCELLED];

function grant(permissions) {
  sessionStorage.setItem('token', 'lifecycle-test-token');
  sessionStorage.setItem('is_supper', 'false');
  sessionStorage.setItem('permissions', JSON.stringify(permissions));
  updatePermissions();
}

let container = null;

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function renderNode(element) {
  container = document.createElement('div');
  document.body.appendChild(container);
  return act(async () => {
    ReactDOM.render(element, container);
    await flush();
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

function rowByName(name) {
  return q('.ant-table-tbody .ant-table-row').find(row => row.textContent.indexOf(name) >= 0);
}

function modalByTitle(title) {
  return q('.ant-modal').find(m => {
    const t = m.querySelector('.ant-modal-title');
    return !!t && t.textContent === title;
  });
}

/** 搜索区状态下拉（排除表格内可能残留的任何 Select） */
function searchStatusSelect() {
  return q('.ant-select').find(node => !node.closest('.ant-table-tbody'));
}

async function expandSelect(select) {
  expect(select).toBeTruthy();
  await act(async () => {
    select.querySelector('.ant-select-selector').dispatchEvent(
      new MouseEvent('mousedown', {bubbles: true}));
    await flush();
  });
  return q('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option');
}

function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

function listCalls() {
  return mockGet.mock.calls.filter(call => call[0] === LIST_URL);
}

/** 以编辑态直接渲染 InvestigationForm（详情引用与 store 现值恒等，防 effect 自激励） */
async function openFormWith(detail) {
  store.investigation = detail;
  store.investigationModalVisible = true;
  await renderNode(<InvestigationForm/>);
  return modalByTitle(detail.id ? '规律调查详情' : '新建规律调查');
}

function resetStore() {
  store.investigations = [];
  store.investigation = {};
  store.investigationModalVisible = false;
  store.investigationPage = 1;
  store.investigationPageSize = 20;
  store.investigationTotal = 0;
  store.investigationName = '';
  store.investigationStatus = undefined;
  store.investigationsLoading = false;
}

let messageSuccessSpy;

beforeEach(() => {
  jest.clearAllMocks();
  mockGet.mockImplementation(url => {
    if (url === LIST_URL) {
      return Promise.resolve({records: ROWS.map(row => ({...row})), total: 3, page: 1, page_size: 20});
    }
    if (/^\/api\/interference\/investigations\/\d+\/$/.test(url)) {
      // 详情响应与 store 现值引用恒等（同 permissionMatrix.test.js 手法），
      // 从构造上杜绝 InvestigationForm 详情 effect 自激励
      const detailId = Number(url.match(/\d+/)[0]);
      if (store.investigation && store.investigation.id === detailId) {
        return Promise.resolve(store.investigation);
      }
      const row = ROWS.find(item => item.id === detailId);
      return Promise.resolve(row ? {...row, events: [], measurements: []} : {});
    }
    return Promise.resolve({records: [], total: 0});
  });
  mockPost.mockResolvedValue({});
  resetStore();
  messageSuccessSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
});

afterEach(async () => {
  unmountNode();
  // antd 弹窗/面板关闭动画的卸载定时器若提前摘除节点，会在下一个用例的
  // 时间窗内抛 jsdom NotFoundError；先等它完成再清理（同既有套件）
  await wait(400);
  document.querySelectorAll(
    '.ant-modal-root, .ant-modal-confirm, .ant-select-dropdown, .ant-picker-dropdown',
  ).forEach(n => n.remove());
  resetStore();
  messageSuccessSpy.mockRestore();
});

test('列表状态列三态文本渲染，不再出现内联状态下拉', async () => {
  grant(['interference.investigation.view', 'interference.investigation.edit']);
  await renderNode(<InvestigationsPage/>);
  const tbody = document.querySelector('.ant-table-tbody');
  expect(tbody.textContent).toContain('调查中');
  expect(tbody.textContent).toContain('已结束');
  expect(tbody.textContent).toContain('已取消');
  // 修复前：edit 权限时状态列渲染内联 Select 直接 PATCH {status}
  expect(tbody.querySelector('.ant-select')).toBeNull();
  // 搜索区状态筛选随三值收缩（旧六值草稿/持续观察/测量中/已形成结论退役）
  const options = await expandSelect(searchStatusSelect());
  expect(options.map(option => option.textContent))
    .toEqual(['调查中', '已结束', '已取消']);
});

test('编辑权限：investigating 行出现结束/取消调查按钮，结束弹窗必填校验且成功后重拉列表', async () => {
  grant(['interference.investigation.view', 'interference.investigation.edit']);
  await renderNode(<InvestigationsPage/>);
  const row = rowByName('调查甲');
  expect(row).toBeTruthy();
  const finishBtn = findButton(row, '结束调查');
  const cancelBtn = findButton(row, '取消调查');
  expect(finishBtn).toBeTruthy();
  expect(cancelBtn).toBeTruthy();

  click(finishBtn);
  await act(async () => { await flush(); });
  const modal = modalByTitle('结束调查');
  expect(modal).toBeTruthy();

  // 不填直接提交：必填校验出现且不发请求
  const okBtn = modal.querySelector('.ant-modal-footer .ant-btn-primary');
  expect(okBtn).toBeTruthy();
  click(okBtn);
  await act(async () => { await flush(); await flush(); });
  expect(document.body.textContent).toContain('请选择调查结果');
  expect(document.body.textContent).toContain('请填写调查结论');
  expect(mockPost).not.toHaveBeenCalled();

  // 填 result + conclusion（end_at 缺省当前时间）后提交
  const radio = modal.querySelector('input[type="radio"][value="found"]');
  expect(radio).toBeTruthy();
  await act(async () => { radio.click(); await flush(); });
  const conclusion = modal.querySelector('textarea#conclusion');
  expect(conclusion).toBeTruthy();
  setInputValue(conclusion, '定位到可疑信号源，建议持续监测');
  click(okBtn);
  await act(async () => { await flush(); await flush(); });

  const finishPosts = mockPost.mock.calls.filter(
    call => call[0] === '/api/interference/investigations/7/finish/');
  expect(finishPosts).toHaveLength(1);
  expect(finishPosts[0][1].result).toBe('found');
  expect(finishPosts[0][1].conclusion).toBe('定位到可疑信号源，建议持续监测');
  expect(finishPosts[0][1].end_at).toEqual(expect.stringContaining(String(moment().year())));
  expect(messageSuccessSpy).toHaveBeenCalledWith('调查已结束');
  // 成功后列表重拉
  expect(listCalls().length).toBeGreaterThanOrEqual(2);
  // 弹窗关闭（destroyOnClose：关闭动画结束后表单内容销毁）
  await act(async () => { await wait(400); });
  expect(document.querySelector('textarea#conclusion')).toBeNull();
});

test('ended/cancelled 行不显示结束/取消调查按钮', async () => {
  grant(['interference.investigation.view', 'interference.investigation.edit']);
  await renderNode(<InvestigationsPage/>);
  const endedRow = rowByName('调查乙');
  expect(endedRow).toBeTruthy();
  expect(endedRow.textContent).toContain('已结束');
  expect(findButton(endedRow, '结束调查')).toBeUndefined();
  expect(findButton(endedRow, '取消调查')).toBeUndefined();
  const cancelledRow = rowByName('调查丙');
  expect(cancelledRow).toBeTruthy();
  expect(cancelledRow.textContent).toContain('已取消');
  expect(findButton(cancelledRow, '结束调查')).toBeUndefined();
  expect(findButton(cancelledRow, '取消调查')).toBeUndefined();
});

test('仅查看权限：无结束/取消调查按钮（Action auth 生效）', async () => {
  grant(['interference.investigation.view']);
  await renderNode(<InvestigationsPage/>);
  expect(findButton(document, '结束调查')).toBeUndefined();
  expect(findButton(document, '取消调查')).toBeUndefined();
  expect(mockPost).not.toHaveBeenCalled();
});

test('取消调查弹窗：必填原因校验，填写后 POST cancel 携带 cancel_reason', async () => {
  grant(['interference.investigation.view', 'interference.investigation.edit']);
  await renderNode(<InvestigationsPage/>);
  const cancelBtn = findButton(rowByName('调查甲'), '取消调查');
  expect(cancelBtn).toBeTruthy();
  click(cancelBtn);
  await act(async () => { await flush(); });
  const modal = modalByTitle('取消调查');
  expect(modal).toBeTruthy();

  const okBtn = modal.querySelector('.ant-modal-footer .ant-btn-primary');
  click(okBtn);
  await act(async () => { await flush(); await flush(); });
  expect(document.body.textContent).toContain('请填写取消原因');
  expect(mockPost).not.toHaveBeenCalled();

  const reason = modal.querySelector('textarea#cancel_reason');
  expect(reason).toBeTruthy();
  setInputValue(reason, '与另一调查重复，合并处理');
  click(okBtn);
  await act(async () => { await flush(); await flush(); });

  const cancelPosts = mockPost.mock.calls.filter(
    call => call[0] === '/api/interference/investigations/7/cancel/');
  expect(cancelPosts).toHaveLength(1);
  expect(cancelPosts[0][1].cancel_reason).toBe('与另一调查重复，合并处理');
  expect(messageSuccessSpy).toHaveBeenCalledWith('调查已取消');
  expect(listCalls().length).toBeGreaterThanOrEqual(2);
});

test('结束失败（http reject）：不显示成功提示、列表不重拉、弹窗保持打开', async () => {
  grant(['interference.investigation.view', 'interference.investigation.edit']);
  mockPost.mockRejectedValue(new Error('只有调查中的调查可以结束'));
  await renderNode(<InvestigationsPage/>);
  const callsBefore = listCalls().length;
  click(findButton(rowByName('调查甲'), '结束调查'));
  await act(async () => { await flush(); });
  const modal = modalByTitle('结束调查');
  expect(modal).toBeTruthy();
  const radio = modal.querySelector('input[type="radio"][value="not_found"]');
  await act(async () => { radio.click(); await flush(); });
  setInputValue(modal.querySelector('textarea#conclusion'), '暂无法确认结论');
  click(modal.querySelector('.ant-modal-footer .ant-btn-primary'));
  await act(async () => { await flush(); await flush(); });

  expect(mockPost).toHaveBeenCalledTimes(1);
  expect(messageSuccessSpy).not.toHaveBeenCalled();
  // 失败不乐观更新：列表不重拉
  expect(listCalls().length).toBe(callsBefore);
  // 弹窗保持打开，便于修正后重试
  expect(modalByTitle('结束调查')).toBeTruthy();
});

test('编辑表单退役「调查状态」下拉，概览页签只读展示状态与调查结果', async () => {
  grant(['interference.investigation.view', 'interference.investigation.edit']);
  const modal = await openFormWith({...ROW_ENDED, events: [], measurements: []});
  expect(modal).toBeTruthy();
  // 修复前：表单「调查状态」下拉随 PUT 提交 status 键（后端已拒绝）；
  // 表单内其余字段均为 Input/DatePicker/TextArea，无任何 Select
  expect(modal.querySelector('.ant-select')).toBeNull();
  expect(document.body.textContent).toContain('调查状态：已结束');
  expect(document.body.textContent).toContain('调查结果：发现规律');
  // 非 cancelled 不显示取消原因
  expect(document.body.textContent).not.toContain('取消原因');
});

test('已取消调查概览展示取消原因，未填写调查结果显示 -', async () => {
  grant(['interference.investigation.view']);
  const modal = await openFormWith({...ROW_CANCELLED, events: [], measurements: []});
  expect(modal).toBeTruthy();
  expect(document.body.textContent).toContain('调查状态：已取消');
  expect(document.body.textContent).toContain('取消原因：与另一调查重复');
  expect(document.body.textContent).toContain('调查结果：-');
});
