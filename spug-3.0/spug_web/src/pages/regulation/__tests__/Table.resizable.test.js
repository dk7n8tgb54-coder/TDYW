/**
 * 规章管理表格列宽拖动接入测试
 *
 * 验证 Table.js 通过 TableCard resizable 接入 components/resizableColumns：
 * 1. 数据列（含规章名称首列）表头右缘渲染拖拽柄，固定操作列不渲染
 * 2. 真实拖拽路径（mousedown -> document mousemove -> mouseup）更新列宽
 *    并按 tKey="regulation" 写入会话存储
 * 3. 双击拖拽柄恢复该列默认宽度
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染组件；
 * store 以 jest.mock 替换，避免 componentDidMount 触发真实 HTTP 请求。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import ComTable from '../Table';

jest.mock('../store', () => ({
  records: [{
    id: 1,
    title: '无线电管理办法',
    rule_no: 'TG-2026-001',
    issuing_authority: '省无线电管理机构',
    biz_type: '制度',
    status: 'active',
    effective_date: '2026-01-01',
  }],
  isFetching: false,
  pageNum: 1,
  pageSize: 20,
  total: 1,
  fetchRecords: jest.fn(),
  showDetail: jest.fn(),
  showForm: jest.fn(),
}));

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
});

describe('规章管理 Table 列宽拖动（TableCard resizable 集成）', () => {
  it('数据列（含规章名称首列）渲染拖拽柄，固定操作列不渲染', () => {
    renderTable();
    ['规章名称', '规章编号', '发文单位', '业务类型', '状态', '生效日期'].forEach(title => {
      expect(findHandle(findTh(title))).not.toBeNull();
    });
    expect(findHandle(findTh('操作'))).toBeNull();
  });

  it('真实拖拽更新列宽并按 tKey=regulation 写入会话存储', () => {
    renderTable();
    expect(colWidths()).toContain('140px');
    drag(findTh('规章编号'), 60);
    expect(colWidths()).toContain('200px');
    expect(colWidths()).not.toContain('140px');
    const stored = window.__sessionTableColWidths || {};
    expect(stored.regulation['规章编号']).toBe(200);
    // 其它列宽度不受影响
    expect(stored.regulation['规章名称']).toBeUndefined();
    expect(stored.regulation['发文单位']).toBeUndefined();
  });

  it('双击拖拽柄恢复该列默认宽度', () => {
    renderTable();
    const th = findTh('规章编号');
    drag(th, 60);
    expect(colWidths()).toContain('200px');
    act(() => {
      Simulate.doubleClick(findHandle(th));
    });
    expect(colWidths()).toContain('140px');
    // 首列规章名称默认宽度也是 200px，按列序断言规章编号列已复原
    expect(colWidths()[1]).toBe('140px');
    const stored = window.__sessionTableColWidths || {};
    expect((stored.regulation || {})['规章编号']).toBeUndefined();
  });
});
