/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行记录 record_type（2026-10-07）组件渲染与请求行为测试。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 表单：日常运行（默认）显示 作业内容/操作结果检查结果，提交携带
 *   record_type=routine；异常事件显示 异常类别口径，提交携带
 *   record_type=abnormal（"关联日常运行"功能已于同日按用户决策整体移除）；
 * - 编辑模式记录类型 Radio 禁用（创建后不可修改），编辑提交不携带
 *   record_type 键；
 * - 列表：记录类型列渲染 + 记录类型筛选参数随查询发送；
 * - 详情：日常运行显示"日常运行"标签/作业内容/操作结果/删除按钮，
 *   不渲染 开始跟进/新增跟进记录/完成跟进/转为正式故障 等异常操作，
 *   无处理进展页签；异常事件保留全部异常操作；
 * - 删除：确认后调用 DELETE 端点并刷新列表；
 * - store：deleteRecord/fetchRecords(record_type)/fetchStatistics(record_type)。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
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

function bodyText() {
  return document.body.textContent.replace(/\s+/g, '');
}

function buttonTexts() {
  return Array.from(document.querySelectorAll('button'))
    .filter(b => !b.closest('.ant-modal-footer'))
    .map(b => b.textContent.replace(/\s+/g, ''));
}

function clickButtonByText(text) {
  const buttons = Array.from(document.querySelectorAll('button'))
    .filter(b => b.textContent.replace(/\s+/g, '').includes(text) && !b.disabled);
  if (!buttons.length) throw new Error(`button not found: ${text}`);
  buttons[0].click();
}

function clickModalOk() {
  const ok = Array.from(document.querySelectorAll('.ant-modal button'))
    .find(b => /^ok|确定$/i.test(b.textContent.replace(/\s+/g, '')) && !b.disabled);
  if (!ok) throw new Error('modal ok button not found');
  ok.click();
}

// —— 以下交互助手与故障模块测试同款（真实用户路径，jsdom 已验证） ——
function findFormItem(labelText) {
  const items = Array.from(document.querySelectorAll('.ant-modal .ant-form-item'));
  return items.find(n => {
    const label = n.querySelector('.ant-form-item-label');
    return label && label.textContent.includes(labelText);
  }) || null;
}

async function setTextareaValue(label, value) {
  const textarea = findFormItem(label).querySelector('textarea');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

async function setInputValue(label, value) {
  const input = findFormItem(label).querySelector('input');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

async function typeAndEnter(formLabel, text) {
  const input = findFormItem(formLabel).querySelector('.ant-select input');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, text);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {await flush();});
  await act(async () => {
    const ev = new KeyboardEvent('keydown', {key: 'Enter', bubbles: true});
    Object.defineProperty(ev, 'keyCode', {get: () => 13});
    Object.defineProperty(ev, 'which', {get: () => 13});
    input.dispatchEvent(ev);
  });
  await act(async () => {await flush();});
}

async function selectOption(formLabel, optionText) {
  const selector = findFormItem(formLabel).querySelector('.ant-select-selector');
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
  });
  await act(async () => {await flush();});
  const option = Array.from(document.querySelectorAll(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option'))
    .find(o => o.textContent.includes(optionText));
  await act(async () => {
    option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

async function setPickerValue(label) {
  const input = findFormItem(label).querySelector('input');
  await act(async () => {
    input.focus();
    input.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
  });
  await act(async () => {await flush();});
  const cell = document.querySelector(
    '.ant-picker-dropdown:not(.ant-picker-dropdown-hidden) ' +
    '.ant-picker-cell-in-view:not(.ant-picker-cell-disabled)');
  expect(cell).toBeTruthy();
  await act(async () => {
    cell.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
  const okButton = document.querySelector(
    '.ant-picker-dropdown:not(.ant-picker-dropdown-hidden) .ant-picker-ok button');
  if (okButton) {
    await act(async () => {
      okButton.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
  }
}

const SYSTEMS = [
  {id: 1, system_code: 'SYS-A1', name: '烟台通信系统', install_location: '机房A'},
];

const ROUTINE_RECORD = {
  id: 21, record_no: 'YX20261007-0001', system: 1,
  record_type: 'routine', record_type_text: '日常运行',
  system_name: '烟台通信系统', system_code: 'SYS-A1', system_location: '机房A',
  occurred_at: '2026-10-07 08:30', title: 'UPS电源切换及南山UPS电池检查紧固',
  description: '航后按计划完成UPS电源切换与电池检查',
  registrar_name: '李四',
  status: 'recorded', status_text: '已记录',
  needs_follow_up: false,
  measures_taken: '切换UPS电源并紧固南山UPS电池连接端子',
  handling_result: '作业完成，UPS切换正常，电池端子无松动',
  converted_fault: null, converted_fault_no: '',
  created_by_name: 'admin', created_at: '2026-10-07 08:35',
};

const ABNORMAL_RECORD = {
  id: 22, record_no: 'YX20261007-0002', system: 1,
  record_type: 'abnormal', record_type_text: '异常事件',
  system_name: '烟台通信系统', system_code: 'SYS-A1', system_location: '机房A',
  occurred_at: '2026-10-07 09:00', title: '120.85主、121.5主、130主电台交流电源故障',
  description: '值班发现多部主用电台交流电源无输出',
  registrar_name: '张三',
  status: 'recorded', status_text: '已记录',
  needs_follow_up: false,
  measures_taken: '', handling_result: '',
  converted_fault: null, converted_fault_no: '',
  created_by_name: 'admin', created_at: '2026-10-07 09:05',
};

function mockListApis(detailResponse) {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/candidate-systems')) return Promise.resolve({data: SYSTEMS});
    if (url.includes('/progress/')) return Promise.resolve({data: [], total: 0});
    if (url.includes('/attachments/')) return Promise.resolve({data: []});
    if (url.includes('/record_type=routine') || url.includes('record_type=routine')) {
      return Promise.resolve({data: [ROUTINE_RECORD], total: 1});
    }
    if (/\/runtime-records\/\d+\/$/.test(url)) {
      return Promise.resolve(detailResponse || ABNORMAL_RECORD);
    }
    if (url.includes('/statistics/')) {
      return Promise.resolve({totals: {total: 1}, by_status: {recorded: 1},
        by_system: [], trend: [], record_type: 'abnormal'});
    }
    return Promise.resolve({data: [ROUTINE_RECORD, ABNORMAL_RECORD], total: 2});
  });
}

async function renderForm() {
  const store = require('../store').default;
  const RecordForm = require('../RecordForm').default;
  mockListApis();
  await act(async () => {
    store.showForm();
    ReactDOM.render(<RecordForm/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

describe('记录类型表单（2026-10-07）', () => {
  it('默认日常运行：提交携带 record_type=routine 与作业内容/操作结果', async () => {
    const store = await renderForm();
    mockHttpPost.mockResolvedValue({});
    // 必填项走真实用户路径（系统下拉/时间面板点选/登记人回车）
    await selectOption('所属系统', '烟台通信系统');
    await setPickerValue('发生时间');
    await setInputValue('标题', 'UPS电源切换及南山UPS电池检查紧固');
    await setTextareaValue('情况描述', '航后按计划完成UPS电源切换与电池检查');
    // 日常运行专属字段
    await setTextareaValue('作业内容', '切换UPS电源并紧固电池端子');
    await setTextareaValue('操作结果/检查结果', '作业完成');
    await typeAndEnter('登记人', '李四');
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalled();
    const payload = mockHttpPost.mock.calls[0][1];
    expect(payload.record_type).toBe('routine');
    expect(payload.measures_taken).toBe('切换UPS电源并紧固电池端子');
    expect(payload.handling_result).toBe('作业完成');
    expect(payload.routine_record).toBeUndefined();
    expect(store.formVisible).toBe(false);
  });

  it('切换异常事件：显示异常类别，隐藏日常专属字段与关联日常运行', async () => {
    await renderForm();
    // 点击"异常事件"单选
    const radio = document.querySelector('.ant-modal input[type=radio][value=abnormal]');
    expect(radio).toBeTruthy();
    await act(async () => {
      radio.click();
    });
    await act(async () => {await flush();});
    const text = bodyText();
    expect(text).toContain('异常类别');
    // "关联日常运行"功能已整体移除（2026-10-07 用户决策）
    expect(text).not.toContain('关联日常运行');
    expect(text).not.toContain('作业内容');
    expect(text).not.toContain('操作结果/检查结果');
  });

  it('编辑模式：记录类型 Radio 禁用，提交不携带 record_type 键', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockListApis();
    mockHttpPut.mockResolvedValue({});
    await act(async () => {
      store.showForm(ABNORMAL_RECORD);
      ReactDOM.render(<RecordForm/>, container);
    });
    await act(async () => {await flush();});
    const radioRoutine = document.querySelector(
      '.ant-modal input[type=radio][value=routine]');
    expect(radioRoutine.disabled).toBe(true);
    const radioAbnormal = document.querySelector(
      '.ant-modal input[type=radio][value=abnormal]');
    expect(radioAbnormal.disabled).toBe(true);
    const inputs = Array.from(document.querySelectorAll('.ant-modal input'));
    const titleInput = inputs.find(i => i.value === ABNORMAL_RECORD.title);
    expect(titleInput).toBeTruthy();
    const proto = window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(titleInput, '改标题');
    titleInput.dispatchEvent(new Event('input', {bubbles: true}));
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPut).toHaveBeenCalled();
    const payload = mockHttpPut.mock.calls[0][1];
    expect(payload.record_type).toBeUndefined();
  });
});

describe('记录类型详情展示与操作差异（2026-10-07）', () => {
  async function renderDetail(record) {
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    mockListApis(record);
    await act(async () => {
      store.showDetail(record);
      ReactDOM.render(<RecordDetail/>, container);
    });
    await act(async () => {await flush();});
    return store;
  }

  it('日常运行详情：类型标签/作业内容/操作结果，无异常操作', async () => {
    await renderDetail(ROUTINE_RECORD);
    const text = bodyText();
    // 类型标签与页面状态（恒为已记录）
    expect(text).toContain('日常运行');
    expect(text).toContain('已记录');
    // 类型专属字段
    expect(text).toContain('作业内容');
    expect(text).toContain('切换UPS电源并紧固南山UPS电池连接端子');
    expect(text).toContain('操作结果/检查结果');
    // 不渲染关联异常事件（功能已移除）
    expect(text).not.toContain('关联异常事件');
    // 只保留 查看/编辑/删除；不渲染任何异常操作按钮
    const btns = buttonTexts();
    ['编辑', '删除'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(true);
    });
    ['开始跟进', '新增跟进记录', '完成跟进', '转为正式故障', '重新跟进'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(false);
    });
    // 无处理进展页签（无跟进流程）
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .map(t => t.textContent);
    expect(tabs.join('|')).not.toContain('处理进展');
    expect(tabs.join('|')).toContain('附件');
  });

  it('日常运行删除：确认后调用 DELETE 端点并刷新列表', async () => {
    const store = await renderDetail(ROUTINE_RECORD);
    mockHttpDelete.mockResolvedValue({});
    await act(async () => {
      clickButtonByText('删除');
    });
    await act(async () => {await flush();});
    // 确认弹窗 OK 后才发起 DELETE（成功提示等待后端真实结果）
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/runtime-records/21/');
    expect(store.detailVisible).toBe(false);
  });

  it('异常事件详情：类型标签/异常操作完整保留，无关联功能', async () => {
    await renderDetail(ABNORMAL_RECORD);
    const text = bodyText();
    expect(text).toContain('异常事件');
    // "关联日常运行"功能已整体移除（2026-10-07 用户决策）
    expect(text).not.toContain('关联日常运行');
    expect(text).not.toContain('删除关联');
    // 异常操作完整保留（已记录状态：编辑/开始跟进/转为正式故障）；无删除
    const btns = buttonTexts();
    ['编辑', '开始跟进', '转为正式故障'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(true);
    });
    expect(btns.some(t => t === '删除')).toBe(false);
    // 处理进展页签存在
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .map(t => t.textContent).join('|');
    expect(tabs).toContain('处理进展');
  });
});

describe('记录类型列表筛选与统计（2026-10-07）', () => {
  it('列表渲染记录类型列', async () => {
    const RuntimeRecordIndex = require('../index').default;
    mockListApis();
    await act(async () => {
      ReactDOM.render(<RuntimeRecordIndex/>, container);
    });
    await act(async () => {await flush();});
    const text = bodyText();
    expect(text).toContain('记录类型');
    expect(text).toContain('日常运行');
    expect(text).toContain('异常事件');
  });

  it('store：fetchRecords 携带 record_type 筛选参数', async () => {
    const store = require('../store').default;
    mockListApis();
    store.f_record_type = 'routine';
    await act(async () => {
      store.fetchRecords();
      await flush();
    });
    const listCall = mockHttpGet.mock.calls.find(c => c[0].endsWith('/runtime-records/'));
    expect(listCall).toBeTruthy();
    expect(listCall[1].params.record_type).toBe('routine');
  });

  it('store：fetchStatistics 携带 record_type 统计口径参数', async () => {
    const store = require('../store').default;
    mockListApis();
    store.f_stats_record_type = 'routine';
    await act(async () => {
      store.fetchStatistics();
      await flush();
    });
    const statCall = mockHttpGet.mock.calls.find(c => c[0].includes('/statistics/'));
    expect(statCall).toBeTruthy();
    expect(statCall[1].params.record_type).toBe('routine');
  });
});
