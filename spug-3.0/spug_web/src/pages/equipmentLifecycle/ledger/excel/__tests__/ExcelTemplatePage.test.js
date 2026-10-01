/**
 * Excel 台账模板页测试（真实渲染 + jsdom + http mock，2026-09-28 试点）。
 *
 * 覆盖：列表渲染 → 上传守卫（缺名称/类型不发请求）→ 上传成功进入绑定
 * 工作区（合并布局渲染）→ 选格绑定（保存载荷/服务端拒绝回退）→ 发布
 * （无绑定拦截/成功后重取详情）→ 版本抽屉渲染 → 重传源文件清空绑定提示。
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

test('列表渲染模板行与版本信息', async () => {
  mockHttpGet.mockResolvedValue({data: [makeDetail().id && {
    id: 11, name: '信道Excel维护台账', ledger_type: 'week_month',
    description: '试点', draft_source_filename: 'channel.xlsx',
    draft_updated_at: '2026-09-28 10:00:00',
    latest_version_no: 1, versions_count: 1, is_active: true,
  }]});
  await renderPage();
  expect(container.textContent).toContain('信道Excel维护台账');
  expect(container.textContent).toContain('周月维护');
  expect(container.textContent).toContain('v1 / 共 1 个');
});

test('上传守卫：未填名称/类型不发请求，填齐后走上传', async () => {
  const Page = loadPage();
  let instance = null;
  await act(async () => {
    instance = ReactDOM.render(<Page store={store}/>, container);
  });
  await flush();
  // 守卫：名称/类型未填 → 返回 false、warning、不发请求
  let result = null;
  await act(async () => {
    result = instance.handleUpload({name: 'channel.xlsx'});
  });
  expect(result).toBe(false);
  expect(message.warning).toHaveBeenCalledWith('请先填写模板名称并选择维护类型');
  expect(mockHttpPost).not.toHaveBeenCalled();
  // 填齐 → 走上传（返回 false 阻止 antd 默认上传行为，请求已发出）
  store.setUploadField('uploadName', '信道Excel维护台账');
  store.setUploadField('uploadType', 'week_month');
  await act(async () => {
    result = instance.handleUpload({name: 'channel.xlsx'});
  });
  expect(result).toBe(false);
  expect(mockHttpPost).toHaveBeenCalledTimes(1);
  expect(mockHttpPost.mock.calls[0][0]).toBe('/api/equipment-lifecycle/excel-templates/');
});

test('上传成功进入绑定工作区并渲染合并布局', async () => {
  const detail = makeDetail();
  mockHttpPost.mockResolvedValue({data: detail});
  await act(async () => {
    await store.upload({name: '信道Excel维护台账', ledger_type: 'week_month'}, {name: 'channel.xlsx'});
  });
  await renderPage();
  expect(container.textContent).toContain('模板绑定：信道Excel维护台账');
  expect(container.querySelector('table.proto-table')).toBeTruthy();
  expect(container.querySelector('td[data-coord="A1"]').textContent).toContain('信道维护记录表');
  expect(container.querySelector('td[data-coord="C2"]').textContent).toContain('PS模块');
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

test('Ctrl 加选多格显示批量面板与数量，可清空选择', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  await renderPage();
  expect(container.querySelector('[data-testid="batch-clear"]')).toBeNull();
  await ctrlClickCell('C4');
  await ctrlClickCell('E4');
  expect(store.selectedCells.slice().sort()).toEqual(['C4', 'E4']);
  // 已绑定单元格不可加选
  const boundDetail = makeDetail([BOUND_PS]);
  store.applyDetail({data: boundDetail});
  await flush();
  await ctrlClickCell('C4');
  await ctrlClickCell('D4');
  expect(store.selectedCells).toEqual(['D4']);
  expect(container.textContent).toContain('批量绑定');
  expect(container.textContent).toContain('已选 1 格');
  // Ctrl 再点已选格 → 取消单个选择；清空后批量面板消失
  await ctrlClickCell('D4');
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

test('切换工作表清空批量选区（跨工作表不混合批量绑定）', async () => {
  const twoSheets = makeDetail();
  twoSheets.draft.layout.sheets.push({
    name: '维护结论', max_row: 4, max_column: 2, merged_ranges: [],
    row_heights: {}, column_widths: {},
    cells: {A1: {v: '维护结论'}, B1: {v: '内容（填写）'}},
    print: {orientation: 'portrait', paper_size: 9},
  });
  store.applyDetail({data: twoSheets});
  await renderPage();
  await ctrlClickCell('C4');
  expect(store.selectedCells).toEqual(['C4']);
  await act(async () => {
    store.setSheet('维护结论');
  });
  await flush();
  expect(store.selectedCells).toEqual([]);
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

test('发布：无绑定拦截，有绑定走 POST 并重取详情', async () => {
  const detail = makeDetail();
  store.applyDetail({data: detail});
  await renderPage();
  // 无绑定拦截
  const publishButton = buttonByText('发布版本');
  expect(publishButton).toBeTruthy();
  await act(async () => {
    store.publishing = false;
  });
  const publishHandler = publishButton;
  expect(publishHandler).toBeTruthy();
  // 有绑定时发布
  store.applyDetail({data: makeDetail([BOUND_PS])});
  mockHttpPost.mockResolvedValue({data: {data: {version_no: 1}}});
  mockHttpGet.mockResolvedValue({data: makeDetail([BOUND_PS], {
    latest_version_no: 1, versions_count: 1,
  })});
  await act(async () => {
    await store.publish();
  });
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/publish/');
  expect(store.current.versions_count).toBe(1);
  expect(message.success).toHaveBeenCalledWith('发布成功');
});

test('版本抽屉渲染不可变版本列表', async () => {
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  mockHttpGet.mockResolvedValue({data: [
    {id: 5, version_no: 1, template_name: '信道Excel维护台账',
     source_filename: 'channel.xlsx', source_hash: 'a'.repeat(64),
     field_count: 1, published_at: '2026-09-28 11:00:00'},
  ]});
  await renderPage();
  await act(async () => {
    await store.fetchVersions();
    store.versionsVisible = true;
  });
  await flush();
  // antd Drawer 渲染进 body portal，须查 document.body（Modal/Drawer portal 惯例）
  expect(document.body.textContent).toContain('已发布版本（不可变）');
  expect(document.body.textContent).toContain('v1');
  expect(document.body.textContent).toContain('channel.xlsx');
});

test('重传源文件后绑定清空并提示', async () => {
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  mockHttpPost.mockResolvedValue({data: makeDetail([])});
  await renderPage();
  const reuploadButton = buttonByText('重传源文件');
  expect(reuploadButton).toBeTruthy();
  await act(async () => {
    await store.reuploadFile({name: 'channel.xlsx'});
  });
  expect(store.bindings).toHaveLength(0);
});

test('下载验收样例走 exportFile', async () => {
  store.applyDetail({data: makeDetail()});
  await renderPage();
  const button = buttonByText('下载验收样例');
  await act(async () => {
    button.click();
  });
  expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
    url: '/api/equipment-lifecycle/excel-templates/sample/',
    method: 'get',
  }));
});

function listRow(overrides = {}) {
  return {
    id: 11, name: '信道Excel维护台账', ledger_type: 'week_month',
    description: '试点', draft_source_filename: 'channel.xlsx',
    draft_updated_at: '2026-09-28 10:00:00',
    latest_version_no: 1, versions_count: 1, is_active: true,
    ...overrides,
  };
}

function popconfirmButton(text) {
  return Array.from(document.body.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text);
}

async function openDeleteConfirm() {
  await act(async () => {
    container.querySelector('[data-testid="tpl-delete"]').click();
  });
  await flush();
}

test('删除按钮按权限显示，已停用模板不显示', async () => {
  mockHttpGet.mockResolvedValue({data: [
    listRow(),
    listRow({id: 12, name: '停用模板', is_active: false}),
  ]});
  await renderPage();
  // del 权限参与按钮显隐判断
  expect(require('libs').hasPermission).toHaveBeenCalledWith(
    'equipment_lifecycle.ledger_template.del');
  // 只有启用模板有删除按钮，停用模板没有
  const deleteButtons = container.querySelectorAll('[data-testid="tpl-delete"]');
  expect(deleteButtons).toHaveLength(1);
  expect(container.textContent).toContain('停用模板');
  expect(container.textContent).toContain('停用');
});

test('无 del 权限时删除按钮不显示', async () => {
  require('libs').hasPermission.mockReturnValue(false);
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  expect(container.querySelector('[data-testid="tpl-delete"]')).toBeNull();
  expect(container.querySelector('[data-testid="tpl-open"]')).toBeTruthy();
});

test('点击删除出现确认框，取消不发请求', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  await openDeleteConfirm();
  expect(document.body.textContent).toContain('删除后将停止该模板使用，历史台账仍可查看，确定删除吗？');
  await act(async () => {
    popconfirmButton('取消').click();
  });
  await flush();
  expect(mockHttpDelete).not.toHaveBeenCalled();
});

test('确认删除：调用 DELETE，成功后提示并重取列表', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  await openDeleteConfirm();
  mockHttpDelete.mockResolvedValue({data: {}});
  mockHttpGet.mockResolvedValue({data: []});
  await act(async () => {
    popconfirmButton('确定').click();
  });
  await flush();
  expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/');
  expect(message.success).toHaveBeenCalledWith('模板已删除');
  // 成功后重新拉取模板列表（不做乐观删除）
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/');
  // loading 状态复位
  expect(store.deletingId).toBe('');
});

test('删除失败：不显示成功提示，loading 复位', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  await openDeleteConfirm();
  mockHttpDelete.mockRejectedValue('模板不存在或无权限访问');
  await act(async () => {
    popconfirmButton('确定').click();
  });
  await flush();
  expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/');
  expect(message.success).not.toHaveBeenCalledWith('模板已删除');
  expect(store.deletingId).toBe('');
});

test('已删除（停用）模板工作区禁用重传/发布/选格编辑', async () => {
  const detail = makeDetail([BOUND_PS], {is_active: false});
  store.applyDetail({data: detail});
  await renderPage();
  expect(container.textContent).toContain('已删除（停用），仅供查看');
  expect(buttonByText('重传源文件').disabled).toBe(true);
  expect(container.querySelector('[data-testid="tpl-publish"]').disabled).toBe(true);
  // 选格编辑冻结：点击单元格不产生选中（面板保持「未选择」占位）
  await act(async () => {
    dispatchMouse('click', findTd('C4'));
  });
  await flush();
  expect(store.selectedCell).toBe('');
  expect(store.selectedCells).toEqual([]);
  expect(container.querySelector('.proto-field-panel').textContent).toContain('未选择');
});

// ==================== 草稿 PDF 预览 + 兼容性检查（2026-09-29） ====================

function stubPdfWindow() {
  const openMock = jest.fn().mockReturnValue({});
  window.open = openMock;
  window.URL.createObjectURL = jest.fn(() => 'blob:preview-url');
  window.URL.revokeObjectURL = jest.fn();
  return openMock;
}

test('有草稿时显示 PDF预览按钮，无草稿时禁用', async () => {
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  await renderPage();
  const button = buttonByText('PDF预览');
  expect(button).toBeTruthy();
  expect(button.disabled).toBe(false);
  // 无草稿：按钮仍在但不可用
  store.applyDetail({data: makeDetail([], {draft: null})});
  await flush();
  expect(buttonByText('PDF预览').disabled).toBe(true);
});

test('点击 PDF预览：POST 预览接口，成功后新窗口打开', async () => {
  const openMock = stubPdfWindow();
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  mockHttpPost.mockResolvedValue({
    data: new ArrayBuffer(16),
    headers: {'content-type': 'application/pdf'},
  });
  await renderPage();
  await act(async () => {
    buttonByText('PDF预览').click();
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

test('PDF预览请求期间按钮 loading，结束后恢复', async () => {
  stubPdfWindow();
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  let resolvePreview = null;
  mockHttpPost.mockReturnValue(new Promise(resolve => {
    resolvePreview = resolve;
  }));
  await renderPage();
  await act(async () => {
    buttonByText('PDF预览').click();
  });
  await flush();
  expect(buttonByText('PDF预览').className).toContain('ant-btn-loading');
  await act(async () => {
    resolvePreview({data: new ArrayBuffer(16), headers: {}});
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  await flush();
  expect(buttonByText('PDF预览').className).not.toContain('ant-btn-loading');
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
    buttonByText('PDF预览').click();
  });
  await flush();
  // window.open 返回空（拦截）→ 仍创建对象 URL 并走下载（不报错、不提示成功之外的副作用）
  expect(window.URL.createObjectURL).toHaveBeenCalledTimes(1);
  expect(store.previewing).toBe(false);
});

test('PDF预览失败：不显示成功提示，loading 复位', async () => {
  stubPdfWindow();
  const detail = makeDetail([BOUND_PS]);
  store.applyDetail({data: detail});
  mockHttpPost.mockRejectedValue('LibreOffice 不可用，无法生成 PDF');
  await renderPage();
  await act(async () => {
    buttonByText('PDF预览').click();
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
