/**
 * LayoutTable 列宽渲染契约（2026-10-19 列宽范围缺陷回归）。
 *
 * 缺陷背景：模板源文件用单条 <col min="1" max="3" width="36.21"> 统一
 * 设定 A:C 三列同宽；旧后端解析只把宽度记在 A 列，B/C 被记成 openpyxl
 * 缺省宽度 13——网页把 B/C 画窄，表格从左页边距开始显示时右侧留白
 * （Excel 打印预览三列同宽，导出 PDF 不受影响）。后端已展开 min/max
 * 范围并对旧快照做读取端修正，本页按 column_widths 逐列渲染，契约：
 * 1. A:C 同宽快照 → 三列像素宽一致（本次偏左场景的页面级回归）；
 * 2. 旧坏数据（A=36.21/B=13/C=13）忠实渲染为前宽后窄——固化逐列
 *    宽度公式，防止渲染层用等宽/均分掩盖数据问题；
 * 3. 未设置宽度的列按 Excel 内置缺省 8.43 兜底。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

import LayoutTable from '../components/LayoutTable';

const SHEET_BASE = {
  name: 'Sheet1',
  max_row: 1,
  max_column: 3,
  merged_ranges: [],
  row_heights: {},
  hidden_rows: [],
  hidden_columns: [],
  cells: {A1: {v: '维护台账'}, C1: {v: '备注'}},
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

function renderTable(sheet) {
  return act(() => {
    ReactDOM.render(
      <LayoutTable sheet={sheet} bindingByCell={{}} fillMode={false}/>,
      container);
  });
}

function columnWidths() {
  return Array.from(container.querySelectorAll('colgroup > col'),
    node => node.style.width);
}

test('A:C 同宽快照渲染三列等宽（列宽范围偏左场景回归）', async () => {
  await renderTable({...SHEET_BASE, column_widths: {A: 36.21, B: 36.21, C: 36.21}});
  // 宽度公式 Math.round(width * 7 + 5)：36.21 -> 258px
  expect(columnWidths()).toEqual(['258px', '258px', '258px']);
});

test('旧坏快照（A=36.21/B=13/C=13）逐列忠实渲染为前宽后窄', async () => {
  await renderTable({...SHEET_BASE, column_widths: {A: 36.21, B: 13, C: 13}});
  // 13 -> Math.round(13 * 7 + 5) = 96px：旧解析落库的坏列宽在页面上的
  // 表现（后端读取端修正后不再出现此形态，渲染层不掩盖）
  expect(columnWidths()).toEqual(['258px', '96px', '96px']);
});

test('未设置宽度的列按 Excel 内置缺省 8.43 兜底', async () => {
  await renderTable({...SHEET_BASE, column_widths: {A: 36.21}});
  // 8.43 -> Math.round(8.43 * 7 + 5) = 64px
  expect(columnWidths()).toEqual(['258px', '64px', '64px']);
});
