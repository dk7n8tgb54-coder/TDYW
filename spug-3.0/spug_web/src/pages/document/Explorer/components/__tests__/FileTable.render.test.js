/**
 * FileTable 组件级渲染测试（2026-08-16）
 *
 * 背景：此前没有任何测试 import FileTable，一次 JSX 语法错误在 jest 全绿下漏网
 * （靠 Babel 手工校验兜住）。本套件用真实 ReactDOM 渲染补上该盲区，
 * 同时验证响应式列显隐在真实组件中的端到端行为。
 *
 * 覆盖：
 * 1. 基础渲染：表头列、数据行、空状态文案、scroll.x 兜底宽度
 * 2. 响应式列显隐：ResizeObserver 上报不同容器宽度时按序隐藏/恢复次要列
 * 3. 首帧（未收到宽度事件）与环境无 ResizeObserver 时：全列展示、不崩溃
 *
 * 环境说明：项目无 @testing-library，用 React 17 自带 react-dom/test-utils + jsdom；
 * jsdom 无原生 ResizeObserver，用桩手动派发宽度事件驱动组件内真实逻辑。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import FileTable from '../FileTable';

// jsdom 未实现 matchMedia，antd Table 的分页链渲染需要（经典 CRA/antd 测试补丁）
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

// ---- ResizeObserver 桩：记录实例，测试手动派发宽度事件 ----
class ResizeObserverStub {
  constructor(callback) {
    this.callback = callback;
    ResizeObserverStub.instances.push(this);
  }
  observe() {}
  unobserve() {}
  disconnect() {}
}
ResizeObserverStub.instances = [];

// ---- 公共空间完整列配置（与 useColumns 输出同构）----
function buildColumns() {
  return [
    { title: '文件名', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'file_type', key: 'file_type', width: 130 },
    { title: '大小', dataIndex: 'size', key: 'size', width: 110 },
    { title: '修改时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    { title: '创建人', dataIndex: 'created_by', key: 'created_by', width: 120 },
  ];
}

const DATA = [
  {
    key: 'f1',
    name: '年度工作总结报告.docx',
    file_type: 'Word 文档',
    size: '1.2 MB',
    created_at: '2026-08-01 10:00:00',
    created_by: '张三',
  },
];

let container = null;

function renderTable(props = {}) {
  act(() => {
    ReactDOM.render(
      <FileTable columns={buildColumns()} dataSource={DATA} isPublic {...props} />,
      container
    );
  });
}

function headerTexts() {
  return Array.from(container.querySelectorAll('.ant-table-thead th')).map((th) =>
    th.textContent.trim()
  );
}

/** 手动派发容器宽度（驱动 FileTable 与 rc-table 内部的 ResizeObserver 逻辑） */
function resizeTo(width) {
  act(() => {
    ResizeObserverStub.instances.forEach((observer) =>
      observer.callback([{ contentRect: { width } }])
    );
  });
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  ResizeObserverStub.instances = [];
  global.ResizeObserver = ResizeObserverStub;
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(container);
  });
  container.remove();
  container = null;
  delete global.ResizeObserver;
});

describe('FileTable 基础渲染', () => {
  it('渲染全部列表头与数据行内容', () => {
    renderTable();
    const headers = headerTexts();
    ['文件名', '类型', '大小', '修改时间', '创建人'].forEach((title) =>
      expect(headers).toContain(title)
    );
    expect(container.textContent).toContain('年度工作总结报告.docx');
    expect(container.textContent).toContain('张三');
  });

  it('scroll.x 最小总宽兜底：body table 带 640px 宽度与 100% 最小宽度', () => {
    renderTable();
    // sticky 模式下存在表头/body 两张 table，内联宽度在 body table 上
    const tables = Array.from(container.querySelectorAll('table'));
    const bodyTable = tables.find((t) => t.style.width === '640px');
    expect(bodyTable).toBeTruthy();
    expect(bodyTable.style.minWidth).toBe('100%');
  });

  it('空数据时渲染公共空间空状态文案', async () => {
    // rc-table 的空状态内容依赖实测宽度（componentWidth 为 0 时有意不渲染）。
    // jsdom 无布局且 rc-resize-observer 内置 polyfill 的初始回调不触发，
    // 借助其官方 dev 测试钩子 _el/_rs 驱动 onResize，配合测量 API 桩补齐宽度
    const widthDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
    const rectDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'getBoundingClientRect');
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
      configurable: true,
      get() {
        return 1000;
      },
    });
    HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRectStub() {
      return { width: 1000, height: 0, top: 0, left: 0, bottom: 0, right: 1000, x: 0, y: 0 };
    };
    try {
      renderTable({ dataSource: [] });
      // eslint-disable-next-line global-require
      const { _el, _rs } = require('rc-resize-observer/lib/utils/observerUtil');
      const entities = Array.from(_el.keys()).map((target) => ({ target }));
      await act(async () => {
        _rs(entities);
      });
      expect(container.querySelector('.ant-table-placeholder').textContent).toContain(
        '暂无公共共享文件'
      );
    } finally {
      if (widthDesc) {
        Object.defineProperty(HTMLElement.prototype, 'offsetWidth', widthDesc);
      }
      if (rectDesc) {
        Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', rectDesc);
      }
    }
  });
});

describe('FileTable 响应式列显隐（真实渲染）', () => {
  it('宽容器（1600px）：全部列可见', () => {
    renderTable();
    resizeTo(1600);
    expect(headerTexts()).toEqual(
      expect.arrayContaining(['文件名', '类型', '大小', '修改时间', '创建人'])
    );
  });

  it('980px：隐藏创建人，其余保留', () => {
    renderTable();
    resizeTo(980);
    const headers = headerTexts();
    expect(headers).not.toContain('创建人');
    ['文件名', '类型', '大小', '修改时间'].forEach((title) => expect(headers).toContain(title));
  });

  it('850px：隐藏创建人+大小', () => {
    renderTable();
    resizeTo(850);
    const headers = headerTexts();
    expect(headers).not.toContain('创建人');
    expect(headers).not.toContain('大小');
    ['文件名', '类型', '修改时间'].forEach((title) => expect(headers).toContain(title));
  });

  it('700px：仅保留文件名+修改时间', () => {
    renderTable();
    resizeTo(700);
    const headers = headerTexts();
    expect(headers).toContain('文件名');
    expect(headers).toContain('修改时间');
    expect(headers).not.toContain('创建人');
    expect(headers).not.toContain('大小');
    expect(headers).not.toContain('类型');
  });

  it('宽度回升：隐藏的列恢复显示', () => {
    renderTable();
    resizeTo(700);
    expect(headerTexts()).not.toContain('类型');
    resizeTo(1600);
    const headers = headerTexts();
    ['文件名', '类型', '大小', '修改时间', '创建人'].forEach((title) =>
      expect(headers).toContain(title)
    );
  });
});

describe('FileTable 降级路径', () => {
  it('首帧（未收到宽度事件）：全列展示', () => {
    renderTable();
    expect(headerTexts()).toContain('创建人');
  });

  it('环境无 ResizeObserver：不崩溃且全列展示', () => {
    delete global.ResizeObserver;
    renderTable();
    expect(headerTexts()).toContain('文件名');
    expect(headerTexts()).toContain('创建人');
  });
});
