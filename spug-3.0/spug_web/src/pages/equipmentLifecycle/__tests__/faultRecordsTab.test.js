/**
 * 系统详情故障页签测试（2026-10-03 自 faultComponents.test.js 拆出，
 * 该文件超出单文件行数限制）。
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 只展示本系统故障，不再区分主体/受影响角色（单系统简化）；
 * - 不影响运行的部件故障显示"不影响运行"标签（与列表/详情口径一致）；
 * - 已撤销（cancelled）行状态标签为虚线灰样式（撤销登记改版）。
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

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

describe('系统详情故障页签（单系统简化）', () => {
  it('只展示本系统故障，不再区分主体/受影响角色', async () => {
    const FaultRecordsTab = require('../FaultRecordsTab').default;
    mockHttpGet.mockResolvedValue({data: [
      {id: 21, fault_no: 'GZ20260918-0002', system: 9,
        affects_system_operation: true, impact_status: 'interrupted',
        status: 'handling',
        occurred_at: '2026-09-18 07:00', phenomenon: '系统中断'},
      {id: 23, fault_no: 'GZ20260918-0004', system: 9,
        affects_system_operation: true, impact_status: 'degraded',
        status: 'closed',
        occurred_at: '2026-09-18 06:00', phenomenon: '另一路链路降级'},
      {id: 25, fault_no: 'GZ20260918-0005', system: 9,
        affects_system_operation: false, impact_status: '',
        status: 'cancelled',
        occurred_at: '2026-09-18 05:00', phenomenon: '部件故障离线维修'},
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
    // 不影响运行的部件故障与列表/详情口径一致，显示"不影响运行"标签而非横杠
    expect(text).toContain('GZ20260918-0005');
    expect(text).toContain('不影响运行');
    // 撤销登记改版：已撤销状态展示新文案"已撤销"
    expect(text).toContain('已撤销');
    // 不再出现角色标识
    expect(text).not.toContain('主体故障');
    expect(text).not.toContain('受影响故障');
    // 请求不再携带 role 参数
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/9/faults/');
  });

  it('已撤销行状态标签为虚线灰（克制区别于处置中/已关闭）', async () => {
    const FaultRecordsTab = require('../FaultRecordsTab').default;
    mockHttpGet.mockResolvedValue({data: [
      {id: 25, fault_no: 'GZ20260918-0005', system: 9,
        affects_system_operation: false, impact_status: '',
        status: 'cancelled',
        occurred_at: '2026-09-18 05:00', phenomenon: '部件故障离线维修'},
    ]});
    await act(async () => {
      ReactDOM.render(<FaultRecordsTab systemId={9}/>, container);
    });
    await act(async () => {await flush();});
    const row = Array.from(document.querySelectorAll('tr'))
      .find(tr => tr.textContent.includes('GZ20260918-0005'));
    expect(row).toBeTruthy();
    const statusTag = Array.from(row.querySelectorAll('.ant-tag'))
      .find(t => t.textContent.includes('已撤销'));
    expect(statusTag).toBeTruthy();
    expect(statusTag.style.borderStyle).toBe('dashed');
  });
});
