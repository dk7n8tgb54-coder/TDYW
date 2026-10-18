/**
 * 模板组"翻阅台账"（2026-10-18）行为测试。
 *
 * 真实渲染 LedgerGroupBrowse（复用真实 ExcelLedgerDetail + ExcelLedgerStore +
 * LedgerStore），mock libs.http 返回真实响应格式（拦截器剥一层后的
 * {data: ...} 形态），覆盖：
 * - 翻阅上下文：顶栏显示模板名称/当前期次/状态/第几张共几张；首张"上一张"
 *   与末张"下一张"正确禁用；
 * - 上一张/下一张：跨清单移动并按条目拉取对应详情；每张台账用创建时固定
 *   版本快照展示（v1/v2 不随模板当前版本漂移）；
 * - 范围：openBrowse 携带进入时模板视图筛选（编号/状态/日期），后端一次性
 *   返回全量清单（不受组内列表 20 条分页限制），空范围给出空态；
 * - 未保存拦截：草稿有未保存修改时切换先确认，"继续填写"保留当前内容与
 *   位置，"放弃修改并继续"才切换；只读台账直接翻阅；
 * - 期次跳转：归并同期条目（含张数），跳到该期次第一张；
 * - 退出翻阅：清空翻阅状态并按进入层级刷新列表。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

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
  exportFile: jest.fn(),
  history: {location: {search: ''}, replace: jest.fn(), push: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
}));

// 翻阅组件内部自建 ExcelLedgerStore（useState）：用真实类的跟踪子类捕获
// 实例，未保存拦截测试经由该实例驱动真实脏值跟踪行为
const mockCreatedExcelStores = [];
jest.mock('../excel/excelLedgerStore', () => {
  const actual = jest.requireActual('../excel/excelLedgerStore');
  class TrackingExcelLedgerStore extends actual.ExcelLedgerStore {
    constructor(...args) {
      super(...args);
      mockCreatedExcelStores.push(this);
    }
  }
  return Object.assign({}, actual, {ExcelLedgerStore: TrackingExcelLedgerStore});
});

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const {LedgerStore} = require('../store');
const LedgerGroupBrowse = require('../LedgerGroupBrowse').default;

const FIELD_PS = 'aaaaaaaa-1111-4aaa-8aaa-000000000001';

const SHEET = {
  name: '信道维护记录', max_row: 4, max_column: 8, merged_ranges: [],
  row_heights: {}, column_widths: {},
  cells: {A1: {v: '信道维护记录表'}, C3: {v: ''}},
};

function makeEntry(id, overrides = {}) {
  return {
    id,
    ledger_no: `EL-WM-2026-1${id}`,
    status: 'draft',
    executed_date: null,
    maintenance_period: '2026-10-05',
    period_key: '2026-10-05',
    period_label: '每周｜2026-10-05 ~ 2026-10-11',
    period_is_derived: false,
    source_version_no: 1,
    ...overrides,
  };
}

function makeDetail(entry) {
  return {
    id: entry.id,
    ledger_no: entry.ledger_no,
    ledger_type: 'week_month',
    executed_date: entry.executed_date,
    status: entry.status,
    maintenance_period: entry.maintenance_period,
    created_from: 'excel_template',
    excel: {
      values: {},
      editable: entry.status === 'draft',
      version: {
        id: entry.id * 10, version_no: entry.source_version_no,
        template_name: '信道Excel维护台账', ledger_type: 'week_month',
        source_filename: 'channel.xlsx', source_hash: 'a'.repeat(64),
        field_count: 1, published_at: '2026-10-01 09:00:00',
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
        bindings: [{
          field_id: FIELD_PS, sheet_name: '信道维护记录', cell_coordinate: 'C3',
          field_name: 'PS模块', input_type: 'status', is_required: true,
          unit: '', options: ['正常', '异常'],
        }],
      },
    },
  };
}

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

function buttonByText(text, root) {
  const scope = root || document.body;
  return Array.from(scope.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
}

function confirmModalByText(text) {
  return Array.from(document.querySelectorAll('.ant-modal'))
    .find(node => node.textContent.includes(text));
}

function removeModals() {
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask')
    .forEach(node => node.remove());
}

let container;
let store;

const BROWSE_URL = '/api/equipment-lifecycle/ledgers/template-groups/7/browse/';
const GROUPS_LIST_URL = '/api/equipment-lifecycle/ledgers/template-groups/';

/** 组装 3 张台账的翻阅清单：v1/v1/v2 版本快照，前两张同期、第三张另一期次。 */
function makeEntries() {
  return [
    makeEntry(101, {status: 'completed'}),
    makeEntry(102),
    makeEntry(103, {
      maintenance_period: '2026-11-02', period_key: '2026-11-02',
      period_label: '每周｜2026-11-02 ~ 2026-11-08', source_version_no: 2,
    }),
  ];
}

function mockRoutes(entries) {
  mockHttpGet.mockImplementation(url => {
    if (url === BROWSE_URL) {
      return Promise.resolve({data: {
        group_key: '7', template_id: 7, group_name: '信道Excel维护台账',
        ledger_type: 'week_month', total: entries.length, entries,
      }});
    }
    if (url === GROUPS_LIST_URL) {
      return Promise.resolve({data: [], total: 0, page: 1, page_size: 10});
    }
    const entry = entries.find(item => url.endsWith(`/excel-ledgers/${item.id}/`));
    if (entry) return Promise.resolve({data: makeDetail(entry)});
    return Promise.resolve({data: [], total: 0});
  });
}

async function renderBrowse(entries) {
  mockRoutes(entries || makeEntries());
  store = new LedgerStore('week_month');
  await store.openBrowse({group_key: '7', template_name: '信道Excel维护台账'});
  await flush();
  await act(async () => {
    ReactDOM.render(<LedgerGroupBrowse store={store}/>, container);
  });
  await flush();
}

beforeEach(() => {
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  mockCreatedExcelStores.length = 0;
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  removeModals();
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
});

describe('LedgerGroupBrowse 翻阅上下文与导航', () => {
  test('顶栏显示模板/期次/状态/第几张共几张，首张上一张禁用', async () => {
    await renderBrowse();
    const header = document.querySelector('[data-testid="ledger-group-browse"]');
    expect(header.textContent).toContain('信道Excel维护台账');
    expect(header.textContent).toContain('每周｜2026-10-05 ~ 2026-10-11');
    expect(document.querySelector('[data-testid="browse-counter"]').textContent)
      .toContain('第 1 张 / 共 3 张');
    expect(document.querySelector('[data-testid="browse-status"]').textContent)
      .toContain('已完成');
    // 首张：上一张禁用，下一张可用
    expect(buttonByText('上一张台账').disabled).toBe(true);
    expect(buttonByText('下一张台账').disabled).toBe(false);
    // 第一张台账详情已按清单条目拉取（创建时版本快照 v1）
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/101/');
    expect(container.textContent).toContain('Excel 台账：EL-WM-2026-1101');
    expect(container.textContent).toContain('v1');
  });

  test('下一张/上一张在清单内移动并加载对应台账（末张禁用下一张）', async () => {
    await renderBrowse();
    await act(async () => {
      buttonByText('下一张台账').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(document.querySelector('[data-testid="browse-counter"]').textContent)
      .toContain('第 2 张 / 共 3 张');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/102/');
    await act(async () => {
      buttonByText('下一张台账').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(document.querySelector('[data-testid="browse-counter"]').textContent)
      .toContain('第 3 张 / 共 3 张');
    // 第三张为 v2 版本快照（版本随台账，不随模板当前版本漂移）
    expect(container.textContent).toContain('v2');
    // 末张：下一张禁用，上一张可用
    expect(buttonByText('下一张台账').disabled).toBe(true);
    expect(buttonByText('上一张台账').disabled).toBe(false);
    await act(async () => {
      buttonByText('上一张台账').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(document.querySelector('[data-testid="browse-counter"]').textContent)
      .toContain('第 2 张 / 共 3 张');
  });

  test('期次跳转归并同期条目并定位该期次第一张', async () => {
    const entries = [
      makeEntry(201, {status: 'completed'}),
      makeEntry(202, {status: 'completed'}),
      makeEntry(203, {
        maintenance_period: '2026-11-02', period_key: '2026-11-02',
        period_label: '每周｜2026-11-02 ~ 2026-11-08',
      }),
      makeEntry(204, {
        maintenance_period: '', period_key: '',
        period_label: '未标注期次', executed_date: '2026-08-05',
      }),
    ];
    await renderBrowse(entries);
    const selector = document.querySelector(
      '[data-testid="ledger-group-browse"] .ant-select-selector');
    await act(async () => {
      selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await flush();
    const options = Array.from(document.querySelectorAll(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option'));
    // 同期归并：每周两张某期次一个选项（含张数）；未标注期次单独一组
    const texts = options.map(option => option.textContent);
    expect(texts.some(t => t.includes('每周｜2026-10-05') && t.includes('2张')))
      .toBe(true);
    expect(texts.some(t => t.includes('未标注期次'))).toBe(true);
    const target = options.find(option => option.textContent.includes('2026-11-02'));
    await act(async () => {
      target.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      target.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(document.querySelector('[data-testid="browse-counter"]').textContent)
      .toContain('第 3 张 / 共 4 张');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/203/');
  });
});

describe('LedgerGroupBrowse 未保存拦截与退出', () => {
  test('草稿未保存修改时切换先确认：继续填写保留内容，放弃后才切换', async () => {
    await renderBrowse();
    const excelStore = mockCreatedExcelStores[0];
    expect(excelStore).toBeTruthy();
    // 翻到第二张（草稿）并制造未保存修改
    await act(async () => {
      buttonByText('下一张台账').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.browseState.index).toBe(1);
    act(() => {
      excelStore.setValue(FIELD_PS, '正常');
    });
    expect(excelStore.hasUnsaved).toBe(true);
    // 点击下一张 → 弹确认
    await act(async () => {
      buttonByText('下一张台账').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const confirmModal = confirmModalByText('有未保存的修改');
    expect(confirmModal).toBeTruthy();
    // 继续填写：不切换、内容保留
    await act(async () => {
      buttonByText('继续填写', confirmModal).dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.browseState.index).toBe(1);
    expect(excelStore.values[FIELD_PS]).toBe('正常');
    // 放弃修改并继续：切换到第三张
    await act(async () => {
      buttonByText('下一张台账').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const confirmAgain = confirmModalByText('有未保存的修改');
    await act(async () => {
      buttonByText('放弃修改并继续', confirmAgain).dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.browseState.index).toBe(2);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/103/');
  });

  test('只读台账（已完成）无未保存状态，直接翻阅不弹确认', async () => {
    await renderBrowse();
    // 第一张为已完成（只读），翻页不触发确认
    await act(async () => {
      buttonByText('下一张台账').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.browseState.index).toBe(1);
    expect(confirmModalByText('有未保存的修改')).toBeFalsy();
  });

  test('退出翻阅清空状态并按进入层级刷新列表', async () => {
    await renderBrowse();
    store.viewMode = 'template';
    await act(async () => {
      buttonByText('退出翻阅').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.browseState).toBe(null);
    // refresh：模板视图无 activeGroup → 刷新模板组列表
    expect(mockHttpGet).toHaveBeenCalledWith(GROUPS_LIST_URL, expect.anything());
  });

  test('openBrowse 携带进入时模板视图筛选（范围口径随进入筛选）', async () => {
    mockRoutes(makeEntries());
    const scoped = new LedgerStore('week_month');
    scoped.t_status = 'void';
    scoped.t_keyword = 'EL-WM';
    await scoped.openBrowse({group_key: '7', template_name: '信道Excel维护台账'});
    await flush();
    const [url, config] = mockHttpGet.mock.calls[0];
    expect(url).toBe(BROWSE_URL);
    expect(config.params.ledger_type).toBe('week_month');
    expect(config.params.status).toBe('void');
    expect(config.params.keyword).toBe('EL-WM');
    expect(scoped.browseState.entries).toHaveLength(3);
    expect(scoped.browseState.index).toBe(0);
  });

  test('空筛选范围给出空态与共 0 张，翻页按钮禁用', async () => {
    await renderBrowse([]);
    expect(document.querySelector('[data-testid="browse-counter"]').textContent)
      .toContain('共 0 张');
    expect(container.textContent).toContain('当前筛选范围内没有可翻阅的台账');
    expect(buttonByText('上一张台账').disabled).toBe(true);
    expect(buttonByText('下一张台账').disabled).toBe(true);
  });
});
