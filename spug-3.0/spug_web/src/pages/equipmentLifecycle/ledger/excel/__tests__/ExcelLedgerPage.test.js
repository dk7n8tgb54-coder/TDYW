/**
 * Excel 维护台账页测试（真实渲染 + jsdom + http mock，2026-09-28 试点）。
 *
 * 覆盖：列表渲染（模板版本列）→ 创建台账（可用版本加载/提交载荷）→
 * 填写详情（绑定单元格渲染输入控件、setValue、保存载荷）→ 提交必填拦截
 * 与成功提交 → 已提交历史只读回放（无输入控件、有填写值文本）→ 导出
 * 走 exportFile → 复核沿用既有端点并重取 Excel 详情。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockExportFile = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: jest.fn()},
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

const loadPage = () => require('../ExcelLedgerPage').default;
const {ExcelLedgerStore} = require('../excelLedgerStore');

const FIELD_PS = 'aaaaaaaa-1111-4aaa-8aaa-000000000001';
const FIELD_REMARK = 'aaaaaaaa-1111-4aaa-8aaa-000000000002';

const SHEET = {
  name: '信道维护记录', max_row: 4, max_column: 8,
  merged_ranges: ['A1:H1'],
  row_heights: {'1': 30},
  column_widths: {A: 12},
  cells: {
    A1: {v: '信道维护记录表'}, A2: {v: '信道'}, C2: {v: 'PS模块'},
    A3: {v: '第1信道'}, B3: {v: '主电台'},
    C3: {s: {border: {top: {style: 'thin'}}}},
    H3: {s: {border: {top: {style: 'thin'}}}},
  },
};

const BINDINGS = [
  {field_id: FIELD_PS, sheet_name: '信道维护记录', cell_coordinate: 'C3',
   field_name: 'PS模块', input_type: 'status', is_required: true,
   unit: '', options: ['正常', '异常'], default_value: '',
   operation_guide: '检查模块指示灯', abnormal_rule: '', maintenance_cycles: ['all']},
  {field_id: FIELD_REMARK, sheet_name: '信道维护记录', cell_coordinate: 'H3',
   field_name: '备注', input_type: 'text', is_required: false,
   unit: '', options: [], default_value: '', operation_guide: '',
   abnormal_rule: '', maintenance_cycles: ['all']},
];

function makeDetail(status = 'draft', values = {}, editable = status === 'draft' || status === 'returned') {
  return {
    id: 33,
    ledger_no: 'EL-WM-20260928-001',
    ledger_type: 'week_month',
    executed_date: '2026-09-28',
    status,
    created_from: 'excel_template',
    excel: {
      record_id: 7,
      values,
      editable,
      version: {
        id: 5, version_no: 1, template_name: '信道Excel维护台账',
        ledger_type: 'week_month', source_filename: 'channel.xlsx',
        source_hash: 'a'.repeat(64), field_count: 2,
        published_at: '2026-09-28 09:00:00',
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
        bindings: BINDINGS,
      },
    },
  };
}

let container = null;
let store = null;

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

const inputSetter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, 'value').set;
const selectSetter = Object.getOwnPropertyDescriptor(
  window.HTMLSelectElement.prototype, 'value').set;

function setInputValue(node, value) {
  (node.tagName === 'SELECT' ? selectSetter : inputSetter).call(node, value);
  node.dispatchEvent(new Event(node.tagName === 'SELECT' ? 'change' : 'input',
    {bubbles: true}));
}

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
  store = new ExcelLedgerStore();
  jest.clearAllMocks();
  mockExportFile.mockResolvedValue(undefined);
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

test('列表渲染 Excel 台账与模板版本信息', async () => {
  mockHttpGet.mockResolvedValue({data: {
    data: [{id: 33, ledger_no: 'EL-WM-20260928-001', ledger_type: 'week_month',
            executed_date: '2026-09-28', status: 'draft',
            excel: {version_no: 1, template_name: '信道Excel维护台账'}}],
    total: 1, page: 1, page_size: 20,
  }});
  await renderPage();
  expect(container.textContent).toContain('EL-WM-20260928-001');
  expect(container.textContent).toContain('信道Excel维护台账 v1');
  expect(container.textContent).toContain('周月维护');
});

test('创建台账：加载可用版本并提交正确载荷', async () => {
  mockHttpGet.mockReset();
  mockHttpGet.mockImplementation(url => {
    if (url.includes('available')) {
      return Promise.resolve({data: [{id: 11, name: '信道Excel维护台账',
        ledger_type: 'week_month',
        versions: [{id: 5, version_no: 1, field_count: 2, source_filename: 'channel.xlsx'}]}]});
    }
    return Promise.resolve({data: {data: [], total: 0}});
  });
  mockHttpPost.mockResolvedValue({data: makeDetail()});
  await renderPage();
  await act(async () => {
    buttonByText('创建台账').click();
  });
  await flush();
  expect(mockHttpGet).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-templates/available/',
    expect.objectContaining({params: {}}));
  await act(async () => {
    await store.createLedger({
      version_id: 5, executed_date: '2026-09-28',
      ledger_type: 'week_month',
      client_token: 'excel-5-20260928',
    });
  });
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/', {
    version_id: 5, executed_date: '2026-09-28',
    ledger_type: 'week_month', client_token: 'excel-5-20260928',
  });
});

test('草稿详情：绑定单元格渲染输入控件并保存填写值', async () => {
  mockHttpGet.mockResolvedValue({data: makeDetail('draft')});
  store.applyDetail({data: makeDetail('draft')});
  mockHttpPut.mockResolvedValue({data: makeDetail('draft', {
    [FIELD_PS]: '正常', [FIELD_REMARK]: '阻抗正常'})});
  await renderPage();
  expect(container.querySelector('td[data-coord="C3"] .ant-select')).toBeTruthy();
  expect(container.querySelector('td[data-coord="H3"] input')).toBeTruthy();
  // 未填写必填格标记
  expect(container.querySelector('td[data-coord="C3"]').className).toContain('proto-cell-missing-required');
  // 填写并保存
  await act(async () => {
    store.setValue(FIELD_PS, '正常');
    store.setValue(FIELD_REMARK, '阻抗正常');
  });
  await act(async () => {
    await store.saveValues();
  });
  expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/33/',
    {values: {[FIELD_PS]: '正常', [FIELD_REMARK]: '阻抗正常'}});
  expect(message.success).toHaveBeenCalledWith('填写值已保存');
});

test('完成填写：必填未填拦截不发请求，填写齐全后完成成功', async () => {
  mockHttpGet.mockResolvedValue({data: makeDetail('draft')});
  store.applyDetail({data: makeDetail('draft')});
  await renderPage();
  // 必填未填 → warning，无请求（主操作按钮为"完成填写"）
  await act(async () => {
    buttonByText('完成填写').click();
  });
  expect(message.warning).toHaveBeenCalledWith(expect.stringContaining('必填字段未填写'));
  expect(mockHttpPost).not.toHaveBeenCalled();
  // 填齐后完成填写
  store.applyDetail({data: makeDetail('draft', {[FIELD_PS]: '正常'})});
  mockHttpPost.mockResolvedValue({data: makeDetail('completed', {[FIELD_PS]: '正常'}, false)});
  await act(async () => {
    await store.complete();
  });
  expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/33/complete/');
  expect(message.success).toHaveBeenCalledWith('已完成填写');
});

test('历史详情只读回放：无输入控件、展示当时填写值', async () => {
  store.applyDetail({data: makeDetail('reviewed', {[FIELD_PS]: '正常', [FIELD_REMARK]: '测试完成'}, false)});
  await renderPage();
  expect(store.editable).toBe(false);
  expect(container.querySelector('td[data-coord="C3"] .ant-select')).toBeNull();
  expect(container.querySelector('td[data-coord="H3"] input')).toBeNull();
  expect(container.querySelector('td[data-coord="C3"]').textContent).toContain('正常');
  expect(container.querySelector('td[data-coord="H3"]').textContent).toContain('测试完成');
  // 只读态没有保存/完成按钮
  expect(buttonByText('保存草稿')).toBeUndefined();
  expect(buttonByText('完成填写')).toBeUndefined();
  expect(buttonByText('复核')).toBeUndefined();
});

test('点击单元格不报错（填写/历史视图缺省选格回调无副作用）', async () => {
  store.applyDetail({data: makeDetail('draft')});
  await renderPage();
  // 填写视图点击绑定格与普通格均不应抛错（onSelectCell 缺省）
  await act(async () => {
    container.querySelector('td[data-coord="C3"]').click();
    container.querySelector('td[data-coord="A1"]').click();
  });
  expect(container.querySelector('td[data-coord="C3"] .ant-select')).toBeTruthy();
  // 历史只读态同样可点击
  store.applyDetail({data: makeDetail('reviewed', {[FIELD_PS]: '正常'}, false)});
  await flush();
  await act(async () => {
    container.querySelector('td[data-coord="C3"]').click();
  });
  expect(container.querySelector('td[data-coord="C3"]').textContent).toContain('正常');
});

test('导出走 exportFile 且必填未填时拦截', async () => {
  store.applyDetail({data: makeDetail('draft')});
  await renderPage();
  // 必填未填拦截
  await act(async () => {
    buttonByText('导出Excel').click();
  });
  expect(mockExportFile).not.toHaveBeenCalled();
  // 填齐后导出 PDF（先预检，无提示直接导出）
  store.applyDetail({data: makeDetail('draft', {[FIELD_PS]: '异常'})});
  await flush();
  await act(async () => {
    buttonByText('导出PDF').click();
  });
  await flush();
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/excel-ledgers/33/export/check/', {});
  expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
    url: '/api/equipment-lifecycle/excel-ledgers/33/export/pdf/',
    method: 'post',
  }));
});

test('导出 PDF 预检有提示时先确认，确认后继续导出', async () => {
  store.applyDetail({data: makeDetail('draft', {[FIELD_PS]: '异常'})});
  await renderPage();
  mockHttpPost.mockResolvedValue({data: {warnings: ['工作表「信道维护记录」内容较宽']}});
  await act(async () => {
    buttonByText('导出PDF').click();
  });
  await flush();
  expect(mockExportFile).not.toHaveBeenCalled();
  const confirmNode = document.querySelector('.ant-modal-confirm');
  expect(confirmNode).toBeTruthy();
  expect(confirmNode.textContent).toContain('导出前检查发现以下问题');
  expect(confirmNode.textContent).toContain('内容较宽');
  const okButton = Array.from(document.querySelectorAll('.ant-modal-confirm button'))
    .find(node => node.textContent.replace(/\s/g, '') === '仍要导出');
  await act(async () => {
    okButton.click();
  });
  await flush();
  expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
    url: '/api/equipment-lifecycle/excel-ledgers/33/export/pdf/',
    method: 'post',
  }));
});

test('已完成台账作废沿用既有台账端点并重取 Excel 详情', async () => {
  store.applyDetail({data: makeDetail('completed', {[FIELD_PS]: '正常'}, false)});
  await renderPage();
  mockHttpPost.mockResolvedValue({data: {data: {id: 33}}});
  mockHttpGet.mockResolvedValue({data: makeDetail('void', {[FIELD_PS]: '正常'}, false)});
  await act(async () => {
    await store.voidLedger('数据有误需重做');
  });
  expect(mockHttpPost).toHaveBeenCalledWith(
    '/api/equipment-lifecycle/ledgers/33/void/', {reason: '数据有误需重做'});
  expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/33/');
  expect(store.detail.status).toBe('void');
});

test('一键正常：仅填充未填写的正常/异常格，文本格不参与', async () => {
  store.applyDetail({data: makeDetail('draft')});
  await renderPage();
  const button = buttonByText('一键正常');
  expect(button).toBeTruthy();
  await act(async () => {
    button.click();
  });
  expect(store.values[FIELD_PS]).toBe('正常');
  expect(store.values[FIELD_REMARK]).toBeUndefined();
  expect(message.success).toHaveBeenCalledWith(
    expect.stringContaining('1 个未填写单元格填为正常'));
});

test('一键正常：已填异常不覆盖，无未填项时警告且不改值', async () => {
  store.applyDetail({data: makeDetail('draft', {[FIELD_PS]: '异常'})});
  await renderPage();
  await act(async () => {
    buttonByText('一键正常').click();
  });
  expect(store.values[FIELD_PS]).toBe('异常');
  expect(message.warning).toHaveBeenCalledWith('没有未填写的正常/异常单元格');
  expect(message.success).not.toHaveBeenCalled();
});

test('一键正常：只读历史态不渲染按钮', async () => {
  store.applyDetail({data: makeDetail('reviewed', {}, false)});
  await renderPage();
  expect(buttonByText('一键正常')).toBeUndefined();
});
