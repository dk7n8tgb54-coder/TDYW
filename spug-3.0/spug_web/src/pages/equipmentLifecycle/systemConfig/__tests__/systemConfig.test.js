/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 */
/**
 * 系统详情 → 配置页签（只读，2026-10-19 起）组件渲染测试。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 页签只读：不提供"记录配置变更"等任何写入口，提供跳转维护入口的链接；
 * - 当前配置按 硬件规格/运行参数 分类展示，建档信息（来源/建档人/时间）可见；
 * - 变更历史请求指向 systems/<id>/config/changes/，筛选参数（状态）生效；
 * - 变更详情抽屉为只读：展示前后值快照，隐藏应用/验证/回退/取消/附件写操作；
 * - 无权限用户不渲染页签内容（AuthDiv 拦截）。
 * 写操作（记录变更/建档/处理变更）的行为测试见
 * systemConfigMaintain/__tests__/systemConfigMaintain.test.js。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {MemoryRouter} from 'react-router-dom';
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
  document.querySelectorAll('.ant-modal, .ant-dropdown, .ant-select-dropdown, .ant-message, .ant-drawer-mask').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const CONFIG_RESPONSE = {
  system: {id: 7, name: 'DVOR系统', system_code: 'SYS-001'},
  baseline: null,
  items: [
    {
      param: 11, param_code: 'rated_power', param_name: '系统额定功率', category: 'hardware_spec',
      category_text: '硬件规格', data_type: 'number', data_type_text: '数字', unit: 'kW',
      is_required: false, options: [], value_text: '', value_number: '3.5', value_bool: null,
      value_date: null, value_choice: '', display_value: '3.5',
      effective_at: '2026-10-01 08:00:00', last_change_id: 3,
      last_change_no: 'PZ20261001-0001', last_changed_by_name: 'admin',
      source_text: '配置变更 PZ20261001-0001',
    },
    {
      param: 12, param_code: 'work_mode', param_name: '工作模式', category: 'runtime_param',
      category_text: '运行参数', data_type: 'choice', data_type_text: '枚举', unit: '',
      is_required: false, options: ['主用', '备用'], value_text: '', value_number: null,
      value_bool: null, value_date: null, value_choice: '主用', display_value: '主用',
      effective_at: null, last_change_id: null, last_change_no: '',
      last_changed_by_name: '', source_text: '初始建档',
    },
    {
      param: 13, param_code: 'set_power', param_name: '设定功率', category: 'runtime_param',
      category_text: '运行参数', data_type: 'number', data_type_text: '数字', unit: 'kW',
      is_required: false, options: [], value_text: '', value_number: null, value_bool: null,
      value_date: null, value_choice: '', display_value: '未设置', effective_at: null,
      last_change_id: null, last_change_no: '', last_changed_by_name: '', source_text: '',
    },
  ],
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
    ReactDOM.render(
      <MemoryRouter><SystemConfigTab systemId={7}/></MemoryRouter>, container);
  });
  return store;
}

describe('系统配置页签（只读） · 渲染与筛选', () => {
  it('按硬件规格/运行参数分类展示当前配置，并渲染变更历史', async () => {
    mountTab();
    await flush();
    await flush();
    const text = container.textContent;
    expect(text).toContain('当前配置');
    expect(text).toContain('硬件规格');
    expect(text).toContain('运行参数');
    // 当前配置行：参数名称/当前值/单位/类型/来源/生效时间/变更人
    expect(text).toContain('系统额定功率');
    expect(text).toContain('3.5');
    expect(text).toContain('kW');
    expect(text).toContain('配置变更 PZ20261001-0001');
    expect(text).toContain('初始建档');
    expect(text).toContain('2026-10-01 08:00:00');
    // 分类拆分：硬件规格区只有额定功率（工作模式/设定功率归运行参数区）
    const hardwareTable = Array.from(container.querySelectorAll('.ant-table'))
      .find(t => t.textContent.includes('系统额定功率'));
    expect(hardwareTable.textContent).not.toContain('工作模式');
    // 变更历史行
    expect(text).toContain('PZ20261002-0001');
    expect(text).toContain('功率校准');
  });

  it('只读页签：无任何写入口，提供前往维护入口的跳转链接', async () => {
    mountTab();
    await flush();
    await flush();
    const btnTexts = Array.from(container.querySelectorAll('button')).map(b => b.textContent);
    expect(btnTexts.join('|')).not.toContain('记录配置变更');
    const jump = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent.includes('前往系统配置维护'));
    expect(jump).toBeTruthy();
    expect(jump.getAttribute('href')).toBe('/el/system-config?system=7');
  });

  it('未建档显示"未建档"标记；已建档展示建档身份', async () => {
    mountTab();
    await flush();
    await flush();
    expect(container.textContent).toContain('未建档');
    // 已建档：CONFIG_RESPONSE 返回 baseline 摘要
    const store = require('../store').default;
    act(() => {
      store.configBaseline = {
        id: 5, source: '验收文档', established_by_name: '建档员',
        established_at: '2026-10-19 10:00:00',
      };
    });
    await flush();
    expect(container.textContent).toContain('初始建档：验收文档');
    expect(container.textContent).toContain('建档员');
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

describe('系统配置页签（只读） · 变更详情抽屉', () => {
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

  it('详情抽屉展示前后值快照，且隐藏全部写操作（应用/验证/回退/取消/附件）', async () => {
    await openDetail();
    const drawer = document.querySelector('.ant-drawer');
    expect(drawer).toBeTruthy();
    expect(drawer.textContent).toContain('PZ20261002-0001');
    expect(drawer.textContent).toContain('功率校准');
    expect(drawer.textContent).toContain('40');
    expect(drawer.textContent).toContain('42.5');
    expect(drawer.textContent).toContain('上调 2.5dB');
    // 只读：不渲染任何动作按钮与附件上传
    const btnTexts = Array.from(drawer.querySelectorAll('button')).map(b => b.textContent);
    const joined = btnTexts.map(t => t.replace(/\s/g, '')).join('|');
    expect(joined).not.toContain('验证');
    expect(joined).not.toContain('回退');
    expect(joined).not.toContain('应用变更');
    expect(joined).not.toContain('取消变更');
    expect(joined).not.toContain('上传附件');
  });
});
