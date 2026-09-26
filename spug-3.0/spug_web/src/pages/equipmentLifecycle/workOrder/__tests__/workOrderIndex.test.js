/**
 * 工单管理列表页——新增/编辑表单打开链路回归测试（真实渲染 ReactDOM + jsdom）。
 *
 * 背景缺陷（2026-09-19）：index.js 以 {store.formVisible && <ComForm/>} 条件渲染
 * WorkOrderForm，但该组件是受控组件（visible/onClose props），未传 props 时
 * Modal visible=undefined，点击"新增工单"后弹窗永不出现；且组件未包 observer，
 * 候选系统异步返回后下拉不会刷新。
 *
 * 验证：
 * - 点击"新增工单"按钮后 Modal 真实打开（标题"新增工单"），并拉取候选系统
 * - 点击弹窗关闭按钮后弹窗收起
 * - 执行中工单点击"编辑"后打开"编辑工单"弹窗并回填标题（先取详情再打开）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const {Button: AntButton} = require('antd');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  // AuthButton 真实实现是权限包装的 antd Button：mock 须保留 Button 行为（onClick/文本），仅剥掉 auth 属性
  const AuthButton = ({auth, ...rest}) => React.createElement(AntButton, rest);
  const SearchForm = (props) => React.createElement('div', null, props.children);
  SearchForm.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell,
    AuthButton,
    AuthCard: Shell,
    AuthFragment: Shell,
    Breadcrumb,
    SearchForm,
    ExportButton: AuthButton,
    TableCard: Shell,
  };
});

// jsdom 未实现 matchMedia，antd 渲染需要
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
  // store 是模块级单例，清掉用例间状态
  const store = require('../store').default;
  store.formVisible = false;
  store.record = {};
  store.detailVisible = false;
  store.detailId = null;
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {});
}

const storeModule = require('../store');
const WorkOrderIndex = require('../index').default;

const LIST_PAYLOAD = {
  data: [{
    id: 5,
    work_no: 'WO20260919-0001',
    title: '主用链路抢修',
    work_type: 'special_maintenance',
    maintenance_subtype: 'field_test',
    priority: 'high',
    status: 'executing',
    source_type: 'manual',
    system_name: '烟台通信系统',
    system_code: 'SYS-A1',
    owner_name: '',
    planned_start: '',
  }],
  total: 1, page: 1, page_size: 20,
};

const DETAIL_PAYLOAD = {
  id: 5,
  work_no: 'WO20260919-0001',
  title: '主用链路抢修',
  work_type: 'repair',
  priority: 'high',
  status: 'executing',
  system: 7,
  system_name: '烟台通信系统',
  system_code: 'SYS-A1',
  affects_system_operation: false,
  participants: [],
};

const CANDIDATE_SYSTEMS = {
  data: [{id: 7, name: '烟台通信系统', system_code: 'SYS-A1'}],
};

function mockDefaults() {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/candidate-systems/')) return Promise.resolve(CANDIDATE_SYSTEMS);
    if (url.includes('/candidate-users/')) return Promise.resolve({data: []});
    if (/\/work-orders\/5\/$/.test(url)) return Promise.resolve(DETAIL_PAYLOAD);
    return Promise.resolve(LIST_PAYLOAD);
  });
}

async function renderPage() {
  mockDefaults();
  await act(async () => {
    ReactDOM.render(h(WorkOrderIndex), container);
  });
  await act(async () => {});
}

function findButtonByText(text) {
  return Array.from(container.querySelectorAll('button'))
    .find(btn => btn.textContent.replace(/\s+/g, '') === text);
}

describe('工单新增/编辑表单打开链路', () => {
  test('列表展示工单类型与维护分类列（专项维护行）', async () => {
    await renderPage();
    const text = container.textContent;
    expect(text).toContain('专项维护');
    expect(text).toContain('维护分类');
    expect(text).toContain('现场测试');
  });

  test('点击"新增工单"按钮后弹窗真实打开并拉取候选系统', async () => {
    await renderPage();
    expect(document.querySelector('.ant-modal-title')).toBeNull();
    const addBtn = findButtonByText('新增工单');
    expect(addBtn).toBeTruthy();
    await click(addBtn);
    await act(async () => {});
    const modalTitle = document.querySelector('.ant-modal-title');
    expect(modalTitle).not.toBeNull();
    expect(modalTitle.textContent).toContain('新增工单');
    const sysCall = mockHttpGet.mock.calls.find(c => c[0].includes('/candidate-systems/'));
    expect(sysCall).toBeTruthy();
    expect(storeModule.default.systems.length).toBe(1);
  });

  test('点击弹窗关闭按钮后弹窗收起', async () => {
    await renderPage();
    await click(findButtonByText('新增工单'));
    expect(document.querySelector('.ant-modal-title')).not.toBeNull();
    const closeBtn = document.querySelector('.ant-modal-close');
    expect(closeBtn).not.toBeNull();
    await click(closeBtn);
    expect(document.querySelector('.ant-modal-title')).toBeNull();
  });

  test('执行中工单点击"编辑"后打开编辑弹窗并回填标题', async () => {
    await renderPage();
    const editBtn = findButtonByText('编辑');
    expect(editBtn).toBeTruthy();
    await click(editBtn);
    await act(async () => {});
    const modalTitle = document.querySelector('.ant-modal-title');
    expect(modalTitle).not.toBeNull();
    expect(modalTitle.textContent).toContain('编辑工单');
    const titleInput = document.querySelector('.ant-modal-body input');
    expect(titleInput).not.toBeNull();
    expect(titleInput.value).toBe('主用链路抢修');
    const detailCall = mockHttpGet.mock.calls.find(c => /\/work-orders\/5\/$/.test(c[0]));
    expect(detailCall).toBeTruthy();
  });
});
