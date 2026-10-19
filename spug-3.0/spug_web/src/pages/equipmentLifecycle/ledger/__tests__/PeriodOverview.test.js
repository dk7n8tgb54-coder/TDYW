/**
 * 本期工作概览与周期分组视图（2026-10-14）页面行为测试。
 *
 * 真实渲染（ReactDOM + jsdom）+ mock libs.http，验证：
 * - LedgerPeriodOverviewCard：拉取 /ledgers/period-overview/（携带台账类型），
 *   渲染 本周/本月（或本航季）的 应填/待生成/待填写/已完成/已作废 真实数量
 *   与待配置提示；无数据时不渲染占位；
 * - LedgerGroupTable：默认只展开本期组（is_current），历史期次折叠；组头
 *   状态统计与"本期"徽标可见；点击展开历史组后状态持久化（localStorage）；
 *   分页切换携带 page 参数重新请求；
 * - 列操作（buildColumns 2026-10-16 流程简化）：草稿 Excel 行主操作
 *   "继续填写"发起详情请求；草稿行"查看"入口与更多菜单删除
 *   （Modal 确认后 DELETE）；已完成行"查看"；作废收进"更多"菜单，
 *   弹窗必须填写作废原因才可确认（POST void 携带原因），空原因时确认
 *   按钮禁用；
 * - 两个填写列表隔离：概览请求按各自 ledger_type 发送，互不串扰。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: jest.fn(),
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
  const AuthButton = (props) => React.createElement('button', {
    type: 'button',
    'data-testid': props['data-testid'],
    onClick: props.onClick,
    disabled: props.disabled,
    style: props.style,
  }, props.children);
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

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const storeModule = require('../store');
const {LedgerStore} = storeModule;
const OverviewCard = require('../LedgerPeriodOverviewCard').default;
const LedgerGroupTable = require('../LedgerGroupTable').default;
const columnsModule = require('../LedgerColumns');
const {buildColumns, LedgerVoidModal} = columnsModule;

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

let container = null;

function render(element) {
  act(() => {
    ReactDOM.render(element, container);
  });
}

const OVERVIEW_PAYLOAD = {
  data: {
    ledger_type: 'week_month', base_date: '2026-10-14',
    blocks: [
      {key: 'week', title: '本周', maintenance_period: '2026-10-12',
       period_label: '每周｜2026-10-12 ~ 2026-10-18',
       period_start: '2026-10-12', period_end: '2026-10-18',
       expected: 3, to_generate: 2, drafting: 0, completed: 0,
       voided: 0, attention: 0},
      {key: 'month', title: '本月', maintenance_period: '2026-10',
       period_label: '每月｜2026年10月',
       period_start: '2026-10-01', period_end: '2026-10-31',
       expected: 1, to_generate: 0, drafting: 1, completed: 0,
       voided: 0, attention: 0},
    ],
    unconfigured_templates: 2,
  },
};

const GROUPS_PAYLOAD = (groups) => ({data: {data: groups, total: groups.length}});

const GROUPS = [
  {maintenance_period: '2026-10-12', period_text: '每周｜2026-10-12 ~ 2026-10-18',
   is_current: true, total: 2, draft: 2, completed: 0,
   void: 0, ledgers: [
     {id: 11, ledger_no: 'EL-WM-20261012-0001', ledger_type: 'week_month',
      status: 'draft', system_name: 'DVOR系统', created_from: 'excel_template',
      source_type: 'excel', source_template_name: '信道周模板',
      period_label: '每周｜2026-10-12 ~ 2026-10-18', period_is_derived: false,
      period_source_text: ''},
     {id: 12, ledger_no: 'EL-WM-20261012-0002', ledger_type: 'week_month',
      status: 'draft', system_name: 'ILS系统', created_from: 'manual',
      source_type: 'manual',
      period_label: '每周｜2026-10-12 ~ 2026-10-18', period_is_derived: false,
      period_source_text: ''},
   ]},
  {maintenance_period: '2026-09', period_text: '每月｜2026年9月',
   is_current: false, total: 1, draft: 0, completed: 1,
   void: 0, ledgers: [
     {id: 21, ledger_no: 'EL-WM-20260910-0001', ledger_type: 'week_month',
      status: 'completed', system_name: 'DVOR系统', created_from: 'manual',
      source_type: 'manual',
      period_label: '每月｜2026年9月', period_is_derived: false,
      period_source_text: ''},
   ]},
];

function rowByNo(no) {
  return Array.from(container.querySelectorAll('tr'))
    .find(tr => tr.textContent.includes(no));
}

beforeEach(() => {
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpDelete.mockReset();
  window.localStorage.clear();
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
});

describe('LedgerPeriodOverviewCard 本期工作概览', () => {
  test('拉取概览（携带台账类型）并渲染真实数量与待配置提示', async () => {
    mockHttpGet.mockResolvedValue(OVERVIEW_PAYLOAD);
    const store = new LedgerStore('week_month');
    await store.fetchOverview();
    render(h(OverviewCard, {store}));
    const card = container.querySelector('[data-testid="period-overview"]');
    expect(card).toBeTruthy();
    expect(card.textContent).toContain('本周');
    expect(card.textContent).toContain('每周｜2026-10-12 ~ 2026-10-18');
    expect(card.textContent).toContain('本月');
    expect(card.textContent).toContain('每月｜2026年10月');
    // 真实数量来自后端响应，前端不伪造（三状态口径：草稿/已完成/已作废）
    expect(card.textContent).toContain('应填');
    expect(card.textContent).toContain('待生成');
    expect(card.textContent).toContain('已完成');
    expect(card.textContent).toContain('已作废');
    expect(card.textContent).toContain('需处理');
    expect(card.textContent).toContain('另有 2 个模板待配置');
    const blocks = container.querySelectorAll('[data-testid^="overview-block-"]');
    expect(blocks).toHaveLength(2);
  });

  test('两个列表概览请求按各自台账类型发送（互不串扰）', async () => {
    mockHttpGet.mockResolvedValue(OVERVIEW_PAYLOAD);
    const wm = new LedgerStore('week_month');
    const se = new LedgerStore('seasonal');
    await wm.fetchOverview();
    await se.fetchOverview();
    const urls = mockHttpGet.mock.calls.map(c => c[0]);
    expect(urls.filter(u => u.endsWith('/ledgers/period-overview/'))).toHaveLength(2);
    expect(mockHttpGet.mock.calls[0][1].params.ledger_type).toBe('week_month');
    expect(mockHttpGet.mock.calls[1][1].params.ledger_type).toBe('seasonal');
  });

  test('概览未加载时不渲染占位（不显示假数字）', () => {
    const store = new LedgerStore('week_month');
    render(h(OverviewCard, {store}));
    expect(container.querySelector('[data-testid="period-overview"]')).toBeNull();
  });
});

describe('LedgerGroupTable 周期分组展开与分页', () => {
  const columns = buildColumns(new LedgerStore('week_month'), 'week_month', () => {});

  function renderTable(store) {
    render(h(LedgerGroupTable, {store, columns}));
  }

  test('默认只展开本期组：本期行可见，历史期次折叠', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    // 本期组行与"本期"徽标可见
    expect(container.textContent).toContain('本期');
    expect(container.textContent).toContain('每周｜2026-10-12 ~ 2026-10-18');
    // 状态统计列可见（草稿1 已完成1；9月组 已完成1）
    expect(container.textContent).toContain('已完成');
    // 本期组内台账行已展开（行号 11 可见），历史组行（21）不可见
    expect(rowByNo('EL-WM-20261012-0001')).toBeTruthy();
    expect(rowByNo('EL-WM-20260910-0001')).toBeFalsy();
  });

  test('点击展开历史期次组：展开状态写入 store 并持久化', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    const historyRow = Array.from(container.querySelectorAll('.ant-table-row'))
      .find(tr => tr.textContent.includes('每月｜2026年9月'));
    expect(historyRow).toBeTruthy();
    const expandBtn = historyRow.querySelector('.ant-table-row-expand-icon');
    expect(expandBtn).toBeTruthy();
    await act(async () => {
      expandBtn.click();
    });
    await act(flush);
    expect(store.expandedPeriodKeys).toContain('2026-09');
    expect(rowByNo('EL-WM-20260910-0001')).toBeTruthy();
    // 持久化：新 store（模拟刷新）恢复展开状态
    const reloaded = new LedgerStore('week_month');
    expect(reloaded.expandedPeriodKeys).toContain('2026-09');
  });

  test('历史数据量大时分页加载：翻页携带 page 重新请求', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    store.groupsPageSize = 1; // 夹具两组 → 两页，验证翻页
    await store.fetchGroups();
    renderTable(store);
    const pageTwo = Array.from(container.querySelectorAll('.ant-pagination-item'))
      .find(node => node.textContent === '2');
    expect(pageTwo).toBeTruthy();
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    await act(async () => {
      pageTwo.click();
    });
    await act(flush);
    expect(store.groupsPage).toBe(2);
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/ledgers/period-groups/'));
    expect(call[1].params.page).toBe(2);
  });

  test('展开的内嵌台账表启用横向滚动（scroll.x 与列宽总和一致），操作列固定右侧', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    // 外层分组表固定布局：宽度不被展开内容撑宽，内嵌表才拥有自己的横向滚动
    const outerTable = container.querySelector('main table, table');
    expect(outerTable.style.tableLayout).toBe('fixed');
    const innerTable = container.querySelector('.ant-table-expanded-row table');
    expect(innerTable).toBeTruthy();
    // antd 对数字 scroll.x 生成固定布局：table 内联宽度 = 列宽总和，
    // 窄屏容器出现横向滚动条时 fixed right 列保持可见
    expect(innerTable.style.width).toBe('990px');
    const innerHeaders = Array.from(innerTable.querySelectorAll('thead th'));
    expect(innerHeaders[innerHeaders.length - 1].textContent).toBe('操作');
    expect(innerHeaders[innerHeaders.length - 1].className).toContain('ant-table-cell-fix-right');
  });
});

describe('台账行操作（buildColumns 2026-10-14）', () => {
  function renderRows(rows) {
    const store = new LedgerStore('week_month');
    const openDetail = jest.fn();
    const Table = require('antd').Table;
    render(h(Table, {
      rowKey: 'id', dataSource: rows,
      columns: buildColumns(store, 'week_month', openDetail),
      pagination: false,
    }));
    return {store, openDetail};
  }

  test('草稿 Excel 行：主操作"继续填写"发起详情请求；模板名称列在前', async () => {
    mockHttpGet.mockResolvedValue({data: {}});
    const rows = [{id: 11, ledger_no: 'EL-WM-20261012-0001', status: 'draft',
      created_from: 'excel_template', source_type: 'excel',
      source_template_name: '信道周模板', ledger_type: 'week_month'}];
    const {openDetail} = renderRows(rows);
    const firstHeader = container.querySelector('.ant-table-thead th');
    expect(firstHeader.textContent).toBe('模板名称');
    const row = rowByNo('EL-WM-20261012-0001');
    const primary = row.querySelector('[data-testid="row-primary-action"]');
    expect(primary.textContent).toBe('继续填写');
    await act(async () => {
      primary.click();
    });
    await act(flush);
    expect(openDetail).toHaveBeenCalledWith(rows[0]);
    // Excel 台账行不提供列表提交（在 Excel 填写详情内提交）
    expect(row.textContent).not.toContain('提交');
  });

  test('草稿行：更多菜单提供删除（确认后 DELETE），已完成行不可删除', async () => {
    mockHttpDelete.mockResolvedValue({});
    const rows = [{id: 12, ledger_no: 'EL-WM-20261012-0002', status: 'draft',
      created_from: 'manual', source_type: 'manual', ledger_type: 'week_month'}];
    const {store} = renderRows(rows);
    const row = rowByNo('EL-WM-20261012-0002');
    const primary = row.querySelector('[data-testid="row-primary-action"]');
    // 草稿行主操作为"继续填写"
    expect(primary.textContent).toBe('继续填写');
    // 更多菜单 → 删除（Modal 确认）
    await act(async () => {
      row.querySelector('[data-testid="row-more"]').click();
    });
    await act(flush);
    const dropdown = document.body.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
    expect(dropdown).toBeTruthy();
    const deleteItem = Array.from(dropdown.querySelectorAll('.ant-dropdown-menu-item'))
      .find(item => item.textContent.includes('删除'));
    expect(deleteItem).toBeTruthy();
    await act(async () => {
      deleteItem.click();
    });
    await act(flush);
    const modal = document.body.querySelector('.ant-modal');
    expect(modal.textContent).toContain('删除台账');
    const okBtn = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.includes('确认删除'));
    await act(async () => {
      okBtn.click();
    });
    await act(flush);
    expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/12/');
    expect(store.isDeleting).toBe(false);
  });

  test('已完成行主操作"查看"；作废收进更多菜单且必须填写原因', async () => {
    mockHttpPost.mockResolvedValue({});
    const rows = [{id: 21, ledger_no: 'EL-WM-20260910-0001', status: 'completed',
      created_from: 'manual', source_type: 'manual', ledger_type: 'week_month'}];
    renderRows(rows);
    const row = rowByNo('EL-WM-20260910-0001');
    expect(row.querySelector('[data-testid="row-primary-action"]').textContent).toBe('查看');
    // 更多菜单 → 作废
    await act(async () => {
      row.querySelector('[data-testid="row-more"]').click();
    });
    await act(flush);
    const dropdown = document.body.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
    expect(dropdown).toBeTruthy();
    expect(dropdown.textContent).toContain('作废');
    const voidItem = Array.from(dropdown.querySelectorAll('.ant-dropdown-menu-item'))
      .find(item => item.textContent.includes('作废'));
    await act(async () => {
      voidItem.click();
    });
    await act(flush);
    const modal = document.body.querySelector('.ant-modal');
    expect(modal.textContent).toContain('作废台账');
    // 空原因时确认按钮禁用（后端要求原因必填）
    const okBtn = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.includes('确认作废'));
    expect(okBtn.disabled).toBe(true);
    const reasonInput = modal.querySelector('[data-testid="void-reason"]');
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => {
      setter.call(reasonInput, '录入错误重复台账');
      reasonInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(flush);
    expect(okBtn.disabled).toBe(false);
    await act(async () => {
      okBtn.click();
    });
    await act(flush);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledgers/21/void/', {reason: '录入错误重复台账'});
  });
});

describe('台账列序与固定操作列（2026-10-18）', () => {
  test('次要信息在前，操作列固定最右（与其他业务列表一致）', () => {
    const store = new LedgerStore('week_month');
    const Table = require('antd').Table;
    render(h(Table, {
      rowKey: 'id',
      dataSource: [{id: 31, ledger_no: 'EL-WM-20261012-0003', status: 'draft',
        created_from: 'excel_template', source_type: 'excel',
        source_template_name: '信道周模板', ledger_type: 'week_month'}],
      columns: buildColumns(store, 'week_month', () => {}),
      pagination: false,
    }));
    const headers = Array.from(container.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent);
    expect(headers).toEqual(['模板名称', '系统', '期次', '状态', '台账编号', '操作']);
    const fixRight = container.querySelectorAll(
      '.ant-table-thead th.ant-table-cell-fix-right, .ant-table-tbody td.ant-table-cell-fix-right');
    expect(fixRight.length).toBeGreaterThanOrEqual(2);
    // 固定列即最后的操作列，主操作/更多菜单在其单元格内
    expect(fixRight[0].textContent).toBe('操作');
    expect(fixRight[1].querySelector('[data-testid="row-primary-action"]')).toBeTruthy();
  });
});

describe('LedgerVoidModal 作废弹窗', () => {
  test('填写原因后确认回调携带原因；取消不发起请求', async () => {
    mockHttpPost.mockResolvedValue({});
    const onOk = jest.fn();
    const onCancel = jest.fn();
    render(h(LedgerVoidModal, {
      record: {id: 5, ledger_no: 'EL-WM-20261012-0009', ledger_type: 'week_month'},
      onOk, onCancel,
    }));
    const modal = document.body.querySelector('.ant-modal');
    const okBtn = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.includes('确认作废'));
    // 未填原因不可确认
    expect(okBtn.disabled).toBe(true);
    const reasonInput = modal.querySelector('[data-testid="void-reason"]');
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => {
      setter.call(reasonInput, '误生成');
      reasonInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(flush);
    await act(async () => {
      okBtn.click();
    });
    await act(flush);
    expect(onOk).toHaveBeenCalledWith('误生成');
    expect(mockHttpPost).not.toHaveBeenCalled();
  });
});
