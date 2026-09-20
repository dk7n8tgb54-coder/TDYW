/**
 * 设备全生命周期（步骤 3.1，单系统简化）故障组件渲染测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 故障详情抽屉展示故障系统（名称+编号+安装地点快照）、影响程度、状态流转按钮随状态切换
 * - 详情不再提供"受影响系统"页签
 * - 处置记录时间线按时间展示，更正留痕可见
 * - 系统详情故障页签只展示本系统故障（不区分主体/受影响角色）
 * - 不使用旧 fault 页面/接口（所有请求只指向 equipment-lifecycle 前缀）
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
  occurred_at: '2026-09-18 08:30', discovery: 'patrol', discovery_text: '巡检发现',
  level: 'major', level_text: '严重', phenomenon: '主用链路频繁丢包',
  impact_scope: '话音业务', fault_location: '机房A 01柜',
  fault_object_name: '接入交换机01', fault_object_model: 'H3C-5120', fault_object_sn: '',
  fault_component: 3, fault_component_name: '接入交换机',
  reason_analysis: '', recovered_at: null, recover_confirm: '',
  recovered_by: null, recovered_by_name: '', recovered_confirmed_at: null,
  final_result: '', handler: 2, handler_name: 'operator',
  created_by_name: 'admin', created_at: '2026-09-18 08:40',
};

const HANDLING_RECORDS = {
  data: [
    {id: 1, fault: 11, handled_at: '2026-09-18 09:00', handler: 2, handler_name: 'operator',
      content: '现场检查，确认光模块告警', result: '处理中', corrections: [], created_at: '2026-09-18 09:05'},
    {id: 2, fault: 11, handled_at: '2026-09-18 09:30', handler: 2, handler_name: 'operator',
      content: '更换备用链路', result: '已切换', created_at: '2026-09-18 09:35',
      corrections: [{old: '更换主用链路', new: '更换备用链路', reason: '笔误', by: 'operator',
        at: '2026-09-18 09:40'}]},
  ],
  total: 2, page: 1, page_size: 100,
};

async function renderDetail(status) {
  const store = require('../faultStore').default;
  const FaultDetail = require('../FaultDetail').default;
  const detail = {...FAULT_DETAIL, status};
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/handling-records')) {
      return Promise.resolve(HANDLING_RECORDS);
    }
    // 详情接口：后端 json_response(详情) 经 http 拦截器解包后 resolve 详情本体
    // （旧 mock 多包一层 data 会固化 fetchDetail 的双重解包缺陷）
    return Promise.resolve(detail);
  });
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    store.detailId = 11;
    store.detailVisible = true;
    store.detail = detail;
    ReactDOM.render(<FaultDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

function bodyText() {
  // antd 两字按钮文案渲染为“作 废”（自动空格），比较前统一去空白
  return document.body.textContent.replace(/\s+/g, '');
}

function tabTexts() {
  return Array.from(document.querySelectorAll('.ant-tabs-tab')).map(t => t.textContent);
}

describe('故障详情抽屉（单系统简化）', () => {
  it('展示故障系统名称与编号/地点快照、影响程度与现象', async () => {
    await renderDetail('handling');
    const text = bodyText();
    expect(text).toContain('GZ20260918-0001');
    expect(text).toContain('烟台通信系统（SYS-A1）');
    expect(text).toContain('机房A');
    expect(text).toContain('主用链路频繁丢包');
    expect(text).toContain('巡检发现');
  });

  it('不再提供"受影响系统"页签', async () => {
    await renderDetail('handling');
    const tabs = tabTexts();
    expect(tabs.some(t => t.includes('受影响系统'))).toBe(false);
    expect(tabs).toEqual(expect.arrayContaining(['基本信息', '处置记录', '关联工单']));
  });

  it('状态按钮随当前状态切换：处置中显示确认恢复与作废', async () => {
    await renderDetail('handling');
    const text = bodyText();
    expect(text).toContain('确认恢复');
    expect(text).toContain('作废');
    expect(text).not.toContain('开始处置');
    expect(text).not.toContain('关闭故障');
  });

  it('待处置状态显示开始处置，已恢复状态显示关闭故障', async () => {
    await renderDetail('pending');
    expect(bodyText()).toContain('开始处置');
    // 同一容器复用：重设 store 后再次渲染已恢复状态
    await renderDetail('recovered');
    expect(bodyText()).toContain('关闭故障');
  });

  it('处置记录时间线按时间展示且更正留痕可见', async () => {
    await renderDetail('handling');
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
    const handlingTab = tabs.find(t => t.textContent.includes('处置记录'));
    await act(async () => {
      handlingTab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    const text = bodyText();
    expect(text).toContain('现场检查，确认光模块告警');
    expect(text).toContain('更换备用链路');
    // 更正留痕：原内容与原因
    expect(text).toContain('笔误');
    expect(text).toContain('由operator更正');
    // 更正按钮可见（可编辑状态）
    expect(text).toContain('更正');
    // 添加处置记录入口可见
    expect(text).toContain('添加处置记录');
  });

  it('所有请求只指向 equipment-lifecycle 前缀（不使用旧 fault 接口）', async () => {
    await renderDetail('handling');
    const urls = mockHttpGet.mock.calls.map(call => call[0]);
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) {
      expect(url.startsWith('/api/equipment-lifecycle/')).toBe(true);
    }
    expect(urls.some(u => u.includes('/fault/'))).toBe(false);
  });
});

describe('系统详情故障页签（单系统简化）', () => {
  it('只展示本系统故障，不再区分主体/受影响角色', async () => {
    const FaultRecordsTab = require('../FaultRecordsTab').default;
    mockHttpGet.mockResolvedValue({data: [
      {id: 21, fault_no: 'GZ20260918-0002', system: 9,
        impact_status: 'interrupted', status: 'pending',
        occurred_at: '2026-09-18 07:00', phenomenon: '系统中断'},
      {id: 23, fault_no: 'GZ20260918-0004', system: 9,
        impact_status: 'degraded', status: 'handling',
        occurred_at: '2026-09-18 06:00', phenomenon: '另一路链路降级'},
    ]});
    await act(async () => {
      ReactDOM.render(<FaultRecordsTab systemId={9}/>, container);
    });
    await act(async () => {await flush();});
    const text = document.body.textContent;
    expect(text).toContain('GZ20260918-0002');
    expect(text).toContain('GZ20260918-0004');
    expect(text).toContain('中断');
    expect(text).toContain('降级');
    // 不再出现角色标识
    expect(text).not.toContain('主体故障');
    expect(text).not.toContain('受影响故障');
    // 请求不再携带 role 参数
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/9/faults/');
  });
});
