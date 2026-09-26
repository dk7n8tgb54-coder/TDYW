/**
 * 行结构树编辑器测试（第一阶段：行方向多级结构）。
 * 真实渲染 RowTreeEditor：新增同级/子级、层级上限禁用、check 不能含子节点、
 * 树展开渲染路径与层级。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: mockHttpDelete},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
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
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

/** 构造 n 层链式本地树（用于层级上限断言）。 */
function chainTree(depth) {
  const make = level => ({
    key: `k${level}`, id: undefined, name: `L${level}`, node_type: 'group',
    display_order: 0, is_active: true, children: level < depth ? [make(level + 1)] : [],
  });
  return [make(1)];
}

describe('RowTreeEditor（行结构树）', () => {
  it('渲染根节点：路径/层级/子节点数可见，展开渲染子节点', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    const tree = [{
      key: 'root', id: undefined, name: '信道', node_type: 'repeat_group',
      display_order: 0, is_active: true,
      children: [{
        key: 'c1', id: undefined, name: '主电台', node_type: 'check',
        display_order: 0, is_active: true, children: [],
      }],
    }];
    await act(async () => {
      ReactDOM.render(<RowTreeEditor tree={tree} onChange={() => {}}/>, container);
    });
    await act(flush);
    expect(document.body.textContent).toContain('信道');
    expect(document.body.textContent).toContain('主电台');
    expect(document.body.textContent).toContain('信道 / 主电台');
    expect(document.body.textContent).toContain('可重复分组');
    expect(document.body.textContent).toContain('行对象');
  });

  it('添加根级行节点（新增同级）与添加子级', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    const tree = [{
      key: 'root', id: undefined, name: '信道', node_type: 'repeat_group',
      display_order: 0, is_active: true, children: [],
    }];
    let latest = null;
    await act(async () => {
      ReactDOM.render(
        <RowTreeEditor tree={tree} onChange={t => {latest = t;}}/>, container);
    });
    await act(flush);
    // 新增同级（根级）
    const addRoot = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.includes('添加根级行节点'));
    await act(async () => {
      addRoot.click();
    });
    await act(flush);
    expect(latest).toHaveLength(2);
    // 新增子级：信道行的 + 按钮（其操作列第一个可用按钮）
    const plusButtons = Array.from(container.querySelectorAll('button.ant-btn-link'))
      .filter(b => b.querySelector('.anticon-plus') && !b.disabled);
    await act(async () => {
      plusButtons[0].click();
    });
    await act(flush);
    // 最新树：根级仍 2 个；其中一个有子节点
    expect(latest.some(n => (n.children || []).length === 1)).toBe(true);
  });

  it('check 节点的添加子级按钮禁用（行对象不能包含子节点）', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    const tree = [{
      key: 'leaf', id: undefined, name: '主电台', node_type: 'check',
      display_order: 0, is_active: true, children: [],
    }];
    await act(async () => {
      ReactDOM.render(<RowTreeEditor tree={tree} onChange={() => {}}/>, container);
    });
    await act(flush);
    const plusButtons = Array.from(container.querySelectorAll('button.ant-btn-link'))
      .filter(b => b.querySelector('.anticon-plus'));
    expect(plusButtons).toHaveLength(1);
    expect(plusButtons[0].disabled).toBe(true);
  });

  it('第 5 级节点的添加子级按钮禁用（最大层级 5）', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    await act(async () => {
      ReactDOM.render(
        <RowTreeEditor tree={chainTree(5)} onChange={() => {}} tableKey="t1"/>, container);
    });
    await act(flush);
    const plusButtons = Array.from(container.querySelectorAll('button.ant-btn-link'))
      .filter(b => b.querySelector('.anticon-plus') && !b.disabled);
    expect(plusButtons).toHaveLength(4);  // 第 1-4 级可用，第 5 级禁用
  });
});
