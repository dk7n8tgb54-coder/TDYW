/**
 * 设备全生命周期（步骤二交互重构）系统详情与列表渲染测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http 与公共组件壳，
 * 验证：
 * - 详情抽屉页签：基本信息 / 配置字段 / 配置组成项 / 配置变更历史 / 配置快照
 *   （本步骤不出现故障、巡检、维护、工单、履历页签）
 * - 基本信息统一展示固定字段 + 类型模板字段值 + 系统自定义字段值
 *   （含停用字段历史值）
 * - 配置字段页签仅管理字段定义：说明文字、定义列表、不出现值录入与保存按钮
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

const DETAIL_PAYLOAD = {
  id: 5, system_code: 'SYS-001', name: '烟台中心站通信系统',
  system_type_name: '通信系统', system_model: 'HX-100',
  install_location: '烟台中心站机房A', geo_coordinate: '',
  system_purpose: '', manufacturer: '某通信设备厂', install_unit: '安装一队',
  use_unit: '运行一科', install_time: '2026-01-01 08:00', enable_time: '2026-02-01 09:00',
  responsible_user_name: '张三', health_status: 'normal', health_status_text: '正常',
  is_active: true, remark: '', created_by_name: 'admin', created_at: '2026-09-18 10:00',
  config_components_count: 2,
  config_fields: [
    {id: 101, scope_type: 'template', field_code: 'frequency', display_name: '工作频率',
      field_type: 'text', field_type_text: '文本', is_required: true, is_sensitive: false,
      is_active: true, help_text: '单位 MHz', display_order: 1,
      value: '438.000MHz', display: '438.000MHz'},
    {id: 102, scope_type: 'custom', field_code: 'antenna_h', display_name: '天线高度',
      field_type: 'number', field_type_text: '数字', is_required: false, is_sensitive: false,
      is_active: true, help_text: '', display_order: 2,
      value: 25, display: '25'},
    {id: 103, scope_type: 'template', field_code: 'old_band', display_name: '旧频段',
      field_type: 'choice', field_type_text: '单选', is_required: false, is_sensitive: false,
      is_active: false, help_text: '', display_order: 3,
      value: 'UHF', display: 'UHF'},
  ],
};

describe('系统详情抽屉', () => {
  function renderDetail() {
    const store = require('../store').default;
    const SystemDetail = require('../SystemDetail').default;
    store.detailId = 5;
    store.detailVisible = true;
    store.detail = DETAIL_PAYLOAD;
    store.isDetailFetching = false;
    mockHttpGet.mockResolvedValue(DETAIL_PAYLOAD);
    act(() => {
      ReactDOM.render(<SystemDetail/>, container);
    });
    return store;
  }

  it('页签随步骤演进：基础五页签 + 故障记录（3.1） + 三类运维台账（3.2） + 工单（3.3） + 系统履历（3.4）', () => {
    renderDetail();
    const text = document.body.textContent;
    expect(text).toContain('基本信息');
    expect(text).toContain('配置字段');
    expect(text).toContain('配置组成项');
    expect(text).toContain('配置变更历史');
    expect(text).toContain('配置快照');
    // 步骤 3.1：故障记录页签
    expect(text).toContain('故障记录');
    // 步骤 3.2：系统详情增加巡检/周月维护/季维护台账页签
    expect(text).toContain('巡检台账');
    expect(text).toContain('周月维护台账');
    expect(text).toContain('季维护台账');
    // 步骤 3.3：工单页签
    expect(text).toContain('工单');
    // 步骤 3.4：系统履历页签（统一履历；角色筛选断言见 systemEvent 组件测试）
    expect(text).toContain('系统履历');
    // 边界：不出现离线/二维码/移动端与系统升级入口
    expect(text).not.toContain('二维码');
    expect(text).not.toContain('离线');
    expect(text).not.toContain('移动端');
    expect(text).not.toContain('系统升级');
  });

  it('基本信息统一展示固定字段、模板字段值与自定义字段值（含停用历史值）', () => {
    renderDetail();
    const text = document.body.textContent;
    // 固定字段
    expect(text).toContain('SYS-001');
    expect(text).toContain('烟台中心站通信系统');
    expect(text).toContain('正常');
    expect(text).toContain('可用');
    // 分组标题
    expect(text).toContain('类型扩展字段');
    expect(text).toContain('系统自定义字段');
    // 模板字段值
    expect(text).toContain('工作频率');
    expect(text).toContain('438.000MHz');
    // 自定义字段值
    expect(text).toContain('天线高度');
    expect(text).toContain('25');
    // 停用字段历史值仍展示
    expect(text).toContain('旧频段');
    expect(text).toContain('已停用');
    expect(text).toContain('UHF');
  });

  it('配置字段页签仅管理字段定义，不出现值录入与保存按钮', async () => {
    const store = renderDetail();
    const tab = Array.from(document.body.querySelectorAll('.ant-tabs-tab'))
      .find(node => node.textContent.includes('配置字段'));
    await click(tab);
    await act(async () => {
      store.detail = DETAIL_PAYLOAD;
      store.isDetailFetching = false;
    });
    await flush();
    const text = document.body.textContent;
    // 职责说明
    expect(text).toContain('本页仅管理字段定义');
    expect(text).toContain('字段值在新增或编辑系统时填写');
    // 定义列表：模板字段与自定义字段分开展示
    expect(text).toContain('类型模板字段');
    expect(text).toContain('本系统自定义字段');
    expect(text).toContain('frequency');
    expect(text).toContain('antenna_h');
    // 不再有动态值编辑表单与保存按钮
    const activePane = document.body.querySelector('.ant-tabs-tabpane-active');
    expect(Array.from(activePane.querySelectorAll('button'))
      .some(b => b.textContent.replace(/\s/g, '') === '保存配置')).toBe(false);
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
