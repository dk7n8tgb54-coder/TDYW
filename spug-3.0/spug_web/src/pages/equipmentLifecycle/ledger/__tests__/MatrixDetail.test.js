/**
 * 矩阵台账详情渲染测试（真实渲染 LedgerDetail）：
 * - 矩阵台账：行层级独立列 × 列项目矩阵（父节点 rowSpan 合并、
 *   完整行路径见 tooltip 与导出/异常清单）+ 异常单元格清单（含处置状态入口）；
 * - 历史台账（无行实例）：保持按系统分组的历史记录展示，不补造行树。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
}));

jest.mock('../../workOrder/LedgerItemDisposition', () => ({
  DispositionTag: () => <span>处置状态</span>,
  ConvertActions: () => <a>转单</a>,
}));

jest.mock('../../workOrder/WorkOrderDetail', () => () => null);

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function matrixDetail() {
  const columns = [1, 2].map(id => id);
  const cell = (id, instanceId, itemId, name, path, value, result) => ({
    id, ledger: 1, system: 7, system_name: '台站系统', template_item: itemId,
    item_name: name, input_type: 'choice', unit: '', choices: ['正常', '不正常'],
    is_required: true, value_text: value, value_number: null, value_bool: null,
    result, abnormal_desc: result === 'abnormal' ? '驻波比超限' : '',
    na_reason: '', onsite_action: '', executor_name: '', executed_at: null,
    is_temporary: false, display_order: 0,
    row_instance: instanceId, row_path: path, row_level: 2,
    row_code: `I${instanceId}`, column_name: name, column_code: String(itemId),
    cell_code: `I${instanceId}:${itemId}`, operation_guide: '',
    disposition: {status: 'none'},
  });
  const cells = [];
  let id = 1;
  columns.forEach(itemId => {
    const name = itemId === 1 ? 'PS模块' : 'TX模块';
    cells.push(cell(id++, 11, itemId, name, '第1信道 / 主电台', '正常', 'normal'));
    cells.push(cell(id++, 12, itemId, name, '第1信道 / 备电台',
      itemId === 1 ? '不正常' : '', itemId === 1 ? 'abnormal' : ''));
  });
  return {
    id: 1, ledger_no: 'EL-WM-20260920-0001', ledger_type: 'week_month',
    executed_date: '2026-09-20', status: 'draft',
    executor_names: '甲', entry_channel: 'web', created_from: 'template',
    version: 1, created_by_name: 'op', has_row_instances: true,
    template: 3, template_name: '矩阵模板A',
    row_instances: [{
      id: 10, ledger: 1, template_node: 9, parent_instance: null,
      instance_name: '第1信道', instance_code: 'I10', row_path: '第1信道',
      row_level: 1, display_order: 0, is_leaf: false, children_count: 2,
      children: [
        {id: 11, ledger: 1, template_node: 10, parent_instance: 10,
          instance_name: '主电台', instance_code: 'I11', row_path: '第1信道 / 主电台',
          row_level: 2, display_order: 0, is_leaf: true, children_count: 0, children: []},
        {id: 12, ledger: 1, template_node: 11, parent_instance: 10,
          instance_name: '备电台', instance_code: 'I12', row_path: '第1信道 / 备电台',
          row_level: 2, display_order: 1, is_leaf: true, children_count: 0, children: []},
      ],
    }],
    items: cells,
    corrections: [],
  };
}

describe('LedgerDetail 矩阵台账', () => {
  it('渲染行路径 × 列项目矩阵与异常单元格页签', async () => {
    const LedgerDetail = require('../LedgerDetail').default;
    const store = {detail: matrixDetail(), detailVisible: true, closeDetail: jest.fn()};
    await act(async () => {
      ReactDOM.render(<LedgerDetail store={store}/>, container);
    });
    await act(flush);
    // antd4 未激活页签不渲染内容：先点击"检查明细（矩阵）"页签
    const matrixTab = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .find(t => t.textContent.includes('检查明细（矩阵）'));
    expect(matrixTab).toBeTruthy();
    await act(async () => {
      matrixTab.click();
    });
    await act(flush);
    expect(document.body.textContent).toContain('第1信道');
    expect(document.body.textContent).toContain('主电台');
    expect(document.body.textContent).toContain('备电台');
    expect(document.body.textContent).toContain('PS模块');
    // 行树的每一级渲染为独立表格列：第1级/第2级，树未达到的深层级自动隐藏
    const headers = Array.from(document.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent.trim());
    expect(headers).toContain('第1级');
    expect(headers).toContain('第2级');
    expect(headers.some(h => h.startsWith('第3级'))).toBe(false);
    // 父节点"第1信道"在第 1 级列 rowSpan 纵向合并主/备电台两行
    const mergedCell = document.querySelector('.ant-table-tbody td[rowspan="2"]');
    expect(mergedCell).toBeTruthy();
    expect(mergedCell.textContent).toContain('第1信道');
    // 异常单元格页签
    const abnormalTab = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .find(t => t.textContent.includes('异常单元格'));
    expect(abnormalTab).toBeTruthy();
    await act(async () => {
      abnormalTab.click();
    });
    await act(flush);
    expect(document.body.textContent).toContain('驻波比超限');
  });

  it('历史台账（无行实例）按系统分组展示，不补造行树', async () => {
    const LedgerDetail = require('../LedgerDetail').default;
    const detail = matrixDetail();
    detail.row_instances = [];
    detail.items = detail.items.slice(0, 2).map(c => ({
      ...c, row_instance: null, row_path: '', row_level: null,
      row_code: '', column_name: '', column_code: '', cell_code: '',
    }));
    const store = {detail, detailVisible: true, closeDetail: jest.fn()};
    await act(async () => {
      ReactDOM.render(<LedgerDetail store={store}/>, container);
    });
    await act(flush);
    expect(document.body.textContent).toContain('检查明细');
    expect(document.body.textContent).not.toContain('检查明细（矩阵）');
    expect(document.body.textContent).not.toContain('第1信道');
  });
});
