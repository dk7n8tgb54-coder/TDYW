/**
 * 无线电执照表格列宽拖动接入测试
 *
 * 验证 Table.js 通过 TableCard resizable 接入 components/resizableColumns：
 * 1. 数据列表头右缘渲染拖拽柄，固定操作列不渲染
 * 2. 真实拖拽路径（mousedown -> document mousemove -> mouseup）更新列宽
 *    并按 tKey="rl" 写入会话存储
 * 3. 双击拖拽柄恢复该列默认宽度
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染组件；
 * store 以 jest.mock 替换，避免 componentDidMount 触发真实 HTTP 请求；
 * 操作列经 hasPermission 条件渲染，jsdom 下通过 sessionStorage 授予超级权限。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import {updatePermissions} from 'libs';
import ComTable from '../Table';
import store from '../store';

jest.mock('../store', () => ({
  records: [{
    id: 1,
    station_name: 'XX 固定站',
    frequencies: [{frequency_value: '439.5', frequency_unit: 'MHz', frequency_text: ''}],
    purpose: '业余中转',
    valid_from: '2026-01-01',
    valid_to: '2026-12-31',
    days_left: 30,
    computed_status: 'normal',
    responsible_user_name: '张三',
    attachment_count: 2,
    created_at: '2026-08-01 10:00:00',
  }],
  isFetching: false,
  pageNum: 1,
  pageSize: 20,
  total: 1,
  fetchRecords: jest.fn(),
  showDetail: jest.fn(),
  showForm: jest.fn(),
}));

// 操作列在具备查看/编辑/删除任一权限时渲染：以超级权限走真实 hasPermission 路径
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

let container = null;

function renderTable() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<ComTable/>, container);
  });
}

function findTh(title) {
  return Array.from(container.querySelectorAll('.ant-table-thead th'))
    .find(th => th.textContent.trim() === title);
}

function findHandle(th) {
  return th ? th.querySelector('.resizableHandle') : null;
}

function colWidths() {
  return Array.from(container.querySelectorAll('colgroup col')).map(col => col.style.width);
}

function drag(th, deltaX, startClientX = 100) {
  act(() => {
    Simulate.mouseDown(findHandle(th), {button: 0, clientX: startClientX});
  });
  act(() => {
    document.dispatchEvent(new MouseEvent('mousemove', {clientX: startClientX + deltaX}));
  });
  act(() => {
    document.dispatchEvent(new MouseEvent('mouseup'));
  });
}

beforeEach(() => {
  delete window.__sessionTableColWidths;
});

afterEach(() => {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
  delete window.__sessionTableColWidths;
  sessionStorage.clear();
});

describe('无线电执照 Table 列宽拖动（TableCard resizable 集成）', () => {
  it('数据列（含台站首列）渲染拖拽柄，固定操作列不渲染', () => {
    renderTable();
    ['台站', '频率', '用途', '起始日期', '截止日期', '剩余天数', '状态', '责任人', '附件', '创建时间'].forEach(title => {
      expect(findHandle(findTh(title))).not.toBeNull();
    });
    expect(findTh('操作')).toBeTruthy();
    expect(findHandle(findTh('操作'))).toBeNull();
  });

  it('真实拖拽更新列宽并按 tKey=rl 写入会话存储', () => {
    renderTable();
    drag(findTh('频率'), 40);
    expect(colWidths()).toContain('220px');
    const stored = window.__sessionTableColWidths || {};
    expect(stored.rl['频率']).toBe(220);
    // 其它列宽度不受影响
    expect(stored.rl['台站']).toBeUndefined();
    expect(stored.rl['用途']).toBeUndefined();
  });

  it('双击拖拽柄恢复该列默认宽度', () => {
    renderTable();
    const th = findTh('频率');
    drag(th, 40);
    expect(colWidths()).toContain('220px');
    act(() => {
      Simulate.doubleClick(findHandle(th));
    });
    expect(colWidths()).toContain('180px');
    const stored = window.__sessionTableColWidths || {};
    expect((stored.rl || {})['频率']).toBeUndefined();
  });
});

describe('无线电执照 Table 操作列门控（只读用户保留查看入口）', () => {
  function grantPermissions(perms) {
    sessionStorage.setItem('is_supper', 'false');
    sessionStorage.setItem('permissions', JSON.stringify(perms));
    updatePermissions();
  }

  function actionButtons() {
    return Array.from(container.querySelectorAll('.ant-table-tbody button'))
      .map(btn => btn.textContent.trim());
  }

  it('仅查看权限的用户渲染操作列，且只有查看按钮、点击进详情', () => {
    grantPermissions(['radio_license.license.view']);
    renderTable();
    expect(findTh('操作')).toBeTruthy();
    expect(actionButtons()).toEqual(['查看']);
    act(() => {
      Simulate.click(container.querySelector('.ant-table-tbody button'));
    });
    expect(store.showDetail).toHaveBeenCalledWith(expect.objectContaining({id: 1}));
  });

  it('无查看/编辑/删除权限的用户不渲染操作列', () => {
    grantPermissions([]);
    renderTable();
    expect(findTh('操作')).toBeUndefined();
  });
});
