/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统配置（系统详情 → 配置页签）组件渲染测试（2026-10）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 页签同时渲染当前配置与配置变更历史两个信息区域，无独立页面入口；
 * - 当前配置表格展示 参数名称/当前值/单位/数据类型/最后生效时间/最后变更人；
 * - 变更历史请求指向 systems/<id>/config/changes/，筛选参数（状态/时间）生效；
 * - 记录配置变更 Modal 提交真实 payload（system/reason/items/纳入履历/client_token），
 *   成功后刷新当前配置与历史；纳入履历必须填原因（客户端拦截不发请求）；
 * - 变更详情抽屉展示前后值快照，动作按钮随状态与权限显隐，
 *   应用/验证/回退/取消调用对应动作端点；
 * - 业务错误（HTTP 200 + error）时 Promise 拒绝，不提示成功；
 * - 无权限用户不渲染页签内容与操作按钮。
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
  // jest mockReset 会清除默认实现：每个用例前显式恢复"有权限"
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
  document.querySelectorAll('.ant-modal, .ant-dropdown, .ant-select-dropdown, .ant-message').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const CONFIG_RESPONSE = {
  system: {id: 7, name: 'DVOR系统', system_code: 'SYS-001'},
  items: [
    {
      param: 11, param_code: 'tx_power', param_name: '发射功率', data_type: 'number',
      data_type_text: '数字', unit: 'dB', is_required: false, options: [],
      value_text: '', value_number: '42.5', value_bool: null, value_date: null,
      value_choice: '', display_value: '42.5', effective_at: '2026-10-01 08:00:00',
      last_change_id: 3, last_change_no: 'PZ20261001-0001', last_changed_by_name: 'admin',
    },
    {
      param: 12, param_code: 'work_mode', param_name: '工作模式', data_type: 'choice',
      data_type_text: '枚举', unit: '', is_required: false, options: ['主用', '备用'],
      value_text: '', value_number: null, value_bool: null, value_date: null,
      value_choice: '主用', display_value: '主用', effective_at: null,
      last_change_id: null, last_change_no: '', last_changed_by_name: '',
    },
    {
      param: 13, param_code: 'auto_switch', param_name: '自动切换', data_type: 'bool',
      data_type_text: '布尔', unit: '', is_required: false, options: [],
      value_text: '', value_number: null, value_bool: true, value_date: null,
      value_choice: '', display_value: 'true', effective_at: '2026-10-01 09:00:00',
      last_change_id: 4, last_change_no: 'PZ20261001-0002', last_changed_by_name: 'admin',
    },
  ],
};

const CHANGES_RESPONSE = {
  total: 1, page: 1, page_size: 10,
  items: [{
    id: 31, change_no: 'PZ20261002-0001', system: 7, system_name: 'DVOR系统',
    reason: '功率校准', status: 'applied', status_text: '已生效',
    applied_at: '2026-10-02 08:30:00', verify_status: '', verify_status_text: '未验证',
    verified_at: null, verified_by_name: '', include_in_history: false,
    history_reason: '', rollback_of: null, rollback_of_no: '',
    created_by_name: 'admin', created_at: '2026-10-02 08:00:00',
  }],
};

const DETAIL_RESPONSE = {
  id: 31, change_no: 'PZ20261002-0001', system: 7, system_name: 'DVOR系统',
  reason: '功率校准', status: 'applied', status_text: '已生效',
  applied_at: '2026-10-02 08:30:00', applied_by_name: 'admin',
  verify_status: '', verify_status_text: '未验证', verify_note: '功率计实测',
  verified_at: null, verified_by_name: '', include_in_history: false,
  history_reason: '', rollback_of: null, rollback_of_no: '', rollback_changes: [],
  cancelled_at: null, cancelled_by_name: '', client_token: 'tok-x',
  created_by_name: 'admin', created_at: '2026-10-02 08:00:00', updated_at: null,
  items: [{
    id: 51, param: 11, param_code: 'tx_power', param_name: '发射功率',
    data_type: 'number', data_type_text: '数字', unit: 'dB',
    old_value: '40', new_value: '42.5', verify_status: '', verify_status_text: '',
    remark: '上调 2.5dB',
  }],
};

function mountTab() {
  const SystemConfigTab = require('../SystemConfigTab').default;
  const store = require('../store').default;
  mockHttpGet.mockImplementation((url) => {
    if (String(url).includes('/config/changes/')) {
      return Promise.resolve(CHANGES_RESPONSE);
    }
    if (String(url).endsWith('/config/')) {
      return Promise.resolve(CONFIG_RESPONSE);
    }
    if (String(url).includes('/config-changes/31')) {
      return Promise.resolve(DETAIL_RESPONSE);
    }
    if (String(url).includes('/attachments')) {
      return Promise.resolve({data: []});
    }
    return Promise.resolve({});
  });
  act(() => {
    ReactDOM.render(<SystemConfigTab systemId={7}/>, container);
  });
  return store;
}

describe('系统配置页签 · 渲染与筛选', () => {
  it('同页签渲染当前配置与变更历史两个区域，并展示全部列', async () => {
    mountTab();
    await flush();
    await flush();
    const text = container.textContent;
    expect(text).toContain('当前配置');
    expect(text).toContain('配置变更历史');
    // 当前配置行：参数名称/当前值/单位/类型/生效时间/变更人
    expect(text).toContain('发射功率');
    expect(text).toContain('42.5');
    expect(text).toContain('dB');
    expect(text).toContain('数字');
    expect(text).toContain('2026-10-01 08:00:00');
    expect(text).toContain('admin');
    // 枚举与布尔展示
    expect(text).toContain('工作模式');
    expect(text).toContain('主用');
    // 变更历史行
    expect(text).toContain('PZ20261002-0001');
    expect(text).toContain('功率校准');
    expect(text).toContain('已生效');
    expect(text).toContain('未验证');
    expect(text).toContain('未纳入');
    // 记录配置变更只是 Modal 操作入口（按钮，不存在独立页面链接）
    const addBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.includes('记录配置变更'));
    expect(addBtn).toBeTruthy();
  });

  it('变更历史请求携带分页与筛选参数', async () => {
    const store = mountTab();
    await flush();
    await flush();
    mockHttpGet.mockClear();
    act(() => {
      store.f_status = 'applied';
      store.fetchChanges(7);
    });
    await flush();
    const [url, config] = mockHttpGet.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/systems/7/config/changes/');
    expect(config.params).toEqual({page: 1, page_size: 10, status: 'applied'});
  });

  it('无权限用户不渲染页签内容（AuthDiv 拦截）', async () => {
    const libs = require('libs');
    libs.hasPermission.mockImplementation(() => false);
    mountTab();
    await flush();
    expect(container.textContent).not.toContain('当前配置');
  });
});

describe('系统配置页签 · 记录配置变更 Modal', () => {
  function openModal() {
    mountTab();
    return flush().then(() => flush()).then(() => {
      const addBtn = Array.from(container.querySelectorAll('button'))
        .find(b => b.textContent.includes('记录配置变更'));
      act(() => {
        addBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      });
      return flush();
    });
  }

  it('打开 Modal 并提交真实 payload，成功后刷新配置与历史', async () => {
    await openModal();
    const modal = document.querySelector('.ant-modal');
    expect(modal).toBeTruthy();
    expect(modal.textContent).toContain('记录配置变更');
    // 添加参数行并选择第一个参数（直接操作下拉项，真实用户路径）
    const addRowBtn = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.includes('添加参数'));
    act(() => {
      addRowBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    const trigger = modal.querySelector('.ant-select-selector');
    expect(trigger).toBeTruthy();
    await flush();
    act(() => {
      trigger.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await flush();
    const options = document.querySelectorAll('.ant-select-dropdown .ant-select-item-option');
    expect(options.length).toBe(3);
    act(() => {
      options[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    // 选中的是 tx_power（数字参数），填写变更后值与原因
    const numberInput = modal.querySelector('.ant-input-number input');
    expect(numberInput).toBeTruthy();
    await flush();
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
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalled();
    const [url, payload] = mockHttpPost.mock.calls.find(c => c[0].includes('/config-changes/'));
    expect(url).toBe('/api/equipment-lifecycle/config-changes/');
    expect(payload.system).toBe(7);
    expect(payload.reason).toBe('功率校准调整');
    expect(payload.items).toEqual([{param: 11, new_value: 45, remark: ''}]);
    expect(payload.include_in_history).toBe(false);
    expect(payload.client_token).toBeTruthy();
    // 成功后刷新当前配置与变更历史
    const refreshCalls = mockHttpGet.mock.calls.filter(c => String(c[0]).includes('/systems/7/'));
    expect(refreshCalls.length).toBeGreaterThanOrEqual(2);
  });

  it('纳入系统履历必须填写原因，缺原因被校验拦截不发请求', async () => {
    await openModal();
    const modal = document.querySelector('.ant-modal');
    // 开启"纳入系统履历"开关
    const switchBtn = modal.querySelector('button.ant-switch');
    expect(switchBtn).toBeTruthy();
    act(() => {
      switchBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    // 不填纳入原因 → 提交被 antd 校验拦截（表单 error），不发 POST
    mockHttpPost.mockResolvedValue({});
    const submitBtn = Array.from(modal.querySelectorAll('.ant-modal-footer button'))
      .find(b => b.textContent.includes('提 交'));
    await act(async () => {
      submitBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(modal.textContent).toContain('纳入系统履历的重要变更必须填写原因');
  });
});

describe('系统配置页签 · 变更详情抽屉与动作', () => {
  function openDetail() {
    mountTab();
    return flush().then(() => flush()).then(() => {
      const detailLink = Array.from(container.querySelectorAll('a'))
        .find(a => a.textContent === '详情');
      act(() => {
        detailLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      });
      return flush().then(() => flush());
    });
  }

  it('详情抽屉展示前后值快照，已生效状态显示验证与回退按钮', async () => {
    await openDetail();
    const drawer = document.querySelector('.ant-drawer');
    expect(drawer).toBeTruthy();
    expect(drawer.textContent).toContain('PZ20261002-0001');
    expect(drawer.textContent).toContain('功率校准');
    expect(drawer.textContent).toContain('40');
    expect(drawer.textContent).toContain('42.5');
    expect(drawer.textContent).toContain('上调 2.5dB');
    // applied 状态：验证 + 回退按钮可见；草稿动作不可见
    const btnTexts = Array.from(drawer.querySelectorAll('button')).map(b => b.textContent);
    expect(btnTexts.map(t => t.replace(/\s/g, '')).join('|')).toContain('验证');
    expect(btnTexts.map(t => t.replace(/\s/g, '')).join('|')).toContain('回退');
    expect(btnTexts.map(t => t.replace(/\s/g, '')).join('|')).not.toContain('应用变更');
  });

  it('验证提交 verify payload（通过）', async () => {
    await openDetail();
    const drawer = document.querySelector('.ant-drawer');
    const verifyBtn = Array.from(drawer.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s/g, '') === '验证');
    act(() => {
      verifyBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const verifyModal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('验证配置变更'));
    expect(verifyModal).toBeTruthy();
    mockHttpPost.mockResolvedValue({...DETAIL_RESPONSE, verify_status: 'passed', status: 'verified'});
    const okBtn = Array.from(verifyModal.querySelectorAll('.ant-modal-footer button'))
      .find(b => b.textContent.replace(/\s/g, '').toLowerCase() === 'ok');
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    const call = mockHttpPost.mock.calls.find(c => c[0].includes('/verify/'));
    expect(call).toBeTruthy();
    expect(call[0]).toBe('/api/equipment-lifecycle/config-changes/31/verify/');
    expect(call[1]).toEqual({verify_status: 'passed', verify_note: ''});
  });

  it('回退经确认后调用 rollback 端点', async () => {
    await openDetail();
    const drawer = document.querySelector('.ant-drawer');
    const rollbackBtn = Array.from(drawer.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s/g, '') === '回退');
    act(() => {
      rollbackBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    expect(confirm.textContent).toContain('反向配置变更');
    mockHttpPost.mockResolvedValue({id: 40, change_no: 'PZ20261002-0002', status: 'applied'});
    const okBtn = confirm.querySelector('.ant-modal-confirm-btns .ant-btn-primary');
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/config-changes/31/rollback/');
  });

  it('业务错误（HTTP 200 + error）时 Promise 拒绝，不出现成功提示', async () => {
    await openDetail();
    const drawer = document.querySelector('.ant-drawer');
    const rollbackBtn = Array.from(drawer.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s/g, '') === '回退');
    act(() => {
      rollbackBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    mockHttpPost.mockRejectedValue('当前值已被其他变更修改');
    const okBtn = document.querySelector('.ant-modal-confirm-btns .ant-btn-primary');
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    // 错误由 http 拦截器提示，业务层不弹成功提示
    expect(document.body.textContent).not.toContain('已回退并生成反向变更');
  });
});

describe('系统配置页签 · 权限控制', () => {
  it('无 apply 权限的用户看不到应用按钮（草稿详情）', async () => {
    const libs = require('libs');
    libs.Permission.isSuper = false;  // 关闭超管直通，走权限码判断
    libs.hasPermission.mockImplementation((code) => code !== 'equipment_lifecycle.config.apply');
    const SystemConfigTab = require('../SystemConfigTab').default;
    mockHttpGet.mockImplementation((url) => {
      if (String(url).includes('/config/changes/')) return Promise.resolve(CHANGES_RESPONSE);
      if (String(url).endsWith('/config/')) return Promise.resolve(CONFIG_RESPONSE);
      return Promise.resolve({
        ...DETAIL_RESPONSE, status: 'draft', status_text: '草稿',
      });
    });
    act(() => {
      ReactDOM.render(<SystemConfigTab systemId={7}/>, container);
    });
    await flush();
    await flush();
    const detailLink = Array.from(container.querySelectorAll('a')).find(a => a.textContent === '详情');
    act(() => {
      detailLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    await flush();
    const drawer = document.querySelector('.ant-drawer');
    const btnTexts = Array.from(drawer.querySelectorAll('button')).map(b => b.textContent);
    // 无 apply 权限：应用变更按钮不渲染；取消（edit 权限）仍渲染
    expect(btnTexts.map(t => t.replace(/\s/g, '')).join('|')).not.toContain('应用变更');
    expect(btnTexts.map(t => t.replace(/\s/g, '')).join('|')).toContain('取消变更');
    libs.Permission.isSuper = true;  // 恢复，避免影响同文件其他用例
  });
});
