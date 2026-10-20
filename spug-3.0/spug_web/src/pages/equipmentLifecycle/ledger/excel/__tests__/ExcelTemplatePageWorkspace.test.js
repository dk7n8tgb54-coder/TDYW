/**
 * Excel 台账模板页绑定工作区测试（真实渲染 + jsdom + http mock，2026-10-14
 * 自 ExcelTemplatePage.test.js 拆分，列表页交互见同目录 ExcelTemplatePage.test.js）。
 *
 * 覆盖：选格绑定（保存载荷/服务端拒绝回退）→ 批量绑定（加选/拖拽/命名/
 * 保存）→ 多工作表切换清空选区 → 编辑页头部信息与左侧返回 → 发布按钮
 * 真实条件约束（无绑定/兼容性 error 禁用并说明原因，UI 全流程发布）→
 * 版本抽屉 → 替换源文件确认与取消 → 已停用模板只读冻结 → 「预览空白
 * 打印稿」→ 兼容性提示 → 填写区尺寸提示。绑定字段导航（2026-10-19
 * 工作区改版）与混合选区批量修改/解绑/拖拽禁文字选择（同日）另见同目录
 * ExcelTemplateBindingNavigator.test.js、ExcelTemplateMixedSelection.test.js。
 * 全部走真实组件与 store 代码路径，http/exportFile 仅打桩。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();
const mockExportFile = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: mockHttpDelete},
  exportFile: mockExportFile,
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

async function dragSelect(fromCoord, toCoord) {
  await act(async () => {
    dispatchMouse('mousedown', findTd(fromCoord), {button: 0});
    dispatchMouse('mouseover', findTd(toCoord));
    dispatchMouse('mouseup', document, {button: 0});
  });
  await flush();
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  store = new ExcelTemplateStore();
  jest.clearAllMocks();
  require('libs').hasPermission.mockReturnValue(true);
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

test('选格绑定：保存载荷走 PUT 且 field_id 为 UUID（不携带退役属性）', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  mockHttpPut.mockResolvedValue({data: makeDetail([BOUND_PS])});
  await renderPage();
  await act(async () => {
    store.selectCell('C4');
  });
  await flush();
  // 字段面板出现
  expect(container.querySelector('.proto-field-panel')).toBeTruthy();
  await act(async () => {
    await store.saveBinding({
      field_name: 'PS模块', input_type: 'status', is_required: true,
      unit: '', options: [],
    });
  });
  expect(mockHttpPut).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/bindings/',
    expect.objectContaining({field_bindings: expect.any(Array)}));
  const payload = mockHttpPut.mock.calls[0][1];
  expect(payload.field_bindings[0].cell_coordinate).toBe('C4');
  expect(payload.field_bindings[0].field_id).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(Object.keys(payload.field_bindings[0]).sort()).toEqual([
    'cell_coordinate', 'field_id', 'field_name', 'input_type',
    'is_required', 'options', 'sheet_name', 'unit']);
  expect(message.success).toHaveBeenCalledWith('绑定已保存');
});

test('绑定保存失败回退本地且不保留新绑定', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  mockHttpPut.mockRejectedValue(new Error('单元格已有内容'));
  await renderPage();
  await act(async () => {
    store.selectCell('C4');
  });
  await flush();
  await act(async () => {
    await expect(store.saveBinding({
      field_name: 'X', input_type: 'text', is_required: false,
    })).rejects.toThrow('单元格已有内容');
  });
  expect(store.bindings).toHaveLength(0);
});

test('Ctrl 加选多格显示批量面板与数量，可清空选择', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  await renderPage();
  expect(container.querySelector('[data-testid="batch-clear"]')).toBeNull();
  await ctrlClickCell('C4');
  await ctrlClickCell('E4');
  expect(store.selectedCells.slice().sort()).toEqual(['C4', 'E4']);
  // 已绑定单元格也可加选（2026-10-19 混合选区），面板摘要含绑定拆分
  const boundDetail = makeDetail([BOUND_PS]);
  store.applyDetail({data: boundDetail});
  await flush();
  await ctrlClickCell('C4');
  await ctrlClickCell('D4');
  expect(store.selectedCells.slice().sort()).toEqual(['C4', 'D4']);
  expect(container.textContent).toContain('批量绑定');
  expect(container.textContent).toContain('已选 2 格');
  expect(container.querySelector('[data-testid="batch-selection-summary"]').textContent)
    .toContain('已选 2 格：已绑定 1 · 未绑定 1');
  // Ctrl 再点已选格 → 取消单个选择；全部清掉后批量面板消失
  await ctrlClickCell('D4');
  expect(store.selectedCells).toEqual(['C4']);
  await ctrlClickCell('C4');
  expect(store.selectedCells).toEqual([]);
  expect(container.querySelector('[data-testid="batch-clear"]')).toBeNull();
  // 重新选两格后点「清空选择」按钮
  await ctrlClickCell('D4');
  await ctrlClickCell('E4');
  expect(store.selectedCells.slice().sort()).toEqual(['D4', 'E4']);
  await act(async () => {
    container.querySelector('[data-testid="batch-clear"]').click();
  });
  await flush();
  expect(store.selectedCells).toEqual([]);
  expect(container.querySelector('[data-testid="batch-clear"]')).toBeNull();
});

test('单击选中单元格显示蓝框（与拖拽选区同样反馈），再点取消', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  await renderPage();
  const tdOf = coordinate => container.querySelector(`td[data-coord="${coordinate}"]`);
  // 普通单击 → 与拖拽选区同样的蓝框（此前单击只加无样式 class，无反馈）
  await act(async () => {
    tdOf('C4').click();
  });
  await flush();
  expect(store.selectedCell).toBe('C4');
  expect(tdOf('C4').className).toContain('proto-cell-in-selection');
  expect(tdOf('C4').style.boxShadow).toContain('inset');
  // 再点同一格 → 取消选中，蓝框消失
  await act(async () => {
    tdOf('C4').click();
  });
  await flush();
  expect(store.selectedCell).toBe('');
  expect(tdOf('C4').style.boxShadow).toBe('');
  // 点另一格 → 蓝框跟随，原格恢复
  await act(async () => {
    tdOf('D4').click();
  });
  await flush();
  expect(store.selectedCell).toBe('D4');
  expect(tdOf('C4').style.boxShadow).toBe('');
  expect(tdOf('D4').style.boxShadow).toContain('inset');
});

test('拖拽矩形多选并剔除内容格', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  await renderPage();
  // C4 向上拖到 C2：C2 是有内容的表头格，只保留 C3/C4
  await dragSelect('C4', 'C2');
  expect(store.selectedCells.slice().sort()).toEqual(['C3', 'C4']);
  // 横向矩形 C3→D4：整块可绑定格入选
  await dragSelect('C3', 'D4');
  expect(store.selectedCells.slice().sort()).toEqual(['C3', 'C4', 'D3', 'D4']);
  // mousedown 在内容格（C2）不启动拖拽，选区不变
  await act(async () => {
    dispatchMouse('mousedown', findTd('C2'), {button: 0});
    dispatchMouse('mouseover', findTd('D3'));
    dispatchMouse('mouseup', document, {button: 0});
  });
  await flush();
  expect(store.selectedCells.slice().sort()).toEqual(['C3', 'C4', 'D3', 'D4']);
  // 拖拽后松开鼠标（window mouseup）结束选区扩展
  expect(store.isDragging).toBe(false);
});

test('批量面板预览：多格生成「前缀-坐标」，单格保留前缀', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  await renderPage();
  await ctrlClickCell('C4');
  await ctrlClickCell('D4');
  const prefixInput = container.querySelector('[data-testid="batch-prefix"]');
  await act(async () => {
    setInputValue(prefixInput, '主电台 PS');
  });
  await flush();
  const preview = container.querySelector('[data-testid="batch-preview"]').textContent;
  expect(preview).toContain('C4 → 主电台 PS-C4');
  expect(preview).toContain('D4 → 主电台 PS-D4');
  // 单格：保留用户输入的字段名称，不追加坐标
  await ctrlClickCell('D4'); // 取消 D4
  await flush();
  expect(container.querySelector('[data-testid="batch-preview"]').textContent)
    .toContain('C4 → 主电台 PS');
});

test('批量保存：载荷独立 UUID 与命名，成功后重取详情并清空选区', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
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
  await act(async () => {
    container.querySelector('[data-testid="batch-save"]').click();
  });
  await flush();
  expect(mockHttpPut).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/bindings/',
    expect.objectContaining({field_bindings: expect.any(Array)}));
  const payload = mockHttpPut.mock.calls[0][1].field_bindings;
  expect(payload).toHaveLength(2);
  expect(payload.map(b => b.field_name).sort()).toEqual(['主电台 PS-C4', '主电台 PS-D4']);
  expect(payload.map(b => b.cell_coordinate).sort()).toEqual(['C4', 'D4']);
  const ids = payload.map(b => b.field_id);
  expect(new Set(ids).size).toBe(2);
  ids.forEach(id => expect(id).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/));
  // 服务端数据成为最终状态：重取详情接口被调用
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/');
  expect(store.bindings).toHaveLength(2);
  expect(store.selectedCells).toEqual([]);
  expect(message.success).toHaveBeenCalledWith('已批量绑定 2 个字段');
});

test('批量保存失败：本地状态回退且不显示成功提示', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  mockHttpPut.mockRejectedValue(new Error('字段绑定数量超过上限'));
  await renderPage();
  await ctrlClickCell('C4');
  await ctrlClickCell('D4');
  await act(async () => {
    setInputValue(container.querySelector('[data-testid="batch-prefix"]'), '主电台 PS');
  });
  await act(async () => {
    await expect(store.saveBatchBinding({
      field_name: '主电台 PS', input_type: 'status', is_required: true,
      unit: '', options: [],
    })).rejects.toThrow('字段绑定数量超过上限');
  });
  await flush();
  expect(store.bindings).toHaveLength(0);
  expect(message.success).not.toHaveBeenCalled();
});

test('多工作表切换入口：点击页签清理单格与批量选区，单工作表不显示', async () => {
  const twoSheets = makeDetail();
  twoSheets.draft.layout.sheets.push({
    name: '维护结论', max_row: 4, max_column: 2, merged_ranges: [],
    row_heights: {}, column_widths: {},
    cells: {A1: {v: '维护结论'}, B1: {v: '内容（填写）'}},
    print: {orientation: 'portrait', paper_size: 9},
  });
  store.applyDetail({data: twoSheets});
  await renderPage();
  const tabs = container.querySelector('[data-testid="tpl-sheet-tabs"]');
  expect(tabs).toBeTruthy();
  expect(tabs.querySelectorAll('.ant-tabs-tab')).toHaveLength(2);
  // 单格 + 批量选区并存
  await ctrlClickCell('C4');
  await ctrlClickCell('E4');
  expect(store.selectedCells.slice().sort()).toEqual(['C4', 'E4']);
  store.selectCell('B4');
  expect(store.selectedCell).toBe('B4');
  // 点击第二个工作表页签（真实 Tabs 点击，走 store.setSheet）
  const secondTab = tabs.querySelectorAll('.ant-tabs-tab')[1];
  await act(async () => {
    secondTab.dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
  });
  await flush();
  expect(store.activeSheet).toBe('维护结论');
  // 单格与批量选区都被清理
  expect(store.selectedCell).toBe('');
  expect(store.selectedCells).toEqual([]);
  // 单工作表：不渲染切换入口
  store.applyDetail({data: makeDetail([BOUND_PS])});
  await flush();
  expect(container.querySelector('[data-testid="tpl-sheet-tabs"]')).toBeNull();
});

test('单格绑定面板不再出现退役属性控件', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  await renderPage();
  await act(async () => {
    store.selectCell('C4');
  });
  await flush();
  expect(container.querySelector('.proto-field-panel')).toBeTruthy();
  const text = container.querySelector('.proto-field-panel').textContent;
  expect(text).not.toContain('默认值');
  expect(text).not.toContain('操作指导');
  expect(text).not.toContain('异常判定规则');
  expect(text).not.toContain('适用维护周期');
});

test('编辑页头部信息完整，左侧返回入口点击后回到列表', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS], {
    latest_version_no: 2, versions_count: 3,
  })});
  await renderPage();
  // 标题区：名称 + 类型；信息行：源文件/绑定字段数/当前版本
  expect(container.textContent).toContain('信道Excel维护台账');
  expect(container.textContent).toContain('周月维护');
  expect(container.querySelector('[data-testid="tpl-source-file"]').textContent)
    .toContain('channel.xlsx');
  expect(container.querySelector('[data-testid="tpl-binding-count"]').textContent)
    .toContain('绑定字段：1 个');
  expect(container.querySelector('[data-testid="tpl-version-line"]').textContent)
    .toContain('当前版本：v2（共 3 个）');
  // 左侧返回入口 → 清空当前模板回到列表
  expect(container.querySelector('[data-testid="tpl-back"]')).toBeTruthy();
  await act(async () => {
    container.querySelector('[data-testid="tpl-back"]').click();
  });
  await flush();
  expect(store.current).toBeNull();
  expect(container.querySelector('[data-testid="tpl-create"]')).toBeTruthy();
});

test('发布按钮与真实条件一致：无绑定/兼容性 error 禁用并说明原因，warning 不阻断', async () => {
  // 无绑定 → 禁用 + 按钮旁原因说明
  store.applyDetail({data: makeDetail([])});
  await renderPage();
  expect(container.querySelector('[data-testid="tpl-publish"]').disabled).toBe(true);
  expect(container.querySelector('[data-testid="tpl-publish-reason"]').textContent)
    .toContain('尚未绑定可填写字段');
  // 兼容性 error → 禁用（即使已有绑定）
  store.applyDetail({data: makeDetail([BOUND_PS])});
  store.current.compatibility = {status: 'error', warnings: [], unsupported: ['公式']};
  await flush();
  expect(container.querySelector('[data-testid="tpl-publish"]').disabled).toBe(true);
  expect(container.querySelector('[data-testid="tpl-publish-reason"]').textContent)
    .toContain('兼容性检查存在问题');
  // 兼容性 warning 不误当作 error：按钮保持可用、无阻断原因
  store.applyDetail({data: makeDetail([BOUND_PS])});
  store.current.compatibility = {
    status: 'warning', warnings: ['未安装 LibreOffice'], unsupported: [],
  };
  await flush();
  expect(container.querySelector('[data-testid="tpl-publish"]').disabled).toBe(false);
  expect(container.querySelector('[data-testid="tpl-publish-reason"]')).toBeNull();
});

test('发布 UI 全流程：确认后 POST 并重取详情刷新版本信息', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS])});
  mockHttpPost.mockResolvedValue({data: {data: {version_no: 1}}});
  mockHttpGet.mockResolvedValue({data: makeDetail([BOUND_PS], {
    latest_version_no: 1, versions_count: 1,
  })});
  await renderPage();
  expect(container.querySelector('[data-testid="tpl-publish"]').disabled).toBe(false);
  await act(async () => {
    container.querySelector('[data-testid="tpl-publish"]').click();
  });
  await flush();
  // Popconfirm 二次确认后点「发布」
  await act(async () => {
    popconfirmButton('发布').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/publish/');
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/');
  expect(store.current.versions_count).toBe(1);
  expect(container.querySelector('[data-testid="tpl-version-line"]').textContent)
    .toContain('v1（共 1 个）');
  expect(message.success).toHaveBeenCalledWith('发布成功');
});

test('版本抽屉渲染不可变版本列表并标注归属模板', async () => {
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  mockHttpGet.mockResolvedValue({data: [
    {id: 5, version_no: 1, template_name: '信道Excel维护台账',
     source_filename: 'channel.xlsx', source_hash: 'a'.repeat(64),
     field_count: 1, published_at: '2026-09-28 11:00:00'},
  ]});
  await renderPage();
  await act(async () => {
    await store.showVersionsFor(store.current);
  });
  await flush();
  expect(mockHttpGet).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/versions/');
  // antd Drawer 渲染进 body portal，须查 document.body（Modal/Drawer portal 惯例）
  expect(document.body.textContent).toContain('已发布版本：信道Excel维护台账');
  expect(document.body.textContent).toContain('v1');
  expect(document.body.textContent).toContain('channel.xlsx');
});

test('替换源文件：选定文件先弹确认并提示清空绑定数，取消不上传', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS])});
  await renderPage();
  await act(async () => {
    container.querySelector('[data-testid="tpl-more-actions"]').click();
  });
  await flush();
  const input = document.body.querySelector('.ant-dropdown input[type="file"]');
  expect(input).toBeTruthy();
  Object.defineProperty(input, 'files', {
    value: [new window.File(['x'], 'channel.xlsx')],
  });
  await act(async () => {
    input.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  await flush();
  // 选定文件只弹确认，不发起上传
  expect(store.reuploadConfirmVisible).toBe(true);
  expect(mockHttpPost).not.toHaveBeenCalled();
  const modal = Array.from(document.body.querySelectorAll('.ant-modal'))
    .find(node => node.textContent.includes('替换源文件'));
  expect(modal.textContent).toContain('将清空现有 1 个字段绑定');
  // 取消 → 弹窗关闭，始终未发请求
  const cancel = Array.from(modal.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === '取消');
  await act(async () => {
    cancel.click();
  });
  await flush();
  expect(store.reuploadConfirmVisible).toBe(false);
  expect(mockHttpPost).not.toHaveBeenCalled();
  expect(store.bindings).toHaveLength(1);
});

test('替换源文件：非 .xlsx 直接拒绝，不弹确认不请求', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS])});
  await renderPage();
  await act(async () => {
    container.querySelector('[data-testid="tpl-more-actions"]').click();
  });
  await flush();
  const input = document.body.querySelector('.ant-dropdown input[type="file"]');
  Object.defineProperty(input, 'files', {
    value: [new window.File(['x'], 'old.xls')],
  });
  await act(async () => {
    input.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  await flush();
  expect(store.reuploadConfirmVisible).toBe(false);
  expect(mockHttpPost).not.toHaveBeenCalled();
});

test('确认替换：上传后绑定清空并提示重新绑定', async () => {
  store.applyDetail({data: makeDetail([BOUND_PS])});
  mockHttpPost.mockResolvedValue({data: makeDetail([])});
  await renderPage();
  await act(async () => {
    container.querySelector('[data-testid="tpl-more-actions"]').click();
  });
  await flush();
  const input = document.body.querySelector('.ant-dropdown input[type="file"]');
  Object.defineProperty(input, 'files', {
    value: [new window.File(['x'], 'channel.xlsx')],
  });
  await act(async () => {
    input.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  await flush();
  const modal = Array.from(document.body.querySelectorAll('.ant-modal'))
    .find(node => node.textContent.includes('替换源文件'));
  const ok = Array.from(modal.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === '确认替换');
  await act(async () => {
    ok.click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/draft-file/', expect.anything());
  expect(store.bindings).toHaveLength(0);
  expect(store.reuploadConfirmVisible).toBe(false);
  expect(message.success).toHaveBeenCalledWith('源文件已替换，原绑定已清空，请重新绑定');
});

test('已停用模板工作区只读：发布禁用并说明原因，替换/打印设置冻结，选格编辑冻结', async () => {
  const detail = makeDetail([BOUND_PS], {is_active: false});
  store.applyDetail({data: detail});
  await renderPage();
  expect(container.textContent).toContain('已停用，仅供查看');
  expect(container.querySelector('[data-testid="tpl-publish"]').disabled).toBe(true);
  expect(container.querySelector('[data-testid="tpl-publish-reason"]').textContent)
    .toContain('模板已停用');
  // 更多操作菜单：替换源文件/打印设置禁用，版本记录可用
  await act(async () => {
    container.querySelector('[data-testid="tpl-more-actions"]').click();
  });
  await flush();
  const dropdown = document.body.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
  expect(dropdown.querySelector('[data-testid="tpl-reupload-menu"]').className)
    .toContain('ant-dropdown-menu-item-disabled');
  expect(dropdown.querySelector('[data-testid="tpl-pdf-params"]').className)
    .toContain('ant-dropdown-menu-item-disabled');
  // 选格编辑冻结：点击单元格不产生选中（面板保持「未选择」占位）
  await act(async () => {
    dispatchMouse('click', findTd('C4'));
  });
  await flush();
  expect(store.selectedCell).toBe('');
  expect(store.selectedCells).toEqual([]);
  expect(container.querySelector('.proto-field-panel').textContent).toContain('未选择');
});

// ==================== 「预览空白打印稿」+ 兼容性检查（2026-09-29） ====================

function stubPdfWindow() {
  const openMock = jest.fn().mockReturnValue({});
  window.open = openMock;
  window.URL.createObjectURL = jest.fn(() => 'blob:preview-url');
  window.URL.revokeObjectURL = jest.fn();
  return openMock;
}

test('有草稿时显示「预览空白打印稿」按钮，无草稿时禁用', async () => {
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  await renderPage();
  const button = buttonByText('预览空白打印稿（已保存参数）');
  expect(button).toBeTruthy();
  expect(button.disabled).toBe(false);
  // 无草稿：按钮仍在但不可用
  store.applyDetail({data: makeDetail([], {draft: null})});
  await flush();
  expect(buttonByText('预览空白打印稿（已保存参数）').disabled).toBe(true);
});

test('点击「预览空白打印稿」：POST 预览接口，成功后新窗口打开', async () => {
  const openMock = stubPdfWindow();
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  mockHttpPost.mockResolvedValue({
    data: new ArrayBuffer(16),
    headers: {'content-type': 'application/pdf'},
  });
  await renderPage();
  await act(async () => {
    buttonByText('预览空白打印稿（已保存参数）').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/preview/pdf/', null,
    expect.objectContaining({responseType: 'arraybuffer'}));
  expect(window.URL.createObjectURL).toHaveBeenCalledTimes(1);
  expect(openMock).toHaveBeenCalledWith('blob:preview-url', '_blank');
  // 请求结束后 loading 复位
  expect(store.previewing).toBe(false);
});

test('「预览空白打印稿」请求期间按钮 loading，结束后恢复', async () => {
  stubPdfWindow();
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  let resolvePreview = null;
  mockHttpPost.mockReturnValue(new Promise(resolve => {
    resolvePreview = resolve;
  }));
  await renderPage();
  await act(async () => {
    buttonByText('预览空白打印稿（已保存参数）').click();
  });
  await flush();
  expect(buttonByText('预览空白打印稿（已保存参数）').className).toContain('ant-btn-loading');
  await act(async () => {
    resolvePreview({data: new ArrayBuffer(16), headers: {}});
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  await flush();
  expect(buttonByText('预览空白打印稿（已保存参数）').className).not.toContain('ant-btn-loading');
});

test('弹窗被拦截时回退为下载', async () => {
  const openMock = stubPdfWindow();
  openMock.mockReturnValue(null);
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  mockHttpPost.mockResolvedValue({
    data: new ArrayBuffer(16),
    headers: {'content-type': 'application/pdf'},
  });
  await renderPage();
  await act(async () => {
    buttonByText('预览空白打印稿（已保存参数）').click();
  });
  await flush();
  // window.open 返回空（拦截）→ 仍创建对象 URL 并走下载（不报错、不提示成功之外的副作用）
  expect(window.URL.createObjectURL).toHaveBeenCalledTimes(1);
  expect(store.previewing).toBe(false);
});

test('「预览空白打印稿」失败：不显示成功提示，loading 复位', async () => {
  stubPdfWindow();
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  mockHttpPost.mockRejectedValue('LibreOffice 不可用，无法生成 PDF');
  await renderPage();
  await act(async () => {
    buttonByText('预览空白打印稿（已保存参数）').click();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  await flush();
  expect(store.previewing).toBe(false);
  expect(window.URL.createObjectURL).not.toHaveBeenCalled();
  expect(message.success).not.toHaveBeenCalled();
});

test('兼容性提示：warning 渲染黄色 Alert，error 渲染红色并列出不支持特性', async () => {
  const warnDetail = makeDetail([BOUND_PS]);
  warnDetail.compatibility = {
    status: 'warning',
    warnings: ['部署环境未安装 LibreOffice，PDF 预览与导出不可用'],
    unsupported: [],
  };
  store.applyDetail({data: warnDetail});
  await renderPage();
  let alert = container.querySelector('[data-testid="tpl-compat"]');
  expect(alert).toBeTruthy();
  expect(alert.className).toContain('ant-alert-warning');
  expect(alert.textContent).toContain('LibreOffice');

  const errorDetail = makeDetail([BOUND_PS]);
  errorDetail.compatibility = {
    status: 'error',
    warnings: ['包含平台暂不支持的特性：公式计算'],
    unsupported: ['公式计算'],
  };
  store.applyDetail({data: errorDetail});
  await flush();
  alert = container.querySelector('[data-testid="tpl-compat"]');
  expect(alert.className).toContain('ant-alert-error');
  expect(alert.textContent).toContain('公式计算');

  const okDetail = makeDetail([BOUND_PS]);
  okDetail.compatibility = {status: 'ok', warnings: [], unsupported: []};
  store.applyDetail({data: okDetail});
  await flush();
  expect(container.querySelector('[data-testid="tpl-compat"]')).toBeNull();
});

test('填写区尺寸提示：一行默认高的合并文本格提示设置行高，不阻断不改模板', async () => {
  // 横向合并 C4:E4（第 4 行无显式行高 → 提示）；纵向合并 F4:F6（不提示）；
  // status 类型 H3（不提示，仅文本类型才谈填写区域）
  const mergedSheet = {
    ...SHEET,
    merged_ranges: [...SHEET.merged_ranges, 'C4:E4', 'F4:F6'],
  };
  const detail = makeDetail([
    {...BOUND_PS, field_id: 'f1', cell_coordinate: 'C4',
     field_name: '负责人签名', input_type: 'text'},
    {...BOUND_PS, field_id: 'f2', cell_coordinate: 'F4',
     field_name: '处理结论', input_type: 'text'},
    {...BOUND_PS, field_id: 'f3', cell_coordinate: 'H3'},
  ]);
  detail.draft = {...detail.draft, layout: {active_sheet: '信道维护记录', sheets: [mergedSheet]}};
  store.applyDetail({data: detail});
  await renderPage();
  const hint = container.querySelector('[data-testid="tpl-size-hints"]');
  expect(hint).toBeTruthy();
  expect(hint.textContent).toContain('负责人签名');
  expect(hint.textContent).toContain('C4');
  // 说明如何在 Excel 中设置行高，且如实说明重传清空绑定
  expect(hint.textContent).toContain('行高');
  expect(hint.textContent).toContain('重新上传');
  // 纵向合并与非文本类型的格子不进提示
  expect(hint.textContent).not.toContain('处理结论');
  expect(hint.textContent).not.toContain('F4');
});

test('填写区尺寸提示：行高足够/无合并文本绑定时不渲染提示', async () => {
  // C4:E4 合并但第 4 行显式 40pt → 空间足够，无提示
  const tallSheet = {
    ...SHEET,
    merged_ranges: [...SHEET.merged_ranges, 'C4:E4'],
    row_heights: {...SHEET.row_heights, '4': 40},
  };
  const detail = makeDetail([
    {...BOUND_PS, field_id: 'f1', cell_coordinate: 'C4',
     field_name: '负责人签名', input_type: 'text'},
  ]);
  detail.draft = {...detail.draft, layout: {active_sheet: '信道维护记录', sheets: [tallSheet]}};
  store.applyDetail({data: detail});
  await renderPage();
  expect(container.querySelector('[data-testid="tpl-size-hints"]')).toBeNull();
  // 无合并文本绑定（status 类型且未合并）同样无提示
  store.applyDetail({data: makeDetail([BOUND_PS])});
  await flush();
  expect(container.querySelector('[data-testid="tpl-size-hints"]')).toBeNull();
});
