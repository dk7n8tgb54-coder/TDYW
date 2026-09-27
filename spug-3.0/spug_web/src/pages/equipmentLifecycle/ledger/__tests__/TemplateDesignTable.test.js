/**
 * 台账模板可视化设计表格测试（真实渲染组件交互）。
 *
 * - 行结构操作在表格内完成：添加检查对象/分组（工具栏）、添加子行/同级行
 *   （行内下拉）、同级排序（上移/下移）、停用/启用、删除（本地草稿）；
 * - 第 5 级与检查对象行禁用"添加子行"；
 * - 列项目：工具栏"添加列"，点击列标题弹出配置气泡（名称/录入类型/必填/
 *   单位/操作指导/异常规则/默认值 + 排序/停用/删除）；
 * - 录入类型收敛（沿用原表单套件口径）：仅 正常/不正常 与 数字/文本 两种，
 *   历史类型仅回显；切换类型清掉不再适用字段，候选项固定；
 * - 行层级表头名称（如"信道"）在层级列头内联编辑；
 * - 远端模式（编辑模板）：行动作经 onCommit 提交后端，不改本地树。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
}));

import {makeEmptyColumn, designRows, insertSiblingAfter} from '../TemplateDesignTable';
import {typePatch} from '../ColumnConfigPopover';

const loadDesignTable = () => require('../TemplateDesignTable').default;

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;
let onChange = null;
let onItemsChange = null;
let onRowHeadersChange = null;
let onCommit = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  onChange = jest.fn();
  onItemsChange = jest.fn();
  onRowHeadersChange = jest.fn();
  onCommit = jest.fn();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  document.body.innerHTML = '';
  mockHttpGet.mockReset();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function renderTable(props) {
  const TemplateDesignTable = loadDesignTable();
  const merged = {
    tree: [], items: [], rowHeaders: [],
    onChange, onItemsChange, onRowHeadersChange, onCommit,
    ...props,
  };
  await act(async () => {
    ReactDOM.render(<TemplateDesignTable {...merged}/>, container);
  });
  await act(flush);
}

async function click(el) {
  await act(async () => {
    el.click();
  });
  await act(flush);
}

function findButtonByText(text) {
  return Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.includes(text));
}

function findButtonByClass(cls) {
  return document.querySelector(`.${cls}`);
}

function allButtonsByClass(cls) {
  return Array.from(document.querySelectorAll(`.${cls}`));
}

/** 点击下拉触发按钮后点击弹出菜单中的指定项（仅可见浮层，精确匹配）。 */
async function pickDropdownItem(triggerEl, itemText) {
  await click(triggerEl);
  const menuItem = Array.from(
    document.querySelectorAll('.ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item'))
    .find(el => el.textContent.trim() === itemText);
  expect(menuItem).toBeTruthy();
  await click(menuItem);
}

/** 确认当前可见的 Popconfirm（antd 默认英文语言包，主按钮为 OK）。 */
async function confirmPopconfirm() {
  const ok = Array.from(document.querySelectorAll(
    '.ant-popover:not(.ant-popover-hidden) .ant-btn-primary')).pop();
  expect(ok).toBeTruthy();
  await click(ok);
}

/** 打开 antd Select（4.x 监听 .ant-select-selector 的 mousedown 而非 click）。 */
async function openSelect(rootEl) {
  await act(async () => {
    rootEl.querySelector('.ant-select-selector')
      .dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
  });
  await act(flush);
}

/** 取最后一个未隐藏下拉（先开过的下拉关闭动画未结束时会残留 DOM）。 */
function visibleSelectOptions() {
  const dropdowns = Array.from(document.querySelectorAll(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden)'));
  expect(dropdowns.length).toBeGreaterThan(0);
  return Array.from(dropdowns[dropdowns.length - 1].querySelectorAll('.ant-select-item'));
}

async function openColumnPopover() {
  await click(document.querySelector('.el-design-col-trigger'));
  const popover = document.querySelector('.ant-popover:not(.ant-popover-hidden)');
  expect(popover).toBeTruthy();
  return popover;
}

/** 触发 React 受控 Input 的 onChange（原生 value setter + input 事件）。 */
function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', {bubbles: true}));
}

function node(name, nodeType, children = []) {
  return {key: `k_${name}`, id: undefined, name, node_type: nodeType,
    is_active: true, children};
}

// ==================== 行结构操作 ====================

describe('TemplateDesignTable 行结构操作', () => {
  it('添加检查对象：本地树新增 check 根节点', async () => {
    await renderTable({});
    await click(findButtonByText('添加检查对象'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const tree = onChange.mock.calls[0][0];
    expect(tree).toHaveLength(1);
    expect(tree[0].node_type).toBe('check');
  });

  it('添加分组：下拉选择可重复分组', async () => {
    await renderTable({});
    await pickDropdownItem(findButtonByText('添加分组'), '可重复分组');
    const tree = onChange.mock.calls[0][0];
    expect(tree[0].node_type).toBe('repeat_group');
  });

  it('行内添加子行：下拉选择检查对象挂到分组之下', async () => {
    await renderTable({tree: [node('信道', 'repeat_group')]});
    await pickDropdownItem(findButtonByClass('el-ra-child'), '检查对象');
    const tree = onChange.mock.calls[0][0];
    expect(tree[0].children).toHaveLength(1);
    expect(tree[0].children[0].node_type).toBe('check');
  });

  it('行内添加同级行：插入到当前行之后（含嵌套层级）', async () => {
    await renderTable({tree: [
      node('第1信道', 'repeat_group', [node('主电台', 'check')]),
      node('第2信道', 'repeat_group'),
    ]});
    // 第1信道行内的"添加同级行"：新节点出现在其后、第2信道之前
    await pickDropdownItem(allButtonsByClass('el-ra-sibling')[0], '分组');
    const tree = onChange.mock.calls[0][0];
    expect(tree).toHaveLength(3);
    expect(tree[0].name).toBe('第1信道');
    expect(tree[1].name).toBe('');
    expect(tree[2].name).toBe('第2信道');
  });

  it('insertSiblingAfter 纯函数：嵌套子行插入到目标之后', () => {
    const tree = [node('信道', 'repeat_group', [node('主电台', 'check'), node('备电台', 'check')])];
    const next = insertSiblingAfter(tree, 'k_主电台', {key: 'new'});
    expect(next[0].children.map(n => n.key)).toEqual(['k_主电台', 'new', 'k_备电台']);
  });

  it('上移/下移：同级排序', async () => {
    await renderTable({tree: [node('甲', 'check'), node('乙', 'check'), node('丙', 'check')]});
    // 乙行上移 → 甲乙交换
    await click(allButtonsByClass('el-ra-up')[1]);
    expect(onChange.mock.calls[0][0].map(n => n.name)).toEqual(['乙', '甲', '丙']);
    // 甲行下移 → 甲乙交换
    await click(allButtonsByClass('el-ra-down')[0]);
    expect(onChange.mock.calls[1][0].map(n => n.name)).toEqual(['乙', '甲', '丙']);
  });

  it('停用/启用：本地直接更新 is_active', async () => {
    await renderTable({tree: [node('主电台', 'check')]});
    await click(findButtonByClass('el-ra-toggle'));
    await confirmPopconfirm();
    expect(onChange.mock.calls[0][0][0].is_active).toBe(false);
  });

  it('删除：仅本地模式提供，删除节点及其子树', async () => {
    await renderTable({tree: [node('信道', 'repeat_group', [node('主电台', 'check')])]});
    await click(findButtonByClass('el-ra-delete'));
    await confirmPopconfirm();
    expect(onChange.mock.calls[0][0]).toHaveLength(0);
  });

  it('检查对象行的"添加子行"按钮禁用', async () => {
    await renderTable({tree: [node('主电台', 'check')]});
    // antd Tooltip 会把禁用按钮包进兼容层 span，类名随之落在包装层
    const trigger = findButtonByClass('el-ra-child');
    expect(trigger).toBeTruthy();
    const button = trigger.tagName === 'BUTTON' ? trigger : trigger.querySelector('button');
    expect(button.disabled).toBe(true);
  });

  it('designRows：标注 depth/path/isCellLeaf，供矩阵渲染', () => {
    const rows = designRows([node('信道', 'repeat_group', [node('主电台', 'check')])]);
    expect(rows[0].depth).toBe(1);
    expect(rows[0].isCellLeaf).toBe(false);
    expect(rows[0].children[0].depth).toBe(2);
    expect(rows[0].children[0].isCellLeaf).toBe(true);
    expect(rows[0].children[0].path).toBe('信道 / 主电台');
  });
});

// ==================== 列项目与层级表头 ====================

describe('TemplateDesignTable 列项目与层级表头', () => {
  it('添加列：追加默认草稿（正常/不正常、必填）', async () => {
    await renderTable({});
    await click(findButtonByText('添加列'));
    expect(onItemsChange).toHaveBeenCalledTimes(1);
    const items = onItemsChange.mock.calls[0][0];
    expect(items).toHaveLength(1);
    expect(items[0].input_type).toBe('choice');
    expect(items[0].choices).toEqual(['正常', '不正常']);
    expect(items[0].is_required).toBe(true);
  });

  it('点击列标题弹出配置气泡，修改项目名称回传', async () => {
    await renderTable({items: [{...makeEmptyColumn(), name: ''}]});
    const popover = await openColumnPopover();
    expect(popover.textContent).toContain('录入类型');
    setInputValue(popover.querySelector('input[placeholder="请输入项目名称"]'), '外观检查');
    expect(onItemsChange).toHaveBeenCalled();
    expect(onItemsChange.mock.calls[0][0][0].name).toBe('外观检查');
  });

  it('录入类型仅两种选项，历史类型仅回显', async () => {
    await renderTable({items: [{...makeEmptyColumn()}]});
    // choice 列：下拉仅 正常/不正常 与 数字/文本
    const popover = await openColumnPopover();
    await openSelect(popover.querySelector('.ant-select'));
    expect(visibleSelectOptions().map(el => el.textContent))
      .toEqual(['正常/不正常', '数字/文本']);
  });

  it('录入类型历史类型仅回显（multi_choice 追加历史选项）', async () => {
    await renderTable({items: [
      {...makeEmptyColumn(), input_type: 'multi_choice', choices: ['主用', '备用']},
    ]});
    const popover = await openColumnPopover();
    await openSelect(popover.querySelector('.ant-select'));
    expect(visibleSelectOptions().map(el => el.textContent))
      .toEqual(['正常/不正常', '数字/文本', '多选（历史）']);
  });

  it('typePatch：切换类型清掉不再适用字段，数字/文本保留单位，候选项固定', () => {
    expect(typePatch('choice')).toEqual({
      input_type: 'choice', unit: '', choices: ['正常', '不正常']});
    // 数字/文本保留已填单位，仅清候选项
    expect(typePatch('text')).toEqual({
      input_type: 'text', choices: []});
  });

  it('配置气泡内停用列（本地草稿）', async () => {
    await renderTable({items: [makeEmptyColumn()]});
    const popover = await openColumnPopover();
    await click(Array.from(popover.querySelectorAll('button'))
      .find(b => b.textContent.includes('停用')));
    await confirmPopconfirm();
    expect(onItemsChange).toHaveBeenCalled();
    expect(onItemsChange.mock.calls[0][0][0].is_active).toBe(false);
  });

  it('配置气泡内删除列（仅本地草稿提供）', async () => {
    await renderTable({items: [makeEmptyColumn()]});
    const popover = await openColumnPopover();
    await click(popover.querySelector('button[title="删除"]'));
    await confirmPopconfirm();
    expect(onItemsChange).toHaveBeenCalled();
    expect(onItemsChange.mock.calls[0][0]).toHaveLength(0);
  });

  it('配置气泡内上移/下移列', async () => {
    await renderTable({items: [makeEmptyColumn(), {...makeEmptyColumn(), name: '第二列'}]});
    // 第二列标题触发器为第 2 个，打开其气泡并上移
    await click(allButtonsByClass('el-design-col-trigger')[1]);
    const popover = document.querySelector('.ant-popover:not(.ant-popover-hidden)');
    await click(popover.querySelector('button[title="上移"]'));
    const items = onItemsChange.mock.calls[0][0];
    expect(items).toHaveLength(2);
    expect(items[0].name).toBe('第二列');
  });

  it('层级表头名称内联编辑：第 1 级输入"信道"', async () => {
    await renderTable({});
    setInputValue(document.querySelector('input[placeholder="第1级"]'), '信道');
    expect(onRowHeadersChange).toHaveBeenCalledWith(['信道']);
  });
});

// ==================== 远端模式（编辑模板） ====================

describe('TemplateDesignTable 远端模式', () => {
  const serverTree = [
    {key: 'srv1', id: 1, name: '第1信道', node_type: 'repeat_group',
      is_active: true, children: []},
  ];

  it('行内添加子行：不改动本地树，经 onCommit 提交 create', async () => {
    await renderTable({tree: serverTree, remote: true});
    await pickDropdownItem(findButtonByClass('el-ra-child'), '检查对象');
    expect(onChange).not.toHaveBeenCalled();
    expect(onCommit).toHaveBeenCalledTimes(1);
    const action = onCommit.mock.calls[0][0];
    expect(action.type).toBe('create');
    expect(action.parent && action.parent.id).toBe(1);
    expect(action.payload).toEqual({name: '新检查对象', node_type: 'check'});
  });

  it('添加同级行：远端以父节点（根级为 null）提交 create，追加后可手动排序', async () => {
    await renderTable({tree: serverTree, remote: true});
    await pickDropdownItem(findButtonByClass('el-ra-sibling'), '分组');
    expect(onCommit).toHaveBeenCalledTimes(1);
    const action = onCommit.mock.calls[0][0];
    expect(action.type).toBe('create');
    expect(action.parent).toBeNull();
    expect(action.payload).toEqual({name: '新分组', node_type: 'group'});
  });

  it('上移/下移：本地树即时交换并提交 sort', async () => {
    await renderTable({tree: [node('甲', 'check'), node('乙', 'check')], remote: true});
    await click(allButtonsByClass('el-ra-up')[1]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({type: 'sort', parent: null,
      orderedKeys: ['k_乙', 'k_甲']});
  });

  it('停用：远端经 onCommit 提交 toggle，本地树不动', async () => {
    await renderTable({tree: serverTree, remote: true});
    await click(findButtonByClass('el-ra-toggle'));
    await confirmPopconfirm();
    expect(onChange).not.toHaveBeenCalled();
    expect(onCommit).toHaveBeenCalledTimes(1);
    const action = onCommit.mock.calls[0][0];
    expect(action.type).toBe('toggle');
    expect(action.node.id).toBe(1);
    expect(action.node.is_active).toBe(false);
  });

  it('远端模式不提供删除按钮（以停用代替）', async () => {
    await renderTable({tree: serverTree, remote: true});
    expect(findButtonByClass('el-ra-delete')).toBeNull();
  });

  it('远端模式已保存列不提供删除入口（仅停用）', async () => {
    await renderTable({tree: [], items: [{...makeEmptyColumn(), id: 11}], remote: true});
    const popover = await openColumnPopover();
    expect(popover.querySelector('button[title="删除"]')).toBeNull();
    expect(Array.from(popover.querySelectorAll('button'))
      .some(b => b.textContent.includes('停用'))).toBe(true);
  });
});
