/**
 * 系统详情「升级记录」页签编号列测试（2026-10 升级编号回归）
 *
 * 真实渲染 UpgradeRecordsTab（ReactDOM + jsdom，仓库惯例），mock libs http
 * 返回带 upgrade_no 的记录，验证表头「编号」与行内编号展示。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(() => Promise.resolve()),
    delete: jest.fn(() => Promise.resolve()),
  },
}));

jest.mock('components', () => {
  const React = require('react');
  return {
    AuthDiv: ({children}) => <div>{children}</div>,
  };
});

let container = null;

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

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockReset();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  container = null;
});

function renderTab(systemId) {
  const UpgradeRecordsTab = require('../UpgradeRecordsTab').default;
  act(() => {
    ReactDOM.render(<UpgradeRecordsTab systemId={systemId}/>, container);
  });
}

describe('系统详情升级记录页签编号列', () => {
  it('请求本系统升级记录并展示编号列', async () => {
    mockHttpGet.mockImplementation((url) => {
      expect(url).toBe('/api/equipment-lifecycle/systems/7/upgrade-records/');
      return Promise.resolve({
        data: [{
          id: 1,
          upgrade_no: 'SJ20261002-0003',
          title: 'ILS 台站软件升级',
          upgrade_type: '功能升级',
          upgrade_time: '2026-10-02 09:00:00',
          status: '处理中',
          owner: '李四',
        }],
      });
    });

    renderTab(7);
    await act(async () => {
      await Promise.resolve();
    });

    const headers = Array.from(container.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent);
    expect(headers[0]).toBe('编号');
    expect(container.textContent).toContain('SJ20261002-0003');
  });
});
