/**
 * 故障"处理进展概览"三层展示测试（2026-10 流程简化配套）
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 故障列表"处理进展"列：显示后端聚合的条数（3 条 / 0 条），
 *   已关闭/已作废故障保留历史数量；数字为链接样式（非大按钮）
 * - 点击列表数量打开故障详情并自动定位到"处理进展"页签（受控页签）
 * - 基本信息页签底部只读"处理概览"紧凑信息条（非边框表格）：条数/最近更新/
 *   最后记录 + 查看全部进展；无进展时展示"暂无处理进展"
 * - "查看全部进展"只切换页签，不重复打开新的详情窗口
 * - 添加/更正处理进展成功后：处理概览（后端详情统计）与页签条数立即刷新
 * - 后端业务错误（Promise 拒绝）不进入成功提示路径
 * （已关闭/已作废终态不显示继续处置操作由 faultComponents.test.js 覆盖；
 *   后端统计口径由 stable_contract/test_fault_handling_overview.py 覆盖）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import { message } from 'antd';

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
  history: {},
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
  // store 为跨用例共享的单例（不 resetModules，避免 React 多副本），
  // 每个用例前重置可能泄漏的可见状态
  const store = require('../faultStore').default;
  store.detailVisible = false;
  store.formVisible = false;
  store.records = [];
  store.detail = {};
  store.handlingRecords = [];
  store.handlingTotal = 0;
  store.activeTab = 'basic';
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  jest.restoreAllMocks();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

// antd 两字按钮/文案自动空格，比较前统一去空白
function bodyText() {
  return document.body.textContent.replace(/\s+/g, '');
}

// 含日期时间的原文断言用（bodyText 的空白折叠会吃掉"日期 时间"中的空格）
function rawText() {
  return document.body.textContent;
}

function tabTexts() {
  return Array.from(document.querySelectorAll('.ant-tabs-tab')).map(t => t.textContent);
}

function activeTabText() {
  const active = document.querySelector('.ant-tabs-tab-active');
  return active ? active.textContent : '';
}

// ===== 夹具 =====

const FAULT_DETAIL = {
  id: 11, fault_no: 'GZ20260918-0001',
  system: 7, system_name: '烟台通信系统', system_code: 'SYS-A1',
  system_location: '机房A',
  impact_status: 'fault', impact_status_text: '故障',
  status: 'handling', status_text: '处置中',
  occurred_at: '2026-09-18 08:30', phenomenon: '主用链路频繁丢包',
  fault_object_name: '接入交换机01', fault_object_model: 'H3C-5120', fault_object_sn: '',
  fault_component_name: '接入交换机',
  reason_analysis: '', recovered_at: null,
  recovery_close_note: '',
  recovered_by_name: '', recovered_confirmed_at: null,
  registrar_name: '登记员甲',
  created_by_name: 'admin', created_at: '2026-09-18 08:40',
  // 后端详情聚合的处理进展概览（fault_services.handling_overview）
  handling_record_count: 2,
  latest_handled_at: '2026-09-18 09:30:00',
  latest_handling_content: '更换备用链路',
};

const HANDLING_RECORDS = {
  data: [
    {id: 1, fault: 11, handled_at: '2026-09-18 09:00', handler: 2, handler_name: 'operator',
      progress_type: 'check', progress_type_text: '检查',
      content: '现场检查，确认光模块告警', result: '处理中', corrections: [],
      recorder_name: '记录员甲', created_at: '2026-09-18 09:05'},
    {id: 2, fault: 11, handled_at: '2026-09-18 09:30', handler: 2, handler_name: 'operator',
      progress_type: 'watch', progress_type_text: '持续观察',
      content: '更换备用链路', result: '已切换', corrections: [],
      recorder_name: '记录员乙', created_at: '2026-09-18 09:35'},
  ],
  total: 2, page: 1, page_size: 100,
};

const EMPTY_HANDLING = {data: [], total: 0, page: 1, page_size: 100};

const LIST_ROWS = [
  {id: 11, fault_no: 'GZ20260918-0001', system_name: '烟台通信系统',
    affects_system_operation: true, impact_status: 'fault', impact_status_text: '故障',
    status: 'handling', status_text: '处置中', occurred_at: '2026-09-18 08:30',
    phenomenon: '主用链路频繁丢包', registrar_name: '登记员甲',
    handling_record_count: 3, latest_handled_at: '2026-09-18 09:30:00',
    latest_handling_content: '更换备用链路'},
  {id: 12, fault_no: 'GZ20260918-0002', system_name: '威海监控系统',
    affects_system_operation: false, impact_status: '', impact_status_text: '',
    status: 'closed', status_text: '已关闭', occurred_at: '2026-09-17 10:00',
    phenomenon: '历史故障（已关闭）', registrar_name: '登记员乙',
    handling_record_count: 0, latest_handled_at: null, latest_handling_content: ''},
  {id: 13, fault_no: 'GZ20260918-0003', system_name: '烟台通信系统',
    affects_system_operation: true, impact_status: 'degraded', impact_status_text: '降级',
    status: 'cancelled', status_text: '已作废', occurred_at: '2026-09-16 09:00',
    phenomenon: '误报（已作废）', registrar_name: '登记员丙',
    handling_record_count: 2, latest_handled_at: '2026-09-16 09:20:00',
    latest_handling_content: '作废前检查记录'},
];

// ===== 渲染助手 =====

async function renderDetail(detailOverrides) {
  const store = require('../faultStore').default;
  const FaultDetail = require('../FaultDetail').default;
  const detail = {...FAULT_DETAIL, ...(detailOverrides || {})};
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/handling-records')) {
      return Promise.resolve(
        (detail.handling_record_count ?? 0) > 0 ? HANDLING_RECORDS : EMPTY_HANDLING);
    }
    // 详情接口：http 拦截器解包后 resolve 详情本体
    return Promise.resolve(detail);
  });
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    store.showDetail(detail);
    ReactDOM.render(<FaultDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

async function renderFaultList() {
  const store = require('../faultStore').default;
  const FaultIndex = require('../FaultIndex').default;
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('candidate-systems')) {
      return Promise.resolve({data: [
        {id: 7, system_code: 'SYS-A1', name: '烟台通信系统', install_location: '机房A'},
      ]});
    }
    if (url.includes('/handling-records')) {
      return Promise.resolve(HANDLING_RECORDS);
    }
    // 故障详情 GET（/faults/<id>/）：resolve 详情本体（行点击后 showDetail 发起）
    if (/\/faults\/\d+\/?$/.test(url)) {
      return Promise.resolve(FAULT_DETAIL);
    }
    // 故障列表：json_response 分页载荷，行内含后端聚合的处理进展概览
    return Promise.resolve({data: LIST_ROWS, total: 3, page: 1, page_size: 20});
  });
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    ReactDOM.render(<FaultIndex/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

function findFormItem(labelText) {
  const modals = document.querySelectorAll('.ant-modal');
  const scope = modals.length ? modals[modals.length - 1] : document;
  const items = Array.from(scope.querySelectorAll('.ant-form-item'));
  return items.find(n => {
    const label = n.querySelector('.ant-form-item-label');
    return label && label.textContent.includes(labelText);
  }) || null;
}

function topModal() {
  const modals = document.querySelectorAll('.ant-modal');
  return modals.length ? modals[modals.length - 1] : null;
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

async function submitModal(method, autoResolve = true) {
  const mock = method === 'put' ? mockHttpPut : mockHttpPost;
  // 默认代填成功响应；业务错误用例传 autoResolve=false 自行注入 reject
  if (autoResolve) {
    mock.mockResolvedValue({});
  }
  const okButton = Array.from(document.querySelectorAll('.ant-modal-footer button'))
    .find(b => b.className.includes('ant-btn-primary'));
  await act(async () => {
    okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

// ===== 用例 =====

describe('故障列表"处理进展"列（后端聚合数量，只读链接样式）', () => {
  it('有记录显示"N 条"、无记录显示"0 条"，已关闭/已作废保留历史数量', async () => {
    await renderFaultList();
    const text = bodyText();
    expect(text).toContain('3条');
    expect(text).toContain('0条');
    // 已作废故障同样展示历史数量（后端统计不因状态过滤）
    expect(text).toContain('2条');
  });

  it('点击数量打开故障详情并定位到"处理进展"页签（不开第二个窗口）', async () => {
    const store = await renderFaultList();
    const countLink = Array.from(document.querySelectorAll('a'))
      .find(a => a.textContent.replace(/\s+/g, '') === '3条');
    expect(countLink).toBeTruthy();
    await act(async () => {
      countLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    expect(store.detailVisible).toBe(true);
    expect(store.detailId).toBe(11);
    // 受控页签直接停在"处理进展"，基本信息非激活
    expect(activeTabText()).toContain('处理进展');
    expect(activeTabText()).not.toContain('基本信息');
    // 时间线内容可见（处理进展页签已挂载）
    expect(bodyText()).toContain('现场检查，确认光模块告警');
  });
});

describe('基本信息"处理概览"（只读摘要，数据来自后端详情统计）', () => {
  it('有进展时展示条数/最近更新/最后记录与查看全部进展', async () => {
    await renderDetail();
    const text = bodyText();
    expect(text).toContain('处理概览');
    expect(text).toContain('2条');
    expect(text).toContain('最近更新');
    expect(rawText()).toContain('2026-09-18 09:30:00');
    expect(text).toContain('最后记录');
    expect(text).toContain('更换备用链路');
    expect(text).toContain('查看全部进展');
  });

  it('无进展时展示"暂无处理进展"，不显示条数/最近更新/最后记录/查看全部进展', async () => {
    await renderDetail({
      handling_record_count: 0, latest_handled_at: null, latest_handling_content: '',
    });
    const text = bodyText();
    expect(text).toContain('暂无处理进展');
    expect(text).not.toContain('条');
    expect(text).not.toContain('查看全部进展');
    expect(text).not.toContain('最近更新');
    expect(text).not.toContain('最后记录');
  });

  it('"查看全部进展"只切换页签（同一详情窗口内），时间线变为可见', async () => {
    await renderDetail();
    // 查看全部进展为 link 样式按钮（渲染为 <button>，非 <a>）
    const link = Array.from(document.querySelectorAll('a, button'))
      .find(n => n.textContent.replace(/\s+/g, '') === '查看全部进展');
    expect(link).toBeTruthy();
    await act(async () => {
      link.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    expect(activeTabText()).toContain('处理进展');
    // 仍是同一个详情窗口（未重新打开）
    expect(document.querySelectorAll('.ant-modal').length).toBe(1);
    // 时间线记录可见
    expect(bodyText()).toContain('现场检查，确认光模块告警');
  });
});

describe('添加/更正进展后摘要与页签数量立即刷新（后端统计静默同步）', () => {
  it('添加进展成功后处理概览与页签条数随最新统计刷新', async () => {
    const store = await renderDetail({
      handling_record_count: 0, latest_handled_at: null, latest_handling_content: '',
    });
    expect(bodyText()).toContain('暂无处理进展');
    // 打开处理进展页签并点击添加
    await act(async () => {
      store.setActiveTab('handling');
    });
    await act(async () => {await flush();});
    const addButton = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '').includes('添加处理进展'));
    expect(addButton).toBeTruthy();
    await act(async () => {
      addButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    await typeAndEnter('进展记录人', '记录员丙');
    await setTextareaValue('进展内容', '更换备件后完成业务验证');
    // 提交成功后，详情与进展列表返回包含新记录的最新统计数据
    const currentDetail = {...FAULT_DETAIL,
      handling_record_count: 1, latest_handled_at: '2026-09-18 09:50:00',
      latest_handling_content: '更换备件后完成业务验证'};
    const currentHandling = {
      data: [...HANDLING_RECORDS.data,
        {id: 9, fault: 11, handled_at: '2026-09-18 09:50', handler: 2,
          handler_name: 'operator', progress_type: 'test', progress_type_text: '测试',
          content: '更换备件后完成业务验证', result: '复测通过', corrections: [],
          recorder_name: '记录员丙', created_at: '2026-09-18 09:55'}],
      total: 1, page: 1, page_size: 100,
    };
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/handling-records')) {
        return Promise.resolve(currentHandling);
      }
      return Promise.resolve(currentDetail);
    });
    mockHttpPost.mockResolvedValue({});
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/faults/11/handling-records/',
      expect.objectContaining({content: '更换备件后完成业务验证'}));
    // 处理概览（详情统计）与页签条数均已刷新
    const text = bodyText();
    expect(text).toContain('1条');
    expect(text).toContain('更换备件后完成业务验证');
    expect(tabTexts().some(t => t.replace(/\s+/g, '').includes('处理进展（1）'))).toBe(true);
    expect(store.detail.handling_record_count).toBe(1);
  });

  it('更正进展内容后"最后记录"随最新统计更新且数量不变', async () => {
    const store = await renderDetail();
    await act(async () => {
      store.setActiveTab('handling');
    });
    await act(async () => {await flush();});
    // 更正"更换备用链路"这条进展
    const item = Array.from(document.querySelectorAll('.ant-timeline-item'))
      .find(n => n.textContent.includes('更换备用链路'));
    const correctButton = Array.from(item.querySelectorAll('button'))
      .find(b => b.textContent.includes('更正'));
    await act(async () => {
      correctButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    await setTextareaValue('进展内容', '更换备用链路并复测通过');
    await setTextareaValue('更正原因', '补充复测结论');
    // 更正不产生新的进展行：统计数量保持 2，最后记录为更正后内容
    const currentDetail = {...FAULT_DETAIL,
      latest_handled_at: '2026-09-18 09:30:00',
      latest_handling_content: '更换备用链路并复测通过'};
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/handling-records')) {
        return Promise.resolve(HANDLING_RECORDS);
      }
      return Promise.resolve(currentDetail);
    });
    await submitModal('put');
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    expect(mockHttpPost).not.toHaveBeenCalled();
    const text = bodyText();
    expect(text).toContain('2条');
    expect(text).toContain('更换备用链路并复测通过');
    expect(store.detail.handling_record_count).toBe(2);
  });

  it('后端业务错误时不进入成功提示路径（HTTP 200 + error 由拦截器统一提示）', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    const store = await renderDetail();
    await act(async () => {
      store.setActiveTab('handling');
    });
    await act(async () => {await flush();});
    const addButton = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '').includes('添加处理进展'));
    await act(async () => {
      addButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    await typeAndEnter('进展记录人', '记录员丙');
    await setTextareaValue('进展内容', '不应保存的内容');
    mockHttpPost.mockRejectedValue(new Error('进展类型不合法'));
    await submitModal('post', false);
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    // 不显示成功提示，弹窗保持打开（可修正后重试）
    expect(successSpy).not.toHaveBeenCalled();
    expect(topModal()).toBeTruthy();
  });
});
