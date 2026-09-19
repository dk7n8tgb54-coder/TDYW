/**
 * 设备全生命周期（步骤 3.5）当前运行状态页面测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 加载 status-summary 汇总并渲染六种健康状态卡片与总数
 * - 点击状态卡片按该状态筛选列表（不修改任何状态，只读页面）
 * - 列表复用 /systems/ 查询接口，行内"详情"跳转 /el/systems?detail=
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  history: {push: jest.fn()},
  Permission: {isSuper: true},
  X_TOKEN: '',
  exportFile: jest.fn(),
  syncAttachmentCount: jest.fn(),
}));

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  mockHttpGet.mockReset();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {});
}

const SUMMARY_PAYLOAD = {
  summary: {normal: 5, degraded: 2, fault: 1, repairing: 1, interrupted: 0, unknown: 0},
  total: 9, active_total: 8, inactive_total: 1,
};

const SYSTEMS_PAYLOAD = {
  data: [
    {id: 5, system_code: 'SYS-001', name: '通信系统',
      install_location: '机房A', health_status: 'fault', health_status_text: '故障',
      is_active: true},
  ],
  total: 1,
};

describe('当前运行状态页面', () => {
  it('渲染健康状态汇总卡片、总数与状态列表（只读）', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('status-summary')) return Promise.resolve(SUMMARY_PAYLOAD);
      return Promise.resolve(SYSTEMS_PAYLOAD);
    });
    // eslint-disable-next-line global-require
    const SystemStatusIndex = require('../index').default;
    await act(async () => {
      ReactDOM.render(<SystemStatusIndex/>, container);
    });
    await act(flush);
    const text = document.body.textContent;
    expect(text).toContain('正常');
    expect(text).toContain('降级');
    expect(text).toContain('故障');
    expect(text).toContain('维修中');
    expect(text).toContain('中断');
    expect(text).toContain('未知');
    expect(text).toContain('系统总数（可用 8 / 停用 1）');
    expect(text).toContain('SYS-001');
    // 只读页面：没有修改健康状态的入口
    expect(text).not.toContain('修改状态');
    // 汇总接口被调用
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/status-summary/');
  });

  it('点击状态卡片按状态筛选列表；行内详情跳转系统列表 ?detail=', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('status-summary')) return Promise.resolve(SUMMARY_PAYLOAD);
      return Promise.resolve(SYSTEMS_PAYLOAD);
    });
    // eslint-disable-next-line global-require
    const SystemStatusIndex = require('../index').default;
    await act(async () => {
      ReactDOM.render(<SystemStatusIndex/>, container);
    });
    await act(flush);
    const faultCard = Array.from(container.querySelectorAll('.ant-card'))
      .filter(card => !card.querySelector('.ant-card') && card.textContent.includes('故障'))
      .find(card => card.textContent.includes('套'));
    await click(faultCard.querySelector('.ant-card-body') || faultCard);
    expect(mockHttpGet).toHaveBeenLastCalledWith('/api/equipment-lifecycle/systems/', {
      params: {page: 1, page_size: 20, health_status: 'fault'},
    });
    // 行内详情链接跳转
    const detailLink = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '详情');
    await click(detailLink);
    // eslint-disable-next-line global-require
    const libs = require('libs');
    expect(libs.history.push).toHaveBeenCalledWith('/el/systems?detail=5');
  });
});
