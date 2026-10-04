/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行记录组件渲染测试（2026-10 第一版）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 列表页渲染运行记录行（编号/系统/标题/状态）与"新增运行记录"入口
 * - 列表请求指向 runtime-records 端点，且不含巡视/维护/升级数据来源
 * - 新增表单第一屏只显示五个必填字段（含登记人，参照故障登记人手输姓名）；
 *   "更多信息"展开可选字段；空表单提交被校验拦截（不发请求）
 * - 编辑模式回填后可提交（PUT 携带修改值，不携带重要程度/登记人键）
 * - 详情窗口展示编号/状态/影响/关联故障入口；动作按钮随状态显隐
 *   （终态无编辑/追加/标记按钮）
 * - 详情基本信息四区块分区（2026-10-04）：运行概况/研判与处置/关联与登记/
 *   处理概览；标题区只保留编号/状态/影响/重要摘要；完整字段各归其区块且
 *   不重复（所属系统/地点/时间→运行概况，研判/跟进→研判与处置，
 *   登记人/时间→关联与登记）；空的跟进安排/重要原因/研判说明不产生空行；
 *   关联故障链接跳转沿用 /el/faults?detail= 实现；处理概览条数/最近更新/
 *   最后记录取自已请求的进展列表（含 total），查看全部进展直达页签
 * - 处理进展时间线展示与更正留痕可见
 * - 关闭弹窗提交 close
 * - 系统详情"运行记录"页签只展示本系统记录
 * - 所有请求只指向 equipment-lifecycle 前缀
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
// 注意：组件渲染测试不使用 jest.resetModules()（会导致 React 多副本触发 Invalid hook call）

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function bodyText() {
  // antd 两字按钮文案渲染为“编 辑”（自动空格），比较前统一去空白
  return document.body.textContent.replace(/\s+/g, '');
}

// 分区不重复断言用：某片段在全文出现次数
function countOccurrences(text, sub) {
  return text.split(sub).length - 1;
}

function setInputValue(element, value) {
  // jsdom 原生 setter（React 受控组件需绕过 value 只读代理）
  const proto = element.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(element, value);
  element.dispatchEvent(new Event('input', {bubbles: true}));
}

function buttonTexts() {
  // 详情窗口（2026-10-02 改 Modal）底部的"关 闭"是外壳按钮，不属于业务动作，
  // 按钮维度断言一律排除弹窗 footer，避免与动作"关闭"同名干扰
  return Array.from(document.querySelectorAll('button'))
    .filter(b => !b.closest('.ant-modal-footer'))
    .map(b => b.textContent.replace(/\s+/g, ''));
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

// Modal 确认按钮：项目未配置 antd 中文 locale，默认渲染为 "OK"（兼容 确定）
function clickModalOk() {
  const ok = Array.from(document.querySelectorAll('.ant-modal button'))
    .find(b => /^ok|确定$/i.test(b.textContent.replace(/\s+/g, '')) && !b.disabled);
  if (!ok) {
    throw new Error('modal ok button not found');
  }
  ok.click();
}

const SYSTEMS = [
  {id: 1, system_code: 'SYS-A1', name: '烟台通信系统', install_location: '机房A'},
  {id: 2, system_code: 'SYS-B1', name: '导航系统B', install_location: '机房B'},
];

const RECORDS_PAGE = {
  data: [
    {
      id: 11, record_no: 'YX20261001-0001', system: 1,
      system_name: '烟台通信系统', system_code: 'SYS-A1', system_location: '机房A',
      occurred_at: '2026-10-01 08:30', title: '主用链路短暂中断',
      status: 'recorded', status_text: '已记录',
      needs_follow_up: false, affects_system_operation: true,
      impact_status: 'interrupted', impact_status_text: '中断',
      importance: 'normal', importance_text: '普通',
      converted_fault: null, converted_fault_no: '',
      created_by_name: 'admin', created_at: '2026-10-01 08:35',
    },
    {
      id: 12, record_no: 'YX20261001-0002', system: 2,
      system_name: '导航系统B', system_code: 'SYS-B1', system_location: '机房B',
      occurred_at: '2026-10-01 09:00', title: '席位显示器闪烁',
      status: 'closed', status_text: '已关闭',
      needs_follow_up: false, affects_system_operation: false,
      impact_status: '', impact_status_text: '',
      importance: 'normal', importance_text: '普通',
      converted_fault: null, converted_fault_no: '',
      created_by_name: 'admin', created_at: '2026-10-01 09:10',
    },
  ],
  total: 2, page: 1, page_size: 20,
};

const RECORD_DETAIL = {
  ...RECORDS_PAGE.data[0],
  description: '值班发现主用链路丢包约 3 分钟后自行恢复',
  registrar_name: '张三',
  measures_taken: '切换备用链路观察',
  handling_result: '',
  importance_reason: '',
  importance_marked_at: null,
  importance_marked_by_name: '',
  converted_fault: 88, converted_fault_no: 'GZ20261001-0007',
  updated_at: null,
};

const PROGRESS_PAGE = {
  data: [
    {id: 1, record: 11, handled_at: '2026-10-01 09:00', handler: 2,
      handler_name: '值班员甲', content: '现场检查，确认交换机告警',
      result: '观察中', work_hours: 0.5,
      corrections: [{old: '现场检查', new: '现场检查，确认交换机告警',
        reason: '补充细节', by: 'admin', at: '2026-10-01 09:10'}],
      created_at: '2026-10-01 09:05'},
  ],
  total: 1, page: 1, page_size: 100,
};

// 已处理且带完整研判/跟进历史：研判与处置区块应只读保留历史数据
const TRIAGED_RESOLVED_DETAIL = {
  ...RECORD_DETAIL,
  status: 'resolved', status_text: '已处理',
  converted_fault: null, converted_fault_no: '',
  triaged_at: '2026-10-02 09:00', triaged_by_name: '李四',
  triage_note: '判断为链路抖动，需持续跟进',
  follow_up_name: '王值班', planned_handle_at: '2026-10-05 09:00',
  handling_result: '链路稳定，连续三天无丢包',
  resolved_at: '2026-10-04 10:00',
};

function mockListApis(detailResponse, progressResponse) {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/candidate-systems')) return Promise.resolve({data: SYSTEMS});
    if (url.includes('/progress/')) {
      return Promise.resolve(progressResponse || PROGRESS_PAGE);
    }
    if (url.includes('/attachments/')) return Promise.resolve({data: []});
    if (url.includes('/systems/') && url.includes('/runtime-records/')) {
      return Promise.resolve({data: RECORDS_PAGE.data, total: 2});
    }
    if (/\/runtime-records\/\d+\/$/.test(url)) {
      return Promise.resolve(detailResponse || RECORD_DETAIL);
    }
    return Promise.resolve(RECORDS_PAGE);
  });
}

async function renderListPage() {
  const RuntimeRecordIndex = require('../index').default;
  mockListApis();
  await act(async () => {
    ReactDOM.render(<RuntimeRecordIndex/>, container);
  });
  await act(async () => {await flush();});
}

async function renderDetail(record, detailResponse, progressResponse) {
  const store = require('../store').default;
  const RecordDetail = require('../RecordDetail').default;
  // 详情请求响应可覆盖：showDetail 传入的对象会被 fetchDetail 响应替换
  mockListApis(detailResponse, progressResponse);
  await act(async () => {
    store.showDetail(record || RECORD_DETAIL);
    ReactDOM.render(<RecordDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

async function openTab(tabText) {
  const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
  const tab = tabs.find(t => t.textContent.includes(tabText));
  await act(async () => {
    tab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

describe('运行记录列表页', () => {
  it('渲染运行记录行：编号/系统/标题/状态与影响，且提供新增入口', async () => {
    await renderListPage();
    const text = bodyText();
    expect(text).toContain('YX20261001-0001');
    expect(text).toContain('YX20261001-0002');
    expect(text).toContain('烟台通信系统');
    expect(text).toContain('主用链路短暂中断');
    expect(text).toContain('已记录');
    expect(text).toContain('已关闭');
    expect(text).toContain('中断');
    expect(text).toContain('不影响运行');
    expect(text).toContain('新增运行记录');
  });

  it('列表请求指向 runtime-records 端点（不混入巡视/维护/升级数据来源）', async () => {
    await renderListPage();
    const urls = mockHttpGet.mock.calls.map(call => call[0]);
    const listCalls = urls.filter(u => u.includes('/runtime-records/'));
    expect(listCalls.length).toBeGreaterThan(0);
    for (const url of urls) {
      expect(url.startsWith('/api/equipment-lifecycle/')).toBe(true);
      // 运行记录页面不请求 巡检/台账/升级 业务列表
      expect(url.includes('/inspection-sheets') || url.includes('/ledgers/')
        || url.includes('/upgrade')).toBe(false);
    }
  });
});

describe('运行记录新增/编辑表单', () => {
  it('第一屏只显示五个必填字段，更多信息展开可选字段', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockListApis();
    await act(async () => {
      store.showForm();
      ReactDOM.render(<RecordForm/>, container);
    });
    await act(async () => {await flush();});
    let text = bodyText();
    ['所属系统', '发生时间', '标题', '情况描述', '登记人'].forEach(label => {
      expect(text).toContain(label);
    });
    // 可选字段（仅在展开后出现；展开按钮文案不含这些标签词）
    expect(text).not.toContain('影响系统运行');
    expect(text).not.toContain('已采取措施');
    expect(text).toContain('需要跟进或更多信息');
    // 展开更多信息
    await act(async () => {
      clickButtonByText('需要跟进或更多信息');
    });
    await act(async () => {await flush();});
    text = bodyText();
    expect(text).toContain('影响系统运行');
    expect(text).toContain('已采取措施');
    expect(text).toContain('处理结果');
    expect(text).toContain('重要程度');
  });

  it('空表单提交被校验拦截，不发起请求', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockListApis();
    await act(async () => {
      store.showForm();
      ReactDOM.render(<RecordForm/>, container);
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(store.formVisible).toBe(true);
  });

  it('编辑模式回填详情后提交 PUT，且不携带重要程度键', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockListApis();
    mockHttpPut.mockResolvedValue({});
    await act(async () => {
      store.showForm({...RECORD_DETAIL, status: 'resolved'});
      ReactDOM.render(<RecordForm/>, container);
    });
    await act(async () => {await flush();});
    // 回填后标题可见且更多信息已展开
    const inputs = Array.from(document.querySelectorAll('.ant-modal input'));
    const titleInput = inputs.find(i => i.value === RECORD_DETAIL.title);
    expect(titleInput).toBeTruthy();
    await act(async () => {
      setInputValue(titleInput, '更新后的标题');
    });
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/11/',
      expect.objectContaining({title: '更新后的标题', system: 1}));
    const payload = mockHttpPut.mock.calls[0][1];
    expect(payload.importance).toBeUndefined();
    expect(payload.importance_reason).toBeUndefined();
    // 登记人仅新增可填：编辑提交不携带该键，后端保留原登记人
    expect(payload.registrar_name).toBeUndefined();
    expect(store.formVisible).toBe(false);
  });
});

describe('运行记录详情窗口', () => {
  it('展示编号/状态/影响信息/关联故障入口与审计信息', async () => {
    await renderDetail();
    const text = bodyText();
    expect(text).toContain('YX20261001-0001');
    expect(text).toContain('已记录');
    // bodyText 去空白：断言用去空格文本
    expect(text).toContain('值班发现主用链路丢包约3分钟后自行恢复');
    expect(text).toContain('切换备用链路观察');
    // 登记人（手输姓名快照）在详情展示
    expect(text).toContain('登记人');
    expect(text).toContain('张三');
    // 已记录状态：编辑 + 研判（一次提交完成结论，无提交研判中转）+ 关闭
    // （留痕记录可直接关闭，不要求先研判，与后端状态机一致）
    const btns = buttonTexts();
    ['编辑', '研判', '关闭'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(true);
    });
    ['提交研判', '标记需要跟进', '标记已处理', '标记重要', '转为故障'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(false);
    });
    // 关联故障入口（已转故障号可见）
    expect(text).toContain('GZ20261001-0007');
  });

  it('已关闭（终态）记录不显示编辑/追加/标记动作', async () => {
    const closedDetail = {...RECORD_DETAIL, status: 'closed', converted_fault: null,
      converted_fault_no: ''};
    await renderDetail(closedDetail, closedDetail);
    const btns = buttonTexts();
    ['编辑', '提交研判', '研判', '标记需要跟进', '标记已处理', '标记重要',
      '转为故障', '关闭', '重新研判'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(false);
    });
  });

  it('处理进展时间线展示内容与更正留痕；已转故障不提供追加入口', async () => {
    await renderDetail({...RECORD_DETAIL, status: 'recorded', converted_fault: null});
    await openTab('处理进展');
    const text = bodyText();
    expect(text).toContain('现场检查，确认交换机告警');
    expect(text).toContain('值班员甲');
    expect(text).toContain('补充细节');
    expect(text).toContain('由admin更正');
    expect(buttonTexts().some(t => t === '追加处理进展')).toBe(true);
    // 已转故障（终态）：无追加与更正按钮
    const convertedDetail = {...RECORD_DETAIL, status: 'converted_fault'};
    await renderDetail(convertedDetail, convertedDetail);
    await openTab('处理进展');
    expect(buttonTexts().some(t => t === '追加处理进展')).toBe(false);
    expect(buttonTexts().some(t => t === '更正')).toBe(false);
  });

  it('顶部不再提供独立的 标记重要 / 转为故障 入口（只能在研判弹窗完成）', async () => {
    // 跟进中（可编辑状态）也不得出现这两个独立入口
    const followingDetail = {...RECORD_DETAIL, status: 'following_up',
      converted_fault: null, converted_fault_no: ''};
    await renderDetail(followingDetail, followingDetail);
    const btns = buttonTexts();
    expect(btns.some(t => t === '标记重要')).toBe(false);
    expect(btns.some(t => t === '转为故障')).toBe(false);
    // 标记重要/转为故障不渲染对应弹窗：整页不存在其确认文案
    const text = bodyText();
    expect(text).not.toContain('标记为重要运行记录');
    expect(text).not.toContain('转为正式故障');
  });

  it('关闭：提交 close 端点（跟进中状态）', async () => {
    const followingDetail = {...RECORD_DETAIL, status: 'following_up',
      converted_fault: null, converted_fault_no: ''};
    await renderDetail(followingDetail, followingDetail);
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByText('关闭');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/11/close/',
      {handling_result: ''});
  });
});

describe('运行记录详情基本信息分区', () => {
  it('按 运行概况/研判与处置/关联与登记/处理概览 四区块展示', async () => {
    const detail = {...RECORD_DETAIL, converted_fault: null, converted_fault_no: ''};
    await renderDetail(detail, detail);
    const text = bodyText();
    ['运行概况', '研判与处置', '关联与登记', '处理概览'].forEach(title => {
      expect(text).toContain(title);
    });
    // 尚未研判以提示行说明，不渲染空的研判说明行
    expect(text).toContain('尚未完成研判');
    expect(text).not.toContain('研判说明');
    // 未关联故障显示"-"；空的跟进安排/重要原因/标记重要/处理时间不产生空行
    expect(text).toMatch(/关联故障:?-/);
    expect(text).not.toContain('跟进安排');
    expect(text).not.toContain('重要原因');
    expect(text).not.toContain('标记重要');
    expect(text).not.toContain('处理时间');
  });

  it('标题区只保留编号/状态/影响/重要摘要，完整字段不再堆在标题区', async () => {
    await renderDetail();
    const header = document.querySelector('.ant-modal-header').textContent;
    expect(header).toContain('YX20261001-0001');
    expect(header).toContain('已记录');
    expect(header).toContain('中断');
    expect(header).toContain('普通');
    // 所属系统/安装地点/发生时间/登记人不进标题区，只在基本信息区块展示
    expect(header).not.toContain('所属系统');
    expect(header).not.toContain('安装地点');
    expect(header).not.toContain('发生时间');
    expect(header).not.toContain('登记人');
  });

  it('所属系统/安装地点/发生时间只在运行概况区出现一次', async () => {
    await renderDetail();
    const text = bodyText();
    expect(text).toContain('烟台通信系统');
    expect(text).toContain('机房A');
    expect(countOccurrences(text, '所属系统')).toBe(1);
    expect(countOccurrences(text, '安装地点')).toBe(1);
    expect(countOccurrences(text, '发生时间')).toBe(1);
    expect(countOccurrences(text, '情况描述')).toBe(1);
  });

  it('研判/跟进历史在已处理状态仍只读展示，且只在研判与处置区出现', async () => {
    await renderDetail(TRIAGED_RESOLVED_DETAIL, TRIAGED_RESOLVED_DETAIL);
    const text = bodyText();
    expect(countOccurrences(text, '研判说明')).toBe(1);
    expect(countOccurrences(text, '研判人及研判时间')).toBe(1);
    expect(text).toContain('判断为链路抖动，需持续跟进');
    expect(text).toContain('李四（2026-10-0209:00）');
    expect(countOccurrences(text, '跟进安排')).toBe(1);
    expect(text).toContain('跟进人：王值班');
    expect(text).toContain('计划处理：');
    expect(text).toContain('链路稳定，连续三天无丢包');
    expect(text).toContain('处理时间');
    expect(text).not.toContain('尚未完成研判');
  });

  it('登记人/登记时间只在关联与登记区，不再重复展示创建人', async () => {
    await renderDetail(TRIAGED_RESOLVED_DETAIL, TRIAGED_RESOLVED_DETAIL);
    const text = bodyText();
    expect(countOccurrences(text, '登记人')).toBe(1);
    expect(countOccurrences(text, '登记时间')).toBe(1);
    expect(text).toContain('张三');
    expect(text).not.toContain('创建人');
    expect(text).not.toContain('创建时间');
  });

  it('需要跟进标识仅在状态标签无法表达时展示', async () => {
    const recordedFollow = {...RECORD_DETAIL, needs_follow_up: true};
    await renderDetail(recordedFollow, recordedFollow);
    expect(document.querySelector('.ant-modal-header').textContent)
      .toContain('需要跟进');
    ReactDOM.unmountComponentAtNode(container);
    // 跟进中状态标签本身已表达跟进含义，标题区不再重复标
    const following = {...RECORD_DETAIL, status: 'following_up', needs_follow_up: true,
      converted_fault: null, converted_fault_no: ''};
    await renderDetail(following, following);
    expect(document.querySelector('.ant-modal-header').textContent)
      .not.toContain('需要跟进');
  });
});

describe('运行记录详情关联跳转与处理概览', () => {
  it('已转正式故障：区块提示+链接跳转沿用现有实现，终态只读无编辑控件', async () => {
    const converted = {...RECORD_DETAIL, status: 'converted_fault'};
    await renderDetail(converted, converted);
    expect(bodyText()).toContain('该记录已转正式故障，后续处置以关联故障为准');
    require('libs').history.push.mockClear();
    await act(async () => {
      clickButtonByText('GZ20261001-0007');
    });
    expect(require('libs').history.push).toHaveBeenCalledWith('/el/faults?detail=88');
    const btns = buttonTexts();
    ['编辑', '研判', '追加处理进展', '标记已处理', '关闭'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(false);
    });
  });

  it('关联故障已撤销时明确提示，不再渲染链接', async () => {
    const cancelled = {...RECORD_DETAIL, status: 'converted_fault',
      converted_fault: null, converted_fault_no: ''};
    await renderDetail(cancelled, cancelled);
    const text = bodyText();
    expect(text).toContain('关联故障登记已撤销');
    expect(text).not.toContain('GZ20261001-0007');
    expect(text).not.toContain('查看关联故障');
  });

  it('处理概览展示条数/最近更新/最后记录，查看全部进展直达处理进展页签', async () => {
    await renderDetail();
    const text = bodyText();
    expect(text).toContain('处理进展1条');
    expect(text).toContain('查看全部进展');
    expect(text).toContain('最近更新');
    expect(text).toContain('最后记录：现场检查，确认交换机告警');
    // 完整时间线不复制到基本信息区：切换前不可见，切换后可见
    expect(text).not.toContain('由admin更正');
    await act(async () => {
      clickButtonByText('查看全部进展');
    });
    await act(async () => {await flush();});
    expect(bodyText()).toContain('由admin更正');
  });

  it('无处理进展时处理概览显示暂无，不发起额外拼装请求', async () => {
    const detail = {...RECORD_DETAIL, converted_fault: null, converted_fault_no: ''};
    await renderDetail(detail, detail, {data: [], total: 0});
    expect(bodyText()).toContain('暂无处理进展');
    expect(bodyText()).not.toContain('查看全部进展');
  });
});

describe('系统详情运行记录页签', () => {
  it('只展示本系统运行记录（系统详情页签数据源）', async () => {
    const SystemRuntimeRecordsTab = require('../../SystemRuntimeRecordsTab').default;
    mockListApis();
    await act(async () => {
      ReactDOM.render(<SystemRuntimeRecordsTab systemId={1}/>, container);
    });
    await act(async () => {await flush();});
    const text = bodyText();
    expect(text).toContain('YX20261001-0001');
    expect(text).toContain('主用链路短暂中断');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/1/runtime-records/');
  });
});
