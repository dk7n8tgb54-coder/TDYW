/**
 * 旧巡检台账（历史）删除改造（2026-09-24）前端契约测试。
 *
 * 真实导入路由表与页面模块（ReactDOM + jsdom，仓库惯例），验证：
 * - routes.js 不再注册 /el/inspection-ledgers 路由（旧巡检菜单已删除）；
 * - 同模块其他入口不受影响：今日巡检/巡检单记录/巡检模板/周月维护/季维护/台账模板仍在；
 * - ledger/entries 不再导出 InspectionLedgerIndex；
 * - 台账类型常量/文本/跳转映射均无 inspection 分支；
 * - 台账模板表单默认类型与类型选项不再包含"巡检"；
 * - 新巡检与维护入口组件仍可正常渲染。
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

function flattenRoutes(nodes, acc = []) {
  (nodes || []).forEach(node => {
    acc.push(node);
    if (node.child) flattenRoutes(node.child, acc);
  });
  return acc;
}

describe('旧巡检台账（历史）入口删除', () => {
  const routes = require('../../../../routes').default;
  const entries = require('../entries');

  it('routes.js 不再注册 /el/inspection-ledgers 路由', () => {
    const all = flattenRoutes(routes);
    expect(all.some(r => r.path === '/el/inspection-ledgers')).toBe(false);
    expect(all.some(r => r.title === '巡检台账（历史）')).toBe(false);
  });

  it('同模块其他入口不受影响：新巡检/周月/季/台账模板路由仍在', () => {
    const all = flattenRoutes(routes);
    const paths = all.map(r => r.path);
    ['/el/inspection-today', '/el/inspection-sheets', '/el/inspection-templates',
      '/el/week-month-ledgers', '/el/seasonal-ledgers', '/el/ledger-templates',
      '/el/systems', '/el/faults', '/el/work-orders',
    ].forEach(path => expect(paths).toContain(path));
  });

  it('ledger/entries 不再导出 InspectionLedgerIndex，维护与新巡检入口仍导出', () => {
    expect(entries.InspectionLedgerIndex).toBeUndefined();
    expect(entries.WeekMonthLedgerIndex).toBeDefined();
    expect(entries.SeasonalLedgerIndex).toBeDefined();
    expect(entries.InspectionToday).toBeDefined();
    expect(entries.InspectionTemplateIndex).toBeDefined();
    expect(entries.InspectionSheetIndex).toBeDefined();
  });

  it('台账类型常量/文本/来源跳转映射均无 inspection 分支', () => {
    const constants = require('../constants');
    expect(constants.LEDGER_TYPE.INSPECTION).toBeUndefined();
    expect(constants.LEDGER_TYPE_TEXT.inspection).toBeUndefined();
    expect(constants.LEDGER_TYPE_TEXT.week_month).toBe('周月维护');
    expect(constants.LEDGER_TYPE_TEXT.seasonal).toBe('季维护');
    const woConstants = require('../../workOrder/constants');
    expect(woConstants.LEDGER_TYPE_PATH.inspection).toBeUndefined();
    expect(woConstants.LEDGER_TYPE_PATH.week_month).toBe('/el/week-month-ledgers');
  });

  it('台账模板表单默认类型为周月维护且不再提供巡检类型选项', async () => {
    const {TemplateStore} = require('../store');
    const TemplateForm = require('../TemplateForm').default;
    const store = new TemplateStore();
    store.formVisible = true;
    let instance = null;
    await act(async () => {
      ReactDOM.render(
        h(TemplateForm, {ref: r => {instance = r;}, store}), container);
    });
    await act(async () => {});
    expect(instance.state.template.ledger_type).toBe('week_month');
    const text = document.body.textContent;
    // 类型下拉当前选中值为"周月维护"（由 LEDGER_TYPE_TEXT 驱动，选项已无巡检）
    expect(text).toContain('周月维护');
    expect(text).not.toContain('巡检');
  });
});

describe('新巡检与维护入口仍正常', () => {
  it('周月维护台账列表页渲染并按类型请求', async () => {
    mockHttpGet.mockResolvedValue({data: [], total: 0, page: 1, page_size: 20});
    const entries = require('../entries');
    await act(async () => {
      ReactDOM.render(h(entries.WeekMonthLedgerIndex), container);
    });
    await act(async () => {});
    expect(container.textContent).toContain('周月维护台账');
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/ledgers/'));
    expect(call[1].params.ledger_type).toBe('week_month');
  });

  it('今日巡检工作台入口组件可挂载', async () => {
    mockHttpGet.mockResolvedValue({data: []});
    const entries = require('../entries');
    await act(async () => {
      ReactDOM.render(h(entries.InspectionToday), container);
    });
    await act(async () => {});
    await flush();
    expect(mockHttpGet).toHaveBeenCalled();
  });
});
