/**
 * 升级中心（页签融合外壳）测试。
 *
 * 真实渲染组件（ReactDOM + jsdom + MemoryRouter，仓库惯例），mock libs，
 * 验证外壳职责，不重复覆盖两个页签页面的业务逻辑（各有独立测试）：
 * - 两个页签（升级表单/升级方案）同属 upgrade.upgrade.view 权限，
 *   默认打开"升级表单"；
 * - URL ?tab= 恢复页签；
 * - 页签切换只挂载当前页签页面，并把页签状态写入 URL；
 * - 外壳已挂载时响应 URL 变化：方案页"创建表单"携带
 *   ?tab=records&planId= 跳入表单页签，planId 由既有挂载逻辑消费
 *   （打开新建弹窗并拉取方案详情），随后清理一次性参数保留页签；
 * - 旧路径重定向组件替换到升级中心对应页签并保留其余参数。
 *
 * 注意：upgrade store 为模块级单例，每个用例后必须重置弹层与列表状态。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {MemoryRouter, useHistory} from 'react-router-dom';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();
const mockHistoryReplace = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {replace: mockHistoryReplace, push: jest.fn()},
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
  sessionStorage.setItem('nickname', 'admin');
  localStorage.clear();
  store = require('../store').default;
  store.records = [];
  store.total = 0;
  store.page = 1;
  store.plans = [];
  store.systems = [];
  store.viewMode = 'list';
  store.createVisible = false;
  store.presetPlanId = null;
  store.f_system = undefined;
  store.f_status = undefined;
  store.f_upgrade_type = undefined;
  store.f_start_date = undefined;
  store.f_end_date = undefined;
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  store = null;
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete, mockHistoryReplace]
    .forEach(fn => fn.mockReset());
  localStorage.clear();
  sessionStorage.removeItem('nickname');
  window.history.replaceState({}, '', '/');
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

// http.get 按 URL 分发；升级页签挂载时的各类列表请求都返回空数据
function mockListResponses() {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/api/upgrade/filter-options/')) {
      return Promise.resolve({
        systems: [], upgrade_types: [], statuses: [],
        phases: [], milestones: [], standard_flow: [],
      });
    }
    if (url.includes('/api/upgrade/candidate-systems/')) {
      return Promise.resolve([]);
    }
    if (url.endsWith('/api/upgrade/plans/9/')) {
      return Promise.resolve({id: 9, name: 'E2E方案', steps: []});
    }
    if (url.includes('/api/upgrade/plans/')) {
      return Promise.resolve([]);
    }
    return Promise.resolve({records: [], total: 0});
  });
}

function renderCenter(search) {
  const UpgradeCenter = require('../UpgradeCenter').default;
  ReactDOM.render(
    <MemoryRouter initialEntries={[`/upgrade${search || ''}`]}>
      <UpgradeCenter/>
    </MemoryRouter>,
    container);
}

// 挂载在 Router 内的跳转探针：测试外部导航触发外壳同步
let navProbe = null;
function NavProbe() {
  navProbe = useHistory();
  return null;
}

function renderCenterWithProbe(search) {
  const UpgradeCenter = require('../UpgradeCenter').default;
  ReactDOM.render(
    <MemoryRouter initialEntries={[`/upgrade${search || ''}`]}>
      <NavProbe/>
      <UpgradeCenter/>
    </MemoryRouter>,
    container);
}

function activeTabLabel() {
  const node = container.querySelector('.ant-tabs-tab-active');
  return node ? node.textContent : '';
}

function tabNode(label) {
  return Array.from(container.querySelectorAll('.ant-tabs-tab'))
    .find(node => node.textContent === label);
}

describe('升级中心页签外壳', () => {
  beforeEach(() => {
    mockListResponses();
  });

  it('显示两个页签，默认打开升级表单；外壳面包屑唯一（表单页 embedded 隐藏自身面包屑）', async () => {
    await act(async () => {
      renderCenter('');
      await flush();
    });
    const labels = Array.from(container.querySelectorAll('.ant-tabs-tab'))
      .map(node => node.textContent);
    expect(labels).toEqual(['升级表单', '升级方案']);
    expect(activeTabLabel()).toBe('升级表单');
    // 升级表单页真实挂载：筛选选项与记录列表请求均发出
    const called = mockHttpGet.mock.calls.map(c => c[0]);
    expect(called.some(u => u.includes('/api/upgrade/filter-options/'))).toBe(true);
    expect(called.some(u => u.includes('/api/upgrade/records/'))).toBe(true);
    // 仅外壳渲染一份面包屑
    expect(container.querySelectorAll('.ant-breadcrumb').length).toBe(1);
  });

  it('URL ?tab=plans 打开升级方案页签并真实挂载方案列表', async () => {
    await act(async () => {
      renderCenter('?tab=plans');
      await flush();
    });
    expect(activeTabLabel()).toBe('升级方案');
    const called = mockHttpGet.mock.calls.map(c => c[0]);
    expect(called.some(u => u.endsWith('/api/upgrade/plans/'))).toBe(true);
    expect(container.textContent).toContain('升级方案管理');
  });

  it('页签切换只挂载当前页签页面，并把页签状态写入 URL', async () => {
    await act(async () => {
      renderCenter('');
      await flush();
    });
    expect(activeTabLabel()).toBe('升级表单');

    await act(async () => {
      tabNode('升级方案').click();
      await flush();
    });
    expect(activeTabLabel()).toBe('升级方案');
    expect(container.textContent).toContain('升级方案管理');
    // 升级表单页搜索区（"计划升级时间"筛选）已随页签卸载
    expect(container.textContent).not.toContain('计划升级时间');
    // 页签状态写入 URL
    expect(mockHistoryReplace).toHaveBeenCalledWith('/upgrade?tab=plans');

    await act(async () => {
      tabNode('升级表单').click();
      await flush();
    });
    expect(activeTabLabel()).toBe('升级表单');
    expect(container.textContent).toContain('计划升级时间');
    expect(mockHistoryReplace).toHaveBeenCalledWith('/upgrade?tab=records');
    // 切回后升级表单页重新挂载并请求列表
    const called = mockHttpGet.mock.calls.map(c => c[0]);
    expect(called.filter(u => u.includes('/api/upgrade/records/')).length).toBe(2);
  });

  it('外壳挂载时响应 URL 变化：方案跳转 ?tab=records&planId= 切入表单页签并消费 planId', async () => {
    await act(async () => {
      renderCenterWithProbe('?tab=plans');
      await flush();
    });
    expect(activeTabLabel()).toBe('升级方案');

    // 模拟方案页"创建表单"跳转：Router 导航 + 真实地址栏同步（表单页读取
    // window.location.search 消费 planId）
    await act(async () => {
      window.history.replaceState({}, '', '/upgrade?tab=records&planId=9');
      navProbe.push('/upgrade?tab=records&planId=9');
      await flush();
    });

    expect(activeTabLabel()).toBe('升级表单');
    // 方案详情经既有挂载逻辑请求（新建弹窗预填）
    const called = mockHttpGet.mock.calls.map(c => c[0]);
    expect(called.some(u => u.endsWith('/api/upgrade/plans/9/'))).toBe(true);
    expect(store.createVisible).toBe(true);
    expect(store.presetPlanId).toBe('9');
    // 一次性 planId 已清理、页签状态保留
    expect(mockHistoryReplace).toHaveBeenCalledWith('/upgrade?tab=records');
  });
});

describe('旧升级方案路径重定向', () => {
  beforeEach(() => {
    mockListResponses();
  });

  it('跳到升级中心方案页签并保留其余参数', async () => {
    const {UpgradeCenterRedirect} = require('../UpgradeCenter');
    await act(async () => {
      ReactDOM.render(
        <UpgradeCenterRedirect tab="plans" location={{search: '?foo=1'}}/>,
        container);
      await flush();
    });
    expect(mockHistoryReplace).toHaveBeenCalledWith('/upgrade?foo=1&tab=plans');
  });

  it('无附加参数时跳到对应页签', async () => {
    const {UpgradeCenterRedirect} = require('../UpgradeCenter');
    await act(async () => {
      ReactDOM.render(
        <UpgradeCenterRedirect tab="plans" location={{search: ''}}/>,
        container);
      await flush();
    });
    expect(mockHistoryReplace).toHaveBeenCalledWith('/upgrade?tab=plans');
  });
});
