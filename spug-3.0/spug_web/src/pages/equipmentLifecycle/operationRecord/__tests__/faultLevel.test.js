/**
 * 运行处置记录——故障等级（fault_level）渲染契约测试（2026-10-23 新增字段）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 新增表单：设备故障渲染"故障等级"下拉（固定四级），一般记录/异常事件
 *   不渲染（故障专用字段显隐契约延伸）；
 * - 详情：设备故障概况区展示等级文本（未选择显示"-"），非故障记录不展示；
 * - 认定设备故障弹窗：选择等级后提交 identify-fault 端点真实携带
 *   fault_level（未选择提交空串）；
 * - 列表筛选栏（2026-10-23 筛选改造）：故障等级筛选项仅当记录类型选中
 *   "设备故障"后渲染，切换/清空类型即清除已选等级；列表请求真实携带
 *   fault_level（筛选由后端查询实现）；导出参数与范围文案同一口径；
 *   重置筛选清除等级。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

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
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  const AuthButton = (props) => React.createElement(
    'button', {onClick: props.onClick, type: 'button'}, props.children);
  const SearchForm = (props) => React.createElement('div', null, props.children);
  // 筛选项渲染 ant-form-item 结构（title 进 label），供按标签文案定位表单项
  SearchForm.Item = (props) => React.createElement(
    'div', {className: 'ant-form-item'},
    props.title ? React.createElement(
      'span', {className: 'ant-form-item-label'}, props.title) : null,
    props.children);
  return {
    AuthDiv: Shell,
    AuthButton,
    AuthCard: Shell,
    AuthFragment: Shell,
    Breadcrumb: Shell,
    SearchForm,
    ExportButton: (props) => React.createElement(
      'button', {type: 'button', 'data-export-params': JSON.stringify(props.params || {})},
      props.children),
    TableCard: Shell,
    AttachmentManager: (props) => React.createElement(
      'div', {'data-object-type': props.objectType}, 'attachments'),
    AttachmentCountBadge:
      jest.requireActual('components').AttachmentCountBadge,
  };
});

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
  mockHttpGet.mockReset();
  mockHttpGet.mockResolvedValue({data: [], total: 0});
  mockHttpPost.mockReset();
  mockHttpPost.mockResolvedValue({data: {}});
  mockHttpPut.mockReset();
  mockHttpPut.mockResolvedValue({data: {}});
  mockHttpDelete.mockReset();
  mockHttpDelete.mockResolvedValue({});
  // store 为模块级单例：跨测试重置可见性与详情状态，避免用例间泄入
  const store = require('../store').default;
  store.detailVisible = false;
  store.formVisible = false;
  store.detailId = null;
  store.detail = {};
  store.detailError = false;
  store.detailRequestSeq += 1;
  store.isDetailFetching = false;
  store.progressRecords = [];
  store.progressTotal = 0;
  store.attachments = [];
  store.attachmentsTotal = 0;
  store.attachmentsError = false;
  store.attachmentsExpanded = false;
  store.isAttachmentsFetching = false;
  store.attachmentRetrySeq = 0;
  store.pendingSection = 'basic';
  // 筛选条件为 store 单例字段：跨用例清空，避免等级筛选条件泄入
  store.records = [];
  store.systems = [];
  store.fetchError = false;
  store.input_keyword = '';
  store.f_keyword = undefined;
  store.f_status = undefined;
  store.f_system = undefined;
  store.f_category = undefined;
  store.f_record_type = undefined;
  store.f_fault_level = undefined;
  store.f_occurred_range = undefined;
  store.page = 1;
  store.pageSize = 20;
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-select-dropdown, .ant-message').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function textContent() {
  return document.body.textContent || '';
}

function findButton(label) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').trim() === label);
}

// 打开新增表单（Modal 挂载于 body portal）并渲染 RecordForm 组件本体
async function renderCreateForm() {
  const store = require('../store').default;
  const RecordForm = require('../RecordForm').default;
  await act(async () => {
    store.showForm();
  });
  await act(async () => {
    ReactDOM.render(React.createElement(RecordForm), container);
    await flush();
  });
}

// 通过遍历 Radio 切换记录类型（受控组件 onChange 双通道）
async function switchRecordType(label) {
  const radios = Array.from(document.querySelectorAll('.ant-radio-wrapper'));
  const target = radios.find(r => r.textContent === label);
  await act(async () => {
    target.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

// 展开指定 Form.Item 内的 Select 下拉，返回已显示的下拉选项文本数组
async function openSelectOptions(formItem) {
  const selector = formItem.querySelector('.ant-select-selector');
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    await flush();
  });
  const dropdown = document.querySelector(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
  expect(dropdown).toBeTruthy();
  return Array.from(dropdown.querySelectorAll('.ant-select-item-option'))
    .map(option => (option.textContent || '').trim());
}

// 按标签文案定位表单项（如 "故障等级"）
function findFormItem(label) {
  return Array.from(document.querySelectorAll('.ant-form-item'))
    .find(item => Array.from(item.querySelectorAll('.ant-form-item-label'))
      .some(labelNode => (labelNode.textContent || '').trim() === label));
}

// 在指定容器（表单项/弹窗）内点选下拉选项（rc-select：mousedown 防焦 + click 选中）
async function pickOption(scope, optionText) {
  const selector = scope.querySelector('.ant-select-selector');
  const dropdown = () => document.querySelector(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    await flush();
  });
  const option = Array.from(dropdown().querySelectorAll('.ant-select-item-option'))
    .find(node => (node.textContent || '').trim() === optionText);
  expect(option).toBeTruthy();
  await act(async () => {
    option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

describe('新增表单故障专用字段显隐（故障等级）', () => {
  it('设备故障：渲染故障等级下拉，固定四级选项', async () => {
    await renderCreateForm();
    await switchRecordType('设备故障');
    const item = findFormItem('故障等级');
    expect(item).toBeTruthy();
    const options = await openSelectOptions(item);
    expect(options).toEqual(['一级', '二级', '三级', '四级']);
  });

  it('一般记录：不渲染故障等级', async () => {
    await renderCreateForm();
    await switchRecordType('一般记录');
    expect(findFormItem('故障等级')).toBeUndefined();
  });

  it('异常事件：不渲染故障等级', async () => {
    await renderCreateForm();
    await switchRecordType('异常事件');
    expect(findFormItem('故障等级')).toBeUndefined();
  });
});

const FAULT_DETAIL = {
  id: 11, record_no: 'JL20261023-0001', record_type: 'fault',
  system: 3, system_name: 'DVOR系统', system_location: '机房A',
  occurred_at: '2026-10-23 08:00:00', title: '发射机故障',
  description: '告警灯亮', registrar_name: '张三', status: 'handling',
  affects_system_operation: true, impact_status: 'fault',
  fault_level: 'level2', reason_analysis: '', reason_unknown: false,
  source_type: 'manual', source_ledger: null, source_ledger_no: '',
  progress_count: 0, created_by_name: 'op_user',
  latest_progress_at: '2026-10-23 10:30:00', duration_seconds: 9000,
};

const ABNORMAL_DETAIL = {
  ...FAULT_DETAIL,
  id: 12, record_no: 'JL20261023-0002', record_type: 'abnormal',
  title: '信号波动', status: 'recorded', affects_system_operation: false,
  impact_status: '', fault_level: '',
};

async function renderDetail(detail) {
  mockHttpGet.mockImplementation((url) => {
    if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 0});
    if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
    return Promise.resolve(detail);
  });
  const store = require('../store').default;
  const RecordDetail = require('../RecordDetail').default;
  await act(async () => {
    store.showDetail(detail.id);
  });
  await act(async () => {
    ReactDOM.render(React.createElement(RecordDetail), container);
  });
  await act(async () => {
    await flush();
  });
}

describe('详情概况区故障等级展示', () => {
  it('设备故障：展示等级文本', async () => {
    await renderDetail(FAULT_DETAIL);
    const text = textContent();
    expect(text).toContain('故障等级');
    expect(text).toContain('二级');
  });

  it('设备故障未选择等级：展示占位"-"', async () => {
    await renderDetail({...FAULT_DETAIL, fault_level: ''});
    const text = textContent();
    expect(text).toContain('故障等级');
    expect(text).not.toContain('二级');
  });

  it('异常事件：不展示故障等级', async () => {
    await renderDetail(ABNORMAL_DETAIL);
    expect(textContent()).not.toContain('故障等级');
  });
});

describe('认定设备故障弹窗携带故障等级', () => {
  it('选择等级后提交 identify-fault 真实携带 fault_level', async () => {
    await renderDetail(ABNORMAL_DETAIL);
    const button = findButton('认定设备故障');
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const modal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('在本条记录上认定为设备故障'));
    expect(modal).toBeTruthy();
    await pickOption(modal, '一级');
    await act(async () => {
      const ok = modal.querySelector('.ant-modal-footer .ant-btn-primary');
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/12/identify-fault/',
      expect.objectContaining({fault_level: 'level1'}));
  });

  it('未选择等级提交：fault_level 为空串（未选择语义）', async () => {
    await renderDetail(ABNORMAL_DETAIL);
    const button = findButton('认定设备故障');
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const modal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('在本条记录上认定为设备故障'));
    await act(async () => {
      const ok = modal.querySelector('.ant-modal-footer .ant-btn-primary');
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/12/identify-fault/',
      expect.objectContaining({fault_level: ''}));
  });
});

// ========== 列表筛选栏故障等级联动（2026-10-23 筛选改造） ==========

const LIST_URL = '/api/equipment-lifecycle/records/';

// 渲染记录中心页（与 components.test.js 同款：location.search 传空）
async function renderIndex() {
  const RecordIndex = require('../index').default;
  await act(async () => {
    ReactDOM.render(
      React.createElement(RecordIndex, {location: {search: ''}}), container);
  });
  await act(async () => {
    await flush();
  });
}

// 展开筛选区"更多筛选"（高级条件默认折叠）
async function openAdvancedFilters() {
  const link = Array.from(document.querySelectorAll('a'))
    .find(a => (a.textContent || '').includes('更多筛选'));
  expect(link).toBeTruthy();
  await act(async () => {
    link.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

// 最近一次列表请求的查询参数
function lastListParams() {
  const calls = mockHttpGet.mock.calls.filter(([url]) => url === LIST_URL);
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][1].params;
}

describe('列表筛选栏故障等级联动', () => {
  it('默认不渲染故障等级筛选项，选中设备故障类型后才渲染（固定四级）', async () => {
    await renderIndex();
    await openAdvancedFilters();
    expect(findFormItem('记录类型')).toBeTruthy();
    expect(findFormItem('故障等级')).toBeUndefined();
    await pickOption(findFormItem('记录类型'), '设备故障');
    const item = findFormItem('故障等级');
    expect(item).toBeTruthy();
    const options = await openSelectOptions(item);
    expect(options).toEqual(['一级', '二级', '三级', '四级']);
  });

  it('选择等级后列表请求真实携带 fault_level（后端筛选口径）', async () => {
    await renderIndex();
    await openAdvancedFilters();
    await pickOption(findFormItem('记录类型'), '设备故障');
    await pickOption(findFormItem('故障等级'), '二级');
    const params = lastListParams();
    expect(params.fault_level).toBe('level2');
    expect(params.record_type).toBe('fault');
  });

  it('切换到其他记录类型：筛选项消失且已选等级被清除', async () => {
    await renderIndex();
    await openAdvancedFilters();
    await pickOption(findFormItem('记录类型'), '设备故障');
    await pickOption(findFormItem('故障等级'), '二级');
    const store = require('../store').default;
    expect(store.f_fault_level).toBe('level2');
    await pickOption(findFormItem('记录类型'), '一般记录');
    expect(findFormItem('故障等级')).toBeUndefined();
    expect(store.f_fault_level).toBeUndefined();
    // 清除后的列表请求不再携带 fault_level（无隐藏残留条件）
    expect(lastListParams().fault_level).toBeUndefined();
  });

  it('清空记录类型：已选等级被清除', async () => {
    await renderIndex();
    await openAdvancedFilters();
    await pickOption(findFormItem('记录类型'), '设备故障');
    await pickOption(findFormItem('故障等级'), '三级');
    // antd 4 Select 清空图标的动作绑定在 mousedown（非 click），派发后
    // React 重渲染替换节点，重新查询后再派发
    const typeItem = findFormItem('记录类型');
    const clear = typeItem.querySelector('.ant-select-clear');
    expect(clear).toBeTruthy();
    await act(async () => {
      clear.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      await flush();
    });
    expect(findFormItem('故障等级')).toBeUndefined();
    const store = require('../store').default;
    expect(store.f_record_type).toBeUndefined();
    expect(store.f_fault_level).toBeUndefined();
    expect(lastListParams().fault_level).toBeUndefined();
  });
});

describe('故障等级筛选导出与重置口径', () => {
  it('getExportParams 携带 fault_level，导出范围文案逐项说明', () => {
    const store = require('../store').default;
    store.f_record_type = 'fault';
    store.f_fault_level = 'level2';
    expect(store.getExportParams()).toEqual(
      {record_type: 'fault', fault_level: 'level2'});
    expect(store.exportScopeText).toContain('故障等级「二级」');
    // 未选等级时文案与参数不出现等级项
    store.f_fault_level = undefined;
    expect(store.getExportParams()).toEqual({record_type: 'fault'});
    expect(store.exportScopeText).not.toContain('故障等级');
  });

  it('重置筛选清除故障等级条件', () => {
    const store = require('../store').default;
    store.f_record_type = 'fault';
    store.f_fault_level = 'level1';
    store.resetFilter();
    expect(store.f_record_type).toBeUndefined();
    expect(store.f_fault_level).toBeUndefined();
    expect(store.hasActiveFilter).toBe(false);
  });

  it('hasActiveFilter 计入故障等级（折叠计数口径）', () => {
    const store = require('../store').default;
    store.f_fault_level = 'level3';
    expect(store.hasActiveFilter).toBe(true);
  });
});
