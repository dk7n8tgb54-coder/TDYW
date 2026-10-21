/**
 * Excel 台账模板页列表测试（真实渲染 + jsdom + http mock，2026-09-28 试点；
 * 2026-10-14 交互改造；2026-10-21 新建流程配置前置；绑定工作区测试见同目录
 * ExcelTemplatePageWorkspace.test.js）。
 *
 * 覆盖：列表渲染（唯一主操作「新建模板」、行操作按状态、更多菜单、停用
 * 确认与权限）→ 新建流程（2026-10-21 配置前置：名称/类型/适用系统/
 * 生成周期/文件集中弹窗一次完成，缺项在对应位置提示，选择文件不上传，
 * 切换类型收敛周期，一次提交全部字段，失败可重试）→ 上传成功进入绑定
 * 工作区。全部走真实组件与 store 代码路径，http/exportFile 仅打桩。
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
  // Modal.confirm 渲染在 body 门户下且 onOk 拒绝时不自动关闭，逐用例清理
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask')
    .forEach(node => node.remove());
  container = null;
  store = null;
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

async function openRowMenu(index = 0) {
  await act(async () => {
    container.querySelectorAll('[data-testid="tpl-more"]')[index].click();
  });
  await flush();
  return document.body.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
}

/** 切换在用/已停用视图（Radio.Button 须点击内部 input 才触发 onChange）。 */
async function switchView(view) {
  const input = Array.from(
    container.querySelectorAll('[data-testid="tpl-view-switch"] input'))
    .find(node => node.value === view);
  await act(async () => {
    input.click();
  });
  await flush();
}

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

// ==================== 列表页交互（2026-10-14 交互改造） ====================

test('列表页唯一主操作「新建模板」：弹窗集中名称/类型/上传/下载样例', async () => {
  mockHttpGet.mockResolvedValue({data: []});
  await renderPage();
  // 列表页不得出现「返回列表」，也不再有重复的样例按钮
  expect(container.querySelector('[data-testid="tpl-back-list"]')).toBeNull();
  expect(container.querySelector('[data-testid="tpl-create"]')).toBeTruthy();
  await act(async () => {
    container.querySelector('[data-testid="tpl-create"]').click();
  });
  await flush();
  const modal = document.body.querySelector('.ant-modal');
  expect(modal.textContent).toContain('新建 Excel 台账模板');
  expect(modal.querySelector('[data-testid="tpl-name"]')).toBeTruthy();
  expect(modal.querySelector('[data-testid="tpl-type"]')).toBeTruthy();
  expect(modal.querySelector('[data-testid="tpl-upload"]')).toBeTruthy();
  // 下载样例只出现在该流程内（全页面仅一处）
  const samples = Array.from(document.body.querySelectorAll('button'))
    .filter(node => node.textContent.replace(/\s/g, '') === '下载样例');
  expect(samples).toHaveLength(1);
  await act(async () => {
    samples[0].click();
  });
  expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
    url: '/api/equipment-lifecycle/excel-templates/sample/',
    method: 'get',
  }));
});

test('无 add 权限时列表不显示「新建模板」', async () => {
  require('libs').hasPermission.mockReturnValue(false);
  mockHttpGet.mockResolvedValue({data: []});
  await renderPage();
  expect(container.querySelector('[data-testid="tpl-create"]')).toBeNull();
});

test('行操作按状态显示：编辑草稿/上传源文件（在用）与查看模板（已停用视图）', async () => {
  mockHttpGet.mockResolvedValue({data: [
    listRow(),
    listRow({id: 12, name: '无草稿模板', draft_source_filename: ''}),
    listRow({id: 13, name: '已停用模板', is_active: false}),
  ]});
  await renderPage();
  // 默认在用视图只显示启用模板
  const openButtons = container.querySelectorAll('[data-testid="tpl-open"]');
  expect(Array.from(openButtons).map(b => b.textContent.replace(/\s/g, '')))
    .toEqual(['编辑草稿', '上传源文件']);
  // 切换已停用视图后停用模板显示为「查看模板」
  await switchView('disabled');
  const disabledButtons = container.querySelectorAll('[data-testid="tpl-open"]');
  expect(Array.from(disabledButtons).map(b => b.textContent.replace(/\s/g, '')))
    .toEqual(['查看模板']);
});

test('行「更多」菜单：版本记录按行取数打开抽屉，不改动当前模板详情', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  const dropdown = await openRowMenu();
  expect(dropdown.textContent).toContain('版本记录');
  mockHttpGet.mockClear();
  mockHttpGet.mockResolvedValue({data: [
    {id: 5, version_no: 2, template_name: '信道Excel维护台账',
     source_filename: 'channel.xlsx', source_hash: 'a'.repeat(64),
     field_count: 1, published_at: '2026-09-28 11:00:00'},
  ]});
  await act(async () => {
    dropdown.querySelector('[data-testid="tpl-row-versions"]').click();
  });
  await flush();
  expect(mockHttpGet).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/11/versions/');
  // 抽屉标题标注归属模板；页面仍停留在列表（未拉取详情进入工作区）
  expect(document.body.textContent).toContain('已发布版本：信道Excel维护台账');
  expect(container.querySelector('[data-testid="tpl-create"]')).toBeTruthy();
});

test('停用模板：确认框保留引用台账数提示，取消不发请求', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow({ledgers_count: 3})]});
  await renderPage();
  const dropdown = await openRowMenu();
  expect(dropdown.querySelector('[data-testid="tpl-stop"]').textContent)
    .toContain('停用模板');
  await act(async () => {
    dropdown.querySelector('[data-testid="tpl-stop"]').click();
  });
  await flush();
  const modal = document.body.querySelector('.ant-modal-confirm');
  expect(modal.textContent).toContain('停用模板');
  expect(modal.textContent).toContain('该模板已被 3 个台账引用');
  expect(modal.textContent).toContain('历史台账仍可查看与导出');
  await act(async () => {
    popconfirmButton('取消').click();
  });
  await flush();
  expect(mockHttpDelete).not.toHaveBeenCalled();
});

test('确认停用：调用停用端点，提示已停用并重取列表，模板立即移出在用视图', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  const dropdown = await openRowMenu();
  await act(async () => {
    dropdown.querySelector('[data-testid="tpl-stop"]').click();
  });
  await flush();
  mockHttpPost.mockResolvedValue({data: {}});
  // 停用成功后重取列表：该模板已呈停用状态
  mockHttpGet.mockResolvedValue({data: [listRow({is_active: false})]});
  await act(async () => {
    popconfirmButton('停用').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/deactivate/');
  expect(message.success).toHaveBeenCalledWith('模板已停用');
  // 成功后重新拉取模板列表（不做乐观停用）
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/');
  expect(store.deletingId).toBe('');
  // 停用后模板立即从在用视图移出，视图数量准确
  expect(container.textContent).not.toContain('信道Excel维护台账');
  expect(container.textContent).toContain('在用（0）');
  expect(container.textContent).toContain('已停用（1）');
  // 切到已停用视图可见该模板
  await switchView('disabled');
  expect(container.textContent).toContain('信道Excel维护台账');
});

test('停用失败：不显示成功提示，状态复位', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  const dropdown = await openRowMenu();
  await act(async () => {
    dropdown.querySelector('[data-testid="tpl-stop"]').click();
  });
  await flush();
  mockHttpPost.mockRejectedValue('模板不存在或无权限访问');
  await act(async () => {
    popconfirmButton('停用').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/deactivate/');
  expect(message.success).not.toHaveBeenCalledWith('模板已停用');
  expect(store.deletingId).toBe('');
});

test('删除模板（2026-10-16 拆分）：无引用模板提供删除项，确认后物理删除', async () => {
  // 清理上一用例遗留的确认框（停用失败时 Modal 不自动关闭）
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask')
    .forEach(node => node.remove());
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  const dropdown = await openRowMenu();
  // 无引用（ledgers_count 空）：停用 + 删除同时提供
  expect(dropdown.querySelector('[data-testid="tpl-destroy"]')).toBeTruthy();
  await act(async () => {
    dropdown.querySelector('[data-testid="tpl-destroy"]').click();
  });
  await flush();
  const modal = document.body.querySelector('.ant-modal-confirm');
  expect(modal.textContent).toContain('删除模板');
  expect(modal.textContent).toContain('不可恢复');
  // 无引用模板确认框不含引用台账提示
  expect(modal.textContent).not.toContain('个台账引用');
  mockHttpDelete.mockResolvedValue({data: {}});
  mockHttpGet.mockResolvedValue({data: []});
  await act(async () => {
    popconfirmButton('删除').click();
  });
  await flush();
  expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/');
  expect(message.success).toHaveBeenCalledWith('模板已删除');
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/');
});

test('被引用模板：只能停用，无删除项（引用检查以后端为准）', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow({ledgers_count: 3})]});
  await renderPage();
  const dropdown = await openRowMenu();
  expect(dropdown.querySelector('[data-testid="tpl-stop"]')).toBeTruthy();
  expect(dropdown.querySelector('[data-testid="tpl-destroy"]')).toBeNull();
});

test('无 del 权限：行更多菜单无停用项，列表无新建入口', async () => {
  require('libs').hasPermission.mockReturnValue(false);
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await renderPage();
  expect(container.querySelector('[data-testid="tpl-create"]')).toBeNull();
  expect(require('libs').hasPermission).toHaveBeenCalledWith(
    'equipment_lifecycle.ledger_template.del');
  const dropdown = await openRowMenu();
  expect(dropdown.textContent).toContain('版本记录');
  expect(dropdown.querySelector('[data-testid="tpl-stop"]')).toBeNull();
});

test('已停用行（已停用视图）：菜单有版本记录与重新启用，无停用项', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow({is_active: false})]});
  await renderPage();
  await switchView('disabled');
  const dropdown = await openRowMenu();
  expect(dropdown.querySelector('[data-testid="tpl-stop"]')).toBeNull();
  expect(dropdown.querySelector('[data-testid="tpl-activate"]')).toBeTruthy();
});

test('已停用视图重新启用：确认后调用 activate 端点，提示并重取列表', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow({is_active: false})]});
  await renderPage();
  // 默认在用视图不显示停用模板，数量准确
  expect(container.textContent).not.toContain('信道Excel维护台账');
  expect(container.textContent).toContain('在用（0）');
  expect(container.textContent).toContain('已停用（1）');
  await switchView('disabled');
  expect(container.textContent).toContain('信道Excel维护台账');
  const dropdown = await openRowMenu();
  await act(async () => {
    dropdown.querySelector('[data-testid="tpl-activate"]').click();
  });
  await flush();
  const modal = document.body.querySelector('.ant-modal-confirm');
  expect(modal.textContent).toContain('重新启用模板');
  expect(modal.textContent).toContain('恢复用于新台账');
  mockHttpPost.mockResolvedValue({data: {}});
  // 启用成功后重取列表：模板回到在用视图
  mockHttpGet.mockResolvedValue({data: [listRow()]});
  await act(async () => {
    popconfirmButton('重新启用').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/activate/');
  expect(message.success).toHaveBeenCalledWith('模板已重新启用');
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/');
  expect(store.deletingId).toBe('');
  expect(store.disabledCount).toBe(0);
});

test('重新启用失败：不显示成功提示，状态复位', async () => {
  mockHttpGet.mockResolvedValue({data: [listRow({is_active: false})]});
  await renderPage();
  await switchView('disabled');
  const dropdown = await openRowMenu();
  await act(async () => {
    dropdown.querySelector('[data-testid="tpl-activate"]').click();
  });
  await flush();
  mockHttpPost.mockRejectedValue('模板不存在或无权限访问');
  await act(async () => {
    popconfirmButton('重新启用').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-templates/11/activate/');
  expect(message.success).not.toHaveBeenCalledWith('模板已重新启用');
  expect(store.deletingId).toBe('');
});

test('无 del 权限：已停用行菜单无重新启用项', async () => {
  require('libs').hasPermission.mockReturnValue(false);
  mockHttpGet.mockResolvedValue({data: [listRow({is_active: false})]});
  await renderPage();
  await switchView('disabled');
  const dropdown = await openRowMenu();
  expect(dropdown.textContent).toContain('版本记录');
  expect(dropdown.querySelector('[data-testid="tpl-activate"]')).toBeNull();
});

test('视图内搜索：关键词过滤行，清空后恢复', async () => {
  mockHttpGet.mockResolvedValue({data: [
    listRow({id: 11, name: '信道Excel维护台账'}),
    listRow({id: 12, name: 'ILS月维护模板'}),
  ]});
  await renderPage();
  expect(container.textContent).toContain('信道Excel维护台账');
  expect(container.textContent).toContain('ILS月维护模板');
  // antd Input 会把 data-testid 铺到内层 input（或其包装节点），两形态兼容
  const searchBox = container.querySelector('[data-testid="tpl-search"]');
  const input = searchBox.tagName === 'INPUT' ? searchBox : searchBox.querySelector('input');
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(input, 'ILS');
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await flush();
  expect(container.textContent).toContain('ILS月维护模板');
  expect(container.textContent).not.toContain('信道Excel维护台账');
  // 清空关键词恢复全量
  await act(async () => {
    setter.call(input, '');
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await flush();
  expect(container.textContent).toContain('信道Excel维护台账');
});

test('视图内分页：默认每页 10 条，翻页显示剩余行', async () => {
  const rows = [];
  for (let i = 1; i <= 12; i++) {
    rows.push(listRow({id: i, name: `批量模板${String(i).padStart(2, '0')}`}));
  }
  mockHttpGet.mockResolvedValue({data: rows});
  await renderPage();
  expect(container.textContent).toContain('共 12 条');
  let moreButtons = container.querySelectorAll('[data-testid="tpl-more"]');
  expect(moreButtons).toHaveLength(10);
  expect(container.textContent).not.toContain('批量模板12');
  await act(async () => {
    container.querySelector('li.ant-pagination-item-2').click();
  });
  await flush();
  moreButtons = container.querySelectorAll('[data-testid="tpl-more"]');
  expect(moreButtons).toHaveLength(2);
  expect(container.textContent).toContain('批量模板12');
});

test('store 双视图：拆分数量、关键词与类型过滤、切换分页复位', async () => {
  const rows = [];
  for (let i = 1; i <= 12; i++) {
    rows.push(listRow({id: i, name: `在用模板${String(i).padStart(2, '0')}`,
                       ledger_type: 'week_month'}));
  }
  rows.push(listRow({id: 100, name: '停用模板A', is_active: false,
                     ledger_type: 'week_month'}));
  rows.push(listRow({id: 101, name: '停用季模板B', is_active: false,
                     ledger_type: 'seasonal'}));
  mockHttpGet.mockResolvedValue({data: rows});
  await act(async () => {
    await store.fetchList();
  });
  // 视图数量只按启用状态统计，不受过滤影响
  expect(store.activeCount).toBe(12);
  expect(store.disabledCount).toBe(2);
  expect(store.activeTemplates).toHaveLength(12);
  expect(store.disabledTemplates.map(t => t.id)).toEqual([100, 101]);
  // 切换视图分页复位
  store.setListFilter('listPage', 2);
  store.setListView('disabled');
  expect(store.listPage).toBe(1);
  // 维护类型过滤（已停用视图内只看季维护）
  store.setListFilter('listType', 'seasonal');
  expect(store.disabledTemplates.map(t => t.id)).toEqual([101]);
  expect(store.disabledCount).toBe(2);
  // 关键词过滤（名称，大小写不敏感）
  store.setListFilter('listType', '');
  store.setListFilter('listKeyword', '模板a');
  expect(store.disabledTemplates.map(t => t.id)).toEqual([100]);
  // 清空关键词并切回在用视图，行与分页复位
  store.setListFilter('listKeyword', '');
  store.setListView('active');
  expect(store.activeTemplates).toHaveLength(12);
  expect(store.listPage).toBe(1);
});

// ==================== 新建模板流程（2026-10-21 配置前置） ====================

/** 新建表单选项（create-options 端点返回：系统清单 + 按类型收敛的周期）。 */
const CREATE_OPTIONS = {
  systems: [
    {id: 3, system_code: 'SYS-3', name: 'DVOR系统', is_active: true},
    {id: 4, system_code: 'SYS-4', name: 'ILS系统', is_active: false},
  ],
  periods: {
    week_month: [
      {value: 'weekly', label: '每周'},
      {value: 'monthly', label: '每月'},
    ],
    seasonal: [{value: 'seasonal', label: '每航季'}],
  },
};

function mockListAndOptions() {
  mockHttpGet.mockImplementation(url => {
    if (url.endsWith('/create-options/')) {
      return Promise.resolve({data: CREATE_OPTIONS});
    }
    return Promise.resolve({data: []});
  });
}

async function openCreateModal() {
  mockListAndOptions();
  await renderPage();
  await act(async () => {
    container.querySelector('[data-testid="tpl-create"]').click();
  });
  await flush();
  return document.body.querySelector('.ant-modal');
}

function modalButton(modal, text) {
  return Array.from(modal.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text);
}

test('新建流程：弹窗集中名称/类型/适用系统/生成周期/文件，下载样例仅一处', async () => {
  const modal = await openCreateModal();
  expect(modal.textContent).toContain('新建 Excel 台账模板');
  expect(modal.querySelector('[data-testid="tpl-name"]')).toBeTruthy();
  expect(modal.querySelector('[data-testid="tpl-type"]')).toBeTruthy();
  expect(modal.querySelector('[data-testid="tpl-system"]')).toBeTruthy();
  expect(modal.querySelector('[data-testid="tpl-period"]')).toBeTruthy();
  expect(modal.querySelector('[data-testid="tpl-upload"]')).toBeTruthy();
  expect(modal.querySelector('[data-testid="tpl-create-submit"]')).toBeTruthy();
  // 下载样例只出现在该流程内（全页面仅一处）
  const samples = Array.from(document.body.querySelectorAll('button'))
    .filter(node => node.textContent.replace(/\s/g, '') === '下载样例');
  expect(samples).toHaveLength(1);
  await act(async () => {
    samples[0].click();
  });
  expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
    url: '/api/equipment-lifecycle/excel-templates/sample/',
    method: 'get',
  }));
});

test('新建流程：缺项在对应位置提示且不发请求', async () => {
  const modal = await openCreateModal();
  await act(async () => {
    modalButton(modal, '创建并进入模板编辑').click();
  });
  await flush();
  // 统一校验：缺项逐项提示，不发起任何创建请求
  expect(mockHttpPost).not.toHaveBeenCalled();
  ['name', 'uploadType', 'uploadSystem', 'uploadPeriod', 'file'].forEach(key => {
    const line = modal.querySelector(`[data-testid="tpl-create-error-${key}"]`);
    expect(line).toBeTruthy();
    expect(line.textContent).toContain('请');
  });
});

test('新建流程：选择文件只登记不上传，可移除重新选择', async () => {
  const modal = await openCreateModal();
  const input = modal.querySelector('input[type="file"]');
  expect(input).toBeTruthy();
  // 同一节点要模拟两次选文件，files 必须可重定义
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: [new window.File(['x'], 'channel.xlsx')],
  });
  await act(async () => {
    input.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  await flush();
  // 文件名展示，无任何上传请求
  expect(modal.querySelector('[data-testid="tpl-file-name"]').textContent)
    .toContain('channel.xlsx');
  expect(mockHttpPost).not.toHaveBeenCalled();
  // 非 .xlsx 直接拒绝（首次选择后组件重渲染，重新取当前 input 节点）
  const rejectInput = modal.querySelector('input[type="file"]');
  Object.defineProperty(rejectInput, 'files', {
    configurable: true,
    value: [new window.File(['x'], 'old.xls')],
  });
  await act(async () => {
    rejectInput.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  await flush();
  expect(message.error).toHaveBeenCalledWith(
    '仅支持 .xlsx 文件（暂不支持 .xls 与 WPS 私有格式）');
  expect(store.uploadFileName).toBe('channel.xlsx');
  // 移除已选文件
  await act(async () => {
    modal.querySelector('[data-testid="tpl-file-remove"]').click();
  });
  await flush();
  expect(modal.querySelector('[data-testid="tpl-file-name"]')).toBeNull();
  expect(store.pendingCreateFile).toBeNull();
  expect(mockHttpPost).not.toHaveBeenCalled();
});

test('新建流程：切换台账类型收敛生成周期（季维护自动设每航季）', async () => {
  await openCreateModal();
  // 季维护：自动设置并明确显示每航季
  store.setUploadField('uploadType', 'seasonal');
  expect(store.uploadPeriod).toBe('seasonal');
  // 切回周月维护：清除不兼容的周期值
  store.setUploadField('uploadType', 'week_month');
  expect(store.uploadPeriod).toBe('');
  // 周月维护兼容周期保留
  store.setUploadField('uploadPeriod', 'weekly');
  store.setUploadField('uploadType', 'week_month');
  expect(store.uploadPeriod).toBe('weekly');
  // 再切季维护：重新自动设置为每航季
  store.setUploadField('uploadType', 'seasonal');
  expect(store.uploadPeriod).toBe('seasonal');
  // 周期候选按类型收敛（季维护只有每航季）
  expect(store.createPeriodOptions.map(p => p.value)).toEqual(['seasonal']);
});

test('新建流程：填齐后点创建一次提交全部字段并进入工作区', async () => {
  const modal = await openCreateModal();
  store.setUploadField('uploadName', '信道Excel维护台账');
  store.setUploadField('uploadType', 'week_month');
  store.setUploadField('uploadSystem', 3);
  store.setUploadField('uploadPeriod', 'weekly');
  const input = modal.querySelector('input[type="file"]');
  Object.defineProperty(input, 'files', {
    value: [new window.File(['x'], 'channel.xlsx')],
  });
  await act(async () => {
    input.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  await flush();
  expect(mockHttpPost).not.toHaveBeenCalled();
  mockHttpPost.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    modalButton(modal, '创建并进入模板编辑').click();
  });
  await flush();
  // 一次提交携带全部字段（multipart），成功后才提示并进入绑定工作区
  expect(mockHttpPost).toHaveBeenCalledTimes(1);
  const [url, formData] = mockHttpPost.mock.calls[0];
  expect(url).toBe('/api/equipment-lifecycle/excel-templates/');
  expect(formData.get('name')).toBe('信道Excel维护台账');
  expect(formData.get('ledger_type')).toBe('week_month');
  expect(String(formData.get('system'))).toBe('3');
  expect(formData.get('generation_period')).toBe('weekly');
  expect(formData.get('file')).toBeTruthy();
  expect(store.createVisible).toBe(false);
  expect(store.current.name).toBe('信道Excel维护台账');
  expect(container.textContent).toContain('信道Excel维护台账');
  expect(message.success).toHaveBeenCalledWith('模板创建成功，请绑定可填写单元格');
});

test('新建流程：创建失败弹窗保持打开可重试，不显示成功提示', async () => {
  const modal = await openCreateModal();
  store.setUploadField('uploadName', '信道Excel维护台账');
  store.setUploadField('uploadType', 'week_month');
  store.setUploadField('uploadSystem', 3);
  store.setUploadField('uploadPeriod', 'weekly');
  const input = modal.querySelector('input[type="file"]');
  Object.defineProperty(input, 'files', {
    value: [new window.File(['x'], 'bad.xlsx')],
  });
  await act(async () => {
    input.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  await flush();
  mockHttpPost.mockRejectedValue('模板包含平台暂不支持的特性：公式计算');
  await act(async () => {
    modalButton(modal, '创建并进入模板编辑').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledTimes(1);
  expect(store.createVisible).toBe(true);
  expect(store.current).toBeNull();
  expect(message.success).not.toHaveBeenCalled();
  // 修正后可重试：第二次请求成功
  mockHttpPost.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    modalButton(modal, '创建并进入模板编辑').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledTimes(2);
  expect(store.createVisible).toBe(false);
  expect(message.success).toHaveBeenCalledWith('模板创建成功，请绑定可填写单元格');
});

test('上传成功进入绑定工作区并渲染合并布局', async () => {
  const detail = makeDetail();
  mockHttpPost.mockResolvedValue({data: detail});
  await act(async () => {
    await store.upload({name: '信道Excel维护台账', ledger_type: 'week_month'}, {name: 'channel.xlsx'});
  });
  await renderPage();
  expect(container.textContent).toContain('信道Excel维护台账');
  expect(container.textContent).toContain('周月维护');
  expect(container.querySelector('table.proto-table')).toBeTruthy();
  expect(container.querySelector('td[data-coord="A1"]').textContent).toContain('信道维护记录表');
  expect(container.querySelector('td[data-coord="C2"]').textContent).toContain('PS模块');
});
