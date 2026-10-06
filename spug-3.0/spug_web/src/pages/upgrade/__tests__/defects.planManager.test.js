/**
 * 缺陷复现测试（2026-10-04 审计）：PlanManager/PlanForm/Workbench。
 *
 * P1  同一失败双重提示（违反"拦截器已提示的业务代码不得重复提示"）：
 *     - 方案详情/编辑加载失败：拦截器已弹真实错误，再弹"获取详情失败"；
 *     - 方案提交失败：拦截器已弹真实错误，再弹"操作失败"；
 *     - 工作台加载失败：拦截器已弹真实错误，再弹"加载数据失败"。
 *     期望：上述场景 message.error 只出现一次（拦截器那次）。
 * P2  删除方案无 .catch：store.deletePlan 拒绝时产生 unhandled rejection。
 *     期望：失败被吞掉（提示由拦截器负责），无 unhandled rejection。
 * P3  PlanForm handleOk 无 return 也无 catch：validateFields 拒绝时
 *     （与 WorkbenchForm 的内联箭头不同，antd 拿不到 promise）产生
 *     unhandled rejection。期望：校验拒绝被本地 catch 吸收。
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

jest.mock('libs/functools', () => ({
  ...jest.requireActual('libs/functools'),
  hasPermission: jest.fn(() => true),
}));

jest.mock('components', () => ({
  AttachmentManager: () => <div>附件管理器</div>,
  AuthDiv: ({children}) => <div>{children}</div>,
  Breadcrumb: ({children}) => <div>{children}</div>,
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

const {http} = require('libs');
const {message, ConfigProvider} = require('antd');
const zhCN = require('antd/lib/locale/zh_CN').default;
const store = require('../store').default;

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}

let container = null;
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function rejectWithInterceptorToast(reason) {
  return () => {
    message.error(reason);
    return Promise.reject(reason);
  };
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

function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
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
  store.plans = [];
  store.systems = [];
  store.filterOptions = {phases: []};
  store.record = {};
  store.recordSteps = [];
  store.statusLogs = [];
  store.attachmentCount = 0;
});

afterEach(async () => {
  await act(async () => {
    if (container) ReactDOM.unmountComponentAtNode(container);
  });
  if (container) document.body.removeChild(container);
  container = null;
});

function renderPlanManager(children) {
  const PlanManager = require('../plan/PlanManager').default;
  act(() => {
    ReactDOM.render(
      <ConfigProvider locale={zhCN}>{children || <PlanManager/>}</ConfigProvider>,
      container);
  });
}

function renderWorkbench(props) {
  const Workbench = require('../Workbench').default;
  act(() => {
    ReactDOM.render(
      <ConfigProvider locale={zhCN}><Workbench {...props}/></ConfigProvider>,
      container);
  });
}

describe('P1a：方案详情加载失败只提示一次', () => {
  it('拦截器提示后组件不再弹"获取详情失败"', async () => {
    const plans = [{id: 5, name: '标准升级方案', step_count: 2}];
    http.get.mockImplementation((url) => {
      if (url.includes('/plans/5/')) {
        return rejectWithInterceptorToast('请求失败: 404 Not Found')();
      }
      if (url.includes('/plans/')) return Promise.resolve(plans);
      return Promise.resolve([]);
    });
    renderPlanManager();
    await act(async () => { await flush(); });
    clickButtonByText('详情');
    await act(async () => { await flush(); await flush(); });

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(message.error).toHaveBeenCalledWith('请求失败: 404 Not Found');
  });
});

describe('P1b：方案提交失败只提示一次', () => {
  it('拦截器提示后组件不再弹"操作失败"，且无 unhandled rejection', async () => {
    const unhandled = [];
    const onUnhandled = (reason) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);

    http.get.mockResolvedValue([]);
    http.post.mockImplementation(rejectWithInterceptorToast('方案名称 [X] 已存在'));
    renderPlanManager();
    await act(async () => { await flush(); });

    clickButtonByText('新建方案');
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    setInputValue(modal.querySelector('input[placeholder="请输入方案名称"]'), 'X');
    // 至少一个步骤才能走到提交
    clickButtonByText('添加步骤', modal);
    setInputValue(modal.querySelector('input[placeholder="步骤标题"]'), '步骤一');

    clickButtonByText('确定', modal);
    await act(async () => { await flush(); await flush(); });
    process.removeListener('unhandledRejection', onUnhandled);

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(unhandled).toEqual([]);
  });
});

describe('P2：删除方案失败无 unhandled rejection', () => {
  it('Popconfirm 确认删除被拒绝时被吞掉，只提示一次', async () => {
    const unhandled = [];
    const onUnhandled = (reason) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);

    const plans = [{id: 7, name: '待删方案', step_count: 1}];
    http.get.mockImplementation((url) => {
      if (url.includes('/plans/')) return Promise.resolve(plans);
      return Promise.resolve([]);
    });
    http.delete.mockImplementation(rejectWithInterceptorToast('请求失败: 500'));
    renderPlanManager();
    await act(async () => { await flush(); });

    clickButtonByText('删除');
    await act(async () => { await flush(); });
    const popover = document.querySelector('.ant-popover');
    expect(popover).not.toBeNull();
    clickButtonByText('确定', popover);
    await act(async () => { await flush(); await flush(); });
    process.removeListener('unhandledRejection', onUnhandled);

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(unhandled).toEqual([]);
  });
});

describe('P3：PlanForm 校验拒绝被本地吸收', () => {
  it('方案名称为空点确定无 unhandled rejection，弹窗保持打开', async () => {
    const unhandled = [];
    const onUnhandled = (reason) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);

    http.get.mockResolvedValue([]);
    http.post.mockResolvedValue({});
    renderPlanManager();
    await act(async () => { await flush(); });

    clickButtonByText('新建方案');
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    clickButtonByText('确定', modal);
    await act(async () => { await flush(); await flush(); });
    process.removeListener('unhandledRejection', onUnhandled);

    expect(unhandled).toEqual([]);
    expect(document.querySelector('.ant-modal')).not.toBeNull();
    expect(http.post).not.toHaveBeenCalled();
  });
});

describe('P1c：工作台加载失败只提示一次', () => {
  it('fetchRecord 拒绝时拦截器提示一次，不再弹"加载数据失败"', async () => {
    // 注意 /attachments/、/status-logs/、/steps/ 先于 /records/1/ 匹配（URL 前缀包含关系）
    http.get.mockImplementation((url) => {
      if (url.includes('/attachments/')) return Promise.resolve([]);
      if (url.includes('/status-logs/')) return Promise.resolve([]);
      if (url.includes('/steps/')) return Promise.resolve({steps: [], stats: {}});
      if (url.includes('/records/1/')) {
        return rejectWithInterceptorToast('请求失败: 403 Forbidden')();
      }
      return Promise.resolve([]);
    });

    renderWorkbench({match: {params: {id: '1'}}});
    await act(async () => { await flush(); await flush(); });

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(message.error).toHaveBeenCalledWith('请求失败: 403 Forbidden');
  });
});
