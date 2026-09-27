/**
 * 台账模板表单测试（可视化表格设计改版）。
 *
 * 一、录入类型收敛改由设计表格的列配置气泡承载（见 TemplateDesignTable.test.js），
 * 本文件聚焦模板表单装配与保存链路（真实渲染组件交互）：
 * - 三区块连续布局（基本信息 → 可视化设计表格 → 预览），无割裂页签；
 * - 检查对象/分组/列均在设计表格中添加：行内改名、列标题气泡配置；
 * - 行层级表头名称（如"信道"）在设计表格层级列头内联编辑，预览同步显示；
 * - 预览实时反映检查对象 × 检查项目交叉；
 * - 保存前校验（名称/检查对象/检查项目）并定位错误区块，不发起请求；
 * - 新建一次提交 row_headers + row_nodes + items（display_order 按列顺序）；
 *   编辑模式提交 row_headers 与检查项目，行结构走即时保存接口。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
}));

// import 会被提升到 mock 变量声明之前，组件须在 mock 就绪后 require
const loadForm = () => require('../TemplateForm').default;

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

// ==================== 真实渲染交互 ====================

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  document.body.innerHTML = '';
  [mockHttpGet, mockHttpPost, mockHttpPut].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function renderForm(store) {
  const TemplateForm = loadForm();
  await act(async () => {
    ReactDOM.render(<TemplateForm store={store}/>, container);
  });
  await act(flush);
}

async function click(el) {
  await act(async () => {
    el.click();
  });
  await act(flush);
}

function findButton(text) {
  return Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.includes(text));
}

function okButton() {
  return document.querySelector('.ant-modal-footer .ant-btn-primary');
}

/** 触发 React 受控 Input 的 onChange（原生 value setter + input 事件）。 */
function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', {bubbles: true}));
}

async function pickDropdownItem(triggerText, itemText) {
  await click(findButton(triggerText));
  const menuItem = Array.from(
    document.querySelectorAll('.ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item'))
    .find(el => el.textContent.trim() === itemText);
  expect(menuItem).toBeTruthy();
  await click(menuItem);
}

/** 打开第一列的配置气泡（点击列标题触发器）。 */
async function openColumnPopover() {
  await click(document.querySelector('.el-design-col-trigger'));
  const popover = document.querySelector('.ant-popover:not(.ant-popover-hidden)');
  expect(popover).toBeTruthy();
  return popover;
}

describe('TemplateForm 可视化设计布局', () => {
  it('三区块连续布局（无页签）：基本信息 → 可视化设计表格 → 预览', async () => {
    const store = {record: {}, formVisible: true, fetchRecords: jest.fn()};
    await renderForm(store);
    expect(document.body.textContent).toContain('1. 基本信息');
    expect(document.body.textContent).toContain('2. 可视化设计表格');
    expect(document.body.textContent).toContain('3. 预览');
    expect(document.querySelector('.ant-tabs')).toBeNull();
    // 设计表格工具栏：添加检查对象 / 添加分组 / 添加列
    expect(findButton('添加检查对象')).toBeTruthy();
    expect(findButton('添加分组')).toBeTruthy();
    expect(findButton('添加列')).toBeTruthy();
    // 空表：第 1 级层级表头列仍可编辑，数据区为空
    expect(document.querySelector('input[placeholder="第1级"]')).toBeTruthy();
  });

  it('新建简单模板：行与列都在设计表格中添加，列标题气泡配置，一次提交 row_headers + items + row_nodes', async () => {
    const store = {record: {}, formVisible: true, fetchRecords: jest.fn()};
    mockHttpPost.mockResolvedValue({});
    await renderForm(store);
    // 添加检查对象并命名
    await click(findButton('添加检查对象'));
    setInputValue(document.querySelector('input[placeholder="请输入名称"]'), '主电台');
    // 添加列并通过列标题气泡命名
    await click(findButton('添加列'));
    await openColumnPopover();
    setInputValue(document.querySelector('input[placeholder="请输入项目名称"]'), '外观检查');
    await act(flush);
    // 设计表格显示行 × 列交叉，层级表头可内联编辑
    setInputValue(document.querySelector('input[placeholder="第1级"]'), '信道');
    await act(flush);
    expect(document.body.textContent).toContain('主电台');
    expect(document.body.textContent).toContain('外观检查');
    // 填写模板名称后保存：一次 POST 同时携带表头、层级表头、检查项目与行结构
    setInputValue(document.querySelector('input[placeholder="请输入模板名称"]'), '周维护模板');
    await click(okButton());
    await act(flush);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledger-templates/',
      expect.objectContaining({
        name: '周维护模板',
        ledger_type: 'week_month',
        row_headers: ['信道'],
        row_nodes: [{name: '主电台', node_type: 'check', display_order: 0, children: []}],
        items: [expect.objectContaining({
          name: '外观检查', input_type: 'choice', is_required: true, display_order: 0,
        })],
      }));
    expect(store.formVisible).toBe(false);
    expect(store.fetchRecords).toHaveBeenCalled();
  });

  it('点击列标题打开配置气泡：包含录入类型/必填/单位/操作指导/异常规则/默认值', async () => {
    const store = {record: {}, formVisible: true, fetchRecords: jest.fn()};
    await renderForm(store);
    await click(findButton('添加列'));
    const popover = await openColumnPopover();
    expect(popover.textContent).toContain('项目名称');
    expect(popover.textContent).toContain('录入类型');
    expect(popover.textContent).toContain('必填');
    expect(popover.textContent).toContain('单位');
    expect(popover.textContent).toContain('操作指导');
    expect(popover.textContent).toContain('异常判定规则');
    expect(popover.textContent).toContain('默认值');
  });
});

describe('TemplateForm 保存与校验', () => {
  it('未配置检查对象/检查项目时不能保存：错误定位到设计表格区块且不发起请求', async () => {
    const store = {record: {}, formVisible: true, fetchRecords: jest.fn()};
    await renderForm(store);
    await click(okButton());
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(store.formVisible).toBe(true);
    expect(document.body.textContent).toContain('请填写模板名称');
    expect(document.body.textContent).toContain('请至少添加一个检查对象');
    expect(document.body.textContent).toContain('请至少添加一个检查项目');
  });

  it('只有分组没有检查对象时不能保存（分组不生成填写行）', async () => {
    const store = {record: {}, formVisible: true, fetchRecords: jest.fn()};
    mockHttpPost.mockResolvedValue({});
    await renderForm(store);
    await pickDropdownItem('添加分组', '分组');
    setInputValue(document.querySelector('input[placeholder="请输入名称"]'), '发信分组');
    setInputValue(document.querySelector('input[placeholder="请输入模板名称"]'), '分组模板');
    await click(findButton('添加列'));
    await openColumnPopover();
    setInputValue(document.querySelector('input[placeholder="请输入项目名称"]'), '外观检查');
    await click(okButton());
    await act(flush);
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('分组仅用于组织，不生成填写行');
    // 检查项目名称已填写，该项不再报错
    expect(document.body.textContent).not.toContain('请至少添加一个检查项目');
  });

  it('编辑模式：标注真实保存时机，保存提交层级表头与检查项目，行结构走即时接口', async () => {
    const store = {record: {id: 9}, formVisible: true, fetchRecords: jest.fn()};
    mockHttpGet.mockImplementation(url => {
      if (url.includes('row-nodes')) {
        return Promise.resolve({data: [{
          id: 1, name: '第1信道', node_type: 'repeat_group', parent: null,
          display_order: 0, is_active: true,
          children: [{id: 2, name: '主电台', node_type: 'check', parent: 1,
            display_order: 0, is_active: true}],
        }]});
      }
      return Promise.resolve({
        name: '信道模板', ledger_type: 'week_month', description: '',
        row_headers: ['信道'],
        items: [{id: 11, name: '外观检查', input_type: 'choice', unit: '',
          choices: ['正常', '不正常'], is_required: true}],
      });
    });
    mockHttpPut.mockResolvedValue({});
    await renderForm(store);
    // 各区块保存时机提示与实际机制一致
    expect(document.body.textContent).toContain('点击底部「保存基本信息」后保存');
    expect(document.body.textContent).toContain('行结构修改后立即保存');
    expect(okButton().textContent).toContain('保存基本信息');
    // 设计表格展示服务端行结构、层级表头与检查项目
    expect(document.body.textContent).toContain('第1信道');
    expect(document.body.textContent).toContain('外观检查');
    expect(document.querySelector('input[placeholder="第1级"]').value).toBe('信道');
    // 保存：PUT 表头（含层级表头）+ PUT 已有检查项目（display_order 重排），不重复提交行结构
    await click(okButton());
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledger-templates/9/',
      expect.objectContaining({name: '信道模板', row_headers: ['信道']}));
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledger-templates/9/items/11/',
      expect.objectContaining({name: '外观检查', display_order: 0}));
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(store.formVisible).toBe(false);
  });
});
