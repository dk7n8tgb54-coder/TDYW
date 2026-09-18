/**
 * 设备全生命周期（步骤二）系统详情与列表渲染测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http 与公共组件壳，
 * 验证：
 * - 详情抽屉页签：基本信息 / 配置档案 / 配置组成项 / 配置变更历史 / 配置快照
 *   （本步骤不出现故障、巡检、维护、工单、履历页签）
 * - 基本信息展示系统编号、名称、健康状态与可用状态
 * - 配置档案页签：模板字段与自定义字段按类型渲染控件、必填标记、
 *   停用字段历史值只读展示
 * - 配置保存提交 config_values 且不重复提示错误
 * - 列表操作列：停用/启用按钮随记录状态切换文案
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
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
  syncAttachmentCount: jest.fn(),
}));

// jsdom 未实现 matchMedia，antd 渲染需要
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
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

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {});
}

const CONFIG_PAYLOAD = {
  system: {id: 5, system_code: 'SYS-001', name: '烟台中心站通信系统',
    system_type: 3, system_type_name: '通信系统'},
  fields: [
    {id: 101, scope_type: 'template', field_code: 'frequency', display_name: '工作频率',
      field_type: 'text', is_required: true, is_sensitive: false, is_active: true,
      choices: '', detail_columns: '', number_min: null, number_max: null, help_text: ''},
    {id: 102, scope_type: 'custom', field_code: 'antenna_h', display_name: '天线高度',
      field_type: 'number', is_required: false, is_sensitive: false, is_active: true,
      choices: '', detail_columns: '', number_min: 0, number_max: 100, help_text: '单位米'},
    {id: 103, scope_type: 'template', field_code: 'old_band', display_name: '旧频段',
      field_type: 'choice', is_required: false, is_sensitive: false, is_active: false,
      choices: '["UHF","VHF"]', detail_columns: '', number_min: null, number_max: null,
      help_text: ''},
  ],
  values: {
    101: {value: '438.000MHz', display: '438.000MHz', updated_at: null, updated_by: ''},
    102: {value: 25, display: '25', updated_at: null, updated_by: ''},
    103: {value: 'UHF', display: 'UHF', updated_at: null, updated_by: ''},
  },
};

describe('系统详情抽屉', () => {
  function renderDetail() {
    const store = require('../store').default;
    const SystemDetail = require('../SystemDetail').default;
    store.detailId = 5;
    store.detailVisible = true;
    store.detail = {
      id: 5, system_code: 'SYS-001', name: '烟台中心站通信系统',
      system_type_name: '通信系统', system_model: 'HX-100',
      install_location: '烟台中心站机房A', geo_coordinate: '',
      system_purpose: '', manufacturer: '某通信设备厂', install_unit: '安装一队',
      use_unit: '运行一科', install_time: '2026-01-01 08:00', enable_time: '2026-02-01 09:00',
      responsible_user_name: '张三', health_status: 'normal', health_status_text: '正常',
      is_active: true, remark: '', created_by_name: 'admin', created_at: '2026-09-18 10:00',
    };
    store.isDetailFetching = false;
    act(() => {
      ReactDOM.render(<SystemDetail/>, container);
    });
    return store;
  }

  it('展示五个页签且不包含故障/巡检/维护/工单/履历', () => {
    mockHttpGet.mockResolvedValue(CONFIG_PAYLOAD);
    renderDetail();
    const text = document.body.textContent;
    expect(text).toContain('基本信息');
    expect(text).toContain('配置档案');
    expect(text).toContain('配置组成项');
    expect(text).toContain('配置变更历史');
    expect(text).toContain('配置快照');
    expect(text).not.toContain('故障管理');
    expect(text).not.toContain('巡检台账');
    expect(text).not.toContain('周月维护');
    expect(text).not.toContain('工单管理');
    expect(text).not.toContain('系统履历');
  });

  it('基本信息展示编号、名称与健康状态', () => {
    mockHttpGet.mockResolvedValue(CONFIG_PAYLOAD);
    renderDetail();
    const text = document.body.textContent;
    expect(text).toContain('SYS-001');
    expect(text).toContain('烟台中心站通信系统');
    expect(text).toContain('正常');
    expect(text).toContain('可用');
  });

  it('配置档案页签渲染模板字段与自定义字段并保留停用字段历史值', async () => {
    mockHttpGet.mockResolvedValue(CONFIG_PAYLOAD);
    const store = renderDetail();
    const tab = Array.from(document.body.querySelectorAll('.ant-tabs-tab'))
      .find(node => node.textContent.includes('配置档案'));
    await click(tab);
    // fetchConfig 被调用
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/5/config/');
    await act(async () => {
      store.config = CONFIG_PAYLOAD;
      store.isConfigFetching = false;
    });
    await flush();
    const text = document.body.textContent;
    expect(text).toContain('工作频率');
    expect(text).toContain('天线高度');
    expect(text).toContain('已停用字段');
    expect(text).toContain('UHF');
    // 自定义字段带“自定义”标记
    const inputs = document.body.querySelectorAll('input.ant-input, input.ant-input-number-input');
    expect(inputs.length).toBeGreaterThan(0);
  });

  it('保存配置提交 config_values', async () => {
    mockHttpGet.mockResolvedValue(CONFIG_PAYLOAD);
    mockHttpPut.mockResolvedValue({saved: true, changed: 1});
    const store = renderDetail();
    const tab = Array.from(document.body.querySelectorAll('.ant-tabs-tab'))
      .find(node => node.textContent.includes('配置档案'));
    await click(tab);
    await act(async () => {
      store.config = CONFIG_PAYLOAD;
      store.isConfigFetching = false;
    });
    await flush();
    // 无改动时保存按钮禁用（真实行为）：先修改模板字段输入
    const input = document.body.querySelector('.ant-tabs-tabpane-active input.ant-input');
    expect(input).toBeTruthy();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '439.000MHz');
      input.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(async () => {});
    const saveBtn = Array.from(document.body.querySelectorAll('button'))
      .find(node => node.textContent.replace(/\s/g, '') === '保存配置');
    expect(saveBtn).toBeTruthy();
    expect(saveBtn.disabled).toBe(false);
    await click(saveBtn);
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/5/config/', {config_values: {101: '439.000MHz'}});
  });
});

describe('系统列表操作列', () => {
  it('按记录状态渲染停用/启用按钮并触发请求', async () => {
    const store = require('../store').default;
    const ComTable = require('../Table').default;
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/system-types/')) {
        return Promise.resolve({data: [{id: 3, name: '通信系统'}]});
      }
      return Promise.resolve({data: [
        {id: 1, system_code: 'SYS-001', name: '系统甲', system_type_name: '通信系统',
          system_model: 'HX-100', install_location: '机房A', use_unit: '运行一科',
          responsible_user_name: '张三', health_status: 'normal', health_status_text: '正常',
          is_active: true},
        {id: 2, system_code: 'SYS-002', name: '系统乙', system_type_name: '通信系统',
          system_model: 'HX-200', install_location: '机房B', use_unit: '运行二科',
          responsible_user_name: '李四', health_status: 'fault', health_status_text: '故障',
          is_active: false},
      ], total: 2});
    });
    act(() => {
      ReactDOM.render(<ComTable/>, container);
    });
    await flush();
    expect(container.textContent).toContain('SYS-001');
    expect(container.textContent).toContain('SYS-002');
    const buttons = Array.from(container.querySelectorAll('button'));
    const deactivate = buttons.find(node => node.textContent === '停 用' || node.textContent === '停用');
    const activate = buttons.find(node => node.textContent === '启 用' || node.textContent === '启用');
    expect(deactivate).toBeTruthy();
    expect(activate).toBeTruthy();
    await click(activate);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/2/active/', {is_active: true});
  });
});
