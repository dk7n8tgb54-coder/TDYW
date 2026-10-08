/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行记录第二版组件渲染测试（2026-10；2026-10-05 第四版：研判不再是
 * 必经步骤）。真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 详情按状态显示新流程按钮（已记录族 = 编辑/开始跟进/转为正式故障；
 *   终态不显示；标记重要已随字段删除移除 2026-10-06）；
 *   TriageModal 整体删除，页面不再出现研判弹窗
 * - 待办视图：只展示跟进中记录，按最近更新优先（跟进人/计划时间/超期
 *   维度已随跟进计划删除移除 2026-10-06）
 * - 统计视图：总数/状态维度（后端按可见四状态归并）/系统维度/趋势渲染；
 *   "重要记录"卡片与系统维度"重要"列已随字段删除移除（2026-10-06）
 * - 重复问题功能下线（2026-10-05）：详情无"重复问题"页签，打开详情不再
 *   请求 similar/ 与 duplicate-links/ 接口，统计页不再展示"重复问题"卡片
 *   （后端旧接口/模型/历史数据保留，仅前端不再调用与展示）
 * 所有请求只指向 equipment-lifecycle 前缀。
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
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function bodyText() {
  return document.body.textContent.replace(/\s+/g, '');
}


// 顶部动作按钮（排除详情弹窗 footer 的"关 闭"外壳按钮）
function topButtonTexts() {
  return Array.from(document.querySelectorAll('button'))
    .filter(b => !b.closest('.ant-modal-footer'))
    .map(b => b.textContent.replace(/\s+/g, ''));
}

const SYSTEMS = [
  {id: 1, system_code: 'SYS-A1', name: '烟台通信系统', install_location: '机房A'},
];

const RECORD_DETAIL = {
  id: 11, record_no: 'YX20261001-0001', system: 1,
  system_name: '烟台通信系统', system_code: 'SYS-A1', system_location: '机房A',
  occurred_at: '2026-10-01 08:30', title: '主用链路短暂中断',
  description: '值班发现主用链路丢包', status: 'recorded', status_text: '已记录',
  needs_follow_up: false,
  converted_fault: null, converted_fault_no: '',
  category: '', category_text: '', is_repeated: false,
  resolved_at: null,
  triaged_at: null, triaged_by_name: '', triage_note: '',
  initial_reason: '', impact_scope: '',
  measures_taken: '', handling_result: '',
  created_by_name: 'admin', created_at: '2026-10-01 08:35', updated_at: null,
};

// 待研判等历史状态已由后端迁移 0007 归一为四状态（2026-10-06），
// 前端不再提供历史状态映射，相关夹具随状态收敛删除。

const TODO_PAGE = {
  data: [
    {id: 21, record_no: 'YX20261001-0003', system: 1, system_name: '烟台通信系统',
     title: '链路质量待观察', status: 'following_up', status_text: '跟进中',
     needs_follow_up: true,
     occurred_at: '2026-10-01 09:00',
     category: '', category_text: '',
     converted_fault: null, converted_fault_no: '',
     created_by_name: 'admin', created_at: '2026-10-01 09:00'},
  ],
  total: 1,
};

const STATISTICS = {
  totals: {total: 5, following_up: 1, converted_fault: 1, duplicated: 2,
    stale_open: 1, avg_resolve_hours: 2.5, resolved_count: 2},
  by_status: {recorded: 3, following_up: 1, completed: 1, converted_fault: 1},
  by_system: [{system: 1, system_name: '烟台通信系统', total: 5,
    following_up: 1, converted_fault: 1}],
  trend: [{date: '2026-10-01', total: 3, converted_fault: 1}],
  occurred_from: '2026-09-02', occurred_to: '2026-10-03', stale_days: 7,
};

function mockDetailApis(detailResponse) {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/candidate-systems')) return Promise.resolve({data: SYSTEMS});
    if (url.includes('/progress/')) return Promise.resolve({data: []});
    if (url.includes('/attachments/')) return Promise.resolve({data: []});
    // 重复问题功能已下线：不再 mock similar/ 与 duplicate-links/——
    // 若组件仍发起相关请求，会落入下方兜底分支并被"不请求旧接口"断言抓住
    if (/\/runtime-records\/\d+\/$/.test(url)) {
      return Promise.resolve(detailResponse || RECORD_DETAIL);
    }
    return Promise.resolve({data: [], total: 0});
  });
}

async function renderDetail(detailResponse) {
  const store = require('../store').default;
  const RecordDetail = require('../RecordDetail').default;
  mockDetailApis(detailResponse);
  await act(async () => {
    store.showDetail({...RECORD_DETAIL});
    ReactDOM.render(<RecordDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

describe('运行记录 V2 · 新流程按钮（研判不再是必经步骤）', () => {
  it('已记录显示 编辑/开始跟进/转为正式故障；页面无研判弹窗与标记重要', async () => {
    await renderDetail();
    const texts = topButtonTexts();
    ['编辑', '开始跟进', '转为正式故障'].forEach(btn => {
      expect(texts).toContain(btn);
    });
    // 研判不再是入口：TriageModal 已删除，页面不出现任何研判字样按钮；
    // 标记重要已随字段删除移除（2026-10-06）
    expect(texts).not.toContain('研判');
    expect(texts).not.toContain('提交研判');
    expect(texts).not.toContain('标记重要');
    expect(texts).not.toContain('关闭');
  });

  it('跟进中显示 新增跟进记录/完成跟进/转为正式故障，无研判入口与跟进计划入口', async () => {
    await renderDetail({...RECORD_DETAIL, status: 'following_up',
      status_text: '跟进中'});
    const texts = topButtonTexts();
    ['新增跟进记录', '完成跟进', '转为正式故障'].forEach(btn => {
      expect(texts).toContain(btn);
    });
    expect(texts).not.toContain('研判');
    expect(texts).not.toContain('提交研判');
    // 跟进计划已删除（2026-10-06）：无修改跟进计划入口
    expect(texts).not.toContain('修改跟进计划');
  });

  it('打开详情不请求 triage 相关接口（前端不再调用旧研判端点）', async () => {
    await renderDetail();
    expect(mockHttpPost).not.toHaveBeenCalled();
    const urls = mockHttpGet.mock.calls.map(call => call[0]);
    // 详情/进展/附件三项，无旧研判页面专属请求
    expect(urls.some(u => u.includes('/triage/'))).toBe(false);
  });
});

describe('运行记录 V2 · 待办视图', () => {
  it('只展示跟进中记录，请求不带跟进计划筛选参数（该维度已删除）', async () => {
    const RecordTodo = require('../RecordTodo').default;
    mockHttpGet.mockImplementation((url, config) => {
      expect(url).toBe('/api/equipment-lifecycle/runtime-records/todo/');
      return Promise.resolve(TODO_PAGE);
    });
    await act(async () => {
      ReactDOM.render(<RecordTodo/>, container);
    });
    await act(async () => {await flush();});
    // 无筛选参数（overdue/follow_up_name/order 已随跟进计划删除）
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/todo/');
    const text = bodyText();
    expect(text).toContain('YX20261001-0003');
    // 跟进人/计划处理时间列已删除，不再出现超期告警
    const headers = Array.from(document.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent.replace(/\s+/g, ''));
    expect(headers).not.toContain('跟进人');
    expect(headers).not.toContain('计划处理时间');
    expect(text).not.toContain('超期');
    expect(text).not.toContain('王值班');
  });

  it('无待办时展示空态文案', async () => {
    const RecordTodo = require('../RecordTodo').default;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await act(async () => {
      ReactDOM.render(<RecordTodo/>, container);
    });
    await act(async () => {await flush();});
    expect(bodyText()).toContain('暂无待办');
  });
});

describe('运行记录 V2 · 统计视图', () => {
  it('渲染总数卡片/状态维度/系统维度/时间趋势', async () => {
    const RecordStatistics = require('../RecordStatistics').default;
    mockHttpGet.mockImplementation((url) => {
      expect(url).toBe('/api/equipment-lifecycle/runtime-records/statistics/');
      return Promise.resolve(STATISTICS);
    });
    await act(async () => {
      ReactDOM.render(<RecordStatistics/>, container);
    });
    await act(async () => {await flush();});
    const text = bodyText();
    expect(text).toContain('运行记录总数');
    expect(text).toContain('跟进中');
    expect(text).toContain('转故障');
    // "重复问题"卡片已下线：夹具仍保留 duplicated 字段（历史统计接口
    // 可能继续返回），前端不再展示
    expect(text).not.toContain('重复问题');
    // "重要记录"卡片与系统维度"重要"列已随字段删除移除（2026-10-06）
    expect(text).not.toContain('重要记录');
    expect(text).toContain('长期未关闭');
    expect(text).toContain('平均处理时长');
    expect(text).toContain('烟台通信系统');
    expect(text).toContain('2026-10-01');
    // 状态维度 Tag：后端按可见四状态归并，已记录 3
    expect(text).toContain('已记录：3');
  });
});

describe('运行记录 V2 · 重复问题功能下线（2026-10-05）', () => {
  it('详情页签只剩 基本信息/处理进展/附件，不显示"重复问题"页签', async () => {
    await renderDetail();
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .map(el => el.textContent.replace(/\s+/g, ''));
    expect(tabs).toEqual(['基本信息', '处理进展', '附件']);
    expect(tabs).not.toContain('重复问题');
  });

  it('打开详情不再请求相似记录与重复关联接口，也不请求标记重复发生', async () => {
    await renderDetail();
    const urls = mockHttpGet.mock.calls.map(call => call[0]);
    expect(urls.some(u => u.includes('/similar/'))).toBe(false);
    expect(urls.some(u => u.includes('/duplicate-links/'))).toBe(false);
    // 旧 mark-repeated 端点也不再被前端调用（is_repeated 新流程不写入）
    expect(mockHttpPost).not.toHaveBeenCalled();
  });
});
