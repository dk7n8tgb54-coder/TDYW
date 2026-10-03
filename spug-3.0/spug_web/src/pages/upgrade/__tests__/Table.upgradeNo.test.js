/**
 * 升级表单列表编号列测试（2026-10 升级编号回归）
 *
 * 真实渲染 Table 组件（ReactDOM + jsdom，仓库惯例），mock libs 与 components
 * （TableCard 以 antd Table 透传，保留真实 antd Table 列渲染），验证：
 * - 列表首列为「编号」，行内展示后端返回的 upgrade_no（如 SJ20261001-0007）；
 * - 历史数据编号缺失时行渲染不报错。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import { Table } from 'antd';
import ComTable from '../Table';
import store from '../store';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => new Promise(() => {})),
    post: jest.fn(() => Promise.resolve()),
    delete: jest.fn(() => Promise.resolve()),
  },
  hasPermission: jest.fn(() => true),
  exportFile: jest.fn(),
}));

jest.mock('libs/history', () => ({
  __esModule: true,
  default: {push: jest.fn(), replace: jest.fn()},
}));

jest.mock('components', () => {
  const React = require('react');
  const {Table} = require('antd');
  return {
    // 透传给真实 antd Table，保留列的真实渲染行为
    TableCard: ({children, dataSource, rowKey, loading, pagination}) => (
      <Table dataSource={dataSource} rowKey={rowKey} loading={loading} pagination={pagination}>
        {children}
      </Table>
    ),
    Action: Object.assign(
      ({children}) => <span>{children}</span>,
      {Button: ({children, onClick}) => <button type="button" onClick={onClick}>{children}</button>},
    ),
    AuthButton: ({children}) => <button type="button">{children}</button>,
    ExportButton: ({children}) => <button type="button">{children}</button>,
  };
});

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

const ROW_WITH_NO = {
  id: 1,
  upgrade_no: 'SJ20261001-0007',
  title: 'DVOR 软件升级',
  system_name: 'DVOR系统',
  upgrade_type: '功能升级',
  upgrade_time: '2026-10-01 10:00:00',
  status: '处理中',
  owner: '张三',
  attachment_count: 0,
};

const ROW_WITHOUT_NO = {
  ...ROW_WITH_NO,
  id: 2,
  upgrade_no: '',
  title: '历史存量记录',
};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  store.records = [ROW_WITH_NO, ROW_WITHOUT_NO];
  store.total = 2;
  store.page = 1;
  store.pageSize = 20;
  store.isFetching = false;
  store.f_export_date_range = null;
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  container = null;
});

function renderTable() {
  ReactDOM.render(<ComTable/>, container);
}

describe('升级表单列表编号列', () => {
  it('首列表头为「编号」，行内展示 upgrade_no', () => {
    act(() => {
      renderTable();
    });
    const headers = Array.from(container.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent);
    expect(headers[0]).toBe('编号');
    expect(container.textContent).toContain('SJ20261001-0007');
  });

  it('编号缺失的历史行渲染不报错', () => {
    act(() => {
      renderTable();
    });
    const row = Array.from(container.querySelectorAll('.ant-table-tbody tr'))
      .find(tr => tr.textContent.includes('历史存量记录'));
    expect(row).toBeDefined();
  });
});
