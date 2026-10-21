/**
 * "批量导出 PDF"（2026-10-21，替换原"导出明细 CSV"入口）页面行为测试。
 *
 * 真实渲染 LedgerIndex（ReactDOM + jsdom）+ mock libs.http/exportFile，
 * antd 组件真实渲染（Modal/Table/Select/Checkbox），验证：
 * - 入口替换：两个列表（周月维护/季维护）的"按维护周期"与"按模板查看"
 *   视图均提供"批量导出 PDF"且不再有"导出明细 CSV"；组内"导出本模板
 *   台账"（单模板导出）保留不变；
 * - 弹窗：打开时按当前台账类型拉取候选清单（周月/季维护不混选），
 *   展示模板名称/ID（同名模板以 ID 区分）/已停用标注/可导出台账数量；
 * - 选择：搜索过滤、全选当前搜索结果、清空，明确显示已选模板数量；
 * - 状态范围：默认已完成（不含草稿/已作废），切换范围后数量与涉及版本
 *   联动；所选范围下为 0 的模板复选框禁用，切换范围后选中项变 0 时
 *   明确提示并禁用导出；超限时禁用导出并提示；
 * - 导出发起：POST 模板 ID + 状态范围 + 预览数量（expected_totals），
 *   单模板与多模板一致走同一端点，导出后弹窗关闭。
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
  // exportFile 实现为 async 函数（必返回 Promise），store 在其上 .finally 复位加载态
  exportFile: jest.fn(() => Promise.resolve()),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement('button', {
    type: 'button',
    onClick: props.onClick,
    disabled: props.disabled,
  }, props.children);
  const SearchForm = (props) => React.createElement('div', null, props.children);
  SearchForm.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell,
    AuthButton,
    AuthCard: Shell,
    AuthFragment: Shell,
    Breadcrumb,
    SearchForm,
    ExportButton: AuthButton,
    TableCard: Shell,
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

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  // mockReset 会清掉 exportFile 的 Promise 实现，这里只清调用记录
  require('libs').exportFile.mockClear();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

// 候选清单载荷（与 GET /ledgers/export-pdf/ 响应 data 形态一致）：
// 模板 7 与 9 同名"信道维护台账"（以 ID 区分），模板 9 已停用；
// 模板 7：v1/v2 各版本均有已完成台账；模板 8：仅草稿（默认范围不可选）
function makeTemplatesPayload(overrides = {}) {
  return {data: {
    ledger_type: 'week_month',
    templates: [
      {
        template_id: 7, template_name: '信道维护台账', is_active: true,
        ledger_type: 'week_month',
        counts: {completed: 2, draft: 1, void: 1},
        versions: {1: {completed: 1, draft: 0, void: 1}, 2: {completed: 1, draft: 1, void: 0}},
      },
      {
        template_id: 8, template_name: '季检草稿模板', is_active: true,
        ledger_type: 'week_month',
        counts: {completed: 0, draft: 3, void: 0},
        versions: {1: {completed: 0, draft: 3, void: 0}},
      },
      {
        template_id: 9, template_name: '信道维护台账', is_active: false,
        ledger_type: 'week_month',
        counts: {completed: 1, draft: 0, void: 0},
        versions: {3: {completed: 1, draft: 0, void: 0}},
      },
    ],
    default_statuses: ['completed'],
    max_records: 50,
    ...overrides,
  }};
}

const PERIOD_GROUPS_PAYLOAD = [{
  maintenance_period: '2026-10', period_text: '2026年10月',
  total: 2, pending: 2, filled: 0, ledgers: [],
}];

const TEMPLATE_GROUPS_PAYLOAD = {data: [], total: 0, page: 1, page_size: 10};

function mockHttpEndpoints(templatesPayload) {
  mockHttpGet.mockImplementation(url => {
    if (url.endsWith('/ledgers/export-pdf/')) {
      return Promise.resolve(templatesPayload || makeTemplatesPayload());
    }
    if (url.endsWith('/ledgers/template-groups/')) {
      return Promise.resolve(TEMPLATE_GROUPS_PAYLOAD);
    }
    if (url.endsWith('/ledgers/period-groups/')) {
      return Promise.resolve({data: PERIOD_GROUPS_PAYLOAD});
    }
    return Promise.resolve({data: [], total: 0});
  });
}

const entriesModule = require('../entries');
const storeModule = require('../store');

async function renderIndex(entry) {
  await act(async () => {
    ReactDOM.render(h(entry || entriesModule.WeekMonthLedgerIndex), container);
  });
  await act(flush);
}

function findButton(text) {
  return Array.from(container.querySelectorAll('button'))
    .find(el => el.textContent.includes(text));
}

function findModalButton(text) {
  // antd 按钮对两个汉字文案自动插入空格（取 消），匹配前统一去除空白
  const target = text.replace(/\s/g, '');
  return Array.from(document.body.querySelectorAll('button'))
    .find(el => el.textContent.replace(/\s/g, '') === target);
}

function findRadioInput(label) {
  const inputs = Array.from(container.querySelectorAll('label.ant-radio-button-wrapper'));
  return inputs.find(el => el.textContent === label);
}

function modalText() {
  return document.querySelector('.ant-modal') ? document.body.textContent : '';
}

function modalVisible() {
  const modal = Array.from(document.body.querySelectorAll('.ant-modal'))
    .find(el => el.textContent.includes('按模板批量导出 PDF'));
  return !!modal && !modal.closest('.ant-modal-wrap.ant-modal-wrap-hidden');
}

async function openModal(entry) {
  await renderIndex(entry);
  await act(async () => {
    findButton('批量导出 PDF').click();
  });
  await act(flush);
}

function checkRow(templateId) {
  const row = Array.from(document.body.querySelectorAll('.ant-table-tbody tr'))
    .find(el => el.textContent.includes(`ID: ${templateId}`));
  expect(row).toBeTruthy();
  return row.querySelector('.ant-checkbox-input');
}

function setKeyword(text) {
  const input = document.body.querySelector('input[placeholder="搜索模板名称或 ID"]');
  expect(input).toBeTruthy();
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, text);
  input.dispatchEvent(new Event('input', {bubbles: true}));
}

describe('批量导出 PDF·入口替换（2026-10-21）', () => {
  beforeEach(() => {
    const store = storeModule.getLedgerStore('week_month');
    store.viewMode = 'period';
    store.activeGroup = null;
    store.multiExportVisible = false;
    store.multiExportTemplates = null;
    store.multiExportSelected = [];
    store.multiExportStatus = '';
    mockHttpEndpoints();
  });

  test('周期视图：批量导出 PDF 在位，导出明细 CSV 已移除', async () => {
    await renderIndex();
    expect(findButton('批量导出 PDF')).toBeTruthy();
    expect(findButton('导出明细 CSV')).toBeUndefined();
  });

  test('模板视图（组列表层级）：批量导出 PDF 在位，导出明细 CSV 已移除', async () => {
    await renderIndex();
    await act(async () => {
      findRadioInput('按模板查看').querySelector('input').click();
    });
    await act(flush);
    expect(findButton('批量导出 PDF')).toBeTruthy();
    expect(findButton('导出明细 CSV')).toBeUndefined();
  });

  test('季维护列表同样提供批量导出 PDF 入口', async () => {
    await renderIndex(entriesModule.SeasonalLedgerIndex);
    expect(findButton('批量导出 PDF')).toBeTruthy();
    expect(findButton('导出明细 CSV')).toBeUndefined();
  });

  test('组内单模板导出入口保留（导出本模板台账），无 CSV 入口回潮', async () => {
    const store = storeModule.getLedgerStore('week_month');
    store.viewMode = 'template';
    store.activeGroup = {group_key: '7', group_name: '信道维护台账'};
    await renderIndex();
    await act(flush);
    expect(findButton('导出本模板台账')).toBeTruthy();
    expect(findButton('导出明细 CSV')).toBeUndefined();
    // 组内层级不显示全局多模板入口（避免与单模板导出混淆）
    expect(findButton('批量导出 PDF')).toBeUndefined();
  });
});

const RESET_FIELDS = () => {
  const store = storeModule.getLedgerStore('week_month');
  store.viewMode = 'period';
  store.activeGroup = null;
  store.multiExportVisible = false;
  store.multiExportTemplates = null;
  store.multiExportSelected = [];
  store.multiExportStatus = '';
  mockHttpEndpoints();
};

describe('批量导出 PDF·弹窗展示与选择', () => {
  beforeEach(RESET_FIELDS);

  test('打开弹窗按当前台账类型拉取候选清单并展示数量/ID/停用标注', async () => {
    await openModal();
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/ledgers/export-pdf/'));
    expect(call[1].params.ledger_type).toBe('week_month');
    expect(modalVisible()).toBe(true);
    const text = modalText();
    expect(text).toContain('信道维护台账');
    expect(text).toContain('ID: 7');
    expect(text).toContain('ID: 9');
    expect(text).toContain('已停用');
    // 默认状态范围（已完成）：模板 7 可导出 2 条
    expect(text).toContain('手工补录台账没有模板版式');
  });

  test('同名模板以 ID 区分展示（两行独立可选）', async () => {
    await openModal();
    const ids = Array.from(document.body.querySelectorAll('.ant-table-tbody tr'))
      .filter(el => el.textContent.includes('信道维护台账'))
      .map(el => el.textContent.includes('ID: 7') ? 7 : (el.textContent.includes('ID: 9') ? 9 : null))
      .filter(Boolean);
    expect(ids).toEqual([7, 9]);
  });

  test('搜索过滤模板列表，全选搜索结果只选中过滤后的可选模板', async () => {
    await openModal();
    await act(async () => {
      setKeyword('信道');
    });
    await act(flush);
    const rows = Array.from(document.body.querySelectorAll('.ant-table-tbody tr'))
      .filter(el => el.querySelector('.ant-checkbox-input'));
    expect(rows).toHaveLength(2); // 模板 7 与 9（同名匹配），模板 8 被过滤
    await act(async () => {
      findModalButton('全选搜索结果').click();
    });
    await act(flush);
    expect(modalText()).toContain('已选择 2 个模板');
    expect(modalText()).toContain('共 3 条台账');
  });

  test('清空选择后已选数量归零', async () => {
    await openModal();
    await act(async () => {
      checkRow(7).click();
    });
    await act(flush);
    expect(modalText()).toContain('已选择 1 个模板');
    await act(async () => {
      findModalButton('清空选择').click();
    });
    await act(flush);
    expect(modalText()).toContain('已选择 0 个模板');
  });

  test('默认范围下零可导出模板复选框禁用（仅草稿模板不可选）', async () => {
    await openModal();
    const checkbox = checkRow(8);
    expect(checkbox.disabled).toBe(true);
  });

});

describe('批量导出 PDF·弹窗状态范围与上限', () => {
  beforeEach(RESET_FIELDS);

  test('切换状态范围为全部：数量与涉及版本联动更新', async () => {
    const store = storeModule.getLedgerStore('week_month');
    await openModal();
    await act(async () => {
      checkRow(7).click();
    });
    await act(flush);
    expect(modalText()).toContain('共 2 条台账');
    expect(modalText()).toContain('v2（1 条）');
    await act(async () => {
      store.setMultiExportStatus('all');
    });
    await act(flush);
    expect(modalText()).toContain('共 4 条台账');
    expect(modalText()).toContain('全部（含草稿、已作废）');
    // 全范围下仅草稿模板也可选了
    expect(checkRow(8).disabled).toBe(false);
  });

  test('选择后切换范围导致部分模板可导出为 0：明确提示并禁用导出', async () => {
    const store = storeModule.getLedgerStore('week_month');
    await openModal();
    await act(async () => {
      checkRow(7).click();
    });
    await act(flush);
    await act(async () => {
      checkRow(9).click();
    });
    await act(flush);
    // 切到"已作废"：模板 7 仍有 1 条已作废，模板 9（仅已完成）变为 0
    await act(async () => {
      store.setMultiExportStatus('void');
    });
    await act(flush);
    expect(modalText()).toContain('模板「信道维护台账」在所选状态范围内没有可导出的台账');
    expect(findModalButton('导出 PDF').disabled).toBe(true);
    expect(findModalButton('导出 PDF').disabled).toBe(true);
  });

  test('超过单次导出上限时禁用导出并明确提示', async () => {
    mockHttpEndpoints(makeTemplatesPayload({max_records: 3}));
    const store = storeModule.getLedgerStore('week_month');
    await openModal();
    await act(async () => {
      checkRow(7).click();
    });
    await act(async () => {
      store.setMultiExportStatus('all');
    });
    await act(flush);
    expect(modalText()).toContain('超过单次导出上限 3 条');
    expect(findModalButton('导出 PDF').disabled).toBe(true);
  });
});

describe('批量导出 PDF·导出发起', () => {
  beforeEach(RESET_FIELDS);

  test('单模板导出：POST 模板 ID + 默认状态范围 + 预览数量，弹窗关闭', async () => {
    await openModal();
    await act(async () => {
      checkRow(7).click();
    });
    await act(flush);
    await act(async () => {
      findModalButton('导出 PDF').click();
    });
    await act(flush);
    const mockExportFile = require('libs').exportFile;
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const options = mockExportFile.mock.calls[0][0];
    expect(options.url).toBe('/api/equipment-lifecycle/ledgers/export-pdf/');
    expect(options.method).toBe('post');
    expect(options.data.ledger_type).toBe('week_month');
    expect(options.data.template_ids).toEqual([7]);
    expect(options.data.status).toBe('');
    expect(options.data.expected_totals).toEqual({7: 2});
    expect(options.timeout).toBe(300000);
    expect(modalVisible()).toBe(false);
  });

  test('多模板导出：全部选中模板与各自预览数量一并提交', async () => {
    await openModal();
    // 两次点击分开（同批次内受控 selectedRowKeys 未刷新会互相覆盖）
    await act(async () => {
      checkRow(7).click();
    });
    await act(flush);
    await act(async () => {
      checkRow(9).click();
    });
    await act(flush);
    await act(async () => {
      findModalButton('导出 PDF').click();
    });
    await act(flush);
    const options = require('libs').exportFile.mock.calls[0][0];
    expect(options.data.template_ids).toEqual([7, 9]);
    expect(options.data.expected_totals).toEqual({7: 2, 9: 1});
  });

  test('状态范围 all：status 与预期数量按全范围计算', async () => {
    const store = storeModule.getLedgerStore('week_month');
    await openModal();
    await act(async () => {
      store.setMultiExportStatus('all');
    });
    await act(async () => {
      checkRow(7).click();
    });
    await act(flush);
    await act(async () => {
      findModalButton('导出 PDF').click();
    });
    await act(flush);
    const options = require('libs').exportFile.mock.calls[0][0];
    expect(options.data.status).toBe('all');
    expect(options.data.expected_totals).toEqual({7: 4});
  });

  test('季维护页打开弹窗请求季维护类型，导出携带对应类型（不混选）', async () => {
    const store = storeModule.getLedgerStore('seasonal');
    store.viewMode = 'period';
    store.activeGroup = null;
    store.multiExportVisible = false;
    store.multiExportTemplates = null;
    store.multiExportSelected = [];
    store.multiExportStatus = '';
    mockHttpEndpoints(makeTemplatesPayload({
      ledger_type: 'seasonal',
      templates: [{
        template_id: 31, template_name: '季维护台账模板', is_active: true,
        ledger_type: 'seasonal',
        counts: {completed: 2, draft: 0, void: 0},
        versions: {1: {completed: 2, draft: 0, void: 0}},
      }],
    }));
    await openModal(entriesModule.SeasonalLedgerIndex);
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/ledgers/export-pdf/'));
    expect(call[1].params.ledger_type).toBe('seasonal');
    await act(async () => {
      checkRow(31).click();
    });
    await act(flush);
    await act(async () => {
      findModalButton('导出 PDF').click();
    });
    await act(flush);
    const options = require('libs').exportFile.mock.calls[0][0];
    expect(options.data.ledger_type).toBe('seasonal');
    expect(options.data.template_ids).toEqual([31]);
  });
});
