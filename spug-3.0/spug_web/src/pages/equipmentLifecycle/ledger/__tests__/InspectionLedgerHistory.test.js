/**
 * 旧巡检台账只读历史（值班巡检改造）前端契约测试。
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http 与公共组件壳，验证：
 * - "巡检台账（历史）"不提供任何写操作（无新增/编辑/提交/作废），
 *   历史查询仍调用 ledgers/ 接口并携带 ledger_type=inspection；
 * - 周/月/季维护台账仍显示对应写操作（草稿可编辑/提交/作废）；
 * - 巡检台账详情（历史）异常明细不再显示"转故障/转工单"，
 *   历史已处置明细仍展示处置目标跳转；周月维护台账不受影响；
 * - 新巡检异常转单继续调用 inspection-sheets/.../convert-* 独立接口
 *   （不调用旧 ledgers/.../convert-* 接口）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';

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
  history: {push: jest.fn()},
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

function draftLedgerRow(type) {
  return {
    id: 1, ledger_no: `EL-${type === 'inspection' ? 'INS' : 'WM'}-20260910-0001`,
    ledger_type: type,
    maintenance_cycle: type === 'inspection' ? '' : 'week',
    executed_date: '2026-09-10', status: 'draft',
    executor_names: '王五', items_count: 3,
    abnormal_count: 2, created_by_name: 'op1', created_at: '2026-09-11 09:00',
  };
}

function renderIndex(Component) {
  return act(async () => {
    ReactDOM.render(h(Component), container);
  });
}

describe('巡检台账（历史）只读', () => {
  const entriesModule = require('../entries');

  test('页面标题为巡检台账（历史），历史查询仍调用 ledgers/ 接口并带 ledger_type=inspection', async () => {
    mockHttpGet.mockResolvedValue({data: [draftLedgerRow('inspection')], total: 1, page: 1, page_size: 20});
    await renderIndex(entriesModule.InspectionLedgerIndex);
    await act(async () => {});
    expect(container.textContent).toContain('巡检台账（历史）');
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/ledgers/'));
    expect(call).toBeTruthy();
    expect(call[1].params.ledger_type).toBe('inspection');
  });

  test('历史列表不显示新增/编辑/提交/作废等写操作，仅保留详情与导出', async () => {
    mockHttpGet.mockResolvedValue({data: [draftLedgerRow('inspection')], total: 1, page: 1, page_size: 20});
    await renderIndex(entriesModule.InspectionLedgerIndex);
    await act(async () => {});
    expect(container.textContent).not.toContain('新增巡检台账');
    expect(container.textContent).not.toContain('编辑');
    expect(container.textContent).not.toContain('提交');
    expect(container.textContent).not.toContain('作废');
    expect(container.textContent).toContain('详情');
    expect(container.textContent).toContain('导出');
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  test('周月维护台账仍显示对应写操作（草稿可编辑/提交/作废）', async () => {
    mockHttpGet.mockResolvedValue({data: [draftLedgerRow('week_month')], total: 1, page: 1, page_size: 20});
    await renderIndex(entriesModule.WeekMonthLedgerIndex);
    await act(async () => {});
    expect(container.textContent).toContain('新增周月维护台账');
    expect(container.textContent).toContain('编辑');
    expect(container.textContent).toContain('提交');
    expect(container.textContent).toContain('作废');
  });
});

describe('台账详情抽屉的转单操作', () => {
  const LedgerDetail = require('../LedgerDetail').default;
  const {getLedgerStore} = require('../store');

  async function renderDetail(ledgerType, items, extra = {}) {
    const store = getLedgerStore(ledgerType);
    store.detail = {
      id: 1, ledger_no: 'EL-X-20260910-0001', ledger_type: ledgerType,
      maintenance_cycle: ledgerType === 'inspection' ? '' : 'week',
      status: 'submitted', executed_date: '2026-09-10',
      items, corrections: [],
      ...extra,
    };
    store.detailVisible = true;
    act(() => {
      ReactDOM.render(h(LedgerDetail, {store}), container);
    });
    await act(flush);
    await act(flush);
    // "检查明细"为非激活页签（antd Tabs 懒渲染），切过去让明细表挂载
    const itemsTab = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .find(t => t.textContent.includes('检查明细'));
    if (itemsTab) {
      act(() => {
        Simulate.click(itemsTab);
      });
      await act(flush);
      await act(flush);
    }
    return store;
  }

  const abnormalItem = (disposition) => ({
    id: 11, system: 5, system_name: '通信系统A', item_name: '电源电压测量',
    input_type: 'number', value_number: 50, unit: 'V',
    result: 'abnormal', abnormal_desc: '电压偏低', disposition,
  });

  test('巡检台账（历史）详情：异常明细不显示转故障/转工单操作', async () => {
    await renderDetail('inspection', [abnormalItem(null)]);
    const text = document.body.textContent;  // Drawer 渲染到 body
    expect(text).not.toContain('转故障');
    expect(text).not.toContain('转工单');
    // 处置状态标签仍展示（历史事实）
    expect(text).toContain('未处置');
  });

  test('巡检台账（历史）详情：改造前已转故障的明细仍可跳转查看处置目标', async () => {
    await renderDetail('inspection', [abnormalItem({
      status: 'converted_fault',
      fault: {id: 3, fault_no: 'GZ20260910-0001'},
    })]);
    const text = document.body.textContent;  // Drawer 渲染到 body
    // "已转故障"标签本身包含"转故障"子串，剔除后再断言无转单操作入口
    expect(text.split('已转故障').join('')).not.toContain('转故障');
    expect(text).toContain('已转故障');
    expect(text).toContain('GZ20260910-0001');
  });

  test('周月维护台账详情：异常明细仍显示转故障/转工单操作', async () => {
    await renderDetail('week_month', [abnormalItem(null)]);
    const text = document.body.textContent;  // Drawer 渲染到 body
    expect(text).toContain('转故障');
    expect(text).toContain('转工单');
  });
});

describe('新巡检异常转单接口契约', () => {
  // 新巡检链路保持独立：只能走 inspection-sheets/.../convert-* 独立接口
  const inspectionStore = require('../../inspection/store').default;

  test('convertToFault 调用 inspection-sheets 转故障接口（不调用旧 ledgers 接口）', async () => {
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      inspectionStore.convertToFault(9, 7, {system: 5});
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/inspection-sheets/9/records/7/convert-to-fault/',
      {system: 5});
    expect(mockHttpPost.mock.calls.some(c => c[0].includes('/ledgers/'))).toBe(false);
  });

  test('convertToWorkOrder 调用 inspection-sheets 转工单接口', async () => {
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      inspectionStore.convertToWorkOrder(9, 7, {system: 5, client_token: 't1'});
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/inspection-sheets/9/records/7/convert-to-work-order/',
      {system: 5, client_token: 't1'});
    expect(mockHttpPost.mock.calls.some(c => c[0].includes('/ledgers/'))).toBe(false);
  });
});
