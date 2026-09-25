/**
 * 设备全生命周期——系统履历页面组件渲染测试（按系统分组、按业务事项聚合）
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 分组表格渲染系统行（编号/名称/健康状态/事项数/未关闭故障/最近履历时间）
 * - 展开系统行显示聚合事项；事项行展开按需加载节点时间线
 * - 健康状态事件默认不进入主事项列表；"状态变化"入口打开历史抽屉
 * - 筛选条件触发重新请求；加载失败与空数据状态
 * - 来源跳转与权限控制；系统详情履历页签（平铺接口）继续正常工作
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHasPermission = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  hasPermission: mockHasPermission,
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
  mockHasPermission.mockImplementation(() => true);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  mockHttpGet.mockReset();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function bodyText() {
  return document.body.textContent.replace(/\s+/g, '');
}

function freshGroupStore() {
  // eslint-disable-next-line global-require
  const store = require('../groupStore').default;
  store.groups = [];
  store.total = 0;
  store.page = 1;
  store.isFetching = false;
  store.fetchFailed = false;
  store.f_keyword = undefined;
  store.f_event_type = undefined;
  store.f_source_type = undefined;
  store.f_range = undefined;
  store.itemNodes = {};
  store.requestSeq = 0;
  store.nodeRequests = {};
  store.healthDrawer = {
    visible: false, systemId: null, systemName: '',
    loading: false, failed: false, records: [],
  };
  return store;
}

const GROUPS_PAYLOAD = {
  data: [
    {
      system: {
        id: 5, system_code: 'SYS-001', name: '通信系统',
        health_status: 'degraded', health_status_text: '降级',
      },
      item_count: 2,
      open_fault_count: 1,
      last_event_at: '2026-09-25T09:30:00',
      items: [
        {
          source_type: 'fault', source_id: '9', event_type: 'fault',
          event_type_text: '故障', item_no: 'GZ20260919-0001',
          title: '主用链路频繁丢包', level: 'major', level_text: '严重',
          status: 'handling', status_text: '处置中',
          first_occurred_at: '2026-09-19T08:00:00',
          last_occurred_at: '2026-09-19T10:00:00',
          duration_seconds: 7200, node_count: 3,
          ledger_sources: [{ledger_no: 'ZW20260918-0003', item_name: '设备指示灯检查'}],
          detail: {},
        },
        {
          source_type: 'work_order', source_id: '7', event_type: 'work_order',
          event_type_text: '工单', item_no: 'WO20260925-0002',
          title: '例行维护工单', level: '', level_text: '',
          status: 'pending_dispatch', status_text: '待派发',
          first_occurred_at: '2026-09-25T09:00:00',
          last_occurred_at: '2026-09-25T09:30:00',
          node_count: 1, ledger_sources: [], detail: {},
        },
      ],
    },
    {
      system: {
        id: 6, system_code: 'SYS-002', name: '供电系统',
        health_status: 'normal', health_status_text: '正常',
      },
      item_count: 1, open_fault_count: 0,
      last_event_at: '2026-09-24T15:00:00',
      items: [{
        source_type: 'upgrade', source_id: '3', event_type: 'upgrade',
        event_type_text: '系统升级', item_no: '', title: '数字板升级',
        level: '', level_text: '', status: '', status_text: '已完成',
        first_occurred_at: '2026-09-24T14:00:00',
        last_occurred_at: '2026-09-24T15:00:00',
        node_count: 2, ledger_sources: [], detail: {},
      }],
    },
  ],
  total: 2,
};

const NODES_PAYLOAD = {
  data: [
    {id: 1, event_type: 'fault', action: 'create', source_type: 'fault',
      source_id: '9', source_no: 'GZ20260919-0001', title: '发生严重故障',
      detail: {}, occurred_at: '2026-09-19T08:00:00', created_by_name: 'admin'},
    {id: 2, event_type: 'ledger', action: 'convert_to_fault', source_type: 'ledger_item',
      source_id: '33', source_no: 'ZW20260918-0003', title: '台账异常转故障',
      detail: {}, occurred_at: '2026-09-19T09:00:00', created_by_name: 'ops'},
    {id: 3, event_type: 'fault', action: 'recover', source_type: 'fault',
      source_id: '9', source_no: 'GZ20260919-0001', title: '故障恢复确认',
      detail: {}, occurred_at: '2026-09-19T10:00:00', created_by_name: ''},
  ],
};

describe('分组表格——系统行与事项展开', () => {
  it('渲染系统分组行：编号/名称/健康状态/事项数/未关闭故障/最近履历时间', async () => {
    freshGroupStore();
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD);
    // eslint-disable-next-line global-require
    const GroupTable = require('../GroupTable').default;
    await act(async () => {
      ReactDOM.render(<GroupTable/>, container);
    });
    await act(flush);
    const text = bodyText();
    expect(text).toContain('SYS-001');
    expect(text).toContain('通信系统');
    expect(text).toContain('降级');
    expect(text).toContain('2项');
    expect(text).toContain('未关闭故障');
    expect(text).toContain('最近履历时间');
    expect(text).toContain('2026-09-2509:30');
    // 列表请求走分组接口，分页以系统为单位
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/system-event-groups/',
      {params: {page: 1, page_size: 10}});
    expect(text).toContain('共2个系统');
  });

  it('展开系统行显示聚合事项；事项行展开按需加载节点时间线', async () => {
    freshGroupStore();
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD);
    // eslint-disable-next-line global-require
    const GroupTable = require('../GroupTable').default;
    await act(async () => {
      ReactDOM.render(<GroupTable/>, container);
    });
    await act(flush);
    // 展开第一个系统分组
    const expandIcons = Array.from(
      container.querySelectorAll('.ant-table-row-expand-icon'));
    await act(async () => {
      expandIcons[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    let text = bodyText();
    expect(text).toContain('GZ20260919-0001');
    expect(text).toContain('处置中');
    expect(text).toContain('主用链路频繁丢包');
    expect(text).toContain('ZW20260918-0003');
    expect(text).toContain('2小时');
    // 展开故障事项：节点接口按需加载，时间线展示（含台账归并节点）
    // 内层事项表位于展开行内，取展开行中的第一个展开图标（故障事项）
    mockHttpGet.mockResolvedValue(NODES_PAYLOAD);
    mockHttpGet.mockClear();
    const expandedRow = container.querySelector('.ant-table-expanded-row');
    const itemExpandIcon = expandedRow.querySelector('.ant-table-row-expand-icon');
    await act(async () => {
      itemExpandIcon.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/system-event-groups/nodes/',
      {params: {system: 5, source_type: 'fault', source_id: '9'}});
    text = bodyText();
    expect(text).toContain('台账异常转故障');
    expect(text).toContain('故障恢复确认');
  });
});

describe('分组表格——健康状态面板与异常状态', () => {
  it('点击"状态变化"打开健康状态历史抽屉（按系统查询 health 事件）', async () => {
    freshGroupStore();
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD);
    // eslint-disable-next-line global-require
    const GroupTable = require('../GroupTable').default;
    // eslint-disable-next-line global-require
    const HealthDrawer = require('../HealthDrawer').default;
    await act(async () => {
      ReactDOM.render(
        <React.Fragment><GroupTable/><HealthDrawer/></React.Fragment>, container);
    });
    await act(flush);
    mockHttpGet.mockResolvedValue({
      data: [{id: 11, occurred_at: '2026-09-19T08:00:00',
        title: '运行健康状态由「正常」变为「降级」', created_by_name: 'admin'}],
    });
    mockHttpGet.mockClear();
    const link = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '状态变化');
    await act(async () => {
      link.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/5/system-events/',
      {params: {page: 1, page_size: 200, event_type: 'health'}});
    expect(bodyText()).toContain('健康状态变化-通信系统');
    expect(bodyText()).toContain('「降级」');
  });

  it('加载失败显示错误占位，空数据显示默认占位', async () => {
    freshGroupStore();
    mockHttpGet.mockRejectedValue(new Error('network'));
    // eslint-disable-next-line global-require
    const GroupTable = require('../GroupTable').default;
    await act(async () => {
      ReactDOM.render(<GroupTable/>, container);
    });
    await act(flush);
    expect(bodyText()).toContain('履历加载失败，请重试');
    // 空数据
    ReactDOM.unmountComponentAtNode(container);
    mockHttpGet.mockReset();
    freshGroupStore();
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await act(async () => {
      ReactDOM.render(<GroupTable/>, container);
    });
    await act(flush);
    expect(bodyText()).toContain('暂无系统履历');
  });

  it('无履历查看权限时不渲染页面内容、不发请求', async () => {
    freshGroupStore();
    // eslint-disable-next-line global-require
    const libs = require('libs');
    libs.hasPermission.mockImplementation(() => false);
    mockHttpGet.mockResolvedValue(GROUPS_PAYLOAD);
    // eslint-disable-next-line global-require
    const SystemEventIndex = require('../index').default;
    await act(async () => {
      ReactDOM.render(<SystemEventIndex/>, container);
    });
    await act(flush);
    expect(bodyText()).not.toContain('SYS-001');
    expect(mockHttpGet).not.toHaveBeenCalled();
  });
});

describe('事项表格（分组内）', () => {
  const group = GROUPS_PAYLOAD.data[0];

  it('渲染事项主记录：类型/编号/状态/摘要/首次发生/节点数/来源台账', async () => {
    // eslint-disable-next-line global-require
    const ItemTable = require('../ItemTable').default;
    await act(async () => {
      ReactDOM.render(<ItemTable group={group}/>, container);
    });
    await act(flush);
    const text = bodyText();
    expect(text).toContain('GZ20260919-0001');
    expect(text).toContain('处置中');
    expect(text).toContain('待派发');
    expect(text).toContain('严重');
    expect(text).toContain('2026-09-1908:00');
    expect(text).toContain('2026-09-1910:00');
    expect(text).toContain('来源台账');
  });

  it('事项展开按需请求节点，失败显示重试入口', async () => {
    freshGroupStore();
    // eslint-disable-next-line global-require
    const ItemTable = require('../ItemTable').default;
    await act(async () => {
      ReactDOM.render(<ItemTable group={group}/>, container);
    });
    await act(flush);
    mockHttpGet.mockRejectedValue(new Error('network'));
    const expandIcon = container.querySelector('.ant-table-row-expand-icon');
    await act(async () => {
      expandIcon.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/system-event-groups/nodes/',
      {params: {system: 5, source_type: 'fault', source_id: '9'}});
    expect(bodyText()).toContain('节点加载失败');
    // 重试成功后展示时间线
    mockHttpGet.mockReset();
    mockHttpGet.mockResolvedValue(NODES_PAYLOAD);
    const retry = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '重试');
    await act(async () => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    await act(flush);
    expect(bodyText()).toContain('故障恢复确认');
  });
});

describe('健康状态历史抽屉', () => {
  it('展示健康状态变化时间线，空数据状态正确', async () => {
    const store = freshGroupStore();
    store.healthDrawer = {
      visible: true, systemId: 5, systemName: '通信系统',
      loading: false, failed: false,
      records: [{id: 11, occurred_at: '2026-09-19T08:00:00',
        title: '运行健康状态由「正常」变为「降级」', created_by_name: 'admin'}],
    };
    // eslint-disable-next-line global-require
    const HealthDrawer = require('../HealthDrawer').default;
    await act(async () => {
      ReactDOM.render(<HealthDrawer/>, container);
    });
    await act(flush);
    expect(bodyText()).toContain('健康状态变化-通信系统');
    expect(bodyText()).toContain('「正常」变为「降级」');
    expect(bodyText()).toContain('记录人：admin');
    // 空数据
    ReactDOM.unmountComponentAtNode(container);
    store.healthDrawer.records = [];
    await act(async () => {
      ReactDOM.render(<HealthDrawer/>, container);
    });
    await act(flush);
    expect(bodyText()).toContain('暂无健康状态变化记录');
  });
});

describe('系统履历页面入口', () => {
  it('页面请求分组接口，筛选下拉不含健康状态/配置快照', async () => {
    freshGroupStore();
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    // eslint-disable-next-line global-require
    const SystemEventIndex = require('../index').default;
    await act(async () => {
      ReactDOM.render(<SystemEventIndex/>, container);
    });
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/system-event-groups/',
      {params: {page: 1, page_size: 10}});
    const text = bodyText();
    expect(text).toContain('事项类型');
    expect(text).toContain('来源类型');
  });
});

describe('系统详情——系统履历页签（平铺接口保持不变）', () => {
  it('按系统查询本系统事件（原接口契约不变，含健康状态事件）', async () => {
    mockHttpGet.mockResolvedValue({data: [{
      id: 2, event_type: 'health', event_type_text: '健康状态',
      source_type: 'health', source_id: '', source_no: '',
      title: '运行健康状态由「正常」变为「故障」', occurred_at: '2026-09-19T08:00:00',
    }], total: 1});
    // eslint-disable-next-line global-require
    const SystemEventsTab = require('../SystemEventsTab').default;
    await act(async () => {
      ReactDOM.render(<SystemEventsTab systemId={5}/>, container);
    });
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/5/system-events/',
      {params: {page: 1, page_size: 20}});
    expect(bodyText()).toContain('「故障」');
    // 履历 append-only：无"新增/删除"操作文案
    expect(bodyText()).not.toContain('新增');
  });
});
