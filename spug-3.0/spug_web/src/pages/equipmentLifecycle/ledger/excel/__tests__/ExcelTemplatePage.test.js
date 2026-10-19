/**
 * Excel 台账模板页列表测试（真实渲染 + jsdom + http mock，2026-09-28 试点；
 * 2026-10-14 交互改造；绑定工作区测试见同目录 ExcelTemplatePageWorkspace.test.js）。
 *
 * 覆盖：列表渲染（唯一主操作「新建模板」+ 弹窗流程、行操作按状态、更多
 * 菜单、停用确认与权限）→ 上传守卫 → 上传成功进入绑定工作区。
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
  expect(container.textContent).toContain('信道Excel维护台账');
  expect(container.textContent).toContain('周月维护');
  expect(container.querySelector('table.proto-table')).toBeTruthy();
  expect(container.querySelector('td[data-coord="A1"]').textContent).toContain('信道维护记录表');
  expect(container.querySelector('td[data-coord="C2"]').textContent).toContain('PS模块');
});
