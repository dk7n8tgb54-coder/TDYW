/**
 * 空中干扰列表摘要列测试
 *
 * 验证：
 * 1. 列表只显示关键列：日期时间/航班号/航线/跑道进近程序/告警摘要/持续时间/
 *    原因分析/附件/操作；
 * 2. 告警摘要/跑道进近程序为后端聚合的共同摘要文本，原因分析以摘要展示；
 * 3. 纯记录型：操作列包含查看/编辑/删除，无状态流转按钮。
 *
 * 环境说明：沿用本仓库惯例使用 ReactDOM + jsdom 真实渲染组件；
 * store 以 jest.mock 替换，避免 componentDidMount 触发真实 HTTP 请求；
 * 操作列经 hasPermission 条件渲染，jsdom 下通过 sessionStorage 授予超级权限。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {updatePermissions} from 'libs';
import ComTable from '../Table';
import store from '../store';

jest.mock('../store', () => ({
  records: [
    {
      id: 1,
      datetime: '2026-08-02 14:30:00', flight_number: 'MU5678',
      aircraft_type: 'B738', route: 'HFE-VVO',
      runway: '16', approach_procedure: 'ILS',
      runway_approach_text: '16 / ILS',
      alert_form: 'TCAS RA', alert_altitude_text: '1200米', alert_segment: '进场下降段',
      alert_summary: 'TCAS RA / 1200米 / 进场下降段',
      duration_text: '45秒',
      cause_analysis: '下降过程中进入相邻航路，与对头航班高度接近，初步判断为间隔不足导致告警，需要进一步核实雷达轨迹与管制通话记录',
      attachment_count: 1,
    },
    {
      id: 2,
      datetime: '2026-08-03 09:00:00', flight_number: 'CZ3321',
      aircraft_type: 'A321', route: 'SHA-CAN',
      runway_approach_text: '05 / VOR',
      alert_summary: '短时高度偏离',
      duration_text: '2分钟',
      cause_analysis: '',
      attachment_count: 0,
    },
  ],
  isFetching: false,
  pageNum: 1,
  pageSize: 10,
  total: 2,
  dataSource: null, // 由 beforeEach 指向 records
  fetchRecords: jest.fn(),
  showForm: jest.fn(),
  getExportParams: jest.fn(() => ({})),
}));

// 操作列在具备编辑/删除权限时渲染：以超级权限走真实 hasPermission 路径
sessionStorage.setItem('is_supper', 'true');
updatePermissions();

// jsdom 环境垫片：antd Table 分页链需要 matchMedia，rc-table 测量需要 ResizeObserver
/* eslint-disable no-empty-function */
if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
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

import mockedStore from '../store';

let container = null;

function renderTable() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<ComTable/>, container);
  });
}

function headerTexts() {
  return Array.from(document.querySelectorAll('.ant-table-thead th')).map(th => th.textContent.trim());
}

function rowByFlight(flight) {
  return Array.from(document.querySelectorAll('.ant-table-tbody tr'))
    .find(r => r.textContent.includes(flight));
}

beforeEach(() => {
  mockedStore.dataSource = mockedStore.records;
  renderTable();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
});

describe('空中列表摘要列', () => {
  test('只显示关键列（日期时间/航班号/航线/跑道进近程序/告警摘要/持续时间/原因分析/附件/操作）', () => {
    const headers = headerTexts();
    for (const title of ['日期时间', '航班号', '航线', '跑道/进近程序', '告警摘要',
      '持续时间', '原因分析', '附件', '操作']) {
      expect(headers).toContain(title);
    }
    // 不应出现地面业务专有列
    expect(headers).not.toContain('机位');
    expect(headers).not.toContain('频率');
  });

  test('告警摘要与跑道/进近程序列渲染后端聚合文本', () => {
    const row = rowByFlight('MU5678');
    expect(row.textContent).toContain('TCAS RA / 1200米 / 进场下降段');
    expect(row.textContent).toContain('16 / ILS');
    expect(row.textContent).toContain('45秒');
  });

  test('原因分析列以摘要（ellipsis）展示且完整文本在详情中查看', () => {
    const cell = Array.from(document.querySelectorAll('.ant-table-tbody td'))
      .find(td => td.textContent.includes('间隔不足导致告警'));
    expect(cell).toBeTruthy();
    expect(cell.className).toContain('ant-table-cell-ellipsis');
  });

  test('双击行触发查看详情', () => {
    const row = document.querySelector('.ant-table-tbody tr');
    act(() => {
      row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
    });
    expect(mockedStore.showForm).toHaveBeenCalled();
  });
});

describe('纯记录型操作列', () => {
  test('操作列包含查看/编辑/删除，无提交/处置/关闭等状态流转按钮', () => {
    const row = rowByFlight('MU5678');
    expect(row.textContent).toContain('查看');
    expect(row.textContent).toContain('编辑');
    expect(row.textContent).toContain('删除');
    expect(row.textContent).not.toContain('提交');
    expect(row.textContent).not.toContain('处置');
    expect(row.textContent).not.toContain('关闭');
  });
});
