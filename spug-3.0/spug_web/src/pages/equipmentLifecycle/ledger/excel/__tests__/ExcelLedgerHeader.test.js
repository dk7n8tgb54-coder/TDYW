/**
 * Excel 台账表头执行信息录入（2026-10-14）页面行为测试。
 *
 * 真实渲染 ExcelLedgerDetail（jsdom + http mock），验证：
 * - 周期生成的应填台账（执行日期为空）：详情显示计划期次、执行日期
 *   占位"执行后录入"，可编辑状态提供录入控件；
 * - 保存执行日期经 PUT header 提交（不冒充创建当天、不改台账编号）；
 * - 已完成（不可编辑）状态只读展示，不提供录入控件。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockExportFile = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: jest.fn(),
  },
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

const {ExcelLedgerStore} = require('../excelLedgerStore');
const ExcelLedgerDetail = require('../ExcelLedgerDetail').default;

const FIELD_PS = 'aaaaaaaa-1111-4aaa-8aaa-000000000001';

const SHEET = {
  name: '信道维护记录', max_row: 4, max_column: 8, merged_ranges: [],
  row_heights: {}, column_widths: {},
  cells: {A1: {v: '信道维护记录表'}, C3: {v: ''}},
};

const BINDINGS = [{
  field_id: FIELD_PS, sheet_name: '信道维护记录', cell_coordinate: 'C3',
  field_name: 'PS模块', input_type: 'status', is_required: true,
  unit: '', options: ['正常', '异常'],
}];

function makeDetail(overrides = {}) {
  return {
    id: 101,
    ledger_no: 'EL-WM-20261012-0001',
    ledger_type: 'week_month',
    executed_date: null,
    created_at: '2026-10-12 08:30:00',
    created_by_name: '王五',
    maintenance_period: '2026-10-12',
    status: 'draft',
    created_from: 'excel_template',
    excel: {
      record_id: 7,
      values: {},
      editable: true,
      version: {
        id: 5, version_no: 1, template_name: '信道Excel维护台账',
        ledger_type: 'week_month', source_filename: 'channel.xlsx',
        source_hash: 'a'.repeat(64), field_count: 1,
        published_at: '2026-10-14 09:00:00',
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
        bindings: BINDINGS,
      },
    },
    ...overrides,
  };
}

let container = null;
let store = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockExportFile].forEach(fn => fn.mockReset());
  store = new ExcelLedgerStore();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask').forEach(node => node.remove());
});

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

async function renderDetail(detail) {
  await act(async () => {
    store.applyDetail({data: detail});
  });
  await act(async () => {
    ReactDOM.render(h(ExcelLedgerDetail, {store, onBack: () => {}}), container);
  });
  await flush();
}

describe('ExcelLedgerDetail 表头执行信息', () => {
  test('周期生成台账显示计划期次与空的执行日期录入控件', async () => {
    await renderDetail(makeDetail());
    const text = container.textContent;
    expect(text).toContain('计划期次');
    expect(text).toContain('2026-10-12');
    expect(text).toContain('实际执行日期');
    // 列表已不放录入时间（2026-10-18 移入详情），Excel 详情头部展示创建时间
    expect(text).toContain('录入时间');
    expect(text).toContain('2026-10-12 08:30:00');
    // 可编辑状态提供录入控件（占位提示执行后录入），不做创建当天伪装
    expect(document.body.querySelector('[data-testid="excel-executed-date"]')).toBeTruthy();
    expect(document.body.querySelector('[data-testid="excel-save-executed-date"]')).toBeTruthy();
  });

  test('保存执行日期经 PUT header 提交并以详情回显', async () => {
    await renderDetail(makeDetail());
    mockHttpPut.mockResolvedValue({data: makeDetail({
      executed_date: '2026-10-16', created_by_name: '王五',
    })});
    const save = document.body.querySelector('[data-testid="excel-save-executed-date"]');
    await act(async () => {
      save.click();
    });
    await flush();
    // 未选日期保存 = 清空语义（空串），此处验证请求形态与回显链路
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/101/',
      {header: {executed_date: ''}});
    // 回显：执行日期经 DatePicker input value 展示（不在 textContent），录入人入文本
    const pickerNode = document.body.querySelector('[data-testid="excel-executed-date"]');
    const pickerInput = pickerNode.tagName === 'INPUT'
      ? pickerNode : pickerNode.querySelector('input');
    expect(pickerInput.value).toBe('2026-10-16');
    expect(container.textContent).toContain('王五');
  });

  test('已完成（不可编辑）状态只读展示执行日期，不提供录入控件', async () => {
    await renderDetail(makeDetail({
      status: 'completed', executed_date: '2026-10-16',
      excel: {
        record_id: 7, values: { [FIELD_PS]: '正常' }, editable: false,
        version: makeDetail().excel.version,
      },
    }));
    expect(container.textContent).toContain('2026-10-16');
    expect(document.body.querySelector('[data-testid="excel-executed-date"]')).toBeNull();
  });
});
