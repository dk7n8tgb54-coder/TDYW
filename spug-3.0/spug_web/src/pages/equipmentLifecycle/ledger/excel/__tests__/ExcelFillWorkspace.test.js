/**
 * Excel 台账填写工作区测试（2026-10-19，真实组件渲染 + 真实 store）。
 *
 * 覆盖（真实代码路径，jsdom 行为断言）：
 * - 多工作表：Tabs 切换工作表、跨表字段（签名页）可填写、切换与显示
 *   模式变化不丢未保存输入（值存 store 按 field_id）；
 * - 字段定位：导航点击跨工作表字段 → 切换 + scrollIntoView + 短暂高亮
 *   + 聚焦格内输入控件；合并格定位到实际填写锚点（B2:D2 → colspan=3）；
 * - 显示模式：适合页宽按可用宽度/自然宽度等比缩放列宽行高，原始尺寸
 *   恢复 100%（缩放只乘在布局像素上）；
 * - 纸张边界：版本 pdf_params（A4 纵向含页边距）→ 纸张卡片 + 说明；
 *   无打印设置的工作表退化为普通卡片；版本无 pdf_params 回退布局 meta
 *   页面设置；宽度超出可打印区域给出横向分页提示；
 * - 显示与数据解耦：切换显示模式/工作表不修改版本快照（layout/bindings
 *   JSON 不变），导出仍走既有端点（导出版式不受显示模式影响）；
 * - 导航可收起与展开。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockExportFile = jest.fn();
jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
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
const FillWorkspace = require('../components/FillWorkspace').default;
const {
  defaultDisplayMode, fitPageWidthScale,
} = require('../utils');
const {FIELD_NAME, FIELD_SIGN, makeDetail} = require('../testing/fillFixtures');

const scrollIntoViewMock = jest.fn();
const originalScrollIntoView = Element.prototype.scrollIntoView;

beforeAll(() => {
  Element.prototype.scrollIntoView = scrollIntoViewMock;
});

afterAll(() => {
  Element.prototype.scrollIntoView = originalScrollIntoView;
});

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  scrollIntoViewMock.mockClear();
  mockExportFile.mockReset();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  container = null;
});

function makeStore(detailOverrides) {
  const store = new ExcelLedgerStore();
  store.applyDetail(makeDetail(detailOverrides));
  return store;
}

async function renderWorkspace(store, readOnly = false) {
  await act(async () => {
    ReactDOM.render(<FillWorkspace store={store} readOnly={readOnly}/>, container);
  });
}

const textSetter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, 'value').set;

function typeInput(input, value) {
  textSetter.call(input, value);
  input.dispatchEvent(new Event('input', {bubbles: true}));
}

function clickRadio(root, label) {
  const target = [...root.querySelectorAll('.ant-radio-button-wrapper')]
    .find(el => el.textContent.includes(label));
  target.querySelector('input').click();
}

function clickSheetTab(index) {
  return container.querySelectorAll('.ant-tabs-tab')[index].click();
}

test('多工作表 Tabs 切换，切换后跨表字段可填写', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  expect(container.querySelector('[data-testid="fill-sheet-tabs"]')).toBeTruthy();
  expect(store.activeSheet).toBe('维护记录');
  // 切到签名页（旧版填写页不可见的跨表字段回归点）
  await act(async () => { clickSheetTab(1); });
  expect(store.activeSheet).toBe('签名页');
  const signInput = container.querySelector('td[data-coord="B2"] input');
  await act(async () => { typeInput(signInput, '李四'); });
  expect(store.values[FIELD_SIGN]).toBe('李四');
  // 切回主表
  await act(async () => { clickSheetTab(0); });
  expect(container.querySelector('td[data-coord="B3"] .ant-select')).toBeTruthy();
});

test('切换工作表与显示模式不丢未保存输入', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  await act(async () => {
    typeInput(container.querySelector('td[data-coord="B2"] input'), '设备A');
  });
  await act(async () => { clickRadio(container, '适合页宽'); });
  expect(container.querySelector('td[data-coord="B2"] input').value).toBe('设备A');
  await act(async () => { clickSheetTab(1); });
  await act(async () => { clickSheetTab(0); });
  expect(container.querySelector('td[data-coord="B2"] input').value).toBe('设备A');
  expect(store.hasUnsaved).toBe(true);
});

test('导航定位跨工作表字段：切换 + 滚动 + 高亮 + 聚焦输入控件', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  const signRow = [...container.querySelectorAll('[data-testid="fill-nav-field"]')]
    .find(el => el.textContent.includes('签名'));
  await act(async () => {
    signRow.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  expect(store.activeSheet).toBe('签名页');
  const td = container.querySelector('td[data-coord="B2"]');
  expect(td).toBeTruthy();
  expect(scrollIntoViewMock).toHaveBeenCalled();
  expect(td.className).toContain('proto-cell-locate');
  expect(document.activeElement).toBe(td.querySelector('input'));
});

test('合并格定位到实际填写锚点（B2:D2 的锚点即输入控件所在格）', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  const nameRow = [...container.querySelectorAll('[data-testid="fill-nav-field"]')]
    .find(el => el.textContent.includes('设备名称'));
  await act(async () => {
    nameRow.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  expect(store.activeSheet).toBe('维护记录');
  const td = container.querySelector('td[data-coord="B2"]');
  expect(td.getAttribute('colspan')).toBe('3');
  expect(td.querySelector('input')).toBeTruthy();
  expect(scrollIntoViewMock).toHaveBeenCalled();
  expect(td.className).toContain('proto-cell-locate');
});

test('适合页宽用 transform 等比缩放，布局像素保持不变（2026-10-21 统一打印布局）', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  const table = container.querySelector('table.proto-table');
  const area = container.querySelector('[data-testid="fill-sheet-area"]');
  Object.defineProperty(table, 'offsetWidth', {value: 1200, configurable: true});
  Object.defineProperty(table, 'offsetHeight', {value: 200, configurable: true});
  Object.defineProperty(area, 'clientWidth', {value: 1248, configurable: true});
  await act(async () => { clickRadio(container, '适合页宽'); });
  // 内容宽度 = max(纸张页宽 794, 左边距 67 + 表格 1200 + 右边距 67
  // + 卡片边框 2) = 1336，缩放 = 可用宽 1200 / 1336，只作用于外层
  // transform——列宽行高等布局像素不乘缩放，文字/边框/内边距随
  // transform 同步等比（换行与分页位置不随倍率变化）
  const viewport = container.querySelector('.el-fill-zoom-viewport');
  const sizer = container.querySelector('[data-testid="fill-zoom-sizer"]');
  expect(parseFloat(viewport.style.transform.replace('scale(', '')))
    .toBeCloseTo(1200 / 1336, 5);
  expect(sizer.style.width).toBe(`${Math.round(1336 * (1200 / 1336))}px`);
  expect(container.querySelector('col').style.width).toBe('93px');
  expect(container.querySelector('tbody tr').style.height).toBe('19px');
  await act(async () => { clickRadio(container, '原始尺寸'); });
  expect(container.querySelector('.el-fill-zoom-viewport').style.transform)
    .toBe('scale(1)');
  expect(container.querySelector('col').style.width).toBe('93px');
  expect(container.querySelector('tbody tr').style.height).toBe('19px');
});

test('纸张边界：A4 纵向卡片整页高度含下边距，说明与参考框（模板打印参数跨工作表保持）', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  expect(container.querySelector('[data-testid="fill-paper-caption"]').textContent)
    .toBe('纸张：A4 · 纵向');
  const paper = container.querySelector('[data-testid="fill-paper"]');
  expect(paper.style.width).toBe('794px');   // 210mm @96dpi
  expect(paper.style.height).toBe('1123px'); // 297mm 整页（含上下边距，2026-10-21）
  expect(paper.style.paddingBottom).toBe('72px'); // 下边距 1.91cm → 72px
  expect(paper.className).not.toContain('el-fill-paper-plain');
  // 每页一张打印范围参考框（四边缩进页边距；仅网页辅助）
  const rect = container.querySelector('.el-fill-print-rect');
  expect(rect).toBeTruthy();
  expect(rect.style.top).toBe('72px');
  // 模板级打印参数作用于整个工作簿：切到其它工作表纸张说明保持
  await act(async () => { clickSheetTab(1); });
  expect(container.querySelector('[data-testid="fill-paper-caption"]').textContent)
    .toBe('纸张：A4 · 纵向');
  expect(container.querySelector('[data-testid="fill-paper"]').className)
    .not.toContain('el-fill-paper-plain');
});

test('统一打印计划：分页参考线按计划换算像素，页数进纸张说明', async () => {
  const plan = {
    plan_version: 1,
    paper: {name: 'A4', width_mm: 210, height_mm: 297, orientation: 'portrait'},
    margins_mm: {top: 19.1, bottom: 19.1, left: 17.8, right: 17.8},
    scale: 1, page_count: 2, warnings: [],
    sheets: {
      '维护记录': {
        scale: 1, page_count: 2, print_row_start: 1, print_row_end: 6,
        print_col_start: 1, print_col_end: 6,
        row_breaks: [4], col_breaks: [], pages: [],
      },
    },
  };
  const store = makeStore({excel: {version: {print_plan: plan}}});
  await renderWorkspace(store);
  expect(container.querySelector('[data-testid="fill-paper-caption"]').textContent)
    .toBe('纸张：A4 · 纵向 · 共 2 页');
  // 分页行 4 的参考线：上方 3 行默认行高 19px × 3 = 57px，加页面上边距 72px
  const guide = container.querySelector('[data-testid="fill-page-guide"]');
  expect(guide).toBeTruthy();
  expect(guide.style.top).toBe('129px');
  expect(guide.textContent).toContain('第 2 页');
});

test('版本无打印参数时回退布局 meta 页面设置：按工作表差异退化', async () => {
  const store = makeStore({excel: {version: {pdf_params: {}}}});
  await renderWorkspace(store);
  // 主表 print 记录 A4 纵向 → 显示纸张卡片
  expect(container.querySelector('[data-testid="fill-paper-caption"]').textContent)
    .toBe('纸张：A4 · 纵向');
  // 签名页无打印设置 → 无纸张信息，退化为普通白底卡片
  await act(async () => { clickSheetTab(1); });
  expect(container.querySelector('[data-testid="fill-paper-caption"]')).toBeNull();
  expect(container.querySelector('[data-testid="fill-paper"]').className)
    .toContain('el-fill-paper-plain');
});

test('表格宽度超出可打印区域时给出横向分页提示', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  const table = container.querySelector('table.proto-table');
  Object.defineProperty(table, 'offsetWidth', {value: 2400, configurable: true});
  // 切换工作表触发工作区重渲染（纸张说明按表格自然宽度重算；
  // 自然宽度与填写值无关，同名工作表切换为 MobX 同值不重渲染）
  await act(async () => { store.setSheet('签名页'); });
  expect(container.querySelector('[data-testid="fill-paper-caption"]').textContent)
    .toContain('横向分页');
});

test('显示模式/工作表切换不修改版本快照，导出仍走既有端点', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  const layoutBefore = JSON.stringify(store.version.layout);
  const bindingsBefore = JSON.stringify(store.version.bindings);
  await act(async () => { clickRadio(container, '适合页宽'); });
  await act(async () => { clickSheetTab(1); });
  await act(async () => { store.setSheet('维护记录'); });
  expect(JSON.stringify(store.version.layout)).toBe(layoutBefore);
  expect(JSON.stringify(store.version.bindings)).toBe(bindingsBefore);
  await act(async () => { store.exportExcel(); });
  expect(mockExportFile).toHaveBeenCalledWith(expect.objectContaining({
    url: '/api/equipment-lifecycle/excel-ledgers/71/export/excel/',
    method: 'post',
  }));
});

test('导航可收起与展开', async () => {
  const store = makeStore();
  await renderWorkspace(store);
  expect(container.querySelector('[data-testid="fill-navigator"]')).toBeTruthy();
  await act(async () => {
    container.querySelector('[data-testid="fill-nav-collapse"]').click();
  });
  expect(container.querySelector('[data-testid="fill-navigator"]')).toBeNull();
  expect(container.querySelector('[data-testid="fill-nav-expand"]')).toBeTruthy();
  await act(async () => {
    container.querySelector('[data-testid="fill-nav-expand"]').click();
  });
  expect(container.querySelector('[data-testid="fill-navigator"]')).toBeTruthy();
});

test('显示模式纯函数：宽表默认适合页宽，缩放夹取上下限', () => {
  expect(defaultDisplayMode(1200, 1000)).toBe('fit_width');
  expect(defaultDisplayMode(900, 1000)).toBe('original');
  expect(defaultDisplayMode(0, 1000)).toBe('original');
  expect(defaultDisplayMode(900, 0)).toBe('original');
  expect(fitPageWidthScale(1200, 1000)).toBeCloseTo(1000 / 1200, 10);
  expect(fitPageWidthScale(400, 1000)).toBe(2.5);
  expect(fitPageWidthScale(3000, 1000)).toBe(0.4);
  expect(fitPageWidthScale(0, 1000)).toBe(1);
});
