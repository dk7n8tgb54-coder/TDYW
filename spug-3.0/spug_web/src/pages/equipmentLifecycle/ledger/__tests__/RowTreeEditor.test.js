/**
 * 检查对象编辑器测试（表格的行，行方向多级结构）。
 * 真实渲染 RowTreeEditor：直接添加检查对象、下拉添加分组/可重复分组、
 * 行内下拉添加子项、检查对象/最大层级禁用添加子项、业务语言列名
 * （不再展示层级/路径/子节点数等技术概念列）。
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
  document.body.innerHTML = '';
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function click(el) {
  await act(async () => {
    el.click();
  });
  await act(flush);
}

/** 点击下拉按钮后点击弹出菜单中的指定项（仅可见浮层，精确匹配）。 */
async function pickDropdownItem(triggerText, itemText) {
  const trigger = Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.includes(triggerText));
  expect(trigger).toBeTruthy();
  await click(trigger);
  const item = Array.from(
    document.querySelectorAll('.ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item'))
    .find(el => el.textContent.trim() === itemText);
  expect(item).toBeTruthy();
  await click(item);
}

/** 构造 n 层链式本地树（用于层级上限断言）。 */
function chainTree(depth) {
  const make = level => ({
    key: `k${level}`, id: undefined, name: `L${level}`, node_type: 'group',
    display_order: 0, is_active: true, children: level < depth ? [make(level + 1)] : [],
  });
  return [make(1)];
}

describe('RowTreeEditor（检查对象编辑器）', () => {
  const tree = [{
    key: 'root', id: undefined, name: '信道', node_type: 'repeat_group',
    display_order: 0, is_active: true,
    children: [{
      key: 'c1', id: undefined, name: '主电台', node_type: 'check',
      display_order: 0, is_active: true, children: [],
    }],
  }];

  it('渲染检查对象与分组：业务语言类型名，无层级/路径/子节点数列', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    await act(async () => {
      ReactDOM.render(<RowTreeEditor tree={tree} onChange={() => {}}/>, container);
    });
    await act(flush);
    // 名称列是输入框，断言输入值而非 textContent
    const nameValues = Array.from(container.querySelectorAll('input'))
      .map(input => input.value).filter(v => v);
    expect(nameValues).toEqual(expect.arrayContaining(['信道', '主电台']));
    expect(document.body.textContent).toContain('可重复分组');
    expect(document.body.textContent).toContain('检查对象');
    const headers = Array.from(document.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent);
    expect(headers).toContain('名称');
    expect(headers).not.toContain('层级');
    expect(headers).not.toContain('路径');
    expect(headers).not.toContain('子节点数');
    expect(document.body.textContent).not.toContain('信道 / 主电台');
  });

  it('添加检查对象：根级直接新增 check 节点', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    let latest = null;
    await act(async () => {
      ReactDOM.render(
        <RowTreeEditor tree={tree} onChange={t => {latest = t;}}/>, container);
    });
    await act(flush);
    await click(Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.includes('添加检查对象')));
    expect(latest).toHaveLength(2);
    expect(latest[1].node_type).toBe('check');
  });

  it('添加分组：下拉选择可重复分组', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    let latest = null;
    await act(async () => {
      ReactDOM.render(
        <RowTreeEditor tree={tree} onChange={t => {latest = t;}}/>, container);
    });
    await act(flush);
    await pickDropdownItem('添加分组', '可重复分组');
    expect(latest).toHaveLength(2);
    expect(latest[1].node_type).toBe('repeat_group');
  });

  it('添加分组：下拉选择普通分组', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    let latest = null;
    await act(async () => {
      ReactDOM.render(
        <RowTreeEditor tree={tree} onChange={t => {latest = t;}}/>, container);
    });
    await act(flush);
    await pickDropdownItem('添加分组', '分组');
    expect(latest).toHaveLength(2);
    expect(latest[1].node_type).toBe('group');
  });

  it('行内添加子项：下拉选择检查对象挂到分组之下', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    let latest = null;
    await act(async () => {
      ReactDOM.render(
        <RowTreeEditor tree={tree} onChange={t => {latest = t;}}/>, container);
    });
    await act(flush);
    // 第一行（信道，分组）操作列的可用 + 按钮触发下拉
    const plusButtons = Array.from(container.querySelectorAll('button.ant-btn-link'))
      .filter(b => b.querySelector('.anticon-plus') && !b.disabled);
    await click(plusButtons[0]);
    const item = Array.from(
      document.querySelectorAll('.ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item'))
      .find(el => el.textContent.trim() === '检查对象');
    expect(item).toBeTruthy();
    await click(item);
    expect(latest[0].children.some(c => c.node_type === 'check')).toBe(true);
  });

  it('检查对象行的添加子项按钮禁用', async () => {
    const RowTreeEditor = require('../RowTreeEditor').default;
    await act(async () => {
      ReactDOM.render(
        <RowTreeEditor tree={[tree[0].children[0]]} onChange={() => {}}/>, container);
    });
    await act(flush);
    const plusButtons = Array.from(container.querySelectorAll('button.ant-btn-link'))
      .filter(b => b.querySelector('.anticon-plus'));
    expect(plusButtons).toHaveLength(1);
    expect(plusButtons[0].disabled).toBe(true);
  });

  it('第 5 级节点的添加子项按钮禁用（最多 5 级嵌套）', async () => {
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
