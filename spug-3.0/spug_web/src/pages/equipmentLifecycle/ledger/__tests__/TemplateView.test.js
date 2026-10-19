/**
 * 运维台账"按模板查看"视图（2026-10-11）页面行为测试。
 *
 * 真实渲染 LedgerIndex（ReactDOM + jsdom，createElement 风格与仓库测试惯例
 * 一致），mock libs.http 与公共组件壳，验证：
 * - 默认"按维护周期"视图保持现状（周期分组表 + 生成本期应填台账入口）；
 * - 视图切换到"按模板查看"后渲染模板组统计（含停用标注与无模板/临时补录组），
 *   且"生成本期应填台账"入口在两个视图模式均可用（2026-10-14 重构）；
 * - 点击"查看台账"进入组内台账列表（返回按钮 + 组内行 + 模板版本列）；
 * - 返回模板组后组列表页码保留；
 * - 组内台账行携带创建时模板版本（后端 source_version_no 渲染为 v{n}）。
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
  // AuthButton 须转发 Button 行为（onClick/disabled），否则交互断言失真
  const AuthButton = (props) => React.createElement('button', {
    type: 'button',
    onClick: props.onClick,
    disabled: props.disabled,
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
  require('libs').exportFile.mockReset();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const TEMPLATE_GROUPS_PAYLOAD = {
  data: [
    {
      group_key: '7', source_type: 'excel', template_id: 7,
      template_name: '信道维护台账', is_active: true,
      total: 3, draft: 1, completed: 1, void: 1,
      last_created_at: '2026-10-08 09:00:00',
    },
    {
      group_key: '9', source_type: 'excel', template_id: 9,
      template_name: '退役模板', is_active: false,
      total: 2, draft: 2, completed: 0, void: 0,
      last_created_at: '2026-09-01 09:00:00',
    },
    {
      group_key: 'manual', source_type: 'manual', template_id: null,
      template_name: '无模板/临时补录', is_active: null,
      total: 1, draft: 1, completed: 0, void: 0,
      last_created_at: '2026-10-02 09:00:00',
    },
  ],
  total: 3, page: 1, page_size: 10,
};

const GROUP_LEDGERS_PAYLOAD = {
  group_key: '7', group_name: '信道维护台账',
  data: [
    {
      id: 21, ledger_no: 'EL-WM-20261008-0001', ledger_type: 'week_month',
      status: 'completed', source_type: 'excel',
      source_template_name: '信道维护台账', source_version_no: 2,
      created_by_name: 'op1', created_at: '2026-10-08 09:00',
    },
    {
      id: 20, ledger_no: 'EL-WM-20261005-0002', ledger_type: 'week_month',
      status: 'draft', source_type: 'excel',
      source_template_name: '信道维护台账', source_version_no: 1,
      created_by_name: 'op1', created_at: '2026-10-05 09:00',
    },
  ],
  total: 2, page: 1, page_size: 20,
};

const PERIOD_GROUPS_PAYLOAD = [{
  maintenance_period: '2026-10', period_text: '2026年10月',
  total: 2, pending: 2, filled: 0, ledgers: [],
}];

const DETAIL_SHEET = {
  name: '信道维护记录', max_row: 4, max_column: 8,
  merged_ranges: [], row_heights: {}, column_widths: {},
  cells: {A1: {v: '信道维护记录表'}, A2: {v: '信道'}, C2: {v: 'PS模块'}},
};

// Excel 台账详情载荷（与 ExcelLedgerStore.fetchDetail 消费形态一致，
// 拦截器已剥一层；版式快照结构对齐 ExcelLedgerDetail 渲染输入）
function makeExcelDetailPayload() {
  return {
    id: 21, ledger_no: 'EL-WM-20261008-0001', ledger_type: 'week_month',
    status: 'completed',
    created_from: 'excel_template',
    excel: {
      record_id: 7, values: {}, editable: false,
      version: {
        id: 5, version_no: 2, template_name: '信道维护台账',
        ledger_type: 'week_month', source_filename: 'channel.xlsx',
        source_hash: 'a'.repeat(64), field_count: 1,
        published_at: '2026-10-01 09:00:00',
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [DETAIL_SHEET]},
        bindings: [],
      },
    },
  };
}

function mockHttpEndpoints() {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/template-groups/7/ledgers/')) {
      return Promise.resolve(GROUP_LEDGERS_PAYLOAD);
    }
    if (url.endsWith('/ledgers/template-groups/')) {
      return Promise.resolve(TEMPLATE_GROUPS_PAYLOAD);
    }
    if (url.endsWith('/ledgers/period-groups/')) {
      return Promise.resolve({data: PERIOD_GROUPS_PAYLOAD});
    }
    return Promise.resolve({data: [], total: 0});
  });
}

const entriesModule = require('../entries');
const storeModule = require('../store');

async function renderIndex() {
  await act(async () => {
    ReactDOM.render(h(entriesModule.WeekMonthLedgerIndex), container);
  });
  await act(flush);
}

function findRadioInput(label) {
  const inputs = Array.from(container.querySelectorAll('label.ant-radio-button-wrapper'));
  return inputs.find(el => el.textContent === label);
}

function findAnchor(text) {
  return Array.from(container.querySelectorAll('a'))
    .find(el => el.textContent === text);
}

function findButton(text) {
  return Array.from(container.querySelectorAll('button'))
    .find(el => el.textContent === text);
}

describe('维护台账模板视图', () => {
  beforeEach(() => {
    // getLedgerStore 模块级缓存：跨用例重置视图相关状态
    const store = storeModule.getLedgerStore('week_month');
    store.viewMode = 'period';
    store.activeGroup = null;
    store.templateGroupsPage = 1;
    store.templateGroups = [];
    store.templateGroupsTotal = 0;
    store.groupLedgers = [];
    store.groupLedgersTotal = 0;
    store.f_keyword = undefined;
    store.f_status = undefined;
    store.f_date_range = undefined;
    mockHttpEndpoints();
  });

  test('默认按维护周期视图：周期分组渲染，含生成本期应填台账入口，不发模板组请求', async () => {
    await renderIndex();
    expect(container.textContent).toContain('2026年10月');
    expect(container.textContent).toContain('生成本期应填台账');
    expect(container.textContent).toContain('按维护周期');
    expect(container.textContent).toContain('按模板查看');
    expect(mockHttpGet.mock.calls.some(c => c[0].includes('template-groups'))).toBe(false);
  });

  test('切换到按模板查看：渲染模板组统计（停用标注与无模板组）', async () => {
    await renderIndex();
    await act(async () => {
      findRadioInput('按模板查看').querySelector('input').click();
    });
    await act(flush);
    expect(container.textContent).toContain('信道维护台账');
    expect(container.textContent).toContain('退役模板 [已停用]');
    expect(container.textContent).toContain('无模板/临时补录');
    expect(container.textContent).toContain('2026-10-08');
    // 系统筛选不在模板视图；生成本期应填台账入口两个视图均可用（2026-10-14）
    expect(container.textContent).not.toContain('按系统查看');
    expect(container.textContent).toContain('生成本期应填台账');
    const call = mockHttpGet.mock.calls.find(c =>
      c[0].endsWith('/ledgers/template-groups/'));
    expect(call[1].params.ledger_type).toBe('week_month');
    // 新增台账入口保留（创建是全局动作）
    expect(container.textContent).toContain('新增周月维护台账');
  });

  test('进入模板组：组内台账渲染创建时版本，提供返回入口', async () => {
    await renderIndex();
    await act(async () => {
      findRadioInput('按模板查看').querySelector('input').click();
    });
    await act(flush);
    await act(async () => {
      findAnchor('查看台账').click();
    });
    await act(flush);
    expect(container.textContent).toContain('返回模板组');
    expect(container.textContent).toContain('EL-WM-20261008-0001');
    expect(container.textContent).toContain('v2');
    expect(container.textContent).toContain('v1');
    // 组内不再展示组列表（模板组统计行消失）
    expect(container.textContent).not.toContain('无模板/临时补录');
    expect(mockHttpGet.mock.calls.some(c => c[0].includes('/template-groups/7/ledgers/')))
      .toBe(true);
  });

  test('返回模板组后组列表状态保留（页码复用）', async () => {
    const store = storeModule.getLedgerStore('week_month');
    await renderIndex();
    await act(async () => {
      findRadioInput('按模板查看').querySelector('input').click();
    });
    await act(flush);
    store.templateGroupsPage = 2;
    await act(async () => {
      findAnchor('查看台账').click();
    });
    await act(flush);
    await act(async () => {
      findButton('返回模板组').click();
    });
    await act(flush);
    const call = mockHttpGet.mock.calls.filter(c =>
      c[0].endsWith('/ledgers/template-groups/')).pop();
    expect(call[1].params.page).toBe(2);
    expect(container.textContent).toContain('信道维护台账');
  });

  test('模板组内 Excel 台账行点击详情进入 Excel 详情（版本快照回放）', async () => {
    await renderIndex();
    await act(async () => {
      findRadioInput('按模板查看').querySelector('input').click();
    });
    await act(flush);
    await act(async () => {
      findAnchor('查看台账').click();
    });
    await act(flush);
    mockHttpGet.mockImplementation(url => {
      if (url.includes('/excel-ledgers/21/')) {
        return Promise.resolve(makeExcelDetailPayload());
      }
      if (url.includes('/template-groups/7/ledgers/')) {
        return Promise.resolve(GROUP_LEDGERS_PAYLOAD);
      }
      return Promise.resolve({data: [], total: 0});
    });
    const detailAnchor = Array.from(container.querySelectorAll('a'))
      .find(el => el.textContent === '查看'); // 已完成行的主操作为"查看"（2026-10-14 列改版）
    await act(async () => {
      detailAnchor.click();
    });
    await act(flush);
    expect(mockHttpGet.mock.calls.some(c => c[0].endsWith('/excel-ledgers/21/')))
      .toBe(true);
    // Excel 详情视图替换组内列表（版本快照回放，非普通明细弹窗）
    expect(container.textContent).toContain('EL-WM-20261008-0001');
  });
});

describe('模板组内台账表列序与横向滚动（2026-10-18）', () => {
  beforeEach(() => {
    // getLedgerStore 模块级缓存：跨用例重置视图相关状态（与上组一致）
    const store = storeModule.getLedgerStore('week_month');
    store.viewMode = 'period';
    store.activeGroup = null;
    store.templateGroupsPage = 1;
    store.templateGroups = [];
    store.templateGroupsTotal = 0;
    store.groupLedgers = [];
    store.groupLedgersTotal = 0;
    store.f_keyword = undefined;
    store.f_status = undefined;
    store.f_date_range = undefined;
    mockHttpEndpoints();
  });

  test('组内台账表横向滚动（scroll.x 与列宽总和一致），操作列固定最右', async () => {
    await renderIndex();
    await act(async () => {
      findRadioInput('按模板查看').querySelector('input').click();
    });
    await act(flush);
    await act(async () => {
      findAnchor('查看台账').click();
    });
    await act(flush);
    const groupTable = Array.from(container.querySelectorAll('table'))
      .find(t => t.textContent.includes('EL-WM-20261008-0001'));
    expect(groupTable).toBeTruthy();
    // antd 对数字 scroll.x 生成固定布局：table 内联宽度 = 列宽总和，
    // 窄屏容器出现横向滚动条时 fixed right 列保持可见
    expect(groupTable.style.width).toBe('990px');
    const headers = Array.from(groupTable.querySelectorAll('thead th'))
      .map(th => th.textContent);
    expect(headers[headers.length - 1]).toBe('操作');
    expect(groupTable.querySelector('thead th.ant-table-cell-fix-right').textContent)
      .toBe('操作');
  });
});

// ===== 组内批量导出"导出本模板台账"（2026-10-11）共享夹具 =====
const EXPORT_PREVIEW_PAYLOAD = {
  data: {
    group_key: '7', template_id: 7, template_name: '信道维护台账',
    ledger_type: 'week_month', total: 3,
    status_scope: ['completed'],
    versions: [{version_no: 1, count: 1}, {version_no: 2, count: 2}],
    max_records: 50,
  },
};

function mockBatchEndpoints({groupLedgers = GROUP_LEDGERS_PAYLOAD, preview = null} = {}) {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/template-groups/7/ledgers/')) {
      return Promise.resolve(groupLedgers);
    }
    if (url.includes('/template-groups/7/export-pdf/') && preview) {
      return Promise.resolve(preview);
    }
    if (url.endsWith('/ledgers/template-groups/')) {
      return Promise.resolve(TEMPLATE_GROUPS_PAYLOAD);
    }
    if (url.endsWith('/ledgers/period-groups/')) {
      return Promise.resolve({data: PERIOD_GROUPS_PAYLOAD});
    }
    return Promise.resolve({data: [], total: 0});
  });
}

async function enterGroup() {
  await renderIndex();
  await act(async () => {
    findRadioInput('按模板查看').querySelector('input').click();
  });
  await act(flush);
  await act(async () => {
    findAnchor('查看台账').click();
  });
  await act(flush);
}

async function enterManualGroup() {
  await renderIndex();
  await act(async () => {
    findRadioInput('按模板查看').querySelector('input').click();
  });
  await act(flush);
  const anchors = Array.from(container.querySelectorAll('a'))
    .filter(el => el.textContent === '查看台账');
  await act(async () => {
    anchors[anchors.length - 1].click();
  });
  await act(flush);
}

function findModalButton(text) {
  // antd 按钮对两个汉字文案自动插入空格（取 消），匹配前统一去除空白
  const target = text.replace(/\s/g, '');
  return Array.from(document.body.querySelectorAll('button'))
    .find(el => el.textContent.replace(/\s/g, '') === target);
}

function resetLedgerStore() {
  const store = storeModule.getLedgerStore('week_month');
  store.viewMode = 'period';
  store.activeGroup = null;
  store.batchExportPreview = null;
  store.isBatchExportFetching = false;
  store.templateGroupsPage = 1;
  store.groupLedgers = [];
  store.groupLedgersTotal = 0;
  store.f_keyword = undefined;
  store.f_status = undefined;
  store.f_date_range = undefined;
  mockBatchEndpoints();
}

describe('组内批量导出·确认框与发起（2026-10-11）', () => {
  beforeEach(() => {
    resetLedgerStore();
  });

  test('点击导出按钮先取确认数据：展示模板名/数量/状态范围/涉及版本', async () => {
    mockBatchEndpoints({preview: EXPORT_PREVIEW_PAYLOAD});
    await enterGroup();
    const exportButton = findButton('导出本模板台账');
    expect(exportButton).toBeTruthy();
    expect(exportButton.disabled).toBe(false);
    await act(async () => {
      exportButton.click();
    });
    await act(flush);
    const call = mockHttpGet.mock.calls.find(c =>
      c[0].endsWith('/template-groups/7/export-pdf/'));
    expect(call).toBeTruthy();
    expect(call[1].params.ledger_type).toBe('week_month');
    const modalText = document.body.textContent;
    expect(modalText).toContain('匹配记录数');
    expect(modalText).toContain('3 条');
    expect(modalText).toContain('已完成');
    expect(modalText).toContain('v1（1 条）、v2（2 条）');
    // 页数无法可靠预估，确认框不展示预计页数
    expect(modalText).not.toContain('预计页数');
  });

  test('确认后以相同筛选 POST 发起导出并关闭确认框', async () => {
    mockBatchEndpoints({preview: EXPORT_PREVIEW_PAYLOAD});
    await enterGroup();
    await act(async () => {
      findButton('导出本模板台账').click();
    });
    await act(flush);
    await act(async () => {
      findModalButton('导出 PDF').click();
    });
    await act(flush);
    const mockExportFile = require('libs').exportFile;
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const options = mockExportFile.mock.calls[0][0];
    expect(options.url).toBe('/api/equipment-lifecycle/ledgers/template-groups/7/export-pdf/');
    expect(options.method).toBe('post');
    expect(options.params.ledger_type).toBe('week_month');
    expect(options.params.status).toBeUndefined();
    expect(options.defaultFilename).toContain('批量导出');
    // 确认框已关闭
    expect(document.body.textContent).not.toContain('匹配记录数');
  });

  test('取消关闭确认框，不发起导出', async () => {
    mockBatchEndpoints({preview: EXPORT_PREVIEW_PAYLOAD});
    await enterGroup();
    await act(async () => {
      findButton('导出本模板台账').click();
    });
    await act(flush);
    await act(async () => {
      findModalButton('取消').click();
    });
    await act(flush);
    expect(require('libs').exportFile).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain('匹配记录数');
  });

  test('确认框内无匹配记录时禁用导出并给出明确提示', async () => {
    mockBatchEndpoints({preview: {...EXPORT_PREVIEW_PAYLOAD, data: {
      ...EXPORT_PREVIEW_PAYLOAD.data, total: 0, versions: [],
    }}});
    await enterGroup();
    await act(async () => {
      findButton('导出本模板台账').click();
    });
    await act(flush);
    expect(document.body.textContent).toContain('当前筛选条件下没有符合条件的台账');
    expect(findModalButton('导出 PDF').disabled).toBe(true);
  });
});

describe('组内批量导出·入口边界（2026-10-11）', () => {
  beforeEach(() => {
    resetLedgerStore();
  });

  test('manual 组不提供批量导出入口（无模板版式不可生成 PDF）', async () => {
    await enterManualGroup();
    expect(storeModule.getLedgerStore('week_month').activeGroup.group_key).toBe('manual');
    expect(findButton('导出本模板台账')).toBeUndefined();
  });

  test('组内无匹配台账时导出按钮禁用', async () => {
    mockBatchEndpoints({groupLedgers: {
      group_key: '7', group_name: '信道维护台账',
      data: [], total: 0, page: 1, page_size: 20,
    }});
    await enterGroup();
    const exportButton = findButton('导出本模板台账');
    expect(exportButton).toBeTruthy();
    expect(exportButton.disabled).toBe(true);
  });
});
