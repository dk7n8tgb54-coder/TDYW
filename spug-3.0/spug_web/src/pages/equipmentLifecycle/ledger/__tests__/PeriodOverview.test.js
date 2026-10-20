/**
 * 本期工作概览与周期分组视图（2026-10-14）页面行为测试。
 *
 * 真实渲染（ReactDOM + jsdom）+ mock libs.http，验证：
 * - LedgerPeriodOverviewCard（2026-10-20 布局改版+同日视觉密度压缩）：拉取
 *   /ledgers/period-overview/（携带台账类型），渲染 本周/本月（或本航季）
 *   两行结构卡片：第一行周期名称与短日期（每周 M.D—M.D，跨年带年份；
 *   每月 YYYY年M月），第二行固定顺序应填/待生成/待填写/已完成；宽屏两卡
 *   并排（flex 换行布局，区块间距 8px、卡内边距 4/12/5、统计数字 16px），
 *   零值淡化，待生成/待填写非零突出，已作废/需处理非零才显示（需处理带
 *   警示图标）；无数据时不渲染占位；
 * - LedgerGroupTable（2026-10-20 单表头改版）：整表只有一套台账记录列表头，
 *   周期作为分组行以 colSpan 贯通整行（本期徽标 + 期次 + 台账数/草稿/
 *   已完成/已作废统计），展开后直接铺该周期台账记录，不再出现子表表头；
 *   默认只展开本期组（is_current），历史期次折叠；分组行点击或行首展开
 *   按钮独立切换各周期，展开状态持久化（localStorage）；分页切换携带
 *   page 参数重新请求；
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
       expected: 3, to_generate: 2, drafting: 1, completed: 0,
       voided: 0, attention: 0},
      {key: 'month', title: '本月', maintenance_period: '2026-10',
       period_label: '每月｜2026年10月',
       period_start: '2026-10-01', period_end: '2026-10-31',
       expected: 12, to_generate: 0, drafting: 4, completed: 1234,
       voided: 2, attention: 1},
    ],
    unconfigured_templates: 2,
  },
};

const CROSS_YEAR_PAYLOAD = {
  data: {
    ledger_type: 'week_month', base_date: '2025-12-30',
    blocks: [
      {key: 'week', title: '本周', maintenance_period: '2025-12-29',
       period_label: '每周｜2025-12-29 ~ 2026-01-04',
       period_start: '2025-12-29', period_end: '2026-01-04',
       expected: 1, to_generate: 0, drafting: 0, completed: 0,
       voided: 0, attention: 0},
      {key: 'month', title: '本月', maintenance_period: '2025-12',
       period_label: '每月｜2025年12月',
       period_start: '2025-12-01', period_end: '2025-12-31',
       expected: 0, to_generate: 0, drafting: 0, completed: 0,
       voided: 0, attention: 0},
    ],
    unconfigured_templates: 0,
  },
};

const SEASON_PAYLOAD = {
  data: {
    ledger_type: 'seasonal', base_date: '2026-10-14',
    blocks: [
      {key: 'season', title: '本航季', maintenance_period: '2026-夏秋',
       period_label: '2026年夏秋季（2026-03-29 ~ 2026-10-25）',
       period_start: '2026-03-29', period_end: '2026-10-25',
       expected: 2, to_generate: 1, drafting: 0, completed: 1,
       voided: 0, attention: 0},
    ],
    unconfigured_templates: 0,
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
  function renderOverview(payload) {
    mockHttpGet.mockResolvedValue(payload);
    const store = new LedgerStore('week_month');
    return store.fetchOverview().then(() => {
      render(h(OverviewCard, {store}));
      return container.querySelector('[data-testid="period-overview"]');
    });
  }

  test('拉取概览（携带台账类型）并渲染两行结构与待配置提示', async () => {
    const card = await renderOverview(OVERVIEW_PAYLOAD);
    expect(card).toBeTruthy();
    // 第一行：周期名称 · 日期（删除"每周｜/每月｜"前缀与重复日期）
    expect(card.textContent).toContain('本周 · 10.12—10.18');
    expect(card.textContent).toContain('本月 · 2026年10月');
    expect(card.textContent).not.toContain('每周｜');
    expect(card.textContent).not.toContain('每月｜');
    // 第二行固定顺序：应填 → 待生成 → 待填写 → 已完成
    const weekCard = container.querySelector('[data-testid="overview-block-week"]');
    const order = ['应填', '待生成', '待填写', '已完成']
      .map(text => weekCard.textContent.indexOf(text));
    expect(order.every(pos => pos >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    // 零值的已作废/需处理整项隐藏（周卡两项均为 0）
    expect(weekCard.textContent).not.toContain('已作废');
    expect(weekCard.textContent).not.toContain('需处理');
    // 待配置模板提示保留
    expect(card.textContent).toContain('另有 2 个模板待配置');
    expect(container.querySelectorAll('[data-testid^="overview-block-"]')).toHaveLength(2);
  });

  test('两卡并排布局：flex 换行容器 + 8px 间距 + 弹性基准断点，紧凑卡体不截断数字', async () => {
    const card = await renderOverview(OVERVIEW_PAYLOAD);
    const row = card.firstChild;
    expect(row.style.display).toBe('flex');
    expect(row.style.flexWrap).toBe('wrap');
    expect(row.style.gap).toBe('8px');
    // 2026-10-20 视觉密度压缩：区块间距 8px、卡内边距 4/12/5、统计数字 16px
    expect(card.style.marginBottom).toBe('8px');
    const weekCard = container.querySelector('[data-testid="overview-block-week"]');
    expect(weekCard.style.flex).toBe('1 1 380px');
    expect(weekCard.style.minWidth).toBe('0');
    expect(weekCard.style.padding).toBe('4px 12px 5px');
    const weekDrafting = container.querySelector('[data-testid="overview-count-week-drafting"]');
    expect(weekDrafting.style.fontSize).toBe('16px');
    // 统计项整体换行（数字与名称不拆开），关键数字完整渲染不截断
    const completed = container.querySelector('[data-testid="overview-count-month-completed"]');
    expect(completed.parentElement.style.whiteSpace).toBe('nowrap');
    expect(completed.textContent).toBe('1234');
  });

  test('突出规则：待生成/待填写非零主题蓝、零值淡化；需处理非零橙色带警示图标', async () => {
    await renderOverview(OVERVIEW_PAYLOAD);
    const numColor = (scope, key) =>
      container.querySelector(`[data-testid="overview-count-${scope}-${key}"]`).style.color;
    // 周卡：待生成/待填写非零突出，应填普通，已完成零值淡化
    expect(numColor('week', 'to_generate')).toBe('rgb(24, 144, 255)');
    expect(numColor('week', 'drafting')).toBe('rgb(24, 144, 255)');
    expect(numColor('week', 'expected')).toBe('rgb(51, 51, 51)');
    expect(numColor('week', 'completed')).toBe('rgb(191, 191, 191)');
    // 月卡：待生成为零同样淡化；已作废非零显示（普通色），需处理橙色
    expect(numColor('month', 'to_generate')).toBe('rgb(191, 191, 191)');
    expect(numColor('month', 'completed')).toBe('rgb(51, 51, 51)');
    const attention = container.querySelector('[data-testid="overview-count-month-attention"]');
    expect(attention.style.color).toBe('rgb(250, 140, 22)');
    expect(attention.parentElement.querySelector('.anticon-warning')).toBeTruthy();
    // 周卡零值的已作废/需处理不渲染节点
    expect(container.querySelector('[data-testid="overview-count-week-voided"]')).toBeNull();
    expect(container.querySelector('[data-testid="overview-count-week-attention"]')).toBeNull();
  });

  test('跨年周期次日期两端带年份；季维护沿用后端完整期次标签', async () => {
    const crossCard = await renderOverview(CROSS_YEAR_PAYLOAD);
    expect(crossCard.textContent).toContain('本周 · 2025.12.29—2026.01.04');
    expect(crossCard.textContent).toContain('本月 · 2025年12月');
    const seasonStore = new LedgerStore('seasonal');
    mockHttpGet.mockResolvedValue(SEASON_PAYLOAD);
    await seasonStore.fetchOverview();
    render(h(OverviewCard, {store: seasonStore}));
    const seasonCard = container.querySelector('[data-testid="period-overview"]');
    expect(seasonCard.textContent).toContain(
      '本航季 · 2026年夏秋季（2026-03-29 ~ 2026-10-25）');
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

// —— LedgerGroupTable 周期分组表（2026-10-20 单表头改版）共用辅助 ——
const groupColumns = buildColumns(new LedgerStore('week_month'), 'week_month', () => {});

function renderTable(store) {
  render(h(LedgerGroupTable, {store, columns: groupColumns}));
}

function groupRow(text) {
  return Array.from(container.querySelectorAll('[data-testid="period-group-row"]'))
    .find(tr => tr.textContent.includes(text));
}

function caretOf(text) {
  const row = groupRow(text);
  expect(row).toBeTruthy();
  return row.querySelector('[data-testid="period-group-caret"]');
}

function headerTexts() {
  return Array.from(container.querySelectorAll('thead th')).map(th => th.textContent);
}

describe('LedgerGroupTable 周期分组单表头与展开', () => {
  test('默认只展开本期组：本期记录直接铺在分组行下，历史期次折叠', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    // 整表只有一套列标题（台账记录列），不存在旧的分组表头
    expect(container.querySelectorAll('thead')).toHaveLength(1);
    expect(headerTexts()).toEqual(['模板名称', '系统', '期次', '状态', '台账编号', '操作']);
    // 本期分组行可见（本期徽标 + 完整期次），组内记录行紧随其后
    expect(container.textContent).toContain('本期');
    expect(container.textContent).toContain('每周｜2026-10-12 ~ 2026-10-18');
    expect(rowByNo('EL-WM-20261012-0001')).toBeTruthy();
    expect(rowByNo('EL-WM-20261012-0002')).toBeTruthy();
    // 历史组未展开：仅分组行，组内记录不可见
    expect(rowByNo('EL-WM-20260910-0001')).toBeFalsy();
  });

  test('表头只出现一次：多个周期同时展开时不再重复渲染子表表头', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    // 展开历史组（本期默认已展开）
    await act(async () => {
      caretOf('每月｜2026年9月').click();
    });
    await act(flush);
    expect(rowByNo('EL-WM-20261012-0001')).toBeTruthy();
    expect(rowByNo('EL-WM-20260910-0001')).toBeTruthy();
    // 两组同时展开：仍然只有一套表头
    expect(container.querySelectorAll('thead')).toHaveLength(1);
    expect(headerTexts()).toEqual(['模板名称', '系统', '期次', '状态', '台账编号', '操作']);
    // 分组行由首列单元格贯通（colSpan），行内无子表、无多余单元格
    container.querySelectorAll('[data-testid="period-group-row"]').forEach(tr => {
      expect(tr.querySelectorAll('td')).toHaveLength(1);
      expect(tr.querySelector('table')).toBeNull();
    });
  });

  test('周期行保留台账数/草稿/已完成/已作废统计，收起后仍在', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    const countsText = text => groupRow(text)
      .querySelector('[data-testid="period-group-counts"]')
      .textContent.replace(/\s/g, '');
    // 本期组：2 台账 / 2 草稿 / 0 已完成 / 0 已作废
    expect(countsText('每周｜2026-10-12 ~ 2026-10-18')).toContain('2台账数');
    expect(countsText('每周｜2026-10-12 ~ 2026-10-18')).toContain('2草稿');
    expect(countsText('每周｜2026-10-12 ~ 2026-10-18')).toContain('0已完成');
    expect(countsText('每周｜2026-10-12 ~ 2026-10-18')).toContain('0已作废');
    // 历史组：1 台账 / 0 草稿 / 1 已完成 / 0 已作废
    expect(countsText('每月｜2026年9月')).toContain('1台账数');
    expect(countsText('每月｜2026年9月')).toContain('1已完成');
    // 收起本期组：记录隐藏，统计保留
    await act(async () => {
      caretOf('每周｜2026-10-12 ~ 2026-10-18').click();
    });
    await act(flush);
    expect(rowByNo('EL-WM-20261012-0001')).toBeFalsy();
    expect(countsText('每周｜2026-10-12 ~ 2026-10-18')).toContain('2台账数');
    expect(countsText('每周｜2026-10-12 ~ 2026-10-18')).toContain('2草稿');
  });

  test('行首展开按钮切换：展开历史组持久化，再点收起且不影响本期组', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    expect(caretOf('每月｜2026年9月').getAttribute('aria-expanded')).toBe('false');
    await act(async () => {
      caretOf('每月｜2026年9月').click();
    });
    await act(flush);
    expect(store.expandedPeriodKeys).toContain('2026-09');
    expect(rowByNo('EL-WM-20260910-0001')).toBeTruthy();
    expect(caretOf('每月｜2026年9月').getAttribute('aria-expanded')).toBe('true');
    // 持久化：新 store（模拟刷新）首次拉取分组时恢复展开状态
    const reloaded = new LedgerStore('week_month');
    await reloaded.fetchGroups();
    expect(reloaded.expandedPeriodKeys).toContain('2026-09');
    // 再次点击收起：各周期独立，本期组记录不受影响
    await act(async () => {
      caretOf('每月｜2026年9月').click();
    });
    await act(flush);
    expect(store.expandedPeriodKeys).not.toContain('2026-09');
    expect(rowByNo('EL-WM-20260910-0001')).toBeFalsy();
    expect(rowByNo('EL-WM-20261012-0001')).toBeTruthy();
    const reloaded2 = new LedgerStore('week_month');
    await reloaded2.fetchGroups();
    expect(reloaded2.expandedPeriodKeys).not.toContain('2026-09');
  });

  test('点击分组行任意区域同样切换展开', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    await act(async () => {
      groupRow('每月｜2026年9月').click();
    });
    await act(flush);
    expect(store.expandedPeriodKeys).toContain('2026-09');
    expect(rowByNo('EL-WM-20260910-0001')).toBeTruthy();
  });
});

describe('LedgerGroupTable 周期行统计与分页布局', () => {
  test('展开组内超过分页 pageSize 的台账记录全部渲染（不被本地切片截断）', async () => {
    // 分页是服务端周期组切片；平铺行内置分页会按 pageSize 对 dataSource
    // 本地切片，把展开的记录行截断（实机 2026-10-20 发现的缺陷回归）
    const bigGroup = {
      maintenance_period: '2026-10', period_text: '每月｜2026年10月',
      is_current: true, total: 8, draft: 8, completed: 0, void: 0,
      ledgers: Array.from({length: 8}, (_, i) => ({
        id: 100 + i,
        ledger_no: `EL-WM-20261001-${String(i + 1).padStart(4, '0')}`,
        ledger_type: 'week_month', status: 'draft', system_name: `系统${i + 1}`,
        created_from: 'manual', source_type: 'manual',
        period_label: '每月｜2026年10月', period_is_derived: false,
        period_source_text: '',
      })),
    };
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD([bigGroup]));
    const store = new LedgerStore('week_month');
    store.groupsPageSize = 6;
    await store.fetchGroups();
    renderTable(store);
    for (let i = 1; i <= 8; i += 1) {
      expect(rowByNo(`EL-WM-20261001-${String(i).padStart(4, '0')}`)).toBeTruthy();
    }
    // 当前页只有 1 个分组行，分页器显示服务端总数
    expect(container.querySelectorAll('[data-testid="period-group-row"]')).toHaveLength(1);
    expect(container.querySelector('.ant-pagination-total-text').textContent)
      .toContain('共 1 个周期分组');
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

  test('单表固定布局：scroll.x 与列宽总和一致，操作列固定右侧，无内嵌展开表', async () => {
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD(GROUPS));
    const store = new LedgerStore('week_month');
    await store.fetchGroups();
    renderTable(store);
    // 旧版内嵌展开行已整体移除
    expect(container.querySelector('.ant-table-expanded-row')).toBeNull();
    const table = container.querySelector('table');
    // antd 对数字 scroll.x 生成固定布局：table 内联宽度 = 列宽总和，
    // 窄屏容器出现横向滚动条时 fixed right 列保持可见
    expect(table.style.tableLayout).toBe('fixed');
    expect(table.style.width).toBe('990px');
    const headers = Array.from(table.querySelectorAll('thead th'));
    expect(headers[headers.length - 1].textContent).toBe('操作');
    expect(headers[headers.length - 1].className).toContain('ant-table-cell-fix-right');
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
