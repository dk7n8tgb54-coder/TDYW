/**
 * Excel 模板历史版本查看/复制为新草稿/草稿状态测试（2026-10-21，真实渲染
 * + jsdom + http mock，自 ExcelTemplatePageWorkspace.test.js 拆出独立套件）。
 *
 * 覆盖（全部走真实组件与 store 代码路径，http/exportFile 仅打桩）：
 * - 版本记录抽屉「查看内容」：拉取版本详情接口，只读查看器展示模板名称
 *   快照/源文件/哈希/字段数，可切换版式布局/字段绑定/打印参数/打印预览
 *   四个只读视图；
 * - 只读约束：版式视图中单元格不可选中、无输入控件（点击不改变模板
 *   store 选区状态）；已停用模板/非当前模板不出现「复制为新草稿」；
 * - 复制为新草稿：确认弹窗明确替换范围，取消不发请求；确认后 POST
 *   copy-to-draft 并以服务端详情刷新草稿；失败保留当前草稿、不提示成功；
 * - 版本打印预览：POST versions/<no>/preview/pdf/（版本自身预览接口），
 *   反馈头解析为页数/纸张；失败显示错误态可重试；
 * - 草稿状态信息行：当前编辑草稿/更新时间与更新人/与发布版本关系文案
 *   （一致/基于某版本后有修改/无法确认）；
 * - 关闭再打开仍进入当前草稿（不自动回退到最新发布版本，打开过程不请求
 *   版本接口）。
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
    addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(),
    removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}
window.URL.createObjectURL = window.URL.createObjectURL
  || jest.fn(() => 'blob:mock-version-preview');
window.URL.revokeObjectURL = window.URL.revokeObjectURL || jest.fn();

// import 会被提升到 mock 变量声明之前，组件须在 mock 就绪后 require
const loadPage = () => require('../ExcelTemplatePage').default;
const {ExcelTemplateStore} = require('../excelTemplateStore');
const {ExcelVersionStore} = require('../excelVersionStore');

const FIELD_PS = 'cccccccc-3333-4ccc-8ccc-000000000001';
const FIELD_TX = 'cccccccc-3333-4ccc-8ccc-000000000002';

const SHEET = {
  name: '自动转报机月维护记录表', max_row: 6, max_column: 8,
  merged_ranges: ['A1:H1'],
  row_heights: {'1': 30},
  column_widths: {A: 12, H: 20},
  cells: {
    A1: {v: '自动转报机月维护记录表', s: {font: {bold: true, size: 14}}},
    A2: {v: '日期'}, B2: {v: '项目'},
    C4: {s: {border: {top: {style: 'thin'}}}},
  },
  print: {orientation: 'portrait', paper_size: 9},
};

const BINDINGS = [
  {field_id: FIELD_PS, sheet_name: SHEET.name, cell_coordinate: 'C4',
   field_name: 'PS模块', input_type: 'status', is_required: true,
   unit: '', options: ['正常', '异常']},
  {field_id: FIELD_TX, sheet_name: SHEET.name, cell_coordinate: 'D4',
   field_name: 'TX模块', input_type: 'number', is_required: false,
   unit: 'dB', options: []},
];

const VERSION_META = {
  id: 91, version_no: 3, template_name: '自动转报机月维护记录表',
  ledger_type: 'week_month', source_filename: '月维护记录表.xlsx',
  source_hash: 'f'.repeat(64), field_count: 2,
  published_at: '2026-10-19 19:57:06',
};

function makeVersionDetail() {
  return {
    ...VERSION_META,
    sheet_name: SHEET.name,
    layout: {active_sheet: SHEET.name, sheets: [SHEET]},
    bindings: BINDINGS,
    pdf_params: {paper_size: 'A4', orientation: 'portrait'},
    print_plan: {paper: 'A4', orientation: 'portrait', rowBreaks: [], colBreaks: []},
  };
}

function makeDetail(bindings = BINDINGS, overrides = {}) {
  return {
    id: 21,
    name: '自动转报机月维护记录表',
    ledger_type: 'week_month',
    description: '',
    is_active: true,
    draft_source_filename: '月维护记录表.xlsx',
    draft_source_hash: 'f'.repeat(64),
    latest_version_no: 3,
    versions_count: 3,
    draft: {
      sheet_name: SHEET.name,
      source_filename: '月维护记录表.xlsx',
      source_hash: 'f'.repeat(64),
      layout: {active_sheet: SHEET.name, sheets: [SHEET]},
      field_bindings: bindings,
      draft_updated_at: '2026-10-21 16:17:39',
    },
    draft_state: {
      latest_version_no: 3, versions_count: 3,
      updated_at: '2026-10-21 16:17:39',
      updated_by: '管理员', updated_by_username: 'admin',
      binding_count: bindings.length,
      relation: 'unknown', based_on_version_no: null,
      differs_from_latest: true,
    },
    ...overrides,
  };
}

let container = null;
let store = null;
let versionStore = null;

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

async function renderPage() {
  const Page = loadPage();
  await act(async () => {
    ReactDOM.render(
      <Page store={store} versionStore={versionStore}/>, container);
  });
  await flush();
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  store = new ExcelTemplateStore();
  versionStore = new ExcelVersionStore();
  jest.clearAllMocks();
  window.URL.createObjectURL.mockClear
    && window.URL.createObjectURL.mockClear();
  window.URL.revokeObjectURL.mockClear
    && window.URL.revokeObjectURL.mockClear();
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
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask')
    .forEach(node => node.remove());
  container = null;
  store = null;
  versionStore = null;
});

async function openVersionsDrawer() {
  store.applyDetail({data: makeDetail()});
  mockHttpGet.mockResolvedValue({data: [VERSION_META]});
  await renderPage();
  await act(async () => {
    container.querySelector('[data-testid="tpl-more-actions"]').click();
  });
  await flush();
  const menu = document.body.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
  await act(async () => {
    menu.querySelector('[data-testid="tpl-versions-menu"]').click();
  });
  await flush();
  return document.body.querySelector('.ant-drawer:not(.ant-drawer-hidden)');
}

async function openVersionViewer(detail, detailError) {
  const drawer = await openVersionsDrawer();
  // 版本详情接口在抽屉打开后才被调用（列表接口已消费），此时再登记 mock
  if (detailError) mockHttpGet.mockRejectedValue(detailError);
  else mockHttpGet.mockResolvedValue({data: detail});
  await act(async () => {
    drawer.querySelector('[data-testid="tpl-version-view"]').click();
  });
  await flush();
  return document.body.querySelectorAll('.ant-drawer')[1];
}

/** 按 textContent（去空白，antd 两字按钮自动插空格）查找按钮。 */
function plainButton(root, text) {
  const found = Array.from(root.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text);
  if (!found) throw new Error(`button not found: ${text}`);
  return found;
}

async function switchViewerView(pane) {
  const input = Array.from(
    document.body.querySelectorAll('[data-testid="ver-view-mode"] input'))
    .find(node => node.value === pane);
  await act(async () => {
    input.click();
  });
  await flush();
}

// ==================== 版本内容只读查看 ====================

test('版本抽屉行「查看内容」打开只读查看器并展示版本快照', async () => {
  const viewer = await openVersionViewer(makeVersionDetail());
  expect(mockHttpGet).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/21/versions/3/');
  expect(viewer.textContent).toContain('版本 v3（只读）');
  expect(viewer.textContent).toContain('自动转报机月维护记录表');
  expect(viewer.textContent).toContain('2026-10-19 19:57:06');
  expect(viewer.textContent).toContain('月维护记录表.xlsx');
  // 版式视图使用版本快照渲染，已绑定格有标记
  expect(viewer.querySelector('[data-testid="ver-layout"]')).toBeTruthy();
  expect(viewer.querySelectorAll('.proto-binding-mark').length).toBe(2);
  expect(viewer.textContent).toContain('已发布版本（不可变）');
});

test('只读版本不能编辑：点击单元格不进入选区，无输入控件', async () => {
  const viewer = await openVersionViewer(makeVersionDetail());
  const cell = viewer.querySelector('td[data-coord="C4"]');
  expect(cell).toBeTruthy();
  await act(async () => {
    cell.dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
  });
  await flush();
  // 模板编辑 store 的选区状态不受只读查看器影响；版式区内无任何输入控件
  expect(store.selectedCell).toBe('');
  expect(store.selectedCells).toEqual([]);
  expect(viewer.querySelector(
    '[data-testid="ver-layout"] .proto-table-wrap input')).toBeNull();
  expect(viewer.querySelector(
    '[data-testid="ver-layout"] .proto-table-wrap textarea')).toBeNull();
});

test('查看器四个只读视图：字段绑定清单与打印参数快照', async () => {
  const viewer = await openVersionViewer(makeVersionDetail());
  await switchViewerView('bindings');
  expect(viewer.querySelector('[data-testid="ver-bindings"]').textContent)
    .toContain('PS模块');
  expect(viewer.querySelector('[data-testid="ver-bindings"]').textContent)
    .toContain('正常/异常');
  await switchViewerView('params');
  expect(viewer.querySelector('[data-testid="ver-params"]').textContent)
    .toContain('A4');
  expect(viewer.querySelector('[data-testid="ver-params"]').textContent)
    .toContain('该版本发布时固定的打印参数快照（只读）');
});

test('版本内容读取失败显示真实错误并可重试，不显示空白成功状态', async () => {
  const viewer = await openVersionViewer(null, '模板版本不存在');
  expect(viewer.querySelector('[data-testid="ver-error"]').textContent)
    .toContain('模板版本不存在');
  // 重试成功后内容出现
  mockHttpGet.mockResolvedValue({data: makeVersionDetail()});
  await act(async () => {
    plainButton(viewer, '重试').click();
  });
  await flush();
  expect(viewer.querySelector('[data-testid="ver-layout"]')).toBeTruthy();
});

test('历史版本源文件可下载（带认证导出通道）', async () => {
  const viewer = await openVersionViewer(makeVersionDetail());
  await act(async () => {
    viewer.querySelector('[data-testid="ver-source-download"]').click();
  });
  expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
    url: '/api/equipment-lifecycle/excel-templates/21/versions/3/source/',
    method: 'get',
  }));
});

// ==================== 复制为新草稿 ====================

test('复制为新草稿：确认弹窗明确替换范围，取消不发请求', async () => {
  const viewer = await openVersionViewer(makeVersionDetail());
  expect(viewer.querySelector('[data-testid="ver-copy"]')).toBeTruthy();
  await act(async () => {
    viewer.querySelector('[data-testid="ver-copy"]').click();
  });
  await flush();
  const modal = document.body.querySelector('.ant-modal');
  const content = modal.querySelector('[data-testid="tpl-copy-confirm"]').textContent;
  expect(content).toContain('当前草稿将被 v3 的内容整体替换');
  expect(content).toContain('现有字段绑定将被替换');
  expect(content).toContain('当前打印参数将被替换');
  expect(content).toContain('不会自动发布');
  expect(content).toContain('不会被修改');
  // 取消 → 不发复制请求
  const cancel = Array.from(modal.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === '取消');
  await act(async () => {
    cancel.click();
  });
  await flush();
  expect(mockHttpPost).not.toHaveBeenCalled();
});

test('复制成功：POST copy-to-draft 后以服务端详情刷新草稿视图', async () => {
  const viewer = await openVersionViewer(makeVersionDetail());
  await act(async () => {
    viewer.querySelector('[data-testid="ver-copy"]').click();
  });
  await flush();
  const confirm = document.body.querySelector('.ant-modal');
  const ok = Array.from(confirm.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === '复制并替换草稿');
  // 后端返回复制后的模板详情（草稿与 v3 一致）
  mockHttpPost.mockResolvedValue({data: {data: makeDetail(BINDINGS, {
    draft_state: {
      latest_version_no: 3, versions_count: 3,
      updated_at: '2026-10-21 17:30:00', updated_by: '管理员',
      updated_by_username: 'admin', binding_count: 2,
      relation: 'identical', based_on_version_no: 3,
      differs_from_latest: false,
    },
  })}});
  await act(async () => {
    ok.click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/21/versions/3/copy-to-draft/');
  // 查看抽屉关闭，草稿视图刷新为服务端详情
  expect(versionStore.visible).toBe(false);
  expect(store.current.draft_state.relation).toBe('identical');
  expect(container.querySelector('[data-testid="tpl-draft-relation"]').textContent)
    .toContain('草稿与 v3 发布版本内容一致');
  expect(message.success).toHaveBeenCalledWith('已把 v3 复制为当前草稿');
});

test('复制失败：保留当前页面与草稿状态，不提示成功', async () => {
  const viewer = await openVersionViewer(makeVersionDetail());
  await act(async () => {
    viewer.querySelector('[data-testid="ver-copy"]').click();
  });
  await flush();
  const ok = Array.from(document.body.querySelector('.ant-modal')
    .querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === '复制并替换草稿');
  const before = store.current;
  mockHttpPost.mockRejectedValue('模板已删除（停用），不能复制版本为新草稿');
  await act(async () => {
    ok.click();
  });
  await flush();
  // 当前草稿原样保留，不提示成功，查看抽屉未关闭
  expect(store.current).toBe(before);
  expect(message.success).not.toHaveBeenCalled();
  expect(versionStore.visible).toBe(true);
});

test('查看非当前模板（列表行入口）时不出现复制入口', async () => {
  // 列表行「版本记录 → 查看内容」：未打开该模板详情 → 只读提示，无复制按钮
  mockHttpGet.mockResolvedValueOnce({data: [{
    id: 21, name: '自动转报机月维护记录表', ledger_type: 'week_month',
    draft_source_filename: '月维护记录表.xlsx', is_active: true,
    latest_version_no: 3, versions_count: 3,
  }]});
  const Page = loadPage();
  await act(async () => {
    ReactDOM.render(<Page store={store} versionStore={versionStore}/>, container);
  });
  await flush();
  // 第二次请求是版本列表接口
  mockHttpGet.mockResolvedValueOnce({data: [VERSION_META]});
  await act(async () => {
    container.querySelector('[data-testid="tpl-more"]').click();
  });
  await flush();
  const dropdown = document.body.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
  await act(async () => {
    dropdown.querySelector('[data-testid="tpl-row-versions"]').click();
  });
  await flush();
  const listDrawer = document.body.querySelector('.ant-drawer');
  expect(listDrawer.textContent).toContain('已发布版本：自动转报机月维护记录表');
  // 版本详情接口在抽屉打开后才被调用
  mockHttpGet.mockResolvedValue({data: makeVersionDetail()});
  await act(async () => {
    listDrawer.querySelector('[data-testid="tpl-version-view"]').click();
  });
  await flush();
  const viewer = document.body.querySelectorAll('.ant-drawer')[1];
  expect(viewer.textContent).toContain('版本 v3（只读）');
  expect(viewer.querySelector('[data-testid="ver-copy"]')).toBeNull();
  expect(viewer.textContent).toContain('历史版本只读');
  // 且未改动当前模板详情（页面停留在列表）
  expect(store.current).toBeNull();
});

// ==================== 版本打印预览 ====================

test('版本打印预览：POST 版本自身预览接口并展示页数/纸张反馈', async () => {
  const viewer = await openVersionViewer(makeVersionDetail());
  mockHttpPost.mockResolvedValue({
    data: new Uint8Array([37, 80, 68, 70]),  // "%PDF"
    headers: {'x-el-pdf-pages': '2', 'x-el-pdf-paper': 'A4 210x297mm'},
  });
  await switchViewerView('preview');
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/21/versions/3/preview/pdf/',
    null, expect.objectContaining({responseType: 'arraybuffer'}));
  expect(viewer.querySelector('[data-testid="ver-preview-iframe"]')).toBeTruthy();
  expect(viewer.querySelector('[data-testid="ver-preview-meta"]').textContent)
    .toContain('A4（210×297 mm）');
  expect(viewer.querySelector('[data-testid="ver-preview-meta"]').textContent)
    .toContain('2 页');
  // 刷新预览复用同一版本接口
  mockHttpPost.mockClear();
  await act(async () => {
    viewer.querySelector('[data-testid="ver-preview-refresh"]').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledTimes(1);
});

test('版本打印预览失败显示错误态可重试，不冒充成功', async () => {

  const viewer = await openVersionViewer(makeVersionDetail());
  mockHttpPost.mockRejectedValue('LibreOffice 不可用，无法生成 PDF');
  await switchViewerView('preview');
  await flush();
  expect(viewer.textContent).toContain('版本打印预览生成失败');
  expect(viewer.querySelector('[data-testid="ver-preview-iframe"]')).toBeNull();
  // 重试成功后 iframe 出现
  mockHttpPost.mockResolvedValue({
    data: new Uint8Array([37, 80, 68, 70]),
    headers: {'x-el-pdf-pages': '1'},
  });
  await act(async () => {
    plainButton(viewer, '重试').click();
  });
  await flush();
  expect(viewer.querySelector('[data-testid="ver-preview-iframe"]')).toBeTruthy();
});

// ==================== 草稿状态信息行与草稿续用 ====================

test('信息行显示当前编辑草稿/更新时间/更新人与关系文案', async () => {
  store.applyDetail({data: makeDetail()});
  await renderPage();
  expect(container.querySelector('[data-testid="tpl-editing-mode"]').textContent)
    .toContain('当前编辑：草稿');
  expect(container.querySelector('[data-testid="tpl-draft-updated"]').textContent)
    .toContain('2026-10-21 16:17:39');
  expect(container.querySelector('[data-testid="tpl-draft-updated"]').textContent)
    .toContain('管理员');
  // unknown 关系：无法确认，不猜测来源版本
  expect(container.querySelector('[data-testid="tpl-draft-relation"]').textContent)
    .toContain('草稿与发布版本来源关系无法确认');
});

test('草稿关系文案：与发布版本一致 / 基于某版本后有修改', async () => {
  store.applyDetail({data: makeDetail(BINDINGS, {
    draft_state: {
      latest_version_no: 3, versions_count: 3,
      updated_at: '2026-10-21 16:17:39', updated_by: '管理员',
      updated_by_username: 'admin', binding_count: 2,
      relation: 'modified', based_on_version_no: 2, differs_from_latest: true,
    },
  })});
  await renderPage();
  expect(container.querySelector('[data-testid="tpl-draft-relation"]').textContent)
    .toContain('草稿基于 v2，之后有修改');
  store.applyDetail({data: makeDetail(BINDINGS, {
    draft_state: {
      latest_version_no: 3, versions_count: 3,
      updated_at: '2026-10-21 16:17:39', updated_by: '管理员',
      updated_by_username: 'admin', binding_count: 2,
      relation: 'identical', based_on_version_no: 3, differs_from_latest: false,
    },
  })});
  await flush();
  expect(container.querySelector('[data-testid="tpl-draft-relation"]').textContent)
    .toContain('草稿与 v3 发布版本内容一致');
});

test('关闭再打开模板仍进入当前草稿，不回退到最新发布版本', async () => {
  store.applyDetail({data: makeDetail()});
  await renderPage();
  // 返回列表（关闭模板）
  await act(async () => {
    container.querySelector('[data-testid="tpl-back"]').click();
  });
  await flush();
  expect(store.current).toBeNull();
  // 重新打开：只请求详情接口，不请求版本接口
  mockHttpGet.mockClear();
  mockHttpGet.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    await store.fetchDetail(21);
  });
  await flush();
  expect(mockHttpGet).toHaveBeenCalledTimes(1);
  expect(mockHttpGet).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/21/');
  // 当前草稿（2 页布局的草稿状态）原样呈现，而非 v3 快照
  expect(store.draft.draft_updated_at).toBe('2026-10-21 16:17:39');
  expect(store.current.draft_state.relation).toBe('unknown');
  expect(store.activeSheet).toBe(SHEET.name);
});
