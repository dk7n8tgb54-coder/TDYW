/**
 * LayoutTable 空格保真测试（真实渲染 + jsdom，2026-10-01）。
 *
 * 覆盖任务书「Excel 预览空格保真」：模板单元格文本（首部空格/连续
 * 空格/中间空格/换行）在预览中逐字符保留——非换行单元格 white-space: pre
 * （不折叠连续空格，配合 overflow hidden 裁剪，行高稳定），换行单元格
 * white-space: pre-wrap + break-word；无样式单元格同样按 pre 保留空白；
 * 历史回放（fillMode + readOnly）的填写值同样保留。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

import LayoutTable from '../components/LayoutTable';

const SHEET = {
  name: 'Sheet1',
  max_row: 2,
  max_column: 3,
  merged_ranges: [],
  row_heights: {},
  column_widths: {A: 24, B: 18, C: 18},
  hidden_rows: [],
  hidden_columns: [],
  cells: {
    // 无样式单元格：默认也有 pre（样式缺失不代表可以折叠空格）
    A1: {v: '     年   月   日'},
    // 非 wrap：保留空格、单行裁剪
    B1: {
      v: '维护记录：                              温度：',
      s: {align: {h: 'left', v: 'center'}},
    },
    // wrap：保留空格 + 自动换行 + 长词断行
    C1: {v: '温 度 湿 度 连续空格      结束', s: {align: {h: 'left', wrap: true}}},
    A2: {v: 'ICS 200/60内话系统周月维护记录表'},
  },
};

const BINDING = {
  field_id: 'bbbbbbbb-2222-4bbb-8bbb-000000000002',
  sheet_name: 'Sheet1',
  cell_coordinate: 'A2',
  field_name: '温度记录',
  input_type: 'text',
  is_required: false,
  unit: '',
  options: [],
};

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  container = null;
});

function renderTable(props) {
  return act(() => {
    ReactDOM.render(<LayoutTable {...props}/>, container);
  });
}

function cellNode(coordinate) {
  return container.querySelector(`td[data-coord="${coordinate}"]`);
}

test('预览保留首部空格与字间空格（textContent 逐字符一致）', async () => {
  await renderTable({sheet: SHEET, bindingByCell: {}, fillMode: false});
  expect(cellNode('A1').textContent).toBe('     年   月   日');
  expect(cellNode('B1').textContent).toBe('维护记录：                              温度：');
  expect(cellNode('C1').textContent).toBe('温 度 湿 度 连续空格      结束');
  expect(cellNode('A2').textContent).toBe('ICS 200/60内话系统周月维护记录表');
});

test('非换行单元格 white-space: pre，换行单元格 pre-wrap + break-word', async () => {
  await renderTable({sheet: SHEET, bindingByCell: {}, fillMode: false});
  // 无样式单元格（A1）与非 wrap 单元格（B1）：pre
  expect(cellNode('A1').style.whiteSpace).toBe('pre');
  expect(cellNode('B1').style.whiteSpace).toBe('pre');
  // wrap 单元格（C1）：pre-wrap + break-word
  expect(cellNode('C1').style.whiteSpace).toBe('pre-wrap');
  expect(cellNode('C1').style.wordBreak).toBe('break-word');
  // 溢出裁剪保持（表格布局宽度稳定不跳动）
  expect(cellNode('C1').style.overflow).toBe('hidden');
});

test('历史回放（fillMode + readOnly）填写值空格同样保留', async () => {
  const filled = '  温 度 25.5  ';
  await renderTable({
    sheet: SHEET,
    bindingByCell: {[`Sheet1!${BINDING.cell_coordinate}`]: BINDING},
    fillMode: true,
    readOnly: true,
    values: {[BINDING.field_id]: filled},
  });
  const node = cellNode('A2');
  expect(node.textContent).toBe(filled);
  expect(node.style.whiteSpace).toBe('pre');
});

test('换行单元格文本按行保留（wrap 渲染两行）', async () => {
  const sheet = {
    ...SHEET,
    cells: {...SHEET.cells, B2: {v: 'line1\nline2', s: {align: {wrap: true}}}},
  };
  await renderTable({sheet, bindingByCell: {}, fillMode: false});
  const node = cellNode('B2');
  expect(node.textContent).toBe('line1\nline2');
  expect(node.style.whiteSpace).toBe('pre-wrap');
});
