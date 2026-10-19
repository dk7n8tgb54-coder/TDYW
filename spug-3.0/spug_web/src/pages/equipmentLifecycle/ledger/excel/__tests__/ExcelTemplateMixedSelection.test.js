/**
 * Excel 台账模板混合选区批量操作测试（真实渲染 + jsdom + http mock，
 * 2026-10-19 自 ExcelTemplatePageWorkspace.test.js 拆分出独立关注点）。
 *
 * 覆盖：从已绑定格开始拖拽（已绑定+未绑定混合选区，仍剔除表头内容格）
 * → 面板显示选中总数/已绑定数/未绑定数与预览保留自定义名称 → 混合批量
 * 保存（已有绑定保留 field_id 与自定义名称、仅更新明确修改过的属性，
 * 未触碰属性原样保留；新绑定按规则自动命名）→ 批量解绑独立操作
 * （取消不发请求，确认后移除选区内已绑定字段）→ 拖拽期间阻止浏览器
 * 文字选择（松开/离开窗口/Escape 取消后恢复，内容格 mousedown 不拦截）
 * → 单击编辑单个字段行为保持不变（含批量解绑按钮按选区绑定数启用）。
 * 全部走真实组件与 store 代码路径（真实点击/拖拽/键盘），http 仅打桩。
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
const FIELD_TX = 'aaaaaaaa-1111-4aaa-8aaa-000000000002';

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
  unit: '', options: ['正常', '异常'],
};

const BOUND_TX = {
  field_id: FIELD_TX, sheet_name: '信道维护记录', cell_coordinate: 'D4',
  field_name: 'TX功率', input_type: 'text', is_required: false,
  unit: 'V', options: [],
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

function popconfirmButton(text) {
  return Array.from(document.body.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text);
}

function findTd(coordinate) {
  return container.querySelector(`td[data-coord="${coordinate}"]`);
}

function dispatchMouse(type, target, init = {}) {
  const event = new window.MouseEvent(type, {bubbles: true, cancelable: true, ...init});
  target.dispatchEvent(event);
}

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

async function dragSelect(fromCoord, toCoord) {
  await act(async () => {
    dispatchMouse('mousedown', findTd(fromCoord), {button: 0});
    dispatchMouse('mouseover', findTd(toCoord));
    dispatchMouse('mouseup', document, {button: 0});
  });
  await flush();
}

const summary = () => container.querySelector('[data-testid="batch-selection-summary"]');
const preview = () => container.querySelector('[data-testid="batch-preview"]');
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

test('从已绑定格开始拖拽：混合选区成立并仍剔除内容格，面板计数与预览正确', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS])});
  await renderPage();
  // C4 已绑定、D4/E4 未绑定：从已绑定格 C4 拖到 E4 → 三格全部入选
  await dragSelect('C4', 'E4');
  expect(store.selectedCells.slice().sort()).toEqual(['C4', 'D4', 'E4']);
  // 面板摘要：选中总数/已绑定数/未绑定数
  expect(summary().textContent).toContain('已选 3 格：已绑定 1 · 未绑定 2');
  // 预览：已绑定格保留自定义名称，未绑定格按规则生成默认名
  expect(preview().textContent).toContain('C4 → PS模块（已绑定·名称保留）');
  expect(preview().textContent).toContain('D4 → 信道维护记录 · D4');
  expect(preview().textContent).toContain('E4 → 信道维护记录 · E4');
  // 选区内有已绑定格 → 批量解绑按钮可用
  expect(container.querySelector('[data-testid="batch-unbind"]').disabled).toBe(false);
  // 拖拽矩形覆盖内容格（C2 表头）→ 内容格仍被剔除，只保留 C3/C4
  await dragSelect('C4', 'C2');
  expect(store.selectedCells.slice().sort()).toEqual(['C3', 'C4']);
  expect(summary().textContent).toContain('已选 2 格：已绑定 1 · 未绑定 1');
});

test('混合批量保存：已有绑定保留 field_id 与自定义名称，仅更新明确修改的属性', async () => {
  const psUnitMv = {...BOUND_PS, is_required: false, unit: 'mV'};
  store.applyDetail({data: makeDetail([psUnitMv])});
  const savedDetail = makeDetail([
    {...psUnitMv, is_required: true},
    {field_id: 'bbbbbbbb-2222-4bbb-8bbb-000000000009', sheet_name: '信道维护记录',
     cell_coordinate: 'E4', field_name: '信道维护记录 · E4', input_type: 'text',
     is_required: true, unit: '', options: []},
  ]);
  mockHttpPut.mockResolvedValue({data: savedDetail});
  mockHttpGet.mockResolvedValue({data: savedDetail});
  await renderPage();
  await ctrlClickCell('C4');
  await ctrlClickCell('E4');
  // 仅勾选「必填字段」：input_type/单位/候选项均未触碰
  await act(async () => {
    container.querySelector('.proto-field-panel .ant-checkbox-input').click();
  });
  await flush();
  await act(async () => {
    container.querySelector('[data-testid="batch-save"]').click();
  });
  await flush();
  expect(mockHttpPut).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/bindings/',
    expect.objectContaining({field_bindings: expect.any(Array)}));
  const payload = putBindings();
  expect(payload).toHaveLength(2);
  // 已绑定格：field_id 与自定义名称保留，未触碰属性原样保留
  const kept = payload.find(b => b.cell_coordinate === 'C4');
  expect(kept.field_id).toBe(FIELD_PS);
  expect(kept.field_name).toBe('PS模块');
  expect(kept.input_type).toBe('status');
  expect(kept.options).toEqual(['正常', '异常']);
  expect(kept.unit).toBe('mV');
  // 明确修改过的属性（必填）应用到已有绑定
  expect(kept.is_required).toBe(true);
  // 未绑定格：新 UUID + 自动命名，属性取表单值
  const added = payload.find(b => b.cell_coordinate === 'E4');
  expect(added.field_id).not.toBe(FIELD_PS);
  expect(added.field_name).toBe('信道维护记录 · E4');
  expect(added.input_type).toBe('text');
  expect(added.is_required).toBe(true);
  expect(added.unit).toBe('');
  expect(message.success).toHaveBeenCalledWith('批量保存完成：更新 1 个、新增 1 个字段');
  // 保存成功后选区清空
  expect(store.selectedCells).toEqual([]);
});

test('批量解绑为独立操作：取消不发请求，确认后移除选区内已绑定字段', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS, BOUND_TX])});
  mockHttpPut.mockResolvedValue({data: makeDetail([])});
  await renderPage();
  await ctrlClickCell('C4');
  await ctrlClickCell('D4');
  expect(summary().textContent).toContain('已选 2 格：已绑定 2 · 未绑定 0');
  // 点击批量解绑 → Popconfirm 要求确认
  await act(async () => {
    container.querySelector('[data-testid="batch-unbind"]').click();
  });
  await flush();
  expect(document.body.textContent)
    .toContain('将解绑选区内 2 个已绑定字段，解绑后需重新配置，确定？');
  // 取消 → 不发任何请求，绑定与选区保持不变
  await act(async () => {
    popconfirmButton('取消').click();
  });
  await flush();
  expect(mockHttpPut).not.toHaveBeenCalled();
  expect(store.bindings).toHaveLength(2);
  expect(store.selectedCells.slice().sort()).toEqual(['C4', 'D4']);
  // 再次点击并确认 → PUT 载荷不再包含选区内两个绑定
  await act(async () => {
    container.querySelector('[data-testid="batch-unbind"]').click();
  });
  await flush();
  await act(async () => {
    popconfirmButton('解绑').click();
  });
  await flush();
  expect(mockHttpPut).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/bindings/',
    expect.objectContaining({field_bindings: []}));
  expect(message.success).toHaveBeenCalledWith('已解绑 2 个字段');
  expect(store.bindings).toHaveLength(0);
  expect(store.selectedCells).toEqual([]);
});

test('拖拽期间阻止浏览器文字选择：松开/离开窗口/Escape 取消后恢复', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS])});
  await renderPage();
  const downs = [];
  container.addEventListener('mousedown', event => downs.push(event));
  // 从已绑定格开始拖拽 → mousedown 阻止默认行为（文字选择锚点），
  // 表格容器进入禁选状态（类 + 内联 user-select:none）
  await act(async () => {
    dispatchMouse('mousedown', findTd('C4'), {button: 0});
  });
  expect(store.isDragging).toBe(true);
  expect(downs[downs.length - 1].defaultPrevented).toBe(true);
  let wrap = container.querySelector('.proto-table-wrap');
  expect(wrap.className).toContain('proto-drag-selecting');
  expect(wrap.style.userSelect).toBe('none');
  // 拖动扩展选区期间保持禁选
  await act(async () => {
    dispatchMouse('mouseover', findTd('E4'));
  });
  expect(store.selectedCells.slice().sort()).toEqual(['C4', 'D4', 'E4']);
  expect(container.querySelector('.proto-table-wrap').style.userSelect).toBe('none');
  // 松开鼠标 → 拖拽结束，恢复正常文字选择
  await act(async () => {
    dispatchMouse('mouseup', document, {button: 0});
  });
  await flush();
  expect(store.isDragging).toBe(false);
  wrap = container.querySelector('.proto-table-wrap');
  expect(wrap.className).not.toContain('proto-drag-selecting');
  expect(wrap.style.userSelect).toBe('');
  // 内容格（C2 表头）mousedown 不启动拖拽、不拦截文字选择
  await act(async () => {
    dispatchMouse('mousedown', findTd('C2'), {button: 0});
  });
  expect(store.isDragging).toBe(false);
  expect(downs[downs.length - 1].defaultPrevented).toBe(false);
  expect(container.querySelector('.proto-table-wrap').style.userSelect).toBe('');
  await act(async () => {
    dispatchMouse('mouseup', document, {button: 0});
  });
  // Escape 取消拖拽：选区清空并恢复正常文字选择
  await act(async () => {
    dispatchMouse('mousedown', findTd('C4'), {button: 0});
    dispatchMouse('mouseover', findTd('D4'));
  });
  expect(store.selectedCells).toHaveLength(2);
  expect(store.isDragging).toBe(true);
  await act(async () => {
    document.dispatchEvent(
      new window.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  });
  await flush();
  expect(store.isDragging).toBe(false);
  expect(store.selectedCells).toEqual([]);
  expect(container.querySelector('.proto-table-wrap').style.userSelect).toBe('');
  // 鼠标离开窗口 → 拖拽结束并恢复正常文字选择
  await act(async () => {
    dispatchMouse('mousedown', findTd('C4'), {button: 0});
  });
  expect(store.isDragging).toBe(true);
  await act(async () => {
    document.dispatchEvent(new window.Event('mouseleave'));
  });
  await flush();
  expect(store.isDragging).toBe(false);
  expect(container.querySelector('.proto-table-wrap').style.userSelect).toBe('');
});

test('单击编辑单个字段行为不变；批量解绑按钮随选区绑定数启用', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS])});
  await renderPage();
  // 单击已绑定格 → 仍是单格编辑面板（不进入批量）
  await clickCell('C4');
  expect(store.selectedCell).toBe('C4');
  expect(store.selectedCells).toEqual([]);
  expect(container.textContent).toContain('更新绑定');
  expect(container.querySelector('[data-testid="batch-save"]')).toBeNull();
  // 单击未绑定格 → 新建绑定面板
  await clickCell('E4');
  expect(store.selectedCell).toBe('E4');
  expect(container.textContent).toContain('保存绑定');
  // Ctrl 选未绑定格 → 批量面板出现，无已绑定格时解绑按钮禁用
  await ctrlClickCell('E4');
  expect(container.querySelector('[data-testid="batch-selection-summary"]'))
    .toBeTruthy();
  expect(container.querySelector('[data-testid="batch-unbind"]').disabled)
    .toBe(true);
  // 加选已绑定格 → 解绑按钮启用，计数含已绑定/未绑定
  await ctrlClickCell('C4');
  expect(summary().textContent).toContain('已选 2 格：已绑定 1 · 未绑定 1');
  expect(container.querySelector('[data-testid="batch-unbind"]').disabled)
    .toBe(false);
});
