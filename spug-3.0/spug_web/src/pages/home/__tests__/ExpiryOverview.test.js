/**
 * 工作台到期提醒卡片（ExpiryOverview）行为测试（上线门禁 六.9）。
 *
 * 真实渲染组件，mock libs（http/history/hasPermission），验证：
 * - 按权限请求执照/合同徽标接口，数量渲染正确
 * - 2026-09 第一轮改造：批复不再参与首页到期概览，
 *   即便用户拥有 radio_license.approval.view 也不请求 approvals/badge/
 * - 点击执照行跳转 /radio-license，点击合同行跳转 /contract-agreement
 * - 接口失败时显示降级文案（不崩溃）
 * - 无任何权限时显示占位文案
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockPush = jest.fn();
const mockHasPermission = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet},
  history: {push: mockPush},
  hasPermission: mockHasPermission,
}));

const ExpiryOverview = require('../ExpiryOverview').default;

let container = null;

function render() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<ExpiryOverview/>, container);
  });
}

beforeEach(() => {
  jest.clearAllMocks();
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

function grantPerms(perms) {
  mockHasPermission.mockImplementation(code => perms.includes(code));
}

describe('工作台到期提醒卡片', () => {
  it('渲染执照与合同徽标数量并正确跳转，不请求批复徽标', async () => {
    grantPerms([
      'radio_license.license.view',
      'radio_license.approval.view',
      'contract_agreement.agreement.view',
    ]);
    mockHttpGet.mockImplementation(url => {
      if (url === '/api/radio-license/badge/') {
        return Promise.resolve({count: 4, expiring_count: 3, expired_count: 1});
      }
      if (url === '/api/contract-agreement/badge/') {
        return Promise.resolve({count: 2, expiring_count: 2, expired_count: 0});
      }
      return Promise.resolve({});
    });
    render();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const text = container.textContent;
    // 总计：3(执照) + 2(合同) = 5
    expect(text).toContain('5');
    expect(text).toContain('无线电台执照');
    expect(text).toContain('3 项');
    expect(text).toContain('合同协议');
    expect(text).toContain('2 项');
    // 过期标签
    expect(text).toContain('执照已过期 1');
    // 批复不再参与统计（2026-09 第一轮改造）
    expect(text).not.toContain('频率批复');
    expect(text).not.toContain('批复已过期');

    // 请求了执照与合同徽标，未请求批复徽标
    const requestedUrls = mockHttpGet.mock.calls.map(([url]) => url);
    expect(requestedUrls).toContain('/api/radio-license/badge/');
    expect(requestedUrls).toContain('/api/contract-agreement/badge/');
    expect(requestedUrls.filter(url => url.includes('/approvals/badge/'))).toHaveLength(0);

    // 点击执照行 → 跳转执照页面（行 onClick 在包裹 label span 的 div 上）
    const licenseLabel = Array.from(container.querySelectorAll('span'))
      .find(sp => sp.textContent.trim() === '无线电台执照');
    const licenseRow = licenseLabel.parentElement;
    act(() => {
      licenseRow.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(mockPush).toHaveBeenCalledWith('/radio-license');

    // 点击合同行 → 跳转合同页面
    const contractLabel = Array.from(container.querySelectorAll('span'))
      .find(sp => sp.textContent.trim() === '合同协议');
    const contractRow = contractLabel.parentElement;
    act(() => {
      contractRow.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(mockPush).toHaveBeenCalledWith('/contract-agreement');
  });

  it('接口全部失败时显示降级文案', async () => {
    grantPerms(['radio_license.license.view', 'contract_agreement.agreement.view']);
    mockHttpGet.mockRejectedValue(new Error('timeout'));
    render();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.textContent).toContain('到期数据暂时无法获取');
  });

  it('无任何到期模块权限时不发请求', async () => {
    grantPerms(['radio_license.approval.view']);
    render();
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockHttpGet).not.toHaveBeenCalled();
    expect(container.textContent).toContain('暂无可查看的到期信息');
  });

  it('全部为 0 时显示空状态文案', async () => {
    grantPerms(['radio_license.license.view', 'contract_agreement.agreement.view']);
    mockHttpGet.mockResolvedValue({count: 0, expiring_count: 0, expired_count: 0});
    render();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.textContent).toContain('暂无即将到期的执照和合同');
  });
});
