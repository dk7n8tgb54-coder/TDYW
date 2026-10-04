/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行记录详情顶部按钮按状态收敛测试（2026-10-04）。
 * 真实渲染 RecordDetail（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 按钮矩阵：recorded=编辑+研判（可选）+关闭（留痕可直接关闭，不要求先研判）；
 *   pending_triage=研判（历史数据兼容）；
 *   following_up=编辑+跟进安排+标记已处理+关闭；resolved=编辑+重新跟进+关闭；
 *   no_follow_up=重新研判；converted_fault/closed 无业务按钮；
 * - 顶部无独立"标记重要"/"转为故障"入口（只能在研判弹窗内完成），
 *   也无"提交研判"中转按钮（同一操作主体登记+研判）；
 * - 点击 研判/重新研判 打开现有 TriageModal，提交走 triage 端点；
 * - 重新跟进复用跟进弹窗，提交走 follow-up 端点；
 * - 动作被后端拒绝（Promise 拒绝）时不弹成功提示、弹窗保持打开。
 * 所有请求只指向 equipment-lifecycle 前缀。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import { message } from 'antd';

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
  jest.restoreAllMocks();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function buttonTexts() {
  // 排除详情弹窗 footer 的"关 闭"外壳按钮，只看业务动作
  return Array.from(document.querySelectorAll('button'))
    .filter(b => !b.closest('.ant-modal-footer'))
    .map(b => b.textContent.replace(/\s+/g, ''));
}

function clickButtonByTextExact(text) {
  const buttons = Array.from(document.querySelectorAll('button'))
    .filter(b => b.textContent.replace(/\s+/g, '') === text && !b.disabled);
  if (!buttons.length) {
    throw new Error(`button not found: ${text}`);
  }
  buttons[0].click();
}

function clickModalOk() {
  const ok = Array.from(document.querySelectorAll('.ant-modal button'))
    .find(b => /^ok|确定$/i.test(b.textContent.replace(/\s+/g, '')) && !b.disabled);
  if (!ok) {
    throw new Error('modal ok button not found');
  }
  ok.click();
}

const RECORD_DETAIL = {
  id: 31, record_no: 'YX20261004-0001', system: 1,
  system_name: '烟台通信系统', system_code: 'SYS-A1', system_location: '机房A',
  occurred_at: '2026-10-04 08:30', title: '主用链路短暂中断',
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
  created_by_name: 'admin', created_at: '2026-10-04 08:35', updated_at: null,
};

function mockDetailApis(detailResponse) {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/candidate-systems')) return Promise.resolve({data: []});
    if (url.includes('/progress/')) return Promise.resolve({data: []});
    if (url.includes('/attachments/')) return Promise.resolve({data: []});
    if (url.includes('/duplicate-links/')) {
      return Promise.resolve({data: [], outbound_count: 0, inbound_count: 0});
    }
    if (url.includes('/similar/')) return Promise.resolve({data: [], window_days: 30});
    if (/\/runtime-records\/\d+\/$/.test(url)) {
      return Promise.resolve(detailResponse || RECORD_DETAIL);
    }
    return Promise.resolve({data: [], total: 0});
  });
}

async function renderDetail(overrides) {
  const store = require('../store').default;
  const RecordDetail = require('../RecordDetail').default;
  const detail = {...RECORD_DETAIL, ...overrides};
  mockDetailApis(detail);
  await act(async () => {
    store.showDetail({...detail});
    ReactDOM.render(<RecordDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

describe('运行记录详情 · 顶部按钮按状态收敛', () => {
  it('recorded：显示 编辑 + 研判（可选）+ 关闭，无提交研判中转', async () => {
    await renderDetail();
    const texts = buttonTexts();
    expect(texts).toContain('编辑');
    expect(texts).toContain('研判');
    // 留痕记录可直接关闭，不要求先研判
    expect(texts).toContain('关闭');
    ['提交研判', '跟进安排', '标记已处理', '重新跟进', '标记重要', '转为故障',
      '重新研判'].forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });

  it('recorded 点击关闭直接走 close 端点（无需先研判）', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    await renderDetail();
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('关闭');
    });
    await act(async () => {await flush();});
    // 关闭确认弹窗打开（可填写处理结果，确认后才提交）
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles).toContain('关闭运行记录');
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/close/',
      {handling_result: ''});
    expect(successSpy).toHaveBeenCalled();
  });

  it('pending_triage：只显示 研判（主要动作）', async () => {
    await renderDetail({status: 'pending_triage', status_text: '待研判'});
    const texts = buttonTexts();
    expect(texts).toContain('研判');
    ['编辑', '提交研判', '跟进安排', '标记已处理', '重新跟进', '标记重要',
      '转为故障', '关闭', '重新研判'].forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });

  it('following_up：显示 编辑/跟进安排/标记已处理/关闭，无 标记重要/转为故障', async () => {
    await renderDetail({status: 'following_up', status_text: '跟进中'});
    const texts = buttonTexts();
    ['编辑', '跟进安排', '标记已处理', '关闭'].forEach(btn => {
      expect(texts).toContain(btn);
    });
    ['标记重要', '转为故障', '研判', '提交研判', '重新跟进', '重新研判'].forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });

  it('resolved：显示 编辑/重新跟进/关闭', async () => {
    await renderDetail({status: 'resolved', status_text: '已处理'});
    const texts = buttonTexts();
    ['编辑', '重新跟进', '关闭'].forEach(btn => {
      expect(texts).toContain(btn);
    });
    ['跟进安排', '标记已处理', '标记重要', '转为故障', '研判', '提交研判',
      '重新研判'].forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });

  it('no_follow_up：只显示 重新研判，无普通编辑/跟进安排', async () => {
    await renderDetail({status: 'no_follow_up', status_text: '无需跟进'});
    const texts = buttonTexts();
    expect(texts).toContain('重新研判');
    ['编辑', '跟进安排', '标记已处理', '重新跟进', '关闭', '标记重要',
      '转为故障', '研判', '提交研判'].forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });

  it('converted_fault / closed：不显示任何业务处理按钮', async () => {
    await renderDetail({status: 'converted_fault', status_text: '已转故障',
      converted_fault: 88, converted_fault_no: 'GZ20261004-0001'});
    const convertedTexts = buttonTexts();
    ['编辑', '提交研判', '研判', '跟进安排', '标记已处理', '重新跟进',
      '标记重要', '转为故障', '关闭', '重新研判'].forEach(btn => {
      expect(convertedTexts).not.toContain(btn);
    });
    // 已转故障保留关联故障入口（详情基本信息内）
    expect(document.body.textContent).toContain('GZ20261004-0001');
    ReactDOM.unmountComponentAtNode(container);
    await renderDetail({status: 'closed', status_text: '已关闭'});
    const closedTexts = buttonTexts();
    ['编辑', '提交研判', '研判', '跟进安排', '标记已处理', '重新跟进',
      '标记重要', '转为故障', '关闭', '重新研判'].forEach(btn => {
      expect(closedTexts).not.toContain(btn);
    });
  });
});

describe('运行记录详情 · 动作走既有弹窗与端点', () => {
  it('recorded 点击研判打开现有 TriageModal，确认提交 triage 端点', async () => {
    await renderDetail();
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('研判');
    });
    await act(async () => {await flush();});
    // 现有研判弹窗打开（标题携带记录编号）
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles.some(t => t.includes('研判 - YX20261004-0001'))).toBe(true);
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/triage/',
      expect.objectContaining({needs_follow_up: false, convert_to_fault: false}));
  });

  it('pending_triage 点击研判打开同一 TriageModal（历史数据兼容）', async () => {
    await renderDetail({status: 'pending_triage', status_text: '待研判'});
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('研判');
    });
    await act(async () => {await flush();});
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles.some(t => t.includes('研判 - YX20261004-0001'))).toBe(true);
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/triage/',
      expect.objectContaining({needs_follow_up: false}));
  });

  it('no_follow_up 重新研判打开 TriageModal，可改判为需要跟进', async () => {
    await renderDetail({status: 'no_follow_up', status_text: '无需跟进'});
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('重新研判');
    });
    await act(async () => {await flush();});
    const radios = Array.from(document.querySelectorAll('.ant-radio-wrapper'))
      .filter(el => el.textContent.replace(/\s+/g, '').includes('需要跟进'));
    expect(radios.length).toBe(1);
    await act(async () => {
      radios[0].click();
    });
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/triage/',
      expect.objectContaining({needs_follow_up: true}));
  });

  it('resolved 重新跟进复用跟进弹窗，提交 follow-up 端点', async () => {
    await renderDetail({status: 'resolved', status_text: '已处理'});
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('重新跟进');
    });
    await act(async () => {await flush();});
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles).toContain('重新跟进');
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/follow-up/',
      {follow_up_name: '', planned_handle_at: ''});
  });
});

describe('运行记录详情 · 非法状态动作被后端拒绝时不弹成功提示', () => {
  it('关闭请求被后端拒绝：无成功提示，确认弹窗保持打开', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    await renderDetail({status: 'following_up', status_text: '跟进中'});
    mockHttpPost.mockRejectedValue({error: '当前状态不能关闭'});
    await act(async () => {
      clickButtonByTextExact('关闭');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/close/',
      {handling_result: ''});
    expect(successSpy).not.toHaveBeenCalled();
    // 弹窗保持打开等待修正（关闭动作弹窗仍存在）
    expect(document.querySelectorAll('.ant-modal').length).toBeGreaterThan(0);
  });

  it('重新跟进请求被后端拒绝：无成功提示，跟进弹窗保持打开', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    await renderDetail({status: 'resolved', status_text: '已处理'});
    mockHttpPost.mockRejectedValue({error: '当前状态不能标记为需要跟进'});
    await act(async () => {
      clickButtonByTextExact('重新跟进');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/follow-up/',
      {follow_up_name: '', planned_handle_at: ''});
    expect(successSpy).not.toHaveBeenCalled();
  });

  it('recorded 研判请求被后端拒绝：无成功提示，研判弹窗保持打开', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    await renderDetail();
    mockHttpPost.mockRejectedValue({error: '系统繁忙，请稍后重试'});
    await act(async () => {
      clickButtonByTextExact('研判');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/triage/',
      expect.objectContaining({needs_follow_up: false}));
    expect(successSpy).not.toHaveBeenCalled();
    // 研判弹窗保持打开等待修正
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles.some(t => t.includes('研判 - YX20261004-0001'))).toBe(true);
  });
});
