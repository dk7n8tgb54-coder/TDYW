/**
 * 台站频率批复表格列宽拖动接入测试
 *
 * 验证 Table.js 通过 TableCard resizable 接入 components/resizableColumns：
 * 1. 数据列（含文件名称首列）表头右缘渲染拖拽柄，固定操作列不渲染
 * 2. 真实拖拽路径（mousedown -> document mousemove -> mouseup）更新列宽
 *    并按 tKey="sfa" 写入会话存储
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

jest.mock('../store', () => ({
  setActive: jest.fn(),
  records: [{
    id: 1,
    name: '关于XX台站频率的批复',
    doc_no: '无电〔2026〕12号',
    frequency_text: '439.5MHz',
    valid_from: '2026-01-01',
    valid_to: '2026-12-31',
    days_left: 30,
    computed_status: 'normal',
    responsible_user_name: '李四',
    attachment_count: 1,
    created_at: '2026-08-01 10:00:00',
  }],
  isFetching: false,
  pageNum: 1,
  pageSize: 20,
  total: 1,
  record: null,
  loadDetail: jest.fn(),
  fetchRecords: jest.fn(),
  showDetail: jest.fn(),
  showForm: jest.fn(),
}));

// 操作列仅在具备编辑/删除权限时渲染：以超级权限走真实 hasPermission 路径
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

describe('台站频率批复 Table 列宽拖动（TableCard resizable 集成）', () => {
  it('数据列（含文件名称首列）渲染拖拽柄，固定操作列不渲染', () => {
    renderTable();
    ['文件名称', '文件编号', '批复频率', '起始日期', '截止日期', '剩余天数', '状态', '责任人', '附件', '创建时间'].forEach(title => {
      expect(findHandle(findTh(title))).not.toBeNull();
    });
    expect(findTh('操作')).toBeTruthy();
    expect(findHandle(findTh('操作'))).toBeNull();
  });

  it('真实拖拽更新列宽并按 tKey=sfa 写入会话存储', () => {
    renderTable();
    drag(findTh('文件名称'), 60);
    expect(colWidths()).toContain('260px');
    const stored = window.__sessionTableColWidths || {};
    expect(stored.sfa['文件名称']).toBe(260);
    // 其它列宽度不受影响
    expect(stored.sfa['文件编号']).toBeUndefined();
    expect(stored.sfa['批复频率']).toBeUndefined();
  });

  it('双击拖拽柄恢复该列默认宽度', () => {
    renderTable();
    const th = findTh('文件名称');
    drag(th, 60);
    expect(colWidths()).toContain('260px');
    act(() => {
      Simulate.doubleClick(findHandle(th));
    });
    expect(colWidths()).toContain('200px');
    const stored = window.__sessionTableColWidths || {};
    expect((stored.sfa || {})['文件名称']).toBeUndefined();
  });
});
