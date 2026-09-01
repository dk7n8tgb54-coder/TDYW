/**
 * 地面干扰记录列表摘要列测试
 *
 * 验证：
 * 1. 列表只显示关键列：日期时间/航班号/机号/位置机位/频率/现象/附件/操作；
 * 2. 现象列以摘要（ellipsis）展示；
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
      datetime: '2026-08-01 10:00:00', flight_number: 'CA1234',
      aircraft_no: 'B-2026', aircraft_type: 'A320',
      location: 'T2航站楼3号廊桥/12号机位', frequency: '118.6',
      phenomenon: '甚高频通信出现杂音，断续无法建立联系，多次呼叫未应答',
      cause_analysis: '判断为地面电源车干扰，已协调停用并复测正常',
      attachment_count: 2,
    },
    {
      id: 2,
      datetime: '2026-08-02 11:00:00', flight_number: 'CA5678',
      aircraft_no: 'B-1001', aircraft_type: 'B738',
      location: 'T1廊桥/08号机位', frequency: '121.5',
      phenomenon: '频率占用的杂音',
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

describe('地面列表摘要列', () => {
  test('只显示关键列（日期时间/航班号/机号/机位/频率/现象/原因分析/附件/操作）', () => {
    const headers = headerTexts();
    for (const title of ['日期时间', '航班号', '机号', '位置/机位', '频率', '现象', '原因分析', '附件', '操作']) {
      expect(headers).toContain(title);
    }
    // 不应出现空中业务专有列
    expect(headers).not.toContain('航线');
    expect(headers).not.toContain('告警摘要');
  });

  test('现象列带省略摘要（ellipsis 类）', () => {
    const cell = Array.from(document.querySelectorAll('.ant-table-tbody td'))
      .find(td => td.textContent.includes('甚高频通信出现杂音'));
    expect(cell).toBeTruthy();
    expect(cell.className).toContain('ant-table-cell-ellipsis');
  });

  test('附件列显示徽标计数', () => {
    const badges = Array.from(document.querySelectorAll('.ant-table-tbody td'))
      .map(td => td.textContent.trim());
    expect(badges).toContain('2');
  });

  test('双击行触发查看详情', () => {
    const row = document.querySelector('.ant-table-tbody tr');
    expect(row).toBeTruthy();
    act(() => {
      row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
    });
    expect(mockedStore.showForm).toHaveBeenCalled();
  });
});

describe('纯记录型操作列', () => {
  test('操作列包含查看/编辑/删除，无提交/关闭等状态流转按钮', () => {
    const rows = Array.from(document.querySelectorAll('.ant-table-tbody tr'));
    expect(rows.length).toBeGreaterThanOrEqual(2);
    const row = rows.find(r => r.textContent.includes('CA1234'));
    expect(row.textContent).toContain('查看');
    expect(row.textContent).toContain('编辑');
    expect(row.textContent).toContain('删除');
    expect(row.textContent).not.toContain('提交');
    expect(row.textContent).not.toContain('关闭');
  });
});
