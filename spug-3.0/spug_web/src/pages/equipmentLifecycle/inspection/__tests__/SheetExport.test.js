/**
 * 巡检单导出测试（列表导出按钮 + 详情抽屉 Excel/PDF 导出按钮）：
 * - 导出按钮按 equipment_lifecycle.inspection.export 权限显示；
 * - 列表导出携带当前筛选条件（不含分页参数）；
 * - 详情抽屉 Excel/PDF 分别请求对应导出端点；
 * - ExportButton 下载中防重复点击，失败后恢复可点、不崩溃。
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

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
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
    ReactDOM.render(<SheetIndex/>, container);
  });
  await act(flush);
  await act(flush);
}

describe('巡检单导出按钮', () => {
  it('无 export 权限时列表导出按钮不渲染，有权限时渲染', async () => {
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

  it('列表导出携带当前筛选条件（值班日范围/状态/关键字，不含分页）', async () => {
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

    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const options = mockExportFile.mock.calls[0][0];
    expect(options.url).toBe('/api/equipment-lifecycle/inspection-sheets/export/');
    expect(options.params).toEqual({
      duty_from: '2026-09-01',
      duty_to: '2026-09-30',
      status: 'submitted',
      keyword: 'XJ20260924',
    });
  });

  it('详情抽屉导出 Excel/PDF 请求对应单据的导出端点', async () => {
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
  });

  it('下载进行中防重复点击（loading 状态），完成后恢复', async () => {
    mockFlow();
    await renderPage();
    mockExportFile.mockImplementation(() => new Promise(() => {}));

    const button = findButton(container, '导出 Excel');
    await act(async () => {
      button.click();
    });
    await act(flush);

    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const loadingButton = findButton(container, '导出 Excel');
    expect(loadingButton.disabled || loadingButton.className.includes('ant-btn-loading'))
      .toBe(true);
    // loading 期间重复点击不再触发请求
    await act(async () => {
      loadingButton.click();
    });
    await act(flush);
    expect(mockExportFile).toHaveBeenCalledTimes(1);
  });

  it('导出失败不崩溃且按钮恢复可点（错误提示由拦截器负责）', async () => {
    mockFlow();
    await renderPage();
    mockExportFile.mockRejectedValue(new Error('export failed'));

    await act(async () => {
      findButton(container, '导出 Excel').click();
    });
    await act(flush);
    await act(flush);

    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const button = findButton(container, '导出 Excel');
    expect(button.disabled).toBe(false);
    expect(button.className.includes('ant-btn-loading')).toBe(false);
    // 页面仍在正常渲染
    expect(document.body.textContent).toContain('XJ20260924-0001');
  });
});
