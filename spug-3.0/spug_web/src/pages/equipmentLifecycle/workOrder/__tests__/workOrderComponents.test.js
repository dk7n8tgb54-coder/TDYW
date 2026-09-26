/**
 * 设备全生命周期（步骤 3.3，单账号协同流程）工单组件渲染测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 工单详情抽屉展示作业系统（名称+地点快照）与影响运行标记、状态标签、来源单据
 * - 详情不再提供"受影响系统"页签，不再提供派发/接单/开始执行/提交复核/复核按钮
 * - 执行中显示完成工单/取消工单，已完成显示关闭工单，历史兼容状态不崩溃
 * - 故障详情"关联工单"页签展示该故障生成的工单（允许多张）
 * - 台账异常明细处置状态标签与可转单操作按处置状态切换
 * - 所有请求只指向 equipment-lifecycle 前缀（不使用旧 fault 接口）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

// 权限可按用例切换（默认超管全可见）
const mockPermState = {isSuper: true, granted: true};

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => mockPermState.granted),
  Permission: {get isSuper() {return mockPermState.isSuper;}},
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
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  mockPermState.isSuper = true;
  mockPermState.granted = true;
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function findButtonByText(text) {
  // 抽屉/弹窗渲染在 body portal 下，需全局查找按钮
  return Array.from(document.querySelectorAll('button'))
    .find(btn => btn.textContent.replace(/\s+/g, '') === text);
}

const detail = {
    id: 5,
    work_no: 'WO20260919-0001',
    title: '主用链路抢修',
    work_type: 'repair',
    work_type_text: '故障维修',
    priority: 'high',
    status: 'executing',
    status_text: '执行中',
    source_type: 'fault',
    source_no: 'GZ20260919-0001',
    source_fault: 33,
    system: 7,
    system_name: '烟台通信系统',
    system_code: 'SYS-A1',
    system_location: '机房A',
    affects_system_operation: true,
    owner_name: '',
    participants: [],
    work_requirement: '链路丢包，需更换光模块',
    process_result: '',
  };

function renderDetail(props) {
  const WorkOrderDetail = require('../WorkOrderDetail').default;
  act(() => {
    ReactDOM.render(
      <WorkOrderDetail woId={5} visible {...props}/>,
      container,
    );
  });
}

describe('工单详情抽屉（基本信息渲染）', () => {
  it('展示作业系统快照、影响运行标记、状态与来源单据，执行中显示完成工单/取消工单', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/work-orders/5/handling-records/')) {
        return Promise.resolve({data: [], total: 0});
      }
      return Promise.resolve(detail);
    });
    renderDetail({});
    await act(flush);
    await act(flush);
    const text = document.body.textContent;
    expect(text).toContain('WO20260919-0001');
    expect(text).toContain('烟台通信系统');
    expect(text).not.toContain('SYS-A1');
    expect(text).toContain('机房A');
    expect(text).toContain('作业期间影响系统运行');
    expect(text).toContain('影响运行');
    expect(text).toContain('执行中');
    const flat = text.replace(/\s+/g, '');
    expect(flat).toContain('完成工单');
    expect(flat).toContain('取消工单');
    // 详情请求指向工单端点
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/work-orders/5/');
  });

  it('执行中不再显示派发/接单/开始执行/提交复核/复核通过/复核退回按钮', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/work-orders/5/handling-records/')) {
        return Promise.resolve({data: [], total: 0});
      }
      return Promise.resolve(detail);
    });
    renderDetail({});
    await act(flush);
    await act(flush);
    const flat = document.body.textContent.replace(/\s+/g, '');
    expect(flat).not.toContain('派发');
    expect(flat).not.toContain('接单');
    expect(flat).not.toContain('开始执行');
    expect(flat).not.toContain('提交复核');
    expect(flat).not.toContain('复核通过');
    expect(flat).not.toContain('复核退回');
  });

  it('不再提供"受影响系统"页签', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/work-orders/5/handling-records/')) {
        return Promise.resolve({data: [], total: 0});
      }
      return Promise.resolve({...detail, affected_systems: [
        {id: 1, system: 9, system_name: '威海监控系统', system_code: 'SYS-A2'},
      ]});
    });
    renderDetail({});
    await act(flush);
    await act(flush);
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab')).map(t => t.textContent);
    expect(tabs.some(t => t.includes('受影响系统'))).toBe(false);
    // 页签含计数后缀（如"参与人员（0）"），按包含断言
    expect(tabs.some(t => t.includes('基本信息'))).toBe(true);
    expect(tabs.some(t => t.includes('参与人员'))).toBe(true);
    expect(tabs.some(t => t.includes('处理记录'))).toBe(true);
  });
});

describe('工单详情抽屉（状态与历史兼容）', () => {
  it('已完成状态显示关闭工单；历史待复核状态不崩溃且仅保留取消', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/work-orders/5/handling-records/')) {
        return Promise.resolve({data: [], total: 0});
      }
      return Promise.resolve({...detail, status: 'completed', status_text: '已完成',
        process_result: '已更换光模块'});
    });
    renderDetail({});
    await act(flush);
    await act(flush);
    let flat = document.body.textContent.replace(/\s+/g, '');
    expect(flat).toContain('已完成');
    expect(flat).toContain('关闭工单');
    expect(findButtonByText('完成工单')).toBeFalsy();

    // 历史待复核状态：页面正常渲染（不崩溃），无复核按钮，仅受控取消
    ReactDOM.unmountComponentAtNode(container);
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/work-orders/5/handling-records/')) {
        return Promise.resolve({data: [], total: 0});
      }
      return Promise.resolve({...detail, status: 'pending_review', status_text: '待复核'});
    });
    renderDetail({});
    await act(flush);
    await act(flush);
    flat = document.body.textContent.replace(/\s+/g, '');
    expect(flat).toContain('待复核（历史）');
    expect(flat).toContain('取消工单');
    expect(flat).not.toContain('复核通过');
    expect(flat).not.toContain('复核退回');
    expect(flat).not.toContain('关闭工单');
  });

  it('历史工单的派发/接单/复核信息以"历史流程信息"分区展示且不崩溃', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/work-orders/5/handling-records/')) {
        return Promise.resolve({data: [], total: 0});
      }
      return Promise.resolve({...detail, status: 'closed', status_text: '已关闭',
        owner_name: '李四', dispatched_by_name: '李四', dispatched_at: '2026-09-01 08:00',
        accepted_by_name: '李四', accepted_at: '2026-09-01 08:10',
        reviewer_name: '李四', reviewed_at: '2026-09-02 09:00'});
    });
    renderDetail({});
    await act(flush);
    await act(flush);
    const flat = document.body.textContent.replace(/\s+/g, '');
    expect(flat).toContain('历史流程信息');
    expect(flat).toContain('李四');
  });

  it('处理记录时间线执行中可追加，更正留痕可见（Tabs 懒渲染，直接单测时间线）', async () => {
    const {HandlingTimeline} = require('../WorkOrderDetail');
    const records = [{
      id: 1, handled_at: '2026-09-18 10:00', handler_name: '李四',
      content: '更换光模块', result: '处理完成', work_hours: 1.5,
      corrections: [{old: '原内容', new: '更换光模块', reason: '笔误', by: '李四', at: '2026-09-18 10:30'}],
    }];
    act(() => {
      ReactDOM.render(<HandlingTimeline records={records} fetching={false} editable
        onAdd={() => Promise.resolve()} onCorrect={() => Promise.resolve()}/>, container);
    });
    const text = container.textContent;
    expect(text).toContain('添加处理记录');
    expect(text).toContain('更换光模块');
    expect(text).toContain('更正记录');
  });
});

describe('故障详情关联工单页签', () => {
  it('展示该故障生成的工单列表并允许多张', async () => {
    const FaultWorkOrdersTab = require('../FaultWorkOrders').FaultWorkOrdersTab;
    const rows = [
      {id: 1, work_no: 'WO20260919-0001', title: '抢修一', work_type: 'repair',
       status: 'executing', priority: 'high', owner_name: '李四'},
      {id: 2, work_no: 'WO20260919-0002', title: '抢修二', work_type: 'repair',
       status: 'completed', priority: 'normal', owner_name: '王五'},
    ];
    mockHttpGet.mockResolvedValue({data: rows, total: 2});
    act(() => {
      ReactDOM.render(
        <FaultWorkOrdersTab fault={{id: 33, fault_no: 'GZ20260919-0001'}}/>,
        container,
      );
    });
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/33/work-orders/');
    const text = container.textContent;
    expect(text).toContain('WO20260919-0001');
    expect(text).toContain('WO20260919-0002');
    expect(text).toContain('多张');
  });

  it('无工单时显示空态提示', async () => {
    const FaultWorkOrdersTab = require('../FaultWorkOrders').FaultWorkOrdersTab;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    act(() => {
      ReactDOM.render(
        <FaultWorkOrdersTab fault={{id: 34, fault_no: 'GZ20260919-0002'}}/>,
        container,
      );
    });
    await act(flush);
    expect(container.textContent).toContain('尚未生成工单');
  });

  it('生成维修工单默认值：默认不影响运行（部件离线维修不影响系统状态）', async () => {
    const {GenerateWorkOrderButton} = require('../FaultWorkOrders');
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/candidate-systems/')) {
        return Promise.resolve({data: [{id: 7, name: '烟台通信系统', system_code: 'SYS-A1'}]});
      }
      return Promise.resolve({data: []});
    });
    async function openAndReadSwitch(fault) {
      ReactDOM.unmountComponentAtNode(container);
      await act(async () => {
        ReactDOM.render(<GenerateWorkOrderButton fault={fault}/>, container);
      });
      const btn = Array.from(container.querySelectorAll('button'))
        .find(b => b.textContent.replace(/\s+/g, '') === '生成维修工单');
      await act(async () => {
        btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      });
      await act(flush);
      // antd Switch 选中态带 ant-switch-checked class
      const sw = document.querySelector('.ant-switch');
      return sw && sw.classList.contains('ant-switch-checked');
    }
    // 新契约：无论来源故障是否恢复，转工单默认均不影响系统运行，
    // 需要影响运行时由用户在表单中明确开启（与后端默认一致）
    expect(await openAndReadSwitch({id: 33, fault_no: 'GZ20260919-0001', status: 'handling'}))
      .toBe(false);
    expect(await openAndReadSwitch({id: 33, fault_no: 'GZ20260919-0001', status: 'recovered'}))
      .toBe(false);
  });
});

describe('台账异常处置组件', () => {
  it('未处置异常显示转故障/转工单操作；已转故障显示跳转不再显示转单', async () => {
    const {ConvertActions, DispositionTag} = require('../LedgerItemDisposition');
    const ledger = {id: 11, ledger_no: 'EL-INS-20260910-0001'};
    // 未处置
    act(() => {
      ReactDOM.render(
        <span>
          <DispositionTag item={{id: 1, result: 'abnormal', disposition: {status: 'none'}}}/>
          <ConvertActions ledger={ledger} item={{id: 1, result: 'abnormal', disposition: {status: 'none'}}}/>
        </span>,
        container,
      );
    });
    expect(container.textContent).toContain('未处置');
    expect(container.textContent).toContain('转故障');
    expect(container.textContent).toContain('转工单');
    // 已转故障：显示目标编号（跳转链接），不显示可用转单操作
    ReactDOM.unmountComponentAtNode(container);
    act(() => {
      ReactDOM.render(
        <span>
          <DispositionTag item={{id: 1, result: 'abnormal',
            disposition: {status: 'converted_fault', fault: {id: 9, fault_no: 'GZ20260919-0003'}}}}/>
          <ConvertActions ledger={ledger} item={{id: 1, result: 'abnormal',
            disposition: {status: 'converted_fault', fault: {id: 9, fault_no: 'GZ20260919-0003'}}}}/>
        </span>,
        container,
      );
    });
    expect(container.textContent).toContain('已转故障');
    expect(container.textContent).toContain('GZ20260919-0003');
    expect(container.textContent).not.toContain('转工单');
  });

  it('正常明细不显示处置状态与转单操作', () => {
    const {ConvertActions, DispositionTag} = require('../LedgerItemDisposition');
    act(() => {
      ReactDOM.render(
        <span>
          <DispositionTag item={{id: 2, result: 'normal'}}/>
          <ConvertActions ledger={{id: 11}} item={{id: 2, result: 'normal'}}/>
        </span>,
        container,
      );
    });
    expect(container.textContent).not.toContain('未处置');
    expect(container.textContent).not.toContain('转故障');
  });
});

describe('工单常量契约', () => {
  it('状态与类型文本映射覆盖后端全部枚举（不含禁用类型）', () => {
    const {WO_STATUS_TEXT, WORK_TYPE_TEXT} = require('../constants');
    ['pending_dispatch', 'pending_accept', 'executing', 'pending_review',
      'completed', 'closed', 'cancelled'].forEach(s => expect(WO_STATUS_TEXT[s]).toBeTruthy());
    ['repair', 'special_maintenance', 'tech_reform', 'config_change',
      'field_test', 'calibration'].forEach(t => expect(WORK_TYPE_TEXT[t]).toBeTruthy());
    // 不得加入建设/验收/试运行/投运/停运/下线/归档等类型
    expect(Object.keys(WORK_TYPE_TEXT).length).toBe(6);
  });
});
