/**
 * 工作台到期提醒卡片（ExpiryOverview）行为测试（上线门禁 六.9）。
 *
 * 真实渲染组件，mock libs（http/history/hasPermission），验证：
 * - 按权限请求执照/批复徽标接口，数量渲染正确
 * - 点击执照行跳转 /radio-license，点击批复行跳转 /station-frequency-approval
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
  it('渲染执照与批复徽标数量并正确跳转', async () => {
    grantPerms(['radio_license.license.view', 'radio_license.approval.view']);
    mockHttpGet.mockImplementation(url => {
      if (url === '/api/radio-license/badge/') {
        return Promise.resolve({count: 4, expiring_count: 3, expired_count: 1});
      }
      if (url === '/api/radio-license/approvals/badge/') {
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
    // 总计：3(执照) + 2(批复) = 5
    expect(text).toContain('5');
    expect(text).toContain('无线电台执照');
    expect(text).toContain('3 项');
    expect(text).toContain('频率批复');
    expect(text).toContain('2 项');
    // 过期标签
    expect(text).toContain('执照已过期 1');

    // 点击执照行 → 跳转执照页面
    const rows = Array.from(container.querySelectorAll('div'))
      .filter(d => d.textContent.trim() === '无线电台执照');
    const licenseRow = rows[rows.length - 1].parentElement;
    act(() => {
      licenseRow.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(mockPush).toHaveBeenCalledWith('/radio-license');

    // 点击批复行 → 跳转批复页面
    const approvalRows = Array.from(container.querySelectorAll('div'))
      .filter(d => d.textContent.trim() === '频率批复');
    const approvalRow = approvalRows[approvalRows.length - 1].parentElement;
    act(() => {
      approvalRow.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(mockPush).toHaveBeenCalledWith('/station-frequency-approval');
  });

  it('接口全部失败时显示降级文案', async () => {
    grantPerms(['radio_license.license.view', 'radio_license.approval.view']);
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
    grantPerms([]);
    render();
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockHttpGet).not.toHaveBeenCalled();
    expect(container.textContent).toContain('暂无可查看的到期信息');
  });

  it('全部为 0 时显示空状态文案', async () => {
    grantPerms(['radio_license.license.view', 'radio_license.approval.view']);
    mockHttpGet.mockResolvedValue({count: 0, expiring_count: 0, expired_count: 0});
    render();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.textContent).toContain('暂无即将到期的执照、批复和合同');
  });
});
