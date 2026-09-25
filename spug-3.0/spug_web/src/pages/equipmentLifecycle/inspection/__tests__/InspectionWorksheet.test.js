/**
 * 今日巡检工作台（合并矩阵表改造）测试。
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 页面只渲染一张四轮巡检矩阵表（检查项目 | 检查内容 | 当日 11:00/16:00/22:00、次日 06:30），
 *   不再分"填写表格/记录回显表格"两套渲染；
 * - 每个轮次列表头吸顶展示：轮次名称 + 状态（未记录/已记录 + 有草稿）+ 该轮次
 *   专属"一键正常/记录本轮"按钮；页面无顶部轮次选择区（Radio）；
 * - 四个轮次彼此独立：未记录轮次整列可编辑、可按任意顺序记录；已记录轮次只读
 *   展示保存值且按钮隐藏（底色浅蓝）；有草稿的未记录列浅黄 + 表头"有草稿"提示；
 * - "记录本轮"只提交对应轮次；成功后该轮次变只读并清理该轮次草稿；
 *   请求期间按钮 loading、其余记录按钮禁用（防重复提交）；失败后仍可编辑；
 * - "一键正常"只填充对应轮次尚未填写的选择型检查项，不覆盖已填内容（含异常）；
 * - 未恢复草稿时自动选中上一次使用的模板（最近一张巡检单的模板，已停用不选）；
 * - 值班人员仅手输姓名回车添加（下拉不打开，历史草稿账号值仍映射姓名回显）；
 * - 不显示实际填写时间与迟填标记；页面无系统选择器；
 * - 已提交后异常记录仍展示（结果 + 现场处理），但不再出现"转故障""转工单"
 *   按钮与转换弹窗（转单功能已下线）；历史"已转故障/已转工单"处置状态
 *   以标签只读展示。
 *
 * 注意：store 为模块级单例，每个用例渲染前必须 resetDetail；
 * 有 seed 的用例走 localStorage 恢复 → loadSheet 流程，无 seed 的用例直接预置 store。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

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
  sessionStorage.setItem('nickname', 'admin');
  localStorage.clear();
  // 拦截 antd message（Portal 渲染跨用例残留且单例被清理后不再渲染，改为直接断言调用）
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'info').mockImplementation(() => {});
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  // 清理 antd Portal（message / modal）在 body 上的残留，避免跨用例文本污染
  document.querySelectorAll('.ant-modal-root').forEach(el => el.remove());
  jest.restoreAllMocks();
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  localStorage.clear();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const TEMPLATE_TREE = {
  id: 7, name: '机房巡检模板', description: '', is_active: true,
  devices: [
    {id: 11, device_name: '1号收发信机', display_order: 0, is_active: true, items: [
      {id: 21, name: '面板指示灯', input_type: 'choice',
        choices: ['正常', '不正常'], is_required: true, display_order: 0},
      {id: 22, name: '输出功率读数', input_type: 'text',
        choices: '', is_required: true, display_order: 1},
    ]},
    {id: 12, device_name: '2号天馈系统', display_order: 1, is_active: true, items: [
      {id: 23, name: '驻波比检查', input_type: 'choice',
        choices: ['正常', '不正常'], is_required: true, display_order: 0},
    ]},
  ],
};

const USERS = [
  {id: 2, username: 'operator', nickname: '值班员乙'},
  {id: 3, username: 'admin', nickname: '值班员甲'},
];

function record(round, itemId, valueText, extra = {}) {
  return {
    id: 100 + itemId, sheet: 5, round_no: round,
    round_text: {r1: '当日 11:00', r2: '当日 16:00', r3: '当日 22:00', r4: '次日 06:30'}[round],
    template_item: itemId, is_temporary: false, client_key: '',
    device_name: '1号收发信机',
    item_name: {21: '面板指示灯', 22: '输出功率读数', 23: '驻波比检查'}[itemId],
    input_type: itemId === 22 ? 'text' : 'choice',
    choices: itemId === 22 ? [] : ['正常', '不正常'],
    is_required: true, display_order: 0,
    value_text: valueText, value_number: null, result: 'normal',
    abnormal_desc: '', onsite_action: '', ...extra,
  };
}

function draftSheetDetail(overrides = {}) {
  return {
    id: 5, sheet_no: 'XJ20260924-0001', duty_date: '2026-09-24',
    template: 7, template_name: '机房巡检模板', status: 'draft',
    status_text: '草稿', version: 1, abnormal_count: 0,
    recorded_rounds: [],
    persons: [{id: 1, user: null, user_name: '', person_name: '值班员甲'}],
    records: [],
    ...overrides,
  };
}

function seedDraft(valuesByRound) {
  // 新格式：values 按轮次分组（组件持久化格式）
  localStorage.setItem('el_insp_ws_admin', JSON.stringify({
    duty_date: '2026-09-24',
    template_id: 7,
    persons: ['3'],
    values: valuesByRound,
    saved_at: Date.now(),
  }));
}

function seedLegacyDraft(flatValues, round) {
  // 旧格式：values 为轮次内条目映射 + 顶层 round 字段
  localStorage.setItem('el_insp_ws_admin', JSON.stringify({
    duty_date: '2026-09-24',
    template_id: 7,
    persons: ['3'],
    round: round || 'r1',
    values: flatValues,
    saved_at: Date.now(),
  }));
}

function seedTemplateOnly() {
  // 仅借暂存恢复预选模板/值班日（loadSheet 需走 mockDraftFlow）；
  // r1 已记录时种子值会被组件自动清理，不影响轮次断言
  seedDraft({r1: {t_22: {value_text: '100'}}});
}

function mockAvailableOnly() {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/inspection-templates/available/')) {
      return Promise.resolve({data: [TEMPLATE_TREE]});
    }
    if (url.includes('/candidate-users/')) {
      return Promise.resolve({data: USERS});
    }
    return Promise.resolve({data: {}});
  });
}

function mockDraftFlow(detail) {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/inspection-templates/available/')) {
      return Promise.resolve({data: [TEMPLATE_TREE]});
    }
    if (url.includes('/candidate-users/')) {
      return Promise.resolve({data: USERS});
    }
    // 单对象响应：libs/http 拦截器直接 resolve 载荷本体（无 data 包装）
    if (/\/inspection-sheets\/\d+\/$/.test(url)) {
      return Promise.resolve(detail);
    }
    if (url.includes('/inspection-sheets/')) {
      return Promise.resolve({data: [{id: detail.id, status: detail.status}], total: 1});
    }
    return Promise.resolve({data: {}});
  });
}

function bodyText() {
  // 组件内 <style> 在 jsdom 中会计入 textContent，剔除后取全文
  const clone = document.body.cloneNode(true);
  clone.querySelectorAll('style').forEach(s => s.remove());
  return clone.textContent.replace(/\s+/g, '');
}

function headerTexts() {
  return Array.from(container.querySelectorAll('table.el-ins-recap-table th'))
    .map(th => th.textContent.trim());
}

function headButton(name) {
  // 卡片头（extra 区）的单据级按钮，如 作废
  return Array.from(container.querySelectorAll('.ant-card-head button'))
    .find(b => b.textContent.replace(/\s+/g, '') === name);
}

function roundTh(round) {
  return container.querySelector(`table.el-ins-recap-table th[data-round="${round}"]`);
}

function roundRoundName(round) {
  return roundTh(round).querySelector('.el-ins-round-name').textContent.trim();
}

function roundStatus(round) {
  return roundTh(round).querySelector('.el-ins-round-status').textContent.trim();
}

function roundButton(round, name) {
  return Array.from(roundTh(round).querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === name);
}

function roundCells(round) {
  return Array.from(container.querySelectorAll(
    `table.el-ins-recap-table td[data-round="${round}"]`));
}

function editableInputs(round) {
  return roundCells(round).filter(td => td.querySelector('input, .ant-select'));
}

function fillInput(inputEl, text) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(inputEl, text);
  inputEl.dispatchEvent(new Event('input', {bubbles: true}));
}

async function renderWorksheet(detail) {
  const InspectionWorksheet = require('../InspectionWorksheet').default;
  const store = require('../store').default;
  // store 为单例：渲染前重置；无 seed 用例直接预置 detail（不经 loadSheet）
  store.resetDetail();
  if (detail) {
    store.templates = [TEMPLATE_TREE];
    store.users = USERS;
    store.detail = detail;
  }
  // 挂载时组件固定请求模板树与账号列表：未配置 mock 时给默认实现
  if (!mockHttpGet.getMockImplementation()) {
    mockAvailableOnly();
  }
  await act(async () => {
    ReactDOM.render(<InspectionWorksheet/>, container);
  });
  await act(flush);
  await act(flush);
}

describe('今日巡检工作台 · 单张四轮矩阵表', () => {
  it('页面只渲染一张巡检矩阵表，四个轮次表头吸顶展示 名称/状态/操作按钮', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet(draftSheetDetail());
    expect(container.querySelectorAll('table').length).toBe(1);
    const headers = headerTexts();
    expect(headers[0]).toBe('检查项目');
    expect(headers[1]).toBe('检查内容');
    // 四个轮次表头：名称 + 状态 + 每轮次独立的 一键正常/记录本轮
    const roundLabels = ['r1', 'r2', 'r3', 'r4'].map(roundRoundName);
    expect(roundLabels).toEqual(['当日 11:00', '当日 16:00', '当日 22:00', '次日 06:30']);
    for (const r of ['r1', 'r2', 'r3', 'r4']) {
      expect(roundStatus(r)).toContain('未记录');
      expect(roundButton(r, '一键正常')).not.toBeUndefined();
      expect(roundButton(r, '记录本轮')).not.toBeUndefined();
    }
    // 不再有顶部轮次选择区（Radio），也不再有旧填写表/回显表两套表头
    expect(container.querySelectorAll('input[type=radio]').length).toBe(0);
    expect(headers).not.toContain('本轮填写值');
    expect(headers).not.toContain('现场处理');
    // 表头吸顶（滚动时轮次名称/状态/按钮仍可见）
    const th = roundTh('r1');
    expect(getComputedStyle(th).position).toBe('sticky');
  });

  it('同一设备名称连续行合并单元格，检查内容逐行显示', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet(draftSheetDetail());
    const merged = container.querySelector('td[rowspan="2"]');
    expect(merged).not.toBeNull();
    expect(merged.textContent).toBe('1号收发信机');
    const text = bodyText();
    expect(text).toContain('面板指示灯');
    expect(text).toContain('输出功率读数');
    expect(text).toContain('驻波比检查');
  });

  it('已有记录回显到对应轮次列，未记录轮次可编辑，已记录轮次整列浅蓝只读', async () => {
    const detailRecords = draftSheetDetail({
      recorded_rounds: ['r1', 'r2'],
      records: [
        record('r1', 21, '正常'),
        record('r2', 22, '450'),
      ],
    });
    seedTemplateOnly();
    mockDraftFlow(detailRecords);
    await renderWorksheet(detailRecords);
    const text = bodyText();
    expect(text).toContain('450');
    expect(text).toContain('XJ20260924-0001');
    // r1/r2 已记录：整列只读无控件；r3/r4 未记录：整列可编辑
    expect(roundCells('r1').length).toBe(3);
    expect(roundCells('r1').filter(
      td => td.querySelector('input, .ant-select')).length).toBe(0);
    expect(roundCells('r2').filter(
      td => td.querySelector('input, .ant-select')).length).toBe(0);
    expect(roundCells('r3').filter(
      td => td.querySelector('input, .ant-select')).length).toBe(3);
    // 已记录轮次表头：状态"已记录"，无操作按钮
    expect(roundStatus('r1')).toBe('已记录');
    expect(roundStatus('r2')).toBe('已记录');
    expect(roundButton('r1', '记录本轮')).toBeUndefined();
    expect(roundButton('r1', '一键正常')).toBeUndefined();
    // 草稿单中已记录轮次整列浅蓝
    expect(container.querySelectorAll('.el-ins-cell-recorded').length).toBe(6);
    // 已记录值在对应单元格回显
    expect(roundCells('r2')[1].textContent).toContain('450');
  });

  it('未记录轮次全部可编辑（四轮彼此独立、可按任意顺序填写）', async () => {
    seedTemplateOnly();
    const detail = draftSheetDetail({
      recorded_rounds: ['r1'],
      records: [record('r1', 21, '正常')],
    });
    mockDraftFlow(detail);
    await renderWorksheet(detail);
    // r1 已记录只读；r2/r3/r4 三个未记录轮次整列可编辑（每列 3 项）
    expect(roundCells('r1').filter(
      td => td.querySelector('input, .ant-select')).length).toBe(0);
    expect(container.querySelectorAll('.el-ins-cell-editable').length).toBe(9);
    // 每个可编辑列：两个选择项下拉 + 一个数值输入框
    for (const r of ['r2', 'r3', 'r4']) {
      const selects = roundCells(r).filter(td => td.querySelector('.ant-select'));
      expect(selects.length).toBe(2);
      const textInputs = roundCells(r).filter(
        td => Array.from(td.querySelectorAll('input'))
          .some(i => (i.placeholder || '').startsWith('请输入')));
      expect(textInputs.length).toBe(1);
    }
  });

  it('不显示实际填写时间与迟填/逾期标记，页面无系统选择器', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet(draftSheetDetail());
    const text = bodyText();
    expect(text).not.toContain('迟填');
    expect(text).not.toContain('逾期');
    expect(text).not.toContain('填写时间');
    const urls = mockHttpGet.mock.calls.map(call => call[0]);
    expect(urls.some(u => u.includes('candidate-systems'))).toBe(false);
  });

  it('当日已有单时直接加载，不显示"开始巡检"', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet(draftSheetDetail());
    expect(bodyText()).toContain('XJ20260924-0001');
    expect(bodyText()).not.toContain('开始巡检');
  });
});

describe('今日巡检工作台 · 模板自动选择与值班人员录入', () => {
  function mockSheetListSheets() {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/inspection-templates/available/')) {
        return Promise.resolve({data: [TEMPLATE_TREE]});
      }
      if (url.includes('/candidate-users/')) {
        return Promise.resolve({data: USERS});
      }
      if (/\/inspection-sheets\/\d+\/$/.test(url)) {
        return Promise.resolve(draftSheetDetail());
      }
      if (url.includes('/inspection-sheets/')) {
        return Promise.resolve({data: [
          {id: 9, sheet_no: 'XJ20260923-0003', duty_date: '2026-09-23',
           template: 7, template_name: '机房巡检模板', status: 'submitted'},
        ], total: 1});
      }
      return Promise.resolve({data: {}});
    });
  }

  it('未恢复草稿时自动选中上一次使用的模板并加载对应巡检单', async () => {
    mockSheetListSheets();
    await renderWorksheet();
    for (let i = 0; i < 3; i++) {await act(flush);}
    // 模板下拉已自动显示上一次使用的模板
    const tplSelect = container.querySelectorAll('.ant-card .ant-select')[0];
    expect(tplSelect.textContent).toContain('机房巡检模板');
    // 用该模板发起今日巡检单查询（查询参数在 http.get 第二入参），并加载到最近单据详情
    const listCalls = mockHttpGet.mock.calls.filter(
      ([u]) => u.includes('/inspection-sheets/') &&
        !/\/inspection-sheets\/\d+\/$/.test(u));
    expect(listCalls.some(
      ([, cfg]) => cfg && cfg.params && cfg.params.template === 7)).toBe(true);
    expect(bodyText()).toContain('XJ20260924-0001');
  });

  it('上一次使用的模板已不在可用列表中时不自动选择', async () => {
    mockSheetListSheets();
    const originImpl = mockHttpGet.getMockImplementation();
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/inspection-sheets/') &&
          !/\/inspection-sheets\/\d+\/$/.test(url) &&
          !url.includes('candidate')) {
        return Promise.resolve({data: [
          {id: 9, sheet_no: 'XJ20260923-0003', duty_date: '2026-09-23',
           template: 88, template_name: '已停用模板', status: 'submitted'},
        ], total: 1});
      }
      return originImpl(url);
    });
    await renderWorksheet();
    for (let i = 0; i < 3; i++) {await act(flush);}
    expect(bodyText()).toContain('请选择巡检模板开始今日巡检');
  });

  it('值班人员仅手输姓名回车添加，账号下拉不再打开', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftSheetDetail());
    mockHttpPut.mockResolvedValue(draftSheetDetail({version: 2}));
    await renderWorksheet(draftSheetDetail());
    const headerSelects = container.querySelectorAll('.ant-card .ant-select');
    // HeaderCard 两个下拉：0=巡检模板、1=值班人员
    const personsSelect = headerSelects[1];
    // 历史草稿中的账号值仍按 options 映射回显姓名
    expect(personsSelect.textContent).toContain('值班员甲');
    // 点击选择器不再出现可见下拉面板（无法选择账号）
    await act(async () => {
      personsSelect.dispatchEvent(
        new MouseEvent('mousedown', {bubbles: true}));
    });
    await act(flush);
    expect(document.querySelector(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden)')).toBeNull();
    // 手输姓名回车 → 触发人员保存，姓名不绑定账号
    // （输入与回车分两次 act：模拟真实输入节奏，同 act 内提交不触发）
    const input = personsSelect.querySelector('input');
    await act(async () => {fillInput(input, '李四');});
    await act(flush);
    await act(async () => {
      const ev = new KeyboardEvent('keydown', {key: 'Enter', bubbles: true});
      Object.defineProperty(ev, 'keyCode', {get: () => 13});
      Object.defineProperty(ev, 'which', {get: () => 13});
      input.dispatchEvent(ev);
    });
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalled();
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toContain('/inspection-sheets/5/');
    expect(payload.persons).toEqual([
      {user: 3, person_name: '值班员甲'},
      {user: null, person_name: '李四'},
    ]);
  });
});

function draftWithR1Recorded() {
  return draftSheetDetail({
    recorded_rounds: ['r1'],
    records: [record('r1', 21, '正常')],
  });
}

describe('今日巡检工作台 · 记录本轮（按轮次提交）', () => {

  it('点击某轮次表头"记录本轮"只提交对应轮次（不提交其他轮次）', async () => {
    seedDraft({
      r2: {t_22: {value_text: '450'}},
      r3: {t_22: {value_text: '380'}},
    });
    mockDraftFlow(draftWithR1Recorded());
    mockHttpPut.mockResolvedValue(draftWithR1Recorded());
    await renderWorksheet();
    // r2 轮次：一键正常填两个选择项（草稿已有数值项）
    await act(async () => {roundButton('r2', '一键正常').click();});
    await act(flush);
    // 只点 r2 的"记录本轮"，不触碰 r3
    await act(async () => {roundButton('r2', '记录本轮').click();});
    await act(flush);
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toContain('/inspection-sheets/5/');
    expect(payload.version).toBe(1);
    expect(payload.persons).toEqual([{user: 3, person_name: '值班员甲'}]);
    // 全部记录 round_no = r2；r3 的草稿内容不在载荷中
    expect(payload.records.map(r => r.round_no)).toEqual(['r2', 'r2', 'r2']);
    expect(payload.records).toEqual([
      {template_item_id: 21, round_no: 'r2', value_text: '正常', onsite_action: ''},
      {template_item_id: 22, round_no: 'r2', value_text: '450', onsite_action: ''},
      {template_item_id: 23, round_no: 'r2', value_text: '正常', onsite_action: ''},
    ]);
  });

  it('可以不按时间顺序记录：先记录 r3 再记录 r2 各自独立成功', async () => {
    seedDraft({
      r3: {t_21: {value_text: '正常'}, t_22: {value_text: '380'},
        t_23: {value_text: '正常'}},
      r2: {t_21: {value_text: '正常'}, t_22: {value_text: '450'},
        t_23: {value_text: '正常'}},
    });
    mockDraftFlow(draftWithR1Recorded());
    await renderWorksheet();
    // 先记录 r3（跳过 r2）
    mockHttpPut.mockResolvedValue(draftSheetDetail({
      recorded_rounds: ['r1', 'r3'],
      records: [record('r1', 21, '正常'), record('r3', 22, '380')],
      version: 2,
    }));
    await act(async () => {roundButton('r3', '记录本轮').click();});
    await act(flush);
    await act(flush);
    expect(message.success).toHaveBeenCalledWith('已记录 当日 22:00 轮次');
    // 再记录 r2（版本号取自详情返回）
    mockHttpPut.mockResolvedValue(draftSheetDetail({
      recorded_rounds: ['r1', 'r2', 'r3'],
      records: [record('r1', 21, '正常'), record('r2', 22, '450'),
        record('r3', 22, '380')],
      version: 3,
    }));
    await act(async () => {roundButton('r2', '记录本轮').click();});
    await act(flush);
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalledTimes(2);
    expect(mockHttpPut.mock.calls[1][1].version).toBe(2);
    expect(mockHttpPut.mock.calls[1][1].records.every(
      r => r.round_no === 'r2')).toBe(true);
    expect(message.success).toHaveBeenCalledWith('已记录 当日 16:00 轮次');
  });

  it('记录成功后该轮次变只读、提示一次，并清理该轮次草稿（其他轮次草稿保留）', async () => {
    seedDraft({
      r2: {t_21: {value_text: '正常'}, t_22: {value_text: '450'},
        t_23: {value_text: '正常'}},
      r3: {t_21: {value_text: '正常'}, t_22: {value_text: '380'},
        t_23: {value_text: '正常'}},
    });
    const after = draftSheetDetail({
      recorded_rounds: ['r1', 'r2'],
      records: [record('r1', 21, '正常'), record('r2', 22, '450')],
      version: 2,
    });
    mockDraftFlow(draftWithR1Recorded());
    mockHttpPut.mockResolvedValue(after);
    await renderWorksheet();
    await act(async () => {roundButton('r2', '记录本轮').click();});
    await act(flush);
    await act(flush);
    expect(message.success).toHaveBeenCalledTimes(1);
    expect(message.success).toHaveBeenCalledWith('已记录 当日 16:00 轮次');
    // r2 已记录：整列只读、按钮隐藏；r3 仍可编辑
    expect(roundCells('r2').filter(
      td => td.querySelector('input, .ant-select')).length).toBe(0);
    expect(roundStatus('r2')).toBe('已记录');
    expect(roundButton('r2', '记录本轮')).toBeUndefined();
    expect(editableInputs('r3').length).toBe(3);
    // r2 草稿已清理，r3 草稿保留
    const savedDraft = JSON.parse(localStorage.getItem('el_insp_ws_admin'));
    expect(savedDraft.values.r2).toBeUndefined();
    expect(savedDraft.values.r3).toEqual({
      t_21: {value_text: '正常'}, t_22: {value_text: '380'},
      t_23: {value_text: '正常'},
    });
  });

  it('必填检查内容未填写时不允许记录本轮', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftWithR1Recorded());
    await renderWorksheet(draftWithR1Recorded());
    await act(async () => {roundButton('r2', '记录本轮').click();});
    await act(flush);
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(message.error).toHaveBeenCalledWith(
      expect.stringContaining('必填内容'));
  });
});

describe('今日巡检工作台 · 记录本轮（加载与失败保护）', () => {

  it('请求期间按钮 loading、其余记录按钮禁用，重复点击不产生重复请求', async () => {
    seedDraft({r1: {t_21: {value_text: '正常'}, t_22: {value_text: '450'},
      t_23: {value_text: '正常'}}});
    let resolvePut;
    mockHttpPut.mockImplementation(
      () => new Promise(res => {resolvePut = res;}));
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet();
    const btn = roundButton('r1', '记录本轮');
    await act(async () => {btn.click();});
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    // 请求在途：按钮 loading，其他轮次记录按钮禁用
    expect(btn.className).toContain('ant-btn-loading');
    expect(roundButton('r2', '记录本轮').disabled).toBe(true);
    expect(roundButton('r4', '记录本轮').disabled).toBe(true);
    // 在途期间重复点击不产生第二个请求
    await act(async () => {btn.click();});
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    // 成功返回后 loading 解除、提示成功
    await act(async () => {resolvePut(draftSheetDetail({
      recorded_rounds: ['r1'], records: [record('r1', 21, '正常')], version: 2,
    }));});
    await act(flush);
    await act(flush);
    expect(message.success).toHaveBeenCalledWith('已记录 当日 11:00 轮次');
    expect(roundTh('r1').querySelector('.ant-btn-loading')).toBeNull();
  });

  it('保存失败时轮次不被锁定：无成功提示，该轮次仍可编辑、草稿保留', async () => {
    seedDraft({r1: {t_21: {value_text: '正常'}, t_22: {value_text: '450'},
      t_23: {value_text: '正常'}}});
    mockDraftFlow(draftSheetDetail());
    // 拒绝原因（如版本冲突）由 libs/http 拦截器统一提示，组件不重复提示
    mockHttpPut.mockRejectedValue('巡检单已被他人修改，请刷新后重试');
    await renderWorksheet();
    await act(async () => {roundButton('r1', '记录本轮').click();});
    await act(flush);
    await act(flush);
    expect(message.success).not.toHaveBeenCalled();
    // 该轮次保持可编辑（输入控件仍在），按钮退出 loading
    expect(editableInputs('r1').length).toBe(3);
    expect(roundTh('r1').querySelector('.ant-btn-loading')).toBeNull();
    expect(roundStatus('r1')).toContain('未记录');
    // 草稿未被清除
    const savedDraft = JSON.parse(localStorage.getItem('el_insp_ws_admin'));
    expect(savedDraft.values.r1.t_22.value_text).toBe('450');
  });
});

describe('今日巡检工作台 · 一键正常与草稿暂存', () => {
  it('一键正常只填充对应轮次列，不影响其他轮次', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet(draftSheetDetail());
    await act(async () => {roundButton('r1', '一键正常').click();});
    await act(flush);
    // r1 的两个选择项填入"正常"
    const r1Selects = roundCells('r1').filter(td => td.querySelector('.ant-select'));
    expect(r1Selects.length).toBe(2);
    r1Selects.forEach(td => expect(
      td.querySelector('.ant-select').textContent).toBe('正常'));
    // r2/r3/r4 列未被填充（仅显示占位符）
    for (const r of ['r2', 'r3', 'r4']) {
      roundCells(r).filter(td => td.querySelector('.ant-select')).forEach(td => {
        expect(td.querySelector('.ant-select').textContent).toBe('正常 / 不正常');
      });
    }
  });

  it('一键正常不覆盖已填写内容（含"不正常"与现场处理），只补未填项', async () => {
    seedDraft({
      r1: {
        t_21: {value_text: '不正常', onsite_action: '已切换备用'},
        t_22: {value_text: '500'},
      },
    });
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet();
    await act(async () => {roundButton('r1', '一键正常').click();});
    await act(flush);
    // 已填的"不正常"+现场处理保持不变
    const selects = roundCells('r1').filter(td => td.querySelector('.ant-select'));
    expect(selects[0].querySelector('.ant-select').textContent).toBe('不正常');
    expect(selects[1].querySelector('.ant-select').textContent).toBe('正常');
    const onsite = Array.from(roundCells('r1')[0].querySelectorAll('input'))
      .find(i => i.placeholder === '现场处理内容');
    expect(onsite.value).toBe('已切换备用');
    // 提示中说明未覆盖已填项
    expect(message.success).toHaveBeenCalledWith(
      expect.stringContaining('保持不变'));
    // 记录本轮：异常值与现场处理随本轮一并提交
    mockHttpPut.mockResolvedValue(draftSheetDetail());
    await act(async () => {roundButton('r1', '记录本轮').click();});
    await act(flush);
    const payload = mockHttpPut.mock.calls[0][1];
    expect(payload.records).toEqual([
      {template_item_id: 21, round_no: 'r1', value_text: '不正常',
       onsite_action: '已切换备用'},
      {template_item_id: 22, round_no: 'r1', value_text: '500', onsite_action: ''},
      {template_item_id: 23, round_no: 'r1', value_text: '正常', onsite_action: ''},
    ]);
  });

  it('未记录轮次草稿按列独立保存，表头同行显示状态与"有草稿"提示（无迟填/逾期）', async () => {
    seedDraft({r1: {t_22: {value_text: '100'}}});
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet();
    // r1 有草稿：状态"未记录"与轮次名同行，"有草稿"可见，整列浅黄
    expect(roundStatus('r1')).toBe('未记录');
    const r1Tag = roundTh('r1').querySelector('.el-ins-round-draft-tag');
    expect(r1Tag).not.toBeNull();
    expect(r1Tag.style.visibility).toBe('visible');
    expect(roundCells('r1').every(
      td => td.className.includes('el-ins-cell-draft'))).toBe(true);
    // 其他轮次无草稿："有草稿"占位隐藏（保持列宽稳定），无浅黄底
    for (const r of ['r2', 'r3', 'r4']) {
      expect(roundStatus(r)).toBe('未记录');
      const tag = roundTh(r).querySelector('.el-ins-round-draft-tag');
      expect(tag).not.toBeNull();
      expect(tag.style.visibility).toBe('hidden');
      expect(roundCells(r).some(
        td => td.className.includes('el-ins-cell-draft'))).toBe(false);
    }
    // 各轮次填写互不影响（草稿按列独立）
    const r2Input = Array.from(roundCells('r2')[1].querySelectorAll('input'))
      .find(i => i.placeholder === '请输入');
    await act(async () => {fillInput(r2Input, '200');});
    await act(flush);
    const r1Input = Array.from(roundCells('r1')[1].querySelectorAll('input'))
      .find(i => i.placeholder === '请输入');
    expect(r1Input.value).toBe('100');
    expect(r2Input.value).toBe('200');
  });

  it('旧格式本地草稿（扁平 values + round）兼容读取不报错', async () => {
    seedLegacyDraft({t_22: {value_text: '300'}}, 'r1');
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet();
    const input = Array.from(roundCells('r1')[1].querySelectorAll('input'))
      .find(i => i.placeholder === '请输入');
    expect(input.value).toBe('300');
  });
});

describe('今日巡检工作台 · 提交后与作废后', () => {
  it('已提交巡检单全部只读，异常记录仍展示但不出现转故障/转工单按钮与转换弹窗', async () => {
    seedTemplateOnly();
    const submittedDetail = draftSheetDetail({
      status: 'submitted', status_text: '已提交',
      recorded_rounds: ['r1'],
      records: [record('r1', 21, '不正常', {
        result: 'abnormal', abnormal_desc: '告警灯红色', onsite_action: '已切换备用',
        disposition: {status: 'none', fault: null, work_order: null},
      })],
    });
    mockDraftFlow(submittedDetail);
    await renderWorksheet(submittedDetail);
    // 只读：无轮次操作按钮、无编辑控件
    expect(container.querySelectorAll(
      '.el-ins-recap-table input, .el-ins-recap-table .ant-select').length).toBe(0);
    for (const r of ['r1', 'r2', 'r3', 'r4']) {
      expect(roundButton(r, '记录本轮')).toBeUndefined();
      expect(roundButton(r, '一键正常')).toBeUndefined();
    }
    expect(container.querySelectorAll('input[type=radio]').length).toBe(0);
    // 已提交单无轮次列底色（异常浅红保留）
    expect(container.querySelectorAll('.el-ins-cell-recorded').length).toBe(0);
    expect(container.querySelectorAll('.el-ins-cell-abnormal').length).toBe(1);
    // 异常记录（结果 + 现场处理）继续展示
    expect(bodyText()).toContain('不正常');
    expect(bodyText()).toContain('（已切换备用）');
    // 不再出现转故障/转工单入口与转换弹窗
    const buttonNames = Array.from(container.querySelectorAll('button'))
      .map(b => b.textContent.replace(/\s+/g, ''));
    expect(buttonNames).not.toContain('转故障');
    expect(buttonNames).not.toContain('转工单');
    expect(document.querySelectorAll('.ant-modal-root').length).toBe(0);
    // 全程未发出转换请求
    const convertCalls = [...mockHttpPost.mock.calls, ...mockHttpGet.mock.calls]
      .filter(call => call[0].includes('convert-to-'));
    expect(convertCalls.length).toBe(0);
  });

  it('历史"已转故障"处置状态以标签只读展示，仍无转单入口', async () => {
    seedTemplateOnly();
    const convertedDetail = draftSheetDetail({
      status: 'submitted', status_text: '已提交',
      recorded_rounds: ['r1'],
      records: [record('r1', 21, '不正常', {
        result: 'abnormal', abnormal_desc: '告警灯红色', onsite_action: '已切换备用',
        disposition: {status: 'converted_fault',
          fault: {id: 9, fault_no: 'GZ20260924-0001', status: 'pending'},
          work_order: null},
      })],
    });
    mockDraftFlow(convertedDetail);
    await renderWorksheet(convertedDetail);
    // 异常内容与历史处置标签只读展示
    expect(bodyText()).toContain('不正常');
    expect(bodyText()).toContain('已转故障');
    // 无任何转单按钮
    const buttonNames = Array.from(container.querySelectorAll('button'))
      .map(b => b.textContent.replace(/\s+/g, ''));
    expect(buttonNames).not.toContain('转故障');
    expect(buttonNames).not.toContain('转工单');
    expect(document.querySelectorAll('.ant-modal-root').length).toBe(0);
  });

  it('已作废巡检单全部只读且无操作按钮', async () => {
    seedTemplateOnly();
    const voidDetail = draftSheetDetail({
      status: 'void', status_text: '已作废',
      recorded_rounds: ['r1'],
      records: [record('r1', 21, '正常')],
    });
    mockDraftFlow(voidDetail);
    await renderWorksheet(voidDetail);
    expect(bodyText()).toContain('已作废');
    expect(container.querySelectorAll(
      '.el-ins-recap-table input, .el-ins-recap-table .ant-select').length).toBe(0);
    expect(container.querySelectorAll('.el-ins-cell-recorded').length).toBe(0);
    expect(roundButton('r1', '记录本轮')).toBeUndefined();
    expect(headButton('作废')).toBeUndefined();
  });

  it('无单时显示"开始巡检"，点击后按 值班日+模板+人员 建单', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/inspection-templates/available/')) {
        return Promise.resolve({data: [TEMPLATE_TREE]});
      }
      if (url.includes('/candidate-users/')) {
        return Promise.resolve({data: USERS});
      }
      if (url.includes('/inspection-sheets/')) {
        return Promise.resolve({data: [], total: 0});
      }
      return Promise.resolve({data: {}});
    });
    seedDraft({r1: {t_21: {value_text: '正常'}}});
    await renderWorksheet();
    expect(bodyText()).not.toContain('XJ20260924-0001');
    const btn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '开始巡检');
    // 单对象响应：POST 建单直接 resolve 详情本体；详情必须立即渲染
    mockHttpPost.mockResolvedValue(draftSheetDetail());
    await act(async () => {btn.click();});
    await act(flush);
    expect(mockHttpPost).toHaveBeenCalled();
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toContain('/inspection-sheets/');
    expect(payload.duty_date).toBe('2026-09-24');
    expect(payload.template_id).toBe(7);
    expect(payload.persons).toEqual([{user: 3, person_name: '值班员甲'}]);
    expect(payload.client_token).toBeTruthy();
    await act(flush);
    expect(bodyText()).toContain('XJ20260924-0001');
    expect(bodyText()).not.toContain('开始巡检');
  });
});

describe('今日巡检工作台 · 已退回整改单', () => {

  function returnedSheetDetail(overrides = {}) {
    // r1 为已记录轮次：三项检查内容均有已存值（原"记录本轮"必填契约）
    return draftSheetDetail({
      status: 'returned', status_text: '已退回',
      recorded_rounds: ['r1', 'r2'],
      records: [
        record('r1', 21, '不正常', {result: 'abnormal', onsite_action: '已切换备用'}),
        record('r1', 22, '500'),
        record('r1', 23, '正常'),
        record('r2', 22, '480'),
      ],
      ...overrides,
    });
  }

  it('已退回单整单可改：状态展示已退回，已记录轮次仍可编辑并回显原值', async () => {
    seedTemplateOnly();
    mockDraftFlow(returnedSheetDetail());
    await renderWorksheet(returnedSheetDetail());
    expect(bodyText()).toContain('已退回');
    // 四个轮次（含已记录的 r1/r2）都有轮次操作按钮：recorded_rounds 不限制整改
    for (const r of ['r1', 'r2', 'r3', 'r4']) {
      expect(roundButton(r, '记录本轮')).not.toBeUndefined();
      expect(roundButton(r, '一键正常')).not.toBeUndefined();
    }
    // 服务端已存记录回显到填写控件（原有填写内容不因退回清空）
    const r1Select = roundCells('r1')[0].querySelector('.ant-select');
    expect(r1Select).not.toBeNull();
    expect(r1Select.textContent).toContain('不正常');
    const r2Input = roundCells('r2')[1].querySelector('input');
    expect(r2Input.value).toBe('480');
    // 单据级操作：重新提交与作废按钮均可见
    expect(headButton('提交巡检单')).not.toBeUndefined();
    expect(headButton('作废')).not.toBeUndefined();
    // 整改提示文案
    expect(bodyText()).toContain('已退回整改');
  });

  it('已退回单可重改已记录轮次：点击 r1 记录本轮正常发送 PUT', async () => {
    seedTemplateOnly();
    mockDraftFlow(returnedSheetDetail());
    mockHttpPut.mockResolvedValue(returnedSheetDetail({
      records: [
        record('r1', 21, '正常'),
        record('r1', 22, '500'),
        record('r1', 23, '正常'),
        record('r2', 22, '480'),
      ],
      version: 6,
    }));
    await renderWorksheet(returnedSheetDetail());
    await act(async () => {roundButton('r1', '记录本轮').click();});
    await act(flush);
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toContain('/inspection-sheets/5/');
    expect(payload.version).toBe(1);
    expect(payload.records.map(r => r.round_no)).toEqual(['r1', 'r1', 'r1']);
    expect(payload.records[0]).toEqual(
      {template_item_id: 21, round_no: 'r1', value_text: '不正常', onsite_action: '已切换备用'});
    expect(message.success).toHaveBeenCalledWith('已记录 当日 11:00 轮次');
  });

  it('已退回单可重新提交：提交按钮 POST submit 端点并清理草稿', async () => {
    mockDraftFlow(returnedSheetDetail());
    mockHttpPost.mockResolvedValue(draftSheetDetail({
      status: 'submitted', status_text: '已提交',
      recorded_rounds: ['r1', 'r2'],
      records: [record('r1', 21, '不正常'), record('r2', 22, '480')],
    }));
    await renderWorksheet(returnedSheetDetail());
    await act(async () => {headButton('提交巡检单').click();});
    await act(flush);
    await act(flush);
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    expect(mockHttpPost.mock.calls[0][0]).toContain('/inspection-sheets/5/submit/');
    expect(message.success).toHaveBeenCalledWith('巡检单已提交');
    // 提交后草稿清空
    expect(localStorage.getItem('el_insp_ws_admin')).toBeNull();
  });
});
