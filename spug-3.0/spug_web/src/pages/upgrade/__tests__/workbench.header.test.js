/**
 * 升级工作台顶栏行为测试（2026-10-15 体验改造）：
 * - 新建模式：保留"保存 / 保存并进入工作台"两个入口（新建流程行为不变）；
 * - 查看/编辑模式：不再渲染全局"保存"按钮（编辑走信息栏内编辑面板），
 *   顶栏不再重复展示完整标题（标题只在信息栏出现一次）；
 * - 面包屑最后一级不再携带记录标题。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => Promise.resolve({})),
    post: jest.fn(() => Promise.resolve({})),
    put: jest.fn(() => Promise.resolve({})),
    delete: jest.fn(() => Promise.resolve({})),
  },
  hasPermission: jest.fn(() => true),
}));

// Workbench.js 从 libs/functools 导入 hasPermission（与 'libs' 是两个模块）
jest.mock('libs/functools', () => ({
  hasPermission: jest.fn(() => true),
}));

jest.mock('libs/history', () => ({
  __esModule: true,
  default: {push: jest.fn(), replace: jest.fn()},
}));

jest.mock('components', () => {
  const React = require('react');
  return {
    Breadcrumb: Object.assign(
      ({children}) => <div className="test-breadcrumb">{children}</div>,
      {Item: ({children}) => <span>{children}</span>},
    ),
    AttachmentManager: () => <div>附件管理器</div>,
  };
});

const {http, hasPermission} = require('libs');
const {hasPermission: hasPermissionFn} = require('libs/functools');
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

const RECORD = {
  id: 1, upgrade_no: 'SJ20261001-0007', title: 'DVOR 软件升级',
  system_name: 'DVOR系统', system_id: 3, upgrade_type: '功能升级',
  upgrade_time: '2026-10-01 10:00:00', status: '处理中', owner: '张三',
};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  http.get.mockImplementation((url) => {
    if (url.includes('/status-logs/')) return Promise.resolve([]);
    if (url.includes('/steps/')) return Promise.resolve({steps: [], stats: {}});
    if (url.includes('/plans/')) return Promise.resolve([]);
    if (url.includes('/records/1/')) return Promise.resolve(RECORD);
    return Promise.resolve({});
  });
  hasPermission.mockReturnValue(true);
  hasPermissionFn.mockReturnValue(true);
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(container);
  });
  document.body.removeChild(container);
  container = null;
});

function renderWorkbench(recordId) {
  const Workbench = require('../Workbench').default;
  act(() => {
    ReactDOM.render(<Workbench match={{params: recordId ? {id: recordId} : {}}}/>, container);
  });
}

async function renderWorkbenchAsync(recordId) {
  await act(async () => {
    renderWorkbench(recordId);
    await flush();
    await flush();
  });
}

function headerButtons() {
  return Array.from(container.querySelectorAll('.ant-layout-header button'))
    .map(b => b.textContent.replace(/\s/g, ''));
}

describe('升级工作台顶栏（编辑模式）', () => {
  it('不渲染全局保存按钮，顶栏不重复展示记录标题且不再渲染页内面包屑', async () => {
    await renderWorkbenchAsync('1');
    expect(headerButtons()).toEqual(['返回列表']);
    expect(container.querySelector('.ant-layout-header').textContent)
      .not.toContain('DVOR 软件升级');
    // 2026-10-19 导航改造：页面路径由全局 Header 面包屑承担，工作台页内不再渲染面包屑
    expect(container.querySelector('.test-breadcrumb')).toBe(null);
    // 顶栏页面名不再携带标题
    expect(container.querySelector('.ant-layout-header').textContent)
      .toContain('升级工作台');
  });
});

describe('升级工作台顶栏（新建模式）', () => {
  it('保留保存与保存并进入工作台两个入口', () => {
    renderWorkbench(null);
    expect(headerButtons()).toEqual(['返回列表', '保存', '保存并进入工作台']);
  });

  it('无 add 权限时新建保存入口不可见', () => {
    hasPermissionFn.mockImplementation((code) => code !== 'upgrade.upgrade.add');
    renderWorkbench(null);
    expect(headerButtons()).toEqual(['返回列表']);
  });
});
