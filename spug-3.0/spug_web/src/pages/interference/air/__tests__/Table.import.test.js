/**
 * 空中干扰列表页 Excel 导入入口测试
 *
 * 验证：
 * 1. 展示「下载导入模板」「导入 Excel」按钮；
 * 2. 模板下载调用空中导入模板接口；
 * 3. 导入弹窗传入 business="air"，导入成功后刷新列表。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {updatePermissions, exportFile} from 'libs';
import ComTable from '../Table';
import mockedStore from '../store';
import ImportModal from '../../ImportModal';

jest.mock('../store', () => ({
  records: [{
    id: 1, datetime: '2026-08-02 09:30:00', flight_number: 'MU5678',
    aircraft_type: 'B738', route: 'KMG-SHA',
    alert_summary: '高度告警',
    duration_text: '90分钟', cause_analysis: '',
    phenomenon: '低高度告警', attachment_count: 0,
  }],
  isFetching: false,
  pageNum: 1,
  pageSize: 10,
  total: 1,
  statusOptions: [],
  dataSource: null,
  fetchRecords: jest.fn(),
  showForm: jest.fn(),
  getExportParams: jest.fn(() => ({})),
}));

jest.mock('../../ImportModal', () => jest.fn(() => null));

// 只 mock 底层 exportFile 模块：mock 整个 'libs' 会与 routes.js 的循环依赖冲突
jest.mock('libs/exportFile', () => ({
  __esModule: true,
  exportFile: jest.fn(() => Promise.resolve()),
  default: jest.fn(() => Promise.resolve()),
}));

/* eslint-disable no-empty-function */
if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {},
    dispatchEvent: () => false,
  });
}
if (!global.ResizeObserver) {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
/* eslint-enable no-empty-function */

let container = null;

function renderTable() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<ComTable/>, container);
  });
}

function findButton(text) {
  return Array.from(container.querySelectorAll('button'))
    .find(btn => btn.textContent.includes(text));
}

beforeEach(() => {
  sessionStorage.setItem('is_supper', 'true');
  updatePermissions();
  mockedStore.dataSource = mockedStore.records;
  mockedStore.fetchRecords.mockClear();
  ImportModal.mockClear();
  exportFile.mockClear();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
});

describe('空中列表导入入口', () => {
  test('展示导入与模板下载按钮', () => {
    renderTable();
    expect(findButton('导入 Excel')).toBeTruthy();
    expect(findButton('下载导入模板')).toBeTruthy();
  });

  test('下载导入模板调用空中模板接口', () => {
    renderTable();
    act(() => {
      findButton('下载导入模板').click();
    });
    expect(exportFile).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/interference/air/import/template/',
      defaultFilename: '空中干扰导入模板.xlsx',
    }));
  });

  test('点击导入 Excel 弹出空中导入弹窗', () => {
    renderTable();
    act(() => {
      findButton('导入 Excel').click();
    });
    expect(ImportModal).toHaveBeenCalled();
    const props = ImportModal.mock.calls[0][0];
    expect(props.business).toBe('air');
    expect(props.visible).toBe(true);
  });

  test('导入成功后关闭弹窗并刷新列表', () => {
    renderTable();
    act(() => {
      findButton('导入 Excel').click();
    });
    const props = ImportModal.mock.calls[0][0];
    // componentDidMount 已触发初次加载，清除后再验证导入成功回调引发刷新
    mockedStore.fetchRecords.mockClear();
    act(() => {
      props.onSuccess(5);
    });
    expect(mockedStore.fetchRecords).toHaveBeenCalledTimes(1);
  });
});
