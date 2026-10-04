/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行记录第二版组件渲染测试（2026-10）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 详情按状态显示 研判 按钮（已记录/待研判；终态不显示）
 * - 研判弹窗：无需跟进/需要跟进/转正式故障三种结论的请求载荷；
 *   转故障缺研判说明被客户端校验拦截（不发请求）
 * - 待办视图：只展示跟进中记录，超期/排序筛选参数生效，超期警示可见
 * - 统计视图：总数/状态维度/系统维度/趋势渲染
 * - 重复问题：相似记录关联 POST、取消关联 DELETE、标记重复发生 POST
 * - 权限控制：无 link 权限时关联入口不渲染
 * - 业务错误处理：研判提交失败不崩溃、弹窗保持打开（错误由拦截器提示）
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

function setInputValue(element, value) {
  const proto = element.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(element, value);
  element.dispatchEvent(new Event('input', {bubbles: true}));
}

function clickButtonByText(text, scope) {
  const root = scope || document.body;
  const buttons = Array.from(root.querySelectorAll('button'))
    .filter(b => b.textContent.replace(/\s+/g, '').includes(text) && !b.disabled);
  if (!buttons.length) {
    throw new Error(`button not found: ${text}`);
  }
  buttons[0].click();
}

function clickButtonByTextExact(text, scope) {
  const root = scope || document.body;
  const buttons = Array.from(root.querySelectorAll('button'))
    .filter(b => b.textContent.replace(/\s+/g, '') === text && !b.disabled);
  if (!buttons.length) {
    throw new Error(`button not found: ${text}`);
  }
  buttons[0].click();
}

function clickRadioByText(text) {
  const radios = Array.from(document.querySelectorAll('.ant-radio-wrapper'))
    .filter(el => el.textContent.replace(/\s+/g, '').includes(text));
  if (!radios.length) {
    throw new Error(`radio not found: ${text}`);
  }
  radios[0].click();
}

function clickTabByText(text) {
  const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'))
    .filter(el => el.textContent.replace(/\s+/g, '').includes(text));
  if (!tabs.length) {
    throw new Error(`tab not found: ${text}`);
  }
  tabs[0].click();
}

function clickModalOk() {
  const ok = Array.from(document.querySelectorAll('.ant-modal button'))
    .find(b => /^ok|确定$/i.test(b.textContent.replace(/\s+/g, '')) && !b.disabled);
  if (!ok) {
    throw new Error('modal ok button not found');
  }
  ok.click();
}

function clickPopconfirmOk() {
  const ok = Array.from(document.querySelectorAll('.ant-popover button'))
    .find(b => /^ok|确定$/i.test(b.textContent.replace(/\s+/g, '')) && !b.disabled);
  if (!ok) {
    throw new Error('popconfirm ok button not found');
  }
  ok.click();
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
  needs_follow_up: false, affects_system_operation: false, impact_status: '',
  impact_status_text: '', importance: 'normal', importance_text: '普通',
  importance_reason: '', importance_marked_at: null, importance_marked_by_name: '',
  converted_fault: null, converted_fault_no: '',
  category: '', category_text: '', is_repeated: false,
  follow_up_name: '', planned_handle_at: null, resolved_at: null,
  triaged_at: null, triaged_by_name: '', triage_note: '',
  object_name: '', object_model: '', initial_reason: '', impact_scope: '',
  measures_taken: '', handling_result: '',
  created_by_name: 'admin', created_at: '2026-10-01 08:35', updated_at: null,
};

// 待研判详情（历史数据兼容状态：顶部同样只有 研判 按钮）
const PENDING_TRIAGE_DETAIL = {...RECORD_DETAIL, status: 'pending_triage',
  status_text: '待研判'};

const TODO_PAGE = {
  data: [
    {id: 21, record_no: 'YX20261001-0003', system: 1, system_name: '烟台通信系统',
     title: '链路质量待观察', status: 'following_up', status_text: '跟进中',
     needs_follow_up: true, affects_system_operation: false, impact_status: '',
     impact_status_text: '', importance: 'normal', importance_text: '普通',
     category: '', category_text: '', is_repeated: false,
     follow_up_name: '王值班', planned_handle_at: '2020-01-01 09:00',
     converted_fault: null, converted_fault_no: '',
     created_by_name: 'admin', created_at: '2026-10-01 09:00'},
  ],
  total: 1, overdue_count: 1, now: '2026-10-01 10:00',
};

const STATISTICS = {
  totals: {total: 5, following_up: 1, converted_fault: 1, duplicated: 2,
    important: 1, stale_open: 1, avg_resolve_hours: 2.5, resolved_count: 2},
  by_status: {recorded: 2, following_up: 1, converted_fault: 1, closed: 1},
  by_system: [{system: 1, system_name: '烟台通信系统', total: 5,
    following_up: 1, converted_fault: 1, important: 1}],
  trend: [{date: '2026-10-01', total: 3, converted_fault: 1}],
  occurred_from: '2026-09-02', occurred_to: '2026-10-03', stale_days: 7,
};

function mockDetailApis(detailResponse) {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/candidate-systems')) return Promise.resolve({data: SYSTEMS});
    if (url.includes('/progress/')) return Promise.resolve({data: []});
    if (url.includes('/attachments/')) return Promise.resolve({data: []});
    if (url.includes('/duplicate-links/')) {
      return Promise.resolve({data: [
        {id: 5, direction: 'inbound', direction_text: '被关联到',
         other_record: {id: 12, record_no: 'YX20261001-0002', title: '链路再中断'},
         note: '同一问题', created_by_name: 'admin', created_at: '2026-10-01 09:30'},
      ], outbound_count: 0, inbound_count: 1});
    }
    if (url.includes('/similar/')) {
      return Promise.resolve({data: [
        {id: 13, record_no: 'YX20261001-0004', system: 1, title: '链路又中断',
         occurred_at: '2026-10-01 12:00', status: 'recorded',
         status_text: '已记录', importance: 'normal'},
      ], window_days: 30});
    }
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

describe('运行记录 V2 · 研判', () => {
  it('已记录显示 研判+关闭（可留痕直关）；待研判只显示 研判；已关闭无业务按钮', async () => {
    await renderDetail();
    let texts = topButtonTexts();
    expect(texts).toContain('研判');
    expect(texts).not.toContain('提交研判');
    // 研判为可选动作：留痕记录可直接关闭，不要求先研判
    expect(texts).toContain('关闭');
    ReactDOM.unmountComponentAtNode(container);
    await renderDetail(PENDING_TRIAGE_DETAIL);
    texts = topButtonTexts();
    expect(texts).toContain('研判');
    expect(texts).not.toContain('提交研判');
    expect(texts).not.toContain('编辑');
    ReactDOM.unmountComponentAtNode(container);
    await renderDetail({...RECORD_DETAIL, status: 'closed', status_text: '已关闭'});
    texts = topButtonTexts();
    expect(texts).not.toContain('提交研判');
    expect(texts).not.toContain('研判');
  });

  it('研判弹窗：默认无需跟进结论提交 triage 载荷', async () => {
    const store = await renderDetail(PENDING_TRIAGE_DETAIL);
    clickButtonByTextExact('研判');
    await act(async () => {await flush();});
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/runtime-records/11/triage/');
    expect(payload.needs_follow_up).toBe(false);
    expect(payload.convert_to_fault).toBe(false);
    expect(payload.mark_important).toBe(false);
    expect(payload.triaged_at).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
    expect(store.triageVisible).toBe(false);
  });

  it('研判弹窗：需要跟进结论携带跟进人', async () => {
    await renderDetail(PENDING_TRIAGE_DETAIL);
    clickButtonByTextExact('研判');
    await act(async () => {await flush();});
    clickRadioByText('需要跟进');
    await act(async () => {await flush();});
    const input = document.querySelector('input[placeholder*="跟进人姓名"]');
    expect(input).toBeTruthy();
    await act(async () => {
      setInputValue(input, '王值班');
    });
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    const [, payload] = mockHttpPost.mock.calls[0];
    expect(payload.needs_follow_up).toBe(true);
    expect(payload.follow_up_name).toBe('王值班');
  });

  it('研判弹窗：转故障缺研判说明被客户端拦截，不发请求', async () => {
    await renderDetail(PENDING_TRIAGE_DETAIL);
    clickButtonByTextExact('研判');
    await act(async () => {await flush();});
    clickRadioByText('转为正式故障');
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  it('研判弹窗：转故障填写说明后提交 convert_to_fault', async () => {
    await renderDetail(PENDING_TRIAGE_DETAIL);
    clickButtonByTextExact('研判');
    await act(async () => {await flush();});
    clickRadioByText('转为正式故障');
    await act(async () => {await flush();});
    const note = document.querySelector('textarea[placeholder*="确认依据"]');
    expect(note).toBeTruthy();
    await act(async () => {
      setInputValue(note, '现场确认设备故障');
    });
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    const [, payload] = mockHttpPost.mock.calls[0];
    expect(payload.convert_to_fault).toBe(true);
    expect(payload.needs_follow_up).toBe(false);
    expect(payload.triage_note).toBe('现场确认设备故障');
  });

  it('研判提交失败：不崩溃、弹窗保持打开等待修正', async () => {
    const store = await renderDetail(PENDING_TRIAGE_DETAIL);
    clickButtonByTextExact('研判');
    await act(async () => {await flush();});
    mockHttpPost.mockRejectedValue(new Error('系统繁忙，请稍后重试'));
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(store.triageVisible).toBe(true);
    expect(bodyText()).toContain('研判');
  });
});

describe('运行记录 V2 · 待办视图', () => {
  it('只展示跟进中记录，超期/排序筛选参数生效，超期提示可见', async () => {
    const store = require('../store').default;
    const RecordTodo = require('../RecordTodo').default;
    mockHttpGet.mockImplementation((url, config) => {
      expect(url).toBe('/api/equipment-lifecycle/runtime-records/todo/');
      return Promise.resolve(TODO_PAGE);
    });
    store.f_todo_overdue = true;
    store.f_todo_order = 'recent';
    await act(async () => {
      ReactDOM.render(<RecordTodo/>, container);
    });
    await act(async () => {await flush();});
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/todo/',
      expect.objectContaining({params: expect.objectContaining({
        overdue: 'yes', order: 'recent',
      })}),
    );
    const text = bodyText();
    expect(text).toContain('YX20261001-0003');
    expect(text).toContain('王值班');
    expect(text).toContain('超期');
    expect(text).toContain('当前有1条跟进中记录已超过计划处理时间');
  });

  it('无待办时展示空态文案', async () => {
    const RecordTodo = require('../RecordTodo').default;
    mockHttpGet.mockResolvedValue({data: [], total: 0, overdue_count: 0});
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
    expect(text).toContain('重复问题');
    expect(text).toContain('长期未关闭');
    expect(text).toContain('平均处理时长');
    expect(text).toContain('烟台通信系统');
    expect(text).toContain('2026-10-01');
    // 状态维度 Tag：已记录 2
    expect(text).toContain('已记录：2');
  });
});

describe('运行记录 V2 · 重复问题', () => {
  it('重复问题页签展示已关联记录与相似记录', async () => {
    await renderDetail();
    await act(async () => {
      clickTabByText('重复问题');
    });
    await act(async () => {await flush();});
    const text = bodyText();
    expect(text).toContain('被关联到');
    expect(text).toContain('YX20261001-0002');
    expect(text).toContain('相似记录');
    expect(text).toContain('YX20261001-0004');
  });

  it('关联相似记录：确认后 POST duplicate-links', async () => {
    await renderDetail();
    await act(async () => {
      clickTabByText('重复问题');
    });
    await act(async () => {await flush();});
    clickButtonByTextExact('关联');
    await act(async () => {await flush();});
    const note = document.querySelector('input[placeholder*="关联说明"]');
    expect(note).toBeTruthy();
    await act(async () => {
      setInputValue(note, '同一链路问题');
    });
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByText('确认');
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/11/duplicate-links/',
      {duplicate_id: 13, note: '同一链路问题'});
  });

  it('取消关联：确认后 DELETE duplicate-links', async () => {
    await renderDetail();
    await act(async () => {
      clickTabByText('重复问题');
    });
    await act(async () => {await flush();});
    mockHttpDelete.mockResolvedValue({});
    await act(async () => {
      clickButtonByText('取消关联');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickPopconfirmOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpDelete).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/11/duplicate-links/5/');
  });

  it('标记重复发生：切换后 POST mark-repeated', async () => {
    await renderDetail();
    await act(async () => {
      clickTabByText('重复问题');
    });
    await act(async () => {await flush();});
    mockHttpPost.mockResolvedValue({...RECORD_DETAIL, is_repeated: true});
    const sw = document.querySelector('.ant-tabs-tabpane-active button.ant-switch');
    expect(sw).toBeTruthy();
    await act(async () => {
      sw.click();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/11/mark-repeated/',
      {is_repeated: true});
  });
});

describe('运行记录 V2 · 权限控制', () => {
  it('无 link 权限时重复问题操作入口不渲染', async () => {
    const libs = require('libs');
    const originalIsSuper = libs.Permission.isSuper;
    libs.Permission.isSuper = false;
    libs.hasPermission.mockImplementation(
      code => !code.endsWith('.link'));
    try {
      await renderDetail();
      await act(async () => {
        clickTabByText('重复问题');
      });
      await act(async () => {await flush();});
      const texts = Array.from(document.querySelectorAll('button'))
        .map(b => b.textContent.replace(/\s+/g, ''));
      expect(texts).not.toContain('关联');
      expect(texts).not.toContain('取消关联');
      // 查看能力仍在：相似记录列表正常渲染
      expect(bodyText()).toContain('YX20261001-0004');
    } finally {
      libs.Permission.isSuper = originalIsSuper;
      libs.hasPermission.mockReset();
      libs.hasPermission.mockImplementation(() => true);
    }
  });
});
