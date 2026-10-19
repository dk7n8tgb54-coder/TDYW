/**
 * Excel 台账填写导航测试（2026-10-19，真实 store 计算 + 真实组件渲染）。
 *
 * 覆盖：
 * - 进度口径同源：fillProgress / missingRequiredBindings 与 requiredMissing()
 *   一致——导航显示完成 ⇔ 提交必填预检不提示缺项（后端完成校验
 *   is_required + not values.get(field_id)，填写值均为字符串）；
 * - bindingsBySheet 按布局工作表顺序分组、只含有绑定的工作表；
 * - setSheet 切换工作表，applyDetail 切换详情回落主工作表；
 * - 导航渲染：进度文本、字段三态（已填/未填必填/未填选填）、按工作表
 *   分组顺序、点击字段触发定位回调、下一个未填必填项循环与禁用、
 *   收起回调、未绑定字段空态。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  exportFile: jest.fn(),
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
const FillNavigator = require('../components/FillNavigator').default;
const {
  FIELD_NAME, FIELD_STATUS, FIELD_CONTENT, FIELD_SIGN, makeDetail,
} = require('../testing/fillFixtures');

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

function makeStore(detailOverrides) {
  const store = new ExcelLedgerStore();
  store.applyDetail(makeDetail(detailOverrides));
  return store;
}

async function renderNavigator(store, located, onCollapse = () => {}) {
  await act(async () => {
    ReactDOM.render(
      <FillNavigator store={store}
                     onLocate={binding => located.push(binding)}
                     onCollapse={onCollapse}/>,
      container);
  });
}

test('进度与必填校验同源：计数与缺失清单一致，随填写值即时更新', () => {
  const store = makeStore();
  expect(store.fillProgress).toEqual(
    {total: 4, filled: 0, requiredTotal: 3, requiredFilled: 0});
  expect(store.missingRequiredBindings.map(b => b.field_name))
    .toEqual(['设备名称', '巡检结论', '签名']);
  expect(store.requiredMissing()).toEqual(['设备名称', '巡检结论', '签名']);
  act(() => {
    store.setValue(FIELD_NAME, '设备A');
    store.setValue(FIELD_SIGN, '李四');
  });
  expect(store.fillProgress).toEqual(
    {total: 4, filled: 2, requiredTotal: 3, requiredFilled: 2});
  expect(store.requiredMissing()).toEqual(['巡检结论']);
  // 选填计入已填总数、不计入必填
  act(() => { store.setValue(FIELD_CONTENT, '清洗滤网'); });
  expect(store.fillProgress.filled).toBe(3);
  expect(store.fillProgress.requiredFilled).toBe(2);
  expect(store.missingRequiredBindings.map(b => b.field_name)).toEqual(['巡检结论']);
});

test('bindingsBySheet 按布局工作表顺序分组且只含有绑定的工作表', () => {
  const store = makeStore();
  const groups = store.bindingsBySheet;
  expect(groups.map(g => g.name)).toEqual(['维护记录', '签名页']);
  expect(groups[0].bindings).toHaveLength(3);
  expect(groups[1].bindings.map(b => b.field_name)).toEqual(['签名']);
  // 清空绑定后无分组
  const emptyStore = makeStore({excel: {version: {bindings: []}}});
  expect(emptyStore.bindingsBySheet).toEqual([]);
});

test('setSheet 切换工作表；applyDetail 切换详情回落主工作表', () => {
  const store = makeStore();
  expect(store.activeSheet).toBe('维护记录');
  act(() => { store.setSheet('签名页'); });
  expect(store.activeSheet).toBe('签名页');
  expect(store.currentSheet.name).toBe('签名页');
  // 切换不触碰填写值（未保存输入不丢失的前提）
  act(() => { store.setValue(FIELD_NAME, '设备A'); });
  act(() => { store.applyDetail(makeDetail()); });
  expect(store.activeSheet).toBe('维护记录');
  expect(store.values[FIELD_NAME]).toBeUndefined();
});

test('导航渲染进度文本、字段三态与分组顺序，点击字段触发定位回调', async () => {
  const store = makeStore();
  act(() => { store.setValue(FIELD_NAME, '设备A'); });
  const located = [];
  await renderNavigator(store, located);
  expect(container.querySelector('[data-testid="fill-nav-progress-text"]').textContent)
    .toBe('已填 1/4 · 必填 1/3');
  const rows = [...container.querySelectorAll('[data-testid="fill-nav-field"]')];
  expect(rows).toHaveLength(4);
  expect(rows[0].textContent).toContain('设备名称');
  expect(rows[0].className).toContain('el-fill-nav-field-filled');
  expect(rows[1].className).toContain('el-fill-nav-field-missing');
  expect(rows[2].className).not.toContain('el-fill-nav-field-missing');
  expect(rows[3].className).toContain('el-fill-nav-field-missing');
  const sheetNames = [...container.querySelectorAll('.el-fill-nav-sheet-name')]
    .map(el => el.textContent);
  expect(sheetNames).toEqual(['维护记录', '签名页']);
  // 点击签名行 → 定位回调携带跨工作表绑定
  await act(async () => {
    rows[3].dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  expect(located).toHaveLength(1);
  expect(located[0].field_id).toBe(FIELD_SIGN);
  expect(located[0].sheet_name).toBe('签名页');
});

test('下一个未填必填项：从上次定位项下一项循环，全部填完后禁用', async () => {
  const store = makeStore();
  const located = [];
  await renderNavigator(store, located);
  const button = container.querySelector('[data-testid="fill-nav-next-required"]');
  expect(button.disabled).toBe(false);
  // 三次点击循环覆盖三个缺失必填项（首个 → 巡检结论 → 签名，尾后回卷）
  await act(async () => { button.click(); });
  await act(async () => { button.click(); });
  await act(async () => { button.click(); });
  expect(located.map(b => b.field_id))
    .toEqual([FIELD_NAME, FIELD_STATUS, FIELD_SIGN]);
  // 全部必填填完后禁用
  act(() => {
    store.setValue(FIELD_NAME, '设备A');
    store.setValue(FIELD_STATUS, '正常');
    store.setValue(FIELD_SIGN, '李四');
  });
  expect(container.querySelector('[data-testid="fill-nav-next-required"]').disabled)
    .toBe(true);
});

test('收起回调与未绑定字段空态', async () => {
  const store = makeStore();
  let collapsed = false;
  await renderNavigator(store, [], () => { collapsed = true; });
  await act(async () => {
    container.querySelector('[data-testid="fill-nav-collapse"]').click();
  });
  expect(collapsed).toBe(true);
  ReactDOM.unmountComponentAtNode(container);
  const emptyStore = makeStore({excel: {version: {bindings: []}}});
  await act(async () => {
    ReactDOM.render(
      <FillNavigator store={emptyStore} onLocate={() => {}} onCollapse={() => {}}/>,
      container);
  });
  expect(container.querySelector('.el-fill-nav-empty').textContent)
    .toContain('该模板未绑定填写字段');
  expect(container.querySelectorAll('[data-testid="fill-nav-field"]')).toHaveLength(0);
});
