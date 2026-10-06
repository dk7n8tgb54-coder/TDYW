/**
 * 缺陷复现测试（2026-10-04 审计）：WorkbenchForm 工作台交互。
 *
 * W1  添加步骤弹窗提交失败仍关闭并清空表单（乐观更新回归）：
 *     期望 POST 失败时弹窗保持打开、用户输入保留（成功提示等待真实结果）。
 * W2  空必填项点确定产生 unhandled rejection：antd 普通 Modal（区别于
 *     Modal.confirm 内部的 ActionButton）不处理 onOk 返回的 promise 拒绝。
 *     期望校验拒绝被本地 catch 吸收。
 * W3  前端权限门用错码：应用方案/添加步骤按钮用 upgrade.upgrade.edit 门控，
 *     后端要求 upgrade.upgrade.add。期望：仅有 edit 权限时不可见。
 * W4  删除状态日志后重取记录冲掉"编辑基本信息"未保存草稿：
 *     期望同一条记录的重取不回灌已触碰（touched）的表单。
 *
 * jsdom 约定：ConfigProvider zh_CN（否则 Modal/Popconfirm 按钮为英文 OK）；
 * antd Modal 关闭后 DOM 在 jsdom 滞留（rc-dialog 动画事件不触发），
 * "弹窗已关"以表单被 reset（输入值清空）为行为信号而非 DOM 查询。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => new Promise(() => {})),
    post: jest.fn(() => Promise.resolve({})),
    put: jest.fn(() => Promise.resolve({})),
    delete: jest.fn(() => Promise.resolve({})),
  },
  hasPermission: jest.fn(() => true),
}));

jest.mock('components', () => ({
  AttachmentManager: () => <div>附件管理器</div>,
}));

jest.mock('antd', () => ({
  ...jest.requireActual('antd'),
  message: {
    success: jest.fn(),
    error: jest.fn(),
    warning: jest.fn(),
    info: jest.fn(),
    confirm: jest.fn(),
  },
}));

const {http, hasPermission} = require('libs');
const {message, ConfigProvider} = require('antd');
const zhCN = require('antd/lib/locale/zh_CN').default;
const store = require('../store').default;
const {deleteStatusLog} = require('../workbenchActions');

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}

let container = null;
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const RECORD = {
  id: 1, upgrade_no: 'SJ20261001-0007', title: 'DVOR 软件升级',
  system_name: 'DVOR系统', system_id: 3, upgrade_type: '功能升级',
  upgrade_time: '2026-10-01 10:00:00', status: '处理中', owner: '张三',
};

// 注意：/status-logs/ 与 /steps/ 必须先于 /records/1/ 匹配
//（其 URL 本身包含 /records/1/ 前缀）
function mockHttp({recordResponse} = {}) {
  http.get.mockImplementation((url) => {
    if (url.includes('/status-logs/')) return Promise.resolve([]);
    if (url.includes('/steps/')) return Promise.resolve({steps: [], stats: {}});
    if (url.includes('/records/1/') && recordResponse) {
      return Promise.resolve(recordResponse);
    }
    return Promise.resolve({});
  });
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  // 显式恢复默认实现，避免上一用例的 mockImplementation 泄漏
  http.get.mockImplementation(() => new Promise(() => {}));
  http.post.mockImplementation(() => Promise.resolve({}));
  http.put.mockImplementation(() => Promise.resolve({}));
  http.delete.mockImplementation(() => Promise.resolve({}));
  store.record = {...RECORD};
  store.recordSteps = [];
  store.recordStepStats = {};
  store.statusLogs = [];
  store.plans = [];
  store.systems = [];
  store.filterOptions = {phases: []};
  store.attachmentCount = 0;
  hasPermission.mockReturnValue(true);
  mockHttp();
});

afterEach(async () => {
  await act(async () => {
    ReactDOM.unmountComponentAtNode(container);
  });
  document.body.removeChild(container);
  container = null;
});

function renderForm(props = {isNew: false, recordId: '1'}) {
  const WorkbenchForm = require('../WorkbenchForm').default;
  act(() => {
    ReactDOM.render(
      <ConfigProvider locale={zhCN}><WorkbenchForm {...props}/></ConfigProvider>,
      container);
  });
}

function clickButtonByText(text, root = document.body) {
  const btn = Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s/g, '') === text);
  if (!btn) throw new Error(`button not found: ${text}`);
  act(() => {
    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
  });
  return btn;
}

function openAddStepModal() {
  clickButtonByText('添加步骤');
  const modal = document.querySelector('.ant-modal');
  expect(modal).not.toBeNull();
  return modal;
}

function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

describe('W1：添加步骤提交失败不关闭弹窗', () => {
  it('POST 失败时弹窗保持打开且输入保留，只提示一次', async () => {
    renderForm();
    openAddStepModal();
    const input = document.querySelector('.ant-modal input[placeholder="请输入步骤标题"]');
    setInputValue(input, '校验回退步骤');

    // 模拟 http 拦截器：真实错误提示一次后 reject
    http.post.mockImplementation(() => {
      message.error('请求失败: 403 Forbidden');
      return Promise.reject('请求失败: 403 Forbidden');
    });

    clickButtonByText('确定', document.querySelector('.ant-modal'));
    await act(async () => {
      await flush();
      await flush();
    });

    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/steps/add/', expect.anything());
    // 弹窗保持打开：输入未被 reset、无成功提示
    expect(document.querySelector('.ant-modal input[placeholder="请输入步骤标题"]').value)
      .toBe('校验回退步骤');
    expect(message.error).toHaveBeenCalledTimes(1);
    expect(message.success).not.toHaveBeenCalled();
  });

  it('POST 成功后关闭弹窗并清空输入', async () => {
    renderForm();
    openAddStepModal();
    const input = document.querySelector('.ant-modal input[placeholder="请输入步骤标题"]');
    setInputValue(input, '正常步骤');

    clickButtonByText('确定', document.querySelector('.ant-modal'));
    await act(async () => {
      await flush();
      await flush();
    });

    expect(message.success).toHaveBeenCalledWith('步骤添加成功');
    // 关闭行为信号：resetFields 清空输入（DOM 在 jsdom 滞留不可靠）
    expect(document.querySelector('.ant-modal input[placeholder="请输入步骤标题"]').value)
      .toBe('');
  });
});

describe('W2：空必填项点确定无 unhandled rejection', () => {
  it('校验拒绝由 antd Modal 吸收，弹窗保持打开', async () => {
    const unhandled = [];
    const onUnhandled = (reason) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);

    renderForm();
    openAddStepModal();
    clickButtonByText('确定', document.querySelector('.ant-modal'));
    await act(async () => {
      await flush();
      await flush();
    });
    process.removeListener('unhandledRejection', onUnhandled);

    expect(unhandled).toEqual([]);
    expect(message.success).not.toHaveBeenCalled();
    expect(http.post).not.toHaveBeenCalled();
  });
});

describe('W3：应用方案/添加步骤受 upgrade.upgrade.add 门控', () => {
  it('仅有 edit 权限时不可见应用方案与添加步骤', () => {
    store.plans = [{id: 5, name: '标准升级方案', step_count: 2}];
    hasPermission.mockImplementation(
      (code) => code !== 'upgrade.upgrade.add');
    renderForm();
    expect(container.textContent).not.toContain('添加步骤');
    expect(container.textContent).not.toContain('应用方案');
  });

  it('具备 add 权限时功能可见（防过度收敛）', () => {
    store.plans = [{id: 5, name: '标准升级方案', step_count: 2}];
    renderForm();
    expect(container.textContent).toContain('添加步骤');
    expect(container.textContent).toContain('应用方案');
  });
});

describe('W4：删除状态日志不冲掉未保存草稿', () => {
  it('同记录重取后编辑面板中已触碰字段保留用户输入', async () => {
    renderForm();
    await act(async () => { await flush(); });

    // 展开编辑基本信息折叠面板
    const header = document.querySelector('.ant-collapse-header');
    expect(header).not.toBeNull();
    act(() => {
      header.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    });

    const input = document.querySelector('input[placeholder="标题"]');
    expect(input.value).toBe('DVOR 软件升级');
    setInputValue(input, '用户手改的标题');

    // 删除一条状态日志 → 后端重算主表状态 → 动作层重取当前记录
    http.delete.mockImplementation(() => Promise.resolve({}));
    const serverRecord = {...RECORD, title: '服务器端标题', status: '已完成'};
    http.get.mockImplementation((url) => {
      if (url.includes('/status-logs/')) return Promise.resolve([]);
      if (url.includes('/steps/')) return Promise.resolve({steps: [], stats: {}});
      if (url.includes('/records/1/')) return Promise.resolve(serverRecord);
      return Promise.resolve({});
    });

    await act(async () => {
      deleteStatusLog('1', 99);
      await flush();
      await flush();
      await flush();
    });

    const inputAfter = document.querySelector('input[placeholder="标题"]');
    expect(inputAfter).not.toBeNull();
    expect(inputAfter.value).toBe('用户手改的标题');
  });
});
