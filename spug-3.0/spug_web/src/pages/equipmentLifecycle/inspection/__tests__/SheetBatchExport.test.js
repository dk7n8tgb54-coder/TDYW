/**
 * 巡检单批量导出测试（按筛选条件批量导出详情，不增加手动勾选）：
 * - store 初始 f_duty_range 即默认最近 30 个自然日（含今天），页面首次渲染
 *   显示默认范围并自动执行列表查询；
 * - 批量导出 Excel/PDF 先弹日期范围选择框（默认为当前筛选范围副本），确认后
 *   请求对应端点：弹窗日期覆盖 duty_from/duty_to、保留其他筛选、无分页参数；
 * - 数量显示来自列表接口返回的 total；为 0 时批量按钮仍可打开弹窗重新选择
 *   日期范围，无数据由后端统一返回业务错误；
 * - 批量按钮按 equipment_lifecycle.inspection.export 权限显示，确认 loading 防重复；
 * - 现有单条详情 Excel/PDF 导出不受影响（不弹日期范围框）。
 * exportFile 由 libs mock 承接（下载行为由 libs/exportFile 自身测试保障）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import moment from 'moment';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHasPermission = jest.fn(() => true);
const mockExportFile = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: (code) => mockHasPermission(code),
  Permission: {isSuper: false},
  history: {},
  X_TOKEN: '',
  exportFile: (...args) => mockExportFile(...args),
}));

const storeModule = require('../store');
const store = storeModule.default;
// store 构造（模块首次加载）时的初始值班日期范围（默认最近 30 个自然日）
const INITIAL_DUTY_RANGE = store.f_duty_range.slice();

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
  mockHasPermission.mockImplementation(() => true);
  mockHttpGet.mockReset();
  mockExportFile.mockReset();
  // 恢复默认筛选（等价"页面首次打开"），用例内再按需覆盖
  store.f_duty_range = storeModule.defaultDutyRange();
  store.f_status = undefined;
  store.f_keyword = undefined;
  store.browsePage = 1;
  store.browseVisible = false;
  store.detail = null;
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  mockHasPermission.mockReset();
  mockHasPermission.mockImplementation(() => true);
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function findButton(root, label) {
  const target = label.replace(/\s+/g, '');
  return [...root.querySelectorAll('button')]
    .find(btn => btn.textContent.replace(/\s+/g, '') === target);
}

const LIST_ROWS = [
  {id: 5, sheet_no: 'XJ20260924-0001', duty_date: '2026-09-24',
    template: 7, template_name: '机房巡检模板', status: 'submitted',
    status_text: '已提交', version: 3, abnormal_count: 1,
    submitted_at: '2026-09-24 18:30', submitted_by_name: 'admin'},
];

const SHEET_DETAIL = {
  id: 5, sheet_no: 'XJ20260924-0001', duty_date: '2026-09-24',
  template: 7, template_name: '机房巡检模板', status: 'submitted',
  status_text: '已提交', version: 3, abnormal_count: 1,
  persons: [{id: 1, user: 3, user_name: 'admin', person_name: '值班员甲'}],
  records: [],
};

function mockFlow(total = 18) {
  mockHttpGet.mockImplementation((url) => {
    if (/\/inspection-sheets\/\d+\/$/.test(url)) {
      return Promise.resolve(SHEET_DETAIL);
    }
    if (url.includes('/inspection-sheets/')) {
      return Promise.resolve({data: LIST_ROWS, total});
    }
    return Promise.resolve({data: {}});
  });
}

async function renderPage() {
  const SheetIndex = require('../SheetIndex').default;
  await act(async () => {
    ReactDOM.render(<SheetIndex/>, container);
  });
  await act(flush);
  await act(flush);
}

function expectedDefaultRange() {
  return {
    duty_from: moment().subtract(29, 'days').format('YYYY-MM-DD'),
    duty_to: moment().format('YYYY-MM-DD'),
  };
}

describe('巡检单批量导出：默认日期范围', () => {
  it('defaultDutyRange 返回最近 30 个自然日（今天往前 29 天 → 今天）', () => {
    const range = storeModule.defaultDutyRange();
    expect(range).toHaveLength(2);
    expect(range[0].format('YYYY-MM-DD'))
      .toBe(moment().subtract(29, 'days').format('YYYY-MM-DD'));
    expect(range[1].format('YYYY-MM-DD')).toBe(moment().format('YYYY-MM-DD'));
    // 自然日边界：相差 29 天，而非 30×24 小时截断
    expect(range[1].diff(range[0], 'days')).toBe(29);
  });

  it('store 初始值班日期范围即默认最近 30 个自然日', () => {
    expect(INITIAL_DUTY_RANGE).toHaveLength(2);
    expect(INITIAL_DUTY_RANGE.map(m => m.format('YYYY-MM-DD'))).toEqual([
      moment().subtract(29, 'days').format('YYYY-MM-DD'),
      moment().format('YYYY-MM-DD'),
    ]);
  });

  it('页面首次渲染默认显示最近 30 天并自动执行列表查询', async () => {
    mockFlow();
    await renderPage();
    const expected = expectedDefaultRange();
    // 首次列表查询携带默认日期范围（真实参与查询）
    const listCalls = mockHttpGet.mock.calls.filter(
      call => call[0].endsWith('/inspection-sheets/'));
    expect(listCalls).toHaveLength(1);
    expect(listCalls[0][1].params.duty_from).toBe(expected.duty_from);
    expect(listCalls[0][1].params.duty_to).toBe(expected.duty_to);
    // 日期控件显示默认范围（antd 4 RangePicker DOM：.ant-picker-input）
    const pickerValues = [...document.querySelectorAll('.ant-picker-input input')]
      .map(input => input.value);
    expect(pickerValues).toEqual([expected.duty_from, expected.duty_to]);
  });
});

describe('巡检单批量导出：请求契约', () => {
  it('批量导出先弹日期范围弹窗，确认后按当前筛选条件调用正确 URL 且不含分页参数', async () => {
    mockFlow();
    await renderPage();
    const momentLocal = moment;
    store.f_duty_range = [momentLocal('2026-09-01'), momentLocal('2026-09-15')];
    store.f_status = 'submitted';
    store.f_keyword = 'XJ20260924';
    mockExportFile.mockResolvedValue(undefined);

    await act(async () => {
      findButton(container, '批量导出 Excel（共 18 条）').click();
    });
    await act(flush);
    await act(flush);
    // 只打开弹窗，尚未发起导出
    expect(mockExportFile).not.toHaveBeenCalled();
    expect(document.body.querySelector('.ant-modal')).not.toBeNull();
    // 弹窗按当前筛选 + 弹窗日期统计可导出条数（page_size=1 只取 total）
    const countCalls = mockHttpGet.mock.calls.filter(
      call => call[0].endsWith('/inspection-sheets/') && call[1] && call[1].params
        && call[1].params.page_size === 1);
    expect(countCalls).toHaveLength(1);
    expect(countCalls[0][1].params).toEqual({
      duty_from: '2026-09-01',
      duty_to: '2026-09-15',
      status: 'submitted',
      keyword: 'XJ20260924',
      page: 1,
      page_size: 1,
    });
    expect(document.body.querySelector('.ant-modal').textContent)
      .toContain('共可导出 18 条巡检单记录');

    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const xlsxOptions = mockExportFile.mock.calls[0][0];
    expect(xlsxOptions.url)
      .toBe('/api/equipment-lifecycle/inspection-sheets/batch-export/xlsx/');
    expect(xlsxOptions.params).toEqual({
      duty_from: '2026-09-01',
      duty_to: '2026-09-15',
      status: 'submitted',
      keyword: 'XJ20260924',
    });
    expect(xlsxOptions.params).not.toHaveProperty('page');
    expect(xlsxOptions.params).not.toHaveProperty('page_size');

    // PDF：再次打开弹窗（默认仍取当前筛选副本）确认后走 PDF 端点
    await act(async () => {
      findButton(container, '批量导出 PDF（共 18 条）').click();
    });
    await act(flush);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(2);
    expect(mockExportFile.mock.calls[1][0].url)
      .toBe('/api/equipment-lifecycle/inspection-sheets/batch-export/pdf/');
    expect(mockExportFile.mock.calls[1][0].params).toEqual(xlsxOptions.params);

    // 弹窗确认不修改列表筛选条件
    expect(store.f_duty_range.map(m => m.format('YYYY-MM-DD')))
      .toEqual(['2026-09-01', '2026-09-15']);
  });

  it('默认 30 天范围内批量导出携带默认日期，筛选变化后使用最新筛选', async () => {
    mockFlow();
    await renderPage();
    mockExportFile.mockResolvedValue(undefined);

    await act(async () => {
      findButton(container, '批量导出 Excel（共 18 条）').click();
    });
    await act(flush);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(mockExportFile.mock.calls[0][0].params).toEqual(expectedDefaultRange());

    // 筛选条件变化后，批量导出使用最新筛选
    store.f_status = 'draft';
    await act(async () => {
      findButton(container, '批量导出 Excel（共 18 条）').click();
    });
    await act(flush);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(mockExportFile.mock.calls[1][0].params).toEqual({
      ...expectedDefaultRange(),
      status: 'draft',
    });
  });
});

describe('巡检单批量导出：权限与按钮状态', () => {
  it('两个批量导出按钮按 export 权限显示', async () => {
    mockFlow();
    mockHasPermission.mockImplementation(
      code => code !== 'equipment_lifecycle.inspection.export');
    await renderPage();
    expect(findButton(container, '批量导出 Excel（共 18 条）')).toBeUndefined();
    expect(findButton(container, '批量导出 PDF（共 18 条）')).toBeUndefined();

    ReactDOM.unmountComponentAtNode(container);
    mockHasPermission.mockImplementation(() => true);
    await renderPage();
    expect(findButton(container, '批量导出 Excel（共 18 条）')).toBeDefined();
    expect(findButton(container, '批量导出 PDF（共 18 条）')).toBeDefined();
  });

  it('数量显示使用列表接口返回的 total；为 0 时批量按钮仍可打开日期弹窗重新选择范围', async () => {
    mockFlow(18);
    await renderPage();
    expect(document.body.textContent).toContain('共 18 条');
    expect(findButton(container, '批量导出 Excel（共 18 条）').disabled).toBe(false);

    ReactDOM.unmountComponentAtNode(container);
    mockHttpGet.mockReset();
    mockFlow(0);
    await renderPage();
    const button = findButton(container, '批量导出 Excel（共 0 条）');
    // 当前列表为空仍允许打开弹窗选择新日期范围，无数据由后端统一返回业务错误
    expect(button.disabled).toBe(false);
    mockExportFile.mockResolvedValue(undefined);
    await act(async () => {
      button.click();
    });
    await act(flush);
    expect(document.body.querySelector('.ant-modal')).not.toBeNull();
    // 统计为 0 时弹窗内明确提示无数据（确认后由后端统一返回业务错误）
    await act(flush);
    expect(document.body.querySelector('.ant-modal').textContent)
      .toContain('没有可导出的数据');
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    expect(mockExportFile.mock.calls[0][0].params).toEqual(expectedDefaultRange());
  });

  it('批量导出 loading 期间不能重复触发，完成后恢复', async () => {
    mockFlow();
    await renderPage();
    mockExportFile.mockImplementation(() => new Promise(() => {}));

    await act(async () => {
      findButton(container, '批量导出 Excel（共 18 条）').click();
    });
    await act(flush);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const okButton = findButton(document.body, '确认');
    expect(okButton.disabled || okButton.className.includes('ant-btn-loading'))
      .toBe(true);
    await act(async () => {
      okButton.click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(1);
  });

  it('现有单条详情 Excel/PDF 导出不受批量导出影响（不弹日期范围框）', async () => {
    mockFlow();
    await renderPage();

    await act(async () => {
      findButton(container, '详情').click();
    });
    await act(flush);
    await act(flush);

    const drawer = document.body.querySelector('.ant-drawer');
    expect(drawer).not.toBeNull();
    mockExportFile.mockClear();
    mockExportFile.mockResolvedValue(undefined);

    await act(async () => {
      findButton(drawer, '导出 Excel').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    expect(mockExportFile.mock.calls[0][0].url)
      .toBe('/api/equipment-lifecycle/inspection-sheets/5/export/xlsx/');

    await act(async () => {
      findButton(drawer, '导出 PDF').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(2);
    expect(mockExportFile.mock.calls[1][0].url)
      .toBe('/api/equipment-lifecycle/inspection-sheets/5/export/pdf/');
    // 单条导出保持直接下载，未出现日期范围弹窗
    expect(document.body.querySelector('.ant-modal')).toBeNull();
  });
});
