/**
 * Excel 台账模板字段名称自动生成测试（真实渲染 + jsdom + http mock，
 * 2026-10-19 自 ExcelTemplatePageWorkspace.test.js 拆分出独立关注点）。
 *
 * 覆盖：新绑定默认名「工作表名 · 坐标」（单格预填、批量每格各一个，
 * 不再要求填写名称/前缀即可保存）→ 清空名称保存回退默认名 → 自定义
 * 名称保留 → 编辑已有绑定名称不变且 field_id 稳定 → 前缀可选仍支持
 * 「前缀-坐标」→ 跨工作表默认名携带所在工作表名 → 保存载荷 field_name
 * 始终非空（后端仍为非空校验权威）。
 * 全部走真实组件与 store 代码路径（真实点击单元格/按钮），http 仅打桩。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: mockHttpDelete},
  exportFile: jest.fn(),
  history: {location: {search: ''}, replace: jest.fn(), push: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

// import 会被提升到 mock 变量声明之前，组件须在 mock 就绪后 require
const loadPage = () => require('../ExcelTemplatePage').default;
const {ExcelTemplateStore} = require('../excelTemplateStore');

const FIELD_PS = 'aaaaaaaa-1111-4aaa-8aaa-000000000001';

const SHEET = {
  name: '信道维护记录', max_row: 6, max_column: 8,
  merged_ranges: ['A1:H1', 'A3:A4'],
  row_heights: {'1': 30, '3': 24},
  column_widths: {A: 12, H: 20},
  cells: {
    A1: {v: '信道维护记录表', s: {font: {bold: true, size: 14}}},
    A2: {v: '信道', s: {fill: 'F2F2F2'}}, B2: {v: '电台'},
    C2: {v: 'PS模块'}, D2: {v: 'TX模块'}, H2: {v: '备注'},
    A3: {v: '第1信道'}, B3: {v: '主电台'}, B4: {v: '备电台'},
    C4: {s: {border: {top: {style: 'thin'}}}},
  },
  print: {orientation: 'portrait', paper_size: 9},
};

function makeDetail(bindings = [], overrides = {}) {
  return {
    id: 11,
    name: '信道Excel维护台账',
    ledger_type: 'week_month',
    description: '',
    is_active: true,
    draft_source_filename: 'channel.xlsx',
    draft_source_hash: 'a'.repeat(64),
    latest_version_no: 0,
    versions_count: 0,
    draft: {
      sheet_name: '信道维护记录',
      source_filename: 'channel.xlsx',
      source_hash: 'a'.repeat(64),
      layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
      field_bindings: bindings,
      draft_updated_at: '2026-09-28 10:00:00',
    },
    ...overrides,
  };
}

const BOUND_PS = {
  field_id: FIELD_PS, sheet_name: '信道维护记录', cell_coordinate: 'C4',
  field_name: 'PS模块', input_type: 'status', is_required: true,
  unit: '', options: ['正常', '异常'], default_value: '',
  operation_guide: '', abnormal_rule: '', maintenance_cycles: ['all'],
};

let container = null;
let store = null;

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

async function renderPage() {
  const Page = loadPage();
  await act(async () => {
    ReactDOM.render(<Page store={store}/>, container);
  });
  await flush();
}

function buttonByText(text, root) {
  const scope = root || container;
  return Array.from(scope.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
}

function findTd(coordinate) {
  return container.querySelector(`td[data-coord="${coordinate}"]`);
}

function dispatchMouse(type, target, init = {}) {
  const event = new window.MouseEvent(type, {bubbles: true, cancelable: true, ...init});
  target.dispatchEvent(event);
}

/** React 16 受控输入：原生 value setter + input 事件 */
function setInputValue(element, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(element, value);
  element.dispatchEvent(new window.Event('input', {bubbles: true}));
}

/** 真实点击单元格选中（非 Ctrl，走单格绑定面板） */
async function clickCell(coordinate) {
  await act(async () => {
    dispatchMouse('click', findTd(coordinate));
  });
  await flush();
}

async function ctrlClickCell(coordinate) {
  await act(async () => {
    dispatchMouse('click', findTd(coordinate), {ctrlKey: true});
  });
  await flush();
}

const nameInput = () => container.querySelector('[data-testid="binding-field-name"]');
const putBindings = () => mockHttpPut.mock.calls[0][1].field_bindings;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  store = new ExcelTemplateStore();
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
  store = null;
});

test('单格新绑定：名称预填「工作表 · 坐标」，不输入直接保存载荷非空', async () => {
  store.applyDetail({data: makeDetail()});
  mockHttpPut.mockResolvedValue({data: makeDetail([BOUND_PS])});
  await renderPage();
  await clickCell('C4');
  // 面板名称输入框已预填默认名，保存按钮不再因名称为空而禁用
  expect(nameInput().value).toBe('信道维护记录 · C4');
  expect(buttonByText('保存绑定').disabled).toBe(false);
  await act(async () => {
    buttonByText('保存绑定').click();
  });
  await flush();
  expect(mockHttpPut).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/bindings/',
    expect.objectContaining({field_bindings: expect.any(Array)}));
  const payload = putBindings()[0];
  expect(payload.field_name).toBe('信道维护记录 · C4');
  expect(payload.sheet_name).toBe('信道维护记录');
  expect(payload.cell_coordinate).toBe('C4');
  expect(payload.field_id).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(message.success).toHaveBeenCalledWith('绑定已保存');
});

test('单格清空名称后保存：回退默认名，载荷仍非空', async () => {
  store.applyDetail({data: makeDetail()});
  mockHttpPut.mockResolvedValue({data: makeDetail([BOUND_PS])});
  await renderPage();
  await clickCell('C4');
  await act(async () => {
    setInputValue(nameInput(), '');
  });
  await flush();
  expect(buttonByText('保存绑定').disabled).toBe(false);
  await act(async () => {
    buttonByText('保存绑定').click();
  });
  await flush();
  expect(putBindings()[0].field_name).toBe('信道维护记录 · C4');
});

test('单格自定义名称：保存载荷使用自定义名称', async () => {
  store.applyDetail({data: makeDetail()});
  mockHttpPut.mockResolvedValue({data: makeDetail([BOUND_PS])});
  await renderPage();
  await clickCell('C4');
  await act(async () => {
    setInputValue(nameInput(), 'PS 模块电压');
  });
  await flush();
  await act(async () => {
    buttonByText('保存绑定').click();
  });
  await flush();
  expect(putBindings()[0].field_name).toBe('PS 模块电压');
});

test('编辑已有绑定：名称保持自定义值不变，field_id 稳定', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS])});
  mockHttpPut.mockResolvedValue({data: makeDetail([BOUND_PS])});
  await renderPage();
  await clickCell('C4');
  // 已有自定义名称「PS模块」不被默认名覆盖
  expect(nameInput().value).toBe('PS模块');
  expect(buttonByText('更新绑定')).toBeTruthy();
  await act(async () => {
    buttonByText('更新绑定').click();
  });
  await flush();
  const payload = putBindings()[0];
  expect(payload.field_name).toBe('PS模块');
  expect(payload.field_id).toBe(FIELD_PS);
  expect(payload.cell_coordinate).toBe('C4');
});

test('批量绑定不填前缀：预览即默认名，直接保存每格「工作表 · 坐标」', async () => {
  store.applyDetail({data: makeDetail()});
  const savedDetail = makeDetail([
    {...BOUND_PS},
    {field_id: 'aaaaaaaa-1111-4aaa-8aaa-000000000002', sheet_name: '信道维护记录',
     cell_coordinate: 'D4', field_name: '信道维护记录 · D4', input_type: 'status',
     is_required: true, unit: '', options: ['正常', '异常']},
  ]);
  mockHttpPut.mockResolvedValue({data: savedDetail});
  mockHttpGet.mockResolvedValue({data: savedDetail});
  await renderPage();
  await ctrlClickCell('D4');
  await ctrlClickCell('C4');
  // 不输入任何名称：预览直接给出每格默认名，保存按钮可用
  const preview = container.querySelector('[data-testid="batch-preview"]').textContent;
  expect(preview).toContain('C4 → 信道维护记录 · C4');
  expect(preview).toContain('D4 → 信道维护记录 · D4');
  expect(container.querySelector('[data-testid="batch-save"]').disabled).toBe(false);
  await act(async () => {
    container.querySelector('[data-testid="batch-save"]').click();
  });
  await flush();
  const payload = putBindings();
  expect(payload).toHaveLength(2);
  expect(payload.map(b => b.field_name)).toEqual([
    '信道维护记录 · C4', '信道维护记录 · D4']);
  expect(payload.map(b => b.cell_coordinate)).toEqual(['C4', 'D4']);
  const ids = payload.map(b => b.field_id);
  expect(new Set(ids).size).toBe(2);
  ids.forEach(id => expect(id).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/));
  expect(message.success).toHaveBeenCalledWith('已批量绑定 2 个字段');
});

test('批量绑定填写前缀：仍生成「前缀-坐标」', async () => {
  store.applyDetail({data: makeDetail()});
  const savedDetail = makeDetail([
    {...BOUND_PS},
    {field_id: 'aaaaaaaa-1111-4aaa-8aaa-000000000002', sheet_name: '信道维护记录',
     cell_coordinate: 'D4', field_name: '主电台 PS-D4', input_type: 'status',
     is_required: true, unit: '', options: ['正常', '异常']},
  ]);
  mockHttpPut.mockResolvedValue({data: savedDetail});
  mockHttpGet.mockResolvedValue({data: savedDetail});
  await renderPage();
  await ctrlClickCell('C4');
  await ctrlClickCell('D4');
  await act(async () => {
    setInputValue(container.querySelector('[data-testid="batch-prefix"]'), '主电台 PS');
  });
  await flush();
  const preview = container.querySelector('[data-testid="batch-preview"]').textContent;
  expect(preview).toContain('C4 → 主电台 PS-C4');
  expect(preview).toContain('D4 → 主电台 PS-D4');
  await act(async () => {
    container.querySelector('[data-testid="batch-save"]').click();
  });
  await flush();
  expect(putBindings().map(b => b.field_name)).toEqual(['主电台 PS-C4', '主电台 PS-D4']);
});

test('批量绑定单格填前缀：直接使用前缀作为字段名', async () => {
  store.applyDetail({data: makeDetail()});
  mockHttpPut.mockResolvedValue({data: makeDetail([BOUND_PS])});
  mockHttpGet.mockResolvedValue({data: makeDetail([BOUND_PS])});
  await renderPage();
  await ctrlClickCell('E4');
  await act(async () => {
    setInputValue(container.querySelector('[data-testid="batch-prefix"]'), '主电台 PS');
  });
  await flush();
  expect(container.querySelector('[data-testid="batch-preview"]').textContent)
    .toContain('E4 → 主电台 PS');
  await act(async () => {
    container.querySelector('[data-testid="batch-save"]').click();
  });
  await flush();
  expect(putBindings()[0].field_name).toBe('主电台 PS');
});

test('批量绑定不填前缀且仅选一格：默认名「工作表 · 坐标」', async () => {
  store.applyDetail({data: makeDetail()});
  mockHttpPut.mockResolvedValue({data: makeDetail([BOUND_PS])});
  mockHttpGet.mockResolvedValue({data: makeDetail([BOUND_PS])});
  await renderPage();
  await ctrlClickCell('E4');
  await act(async () => {
    container.querySelector('[data-testid="batch-save"]').click();
  });
  await flush();
  expect(putBindings()[0].field_name).toBe('信道维护记录 · E4');
});

test('跨工作表：切换工作表后默认名携带所在工作表名', async () => {
  const twoSheets = makeDetail();
  twoSheets.draft.layout.sheets.push({
    name: '维护结论', max_row: 4, max_column: 3, merged_ranges: [],
    row_heights: {}, column_widths: {},
    cells: {A1: {v: '维护结论'}, B1: {v: '内容（填写）'}},
    print: {orientation: 'portrait', paper_size: 9},
  });
  store.applyDetail({data: twoSheets});
  mockHttpPut.mockResolvedValue({data: makeDetail([BOUND_PS])});
  await renderPage();
  // 真实点击第二个工作表页签（走 store.setSheet，清空选区）
  const tabs = container.querySelector('[data-testid="tpl-sheet-tabs"]');
  await act(async () => {
    tabs.querySelectorAll('.ant-tabs-tab')[1]
      .dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
  });
  await flush();
  expect(store.activeSheet).toBe('维护结论');
  // C3 为空白可绑定格（B1 有内容会进 blockReason，不出现表单）
  await clickCell('C3');
  expect(nameInput().value).toBe('维护结论 · C3');
  await act(async () => {
    buttonByText('保存绑定').click();
  });
  await flush();
  const payload = putBindings()[0];
  expect(payload.sheet_name).toBe('维护结论');
  expect(payload.field_name).toBe('维护结论 · C3');
  expect(payload.cell_coordinate).toBe('C3');
});
