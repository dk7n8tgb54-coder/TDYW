/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 */
/**
 * 「设备管理 → 系统配置」独立维护入口组件测试（2026-10-19）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 系统候选加载与 ?system= 直达选择（触发建档状态/当前配置/变更历史请求）；
 * - 系统档案引用字段"未核实/已填写"区分；
 * - 建档：可建档显示按钮，建档 Modal 提交真实 payload（来源/明细基线值），
 *   成功后刷新建档状态与当前配置；已有配置数据的系统展示后端拦截原因；
 * - 参数定义 Modal 新增提交真实 payload（含分类/枚举选项）；
 * - 记录配置变更 Modal 提交真实 payload（由只读页签迁入本入口）；
 * - 变更详情抽屉（非只读）动作：验证/回退端点真实调用、业务错误不提示成功；
 * - 无 baseline 权限用户看不到"建立初始配置"按钮（后端独立校验权限码）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();
const mockHasPermission = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: mockHasPermission,
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
  mockHasPermission.mockImplementation(() => true);
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-dropdown, .ant-select-dropdown, .ant-message, .ant-modal-confirm, .ant-drawer-mask').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const OPTIONS_RESPONSE = {
  items: [{
    id: 7, system_code: 'SYS-001', name: 'DVOR系统',
    system_model: 'VR-12', manufacturer: '某通信设备厂',
    install_location: '机房A', callsign: 'BI7AA', work_frequency: '',
    is_active: true, has_baseline: false,
  }, {
    id: 8, system_code: 'SYS-002', name: 'DME系统',
    system_model: '', manufacturer: '', install_location: '',
    callsign: '', work_frequency: '',
    is_active: false, has_baseline: false,
  }],
};

const PARAMS_RESPONSE = {
  total: 2, page: 1, page_size: 200,
  items: [{
    id: 11, param_code: 'rated_power', param_name: '系统额定功率',
    category: 'hardware_spec', category_text: '硬件规格',
    data_type: 'number', data_type_text: '数字', unit: 'kW',
    scope_type: 'all', scope_type_text: '全部系统',
    is_required: false, options: [], is_enabled: true, remark: '',
  }, {
    id: 12, param_code: 'work_mode', param_name: '工作模式',
    category: 'runtime_param', category_text: '运行参数',
    data_type: 'choice', data_type_text: '枚举', unit: '',
    scope_type: 'all', scope_type_text: '全部系统',
    is_required: false, options: ['主用', '备用'], is_enabled: true, remark: '',
  }],
};

const CONFIG_RESPONSE = {
  system: {id: 7, name: 'DVOR系统', system_code: 'SYS-001'},
  baseline: null,
  items: [
    {
      param: 11, param_code: 'rated_power', param_name: '系统额定功率',
      category: 'hardware_spec', category_text: '硬件规格', data_type: 'number',
      data_type_text: '数字', unit: 'kW', is_required: false, options: [],
      value_text: '', value_number: '3.5', value_bool: null, value_date: null,
      value_choice: '', display_value: '3.5', effective_at: '2026-10-19 10:00:00',
      last_change_id: null, last_change_no: '', last_changed_by_name: '建档员',
      source_text: '初始建档',
    },
    {
      param: 12, param_code: 'work_mode', param_name: '工作模式',
      category: 'runtime_param', category_text: '运行参数', data_type: 'choice',
      data_type_text: '枚举', unit: '', is_required: false, options: ['主用', '备用'],
      value_text: '', value_number: null, value_bool: null, value_date: null,
      value_choice: '主用', display_value: '主用', effective_at: null,
      last_change_id: null, last_change_no: '', last_changed_by_name: '', source_text: '',
    },
  ],
};

const BASELINE_STATE_EMPTY = {
  baseline: null, can_establish: true, block_reason: '',
};

const CHANGES_RESPONSE = {
  total: 1, page: 1, page_size: 10,
  items: [{
    id: 31, change_no: 'PZ20261002-0001', system: 7, system_name: 'DVOR系统',
    reason: '功率校准', status: 'applied', status_text: '已生效',
    applied_at: '2026-10-02 08:30:00', verify_status: '', verify_status_text: '未验证',
    verified_at: null, verified_by_name: '',
    created_by_name: 'admin', created_at: '2026-10-02 08:00:00',
  }],
};

const DETAIL_RESPONSE = {
  id: 31, change_no: 'PZ20261002-0001', system: 7, system_name: 'DVOR系统',
  reason: '功率校准', status: 'applied', status_text: '已生效',
  applied_at: '2026-10-02 08:30:00', applied_by_name: 'admin',
  verify_status: '', verify_status_text: '未验证', verify_note: '功率计实测',
  verified_at: null, verified_by_name: '', rollback_of: null, rollback_of_no: '',
  rollback_changes: [], cancelled_at: null, cancelled_by_name: '', client_token: 'tok-x',
  created_by_name: 'admin', created_at: '2026-10-02 08:00:00', updated_at: null,
  items: [{
    id: 51, param: 11, param_code: 'tx_power', param_name: '发射功率',
    data_type: 'number', data_type_text: '数字', unit: 'dB',
    old_value: '40', new_value: '42.5', verify_status: '', verify_status_text: '',
    remark: '上调 2.5dB',
  }],
};

function defaultGet(url) {
  url = String(url);
  if (url.includes('/config/system-options/')) return Promise.resolve(OPTIONS_RESPONSE);
  if (url.includes('/config-params')) return Promise.resolve(PARAMS_RESPONSE);
  if (url.includes('/config/baseline/')) return Promise.resolve(BASELINE_STATE_EMPTY);
  if (url.includes('/config/changes/')) return Promise.resolve(CHANGES_RESPONSE);
  if (url.endsWith('/config/')) return Promise.resolve(CONFIG_RESPONSE);
  if (url.includes('/config-changes/31')) return Promise.resolve(DETAIL_RESPONSE);
  if (url.includes('/attachments')) return Promise.resolve({data: []});
  return Promise.resolve({});
}

function mountPage(search = '') {
  const SystemConfigMaintain = require('../index').default;
  mockHttpGet.mockImplementation(defaultGet);
  act(() => {
    ReactDOM.render(
      <SystemConfigMaintain location={{search}}/>, container);
  });
  return require('../store').default;
}

async function selectSystem(store) {
  await act(async () => {
    store.selectSystem(7);
    await flush();
    await flush();
  });
}

describe('系统配置维护入口 · 系统选择与档案引用', () => {
  it('加载系统候选与参数定义；选择系统后请求建档状态/当前配置/变更历史', async () => {
    const store = mountPage();
    await flush();
    await flush();
    expect(container.textContent).toContain('选择系统');
    expect(container.textContent).toContain('请先选择要维护配置的系统');
    await selectSystem(store);
    const urls = mockHttpGet.mock.calls.map(c => String(c[0]));
    expect(urls.some(u => u.includes('/systems/7/config/baseline/'))).toBe(true);
    expect(urls.some(u => u.endsWith('/systems/7/config/'))).toBe(true);
    expect(urls.some(u => u.includes('/systems/7/config/changes/'))).toBe(true);
    // 引用档案字段：已填写展示值，未填写标"未核实"
    expect(container.textContent).toContain('VR-12');
    expect(container.textContent).toContain('某通信设备厂');
    expect(container.textContent).toContain('BI7AA');
    expect(container.textContent).toContain('未核实');
  });

  it('支持 ?system= 直达（页签跳转携带系统 ID）', async () => {
    mountPage('?system=7');
    await flush();
    await flush();
    const urls = mockHttpGet.mock.calls.map(c => String(c[0]));
    expect(urls.some(u => u.includes('/systems/7/config/baseline/'))).toBe(true);
    expect(container.textContent).toContain('DVOR系统');
  });
});

describe('系统配置维护入口 · 初始建档', () => {
  it('可建档系统显示按钮；建档 Modal 提交真实 payload 并刷新', async () => {
    const store = mountPage();
    await selectSystem(store);
    const establishBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.includes('建立初始配置'));
    expect(establishBtn).toBeTruthy();
    act(() => {
      establishBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const modal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('建立初始配置'));
    expect(modal).toBeTruthy();
    // 选择基线参数（数字类型 → InputNumber）
    const trigger = modal.querySelector('.ant-select-selector');
    await flush();
    act(() => {
      trigger.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await flush();
    const options = document.querySelectorAll('.ant-select-dropdown .ant-select-item-option');
    act(() => {
      options[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const numberInput = modal.querySelector('.ant-input-number input');
    expect(numberInput).toBeTruthy();
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(numberInput, '42');
      numberInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    // 建档来源必填
    const sourceInput = modal.querySelector('input[placeholder^="如：验收文档"]');
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(sourceInput, '验收文档 2026-004');
      sourceInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    mockHttpPost.mockResolvedValue({id: 5, source: '验收文档 2026-004'});
    const okBtn = Array.from(modal.querySelectorAll('.ant-modal-footer button'))
      .find(b => b.textContent.includes('建 档'));
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalled();
    const [url, payload] = mockHttpPost.mock.calls.find(c => c[0].includes('/config/baseline/'));
    expect(url).toBe('/api/equipment-lifecycle/systems/7/config/baseline/');
    expect(payload.source).toBe('验收文档 2026-004');
    expect(payload.items).toEqual([{param: 11, value: 42}]);
    // 成功后刷新建档状态与当前配置
    const urls = mockHttpGet.mock.calls.map(c => String(c[0]));
    expect(urls.some(u => u.includes('/systems/7/config/baseline/'))).toBe(true);
    expect(urls.some(u => u.endsWith('/systems/7/config/'))).toBe(true);
  });

  it('已建档展示建档身份（来源/建档人/时间）；不可建档展示后端拦截原因', async () => {
    const store = mountPage();
    mockHttpGet.mockImplementation((url) => {
      if (String(url).includes('/config/baseline/')) {
        return Promise.resolve({
          baseline: {
            id: 5, source: '验收文档 2026-004', established_by_name: '建档员',
            established_at: '2026-10-19 10:00:00', items: [{}, {}],
          },
          can_establish: false, block_reason: '该系统已建立初始配置',
        });
      }
      return defaultGet(url);
    });
    await act(async () => {
      store.selectSystem(7);
      await flush();
      await flush();
    });
    expect(container.textContent).toContain('已建档');
    expect(container.textContent).toContain('验收文档 2026-004');
    expect(container.textContent).toContain('建档员');
    expect(container.textContent).not.toContain('建立初始配置');
    // 未建档但后端拦截（已有配置值）
    mockHttpGet.mockImplementation((url) => {
      if (String(url).includes('/config/baseline/')) {
        return Promise.resolve({
          baseline: null, can_establish: false,
          block_reason: '该系统已有配置值（来自历史配置变更），保留原记录，不再补建初始配置',
        });
      }
      return defaultGet(url);
    });
    await act(async () => {
      store.fetchBaseline(7);
      await flush();
      await flush();
    });
    expect(container.textContent).toContain('保留原记录，不再补建初始配置');
  });

  it('无 baseline 权限的用户看不到建立初始配置按钮', async () => {
    const libs = require('libs');
    libs.Permission.isSuper = false;
    libs.hasPermission.mockImplementation(
      code => code !== 'equipment_lifecycle.config.baseline');
    const store = mountPage();
    await selectSystem(store);
    const btnTexts = Array.from(container.querySelectorAll('button')).map(b => b.textContent);
    expect(btnTexts.join('|')).not.toContain('建立初始配置');
    // 有 view 权限：维护页内容仍可见
    expect(container.textContent).toContain('参数定义维护');
    libs.Permission.isSuper = true;
  });
});

describe('系统配置维护入口 · 参数定义与记录变更', () => {
  it('新增参数 Modal 提交真实 payload（含分类与枚举选项）', async () => {
    const store = mountPage();
    await selectSystem(store);
    const addBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.includes('新增参数'));
    act(() => {
      addBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const modal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('新增参数定义'));
    expect(modal).toBeTruthy();
    expect(modal.textContent).toContain('硬件规格');
    const inputs = modal.querySelectorAll('.ant-form-item input.ant-input:not([readonly])');
    // 编码/名称/单位/备注按表单顺序
    const setNative = (el, value) => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(el, value);
      el.dispatchEvent(new Event('input', {bubbles: true}));
    };
    act(() => setNative(inputs[0], 'set_power'));
    act(() => setNative(inputs[1], '设定功率'));
    mockHttpPost.mockResolvedValue({id: 20, param_code: 'set_power'});
    const okBtn = Array.from(modal.querySelectorAll('.ant-modal-footer button'))
      .find(b => b.textContent.replace(/\s/g, '') === '保存');
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalled();
    const [url, payload] = mockHttpPost.mock.calls.find(c => c[0].includes('/config-params'));
    expect(url).toBe('/api/equipment-lifecycle/config-params/');
    expect(payload.param_code).toBe('set_power');
    // 默认分类为运行参数（表单初始值）
    expect(payload.category).toBe('runtime_param');
    expect(payload.enum_options).toEqual([]);
  });

  it('记录配置变更 Modal 提交真实 payload，成功后刷新配置与历史', async () => {
    const store = mountPage();
    await selectSystem(store);
    const addBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.includes('记录配置变更'));
    expect(addBtn).toBeTruthy();
    act(() => {
      addBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const modal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('记录配置变更'));
    expect(modal).toBeTruthy();
    const trigger = modal.querySelector('.ant-select-selector');
    await flush();
    act(() => {
      trigger.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await flush();
    const options = document.querySelectorAll('.ant-select-dropdown .ant-select-item-option');
    act(() => {
      options[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const numberInput = modal.querySelector('.ant-input-number input');
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(numberInput, '45');
      numberInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    const textareas = modal.querySelectorAll('textarea');
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      nativeSetter.call(textareas[0], '功率校准调整');
      textareas[0].dispatchEvent(new Event('input', {bubbles: true}));
    });
    mockHttpPost.mockResolvedValue({id: 99, change_no: 'PZ20261002-0009', status: 'draft'});
    const submitBtn = Array.from(modal.querySelectorAll('.ant-modal-footer button'))
      .find(b => b.textContent.includes('提 交'));
    await act(async () => {
      submitBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    const [url, payload] = mockHttpPost.mock.calls.find(c => c[0].includes('/config-changes/'));
    expect(url).toBe('/api/equipment-lifecycle/config-changes/');
    expect(payload.system).toBe(7);
    expect(payload.reason).toBe('功率校准调整');
    expect(payload.items).toEqual([{param: 11, new_value: 45, remark: ''}]);
    expect(payload.client_token).toBeTruthy();
  });
});

describe('系统配置维护入口 · 变更详情动作', () => {
  it('变更详情抽屉（非只读）展示快照并提交验证 payload', async () => {
    const store = mountPage();
    await selectSystem(store);
    const detailLink = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '详情');
    act(() => {
      detailLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    await flush();
    const drawer = document.querySelector('.ant-drawer');
    expect(drawer.textContent).toContain('PZ20261002-0001');
    expect(drawer.textContent).toContain('42.5');
    const verifyBtn = Array.from(drawer.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s/g, '') === '验证');
    expect(verifyBtn).toBeTruthy();
    act(() => {
      verifyBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const verifyModal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('验证配置变更'));
    mockHttpPost.mockResolvedValue({...DETAIL_RESPONSE, verify_status: 'passed', status: 'verified'});
    const okBtn = Array.from(verifyModal.querySelectorAll('.ant-modal-footer button'))
      .find(b => b.textContent.replace(/\s/g, '').toLowerCase() === 'ok');
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    const call = mockHttpPost.mock.calls.find(c => c[0].includes('/verify/'));
    expect(call[0]).toBe('/api/equipment-lifecycle/config-changes/31/verify/');
    expect(call[1]).toEqual({verify_status: 'passed', verify_note: ''});
  });

  it('回退经确认后调用 rollback 端点；业务错误不出现成功提示', async () => {
    const store = mountPage();
    await selectSystem(store);
    const detailLink = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '详情');
    act(() => {
      detailLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    await flush();
    const drawer = document.querySelector('.ant-drawer');
    const rollbackBtn = Array.from(drawer.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s/g, '') === '回退');
    act(() => {
      rollbackBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    mockHttpPost.mockRejectedValue('当前值已被其他变更修改');
    const okBtn = confirm.querySelector('.ant-modal-confirm-btns .ant-btn-primary');
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/config-changes/31/rollback/');
    expect(document.body.textContent).not.toContain('已回退并生成反向变更');
  });
});
