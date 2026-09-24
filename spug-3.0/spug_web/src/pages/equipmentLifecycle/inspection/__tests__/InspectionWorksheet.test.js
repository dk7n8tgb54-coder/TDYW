/**
 * 今日巡检工作台（合并矩阵表改造）测试。
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 页面只渲染一张四轮巡检矩阵表（检查项目 | 检查内容 | 当日 11:00/16:00/22:00、次日 06:30），
 *   不再分"填写表格/记录回显表格"两套渲染；
 * - 同一设备名称连续行合并单元格（rowSpan）；
 * - 轮次三态：当前选择轮次可编辑、已记录轮次只读展示保存值、未记录轮次显示"—"；
 *   底色只跟随当前选择轮次列（未选中列无底色，已提交/已作废单全部无轮次底色）；
 * - 未恢复草稿时自动选中上一次使用的模板（最近一张巡检单的模板，已停用不选）；
 * - 值班人员仅手输姓名回车添加（下拉不打开，历史草稿账号值仍映射姓名回显）；
 * - "记录本轮"只提交当前选择的轮次；成功后当前轮次变只读并清理该轮次草稿；
 * - 一键正常只作用于当前轮次的选择型检查项；
 * - 切换轮次不丢未记录草稿；旧格式（扁平 values + round）本地草稿兼容读取；
 * - 不显示实际填写时间与迟填标记；页面无系统选择器；
 * - 提交后异常记录可转故障/工单，弹窗必须选择系统（未选不提交）。
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
  return Array.from(container.querySelectorAll('.ant-card-head button'))
    .find(b => b.textContent.replace(/\s+/g, '') === name);
}

function switchRound(round) {
  const input = Array.from(container.querySelectorAll('input[type=radio]'))
    .find(i => i.value === round);
  input.click();
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
  it('页面只渲染一张巡检矩阵表，表头为 检查项目/检查内容 + 四个固定轮次', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet(draftSheetDetail());
    expect(container.querySelectorAll('table').length).toBe(1);
    const headers = headerTexts();
    expect(headers).toEqual([
      '检查项目', '检查内容', '当日 11:00', '当日 16:00', '当日 22:00', '次日 06:30',
    ]);
    // 不再有旧填写表/回显表两套表头
    expect(headers).not.toContain('本轮填写值');
    expect(headers).not.toContain('现场处理');
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

  it('已有记录回显到对应轮次列，未记录轮次显示—，已记录单元格只读', async () => {
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
    // 草稿态但当前轮次 r1 已记录：全部单元格无输入控件
    expect(container.querySelectorAll(
      '.el-ins-recap-table input, .el-ins-recap-table .ant-select').length).toBe(0);
    // 底色只跟随当前选择轮次列：默认选中 r1 → 仅 r1 的已记录单元格浅蓝
    expect(container.querySelectorAll('.el-ins-cell-recorded').length).toBe(1);
    // 切到 r2：浅蓝随选择列移动，r1 已记录列不再有底色
    await act(async () => {switchRound('r2');});
    await act(flush);
    expect(container.querySelectorAll('.el-ins-cell-recorded').length).toBe(1);
    const blueRow = container.querySelector('.el-ins-cell-recorded').closest('tr');
    expect(blueRow.textContent).toContain('输出功率读数');
    expect(blueRow.textContent).not.toContain('面板指示灯');
  });

  it('当前选择轮次可编辑，其他轮次不可编辑', async () => {
    seedTemplateOnly();
    const detail = draftSheetDetail({
      recorded_rounds: ['r1'],
      records: [record('r1', 21, '正常')],
    });
    mockDraftFlow(detail);
    await renderWorksheet(detail);
    // r1 已记录：默认轮次无输入控件
    expect(container.querySelectorAll(
      '.el-ins-recap-table input, .el-ins-recap-table .ant-select').length).toBe(0);
    // 切到 r2：三个检查内容均出现控件，且只出现在当前轮次单元格
    await act(async () => {switchRound('r2');});
    await act(flush);
    expect(container.querySelectorAll('.el-ins-cell-current').length).toBe(3);
    // 两个选择项下拉 + 一个数值输入框（antd Select 内部 input 不计）
    expect(container.querySelectorAll(
      '.el-ins-cell-current .ant-select').length).toBe(2);
    const textInputs = Array.from(container.querySelectorAll('.el-ins-cell-current input'))
      .filter(i => (i.placeholder || '').startsWith('请输入'));
    expect(textInputs.length).toBe(1);
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

describe('今日巡检工作台 · 记录本轮', () => {

  it('记录本轮只提交当前选择的轮次（必填校验通过后）', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftWithR1Recorded());
    await renderWorksheet(draftWithR1Recorded());
    mockHttpPut.mockResolvedValue(draftWithR1Recorded());
    await act(async () => {switchRound('r2');});
    await act(flush);
    // 一键正常填两个选择项，再手填数值项
    await act(async () => {headButton('一键正常').click();});
    await act(flush);
    const input = Array.from(container.querySelectorAll('.el-ins-cell-current input'))
      .find(i => i.placeholder === '请输入');
    await act(async () => {fillInput(input, '450');});
    await act(async () => {headButton('记录本轮').click();});
    await act(flush);
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalled();
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toContain('/inspection-sheets/5/');
    expect(payload.version).toBe(1);
    expect(payload.persons).toEqual([{user: 3, person_name: '值班员甲'}]);
    expect(payload.records).toEqual([
      {template_item_id: 21, round_no: 'r2', value_text: '正常', onsite_action: ''},
      {template_item_id: 22, round_no: 'r2', value_text: '450', onsite_action: ''},
      {template_item_id: 23, round_no: 'r2', value_text: '正常', onsite_action: ''},
    ]);
  });

  it('记录成功后当前轮次变只读、提示已记录，并清理该轮次本地草稿', async () => {
    seedDraft({r2: {t_22: {value_text: '450'}}});
    const after = draftSheetDetail({
      recorded_rounds: ['r1', 'r2'],
      records: [record('r1', 21, '正常'), record('r2', 22, '450')],
      version: 2,
    });
    mockDraftFlow(draftWithR1Recorded());
    mockHttpPut.mockResolvedValue(after);
    await renderWorksheet();
    await act(async () => {switchRound('r2');});
    await act(flush);
    await act(async () => {headButton('一键正常').click();});
    await act(flush);
    await act(async () => {headButton('记录本轮').click();});
    await act(flush);
    await act(flush);
    expect(message.success).toHaveBeenCalledWith('已记录 当日 16:00 轮次');
    // r2 已记录：无编辑控件，全部只读
    expect(container.querySelectorAll(
      '.el-ins-recap-table input, .el-ins-recap-table .ant-select').length).toBe(0);
    // 该轮次草稿已清理（无未记录填写内容 → 暂存移除）
    expect(localStorage.getItem('el_insp_ws_admin')).toBeNull();
  });

  it('必填检查内容未填写时不允许记录本轮', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftWithR1Recorded());
    await renderWorksheet(draftWithR1Recorded());
    await act(async () => {switchRound('r2');});
    await act(flush);
    await act(async () => {headButton('记录本轮').click();});
    await act(flush);
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(message.error).toHaveBeenCalledWith(
      expect.stringContaining('必填内容'));
  });

  it('已记录轮次点击记录本轮不发起请求（前端拦截，后端亦有保护）', async () => {
    await renderWorksheet(draftWithR1Recorded());
    // 默认轮次 r1 已记录：记录按钮点击不发请求并给出提示
    await act(async () => {headButton('记录本轮').click();});
    await act(flush);
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(message.warning).toHaveBeenCalledWith(
      expect.stringContaining('已记录'));
  });
});

describe('今日巡检工作台 · 一键正常与草稿暂存', () => {
  it('一键正常只作用于当前轮次的选择型检查项，不覆盖其他轮次', async () => {
    seedTemplateOnly();
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet(draftSheetDetail());
    await act(async () => {headButton('一键正常').click();});
    await act(flush);
    // r1 的两个选择项填入"正常"
    let selects = Array.from(container.querySelectorAll('.el-ins-cell-current .ant-select'));
    expect(selects.length).toBe(2);
    selects.forEach(s => expect(s.textContent).toBe('正常'));
    // 切到 r2：选择项未被填充（仅显示占位符）
    await act(async () => {switchRound('r2');});
    await act(flush);
    selects = Array.from(container.querySelectorAll('.el-ins-cell-current .ant-select'));
    selects.forEach(s => expect(s.textContent).toBe('正常 / 不正常'));
  });

  it('切换轮次时未记录草稿不丢失', async () => {
    seedDraft({r1: {t_22: {value_text: '100'}}});
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet();
    const inputOf = () => Array.from(container.querySelectorAll('.el-ins-cell-current input'))
      .find(i => i.placeholder === '请输入');
    expect(inputOf().value).toBe('100');
    await act(async () => {switchRound('r2');});
    await act(flush);
    // r2 的数值项输入框存在（Select 内部也含 input，按 placeholder 定位）
    const r2input = Array.from(container.querySelectorAll('.el-ins-cell-current input'))
      .find(i => i.placeholder === '请输入');
    expect(r2input).not.toBeUndefined();
    expect(r2input.value).toBe('');
    await act(async () => {switchRound('r1');});
    await act(flush);
    expect(inputOf().value).toBe('100');
  });

  it('旧格式本地草稿（扁平 values + round）兼容读取不报错', async () => {
    seedLegacyDraft({t_22: {value_text: '300'}}, 'r1');
    mockDraftFlow(draftSheetDetail());
    await renderWorksheet();
    const input = Array.from(container.querySelectorAll('.el-ins-cell-current input'))
      .find(i => i.placeholder === '请输入');
    expect(input.value).toBe('300');
  });

  it('不正常单元格内可填写现场处理内容（同轮次单元格内）', async () => {
    seedDraft({
      r1: {
        t_21: {value_text: '不正常'},
        t_22: {value_text: '500'},
        t_23: {value_text: '正常'},
      },
    });
    mockDraftFlow(draftSheetDetail());
    mockHttpPut.mockResolvedValue(draftSheetDetail());
    await renderWorksheet();
    const onsite = Array.from(container.querySelectorAll('.el-ins-cell-current input'))
      .find(i => i.placeholder === '现场处理内容');
    expect(onsite).not.toBeUndefined();
    await act(async () => {fillInput(onsite, '已切换备用');});
    await act(flush);
    await act(async () => {headButton('记录本轮').click();});
    await act(flush);
    const payload = mockHttpPut.mock.calls[0][1];
    expect(payload.records).toEqual([
      {template_item_id: 21, round_no: 'r1', value_text: '不正常',
       onsite_action: '已切换备用'},
      {template_item_id: 22, round_no: 'r1', value_text: '500', onsite_action: ''},
      {template_item_id: 23, round_no: 'r1', value_text: '正常', onsite_action: ''},
    ]);
  });
});

describe('今日巡检工作台 · 提交后与作废后', () => {
  it('已提交巡检单全部只读，异常记录可转故障/工单；弹窗未选系统不提交', async () => {
    seedTemplateOnly();
    const submittedDetail = draftSheetDetail({
      status: 'submitted', status_text: '已提交',
      recorded_rounds: ['r1'],
      records: [record('r1', 21, '不正常', {
        result: 'abnormal',
        disposition: {status: 'none', fault: null, work_order: null},
      })],
    });
    mockDraftFlow(submittedDetail);
    await renderWorksheet(submittedDetail);
    // 只读：无轮次选择与操作按钮、无编辑控件
    expect(container.querySelectorAll(
      '.el-ins-recap-table input, .el-ins-recap-table .ant-select').length).toBe(0);
    expect(headButton('记录本轮')).toBeUndefined();
    expect(container.querySelectorAll('input[type=radio]').length).toBe(0);
    // 已提交单无"当前选择轮次"概念：所有列均无记录底色，异常浅红保留
    expect(container.querySelectorAll('.el-ins-cell-recorded').length).toBe(0);
    expect(container.querySelectorAll('.el-ins-cell-abnormal').length).toBe(1);
    // 异常单元格内转故障入口
    const btn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '转故障');
    await act(async () => {btn.click();});
    await act(flush);
    expect(bodyText()).toContain('故障系统');
    // 无 ConfigProvider 的 jsdom 环境下 antd Modal 默认 footer 为 OK/Cancel
    const ok = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === 'OK');
    await act(async () => {ok.click();});
    await act(flush);
    const convertCalls = mockHttpPost.mock.calls.filter(
      call => call[0].includes('convert-to-fault'));
    expect(convertCalls.length).toBe(0);
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
    expect(headButton('记录本轮')).toBeUndefined();
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
