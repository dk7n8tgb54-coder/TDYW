/**
 * 列宽拖动公共能力测试（components/resizableColumns + TableCard 集成）
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染 antd Table 执行
 * 真实拖拽路径（mousedown -> document mousemove -> mouseup）。
 * ResizeObserver / matchMedia 为 jsdom 环境垫片，仅补齐浏览器 API。
 * 宽度存储是 window 上的会话内存：beforeEach 直接清空模拟新会话，
 * "整页刷新"用例用 delete 模拟 JS 上下文销毁。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import {Table} from 'antd';
import TableCard from '../TableCard';
import {useResizableColumns} from '../resizableColumns';

// jsdom 环境垫片仅需补齐 API 形状，无行为可实现
/* eslint-disable no-empty-function */
if (!global.ResizeObserver) {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
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
/* eslint-enable no-empty-function */

const BASE_COLUMNS = [
  {title: '名称', dataIndex: 'name', width: 200},
  {title: '数量', dataIndex: 'count', width: 100, minWidth: 80},
];

let lastApi = null;

function HookTable({tKey, columns, enabled = true}) {
  lastApi = useResizableColumns(tKey, columns, {enabled});
  return (
    <Table
      rowKey="id"
      tableLayout="fixed"
      scroll={{x: 320}}
      components={lastApi.components}
      columns={lastApi.resizableColumns}
      dataSource={[{id: 1, name: 'n1', count: 5}]}/>
  );
}

function renderNode(node) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(node, container);
  });
  return container;
}

function findHeaderCell(container, title) {
  return Array.from(container.querySelectorAll('thead th'))
    .find(th => th.textContent.includes(title));
}

function findHandle(th) {
  return th ? th.querySelector('.resizableHandle') : null;
}

function findCols(container) {
  return container.querySelectorAll('colgroup col');
}

function drag(th, deltaX, startClientX = 100) {
  const handle = findHandle(th);
  act(() => {
    Simulate.mouseDown(handle, {button: 0, clientX: startClientX});
  });
  act(() => {
    document.dispatchEvent(new MouseEvent('mousemove', {clientX: startClientX + deltaX}));
  });
}

function mouseUp() {
  act(() => {
    document.dispatchEvent(new MouseEvent('mouseup'));
  });
}

function readSessionWidths(tKey) {
  const all = window.__sessionTableColWidths;
  return (all && all[tKey]) || {};
}

describe('useResizableColumns（真实 antd Table 渲染）', () => {
  beforeEach(() => {
    lastApi = null;
    delete window.__sessionTableColWidths;
  });

  it('未开启（enabled=false）时不渲染拖拽柄，列配置原样透传', () => {
    const container = renderNode(<HookTable tKey="demo" columns={BASE_COLUMNS} enabled={false}/>);
    expect(findHandle(findHeaderCell(container, '名称'))).toBeNull();
    expect(findHandle(findHeaderCell(container, '数量'))).toBeNull();
    const cols = findCols(container);
    expect(cols[0].style.width).toBe('200px');
    expect(cols[1].style.width).toBe('100px');
  });

  it('未传 tKey 时不渲染拖拽柄、不写入会话存储', () => {
    const container = renderNode(<HookTable tKey={undefined} columns={BASE_COLUMNS}/>);
    expect(findHandle(findHeaderCell(container, '名称'))).toBeNull();
    expect(readSessionWidths(undefined)).toEqual({});
  });

  it('有数字 width 的列渲染拖拽柄，无 width 的列不渲染', () => {
    const columns = [...BASE_COLUMNS, {title: '备注', dataIndex: 'memo'}];
    const container = renderNode(<HookTable tKey="demo" columns={columns}/>);
    expect(findHandle(findHeaderCell(container, '名称'))).not.toBeNull();
    expect(findHandle(findHeaderCell(container, '数量'))).not.toBeNull();
    expect(findHandle(findHeaderCell(container, '备注'))).toBeNull();
  });

  it('拖动实时更新宽度，mouseup 才写入会话存储', () => {
    const container = renderNode(<HookTable tKey="demo" columns={BASE_COLUMNS}/>);
    drag(findHeaderCell(container, '名称'), 60);
    expect(findCols(container)[0].style.width).toBe('260px');
    expect(readSessionWidths('demo')).toEqual({});
    mouseUp();
    expect(readSessionWidths('demo')).toEqual({名称: 260});
    expect(findCols(container)[0].style.width).toBe('260px');
  });

  it('宽度受列级 minWidth 钳制', () => {
    const container = renderNode(<HookTable tKey="demo" columns={BASE_COLUMNS}/>);
    drag(findHeaderCell(container, '数量'), -100);
    mouseUp();
    expect(findCols(container)[1].style.width).toBe('80px');
    expect(readSessionWidths('demo')).toEqual({数量: 80});
  });

  it('未设置 minWidth 的列使用默认最小宽度 60', () => {
    const container = renderNode(<HookTable tKey="demo" columns={BASE_COLUMNS}/>);
    drag(findHeaderCell(container, '名称'), -300);
    mouseUp();
    expect(findCols(container)[0].style.width).toBe('60px');
  });

  it('站内切页往返（卸载重挂载）保留已调宽度', () => {
    const first = renderNode(<HookTable tKey="retain_demo" columns={BASE_COLUMNS}/>);
    drag(findHeaderCell(first, '名称'), 60);
    mouseUp();
    expect(findCols(first)[0].style.width).toBe('260px');
    const again = renderNode(<HookTable tKey="retain_demo" columns={BASE_COLUMNS}/>);
    expect(findCols(again)[0].style.width).toBe('260px');
  });

  it('整页刷新（会话存储随 JS 上下文销毁）后列宽还原默认', () => {
    const container = renderNode(<HookTable tKey="refresh_demo" columns={BASE_COLUMNS}/>);
    drag(findHeaderCell(container, '名称'), 60);
    mouseUp();
    expect(findCols(container)[0].style.width).toBe('260px');
    // 模拟整页刷新：JS 上下文销毁，window 上的会话存储随之清空
    delete window.__sessionTableColWidths;
    const reloaded = renderNode(<HookTable tKey="refresh_demo" columns={BASE_COLUMNS}/>);
    expect(findCols(reloaded)[0].style.width).toBe('200px');
    expect(findCols(reloaded)[1].style.width).toBe('100px');
  });

  it('双击拖拽柄恢复该列默认宽度', () => {
    const container = renderNode(<HookTable tKey="demo" columns={BASE_COLUMNS}/>);
    const th = findHeaderCell(container, '名称');
    drag(th, 60);
    mouseUp();
    expect(findCols(container)[0].style.width).toBe('260px');
    act(() => {
      Simulate.doubleClick(findHandle(th));
    });
    expect(findCols(container)[0].style.width).toBe('200px');
    expect(readSessionWidths('demo')).toEqual({});
  });

  it('resetAllWidths 恢复当前表格全部列宽', () => {
    const container = renderNode(<HookTable tKey="demo" columns={BASE_COLUMNS}/>);
    drag(findHeaderCell(container, '名称'), 60);
    mouseUp();
    drag(findHeaderCell(container, '数量'), 40);
    mouseUp();
    expect(findCols(container)[0].style.width).toBe('260px');
    expect(findCols(container)[1].style.width).toBe('140px');
    act(() => {
      lastApi.resetAllWidths();
    });
    expect(findCols(container)[0].style.width).toBe('200px');
    expect(findCols(container)[1].style.width).toBe('100px');
    expect(readSessionWidths('demo')).toEqual({});
  });

  it('固定列不渲染拖拽柄，宽度不被会话存储值覆盖', () => {
    window.__sessionTableColWidths = {demo: {操作: 400}};
    const columns = [...BASE_COLUMNS, {title: '操作', width: 210, fixed: 'right'}];
    const container = renderNode(<HookTable tKey="demo" columns={columns}/>);
    expect(findHandle(findHeaderCell(container, '操作'))).toBeNull();
    expect(findHandle(findHeaderCell(container, '名称'))).not.toBeNull();
    expect(findCols(container)[2].style.width).toBe('210px');
  });
});

describe('TableCard resizable 集成', () => {
  function renderCard(resizable, tKey = 'card_demo') {
    return renderNode(
      <TableCard
        tKey={tKey}
        resizable={resizable}
        title="测试表格"
        rowKey="id"
        dataSource={[{id: 1, name: 'n1', count: 5}]}>
        <Table.Column title="甲" dataIndex="name" width={200}/>
        <Table.Column title="乙" dataIndex="count" width={100}/>
      </TableCard>
    );
  }

  beforeEach(() => {
    delete window.__sessionTableColWidths;
  });

  it('开启 resizable 后可拖动列宽，同会话重新挂载保留', () => {
    const container = renderCard(true);
    const th = findHeaderCell(container, '甲');
    expect(findHandle(th)).not.toBeNull();
    drag(th, 50);
    mouseUp();
    expect(findCols(container)[0].style.width).toBe('250px');
    const again = renderCard(true);
    expect(findCols(again)[0].style.width).toBe('250px');
  });

  it('未开启 resizable 的表格行为保持不变', () => {
    const container = renderCard(false);
    expect(findHandle(findHeaderCell(container, '甲'))).toBeNull();
    expect(window.__sessionTableColWidths).toBeUndefined();
  });

  it('TableCard 集成：固定列不渲染拖拽柄，其他列正常', () => {
    const container = renderNode(
      <TableCard
        tKey="card_fixed"
        resizable
        title="测试表格"
        rowKey="id"
        dataSource={[{id: 1, name: 'n1', count: 5}]}>
        <Table.Column title="甲" dataIndex="name" width={200}/>
        <Table.Column title="乙" dataIndex="count" width={100}/>
        <Table.Column title="操作" dataIndex="name" width={120} fixed="right"/>
      </TableCard>
    );
    expect(findHandle(findHeaderCell(container, '操作'))).toBeNull();
    expect(findHandle(findHeaderCell(container, '甲'))).not.toBeNull();
  });
});
