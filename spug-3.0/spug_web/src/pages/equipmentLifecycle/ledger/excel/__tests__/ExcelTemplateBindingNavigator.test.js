/**
 * Excel 台账模板绑定字段导航测试（真实渲染 + jsdom + http mock，2026-10-19
 * 自 ExcelTemplatePageWorkspace.test.js 拆分，其余工作区交互见同文件）。
 *
 * 覆盖工作区改版新增的左侧「已绑定字段」导航：条目渲染（字段名/坐标/
 * 必填标记）→ 点击当前工作表条目选中对应单元格（且不反选）→ 跨工作表
 * 条目点击后切换工作表并选中目标单元格（批量选区一并清空）→ 搜索过滤
 * 与无匹配占位 → 已停用模板条目禁用且点击不产生定位。
 * 全部走真实组件与 store 代码路径，http 仅打桩。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

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

async function ctrlClickCell(coordinate) {
  await act(async () => {
    dispatchMouse('click', findTd(coordinate), {ctrlKey: true});
  });
  await flush();
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  store = new ExcelTemplateStore();
  jest.clearAllMocks();
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    document.body.removeChild(container);
  }
  container = null;
  store = null;
});

test('绑定导航：列出全部绑定，点击当前工作表条目选中对应单元格', async () => {
  const second = {...BOUND_PS, field_id: 'aaaaaaaa-1111-4aaa-8aaa-000000000002',
    cell_coordinate: 'E4', field_name: 'TX模块', is_required: false};
  store.applyDetail({data: makeDetail([BOUND_PS, second])});
  await renderPage();
  const rows = container.querySelectorAll('[data-testid="tpl-binding-item"]');
  expect(rows).toHaveLength(2);
  expect(rows[0].textContent).toContain('PS模块');
  expect(rows[0].textContent).toContain('C4');
  expect(rows[0].textContent).toContain('必填');
  expect(rows[1].textContent).toContain('TX模块');
  // 点击当前工作表条目 → 单格选中，字段面板显示已有绑定（更新绑定）
  await act(async () => {
    rows[1].click();
  });
  await flush();
  expect(store.selectedCell).toBe('E4');
  expect(store.selectedCells).toEqual([]);
  expect(container.querySelector('[data-testid="tpl-status-tag"]').textContent)
    .toContain('草稿');
  expect(container.textContent).toContain('更新绑定');
  // 点击已选条目不会反选（与 selectCell 的切换语义区分）
  await act(async () => {
    rows[1].click();
  });
  await flush();
  expect(store.selectedCell).toBe('E4');
});

test('绑定导航：跨工作表条目点击后切换工作表并选中目标单元格', async () => {
  const detail = makeDetail([BOUND_PS]);
  detail.draft.layout.sheets.push({
    name: '维护结论', max_row: 4, max_column: 2, merged_ranges: [],
    row_heights: {}, column_widths: {},
    cells: {A1: {v: '维护结论'}, B1: {v: '内容（填写）'}},
    print: {orientation: 'portrait', paper_size: 9},
  });
  const conclusion = {field_id: 'aaaaaaaa-1111-4aaa-8aaa-000000000003',
    sheet_name: '维护结论', cell_coordinate: 'B1', field_name: '维护结论',
    input_type: 'text', is_required: false, unit: '', options: []};
  detail.draft.field_bindings.push(conclusion);
  store.applyDetail({data: detail});
  await renderPage();
  // 初始在第一个工作表，批量选区存在
  await ctrlClickCell('D4');
  expect(store.activeSheet).toBe('信道维护记录');
  const rows = container.querySelectorAll('[data-testid="tpl-binding-item"]');
  expect(rows).toHaveLength(2);
  // 点击另一工作表的条目 → 切换工作表、清空批量选区、选中目标格
  await act(async () => {
    rows[1].click();
  });
  await flush();
  expect(store.activeSheet).toBe('维护结论');
  expect(store.selectedCell).toBe('B1');
  expect(store.selectedCells).toEqual([]);
  // 字段面板跟随工作表切换展示该绑定（key 重挂载后呈现更新绑定按钮）
  expect(container.textContent).toContain('更新绑定');
  // 切回：点击第一个工作表的条目同样能跨表定位
  await act(async () => {
    rows[0].click();
  });
  await flush();
  expect(store.activeSheet).toBe('信道维护记录');
  expect(store.selectedCell).toBe('C4');
});

test('绑定导航：搜索过滤无匹配显示占位，清空后恢复全部', async () => {
  const second = {...BOUND_PS, field_id: 'aaaaaaaa-1111-4aaa-8aaa-000000000002',
    cell_coordinate: 'E4', field_name: 'TX模块', is_required: false};
  store.applyDetail({data: makeDetail([BOUND_PS, second])});
  await renderPage();
  expect(container.querySelectorAll('[data-testid="tpl-binding-item"]')).toHaveLength(2);
  await act(async () => {
    setInputValue(container.querySelector('[data-testid="tpl-binding-search"]'), 'TX');
  });
  await flush();
  const rows = container.querySelectorAll('[data-testid="tpl-binding-item"]');
  expect(rows).toHaveLength(1);
  expect(rows[0].textContent).toContain('TX模块');
  // 无匹配 → 占位提示；清空 → 全部恢复
  await act(async () => {
    setInputValue(container.querySelector('[data-testid="tpl-binding-search"]'), '不存在');
  });
  await flush();
  expect(container.querySelectorAll('[data-testid="tpl-binding-item"]')).toHaveLength(0);
  expect(container.textContent).toContain('没有匹配字段');
  await act(async () => {
    setInputValue(container.querySelector('[data-testid="tpl-binding-search"]'), '');
  });
  await flush();
  expect(container.querySelectorAll('[data-testid="tpl-binding-item"]')).toHaveLength(2);
});

test('绑定导航：已停用模板条目禁用且点击不产生定位', async () => {
  const detail = makeDetail([BOUND_PS], {is_active: false});
  store.applyDetail({data: detail});
  await renderPage();
  const row = container.querySelector('[data-testid="tpl-binding-item"]');
  expect(row.disabled).toBe(true);
  await act(async () => {
    row.click();
  });
  await flush();
  expect(store.selectedCell).toBe('');
  expect(store.activeSheet).toBe('信道维护记录');
});
