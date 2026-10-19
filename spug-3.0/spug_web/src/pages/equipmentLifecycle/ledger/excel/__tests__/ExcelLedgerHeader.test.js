/**
 * Excel 台账详情表头（2026-10-19 改版）页面行为测试。
 *
 * 真实渲染 ExcelLedgerDetail（jsdom + http mock），验证：
 * - 模板信息置首（用户指定顺序），状态/类型/计划期次/完成时间/录入人/
 *   录入时间依次排列；执行日期字段已删除（由台账表格内容承载）；
 * - 草稿与已完成状态都不再提供执行日期录入控件。
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

/** Descriptions 渲染顺序 = DOM 中 ant-descriptions-item 的出现顺序。 */
function headerLabels(root) {
  return Array.from(root.querySelectorAll('.ant-descriptions-item-label'))
    .map(node => node.textContent.trim());
}

describe('ExcelLedgerDetail 表头信息', () => {
  test('模板信息置首，其余字段依次排列；执行日期字段不再展示', async () => {
    await renderDetail(makeDetail());
    const text = container.textContent;
    expect(headerLabels(container)).toEqual([
      '模板', '状态', '类型', '计划期次',
      '完成时间', '录入人', '录入时间', '版本', '源文件', 'SHA-256']);
    // 模板名取自版本快照
    expect(text).toContain('信道Excel维护台账');
    expect(text).toContain('计划期次');
    expect(text).toContain('2026-10-12');
    // 列表已不放录入时间（2026-10-18 移入详情），Excel 详情头部展示创建时间
    expect(text).toContain('录入时间');
    expect(text).toContain('2026-10-12 08:30:00');
    // 执行日期字段已删除：不出现标签，也不再有录入控件
    expect(text).not.toContain('实际执行日期');
    expect(document.body.querySelector('[data-testid="excel-executed-date"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="excel-save-executed-date"]')).toBeNull();
  });

  test('已完成（不可编辑）状态同样无执行日期录入控件', async () => {
    await renderDetail(makeDetail({
      status: 'completed',
      excel: {
        record_id: 7, values: {[FIELD_PS]: '正常'}, editable: false,
        version: makeDetail().excel.version,
      },
    }));
    expect(container.textContent).toContain('已完成');
    expect(document.body.querySelector('[data-testid="excel-executed-date"]')).toBeNull();
  });
});
