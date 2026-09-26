/**
 * 完成工单链路测试（单账号协同流程：执行中 → 已完成，无派发/接单/复核环节）。
 *
 * 真实渲染 WorkOrderDetail（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 执行中显示"完成工单"按钮，点击后弹窗真实打开
 * - 处理结果必填：空提交被前端校验拦截，不发起请求
 * - 提交调用新的 /complete/ 端点并携带处理结果/工时/系统中断时间
 * - 完成成功后详情刷新为后端返回的"已完成"，并出现"关闭工单"
 * - 无执行权限时不显示"完成工单"按钮（后端仍独立校验，前端只是入口控制）
 * - 状态筛选选项不再包含待派发/待接单/待复核（历史兼容状态不作为新流程选项）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

const mockPermState = {isSuper: true, granted: true};

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => mockPermState.granted),
  Permission: {get isSuper() {return mockPermState.isSuper;}},
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

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  mockPermState.isSuper = true;
  mockPermState.granted = true;
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {});
}

function findButtonByText(text) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => btn.textContent.replace(/\s+/g, '') === text);
}

function setTextareaValue(textarea, value) {
  // React 17 受控输入：需借用原生 value setter 触发 onChange
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(textarea, value);
  textarea.dispatchEvent(new Event('input', {bubbles: true}));
}

const EXECUTING_DETAIL = {
  id: 5,
  work_no: 'WO20260926-0001',
  title: '主用链路抢修',
  work_type: 'repair',
  priority: 'high',
  status: 'executing',
  status_text: '执行中',
  source_type: 'fault',
  source_no: 'GZ20260926-0001',
  source_fault: 33,
  system: 7,
  system_name: '烟台通信系统',
  system_code: 'SYS-A1',
  system_location: '机房A',
  affects_system_operation: true,
  participants: [],
  process_result: '',
};

const COMPLETED_DETAIL = {
  ...EXECUTING_DETAIL,
  status: 'completed',
  status_text: '已完成',
  process_result: '已更换光模块，链路恢复',
  completed_by_name: 'wo_admin',
  completed_at: '2026-09-26 10:00',
  actual_end: '2026-09-26 10:00',
};

function mockHttpDefaults() {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/work-orders/5/handling-records/')) {
      return Promise.resolve({data: [], total: 0});
    }
    return Promise.resolve(EXECUTING_DETAIL);
  });
}

async function renderDetail() {
  const WorkOrderDetail = require('../WorkOrderDetail').default;
  mockHttpDefaults();
  await act(async () => {
    ReactDOM.render(<WorkOrderDetail woId={5} visible onClose={() => {}}/>, container);
  });
  await act(flush);
  await act(flush);
}

describe('完成工单链路', () => {
  test('执行中点击"完成工单"后弹窗打开，空处理结果被校验拦截不发起请求', async () => {
    await renderDetail();
    const completeBtn = findButtonByText('完成工单');
    expect(completeBtn).toBeTruthy();
    await click(completeBtn);
    const modalTitle = document.querySelector('.ant-modal-title');
    expect(modalTitle).not.toBeNull();
    expect(modalTitle.textContent).toContain('完成工单');

    // 处理结果必填：直接点确定 → 前端校验拦截，不发起 POST
    await click(document.querySelector('.ant-modal-footer .ant-btn-primary'));
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  test('提交调用 /complete/ 端点携带处理结果，成功后详情刷新并显示关闭工单', async () => {
    await renderDetail();
    await click(findButtonByText('完成工单'));
    const modalBody = document.querySelector('.ant-modal-body');
    const textarea = modalBody.querySelector('textarea');
    expect(textarea).not.toBeNull();
    await act(async () => {
      setTextareaValue(textarea, '已更换光模块，链路恢复');
    });
    mockHttpPost.mockResolvedValue(COMPLETED_DETAIL);
    await click(document.querySelector('.ant-modal-footer .ant-btn-primary'));

    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/complete/',
      {process_result: '已更换光模块，链路恢复', work_hours: null, interrupt_hours: null});
    await act(flush);
    await act(flush);
    // 详情刷新为后端返回：状态已完成，出现关闭工单入口，完成工单按钮消失
    const flat = document.body.textContent.replace(/\s+/g, '');
    expect(flat).toContain('已完成');
    expect(flat).toContain('关闭工单');
    expect(findButtonByText('完成工单')).toBeFalsy();
    expect(findButtonByText('关闭工单')).toBeTruthy();
    // 完成账号与完成时间展示
    expect(flat).toContain('完成账号');
    expect(flat).toContain('完成时间');
  });

  test('无执行权限时不显示完成工单按钮', async () => {
    mockPermState.isSuper = false;
    mockPermState.granted = false;
    await renderDetail();
    expect(findButtonByText('完成工单')).toBeFalsy();
  });

  test('状态筛选选项不含待派发/待接单/待复核，文本映射仍兼容历史状态', () => {
    const {WO_STATUS_OPTIONS, WO_STATUS_TEXT} = require('../constants');
    const values = WO_STATUS_OPTIONS.map(item => item.value);
    expect(values).toEqual(['executing', 'completed', 'closed', 'cancelled']);
    expect(values).not.toContain('pending_dispatch');
    expect(values).not.toContain('pending_accept');
    expect(values).not.toContain('pending_review');
    // 历史数据展示兼容：旧状态仍有文本映射，不崩溃
    expect(WO_STATUS_TEXT.pending_dispatch).toBeTruthy();
    expect(WO_STATUS_TEXT.pending_accept).toBeTruthy();
    expect(WO_STATUS_TEXT.pending_review).toBeTruthy();
  });
});
