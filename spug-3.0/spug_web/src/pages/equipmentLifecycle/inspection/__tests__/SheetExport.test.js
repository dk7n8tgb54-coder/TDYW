/**
 * 巡检单导出测试（列表导出日期范围弹窗 + 详情抽屉 Excel/PDF 直接导出）：
 * - 列表导出按钮先弹日期范围选择框（默认为当前筛选范围副本/最近 30 个自然日），
 *   确认后才经 exportFile 下载；取消或校验失败不发起请求、不改列表筛选；
 * - 导出参数保留 status/keyword 等当前筛选、弹窗日期覆盖 duty_from/duty_to、
 *   不含分页参数，权限仍按 equipment_lifecycle.inspection.export 控制且
 *   导出进行中防重复提交、失败后状态恢复；
 * - 详情抽屉单条 Excel/PDF 保持直接下载，不弹日期范围框。
 * exportFile 由 libs mock 承接（下载行为本身由 libs/exportFile 自身测试保障）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
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

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;
let pageRef = null;   // SheetIndex 类实例引用（驱动弹窗日期变更的真实处理函数）

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  pageRef = null;
  mockHasPermission.mockImplementation(() => true);
  // 重置单例 store 的筛选与详情状态，避免用例间串扰
  const store = require('../store').default;
  store.f_duty_range = [];
  store.f_status = undefined;
  store.f_keyword = undefined;
  store.browsePage = 1;
  store.browseVisible = false;
  store.detail = null;
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  mockHttpGet.mockReset();
  mockExportFile.mockReset();
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

function mockFlow() {
  mockHttpGet.mockImplementation((url) => {
    if (/\/inspection-sheets\/\d+\/$/.test(url)) {
      return Promise.resolve(SHEET_DETAIL);
    }
    if (url.includes('/inspection-sheets/')) {
      return Promise.resolve({data: LIST_ROWS, total: 1});
    }
    return Promise.resolve({data: {}});
  });
}

async function renderPage() {
  const SheetIndex = require('../SheetIndex').default;
  await act(async () => {
    ReactDOM.render(<SheetIndex ref={r => {pageRef = r;}}/>, container);
  });
  await act(flush);
  await act(flush);
}

function modalHidden() {
  const wrap = document.body.querySelector('.ant-modal-wrap');
  return !wrap || wrap.style.display === 'none';
}

describe('巡检单导出：权限与日期弹窗打开', () => {
  it('无 export 权限时列表导出按钮不渲染（弹窗入口不可见），有权限时渲染', async () => {
    mockFlow();
    mockHasPermission.mockImplementation(
      code => code !== 'equipment_lifecycle.inspection.export');
    await renderPage();
    expect(findButton(container, '导出 Excel')).toBeUndefined();

    ReactDOM.unmountComponentAtNode(container);
    mockHasPermission.mockImplementation(() => true);
    await renderPage();
    expect(findButton(container, '导出 Excel')).toBeDefined();
  });

  it('点击列表导出 Excel 按钮只打开日期弹窗，不调用 exportFile', async () => {
    mockFlow();
    await renderPage();
    mockExportFile.mockResolvedValue(undefined);

    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);

    expect(mockExportFile).not.toHaveBeenCalled();
    const modal = document.body.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('选择导出日期范围');
  });

  it('弹窗默认值为当前筛选范围副本；筛选为空时回退最近 30 个自然日', async () => {
    mockFlow();
    const moment = require('moment');
    const store = require('../store').default;
    store.f_duty_range = [moment('2026-09-01'), moment('2026-09-30')];
    await renderPage();

    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);
    const readModalPicker = () => [...document.body.querySelector('.ant-modal')
      .querySelectorAll('.ant-picker-input input')].map(input => input.value);
    expect(readModalPicker()).toEqual(['2026-09-01', '2026-09-30']);

    // 筛选范围被清空后，弹窗默认回退最近 30 个自然日（含今天）
    store.f_duty_range = [];
    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);
    expect(readModalPicker()).toEqual([
      moment().subtract(29, 'days').format('YYYY-MM-DD'),
      moment().format('YYYY-MM-DD'),
    ]);
  });
  it('打开弹窗按所选日期范围统计可导出条数，日期变更后重新统计', async () => {
    // 列表 mock 按起始日期返回不同 total，区分首次统计与变更后统计
    mockHttpGet.mockImplementation((url, config) => {
      if (/\/inspection-sheets\/\d+\/$/.test(url)) {
        return Promise.resolve(SHEET_DETAIL);
      }
      if (url.includes('/inspection-sheets/')) {
        const params = (config && config.params) || {};
        return Promise.resolve(
          {data: LIST_ROWS, total: params.duty_from === '2026-10-01' ? 7 : 1});
      }
      return Promise.resolve({data: {}});
    });
    const moment = require('moment');
    const store = require('../store').default;
    store.f_duty_range = [moment('2026-09-01'), moment('2026-09-30')];
    await renderPage();

    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);
    await act(flush);

    // 统计请求：弹窗日期 + page_size=1 只取 total，不修改列表筛选
    const countCalls = mockHttpGet.mock.calls.filter(
      call => call[0].endsWith('/inspection-sheets/') && call[1] && call[1].params
        && call[1].params.page_size === 1);
    expect(countCalls).toHaveLength(1);
    expect(countCalls[0][1].params).toEqual({
      duty_from: '2026-09-01',
      duty_to: '2026-09-30',
      page: 1,
      page_size: 1,
    });
    expect(document.body.querySelector('.ant-modal').textContent)
      .toContain('共可导出 1 条巡检单记录');

    // 弹窗内变更日期后按新范围重新统计
    await act(async () => {
      pageRef.handleExportRangeChange([moment('2026-10-01'), moment('2026-10-31')]);
    });
    await act(flush);
    await act(flush);
    const countCalls2 = mockHttpGet.mock.calls.filter(
      call => call[0].endsWith('/inspection-sheets/') && call[1] && call[1].params
        && call[1].params.page_size === 1);
    expect(countCalls2).toHaveLength(2);
    expect(countCalls2[1][1].params.duty_from).toBe('2026-10-01');
    expect(countCalls2[1][1].params.duty_to).toBe('2026-10-31');
    expect(document.body.querySelector('.ant-modal').textContent)
      .toContain('共可导出 7 条巡检单记录');
  });
});

describe('巡检单导出：确认导出与状态控制', () => {
  it('取消不触发下载且列表筛选条件不变', async () => {
    mockFlow();
    const moment = require('moment');
    const store = require('../store').default;
    store.f_duty_range = [moment('2026-09-01'), moment('2026-09-30')];
    store.f_status = 'submitted';
    await renderPage();

    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);
    await act(async () => {
      findButton(document.body, '取消').click();
    });
    await act(flush);

    expect(mockExportFile).not.toHaveBeenCalled();
    expect(store.f_duty_range.map(m => m.format('YYYY-MM-DD')))
      .toEqual(['2026-09-01', '2026-09-30']);
    expect(store.f_status).toBe('submitted');
    expect(modalHidden()).toBe(true);
  });

  it('确认后按弹窗日期调用导出接口，保留 status/keyword 且不含分页参数', async () => {
    mockFlow();
    const moment = require('moment');
    const store = require('../store').default;
    store.f_duty_range = [moment('2026-09-01'), moment('2026-09-30')];
    store.f_status = 'submitted';
    store.f_keyword = 'XJ20260924';
    await renderPage();
    mockExportFile.mockResolvedValue(undefined);

    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);

    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const options = mockExportFile.mock.calls[0][0];
    expect(options.url).toBe('/api/equipment-lifecycle/inspection-sheets/export/');
    expect(options.params).toEqual({
      duty_from: '2026-09-01',
      duty_to: '2026-09-30',
      status: 'submitted',
      keyword: 'XJ20260924',
    });
    expect(options.params).not.toHaveProperty('page');
    expect(options.params).not.toHaveProperty('page_size');
  });
});

describe('巡检单导出：防重复与失败恢复', () => {
  it('导出进行中确认按钮 loading、重复确认/取消不生效，请求结束后关闭弹窗', async () => {
    mockFlow();
    await renderPage();
    let resolveExport;
    mockExportFile.mockImplementation(
      () => new Promise(resolve => {resolveExport = resolve;}));

    await act(async () => {
      findButton(container, '导出 Excel').click();
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
    // loading 期间重复确认不再触发请求，取消也不关闭弹窗（防重复提交）
    await act(async () => {
      okButton.click();
      findButton(document.body, '取消').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    expect(modalHidden()).toBe(false);

    await act(async () => {
      resolveExport();
    });
    await act(flush);
    await act(flush);
    expect(modalHidden()).toBe(true);
  });

  it('导出失败后不崩溃且状态恢复可再次导出（错误提示由拦截器负责）', async () => {
    mockFlow();
    await renderPage();
    mockExportFile.mockRejectedValue(new Error('export failed'));

    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    await act(flush);

    expect(mockExportFile).toHaveBeenCalledTimes(1);
    // 失败后状态恢复：可重新打开弹窗再次导出
    mockExportFile.mockResolvedValue(undefined);
    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(2);
    expect(document.body.textContent).toContain('XJ20260924-0001');
  });
});

describe('巡检单导出：详情抽屉单条导出', () => {
  it('详情抽屉导出 Excel/PDF 请求对应单据的导出端点，不弹日期范围框', async () => {
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
    expect(mockExportFile.mock.calls[0][0].defaultFilename)
      .toBe('巡检单_XJ20260924-0001.xlsx');

    await act(async () => {
      findButton(drawer, '导出 PDF').click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(2);
    expect(mockExportFile.mock.calls[1][0].url)
      .toBe('/api/equipment-lifecycle/inspection-sheets/5/export/pdf/');
    expect(mockExportFile.mock.calls[1][0].defaultFilename)
      .toBe('巡检单_XJ20260924-0001.pdf');
    // 单条导出保持直接下载，未出现日期范围弹窗
    expect(document.body.querySelector('.ant-modal')).toBeNull();
  });
});
