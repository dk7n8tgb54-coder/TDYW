/**
 * 运维台账（步骤 3.2）页面渲染与交互测试。
 *
 * 真实渲染组件（ReactDOM + jsdom，全 createElement 风格与仓库测试惯例一致），
 * mock libs.http 与公共组件壳，验证：
 * - 两类维护台账页面名称正确（周月维护/季维护），周月维护单入口区分周与月；
 *   旧巡检台账（历史）入口已删除，entries 不再导出 InspectionLedgerIndex
 * - 异常数量红色突出显示
 * - 页面不存在机房现场/离线/二维码/移动端入口
 *
 * 旧可视化模板矩阵表单（LedgerForm/MatrixForm）已随旧可视化模板路线整体
 * 删除（2026-10），正式新增台账统一走 Excel/WPS 模板路线，见 UnifiedLedgerEntry.test.js。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement('span', null, props.children);
  const SearchForm = (props) => React.createElement('div', null, props.children);
  SearchForm.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell,
    AuthButton,
    AuthCard: Shell,
    AuthFragment: Shell,
    Breadcrumb,
    SearchForm,
    ExportButton: AuthButton,
    TableCard: Shell,
  };
});

// jsdom 未实现 matchMedia，antd 渲染需要
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
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
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const LEDGERS_PAYLOAD = {
  data: [
    {
      id: 1, ledger_no: 'EL-WM-20260910-0001', ledger_type: 'week_month',
      executed_date: '2026-09-10', status: 'submitted',
      executor_names: '王五', items_count: 3,
      abnormal_count: 2, created_by_name: 'op1', created_at: '2026-09-11 09:00',
    },
  ],
  total: 1, page: 1, page_size: 20,
};

const entriesModule = require('../entries');
const storeModule = require('../store');

describe('三类台账页面', () => {
  test('旧巡检台账（历史）入口已删除：entries 不再导出 InspectionLedgerIndex', () => {
    expect(entriesModule.InspectionLedgerIndex).toBeUndefined();
    expect(entriesModule.WeekMonthLedgerIndex).toBeDefined();
    expect(entriesModule.SeasonalLedgerIndex).toBeDefined();
  });

  test.each([
    [entriesModule.WeekMonthLedgerIndex, 'week_month', '周月维护台账'],
    [entriesModule.SeasonalLedgerIndex, 'seasonal', '季维护台账'],
  ])('%s 入口渲染正确的页面名称与请求类型', async (Component, type, label) => {
    mockHttpGet.mockResolvedValue(LEDGERS_PAYLOAD);
    await act(async () => {
      ReactDOM.render(h(Component), container);
    });
    await act(async () => {});
    expect(container.textContent).toContain(label);
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/ledgers/'));
    expect(call[1].params.ledger_type).toBe(type);
  });

  test('异常数量突出显示（红色加粗）', async () => {
    mockHttpGet.mockResolvedValue(LEDGERS_PAYLOAD);
    await act(async () => {
      ReactDOM.render(h(entriesModule.WeekMonthLedgerIndex), container);
    });
    await act(async () => {});
    const abnormal = container.querySelector('span[style*="f5222d"], span[style*="rgb(245, 34, 45)"]');
    expect(abnormal).not.toBeNull();
    expect(abnormal.textContent).toBe('2');
  });

  test('页面不存在二维码、离线、移动端或机房现场录入入口', async () => {
    mockHttpGet.mockResolvedValue(LEDGERS_PAYLOAD);
    await act(async () => {
      ReactDOM.render(h(entriesModule.WeekMonthLedgerIndex), container);
    });
    await act(async () => {});
    ['二维码', '离线', '移动端', '现场录入', '扫码'].forEach(word => {
      expect(container.textContent).not.toContain(word);
    });
  });
});
