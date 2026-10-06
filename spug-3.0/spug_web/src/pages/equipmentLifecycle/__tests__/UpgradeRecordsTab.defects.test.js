/**
 * 缺陷复现测试（2026-10-04 审计）：系统详情"升级记录"页签分页。
 *
 * T1  服务端分页被静默忽略：后端 SystemUpgradeRecordsView 走 paginate()
 *     默认 page_size=20，前端不传分页参数且用客户端分页——某系统升级记录
 *     超过 20 条时第 21 条起永远不显示，"共 N 条"最多 20。
 *     期望：组件请求携带 page/page_size，使用服务端 total，翻页触发新请求。
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

jest.mock('components', () => ({
  AuthDiv: ({children}) => <div>{children}</div>,
}));

const {http} = require('libs');

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}

let container = null;
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function makeRecords(count) {
  return Array.from({length: count}, (_, i) => ({
    id: i + 1,
    upgrade_no: `SJ20261001-${String(i + 1).padStart(4, '0')}`,
    title: `升级记录 ${i + 1}`,
    upgrade_type: '功能升级',
    upgrade_time: '2026-10-01 10:00:00',
    status: '处理中',
    owner: '张三',
  }));
}

function mockPageResponse(page, pageSize) {
  const all = makeRecords(25);
  http.get.mockImplementation((url, config) => {
    expect(url).toBe('/api/equipment-lifecycle/systems/3/upgrade-records/');
    const params = (config && config.params) || {};
    const p = params.page || 1;
    const size = params.page_size || 20;
    const data = all.slice((p - 1) * size, p * size);
    return Promise.resolve({data, total: all.length, page: p, page_size: size});
  });
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  container = null;
});

function renderTab() {
  const UpgradeRecordsTab = require('../../equipmentLifecycle/UpgradeRecordsTab').default;
  act(() => {
    ReactDOM.render(<UpgradeRecordsTab systemId={3}/>, container);
  });
}

describe('缺陷复现：升级记录页签服务端分页', () => {
  it('首屏请求携带 page/page_size 并展示服务端 total', async () => {
    mockPageResponse(1, 10);
    renderTab();
    await act(async () => { await flush(); });

    expect(http.get).toHaveBeenCalledTimes(1);
    const config = http.get.mock.calls[0][1];
    expect(config).toBeDefined();
    expect(config.params.page).toBe(1);
    expect(config.params.page_size).toBe(10);
    expect(container.textContent).toContain('共 25 条');
  });

  it('点击第 2 页触发携带 page=2 的新请求', async () => {
    mockPageResponse(1, 10);
    renderTab();
    await act(async () => { await flush(); });

    const page2 = document.querySelector('.ant-pagination-item-2');
    expect(page2).not.toBeNull();
    act(() => {
      page2.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    });
    await act(async () => { await flush(); await flush(); });

    const secondCall = http.get.mock.calls[1];
    expect(secondCall).toBeDefined();
    expect(secondCall[1].params.page).toBe(2);
  });
});
