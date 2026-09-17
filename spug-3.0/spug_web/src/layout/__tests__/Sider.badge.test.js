/**
 * Sider 菜单红点行为测试（2026-09 第二轮：批复全局红点恢复）。
 *
 * 真实渲染 Sider（ReactDOM + jsdom），mock 徽标 store 与 routes，验证：
 * - 无线电台执照子菜单显示执照徽标
 * - 台站频率批复子菜单显示全局红点数字（所有 approval.view 账户相同）
 * - 父菜单"无线电执照管理"合计 = 执照 + 批复红点数量
 * - count 为 0 或首次成功加载前（loaded=false）不显示红圈
 *
 * 注意：不使用 jest.resetModules（会产生两份 React 导致 hooks 报错），
 * 三个徽标 store 是被 mock 的单例对象，各用例直接改字段后重新渲染。
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

const mockLicenseStore = mockBadgeStore(2, true);
const mockApprovalStore = mockBadgeStore(5, true);

jest.mock('../RadioLicenseBadgeStore', () => mockLicenseStore);
jest.mock('../ApprovalBadgeStore', () => mockApprovalStore);
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
  mockLicenseStore.count = 2;
  mockLicenseStore.loaded = true;
  mockApprovalStore.count = 5;
  mockApprovalStore.loaded = true;
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

function parentSubmenu() {
  return Array.from(container.querySelectorAll('.ant-menu-submenu'))
    .find(li => li.textContent.includes('无线电执照管理'));
}

function renderSiderAt(pathname) {
  // Sider 挂载时按 window.location.pathname 初始化 openKeys；
  // 内联子菜单只有展开后才渲染子项，先导航到执照页使其展开
  window.history.pushState({}, '', pathname);
  act(() => {
    ReactDOM.render(<Sider collapsed={false}/>, container);
  });
}

describe('Sider 菜单红点（批复全局红点恢复）', () => {
  it('执照与批复子菜单分别显示各自红点数字', () => {
    renderSiderAt('/radio-license');
    const licenseItem = menuItemByText('无线电台执照');
    const approvalItem = menuItemByText('台站频率批复');
    expect(licenseItem).toBeTruthy();
    expect(approvalItem).toBeTruthy();

    const licenseBadge = licenseItem.querySelector('.ant-badge-count');
    expect(licenseBadge).toBeTruthy();
    expect(licenseBadge.textContent).toContain('2');

    // 批复红点恢复：显示全局统计数字
    const approvalBadge = approvalItem.querySelector('.ant-badge-count');
    expect(approvalBadge).toBeTruthy();
    expect(approvalBadge.textContent).toContain('5');
  });

  it('父菜单合计 = 执照红点 + 批复红点', () => {
    renderSiderAt('/radio-license');
    const parentLi = parentSubmenu();
    expect(parentLi).toBeTruthy();
    // 父菜单标题行内徽标数量 = 执照(2) + 批复(5) = 7
    const titleBadges = parentLi.querySelectorAll('.ant-menu-submenu-title .ant-badge-count');
    expect(titleBadges.length).toBe(1);
    expect(titleBadges[0].textContent).toContain('7');
  });

  it('批复 count 为 0 时子菜单不显示红圈，父菜单只合计执照', () => {
    mockApprovalStore.count = 0;
    renderSiderAt('/radio-license');
    const approvalItem = menuItemByText('台站频率批复');
    expect(approvalItem.querySelector('.ant-badge')).toBeNull();
    // 父菜单合计只剩执照 2
    const titleBadge = parentSubmenu().querySelector('.ant-menu-submenu-title .ant-badge-count');
    expect(titleBadge).toBeTruthy();
    expect(titleBadge.textContent).toContain('2');
  });

  it('批复首次成功加载前（loaded=false）不显示红圈', () => {
    mockApprovalStore.loaded = false;
    renderSiderAt('/radio-license');
    const approvalItem = menuItemByText('台站频率批复');
    expect(approvalItem.querySelector('.ant-badge')).toBeNull();
    // 父菜单合计要求组内全部 store 已成功加载：批复未加载前整体不显示
    expect(parentSubmenu().querySelector('.ant-menu-submenu-title .ant-badge-count')).toBeNull();
  });
});
