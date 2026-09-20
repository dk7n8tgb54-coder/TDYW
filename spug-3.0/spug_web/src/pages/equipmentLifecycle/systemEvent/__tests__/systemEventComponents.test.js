/**
 * 设备全生命周期（步骤 3.4，单系统简化）统一系统履历——组件渲染测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http 与公共组件壳，验证：
 * - 履历列表渲染事件类型/来源/摘要，故障来源渲染跳转链接（不再有角色列）
 * - 健康状态事件（无来源）来源列不渲染链接
 * - 系统详情履历页签：按系统查询本系统事件（无角色切换），
 *   无新增/编辑/删除操作按钮（履历 append-only）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  history: {push: jest.fn()},
  Permission: {isSuper: true},
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
  mockHttpGet.mockReset();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const EVENTS_PAYLOAD = {
  data: [
    {
      id: 1, system: 5, system_code: 'SYS-001', system_name: '通信系统',
      event_type: 'fault', event_type_text: '故障', action: 'create',
      source_type: 'fault',
      source_id: '9', source_no: 'GZ20260919-0001',
      title: '发生严重故障', detail: {}, occurred_at: '2026-09-19 08:00',
      created_by_name: 'admin',
    },
    {
      id: 2, system: 5, system_code: 'SYS-001', system_name: '通信系统',
      event_type: 'health', event_type_text: '健康状态', action: 'status_change',
      source_type: 'health', source_id: '',
      source_no: '', title: '运行健康状态由「正常」变为「故障」', detail: {},
      occurred_at: '2026-09-19 08:00', created_by_name: '',
    },
    {
      id: 3, system: 6, system_code: 'SYS-002', system_name: '供电系统',
      event_type: 'work_order', event_type_text: '工单', action: 'create',
      source_type: 'work_order',
      source_id: '7', source_no: 'WO20260919-0002', title: '工单登记', detail: {},
      occurred_at: '2026-09-19 09:00', created_by_name: 'ops',
    },
  ],
  total: 3,
};

describe('履历列表表格（单系统简化）', () => {
  it('渲染事件行：类型/摘要，故障来源渲染链接，健康状态无链接，无角色列', async () => {
    mockHttpGet.mockResolvedValue(EVENTS_PAYLOAD);
    // eslint-disable-next-line global-require
    const ComTable = require('../Table').default;
    await act(async () => {
      ReactDOM.render(<ComTable/>, container);
    });
    await act(flush);
    const text = document.body.textContent;
    expect(text).toContain('GZ20260919-0001');
    expect(text).toContain('发生严重故障');
    expect(text).toContain('故障');
    expect(text).toContain('工单登记');
    // 单系统简化：不再展示"角色"列与主体/受影响/关联文案
    expect(text).not.toContain('角色');
    expect(text).not.toContain('受影响');
    expect(text).not.toContain('关联');
    // 来源链接：故障来源有 <a>，健康状态来源只有纯文本
    const links = Array.from(container.querySelectorAll('a'));
    const faultLink = links.find(a => a.textContent === '故障 GZ20260919-0001');
    expect(faultLink).toBeTruthy();
    const healthCell = Array.from(container.querySelectorAll('td'))
      .find(td => td.textContent === '健康状态');
    expect(healthCell).toBeTruthy();
  });

  it('查询履历调用只读接口 /system-events/', async () => {
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    // eslint-disable-next-line global-require
    const ComTable = require('../Table').default;
    await act(async () => {
      ReactDOM.render(<ComTable/>, container);
    });
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/system-events/', {params: {page: 1, page_size: 20}});
    expect(document.body.textContent).toContain('暂无系统履历');
  });
});

describe('系统详情——系统履历页签（单系统简化）', () => {
  it('按系统查询本系统事件，无角色切换；不提供新增/编辑/删除入口', async () => {
    mockHttpGet.mockResolvedValue({data: EVENTS_PAYLOAD.data, total: 3});
    // eslint-disable-next-line global-require
    const SystemEventsTab = require('../SystemEventsTab').default;
    await act(async () => {
      ReactDOM.render(<SystemEventsTab systemId={5}/>, container);
    });
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/5/system-events/',
      {params: {page: 1, page_size: 20}});
    const text = document.body.textContent;
    // 不再提供角色单选切换
    expect(text).not.toContain('主体');
    expect(text).not.toContain('受影响');
    expect(text).not.toContain('关联');
    expect(container.querySelectorAll('.ant-radio-button-wrapper').length).toBe(0);
    // 履历 append-only：无"新增/编辑/删除"操作文案
    expect(text).not.toContain('新增');
    expect(text).not.toContain('删除');
  });
});
