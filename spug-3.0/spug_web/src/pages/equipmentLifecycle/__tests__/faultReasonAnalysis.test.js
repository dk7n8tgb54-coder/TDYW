/**
 * 原因分析流程优化测试（2026-10）
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证原因分析
 * 在新增、详情、结案三个关键阶段的入口与状态展示（编辑阶段入口由
 * faultComponents.test.js 覆盖）：
 * - 新增故障表单"初步判断"区块：非必填"初步原因分析"（紧随故障现象之后），
 *   不填写可正常创建，填写后请求携带 reason_analysis
 * - 详情页原因分析状态化展示：未填写="尚未分析"+补充入口；处置中=
 *   "初步判断：{内容}"+修改；已关闭="最终原因：{内容}"（只读）；
 *   原因未明="原因未明：{说明}"（reason_unknown 标记）
 * - 详情页直接补充/修改：专用弹窗只处理原因分析（回填当前值），保存走
 *   PUT reason-analysis 端点并静默刷新详情，真实成功后提示一次
 * - 结案弹窗"最终原因分析"默认回填、可修改、可选"原因未明"随结案保存
 * - 处理进展"故障定位"类型可选、提交正式编码 fault_locate、时间线展示
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

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
  store.record = {};
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

function bodyText() {
  // antd 两字按钮/文案自动空格，比较前统一去空白
  return document.body.textContent.replace(/\s+/g, '');
}

function modalText() {
  // 详情为 Modal（2026-10-02）：动作弹窗挂载在后，取 DOM 中最后一个（顶层对话框）
  const modals = document.querySelectorAll('.ant-modal');
  return modals.length ? modals[modals.length - 1].textContent : '';
}

function topModal() {
  const modals = document.querySelectorAll('.ant-modal');
  return modals.length ? modals[modals.length - 1] : null;
}

function findFormItem(labelText) {
  const scope = topModal() || document;
  const items = Array.from(scope.querySelectorAll('.ant-form-item'));
  return items.find(n => {
    const label = n.querySelector('.ant-form-item-label');
    return label && label.textContent.includes(labelText);
  }) || null;
}

function findButton(text) {
  return Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === text) || null;
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

async function setCheckbox(label, checked) {
  const checkbox = findFormItem(label).querySelector('input[type="checkbox"]');
  expect(checkbox).toBeTruthy();
  await act(async () => {
    if (checkbox.checked !== checked) {
      checkbox.click();
    }
  });
  await act(async () => {await flush();});
}

// antd4 DatePicker：打开面板后点击日期单元格 + OK 提交（真实用户路径；
// jsdom 中直接给输入框塞值不触发 rc-picker 解析确认）
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
  expect(input.value).not.toBe('');
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

async function submitModal() {
  mockHttpPut.mockResolvedValue({});
  mockHttpPost.mockResolvedValue({});
  const okButton = topModal().querySelector('.ant-modal-footer button.ant-btn-primary');
  await act(async () => {
    okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
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
  reason_analysis: '', reason_unknown: false,
  recovered_at: null,
  recovery_close_note: '',
  recovered_by_name: '', recovered_confirmed_at: null,
  registrar_name: '登记员甲',
  created_by_name: 'admin', created_at: '2026-09-18 08:40',
};

const HANDLING_RECORDS = {
  data: [
    {id: 1, fault: 11, handled_at: '2026-09-18 09:00', handler: 2, handler_name: 'operator',
      recorder_name: '记录员甲', progress_type: 'check', progress_type_text: '检查',
      content: '现场检查，确认光模块告警', result: '处理中', corrections: [],
      created_at: '2026-09-18 09:05'},
  ],
  total: 1, page: 1, page_size: 100,
};

// ===== 渲染助手 =====

async function renderDetail(status, overrides) {
  const store = require('../faultStore').default;
  const FaultDetail = require('../FaultDetail').default;
  const detail = {...FAULT_DETAIL, status, ...(overrides || {})};
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/handling-records')) {
      return Promise.resolve(HANDLING_RECORDS);
    }
    // 详情接口：http 拦截器解包后 resolve 详情本体
    return Promise.resolve(detail);
  });
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    // 真实打开路径：列表行与 ?detail= 深链接均经 showDetail 进入
    store.showDetail(detail);
    ReactDOM.render(<FaultDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

async function renderFaultForm({record = {}, detail = null} = {}) {
  const store = require('../faultStore').default;
  const FaultForm = require('../FaultForm').default;
  store.systems = [{id: 7, name: '烟台通信系统', install_location: '机房A'}];
  store.record = record;
  store.formVisible = true;
  if (detail) {
    mockHttpGet.mockResolvedValue(detail);
  }
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    ReactDOM.render(<FaultForm/>, container);
  });
  await act(async () => {await flush();});
}

async function submitFormModal(method) {
  const mock = method === 'put' ? mockHttpPut : mockHttpPost;
  mock.mockResolvedValue({});
  const okButton = document.querySelector('.ant-modal-footer button.ant-btn-primary');
  await act(async () => {
    okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

// ===== 用例 =====

describe('新增故障表单"初步判断"区块（2026-10）', () => {
  it('显示非必填"初步原因分析"，位于故障现象之后、故障登记人之前，占位提示明确', async () => {
    await renderFaultForm();
    const text = bodyText();
    expect(text).toContain('初步判断');
    expect(text).toContain('初步原因分析');
    // 占位提示为输入框属性（textContent 不含 placeholder）
    const textarea = findFormItem('初步原因分析').querySelector('textarea');
    expect(textarea.placeholder).toBe('已知时填写，暂时无法判断可留空，处置过程中可继续补充');
    // 无必填星号（非必填，原因未知可留空）
    const item = findFormItem('初步原因分析');
    expect(item).toBeTruthy();
    expect(item.querySelector('.ant-form-item-required')).toBeNull();
    // 顺序：故障现象 → 初步原因分析 → 故障登记人
    expect(text.indexOf('故障现象')).toBeGreaterThan(-1);
    expect(text.indexOf('故障现象')).toBeLessThan(text.indexOf('初步原因分析'));
    expect(text.indexOf('初步原因分析')).toBeLessThan(text.indexOf('故障登记人'));
  });

  it('不填写原因分析可成功提交（提交空串，原因未知不阻塞创建）', async () => {
    await renderFaultForm();
    await fillCreateRequiredFields();
    await submitFormModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/');
    expect(payload.reason_analysis).toBe('');
  });

  it('填写初步原因分析后请求携带 reason_analysis', async () => {
    await renderFaultForm();
    await fillCreateRequiredFields();
    await setTextareaValue('初步原因分析', '现场检查疑为光模块老化');
    await submitFormModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPost.mock.calls[0];
    expect(payload.reason_analysis).toBe('现场检查疑为光模块老化');
  });

  it('编辑表单保留"原因分析"入口，无"初步判断"区块（阶段口径区分）', async () => {
    await renderFaultForm({record: {id: 11}, detail: FAULT_DETAIL});
    const text = bodyText();
    expect(text).toContain('原因分析');
    expect(text).not.toContain('初步判断');
    expect(text).not.toContain('初步原因分析');
  });
});

// 新增表单必填项构造：选择系统 + 登记人 + 现象 + 发生时间（满足必填校验，
// 使提交真实到达请求层）
async function fillCreateRequiredFields() {
  // 选择故障系统（下拉搜索输入后点击选项）
  const selector = findFormItem('故障系统').querySelector('.ant-select-selector');
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
  });
  await act(async () => {await flush();});
  const option = Array.from(document.querySelectorAll(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option'))
    .find(o => o.textContent.includes('烟台通信系统'));
  await act(async () => {
    option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
  // 登记人（tags 手输回车）
  await typeAndEnter('故障登记人', '登记人甲');
  // 故障现象
  await setTextareaValue('故障现象', '主用链路频繁丢包');
  // 故障发生时间（面板点选任意可用日期，值不参与断言）
  await setPickerValue('故障发生时间');
}

describe('详情页原因分析状态展示（处置结果区块）', () => {
  it('未填写：显示"尚未分析"与"补充原因分析"入口', async () => {
    await renderDetail('handling');
    const text = bodyText();
    expect(text).toContain('原因分析');
    expect(text).toContain('尚未分析');
    expect(findButton('补充原因分析')).toBeTruthy();
    expect(findButton('修改')).toBeNull();
  });

  it('已填写且处置中：显示"初步判断：{内容}"与"修改"入口', async () => {
    await renderDetail('handling', {reason_analysis: '疑为光模块老化'});
    const text = bodyText();
    expect(text).toContain('初步判断：疑为光模块老化');
    expect(findButton('修改')).toBeTruthy();
    expect(findButton('补充原因分析')).toBeNull();
  });

  it('原因未明：显示"原因未明：{说明}"与"修改"入口', async () => {
    await renderDetail('handling', {
      reason_analysis: '多方排查未复现，暂无法定位',
      reason_unknown: true,
    });
    const text = bodyText();
    expect(text).toContain('原因未明：多方排查未复现，暂无法定位');
    expect(text).not.toContain('初步判断：多方排查未复现');
    expect(findButton('修改')).toBeTruthy();
  });

  it('已关闭：显示"最终原因：{内容}"，不显示任何原因分析编辑入口（终态只读）', async () => {
    await renderDetail('closed', {reason_analysis: '光模块老化，更换后恢复'});
    const text = bodyText();
    expect(text).toContain('最终原因：光模块老化，更换后恢复');
    expect(findButton('修改')).toBeNull();
    expect(findButton('补充原因分析')).toBeNull();
  });

  it('已关闭且无原因分析：显示"尚未分析"不报错（历史数据兼容）', async () => {
    await renderDetail('closed');
    expect(bodyText()).toContain('尚未分析');
    expect(findButton('补充原因分析')).toBeNull();
  });

  it('已作废故障不显示原因分析编辑入口（终态封闭）', async () => {
    await renderDetail('cancelled', {reason_analysis: '误报作废前初步判断'});
    expect(bodyText()).toContain('初步判断：误报作废前初步判断');
    expect(findButton('修改')).toBeNull();
    expect(findButton('补充原因分析')).toBeNull();
  });
});

describe('详情页直接补充/修改原因分析（专用弹窗）', () => {
  async function openReasonModal(status = 'handling', overrides) {
    const store = await renderDetail(status, overrides);
    const button = findButton('补充原因分析') || findButton('修改');
    expect(button).toBeTruthy();
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    return store;
  }

  it('弹窗只处理原因分析：不出现系统/发生时间/故障现象等无关字段', async () => {
    await openReasonModal();
    const text = modalText();
    expect(text).toContain('原因分析');
    expect(text).not.toContain('故障系统');
    expect(text).not.toContain('发生时间');
    expect(text).not.toContain('故障现象');
  });

  it('未填写时打开弹窗为空并可补充保存：PUT 专用端点 + 静默刷新详情 + 成功提示', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    const store = await openReasonModal();
    await setTextareaValue('原因分析', '现场检查确认为光模块老化');
    // 保存成功后详情静默刷新：mock 返回已更新的详情（处置结果随新状态展示）
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/handling-records')) {
        return Promise.resolve(HANDLING_RECORDS);
      }
      return Promise.resolve({...FAULT_DETAIL, status: 'handling',
        reason_analysis: '现场检查确认为光模块老化'});
    });
    await submitModal();
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/reason-analysis/');
    expect(payload.reason_analysis).toBe('现场检查确认为光模块老化');
    expect(payload.reason_unknown).toBe(false);
    // 保存后重新获取详情（打开详情 1 次 + 保存后静默刷新 1 次）
    const detailGets = mockHttpGet.mock.calls
      .filter(call => call[0] === '/api/equipment-lifecycle/faults/11/').length;
    expect(detailGets).toBe(2);
    expect(successSpy).toHaveBeenCalledTimes(1);
    expect(store.detail.reason_analysis).toBe('现场检查确认为光模块老化');
  });

  it('已填写时弹窗回填当前原因分析（标题为修改原因分析）', async () => {
    await openReasonModal('handling', {reason_analysis: '疑为光模块老化'});
    expect(modalText()).toContain('修改原因分析');
    const textarea = findFormItem('原因分析').querySelector('textarea');
    expect(textarea.value).toBe('疑为光模块老化');
  });

  it('勾选"原因未明"后切换为必填未明说明，未填说明被前端校验拦截', async () => {
    await openReasonModal();
    await setCheckbox('原因未明', true);
    expect(modalText()).toContain('未明说明');
    // 不填说明直接提交：required 拦截，不发请求
    await submitModal();
    expect(mockHttpPut).not.toHaveBeenCalled();
  });

  it('勾选"原因未明"并填写说明可保存：payload 携带 reason_unknown=true', async () => {
    const store = await openReasonModal();
    await setCheckbox('原因未明', true);
    await setTextareaValue('未明说明', '多方排查未复现，暂无法定位');
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/handling-records')) {
        return Promise.resolve(HANDLING_RECORDS);
      }
      return Promise.resolve({...FAULT_DETAIL, status: 'handling',
        reason_analysis: '多方排查未复现，暂无法定位', reason_unknown: true});
    });
    await submitModal();
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPut.mock.calls[0];
    expect(payload.reason_unknown).toBe(true);
    expect(payload.reason_analysis).toBe('多方排查未复现，暂无法定位');
    expect(store.detail.reason_unknown).toBe(true);
  });

  it('后端业务错误时不进入成功路径（不提示成功、弹窗保持可重试）', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    await openReasonModal();
    await setTextareaValue('原因分析', '将被后端拒绝的内容');
    mockHttpPut.mockRejectedValueOnce(new Error('已关闭或已作废的故障不能修改原因分析'));
    await submitModal();
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    expect(successSpy).not.toHaveBeenCalled();
    expect(topModal()).toBeTruthy();
  });
});

describe('结案弹窗"最终原因分析"（2026-10）', () => {
  async function openRecoverModal(status = 'handling', overrides) {
    await renderDetail(status, overrides);
    const recoverButton = findButton('确认恢复并结案');
    expect(recoverButton).toBeTruthy();
    await act(async () => {
      recoverButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
  }

  async function fillRecoveryRequiredFields() {
    await setTextareaValue('结案说明', '更换备件并复测通过，业务验证已恢复');
    const input = findFormItem('恢复确认人').querySelector('.ant-select input');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '确认人甲');
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

  it('弹窗提供"最终原因分析"与"原因未明"，默认回填详情中的原因分析', async () => {
    await openRecoverModal('handling', {reason_analysis: '疑为光模块老化'});
    const text = modalText();
    expect(text).toContain('最终原因分析');
    expect(text).toContain('原因未明');
    const textarea = findFormItem('最终原因分析').querySelector('textarea');
    expect(textarea.value).toBe('疑为光模块老化');
  });

  it('修改最终原因分析后随结案提交 reason_analysis', async () => {
    await openRecoverModal('handling', {reason_analysis: '疑为光模块老化'});
    await fillRecoveryRequiredFields();
    await setTextareaValue('最终原因分析', '确认为光模块老化，已更换并复测');
    await submitModal();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/recover/');
    expect(payload.reason_analysis).toBe('确认为光模块老化，已更换并复测');
    expect(payload.reason_unknown).toBe(false);
  });

  it('选择"原因未明"并填写说明可正常结案：payload 携带 reason_unknown=true', async () => {
    await openRecoverModal('handling');
    await fillRecoveryRequiredFields();
    await setCheckbox('原因未明', true);
    expect(modalText()).toContain('未明说明');
    await setTextareaValue('未明说明', '现象未再复现，多方排查无法定位');
    await submitModal();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/recover/');
    expect(payload.reason_unknown).toBe(true);
    expect(payload.reason_analysis).toBe('现象未再复现，多方排查无法定位');
  });

  it('勾选"原因未明"未填说明时前端校验拦截（不发请求）', async () => {
    await openRecoverModal('handling');
    await fillRecoveryRequiredFields();
    await setCheckbox('原因未明', true);
    await submitModal();
    expect(mockHttpPost).not.toHaveBeenCalled();
  });
});

describe('处理进展"故障定位"类型（2026-10）', () => {
  async function openAddModal() {
    await renderDetail('handling');
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
    const handlingTab = tabs.find(t => t.textContent.includes('处理进展'));
    await act(async () => {
      handlingTab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    const addButton = findButton('添加处理进展');
    expect(addButton).toBeTruthy();
    await act(async () => {
      addButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
  }

  async function chooseProgressType(label) {
    const selectSelector = findFormItem('进展类型').querySelector('.ant-select-selector');
    await act(async () => {
      selectSelector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await act(async () => {await flush();});
    const option = Array.from(document.querySelectorAll(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option'))
      .find(o => o.title === label || o.textContent.includes(label));
    expect(option).toBeTruthy();
    await act(async () => {
      option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
  }

  it('"故障定位"可选并随进展提交正式编码 fault_locate', async () => {
    await openAddModal();
    await chooseProgressType('故障定位');
    const input = findFormItem('进展记录人').querySelector('.ant-select input');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '记录员甲');
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
    await setTextareaValue('进展内容', '更换备件前后对比测试，定位为光模块老化');
    await submitModal();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/handling-records/');
    expect(payload.progress_type).toBe('fault_locate');
  });

  it('时间线展示"故障定位"类型标签（历史数据兼容：仅按后端文本渲染）', async () => {
    await renderDetail('handling', null);
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/handling-records')) {
        return Promise.resolve({data: [
          {id: 2, fault: 11, handled_at: '2026-09-18 09:30', handler: 2,
            handler_name: 'operator', recorder_name: '记录员乙',
            progress_type: 'fault_locate', progress_type_text: '故障定位',
            content: '定位过程：更换备件前后对比测试', result: '', corrections: [],
            created_at: '2026-09-18 09:35'},
        ], total: 1, page: 1, page_size: 100});
      }
      return Promise.resolve({...FAULT_DETAIL, status: 'handling'});
    });
    const store = require('../faultStore').default;
    await act(async () => {
      store.setActiveTab('handling');
      await store.fetchHandlingRecords();
    });
    await act(async () => {await flush();});
    expect(bodyText()).toContain('故障定位');
    expect(bodyText()).toContain('定位过程：更换备件前后对比测试');
  });
});
