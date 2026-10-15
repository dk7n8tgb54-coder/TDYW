/**
 * LayoutTable 填写区尺寸匹配测试（真实渲染 + jsdom，2026-10-14）。
 *
 * 复现任务书问题并固化修复行为：模板解析（后端 parse_workbook 已实证）
 * 与布局渲染（colSpan/rowSpan/行高）均保留合并与尺寸信息，问题在输入
 * 控件层——此前一律单行 Input。覆盖：
 * 1. 纵向合并多行的文本填写格 → 多行文本域绝对定位填满单元格
 *    （高度 = 跨行行高逐行换算累计 - 内边距），输入值走 onValueChange；
 * 2. 横向合并多列（一行默认高）的文本填写格 → 仍单行输入框
 *    （横向合并不算高度）；
 * 3. 显式大行高的单格文本填写格 → 多行文本域；显式小行高 → 单行；
 * 4. 正常/异常（Select）与数值/日期类型不受高度影响；
 * 5. 必填标记在多行文本域上仍可见（绝对定位不被文本域遮盖）；
 * 6. utils 几何计算：跨行累计、隐藏行计 0、单行高合并格提示收集。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

import LayoutTable from '../components/LayoutTable';
import {
  DEFAULT_ROW_HEIGHT_PT, TALL_FILL_THRESHOLD_PT,
  effectiveFillHeightPt, effectiveFillHeightPx, tightMergedTextBindings,
} from '../utils';

// 三种情况复现模板（与后端 Docker parse_workbook 复现脚本同一版式）：
// 横向合并 B3:D3（默认行高）、纵向合并 B5:B7（3 行）、显式行高 45pt 的 B9
const SHEET = {
  name: '维护记录', max_row: 9, max_column: 5,
  merged_ranges: ['A1:E1', 'B3:D3', 'B5:B7'],
  row_heights: {'9': 45.0},
  column_widths: {},
  hidden_rows: [],
  hidden_columns: [],
  cells: {
    A1: {v: '维护记录'},
    B2: {v: '签名'},
    A3: {v: '横向合并格'}, A5: {v: '纵向合并格'}, A9: {v: '显式行高格'},
    B3: {s: {border: {top: {style: 'thin'}}}},
    B5: {s: {border: {top: {style: 'thin'}}}},
    B9: {s: {border: {top: {style: 'thin'}}}},
  },
};

const FIELD_H = 'cccccccc-3333-4ccc-8ccc-000000000001';
const FIELD_V = 'cccccccc-3333-4ccc-8ccc-000000000002';
const FIELD_R = 'cccccccc-3333-4ccc-8ccc-000000000003';
const FIELD_N = 'cccccccc-3333-4ccc-8ccc-000000000004';

function binding(coordinate, fieldId, inputType = 'text', extra = {}) {
  return {
    field_id: fieldId, sheet_name: '维护记录', cell_coordinate: coordinate,
    field_name: `签名-${coordinate}`, input_type: inputType,
    is_required: false, unit: '', options: [], ...extra,
  };
}

const BINDINGS = {
  [`维护记录!B3`]: binding('B3', FIELD_H),
  [`维护记录!B5`]: binding('B5', FIELD_V),
  [`维护记录!B9`]: binding('B9', FIELD_R),
};

let container = null;
let changes = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  changes = [];
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  container = null;
  changes = null;
});

async function renderFillTable(sheet, bindingByCell, values = {}) {
  await act(async () => {
    ReactDOM.render(
      <LayoutTable sheet={sheet} bindingByCell={bindingByCell} fillMode
                   values={values}
                   onValueChange={(fieldId, value) => changes.push([fieldId, value])}/>,
      container);
  });
}

const inputSetter = Object.getOwnPropertyDescriptor(
  window.HTMLTextAreaElement.prototype, 'value').set;
const textSetter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, 'value').set;

test('纵向合并多行的文本格渲染多行文本域并填满单元格（输入走 onValueChange）', async () => {
  await renderFillTable(SHEET, BINDINGS);
  const td = container.querySelector('td[data-coord="B5"]');
  expect(td.getAttribute('rowSpan')).toBe('3');
  const textarea = td.querySelector('textarea');
  expect(textarea).toBeTruthy();
  // 高度 = 3 行默认高逐行换算累计（3 × round(14.25×4/3)）- 上下内边距 4
  expect(textarea.style.height).toBe(`${Math.round(DEFAULT_ROW_HEIGHT_PT * 4 / 3) * 3 - 4}px`);
  expect(textarea.style.position).toBe('absolute');
  // 不再有单行输入框
  expect(td.querySelector('input')).toBeNull();
  // 输入姓名走真实 onChange 链路
  await act(async () => {
    inputSetter.call(textarea, '张三');
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
  });
  expect(changes).toEqual([[FIELD_V, '张三']]);
  // 回显受控值
  await renderFillTable(SHEET, BINDINGS, {[FIELD_V]: '张三'});
  expect(container.querySelector('td[data-coord="B5"] textarea').value).toBe('张三');
});

test('横向合并多列（一行默认高）的文本格仍为单行输入框', async () => {
  await renderFillTable(SHEET, BINDINGS);
  const td = container.querySelector('td[data-coord="B3"]');
  expect(td.getAttribute('colSpan')).toBe('3');
  expect(td.querySelector('textarea')).toBeNull();
  expect(td.querySelector('input')).toBeTruthy();
});

test('显式大行高的单格文本格渲染多行文本域，小行高仍单行', async () => {
  await renderFillTable(SHEET, BINDINGS);
  // B9：45pt → round(45×4/3)=60px，减内边距 4
  const textarea = container.querySelector('td[data-coord="B9"] textarea');
  expect(textarea).toBeTruthy();
  expect(textarea.style.height).toBe('56px');
  // 26pt（< 2 行默认高度 28.5pt）单行
  const small = {...SHEET, row_heights: {'9': 26}};
  await renderFillTable(small, BINDINGS);
  expect(container.querySelector('td[data-coord="B9"] textarea')).toBeNull();
  expect(container.querySelector('td[data-coord="B9"] input')).toBeTruthy();
});

test('高度足够时正常/异常与数值类型不改为文本域', async () => {
  const bindings = {
    '维护记录!B5': binding('B5', FIELD_N, 'status'),
    '维护记录!B9': binding('B9', FIELD_N, 'number'),
  };
  await renderFillTable(SHEET, bindings);
  expect(container.querySelector('td[data-coord="B5"] textarea')).toBeNull();
  expect(container.querySelector('td[data-coord="B5"] .ant-select')).toBeTruthy();
  expect(container.querySelector('td[data-coord="B9"] textarea')).toBeNull();
  expect(container.querySelector('td[data-coord="B9"] input[type="number"]')).toBeTruthy();
});

test('必填标记在多行文本域上仍渲染（绝对定位不遮盖）', async () => {
  const bindings = {
    '维护记录!B5': binding('B5', FIELD_V, 'text', {is_required: true}),
  };
  await renderFillTable(SHEET, bindings);
  const mark = container.querySelector('td[data-coord="B5"] .proto-required-mark');
  expect(mark).toBeTruthy();
  expect(mark.style.zIndex).toBe('1');
});

test('历史回放（readOnly）不渲染任何输入控件', async () => {
  await act(async () => {
    ReactDOM.render(
      <LayoutTable sheet={SHEET} bindingByCell={BINDINGS} fillMode readOnly
                   values={{[FIELD_V]: '张三'}} onValueChange={() => {}}/>,
      container);
  });
  expect(container.querySelector('textarea')).toBeNull();
  expect(container.querySelector('input[type="text"]')).toBeNull();
  expect(container.querySelector('td[data-coord="B5"]').textContent).toContain('张三');
});

test('utils 几何：跨行累计、隐藏行计 0、横向合并不算高度', () => {
  expect(DEFAULT_ROW_HEIGHT_PT).toBe(14.25);
  expect(TALL_FILL_THRESHOLD_PT).toBe(28.5);
  // 横向合并 B3：只有一行默认高
  expect(effectiveFillHeightPt(SHEET, 'B3')).toBe(14.25);
  expect(effectiveFillHeightPt(SHEET, 'D3')).toBe(14.25);
  // 纵向合并 B5：3 行默认高
  expect(effectiveFillHeightPt(SHEET, 'B5')).toBeCloseTo(42.75);
  // 显式 45pt 单格
  expect(effectiveFillHeightPt(SHEET, 'B9')).toBe(45);
  // px 逐行取整累计
  expect(effectiveFillHeightPx(SHEET, 'B5')).toBe(Math.round(14.25 * 4 / 3) * 3);
  // 隐藏行计 0
  const hidden = {...SHEET, hidden_rows: ['6']};
  expect(effectiveFillHeightPt(hidden, 'B5')).toBeCloseTo(28.5);
  // 未合并单格
  expect(effectiveFillHeightPt(SHEET, 'C4')).toBe(14.25);
});

test('utils 尺寸提示收集：只收集一行默认高的横向合并文本格', () => {
  const bindings = [
    binding('B3', FIELD_H),        // 横向合并默认高 → 收集
    binding('B5', FIELD_V),        // 纵向合并（3 行）→ 不收集
    binding('B9', FIELD_R),        // 显式 45pt → 不收集
    binding('C4', FIELD_N, 'status'), // 非文本/未合并 → 不收集
  ];
  expect(tightMergedTextBindings(SHEET, bindings)).toEqual([
    {coordinate: 'B3', field_name: '签名-B3'},
  ]);
  // B3 行显式设置 40pt 后不再提示
  const adjusted = {...SHEET, row_heights: {'3': 40}};
  expect(tightMergedTextBindings(adjusted, bindings)).toEqual([]);
});
