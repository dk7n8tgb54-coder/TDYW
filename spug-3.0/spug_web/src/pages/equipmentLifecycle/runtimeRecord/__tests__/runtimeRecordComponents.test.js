/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行记录组件渲染测试（2026-10 第一版；2026-10-04 信息分层收敛；
 * 2026-10-05 第四版研判不再是必经步骤）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 列表页渲染运行记录行（编号/系统/标题/状态）与"新增运行记录"入口
 * - 列表请求指向 runtime-records 端点，且不含巡视/维护/升级数据来源
 * - 新增表单承载运行事实（五个必填 + 异常类别选填）；具体对象名称/对象型号/
 *   影响系统运行/影响程度/标记重要已删除（2026-10-06），不再出现在表单；
 *   跟进安排与处理字段（已采取措施/处理结果/初步原因/影响范围/研判说明/
 *   跟进人/计划处理时间）不出现；空表单提交被校验拦截（不发请求）
 * - 编辑模式回填后可提交（PUT 携带修改值，不携带重要程度/登记人键）
 * - 详情窗口展示编号/状态/关联故障入口；顶部动作按第四版状态收敛：
 *   已记录族 = 编辑/开始跟进/转为正式故障（无研判/关闭/标记重要）；
 *   跟进中 = 新增跟进记录/完成跟进/转为正式故障（修改跟进计划已随跟进
 *   计划删除移除 2026-10-06）；已转故障终态无编辑/追加/标记按钮
 * - 详情基本信息分区（2026-10-04 信息分层）：运行概况/关联与登记/处理概览
 *   （研判结论区块已随研判快照字段删除移除 2026-10-07）；标题区只保留
 *   编号/状态摘要
 * - 处理进展页签统一工作区（2026-10-06 优化）：新增处理进展（内联表单）/
 *   处理进展时间线；处理结果/本次工时字段已删除
 * - 跟进中动作（完成跟进/转为正式故障）走 resolve/convert-to-fault 端点
 *   （矩阵与端点细节见 runtimeRecordDetailActions 套件）
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
      record_type: 'abnormal', record_type_text: '异常事件',
      system_name: '烟台通信系统', system_code: 'SYS-A1', system_location: '机房A',
      occurred_at: '2026-10-01 08:30', title: '主用链路短暂中断',
      status: 'recorded', status_text: '已记录',
      needs_follow_up: false,
      converted_fault: null, converted_fault_no: '',
      created_by_name: 'admin', created_at: '2026-10-01 08:35',
    },
    {
      id: 12, record_no: 'YX20261001-0002', system: 2,
      record_type: 'routine', record_type_text: '日常运行',
      system_name: '导航系统B', system_code: 'SYS-B1', system_location: '机房B',
      occurred_at: '2026-10-01 09:00', title: '席位显示器闪烁',
      status: 'completed', status_text: '已完成',
      needs_follow_up: false,
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
  converted_fault: 88, converted_fault_no: 'GZ20261001-0007',
  updated_at: null,
};

const PROGRESS_PAGE = {
  data: [
    {id: 1, record: 11, handled_at: '2026-10-01 09:00', handler: 2,
      handler_name: '值班员甲', content: '现场检查，确认交换机告警',
      corrections: [{old: '现场检查', new: '现场检查，确认交换机告警',
        reason: '补充细节', by: 'admin', at: '2026-10-01 09:10'}],
      created_at: '2026-10-01 09:05'},
  ],
  total: 1, page: 1, page_size: 100,
};

// 已完成且带遗留研判字段：研判快照字段已删除（2026-10-07），即使接口
// 返回旧字段值也不再渲染
const TRIAGED_COMPLETED_DETAIL = {
  ...RECORD_DETAIL,
  status: 'completed', status_text: '已完成',
  converted_fault: null, converted_fault_no: '',
  triaged_at: '2026-10-02 09:00', triaged_by_name: '李四',
  triage_note: '判断为链路抖动，需持续跟进',
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
  it('渲染运行记录行：编号/系统/标题/状态，且提供新增入口', async () => {
    await renderListPage();
    const text = bodyText();
    expect(text).toContain('YX20261001-0001');
    expect(text).toContain('YX20261001-0002');
    expect(text).toContain('烟台通信系统');
    expect(text).toContain('主用链路短暂中断');
    expect(text).toContain('已记录');
    expect(text).toContain('已完成');
    expect(text).toContain('新增运行记录');
    // "关联"（重复关联数量）列已随重复问题功能下线（2026-10-05）移除；
    // "影响状态"列已随影响字段删除（2026-10-06）移除
    const headers = Array.from(document.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent.replace(/\s+/g, ''));
    expect(headers).not.toContain('关联');
    expect(headers).not.toContain('影响状态');
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
  it('新增默认日常运行：记录类型选择 + 作业内容/操作结果字段，异常专属字段不出现', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockListApis();
    await act(async () => {
      store.showForm();
      ReactDOM.render(<RecordForm/>, container);
    });
    await act(async () => {await flush();});
    const text = bodyText();
    // 记录类型（2026-10-07）默认日常运行：类型选择 + 公共字段 + 日常专属字段
    ['记录类型', '日常运行', '异常事件', '所属系统', '发生时间', '标题',
      '情况描述', '登记人', '记录类别', '作业内容', '操作结果/检查结果'].forEach(label => {
      expect(text).toContain(label);
    });
    // 日常运行不出现异常类别口径与异常专属/已删除字段
    ['异常类别', '关联日常运行', '具体对象名称', '对象型号/编号', '影响系统运行',
      '影响程度', '标记重要', '已采取措施', '处理结果', '初步原因', '影响范围',
      '研判说明', '跟进人', '计划处理时间', '需要跟进'].forEach(label => {
      expect(text).not.toContain(label);
    });
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

  it('编辑模式回填详情后提交 PUT，且不携带重要程度/登记人键/记录类型键', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockListApis();
    mockHttpPut.mockResolvedValue({});
    await act(async () => {
      store.showForm({...RECORD_DETAIL, status: 'recorded'});
      ReactDOM.render(<RecordForm/>, container);
    });
    await act(async () => {await flush();});
    // 回填后标题可见（编辑表单只回填事实字段，历史字段不进编辑表单）
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
    // record_type 创建后不可修改：编辑提交不携带该键
    expect(payload.record_type).toBeUndefined();
    expect(store.formVisible).toBe(false);
  });
});

describe('运行记录详情窗口', () => {
  it('展示编号/状态/关联故障入口与登记信息', async () => {
    await renderDetail();
    const text = bodyText();
    expect(text).toContain('YX20261001-0001');
    expect(text).toContain('已记录');
    // bodyText 去空白：断言用去空格文本
    expect(text).toContain('值班发现主用链路丢包约3分钟后自行恢复');
    // 登记人（手输姓名快照）在详情展示
    expect(text).toContain('登记人');
    expect(text).toContain('张三');
    // 已记录状态（第四版）：编辑/开始跟进/转为正式故障；
    // 无研判入口与业务"关闭记录"（留痕场景以新建提交为完成）；
    // 标记重要已随字段删除移除（2026-10-06）
    const btns = buttonTexts();
    ['编辑', '开始跟进', '转为正式故障'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(true);
    });
    ['关闭', '研判', '提交研判', '标记需要跟进', '标记已处理', '转为故障',
      '标记重要', '完成跟进', '添加处理进展', '重新跟进'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(false);
    });
    // 关联故障入口（已转故障号可见）
    expect(text).toContain('GZ20261001-0007');
  });

  it('已转故障（终态，关联已撤销）记录不显示编辑/追加/标记动作', async () => {
    const convertedDetail = {...RECORD_DETAIL, status: 'converted_fault',
      converted_fault: null, converted_fault_no: ''};
    await renderDetail(convertedDetail, convertedDetail);
    const btns = buttonTexts();
    ['编辑', '研判', '开始跟进', '新增跟进记录', '标记需要跟进', '标记已处理',
      '标记重要', '转为故障', '转为正式故障', '完成跟进', '重新跟进',
      '关闭', '重新研判'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(false);
    });
  });

  it('处理进展页签：时间线展示内容与更正留痕，内联录入表单可见；已转故障只读', async () => {
    await renderDetail({...RECORD_DETAIL, status: 'recorded', converted_fault: null});
    await openTab('处理进展');
    const text = bodyText();
    expect(text).toContain('现场检查，确认交换机告警');
    expect(text).toContain('值班员甲');
    expect(text).toContain('补充细节');
    expect(text).toContain('由admin更正');
    // 内联录入表单（处理时间/处理人/处理内容）+ 追加进展按钮
    expect(text).toContain('新增处理进展');
    expect(text).toContain('处理时间');
    expect(text).toContain('处理人');
    expect(text).toContain('处理内容');
    expect(buttonTexts().some(t => t === '追加进展')).toBe(true);
    // 处理结果/本次工时已删除：表单与时间线均不再出现
    expect(text).not.toContain('处理结果');
    expect(text).not.toContain('本次工时');
    // 已转故障（终态）：无内联表单与更正按钮
    const convertedDetail = {...RECORD_DETAIL, status: 'converted_fault'};
    await renderDetail(convertedDetail, convertedDetail);
    await openTab('处理进展');
    expect(buttonTexts().some(t => t === '追加进展')).toBe(false);
    expect(buttonTexts().some(t => t === '更正')).toBe(false);
  });

  it('跟进中顶部提供 转为正式故障 入口（独立动作，不依赖研判）', async () => {
    const followingDetail = {...RECORD_DETAIL, status: 'following_up',
      converted_fault: null, converted_fault_no: ''};
    await renderDetail(followingDetail, followingDetail);
    const btns = buttonTexts();
    expect(btns.some(t => t === '转为正式故障')).toBe(true);
    expect(btns.some(t => t === '转为故障')).toBe(false);
    // 跟进中不显示标记重要（仅已记录族独立动作）
    expect(btns.some(t => t === '标记重要')).toBe(false);
    // 新流程动作齐备（修改跟进计划已随跟进计划删除移除）
    ['新增跟进记录', '完成跟进'].forEach(btn => {
      expect(btns.some(t => t === btn)).toBe(true);
    });
    expect(btns.some(t => t === '修改跟进计划')).toBe(false);
  });

  it('完成跟进：提交 resolve 端点（纯确认动作，不携带处理结果字段）', async () => {
    const followingDetail = {...RECORD_DETAIL, status: 'following_up',
      converted_fault: null, converted_fault_no: ''};
    await renderDetail(followingDetail, followingDetail);
    mockHttpPost.mockResolvedValue({});
    await act(async () => {
      clickButtonByText('完成跟进');
    });
    await act(async () => {await flush();});
    await act(async () => {
      clickModalOk();
    });
    await act(async () => {await flush();});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/11/resolve/',
      {});
    // 完成跟进确认弹窗不再提供处理结果输入
    expect(document.body.textContent).not.toContain('补填处理结果');
  });
});

describe('运行记录详情基本信息分区', () => {
  it('按 运行概况/关联与登记/处理概览 分区；无历史研判数据时不渲染研判结论区', async () => {
    const detail = {...RECORD_DETAIL, converted_fault: null, converted_fault_no: '',
      measures_taken: '', initial_reason: '', impact_scope: '', handling_result: ''};
    await renderDetail(detail, detail);
    const text = bodyText();
    // 第四版：研判不再是必经步骤，新记录无研判数据，研判结论区不渲染
    ['运行概况', '关联与登记', '处理概览'].forEach(title => {
      expect(text).toContain(title);
    });
    expect(text).not.toContain('研判结论');
    expect(text).not.toContain('尚未完成研判');
    // 信息分层：处理过程只进处理进展时间线，基本信息不重复展示
    expect(text).not.toContain('已采取措施');
    expect(text).not.toContain('处理结果');
    expect(text).not.toContain('初步原因');
    expect(text).not.toContain('影响范围');
    // 无历史字段数据时不渲染"历史记录"区块
    expect(text).not.toContain('历史记录');
    // 未关联故障显示"-"；跟进安排已移出基本信息，重要原因/处理时间不产生空行
    expect(text).toMatch(/关联故障:?-/);
    expect(text).not.toContain('跟进安排');
    expect(text).not.toContain('重要原因');
    expect(text).not.toContain('处理时间');
  });

  it('标题区只保留编号/状态摘要，影响/重要标签与完整字段不再出现', async () => {
    await renderDetail();
    const header = document.querySelector('.ant-modal-header').textContent;
    expect(header).toContain('YX20261001-0001');
    expect(header).toContain('已记录');
    // 影响程度/重要程度标签已随字段删除移除（2026-10-06）
    expect(header).not.toContain('中断');
    expect(header).not.toContain('普通');
    expect(header).not.toContain('重要');
    expect(header).not.toContain('不影响运行');
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

  it('已采取措施/处理结果/初步原因/影响范围已不再在任何区块展示（历史记录区块删除）', async () => {
    const legacy = {...RECORD_DETAIL, converted_fault: null, converted_fault_no: '',
      initial_reason: '疑为功放模块老化', impact_scope: '本场航路导航',
      measures_taken: '切换备用链路观察', handling_result: '链路稳定，连续三天无丢包'};
    await renderDetail(legacy, legacy);
    const text = bodyText();
    // 历史字段只读展示区块已整体移除（2026-10-06 状态/信息收敛）：旧字段
    // 数据即使接口返回也不再渲染
    ['历史记录', '以下为历史版本字段数据', '初步原因', '疑为功放模块老化',
      '影响范围', '本场航路导航', '已采取措施', '切换备用链路观察',
      '链路稳定，连续三天无丢包'].forEach(sub => {
      expect(text).not.toContain(sub);
    });
  });

  it('遗留研判字段即使接口返回也不再渲染（研判结论区块已删除）；处理时间保留', async () => {
    await renderDetail(TRIAGED_COMPLETED_DETAIL, TRIAGED_COMPLETED_DETAIL);
    const text = bodyText();
    // 研判快照字段已彻底删除（2026-10-07 迁移 0010）：详情不再有研判结论
    // 区块，接口遗留的旧字段值也不渲染
    ['研判结论', '研判说明', '研判人及研判时间', '判断为链路抖动，需持续跟进',
      '李四（2026-10-0209:00）', '尚未完成研判'].forEach(sub => {
      expect(text).not.toContain(sub);
    });
    // 已完成记录的生命周期信息（处理时间）正常展示
    expect(text).toContain('处理时间');
    // 处理进展页签：已完成提示追加进展将重新进入跟进中
    await openTab('处理进展');
    expect(bodyText()).toContain('跟进已完成');
  });

  it('登记人/登记时间只在关联与登记区，不再重复展示创建人', async () => {
    await renderDetail(TRIAGED_COMPLETED_DETAIL, TRIAGED_COMPLETED_DETAIL);
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

describe('运行记录详情处理进展页签（统一处理工作区）', () => {
  const FOLLOWING_DETAIL = {...RECORD_DETAIL, status: 'following_up',
    status_text: '跟进中', converted_fault: null, converted_fault_no: ''};

  it('跟进中：页签为 新增处理进展（内联表单）+ 处理进展时间线，无跟进计划区块', async () => {
    await renderDetail(FOLLOWING_DETAIL, FOLLOWING_DETAIL);
    // 顶部按钮：新增跟进记录/完成跟进/转为正式故障（无修改跟进计划）
    expect(buttonTexts().some(t => t === '新增跟进记录')).toBe(true);
    expect(buttonTexts().some(t => t === '修改跟进计划')).toBe(false);
    await openTab('处理进展');
    const text = bodyText();
    // 跟进计划区块已删除（2026-10-06）
    expect(text).not.toContain('当前跟进计划');
    expect(text).not.toContain('跟进人：');
    expect(text).toContain('新增处理进展');
    expect(text).toContain('处理进展时间线');
    // 内联表单：处理时间/处理人/处理内容（处理结果/本次工时已删除）
    ['处理时间', '处理人', '处理内容'].forEach(label => {
      expect(text).toContain(label);
    });
    expect(text).not.toContain('本次工时');
    expect(buttonTexts().some(t => t === '追加进展')).toBe(true);
  });

  it('未开始跟进的记录提示保存首条进展后进入跟进中；已完成提示追加进展将重新跟进', async () => {
    await renderDetail({...RECORD_DETAIL, converted_fault: null, converted_fault_no: ''});
    await openTab('处理进展');
    expect(bodyText()).toContain('尚未开始跟进');
    expect(bodyText()).toContain('保存第一条处理进展后进入跟进中');
    expect(bodyText()).not.toContain('研判');
    ReactDOM.unmountComponentAtNode(container);
    await renderDetail(TRIAGED_COMPLETED_DETAIL, TRIAGED_COMPLETED_DETAIL);
    await openTab('处理进展');
    expect(bodyText()).toContain('跟进已完成');
    expect(bodyText()).toContain('追加新的处理进展将重新进入跟进中');
    // 已完成可重新跟进（跳到处理进展工作区），但顶部无编辑/完成跟进入口
    expect(buttonTexts().some(t => t === '重新跟进')).toBe(true);
    expect(buttonTexts().some(t => t === '完成跟进')).toBe(false);
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
    // "关联"（重复关联数量）列已随重复问题功能下线（2026-10-05）移除
    const headers = Array.from(document.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent.replace(/\s+/g, ''));
    expect(headers).not.toContain('关联');
  });
});
