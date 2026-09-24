/**
 * 设备全生命周期（步骤二交互重构）系统详情与列表渲染测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http 与公共组件壳，
 * 验证：
 * - 详情抽屉页签：基本信息 / 故障记录 / 升级记录 / 台账 / 工单 / 履历
 *   （自定义字段机制已下线，「系统当前配置」页签一并移除）
 * - 基本信息展示固定字段；扩展信息展示 呼号/安装经纬度/工作频率（选填）
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
  system_model: 'HX-100',
  install_location: '烟台中心站机房A', geo_coordinate: '121.5,37.5',
  callsign: 'XZ5792', work_frequency: '438.500MHz',
  system_purpose: '', manufacturer: '某通信设备厂', install_unit: '安装一队',
  use_unit: '运行一科', install_time: '2026-01-01', enable_time: '2026-02-01',
  responsible_user_name: '张三', health_status: 'normal', health_status_text: '正常',
  is_active: true, remark: '', created_by_name: 'admin', created_at: '2026-09-18 10:00',
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

  it('页签随步骤演进：基础页签 + 故障记录（3.1） + 三类运维台账（3.2） + 工单（3.3） + 系统履历（3.4）', () => {
    renderDetail();
    const text = document.body.textContent;
    expect(text).toContain('基本信息');
    // 自定义字段机制已下线：「系统当前配置」页签不再渲染
    expect(text).not.toContain('系统当前配置');
    // 配置组成项/配置变更历史/配置快照已下线，页签不再渲染
    expect(text).not.toContain('配置组成项');
    expect(text).not.toContain('配置变更历史');
    expect(text).not.toContain('配置快照');
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

  it('基本信息展示固定字段；扩展信息展示呼号/安装经纬度/工作频率（选填）', () => {
    renderDetail();
    const text = document.body.textContent;
    // 固定字段（系统编号由后端自动生成，前端不展示）
    expect(text).not.toContain('SYS-001');
    expect(text).toContain('烟台中心站通信系统');
    expect(text).toContain('正常');
    expect(text).toContain('可用');
    // 自定义字段机制已下线：不再出现自定义字段区块
    expect(text).not.toContain('系统自定义字段');
    // 扩展信息固定字段（含值回显）
    expect(text).toContain('扩展信息');
    expect(text).toContain('呼号');
    expect(text).toContain('XZ5792');
    expect(text).toContain('安装经纬度');
    expect(text).toContain('121.5,37.5');
    expect(text).toContain('工作频率');
    expect(text).toContain('438.500MHz');
  });

  it('扩展信息空值以"-"占位且不提供自定义字段管理入口', () => {
    const store = require('../store').default;
    const SystemDetail = require('../SystemDetail').default;
    store.detailId = 6;
    store.detailVisible = true;
    store.detail = {...DETAIL_PAYLOAD, id: 6, callsign: '', geo_coordinate: '', work_frequency: ''};
    store.isDetailFetching = false;
    act(() => {
      ReactDOM.render(<SystemDetail/>, container);
    });
    const text = document.body.textContent;
    expect(text).toContain('扩展信息');
    expect(text).not.toContain('添加自定义字段');
    expect(text).not.toContain('新增配置字段');
    expect(text).not.toContain('编辑当前配置');
    // 空值占位：标签仍在，值显示 -
    const labels = Array.from(document.body.querySelectorAll('.ant-descriptions-item-label'));
    const callsignLabel = labels.find(n => n.textContent.includes('呼号'));
    expect(callsignLabel).toBeTruthy();
    expect(callsignLabel.nextElementSibling.textContent).toBe('-');
  });
});

describe('系统列表操作列', () => {
  it('按记录状态渲染停用/启用按钮并触发请求', async () => {
    const store = require('../store').default;
    const ComTable = require('../Table').default;
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) {
        return Promise.resolve({data: [
          {id: 1, system_code: 'SYS-001', name: '系统甲',
            system_model: 'HX-100', install_location: '机房A', use_unit: '运行一科',
            responsible_user_name: '张三', health_status: 'normal', health_status_text: '正常',
            is_active: true},
          {id: 2, system_code: 'SYS-002', name: '系统乙',
            system_model: 'HX-200', install_location: '机房B', use_unit: '运行二科',
            responsible_user_name: '李四', health_status: 'fault', health_status_text: '故障',
            is_active: false},
        ], total: 2});
      }
      return Promise.resolve({data: []});
    });
    act(() => {
      ReactDOM.render(<ComTable/>, container);
    });
    await flush();
    expect(container.textContent).toContain('系统甲');
    expect(container.textContent).toContain('系统乙');
    expect(container.textContent).not.toContain('SYS-001');
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

describe('系统列表部件维护提示（运行状态与部件维修分离）', () => {
  it('列表同时展示系统运行健康状态与部件维护标签（部件故障/部件维修中）', async () => {
    const SystemTable = require('../Table').default;
    const row = {
      id: 1, name: '烟台通信系统', system_model: 'HX-100', install_location: '机房A',
      use_unit: '运行一科', responsible_user_name: '张三', is_active: true,
      health_status: 'normal', health_status_text: '正常',
      component_maintenance: {fault_count: 2, repairing_count: 1},
    };
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems')) {
        // http 拦截器解包后 resolve {data: 行数组, total}
        return Promise.resolve({data: [row], total: 1, page: 1, page_size: 10});
      }
      return Promise.resolve({data: {}});
    });
    await act(async () => {
      ReactDOM.render(<SystemTable/>, container);
    });
    await act(flush);
    const text = document.body.textContent.replace(/\s+/g, '');
    // 系统运行状态（正常）与部件维护提示并列展示，互不混淆
    expect(text).toContain('正常');
    expect(text).toContain('部件故障2');
    expect(text).toContain('部件维修中1');
    // 无部件维护时不出空标签
    expect(text).not.toContain('部件故障0');
    expect(text).not.toContain('部件维修中0');
  });

  it('系统详情"当前状态"展示部件维护提示', async () => {
    const store = require('../store').default;
    const SystemDetail = require('../SystemDetail').default;
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) return Promise.resolve({data: DETAIL_PAYLOAD});
      return Promise.resolve({data: {}});
    });
    store.detail = {...DETAIL_PAYLOAD,
      component_maintenance: {fault_count: 1, repairing_count: 0}};
    store.detailVisible = true;
    await act(async () => {
      ReactDOM.render(<SystemDetail/>, container);
    });
    await act(flush);
    const text = document.body.textContent.replace(/\s+/g, '');
    expect(text).toContain('部件故障1');
    expect(text).not.toContain('部件维修中');
  });
});
