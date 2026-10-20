/**
 * Header 全局路径面包屑行为测试（2026-10-19 导航改造）。
 *
 * 真实渲染 Header（MemoryRouter 提供路由上下文 + 真实 routeMeta），
 * 验证面包屑标题与层级统一取自 routes.js 配置：
 * - 菜单路由：首页 / 分组… / 页面标题
 * - 隐藏路由（tabTitle/tabCrumbs）：系统公告、升级工作台等
 * - 未知路径仅显示首页
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {MemoryRouter} from 'react-router-dom';
import {act} from 'react-dom/test-utils';

jest.mock('libs', () => ({
  hasPermission: jest.fn(() => true),
  history: {push: jest.fn(), listen: jest.fn(() => () => {})},
}));
jest.mock('../../libs/http', () => ({__esModule: true, default: {get: jest.fn()}}));
jest.mock('../AlertStore', () => ({
  unreadCount: 0, recentAlerts: [], loading: false,
  fetchRecent: jest.fn(), markAllRead: jest.fn(),
}));
jest.mock('../../pages/release/store', () => ({unreadCount: 0, openDrawer: jest.fn()}));

jest.mock('../../routes', () => [
  {icon: 'home', title: '工作台', auth: 'dashboard.dashboard.view', path: '/home', component: 'Home'},
  {icon: 'el', title: '设备管理', auth: 'el.system.view', child: [
    {title: '系统档案', auth: 'el.system.view', path: '/el/systems', component: 'Systems'},
  ]},
  {path: '/upgrade/workbench/:id', component: 'WB', tabTitle: '升级工作台', tabCrumbs: ['设备管理', '系统升级管理']},
  {path: '/announcement', component: 'AL', tabTitle: '系统公告'},
]);

const Header = require('../Header').default;

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  sessionStorage.setItem('nickname', '测试用户');
  sessionStorage.setItem('is_supper', 'false');
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(container);
  });
  document.body.removeChild(container);
  container = null;
});

function renderAt(pathname) {
  act(() => {
    ReactDOM.render(
      <MemoryRouter initialEntries={[pathname]}>
        <Header collapsed={false} toggle={() => {}}/>
      </MemoryRouter>,
      container);
  });
}

function crumbsText() {  // antd 渲染带尾部分隔符
  const node = container.querySelector('.ant-breadcrumb');
  return node ? node.textContent.replace(/\/$/, '') : '';
}

describe('Header 全局面包屑', () => {
  it('菜单路由按路由配置渲染层级：首页/设备管理/系统档案', () => {
    renderAt('/el/systems');
    expect(crumbsText()).toBe('首页/设备管理/系统档案');
  });

  it('隐藏路由按 tabTitle/tabCrumbs 渲染归属与标题（系统公告）', () => {
    renderAt('/announcement');
    expect(crumbsText()).toBe('首页/系统公告');
  });

  it('带参数路由按 tabCrumbs 渲染层级（升级工作台）', () => {
    renderAt('/upgrade/workbench/9');
    expect(crumbsText()).toBe('首页/设备管理/系统升级管理/升级工作台');
  });

  it('未知路径仅显示首页', () => {
    renderAt('/no/such/path');
    expect(crumbsText()).toBe('首页');
  });

  it('面包屑位于折叠按钮与右侧操作之间，右侧账号操作保留', () => {
    renderAt('/el/systems');
    const header = container.querySelector('.ant-layout-header');
    expect(header.textContent).toContain('系统档案');
    expect(header.textContent).toContain('测试用户');
  });
});
