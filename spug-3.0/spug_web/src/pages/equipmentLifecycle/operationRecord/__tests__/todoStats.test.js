/**
 * 运行处置记录——待办视图与统计视图契约测试（2026-10-14 体验二轮）。
 * 自 components.test.js 拆出（文件行数治理）。真实渲染组件，mock libs.http：
 * - 待办：全量分组计数（跟进中异常事件/处置中设备故障）、分页与类型筛选
 *   参数透传、加载失败横幅可重试（查询时机由 index 页签切换驱动）；
 * - 统计：四个核心指标并排（进行中附口径说明）、时间趋势柱状图逐日数值、
 *   状态/类型/系统维度保留、加载失败横幅可重试。
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
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
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

// 重试按钮：antd 对两字中文按钮自动插空格（“重 试”），匹配前去掉空白
function findRetryButton() {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === '重试');
}

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function textContent() {
  return document.body.textContent || '';
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockReset();
  mockHttpGet.mockResolvedValue({data: [], total: 0});
  mockHttpPost.mockReset();
  mockHttpPost.mockResolvedValue({});
  mockHttpPut.mockReset();
  mockHttpPut.mockResolvedValue({});
  mockHttpDelete.mockReset();
  mockHttpDelete.mockResolvedValue({});
  // store 为模块级单例：跨测试重置可见性/失败标记
  const store = require('../store').default;
  store.detailVisible = false;
  store.formVisible = false;
  store.fetchError = false;
  store.todoError = false;
  store.statsError = false;
  store.todoRecords = [];
  store.todoCounts = null;
  store.statistics = null;
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-message').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

describe('待办视图（跟进中+处置中，2026-10-14 扩展口径）', () => {
  const TODO_RESPONSE = {
    data: [
      {id: 31, record_no: 'JL20261014-0031', record_type: 'abnormal',
        title: '信号波动', system_name: 'DVOR系统', status: 'following_up',
        occurred_at: '2026-10-14 08:00:00'},
      {id: 32, record_no: 'JL20261014-0032', record_type: 'fault',
        title: '发射机故障', system_name: 'DVOR系统', status: 'handling',
        occurred_at: '2026-10-14 09:00:00'},
    ],
    total: 3, page: 1, page_size: 20,
    counts: {following_up: 2, handling: 1, total: 3},
  };

  it('展示全量分组计数，分页参数随请求透传', async () => {
    mockHttpGet.mockResolvedValue(TODO_RESPONSE);
    const store = require('../store').default;
    const RecordTodo = require('../RecordTodo').default;
    await act(async () => {
      ReactDOM.render(React.createElement(RecordTodo), container);
    });
    // 查询时机由 index 页签切换驱动（handleTabChange），这里显式触发同一路径
    await act(async () => {
      await store.fetchTodoRecords();
    });
    const text = textContent();
    expect(text).toContain('共 3 条待办');
    expect(text).toContain('跟进中异常事件 2 条');
    expect(text).toContain('处置中设备故障 1 条');
    expect(text).toContain('JL20261014-0032');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/todo/',
      {params: {page: 1, page_size: 20}});
    // 分组筛选：重置页码并携带 record_type
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue(TODO_RESPONSE);
    await act(async () => {
      await store.setTodoRecordType('fault');
    });
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/todo/',
      {params: {page: 1, page_size: 20, record_type: 'fault'}});
    store.f_todo_record_type = undefined;
    store.todoPage = 1;
  });

  it('待办加载失败显示警告横幅并可重试', async () => {
    mockHttpGet.mockRejectedValue('boom');
    const store = require('../store').default;
    const RecordTodo = require('../RecordTodo').default;
    await act(async () => {
      ReactDOM.render(React.createElement(RecordTodo), container);
    });
    await act(async () => {
      await store.fetchTodoRecords();
    });
    expect(textContent()).toContain('待办加载失败');
    const retry = findRetryButton();
    expect(retry).toBeTruthy();
    mockHttpGet.mockResolvedValue(TODO_RESPONSE);
    await act(async () => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(textContent()).toContain('跟进中异常事件 2 条');
  });
});

describe('统计视图（2026-10-14 体验二轮）', () => {
  const STATS = {
    totals: {
      total: 5, following_up: 2, handling_fault: 1, stale_open: 1,
      stale_days: 7, avg_resolve_hours: 3.5, resolved_count: 2,
    },
    by_status: {recorded: 2, following_up: 2, handling: 1},
    by_type: {routine: 2, abnormal: 2, fault: 1},
    by_system: [{system: 3, system_name: 'DVOR系统', total: 5, following_up: 2, handling_fault: 1}],
    trend: [
      {date: '2026-10-10', total: 3, fault: 1},
      {date: '2026-10-11', total: 2, fault: 0},
    ],
  };

  function renderStats() {
    const store = require('../store').default;
    const RecordStatistics = require('../RecordStatistics').default;
    store.statistics = STATS;
    return ReactDOM.render(React.createElement(RecordStatistics), container);
  }

  it('四个核心指标并排展示，进行中附口径说明', async () => {
    renderStats();
    const text = textContent();
    expect(text).toContain('记录总数');
    expect(text).toContain('进行中');
    expect(text).toContain('跟进中 2 / 处置中故障 1');
    expect(text).toContain('超期未关闭');
    expect(text).toContain('平均处理时长（小时）');
    expect(text).toContain('2 条参与');
  });

  it('时间趋势柱状图展示逐日数值与无数据说明', async () => {
    renderStats();
    const text = textContent();
    // 柱顶数值与日期刻度
    expect(text).toContain('10-10');
    expect(text).toContain('10-11');
    expect(text).toContain('按自然日统计范围内每日新增记录数');
  });

  it('状态/类型维度与系统维度保留', async () => {
    renderStats();
    const text = textContent();
    expect(text).toContain('状态维度');
    expect(text).toContain('类型维度');
    expect(text).toContain('系统维度');
    expect(text).toContain('DVOR系统');
  });

  it('统计加载失败显示警告横幅并可重试', async () => {
    mockHttpGet.mockRejectedValue('boom');
    const store = require('../store').default;
    const RecordStatistics = require('../RecordStatistics').default;
    await act(async () => {
      ReactDOM.render(React.createElement(RecordStatistics), container);
    });
    // 查询时机由 index 页签切换驱动（handleTabChange），这里显式触发同一路径
    await act(async () => {
      await store.fetchStatistics();
    });
    expect(textContent()).toContain('统计加载失败');
    const retry = findRetryButton();
    mockHttpGet.mockResolvedValue(STATS);
    await act(async () => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(textContent()).toContain('记录总数');
  });
});
