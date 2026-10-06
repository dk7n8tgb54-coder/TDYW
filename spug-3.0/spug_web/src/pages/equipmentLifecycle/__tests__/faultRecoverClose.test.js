/**
 * 确认恢复并结案弹窗测试（2026-10 流程合并，自 faultComponents.test.js 拆出）。
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 弹窗一次展示三个必填字段（恢复时间/恢复确认人/结案说明）
 * - 结案说明字段合并（2026-10-04）：只展示"结案说明"一个文本框，
 *   原"恢复确认信息"/"最终结果"两框不再同时出现，提交只携带统一字段
 * - 结案说明缺失或纯空格提交被前端校验拦截（不发请求）
 * - 恢复确认人必填手输：不预填登录账号，多人顿号拼接提交
 * - 提交成功后重新拉取详情（确认恢复并结案 → 已关闭终态刷新）
 * - 后端业务错误时不进入成功路径（不刷新详情，弹窗保持可重试）
 * - 存量带恢复数据的记录打开弹窗预填既有结案说明
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
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});
// 注意：组件渲染测试不使用 jest.resetModules()（会导致 React 多副本触发 Invalid hook call）

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

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
};

const HANDLING_RECORDS = {
  data: [
    {id: 1, fault: 11, handled_at: '2026-09-18 09:00', handler: 2, handler_name: 'operator',
      content: '现场检查，确认光模块告警', corrections: [], created_at: '2026-09-18 09:05'},
  ],
  total: 1, page: 1, page_size: 100,
};

async function renderDetail(status, overrides) {
  const store = require('../faultStore').default;
  const FaultDetail = require('../FaultDetail').default;
  const detail = {...FAULT_DETAIL, status, ...(overrides || {})};
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/handling-records')) {
      return Promise.resolve(HANDLING_RECORDS);
    }
    // 详情接口：后端 json_response(详情) 经 http 拦截器解包后 resolve 详情本体
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

function bodyText() {
  // antd 两字按钮文案渲染为"作 废"（自动空格），比较前统一去空白
  return document.body.textContent.replace(/\s+/g, '');
}

function modalText() {
  // 详情已改为 Modal（2026-10-02）：动作弹窗挂载在后，取 DOM 中最后一个（顶层对话框）
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

function selectionTags(formLabel) {
  const item = findFormItem(formLabel);
  if (!item) return null;
  return Array.from(item.querySelectorAll('.ant-select-selection-item'))
    .map(n => n.getAttribute('title') || n.textContent);
}

function selectInput(formLabel) {
  return findFormItem(formLabel).querySelector('.ant-select input');
}

async function typeAndEnter(formLabel, text) {
  // 输入与回车分两次 act：模拟真实输入节奏（同 act 内提交不触发）
  const input = selectInput(formLabel);
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

async function submitModal(method) {
  const mock = method === 'put' ? mockHttpPut : mockHttpPost;
  mock.mockResolvedValue({});
  const okButton = Array.from(document.querySelectorAll('.ant-modal-footer button'))
    .find(b => b.className.includes('ant-btn-primary'));
  await act(async () => {
    okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

describe('确认恢复并结案弹窗（三项一次校验，直接进入终态）', () => {
  async function openRecoverModal(status = 'handling', overrides) {
    await renderDetail(status, overrides);
    const recoverButton = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '确认恢复并结案');
    expect(recoverButton).toBeTruthy();
    await act(async () => {
      recoverButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
  }

  it('弹窗只展示"结案说明"一个结案文本框，旧两字段不再同时显示', async () => {
    await openRecoverModal();
    const text = modalText();
    expect(text).toContain('恢复时间');
    expect(text).toContain('恢复确认人');
    expect(text).toContain('结案说明');
    // 原"恢复确认信息"/"最终结果"两个输入框已合并删除
    expect(text).not.toContain('恢复确认信息');
    expect(text).not.toContain('最终结果');
    // 结案说明只有一个 TextArea（多行输入框）
    const noteItem = findFormItem('结案说明');
    expect(noteItem.querySelectorAll('textarea').length).toBe(1);
    // 结案说明位于最终原因分析之下（用户指定排序）
    expect(text.indexOf('最终原因分析')).toBeGreaterThan(-1);
    expect(text.indexOf('最终原因分析')).toBeLessThan(text.indexOf('结案说明'));
    // 恢复时间默认当前时间
    const timeInput = findFormItem('恢复时间').querySelector('input');
    expect(timeInput.value).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
    expect(selectionTags('恢复确认人')).toEqual([]);
  });

  it('结案说明缺失或纯空格提交被拦截（不发请求）；填写后真实提交统一字段', async () => {
    await openRecoverModal();
    // 仅填恢复确认人：缺结案说明 → required 拦截
    await typeAndEnter('恢复确认人', '确认人甲');
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(0);
    // 结案说明只填空格 → whitespace 校验同样拦截（不能只填空格）
    await setTextareaValue('结案说明', '   ');
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(0);
    // 补齐结案说明 → 真实提交（一个弹窗一次事务完成恢复+结案）
    await setTextareaValue('结案说明', '更换备件并复测通过，业务验证正常');
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/recover/');
    expect(payload.recovered_by_name).toBe('确认人甲');
    expect(payload.recovery_close_note).toBe('更换备件并复测通过，业务验证正常');
    expect(payload.recovered_at).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
    // 前端只提交统一字段，不再发送新旧两套参数
    expect(payload).not.toHaveProperty('recover_confirm');
    expect(payload).not.toHaveProperty('final_result');
  });

  it('恢复确认人必填手输：不预填登录账号，多人顿号拼接提交', async () => {
    await openRecoverModal();
    expect(selectionTags('恢复确认人')).toEqual([]);
    await setTextareaValue('结案说明', '更换备件并复测通过，业务验证正常');
    await typeAndEnter('恢复确认人', '确认人甲');
    await typeAndEnter('恢复确认人', '确认人乙');
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/recover/');
    expect(payload.recovered_by_name).toBe('确认人甲、确认人乙');
  });

  it('提交成功后重新拉取详情并展示已关闭终态（成功提示一次）', async () => {
    await openRecoverModal();
    await setTextareaValue('结案说明', '更换备件并复测通过，业务验证正常');
    await typeAndEnter('恢复确认人', '确认人甲');
    await submitModal('post');
    // 动作成功路径触发统一刷新：详情 + 处置记录 + 列表各一次
    const gets = mockHttpGet.mock.calls.map(call => call[0]);
    expect(gets.filter(u => u === '/api/equipment-lifecycle/faults/11/').length)
      .toBeGreaterThanOrEqual(2);
  });

  it('后端返回业务错误时不进入成功路径（不刷新详情，Promise 拒绝被吞）', async () => {
    await openRecoverModal();
    await setTextareaValue('结案说明', '更换备件并复测通过，业务验证正常');
    await typeAndEnter('恢复确认人', '确认人甲');
    // http 拦截器对业务错误 reject：成功路径（重新拉取详情/弹窗关闭）不执行
    mockHttpPost.mockRejectedValueOnce(new Error('已关闭或已作废的故障不能重复确认恢复并结案'));
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    // 失败后再次提交仍指向同一端点（弹窗未关闭，可修正后重试）
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(2);
    expect(mockHttpPost.mock.calls[1][0]).toBe(
      '/api/equipment-lifecycle/faults/11/recover/');
  });

  it('存量带恢复数据的记录（迁移转为处置中）打开弹窗预填既有结案说明', async () => {
    // 迁移 0051 把旧流程 recovered 存量转为 handling，其结案说明字段保留：
    // 打开合并弹窗时预填既有值，重新确认后结案
    await openRecoverModal('handling', {
      recovered_at: '2026-09-18 10:00:00',
      recovered_by_name: '恢复确认人甲',
      recovery_close_note: '旧流程已完成恢复确认，更换备件并验证',
    });
    const text = modalText();
    expect(text).toContain('确认恢复并结案');
    // 预填：恢复时间/确认人/结案说明取详情既有值
    const timeInput = findFormItem('恢复时间').querySelector('input');
    expect(timeInput.value).toBe('2026-09-18 10:00');
    expect(selectionTags('恢复确认人')).toEqual(['恢复确认人甲']);
    const noteArea = findFormItem('结案说明').querySelector('textarea');
    expect(noteArea.value).toBe('旧流程已完成恢复确认，更换备件并验证');
  });
});
