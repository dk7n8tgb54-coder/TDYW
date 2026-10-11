/**
 * 旧巡检台账（历史）删除改造（2026-09-24）前端契约测试。
 *
 * 真实导入路由表与页面模块（ReactDOM + jsdom，仓库惯例），验证：
 * - routes.js 不再注册 /el/inspection-ledgers 路由（旧巡检菜单已删除）；
 * - 同模块维护入口不受影响：周月维护/季维护/Excel台账模板仍在；
 *   日巡视活跃入口已整体下线（2026-10-11），巡检中心及其旧路径兼容路由注销；
 * - ledger/entries 不再导出 InspectionLedgerIndex 与任何巡检入口；
 * - 台账类型常量/文本/跳转映射均无 inspection 分支；
 * - 台账模板表单默认类型与类型选项不再包含"巡检"；
 * - 维护台账入口组件仍可正常渲染。
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

  it('同模块其他入口不受影响：周月/季/Excel台账模板路由仍在', () => {
    const all = flattenRoutes(routes);
    const paths = all.map(r => r.path);
    ['/el/week-month-ledgers', '/el/seasonal-ledgers', '/el/excel-ledger-templates',
      '/el/systems', '/el/faults',
    ].forEach(path => expect(paths).toContain(path));
    // 工单路由已随故障维修工单功能整体删除（2026-09-30）
    expect(paths).not.toContain('/el/work-orders');
    // 旧可视化台账模板入口已随旧可视化模板路线整体删除（2026-10）
    expect(paths).not.toContain('/el/ledger-templates');
    // 日巡视活跃功能已整体下线（2026-10-11）：巡检中心与其旧独立路径
    // 兼容路由全部注销（历史数据保留在后端，见下线契约测试）
    ['/el/inspection-center', '/el/inspection-today',
      '/el/inspection-sheets', '/el/inspection-templates',
    ].forEach(path => expect(paths).not.toContain(path));
  });

  it('ledger/entries 只导出维护台账入口（新旧巡检入口均已删除）', () => {
    expect(entries.InspectionLedgerIndex).toBeUndefined();
    expect(entries.WeekMonthLedgerIndex).toBeDefined();
    expect(entries.SeasonalLedgerIndex).toBeDefined();
    // 日巡视活跃功能下线（2026-10-11）：巡检入口导出一并删除
    expect(entries.InspectionToday).toBeUndefined();
    expect(entries.InspectionTemplateIndex).toBeUndefined();
    expect(entries.InspectionSheetIndex).toBeUndefined();
  });

  it('台账类型常量/文本/来源跳转映射均无 inspection 分支', () => {
    const constants = require('../constants');
    expect(constants.LEDGER_TYPE.INSPECTION).toBeUndefined();
    expect(constants.LEDGER_TYPE_TEXT.inspection).toBeUndefined();
    expect(constants.LEDGER_TYPE_TEXT.week_month).toBe('周月维护');
    expect(constants.LEDGER_TYPE_TEXT.seasonal).toBe('季维护');
    // LEDGER_TYPE_PATH 已随工单功能删除迁入 ledger/constants（2026-09-30）
    expect(constants.LEDGER_TYPE_PATH.inspection).toBeUndefined();
    expect(constants.LEDGER_TYPE_PATH.week_month).toBe('/el/week-month-ledgers');
  });

  it('旧可视化台账模板入口组件已整体删除（2026-10）', () => {
    let deleted = false;
    try {
      jest.isolateModules(() => require('../TemplateIndex'));
    } catch (e) {
      deleted = true;
    }
    expect(deleted).toBe(true);
  });
});

describe('维护台账入口仍正常', () => {
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

  it('日巡视入口组件已整体删除（2026-10-11）', () => {
    let deleted = false;
    try {
      jest.isolateModules(() => require('../../inspection/InspectionWorksheet'));
    } catch (e) {
      deleted = true;
    }
    expect(deleted).toBe(true);
  });
});
