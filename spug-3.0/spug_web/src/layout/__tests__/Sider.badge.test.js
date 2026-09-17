/**
 * Sider 菜单红点行为测试（2026-09 台站频率批复第一轮改造）。
 *
 * 真实渲染 Sider（ReactDOM + jsdom），mock 徽标 store 与 routes，验证：
 * - 无线电台执照子菜单显示执照徽标
 * - 台站频率批复子菜单不再显示红点（批复取消主动提醒）
 * - 父菜单"无线电执照管理"合计只含执照徽标数量
 * - Sider 模块图不再包含已删除的 ApprovalBadgeStore
 *   （若 Sider 仍引用它，jest 解析阶段即失败）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockBadgeStore = (count, loaded) => ({
  count,
  loaded,
  expiringCount: count,
  expiredCount: 0,
  start: jest.fn(),
  stop: jest.fn(),
  fetch: jest.fn(),
});

jest.mock('../RadioLicenseBadgeStore', () => mockBadgeStore(2, true));
jest.mock('../CoopTaskBadgeStore', () => mockBadgeStore(0, true));
jest.mock('../ContractAgreementBadgeStore', () => mockBadgeStore(0, true));

jest.mock('libs', () => ({
  hasPermission: jest.fn(() => true),
  history: {
    push: jest.fn(),
    listen: jest.fn(() => () => {}),
  },
}));

jest.mock('../../routes', () => ([
  {
    icon: 'safe',
    title: '无线电执照管理',
    auth: 'radio_license.license.view|radio_license.approval.view',
    child: [
      {title: '无线电台执照', auth: 'radio_license.license.view', path: '/radio-license'},
      {title: '台站频率批复', auth: 'radio_license.approval.view', path: '/station-frequency-approval'},
    ],
  },
]));

const Sider = require('../Sider').default;

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

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
});

function menuItemByText(text) {
  return Array.from(container.querySelectorAll('.ant-menu-item'))
    .find(li => li.textContent.includes(text));
}

function renderSiderAt(pathname) {
  // Sider 挂载时按 window.location.pathname 初始化 openKeys；
  // 内联子菜单只有展开后才渲染子项，先导航到执照页使其展开
  window.history.pushState({}, '', pathname);
  act(() => {
    ReactDOM.render(<Sider collapsed={false}/>, container);
  });
}

describe('Sider 菜单红点（批复红点已移除）', () => {
  it('执照子菜单显示徽标，批复子菜单不显示徽标', () => {
    renderSiderAt('/radio-license');
    const licenseItem = menuItemByText('无线电台执照');
    const approvalItem = menuItemByText('台站频率批复');
    expect(licenseItem).toBeTruthy();
    expect(approvalItem).toBeTruthy();

    // 执照徽标存在且数量为 2
    const licenseBadge = licenseItem.querySelector('.ant-badge-count');
    expect(licenseBadge).toBeTruthy();
    expect(licenseBadge.textContent).toContain('2');

    // 批复子菜单不再有红点
    expect(approvalItem.querySelector('.ant-badge')).toBeNull();
  });

  it('父菜单合计只统计执照徽标数量（不含批复）', () => {
    renderSiderAt('/radio-license');
    const parentLi = Array.from(container.querySelectorAll('.ant-menu-submenu'))
      .find(li => li.textContent.includes('无线电执照管理'));
    expect(parentLi).toBeTruthy();
    // 父菜单标题行内的徽标数量 = 执照(2)，不含任何批复计数
    const titleBadges = parentLi.querySelectorAll('.ant-menu-submenu-title .ant-badge-count');
    expect(titleBadges.length).toBe(1);
    expect(titleBadges[0].textContent).toContain('2');
  });
});
