/**
 * 主布局 Badge Store 启停与提醒组件挂载行为测试（2026-09 第二轮）。
 *
 * 真实渲染 layout/index（ReactDOM + jsdom），mock 布局子组件与外部依赖，
 * 验证：
 * - 布局挂载时立即启动执照/批复/合同三个 Badge Store（登录进入主布局立即获取）
 * - 布局卸载时停止全部 Badge Store（事件监听与跨日刷新生命周期终止）
 * - 执照与合同弹窗提醒组件仍正常挂载；不存在批复弹窗组件
 * - 批复相关 popup / ack 接口不会被请求
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {MemoryRouter} from 'react-router-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn().mockResolvedValue({data: {}});
const mockHasPermission = jest.fn(() => true);

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
  hasPermission: mockHasPermission,
}));

const mockBadgeStoreFactory = () => ({
  start: jest.fn(),
  stop: jest.fn(),
  fetch: jest.fn(),
  count: 0,
  loaded: false,
});

jest.mock('../RadioLicenseBadgeStore', () => mockBadgeStoreFactory());
jest.mock('../ApprovalBadgeStore', () => mockBadgeStoreFactory());
jest.mock('../CoopTaskBadgeStore', () => mockBadgeStoreFactory());
jest.mock('../ContractAgreementBadgeStore', () => mockBadgeStoreFactory());
jest.mock('../AlertStore', () => ({start: jest.fn(), stop: jest.fn()}));

jest.mock('../Sider', () => () => <div data-testid="sider"/>);
jest.mock('../Header', () => () => <div/>);
// 2026-10-19 导航改造：工作页签条为布局子组件，这里 mock 掉（其行为有独立测试）
jest.mock('../WorkTabs', () => () => <div data-testid="work-tabs"/>);
jest.mock('../Footer', () => () => <div/>);
jest.mock('components', () => ({NotFound: () => <div/>}));
jest.mock('components/expirationReminderConfigs', () => ({licenseReminderConfig: {}}));
jest.mock('components/ExpirationReminderNotification', () =>
  () => <div data-testid="license-reminder"/>);
jest.mock('components/ContractAgreementReminderNotification', () =>
  () => <div data-testid="contract-reminder"/>);
jest.mock('../../pages/release/ReleaseNoteNotification', () => () => <div/>);
jest.mock('../../pages/release/ReleaseNoteDrawer', () => () => <div/>);
jest.mock('../../pages/release/store', () => ({fetchVersion: jest.fn()}));
jest.mock('../../routes', () => []);

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

function renderLayout() {
  const LayoutRoot = require('../index').default;
  act(() => {
    ReactDOM.render(
      <MemoryRouter><LayoutRoot/></MemoryRouter>, container);
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockHttpGet.mockResolvedValue({data: {}});
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

describe('主布局 Badge Store 生命周期', () => {
  it('挂载时立即启动执照/批复/合同三个 Badge Store 及告警 Store', () => {
    renderLayout();
    const radioLicenseBadge = require('../RadioLicenseBadgeStore');
    const approvalBadge = require('../ApprovalBadgeStore');
    const contractAgreementBadge = require('../ContractAgreementBadgeStore');
    const alertStore = require('../AlertStore');
    expect(radioLicenseBadge.start).toHaveBeenCalledTimes(1);
    expect(approvalBadge.start).toHaveBeenCalledTimes(1);
    expect(contractAgreementBadge.start).toHaveBeenCalledTimes(1);
    expect(alertStore.start).toHaveBeenCalledTimes(1);
  });

  it('卸载时停止全部 Badge Store，跨日事件不再产生刷新', () => {
    renderLayout();
    const approvalBadge = require('../ApprovalBadgeStore');
    const radioLicenseBadge = require('../RadioLicenseBadgeStore');
    const contractAgreementBadge = require('../ContractAgreementBadgeStore');
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
    expect(radioLicenseBadge.stop).toHaveBeenCalledTimes(1);
    expect(approvalBadge.stop).toHaveBeenCalledTimes(1);
    expect(contractAgreementBadge.stop).toHaveBeenCalledTimes(1);

    // 卸载后 focus / visible 事件不触发任何 badge 请求
    const callsBefore = mockHttpGet.mock.calls.length;
    window.dispatchEvent(new Event('focus'));
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible', configurable: true,
    });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(mockHttpGet.mock.calls.length).toBe(callsBefore);
  });

  it('执照与合同弹窗提醒仍挂载；不挂载批复弹窗组件', () => {
    renderLayout();
    expect(document.querySelector('[data-testid="license-reminder"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="contract-reminder"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="approval-reminder"]')).toBeNull();
  });

  it('布局生命周期内不请求批复 popup 或 ack 接口', async () => {
    renderLayout();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const urls = mockHttpGet.mock.calls.map(([url]) => String(url));
    const approvalReminderUrls = urls.filter(
      url => url.includes('/approvals/reminders/popup/') || url.includes('/approvals/reminders/ack/'));
    expect(approvalReminderUrls).toHaveLength(0);
  });
});
