/**
 * 常驻"今日巡检"工作台测试（真实渲染 ReactDOM + jsdom，惯例同 LedgerPage.test.js）。
 *
 * 验证"一日一账"契约（对齐纸质台账：同一天多次检查累积在同一张草稿台账）：
 * - 打开即填：无暂存无当日台账时引导选择模板，不发预览请求；
 * - 沿用上次模板组合：挂载自动按 系统×模板 调用预览接口展开明细，表头默认
 *   （执行日期=今天、检查时刻=当前时刻、执行人=当前登录人）；
 * - 记录本次检查：首轮 POST 创建草稿（明细带 executed_at），后续轮 PUT 追加
 *   （已有明细带 id 仅报填写值 + version 并发，新明细带本轮 executed_at）；
 *   成功后以服务器详情还原已记录轮次、清空当前轮、刷新检查时刻；
 * - 提交台账：POST /submit/ 草稿转待复核，成功后清空当日台账状态；
 * - 挂载恢复：当日草稿还原为只读轮次网格（列头=检查时刻），本地暂存只恢复
 *   当前未记录轮，两者可并存；本地暂存日期与当日草稿不一致时弃用；
 * - 一日一账护栏：已有草稿时改执行日期需确认另起一张；无草稿时改日期即补录；
 * - 当日已提交/复核台账存在时顶部提示。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

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
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement('span', null, props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell,
    AuthButton,
    Breadcrumb,
    SearchForm: Shell,
  };
});

// jsdom 未实现 matchMedia，antd 渲染需要
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

import {makeRow, todayStr} from '../ledgerCommon';

let container = null;

const TODAY = todayStr();

const SYSTEMS = [
  {id: 11, system_code: 'S1', name: '系统一', install_location: '机房A'},
  {id: 12, system_code: 'S2', name: '系统二', install_location: '机房B'},
  {id: 99, system_code: 'S9', name: '停用系统', install_location: '机房X', is_active: false},
];
const TEMPLATES = [{
  id: 5, name: '全科巡检模板', items_count: 1,
}];
const PREVIEW_DATA = [11, 12].map(sid => ({
  system: {id: sid, system_code: `S${sid - 10}`, name: `系统${sid - 10}`, install_location: '机房'},
  template: {id: 5, name: '全科巡检模板'},
  items: [sid === 11 ? {
    id: 200 + sid, name: '外观检查', input_type: 'choice',
    unit: '', choices: ['正常', '不正常'], is_required: false, default_value: '',
  } : {
    id: 200 + sid, name: '电源电压', input_type: 'text',
    unit: '', choices: [], is_required: false, default_value: '',
  }],
}));

const LAST_KEY = `el_ledger_ws_last_inspection_${encodeURIComponent('张三')}`;
const DRAFT_KEY = `el_ledger_ws_draft_inspection_${encodeURIComponent('张三')}`;

/**
 * 构造台账详情（模拟 http 拦截器解包后的返回：详情接口直接返回字典）。
 * rounds: [{time: '08:35', values: {11: '正常', 12: '52V'}}]
 */
function makeDetail(rounds, overrides = {}) {
  let itemId = 500;
  const items = [];
  rounds.forEach(r => {
    [11, 12].forEach(sid => {
      items.push({
        id: itemId++,
        ledger: 90,
        system: sid,
        system_code: `S${sid - 10}`,
        system_name: `系统${sid - 10}`,
        system_location: '机房',
        template_item: 200 + sid,
        template_name: '全科巡检模板',
        item_name: sid === 11 ? '外观检查' : '电源电压',
        input_type: sid === 11 ? 'choice' : 'text',
        unit: '',
        choices: sid === 11 ? ['正常', '不正常'] : [],
        is_required: false,
        abnormal_rule: '',
        execution_scope: 'all',
        value_text: r.values[sid] || '',
        value_number: null,
        value_bool: null,
        result: r.values[sid] === '不正常' ? 'abnormal' : 'normal',
        abnormal_desc: '',
        na_reason: '',
        onsite_action: '',
        executor_name: '',
        executed_at: `${TODAY} ${r.time}:00`,
        is_temporary: false,
        display_order: 1,
      });
    });
  });
  return {
    id: 90,
    ledger_no: 'EL-INS-20260923-0001',
    ledger_type: 'inspection',
    maintenance_cycle: '',
    executed_date: TODAY,
    executor_names: '张三',
    status: 'draft',
    entry_channel: 'web',
    created_from: 'template',
    version: rounds.length,
    items,
    corrections: [],
    ...overrides,
  };
}

function todayListMock(records) {
  // 模拟 http 拦截器解包后的列表返回：{data: 记录数组, total}
  return Promise.resolve({data: records, total: records.length});
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  sessionStorage.setItem('nickname', '张三');
  window.localStorage.clear();
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/systems/')) return Promise.resolve({data: SYSTEMS, total: 2});
    if (url.includes('/ledger-templates/available/')) return Promise.resolve({data: TEMPLATES});
    if (/\/ledgers\/\d+\/$/.test(url)) return Promise.resolve({});
    if (/\/ledgers\/$/.test(url)) return todayListMock([]);
    return Promise.resolve({data: []});
  });
  mockHttpPost.mockImplementation((url) => {
    if (url.endsWith('/ledgers/preview/')) return Promise.resolve({data: PREVIEW_DATA});
    return Promise.resolve({});
  });
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  // 清理 Modal.confirm 等渲染到 body 的节点
  Array.from(document.body.children).forEach(node => {
    if (node !== container) node.remove();
  });
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function renderWorksheet() {
  const mod = require('../LedgerWorksheet');
  const LedgerWorksheet = mod.LedgerWorksheet;
  let instance = null;
  await act(async () => {
    ReactDOM.render(h(LedgerWorksheet, {
      ref: r => {
        instance = r;
      }, ledgerType: 'inspection',
    }), container);
  });
  await act(async () => {});
  return instance;
}

describe('今日巡检常驻工作台（一日一账）', () => {
  test('首次打开（无暂存无当日台账）：不发预览请求，显示引导与模板调整区', async () => {
    const instance = await renderWorksheet();
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(instance.state.adjustVisible).toBe(true);
    expect(instance.state.ledgerId).toBeNull();
    expect(container.textContent).toContain('未选择模板');
    expect(container.textContent).toContain('应用并展开');
  });

  test('沿用上次模板组合：挂载自动展开，表头默认今天/当前时刻/当前登录人', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({
      templateEntries: [{template_id: 5}],
    }));
    const instance = await renderWorksheet();
    // 预览请求条目带 系统+模板：模板自动覆盖全部未停用系统（停用系统剔除）
    const previewCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/preview/'));
    expect(previewCalls).toHaveLength(1);
    expect(previewCalls[0][1]).toEqual({
      ledger_type: 'inspection',
      maintenance_cycle: '',
      entries: [
        {system_id: 11, template_id: 5},
        {system_id: 12, template_id: 5},
      ],
    });
    // 多系统明细展开 + 表头默认值
    expect(instance.state.rows).toHaveLength(2);
    expect(instance.state.rows.map(r => r.system_id)).toEqual([11, 12]);
    expect(instance.state.rows.every(r => r.template_id === 5)).toBe(true);
    expect(instance.state.header.executed_date).toBe(TODAY);
    expect(instance.state.header.executor_names).toBe('张三');
    expect(instance.state.roundTime).toMatch(/^\d{2}:\d{2}$/);
    // 空骨架不入暂存：开始填写后才产生草稿
    expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull();
    await act(async () => {
      instance.setRow(instance.state.rows[0].client_key, {value_text: '51V'});
    });
    const draft = JSON.parse(window.localStorage.getItem(DRAFT_KEY));
    expect(draft.rows).toHaveLength(2);
    expect(draft.round_time).toMatch(/^\d{2}:\d{2}$/);
    expect(draft.client_token).toBeTruthy();
  });

  test('旧版单配对种子兼容：归一为模板条目并展开全部可用电台', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({
      templateEntries: [{system_id: 11, template_id: 5}],
    }));
    await renderWorksheet();
    const previewCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/preview/'));
    expect(previewCalls).toHaveLength(1);
    expect(previewCalls[0][1].entries).toEqual([
      {system_id: 11, template_id: 5},
      {system_id: 12, template_id: 5},
    ]);
  });

  test('有未提交暂存：重开自动恢复当前轮并提示，不发预览请求', async () => {
    const savedRows = [makeRow({
      system_id: 11, template_id: 5, template_item_id: 211,
      item_name: '电源电压', input_type: 'text', value_text: '51V',
    })];
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify({
      templateEntries: [{system_id: 11, template_id: 5}],
      rows: savedRows,
      header: {executed_date: TODAY, executor_names: '张三'},
      round_time: '07:50',
      client_token: 'ws_saved_1',
      saved_at: Date.now(),
    }));
    const instance = await renderWorksheet();
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(instance.state.restored).toBe(true);
    expect(instance.state.rows).toHaveLength(1);
    expect(instance.state.rows[0].value_text).toBe('51V');
    expect(instance.state.roundTime).toBe('07:50');
    expect(instance.state.clientToken).toBe('ws_saved_1');
    expect(container.textContent).toContain('已恢复上次未提交的填写内容');
  });

  test('记录第一轮：POST 创建草稿，明细带本轮 executed_at；成功后轮次还原并重建空表', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({templateEntries: [{template_id: 5}]}));
    const instance = await renderWorksheet();
    await act(async () => {
      instance.setRow(instance.state.rows[0].client_key, {value_text: '正常'});
      instance.setRow(instance.state.rows[1].client_key, {value_text: '52V'});
    });
    const roundTime = instance.state.roundTime;
    mockHttpPost.mockClear();
    mockHttpPost.mockImplementation((url) => {
      if (url.endsWith('/ledgers/preview/')) return Promise.resolve({data: PREVIEW_DATA});
      if (url.endsWith('/ledgers/')) {
        return Promise.resolve(makeDetail([{time: '09:15', values: {11: '正常', 12: '52V'}}]));
      }
      return Promise.resolve({});
    });
    await act(async () => {
      instance.handleRecord();
    });
    await flush();
    // 首轮：POST 创建（而非 PUT）
    expect(mockHttpPut).not.toHaveBeenCalled();
    const createCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/'));
    expect(createCalls).toHaveLength(1);
    const [url, payload] = createCalls[0];
    expect(url).toBe('/api/equipment-lifecycle/ledgers/');
    expect(payload.ledger_type).toBe('inspection');
    expect(payload.maintenance_cycle).toBe('');
    expect(payload.created_from).toBe('template');
    expect(payload.executed_date).toBe(TODAY);
    expect(payload.executor_names).toBe('张三');
    expect(payload.client_token).toBeTruthy();
    // 每个系统一条 entry，明细携带本轮 executed_at，不携带结果类字段
    expect(payload.entries).toHaveLength(2);
    payload.entries.forEach(e => {
      expect(typeof e.system_id).toBe('number');
      expect(e.template_id).toBe(5);
      e.items.forEach(it => {
        expect(it.id).toBeUndefined();
        expect(it.executed_at).toBe(`${TODAY} ${roundTime}`);
        expect(it.result).toBeUndefined();
        expect(it.abnormal_desc).toBeUndefined();
        expect(it.onsite_action).toBeUndefined();
      });
    });
    // 成功后：当日草稿台账状态建立、轮次以服务器为准、当前轮重建为空表
    expect(instance.state.ledgerId).toBe(90);
    expect(instance.state.ledgerNo).toBe('EL-INS-20260923-0001');
    expect(instance.state.ledgerVersion).toBe(1);
    expect(instance.state.rounds).toHaveLength(1);
    expect(instance.state.rounds[0].time).toBe('09:15');
    expect(instance.state.rows).toHaveLength(2);
    expect(instance.state.rows.every(r => !r.value_text)).toBe(true);
    expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull();
    const last = JSON.parse(window.localStorage.getItem(LAST_KEY));
    expect(last.templateEntries).toEqual([{template_id: 5}]);
  });

  test('记录第二轮：PUT 追加（已有明细带 id 仅报填写值，新明细带 executed_at，含 version）', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({templateEntries: [{template_id: 5}]}));
    const instance = await renderWorksheet();
    // 第一轮
    await act(async () => {
      instance.setRow(instance.state.rows[0].client_key, {value_text: '正常'});
      instance.setRow(instance.state.rows[1].client_key, {value_text: '52V'});
    });
    mockHttpPost.mockImplementation((url) => {
      if (url.endsWith('/ledgers/preview/')) return Promise.resolve({data: PREVIEW_DATA});
      if (url.endsWith('/ledgers/')) {
        return Promise.resolve(makeDetail([{time: '09:15', values: {11: '正常', 12: '52V'}}]));
      }
      return Promise.resolve({});
    });
    await act(async () => {
      instance.handleRecord();
    });
    await flush();
    // 第二轮（重建后的新行）
    await act(async () => {
      instance.setRow(instance.state.rows[0].client_key, {value_text: '正常'});
      instance.setRow(instance.state.rows[1].client_key, {value_text: '53V'});
    });
    const roundTime2 = instance.state.roundTime;
    mockHttpPut.mockImplementation(() => Promise.resolve(makeDetail([
      {time: '09:15', values: {11: '正常', 12: '52V'}},
      {time: '11:30', values: {11: '正常', 12: '53V'}},
    ])));
    await act(async () => {
      instance.handleRecord();
    });
    await flush();
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/ledgers/90/');
    expect(payload.version).toBe(1);
    // 已有明细：带 id 仅报填写值（按系统分组保留），不重报模板信息与时刻
    const keepEntries = payload.entries.filter(e => e.items.some(it => it.id));
    expect(keepEntries.map(e => e.system_id).sort()).toEqual([11, 12]);
    keepEntries.forEach(e => e.items.forEach(it => {
      expect(it.id).toBeDefined();
      expect(it.executed_at).toBeUndefined();
      expect(it.template_item_id).toBeUndefined();
    }));
    // 新增明细：不带 id，带本轮 executed_at
    const freshEntries = payload.entries.filter(e => e.items.every(it => !it.id));
    expect(freshEntries.map(e => e.system_id).sort()).toEqual([11, 12]);
    freshEntries.forEach(e => {
      expect(e.template_id).toBe(5);
      e.items.forEach(it => {
        expect(it.executed_at).toBe(`${TODAY} ${roundTime2}`);
      });
    });
    // 成功后：轮次为 2 次、版本推进
    expect(instance.state.rounds).toHaveLength(2);
    expect(instance.state.rounds.map(r => r.time)).toEqual(['09:15', '11:30']);
    expect(instance.state.ledgerVersion).toBe(2);
  });

  test('提交台账：POST submit 转待复核，成功后清空当日台账状态并重建空表', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({templateEntries: [{template_id: 5}]}));
    const instance = await renderWorksheet();
    await act(async () => {
      instance.setRow(instance.state.rows[0].client_key, {value_text: '正常'});
    });
    mockHttpPost.mockImplementation((url) => {
      if (url.endsWith('/ledgers/preview/')) return Promise.resolve({data: PREVIEW_DATA});
      if (url.endsWith('/ledgers/')) {
        return Promise.resolve(makeDetail([{time: '09:15', values: {11: '正常', 12: ''}}]));
      }
      if (url.endsWith('/submit/')) {
        return Promise.resolve(makeDetail([{time: '09:15', values: {11: '正常', 12: ''}}], {status: 'submitted'}));
      }
      return Promise.resolve({});
    });
    await act(async () => {
      instance.handleRecord();
    });
    await flush();
    mockHttpPost.mockClear();
    await act(async () => {
      instance.handleSubmitLedger();
    });
    await flush();
    const submitCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/submit/'));
    expect(submitCalls).toHaveLength(1);
    expect(submitCalls[0][0]).toBe('/api/equipment-lifecycle/ledgers/90/submit/');
    // 成功后：当日台账状态清空、已提交计数 +1、重建空表等待后续
    expect(instance.state.ledgerId).toBeNull();
    expect(instance.state.rounds).toHaveLength(0);
    expect(instance.state.submittedCount).toBe(1);
    expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull();
    const previewCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/preview/'));
    expect(previewCalls).toHaveLength(1);
  });

  test('当日已有草稿台账：挂载还原已记录轮次网格（列头=时刻）并重建当前轮', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({templateEntries: [{template_id: 5}]}));
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) return Promise.resolve({data: SYSTEMS, total: 2});
      if (url.includes('/ledger-templates/available/')) return Promise.resolve({data: TEMPLATES});
      if (/\/ledgers\/\d+\/$/.test(url)) {
        return Promise.resolve(makeDetail([
          {time: '08:35', values: {11: '正常', 12: '52V'}},
          {time: '12:40', values: {11: '正常', 12: '53V'}},
        ]));
      }
      if (/\/ledgers\/$/.test(url)) {
        return todayListMock([{id: 90, ledger_no: 'EL-INS-20260923-0001', status: 'draft'}]);
      }
      return Promise.resolve({data: []});
    });
    const instance = await renderWorksheet();
    // 轮次还原：时刻升序、台账状态建立
    expect(instance.state.rounds.map(r => r.time)).toEqual(['08:35', '12:40']);
    expect(instance.state.ledgerId).toBe(90);
    expect(instance.state.header.executed_date).toBe(TODAY);
    expect(instance.state.header.executor_names).toBe('张三');
    // 只读网格渲染：列头时刻 + 网格取值
    expect(container.textContent).toContain('已记录的检查（2 次）');
    expect(container.textContent).toContain('08:35');
    expect(container.textContent).toContain('12:40');
    // 当前轮从上次模板组合重建
    const previewCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/preview/'));
    expect(previewCalls).toHaveLength(1);
    expect(instance.state.rows).toHaveLength(2);
  });

  test('当日草稿 + 本地暂存并存：轮次与当前轮同时恢复', async () => {
    const savedRows = [makeRow({
      system_id: 11, template_id: 5, template_item_id: 211,
      item_name: '电源电压', input_type: 'text', value_text: '51V',
    })];
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify({
      templateEntries: [{template_id: 5}],
      rows: savedRows,
      header: {executed_date: TODAY, executor_names: '张三'},
      round_time: '07:50',
      client_token: 'ws_saved_2',
      saved_at: Date.now(),
    }));
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) return Promise.resolve({data: SYSTEMS, total: 2});
      if (url.includes('/ledger-templates/available/')) return Promise.resolve({data: TEMPLATES});
      if (/\/ledgers\/\d+\/$/.test(url)) {
        return Promise.resolve(makeDetail([{time: '08:35', values: {11: '正常', 12: '52V'}}]));
      }
      if (/\/ledgers\/$/.test(url)) {
        return todayListMock([{id: 90, ledger_no: 'EL-INS-20260923-0001', status: 'draft'}]);
      }
      return Promise.resolve({data: []});
    });
    const instance = await renderWorksheet();
    expect(instance.state.restored).toBe(true);
    expect(instance.state.ledgerId).toBe(90);
    expect(instance.state.rounds).toHaveLength(1);
    expect(instance.state.rows).toHaveLength(1);
    expect(instance.state.rows[0].value_text).toBe('51V');
    expect(instance.state.roundTime).toBe('07:50');
    expect(instance.state.clientToken).toBe('ws_saved_2');
    expect(container.textContent).toContain('已恢复上次未提交的填写内容');
    // 无需预览：当前轮来自本地暂存
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  test('本地暂存日期与当日草稿不一致（跨日残留）：弃用本地暂存', async () => {
    const savedRows = [makeRow({
      system_id: 11, template_id: 5, template_item_id: 211,
      item_name: '电源电压', input_type: 'text', value_text: '51V',
    })];
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify({
      templateEntries: [{template_id: 5}],
      rows: savedRows,
      header: {executed_date: '2026-09-20', executor_names: '张三'},
      round_time: '07:50',
      client_token: 'ws_saved_3',
      saved_at: Date.now(),
    }));
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) return Promise.resolve({data: SYSTEMS, total: 2});
      if (url.includes('/ledger-templates/available/')) return Promise.resolve({data: TEMPLATES});
      if (/\/ledgers\/\d+\/$/.test(url)) {
        return Promise.resolve(makeDetail([{time: '08:35', values: {11: '正常', 12: '52V'}}]));
      }
      if (/\/ledgers\/$/.test(url)) {
        return todayListMock([{id: 90, ledger_no: 'EL-INS-20260923-0001', status: 'draft'}]);
      }
      return Promise.resolve({data: []});
    });
    const instance = await renderWorksheet();
    expect(instance.state.restored).toBe(false);
    // 无上次模板种子：本地暂存弃用后回到空表引导，且暂存已清除
    expect(instance.state.rows).toHaveLength(0);
    expect(instance.state.adjustVisible).toBe(true);
    expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  test('当日已有已提交台账：顶部提示，记录将另起新账', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({templateEntries: [{template_id: 5}]}));
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) return Promise.resolve({data: SYSTEMS, total: 2});
      if (url.includes('/ledger-templates/available/')) return Promise.resolve({data: TEMPLATES});
      if (/\/ledgers\/$/.test(url)) {
        return todayListMock([{id: 80, ledger_no: 'EL-INS-20260923-0001', status: 'submitted'}]);
      }
      return Promise.resolve({data: []});
    });
    const instance = await renderWorksheet();
    expect(instance.state.submittedCount).toBe(1);
    expect(container.textContent).toContain('今日已有 1 张已提交/复核的巡检台账');
  });

  test('无草稿时改执行日期即补录，不弹确认', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({templateEntries: [{template_id: 5}]}));
    const instance = await renderWorksheet();
    await act(async () => {
      instance.setHeader('executed_date', '2026-09-20');
    });
    expect(instance.state.header.executed_date).toBe('2026-09-20');
    expect(document.querySelector('.ant-modal-confirm')).toBeFalsy();
  });

  test('已有草稿时改执行日期：确认后另起一张（原草稿保留）', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({templateEntries: [{template_id: 5}]}));
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) return Promise.resolve({data: SYSTEMS, total: 2});
      if (url.includes('/ledger-templates/available/')) return Promise.resolve({data: TEMPLATES});
      if (/\/ledgers\/\d+\/$/.test(url)) {
        return Promise.resolve(makeDetail([{time: '08:35', values: {11: '正常', 12: '52V'}}]));
      }
      if (/\/ledgers\/$/.test(url)) {
        return todayListMock([{id: 90, ledger_no: 'EL-INS-20260923-0001', status: 'draft'}]);
      }
      return Promise.resolve({data: []});
    });
    const instance = await renderWorksheet();
    expect(instance.state.ledgerId).toBe(90);
    await act(async () => {
      instance.setHeader('executed_date', '2026-09-22');
    });
    await act(async () => {
      await flush();
    });
    // 确认前：日期不变、弹出确认框
    expect(instance.state.header.executed_date).toBe(TODAY);
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    expect(confirm.textContent).toContain('另起一张台账');
    const buttons = confirm.querySelectorAll('.ant-modal-confirm-btns button');
    await act(async () => {
      buttons[buttons.length - 1].click();
    });
    await act(async () => {});
    // 确认后：另起新账（ledger 状态清空），日期生效
    expect(instance.state.ledgerId).toBeNull();
    expect(instance.state.rounds).toHaveLength(0);
    expect(instance.state.header.executed_date).toBe('2026-09-22');
  });

  test('单选行填"不正常"：面板显示异常角标，记录不拦截', async () => {
    window.localStorage.setItem(LAST_KEY, JSON.stringify({
      templateEntries: [{template_id: 5}],
    }));
    const instance = await renderWorksheet();
    await act(async () => {
      instance.setRow(instance.state.rows[0].client_key, {value_text: '不正常'});
    });
    expect(container.textContent).toContain('异常 1');
    mockHttpPost.mockClear();
    mockHttpPost.mockImplementation((url) => {
      if (url.endsWith('/ledgers/preview/')) return Promise.resolve({data: PREVIEW_DATA});
      if (url.endsWith('/ledgers/')) {
        return Promise.resolve(makeDetail([{time: '09:15', values: {11: '不正常', 12: ''}}]));
      }
      return Promise.resolve({});
    });
    await act(async () => {
      instance.handleRecord();
    });
    await flush();
    const createCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/'));
    expect(createCalls).toHaveLength(1);
    createCalls[0][1].entries.forEach(e => {
      e.items.forEach(it => expect(it.result).toBeUndefined());
    });
    expect(instance.state.rounds[0].rows.some(r => r.result === 'abnormal')).toBe(true);
  });
});
