/**
 * 正式台账列表统一接入 Excel 路线的前端行为测试（2026-10，旧可视化模板
 * 路线删除后收口为 Excel 单一新增入口）。
 *
 * 真实渲染 LedgerIndex（ReactDOM + jsdom，mock libs.http 与公共组件壳）：
 * - 统一列表渲染 Excel 模板列（来源标签列已删除，source_type 仅驱动详情路由）；
 * - 正式新增台账只提供 Excel/WPS 模板一种方式：点击"新增"直接打开
 *   Excel 创建弹窗，不再有"可视化表格"选项与录入方式选择弹窗；
 * - 周月/季维护入口各自只加载对应台账类型的已发布 Excel 模板版本；
 * - 创建经既有 POST /excel-ledgers/（client_token 幂等），成功后进入
 *   Excel 台账填写详情；
 * - 详情按来源路由：Excel 行走 /excel-ledgers/ 详情，手工补录走既有详情；
 * - 跨页跳转 ?detail=<id>&source=excel 直达 Excel 详情。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: jest.fn()},
  exportFile: jest.fn(),
  history: {location: {search: ''}, replace: jest.fn(), push: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  X_TOKEN: '',
}));

jest.mock('components', () => {
  const React = require('react');
  const antd = require('antd');
  // AuthButton/ExportButton 转发到真实 antd Button（保留 type/icon/onClick，
  // 页面工具栏按钮依赖真实 button 元素做点击交互）
  const AuthButton = (props) => React.createElement(antd.Button, props, props.children);
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
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
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const entriesModule = require('../entries');

const FIELD_PS = 'aaaaaaaa-1111-4aaa-8aaa-000000000001';

const SHEET = {
  name: '信道维护记录', max_row: 4, max_column: 8,
  merged_ranges: [], row_heights: {}, column_widths: {},
  cells: {
    A1: {v: '信道维护记录表'}, A2: {v: '信道'}, C2: {v: 'PS模块'},
    A3: {v: '第1信道'}, B3: {v: '主电台'},
  },
};

const BINDINGS = [{
  field_id: FIELD_PS, sheet_name: '信道维护记录', cell_coordinate: 'C3',
  field_name: 'PS模块', input_type: 'status', is_required: true,
  unit: '', options: ['正常', '异常'],
}];

function makeExcelDetail(status = 'draft', values = {}) {
  return {
    id: 33, ledger_no: 'EL-WM-20260928-001', ledger_type: 'week_month', status,
    created_from: 'excel_template',
    excel: {
      record_id: 7, values, editable: status === 'draft',
      version: {
        id: 5, version_no: 2, template_name: '信道Excel维护台账',
        ledger_type: 'week_month', source_filename: 'channel.xlsx',
        source_hash: 'a'.repeat(64), field_count: 1,
        published_at: '2026-09-28 09:00:00',
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
        bindings: BINDINGS,
      },
    },
  };
}

function makeManualDetail() {
  return {
    id: 1, ledger_no: 'EL-WM-20260910-0001', ledger_type: 'week_month', status: 'draft', created_from: 'manual',
    entry_channel: 'web', version: 1,
    created_by_name: 'op1', items: [], corrections: [],
  };
}

const LIST_PAYLOAD = {
  data: [
    {id: 1, ledger_no: 'EL-WM-20260910-0001', ledger_type: 'week_month', status: 'draft',
     created_by_name: 'op1',
     created_at: '2026-09-11 09:00', created_from: 'manual',
     source_type: 'manual', source_template_name: '',
     source_version_no: null,
     detail_route: '/el/week-month-ledgers?detail=1&source=manual'},
    {id: 33, ledger_no: 'EL-WM-20260928-001', ledger_type: 'week_month', status: 'draft',
     created_by_name: 'op1',
     created_at: '2026-09-28 10:00', created_from: 'excel_template',
     source_type: 'excel', source_template_name: '信道Excel维护台账',
     source_version_no: 2,
     detail_route: '/el/week-month-ledgers?detail=33&source=excel'},
  ],
  total: 2, page: 1, page_size: 20,
};

// 周期分组视图（2026-10-11）：页面列表改拉 /ledgers/period-groups/；
// 2026-10-14 起为分页形态 {data: {data, total}}，is_current=true 的组默认展开，
// 组内行复用原列表行（模板名称列/详情路由断言保持不变）
const GROUPS_FROM_LIST = {
  data: {
    data: [{
      maintenance_period: '2026-09', period_text: '每月｜2026年9月',
      is_current: true,
      total: LIST_PAYLOAD.data.length, draft: LIST_PAYLOAD.data.length,
      completed: 0, void: 0,
      ledgers: LIST_PAYLOAD.data,
    }],
    total: 1,
  },
};

const AVAILABLE_EXCEL_PAYLOAD = [{id: 11, name: '信道Excel维护台账', ledger_type: 'week_month',
  description: '',
  versions: [{id: 5, version_no: 2, field_count: 1,
              source_filename: 'channel.xlsx'}]}];

let container = null;

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    document.body.removeChild(container);
  }
  container = null;
});

async function renderIndex(location) {
  await act(async () => {
    ReactDOM.render(
      React.createElement(entriesModule.WeekMonthLedgerIndex,
        location ? {location} : {}),
      container);
  });
  await flush();
}

async function renderSeasonalIndex() {
  await act(async () => {
    ReactDOM.render(
      React.createElement(entriesModule.SeasonalLedgerIndex), container);
  });
  await flush();
}

function buttonByText(text, root) {
  const scope = root || document;
  return Array.from(scope.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
}

function modalRootByTitle(title) {
  return Array.from(document.querySelectorAll('.ant-modal'))
    .find(node => node.textContent.includes(title));
}

async function chooseSelectOption(modalRoot, matchText) {
  const selector = modalRoot.querySelector('.ant-select-selector');
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
  });
  await flush();
  const option = Array.from(document.querySelectorAll(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option'))
    .find(o => o.textContent.includes(matchText));
  expect(option).toBeTruthy();
  await act(async () => {
    option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await flush();
}

test('统一列表渲染 Excel 模板列，不渲染来源标签/明细数/异常数列', async () => {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/ledgers/period-groups/')) return Promise.resolve(GROUPS_FROM_LIST);
    return Promise.resolve(LIST_PAYLOAD);
  });
  await renderIndex();
  // 2026-10-14 列改版：模板名称列在前，版本不再拼进同一单元格
  expect(container.textContent).toContain('模板名称');
  expect(container.textContent).toContain('信道Excel维护台账');
  expect(container.textContent).toContain('每月｜'); // 分组期次为完整标签（2026-10-14）
  // 来源/明细数/异常数列已删除（2026-10）
  expect(container.textContent).not.toContain('临时补录');
  expect(container.textContent).not.toContain('明细数');
  expect(container.textContent).not.toContain('异常数');
  // 旧可视化模板来源已随路线删除
  expect(container.textContent).not.toContain('可视化模板');
  expect(container.textContent).not.toContain('可视化表格');
});

test('正式新增台账只提供 Excel 模板：点击新增直接打开 Excel 创建弹窗', async () => {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/ledgers/period-groups/')) return Promise.resolve(GROUPS_FROM_LIST);
    if (url.includes('/ledgers/')) return Promise.resolve(LIST_PAYLOAD);
    if (url.includes('excel-templates/available')) {
      return Promise.resolve({data: AVAILABLE_EXCEL_PAYLOAD});
    }
    return Promise.resolve({data: []});
  });
  await renderIndex();
  await act(async () => {
    buttonByText('新增周月维护台账').click();
  });
  await flush();
  // 不再有录入方式选择弹窗（二选一逻辑已删除）
  expect(modalRootByTitle('选择台账录入方式')).toBeUndefined();
  // 直接打开 Excel/WPS 模板创建弹窗
  const createModal = modalRootByTitle('选择 Excel/WPS 模板创建周月维护台账');
  expect(createModal).toBeTruthy();
  expect(document.body.textContent).not.toContain('可视化表格');
  // 未选择版本前不发起创建请求
  expect(mockHttpPost).not.toHaveBeenCalled();
});

test('周月维护入口只加载周月类型的已发布 Excel 模板版本', async () => {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/ledgers/period-groups/')) return Promise.resolve(GROUPS_FROM_LIST);
    if (url.includes('/ledgers/')) return Promise.resolve(LIST_PAYLOAD);
    if (url.includes('excel-templates/available')) {
      return Promise.resolve({data: AVAILABLE_EXCEL_PAYLOAD});
    }
    return Promise.resolve({data: []});
  });
  await renderIndex();
  await act(async () => {
    buttonByText('新增周月维护台账').click();
  });
  await flush();
  const createModal = modalRootByTitle('选择 Excel/WPS 模板创建周月维护台账');
  const availableCall = mockHttpGet.mock.calls.find(c => c[0].includes('excel-templates/available'));
  expect(availableCall[1].params.ledger_type).toBe('week_month');
  await chooseSelectOption(createModal, 'v2');
  expect(createModal.textContent).toContain('信道Excel维护台账 v2');
  expect(createModal.textContent).toContain('1 字段');
  expect(createModal.textContent).toContain('channel.xlsx');
});

test('季维护入口只加载季维护类型的已发布 Excel 模板版本', async () => {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/ledgers/')) return Promise.resolve({data: [], total: 0, page: 1, page_size: 20});
    if (url.includes('excel-templates/available')) {
      return Promise.resolve({data: [{id: 21, name: '季维护Excel台账', ledger_type: 'seasonal',
        versions: [{id: 9, version_no: 1, field_count: 2, source_filename: 'season.xlsx'}]}]});
    }
    return Promise.resolve({data: []});
  });
  await renderSeasonalIndex();
  await act(async () => {
    buttonByText('新增季维护台账').click();
  });
  await flush();
  const availableCall = mockHttpGet.mock.calls.find(c => c[0].includes('excel-templates/available'));
  expect(availableCall[1].params.ledger_type).toBe('seasonal');
  const createModal = modalRootByTitle('选择 Excel/WPS 模板创建季维护台账');
  expect(createModal).toBeTruthy();
  await chooseSelectOption(createModal, 'v1');
  expect(createModal.textContent).toContain('季维护Excel台账 v1');
});

test('Excel 创建成功后进入 Excel 台账详情', async () => {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/ledgers/period-groups/')) return Promise.resolve(GROUPS_FROM_LIST);
    if (url.includes('/ledgers/')) return Promise.resolve(LIST_PAYLOAD);
    if (url.includes('excel-templates/available')) {
      return Promise.resolve({data: AVAILABLE_EXCEL_PAYLOAD});
    }
    return Promise.resolve({data: []});
  });
  mockHttpPost.mockResolvedValue({data: makeExcelDetail()});
  await renderIndex();
  await act(async () => {
    buttonByText('新增周月维护台账').click();
  });
  await flush();
  const createModal = modalRootByTitle('选择 Excel/WPS 模板创建周月维护台账');
  await chooseSelectOption(createModal, 'v2');
  await act(async () => {
    buttonByText('确定', createModal).click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/',
    expect.objectContaining({version_id: 5, ledger_type: 'week_month',
                             client_token: expect.any(String)}));
  // 创建成功：弹窗关闭，统一列表被 Excel 台账详情视图替换（ExcelLedgerDetail 复用）
  expect(modalRootByTitle('选择 Excel/WPS 模板创建周月维护台账')).toBeUndefined();
  expect(container.textContent).toContain('Excel 台账：EL-WM-20260928-001');
});

test('列表点击详情按来源路由：Excel 行走 Excel 详情，手工补录走既有详情', async () => {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/excel-ledgers/33/')) {
      return Promise.resolve({data: makeExcelDetail()});
    }
    if (url.includes('/ledgers/1/')) {
      return Promise.resolve(makeManualDetail());
    }
    if (url.includes('/ledgers/period-groups/')) return Promise.resolve(GROUPS_FROM_LIST);
    if (url.includes('/ledgers/')) return Promise.resolve(LIST_PAYLOAD);
    return Promise.resolve({data: []});
  });
  await renderIndex();
  // Excel 来源行
  await act(async () => {
    Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '继续填写' && a.closest('tr').textContent.includes('EL-WM-20260928-001'))
      .click();
  });
  await flush();
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/33/');
  expect(container.textContent).toContain('Excel 台账：EL-WM-20260928-001');
  // 返回列表后点击手工补录行
  await act(async () => {
    buttonByText('返回列表').click();
  });
  await flush();
  await act(async () => {
    Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '继续填写' && a.closest('tr').textContent.includes('EL-WM-20260910-0001'))
      .click();
  });
  await flush();
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/1/');
});

test('跨页跳转 ?detail=33&source=excel 直达 Excel 详情', async () => {
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/excel-ledgers/33/')) {
      return Promise.resolve({data: makeExcelDetail()});
    }
    if (url.includes('/ledgers/period-groups/')) return Promise.resolve(GROUPS_FROM_LIST);
    if (url.includes('/ledgers/')) return Promise.resolve(LIST_PAYLOAD);
    return Promise.resolve({data: []});
  });
  await renderIndex({search: '?detail=33&source=excel'});
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/33/');
  expect(container.textContent).toContain('Excel 台账：EL-WM-20260928-001');
});
