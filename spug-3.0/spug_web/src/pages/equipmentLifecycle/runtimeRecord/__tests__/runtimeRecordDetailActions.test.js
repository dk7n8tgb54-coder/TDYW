/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行记录详情顶部按钮按状态收敛测试（2026-10-05 第四版：研判不再是必经
 * 步骤，TriageModal 整体删除；2026-10-06 跟进计划删除，重新跟进由追加处理
 * 进展触发）。真实渲染 RecordDetail（ReactDOM + jsdom，仓库惯例），mock
 * libs.http，验证：
 * - 按钮矩阵（状态已收敛为四状态，历史 pending_triage/no_follow_up/resolved/
 *   closed 由迁移 0007 归一，前端不再特判）：recorded = 编辑 + 开始跟进 +
 *   转为正式故障；following_up = 新增跟进记录 + 完成跟进 + 转为正式故障
 *   （修改跟进计划已随跟进计划删除移除）；completed（已完成）= 重新跟进；
 *   converted_fault = 查看关联故障；
 * - 已删除入口：提交研判/研判/重新研判/无需跟进/关闭运行记录/跟进安排/
 *   影响判定/标记重要/修改跟进计划（TriageModal 与跟进计划弹窗不再存在）；
 * - 详情底部"关 闭"只关闭窗口，不改业务状态；
 * - 开始跟进/新增跟进记录/重新跟进：跳到处理进展页签，页签内联表单
 *   提交走 progress 端点（2026-10-06 优化：内联录入，去弹窗）；
 * - 完成跟进走 resolve 端点（纯确认，不携带处理结果字段）；转为正式故障
 *   走 convert-to-fault 端点；
 * - 动作被后端拒绝（Promise 拒绝）时不弹成功提示；
 * - 只记录场景闭环：保存 → 关闭详情 → 重新打开 → 仍可开始跟进。
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
  needs_follow_up: false,
  converted_fault: null, converted_fault_no: '',
  category: '', category_text: '', is_repeated: false,
  follow_up_name: '', planned_handle_at: null, resolved_at: null,
  triaged_at: null, triaged_by_name: '', triage_note: '',
  initial_reason: '', impact_scope: '',
  measures_taken: '', handling_result: '',
  created_by_name: 'admin', created_at: '2026-10-04 08:35', updated_at: null,
};

function mockDetailApis(detailResponse) {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/candidate-systems')) return Promise.resolve({data: []});
    if (url.includes('/progress/')) return Promise.resolve({data: []});
    if (url.includes('/attachments/')) return Promise.resolve({data: []});
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

describe('运行记录详情 · 顶部按钮按状态收敛（已记录族）', () => {
  const FORBIDDEN = ['提交研判', '研判', '重新研判', '无需跟进', '关闭',
    '跟进安排', '完成跟进', '重新跟进', '查看处理进展', '标记重要'];

  it('recorded：显示 编辑+开始跟进+转为正式故障，无研判/关闭/标记重要入口', async () => {
    await renderDetail();
    const texts = buttonTexts();
    ['编辑', '开始跟进', '转为正式故障'].forEach(btn => {
      expect(texts).toContain(btn);
    });
    FORBIDDEN.forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });

  it('recorded 底部"关 闭"只关闭详情窗口，不调用任何状态接口', async () => {
    const store = await renderDetail();
    await act(async () => {
      clickButtonByTextExact('关闭');
    });
    await act(async () => {await flush();});
    expect(store.detailVisible).toBe(false);
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  it('保存记录 → 关闭详情 → 重新打开：recorded 仍可开始跟进（无需研判即可离开）', async () => {
    const store = require('../store').default;
    mockDetailApis();
    mockHttpPost.mockResolvedValue({});
    store.showForm();
    await act(async () => {
      await store.submitForm({
        system: 1, occurred_at: '2026-10-04 08:30',
        title: '主用链路短暂中断', description: '值班发现主用链路丢包',
        registrar_name: '张三', client_token: 'rt-save-reopen',
      });
    });
    await act(async () => {await flush();});
    expect(store.formVisible).toBe(false);
    expect(store.detailVisible).toBe(false);
    const postUrls = mockHttpPost.mock.calls.map(call => call[0]);
    expect(postUrls).toEqual(['/api/equipment-lifecycle/runtime-records/']);
    expect(mockHttpGet.mock.calls.map(call => call[0]))
      .toContain('/api/equipment-lifecycle/runtime-records/');
    const RecordDetail = require('../RecordDetail').default;
    ReactDOM.unmountComponentAtNode(container);
    await renderDetail();
    const texts = buttonTexts();
    expect(texts).toContain('开始跟进');
    FORBIDDEN.forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });
});

describe('运行记录详情 · 顶部按钮按状态收敛（跟进/完成/终态）', () => {
  it('following_up：显示 新增跟进记录+完成跟进+转为正式故障，无 编辑/开始跟进/标记重要/修改跟进计划', async () => {
    await renderDetail({status: 'following_up', status_text: '跟进中'});
    const texts = buttonTexts();
    ['新增跟进记录', '完成跟进', '转为正式故障'].forEach(btn => {
      expect(texts).toContain(btn);
    });
    ['编辑', '开始跟进', '标记重要', '研判', '重新跟进', '关闭',
      '添加处理进展', '修改跟进计划'].forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });

  it('completed：显示 重新跟进（已完成不提供关闭/完成跟进/编辑）', async () => {
    await renderDetail({status: 'completed', status_text: '已完成',
      resolved_at: '2026-10-04 10:00'});
    const texts = buttonTexts();
    expect(texts).toContain('重新跟进');
    ['编辑', '研判', '开始跟进', '完成跟进', '转为正式故障',
      '标记重要', '关闭', '修改跟进计划'].forEach(btn => {
      expect(texts).not.toContain(btn);
    });
  });

  it('converted_fault：显示 查看关联故障，无其他业务按钮', async () => {
    await renderDetail({status: 'converted_fault', status_text: '已转故障',
      converted_fault: 88, converted_fault_no: 'GZ20261004-0001'});
    const convertedTexts = buttonTexts();
    expect(convertedTexts).toContain('查看关联故障');
    ['编辑', '研判', '开始跟进', '完成跟进', '重新跟进', '标记重要',
      '转为正式故障', '关闭'].forEach(btn => {
      expect(convertedTexts).not.toContain(btn);
    });
    expect(document.body.textContent).toContain('GZ20261004-0001');
  });

  it('converted_fault 关联故障已撤销：无查看入口（无可跳转对象）', async () => {
    await renderDetail({status: 'converted_fault', status_text: '已转故障',
      converted_fault: null, converted_fault_no: ''});
    const texts = buttonTexts();
    expect(texts).not.toContain('查看关联故障');
  });
});

// 内联新增处理进展表单（2026-10-06 优化：页签内直接填写，去弹窗）必填：
// 处理人（tags 手输回车）+ 处理内容（textarea）；处理时间缺省当前时间。
// 输入与回车分两次 act（模拟真实输入节奏）。表单在处理进展页签内，
// 需先点击顶部跟进动作（或页签）让页签挂载；详情为 Modal 门户渲染，
// 查询范围是 document 而非组件容器。
async function fillInlineProgressForm() {
  // 处理人：处理进展页签内唯一的 Select tags 输入框
  const tagInput = document.querySelector('.ant-select input');
  expect(tagInput).toBeTruthy();
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    setter.call(tagInput, '值班员甲');
    tagInput.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {await flush();});
  await act(async () => {
    const ev = new KeyboardEvent('keydown', {key: 'Enter', bubbles: true});
    Object.defineProperty(ev, 'keyCode', {get: () => 13});
    Object.defineProperty(ev, 'which', {get: () => 13});
    tagInput.dispatchEvent(ev);
  });
  await act(async () => {await flush();});
  // 处理内容：页签内唯一的 textarea（更正弹窗未打开）
  const textarea = document.querySelector('textarea');
  expect(textarea).toBeTruthy();
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, '现场检查，确认恢复');
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

// 提交内联表单：点击"追加进展"按钮（输入与提交分属不同 act，模拟真实节奏）
async function submitInlineProgressForm() {
  const button = Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === '追加进展' && !b.disabled);
  expect(button).toBeTruthy();
  await act(async () => {
    button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

describe('运行记录详情 · 动作端点（新流程）', () => {
  it('recorded 开始跟进：跳到处理进展页签，内联表单提交 progress 端点', async () => {
    await renderDetail();
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('开始跟进');
    });
    await act(async () => {await flush();});
    // 处理进展页签已挂载（内联录入表单可见）
    expect(document.querySelector('.ant-select input')).toBeTruthy();
    await fillInlineProgressForm();
    await submitInlineProgressForm();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/progress/',
      expect.objectContaining({content: '现场检查，确认恢复',
        handler_name: '值班员甲'}));
  });

  it('following_up 新增跟进记录：跳到处理进展页签，内联表单提交 progress 端点', async () => {
    await renderDetail({status: 'following_up', status_text: '跟进中'});
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('新增跟进记录');
    });
    await act(async () => {await flush();});
    expect(document.querySelector('.ant-select input')).toBeTruthy();
    await fillInlineProgressForm();
    await submitInlineProgressForm();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/progress/',
      expect.objectContaining({content: '现场检查，确认恢复'}));
  });

  it('following_up 完成跟进提交 resolve 端点（进入已完成，不要求关闭）', async () => {
    await renderDetail({status: 'following_up', status_text: '跟进中'});
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('完成跟进');
    });
    await act(async () => {await flush();});
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles).toContain('完成跟进');
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    // 完成跟进为纯确认动作，不再携带处理结果字段
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/resolve/',
      {});
  });

  it('recorded 标记重要入口已随字段删除移除（2026-10-06）：无按钮、无 mark-important 请求', async () => {
    await renderDetail();
    mockHttpPost.mockResolvedValue({});
    const texts = buttonTexts();
    expect(texts).not.toContain('标记重要');
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles.some(t => t.includes('标记重要'))).toBe(false);
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

});

describe('运行记录详情 · 动作端点（重新跟进/终态跳转）', () => {
  it('recorded 转为正式故障提交 convert-to-fault 端点（不依赖研判）', async () => {
    await renderDetail();
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('转为正式故障');
    });
    await act(async () => {await flush();});
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles).toContain('转为正式故障');
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/convert-to-fault/',
      {phenomenon: '', re_dispose_reason: ''});
  });

  it('following_up 转为正式故障提交 convert-to-fault 端点', async () => {
    await renderDetail({status: 'following_up', status_text: '跟进中'});
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('转为正式故障');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/convert-to-fault/',
      {phenomenon: '', re_dispose_reason: ''});
  });

  it('completed 重新跟进：跳到处理进展页签，追加处理进展提交 progress 端点', async () => {
    await renderDetail({status: 'completed', status_text: '已完成'});
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByTextExact('重新跟进');
    });
    await act(async () => {await flush();});
    // 已完成工作区提示：追加新的处理进展将重新进入跟进中
    expect(document.body.textContent).toContain('追加新的处理进展将重新进入跟进中');
    // follow-up 跟进计划端点已删除：重新跟进只发 progress 请求
    expect(document.querySelector('.ant-select input')).toBeTruthy();
    await fillInlineProgressForm();
    await submitInlineProgressForm();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/progress/',
      expect.objectContaining({content: '现场检查，确认恢复'}));
  });

  it('converted_fault 查看关联故障：关闭详情并跳转故障模块', async () => {
    const {history} = require('libs');
    const store = await renderDetail({status: 'converted_fault',
      status_text: '已转故障', converted_fault: 88,
      converted_fault_no: 'GZ20261004-0001'});
    await act(async () => {
      clickButtonByTextExact('查看关联故障');
    });
    await act(async () => {await flush();});
    expect(history.push).toHaveBeenCalledWith('/el/faults?detail=88');
    expect(store.detailVisible).toBe(false);
  });

  it('页面不再渲染 TriageModal（研判弹窗已整体删除）', async () => {
    await renderDetail();
    const modalTitles = Array.from(document.querySelectorAll('.ant-modal-title'))
      .map(el => el.textContent);
    expect(modalTitles.some(t => t.includes('研判'))).toBe(false);
    expect(document.body.textContent).not.toContain('跟进结论');
  });
});

describe('运行记录详情 · 动作被后端拒绝时不弹成功提示', () => {
  it('完成跟进请求被后端拒绝：无成功提示，确认弹窗保持打开', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    await renderDetail({status: 'following_up', status_text: '跟进中'});
    mockHttpPost.mockRejectedValue({error: '当前状态不能完成跟进'});
    await act(async () => {
      clickButtonByTextExact('完成跟进');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/resolve/',
      {});
    expect(successSpy).not.toHaveBeenCalled();
    expect(document.querySelectorAll('.ant-modal').length).toBeGreaterThan(0);
  });

  it('转为正式故障请求被后端拒绝：无成功提示，确认弹窗保持打开', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    await renderDetail();
    mockHttpPost.mockRejectedValue({error: '该运行记录已转故障，不能重复转换'});
    await act(async () => {
      clickButtonByTextExact('转为正式故障');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/convert-to-fault/',
      {phenomenon: '', re_dispose_reason: ''});
    expect(successSpy).not.toHaveBeenCalled();
  });

  it('开始跟进（追加进展）请求被后端拒绝：无成功提示，表单数据保留', async () => {
    const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    await renderDetail();
    mockHttpPost.mockRejectedValue({error: '系统繁忙，请稍后重试'});
    await act(async () => {
      clickButtonByTextExact('开始跟进');
    });
    await act(async () => {await flush();});
    await fillInlineProgressForm();
    await submitInlineProgressForm();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/31/progress/',
      expect.objectContaining({content: '现场检查，确认恢复'}));
    expect(successSpy).not.toHaveBeenCalled();
  });
});
