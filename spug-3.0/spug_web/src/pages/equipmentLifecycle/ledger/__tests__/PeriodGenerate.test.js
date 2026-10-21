/**
 * 生成本期应填台账（2026-10-14 重构原"一键新增"）页面行为测试。
 *
 * 真实渲染（ReactDOM + jsdom）+ mock libs.http，验证：
 * - Store：fetchGeneratePreview 请求参数与响应映射；generatePeriodLedgers
 *   提交类型、成功后按当前视图刷新并保存实际结果；
 * - LedgerPeriodGenerateModal：预览展示 模板/系统/生成周期/期次/版本 与
 *   四类判定汇总（将新建/已存在跳过/缺少可用版本/需人工处理，含原因）；
 *   无可新建条目时确认按钮禁用；确认后按后端实际结果如实展示；
 * - 两个填写列表入口：周月维护与季维护列表各有"生成本期应填台账"按钮，
 *   点击后拉取对应类型的预览（互不串扰）；
 * - 周期视图操作区（2026-10-20 视觉密度整轮）："生成本期应填台账"为唯一
 *   主按钮，Excel 新增与"批量导出 PDF"为次级默认按钮且全部在位
 *   （原生模板新增入口已随原生路线整体下线删除，2026-10-20；
 *   明细导出 CSV 已于 2026-10-21 替换为"批量导出 PDF"按模板多选入口）。
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
  const AuthButton = (props) => React.createElement('button', {
    type: 'button',
    'data-testid': props['data-testid'],
    'data-btn-type': props.type,
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

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const storeModule = require('../store');
const {LedgerStore} = storeModule;
const LedgerPeriodGenerateModal = require('../LedgerPeriodGenerateModal').default;

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const PREVIEW_PAYLOAD = {
  ledger_type: 'week_month',
  base_date: '2026-10-14',
  entries: [
    {template_id: 7, template_name: '信道周模板', system_id: 3, system_name: 'DVOR系统',
     system_code: 'SYS-3', generation_period: 'weekly', generation_period_text: '每周',
     maintenance_period: '2026-10-12', period_text: '2026-10-12 ~ 2026-10-18',
     version_id: 15, version_no: 2, status: 'create', reason: '', existing_ledger: null},
    {template_id: 8, template_name: '月模板', system_id: 4, system_name: 'ILS系统',
     system_code: 'SYS-4', generation_period: 'monthly', generation_period_text: '每月',
     maintenance_period: '2026-10', period_text: '2026年10月',
     version_id: 16, version_no: 1, status: 'exists', reason: '',
     existing_ledger: {id: 91, ledger_no: 'EL-WM-20261001-0001', status: 'draft'}},
    {template_id: 9, template_name: '未发布模板', system_id: 3, system_name: 'DVOR系统',
     system_code: 'SYS-3', generation_period: 'weekly', generation_period_text: '每周',
     maintenance_period: '2026-10-12', period_text: '2026-10-12 ~ 2026-10-18',
     version_id: null, version_no: null, status: 'no_version',
     reason: '缺少可用版本：模板尚未发布任何版本', existing_ledger: null},
    {template_id: 10, template_name: '历史模板', system_id: null, system_name: '',
     system_code: '', generation_period: '', generation_period_text: '待配置',
     maintenance_period: '', period_text: '', version_id: null, version_no: null,
     status: 'manual_needed', reason: '模板待配置：适用系统、生成周期'
       + '（历史模板不自动推断，请在模板管理中配置）', existing_ledger: null,
     rebuildable: false},
    {template_id: 12, template_name: '作废占用模板', system_id: 5, system_name: 'VOR系统',
     system_code: 'SYS-5', generation_period: 'weekly', generation_period_text: '每周',
     maintenance_period: '2026-10-12', period_text: '2026-10-12 ~ 2026-10-18',
     version_id: 17, version_no: 1, status: 'manual_needed',
     reason: '该期次已存在已作废台账 EL-WM-20261012-0009，不在一键生成中重建；确需重做请使用补建操作',
     existing_ledger: {id: 95, ledger_no: 'EL-WM-20261012-0009', status: 'void'},
     rebuildable: true},
  ],
  summary: {create: 1, exists: 1, no_version: 1, manual_needed: 2},
};

const GENERATE_RESULT = {
  ledger_type: 'week_month',
  created: [{id: 101, ledger_no: 'EL-WM-20261012-0001', template_id: 7,
             template_name: '信道周模板', system_name: 'DVOR系统',
             maintenance_period: '2026-10-12', period_text: '2026-10-12 ~ 2026-10-18',
             version_no: 2}],
  skipped: [{template_id: 8, template_name: '月模板', system_name: 'ILS系统',
             maintenance_period: '2026-10', period_text: '2026年10月',
             ledger: {id: 91, ledger_no: 'EL-WM-20261001-0001', status: 'draft'}}],
  failed: [{template_id: 9, template_name: '未发布模板', system_name: 'DVOR系统',
            status: 'no_version', reason: '缺少可用版本：模板尚未发布任何版本'},
           {template_id: 10, template_name: '历史模板', system_name: '',
            status: 'manual_needed', reason: '模板待配置'}],
};

const EMPTY_GROUPS = {data: []};

function mockLedgerEndpoints() {
  mockHttpGet.mockImplementation(url => {
    if (url.endsWith('/ledgers/period-groups/')) return Promise.resolve(EMPTY_GROUPS);
    if (url.endsWith('/ledgers/batch-create/')) return Promise.resolve({data: []});
    return Promise.resolve({});
  });
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  mockLedgerEndpoints();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  // 清理 Modal 传送门残留，避免污染后续用例的 textContent 断言
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask').forEach(node => node.remove());
});

function findButton(text) {
  return Array.from(document.body.querySelectorAll('button'))
    .find(el => el.textContent.replace(/\s+/g, '') === text);
}

function findButtonStarting(text) {
  return Array.from(document.body.querySelectorAll('button'))
    .find(el => el.textContent.replace(/\s+/g, '').startsWith(text));
}

describe('LedgerStore 生成预览与生成', () => {
  test('fetchGeneratePreview 携带台账类型并映射预览数据', async () => {
    mockHttpGet.mockResolvedValue({data: PREVIEW_PAYLOAD});
    const store = new LedgerStore('week_month');
    const preview = await store.fetchGeneratePreview('week_month');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledgers/period-generate/',
      {params: {ledger_type: 'week_month'}});
    expect(preview.summary).toEqual({create: 1, exists: 1, no_version: 1, manual_needed: 2});
    expect(store.generatePreview.entries).toHaveLength(5);
    expect(store.isGenerateFetching).toBe(false);
  });

  test('generatePeriodLedgers 提交类型、保存实际结果并刷新当前视图', async () => {
    mockHttpPost.mockResolvedValue({data: GENERATE_RESULT});
    const store = new LedgerStore('week_month');
    const result = await store.generatePeriodLedgers('week_month', ['weekly'], [7]);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledgers/period-generate/', {
        ledger_type: 'week_month', maintenance_cycles: ['weekly'], template_ids: [7]});
    expect(result.created).toHaveLength(1);
    expect(result.created[0].ledger_no).toBe('EL-WM-20261012-0001');
    expect(store.generatePeriodResult.failed).toHaveLength(2);
    await flush();
    // 成功后按当前视图刷新（默认周期分组视图）
    expect(mockHttpGet.mock.calls.some(c => c[0].endsWith('/ledgers/period-groups/'))).toBe(true);
  });
});

describe('LedgerPeriodGenerateModal 预览与生成弹窗', () => {
  async function renderModal(store) {
    await act(async () => {
      ReactDOM.render(
        h(LedgerPeriodGenerateModal, {
          visible: true, ledgerType: 'week_month', store,
          onCancel: () => {},
        }), container);
    });
    await act(flush);
  }

  test('预览展示模板/系统/生成周期/期次/版本与四类判定汇总及原因', async () => {
    mockHttpGet.mockResolvedValue({data: PREVIEW_PAYLOAD});
    const store = new LedgerStore('week_month');
    await renderModal(store);
    const text = document.body.textContent; // Modal 经传送门渲染在 body 下
    // 汇总数量（后端预览口径，不编造）
    expect(text).toContain('将新建');
    expect(text).toContain('已存在跳过');
    expect(text).toContain('缺少可用版本');
    expect(text).toContain('需人工处理');
    // 条目：模板/适用系统/生成周期/期次（每周显示完整起止日期）/版本
    expect(text).toContain('信道周模板');
    expect(text).toContain('DVOR系统（SYS-3）');
    expect(text).toContain('2026-10-12 ~ 2026-10-18');
    expect(text).toContain('v2');
    // 需人工处理原因（待配置）与缺少可用版本原因如实展示
    expect(text).toContain('模板待配置：适用系统、生成周期');
    expect(text).toContain('缺少可用版本：模板尚未发布任何版本');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledgers/period-generate/',
      {params: {ledger_type: 'week_month', maintenance_cycles: ['weekly']}});
  });

  test('无可新建条目时确认按钮禁用，不发起生成请求', async () => {
    mockHttpGet.mockResolvedValue({data: {...PREVIEW_PAYLOAD,
      entries: PREVIEW_PAYLOAD.entries.map(entry => entry.status === 'create'
        ? {...entry, status: 'exists'} : entry),
      summary: {create: 0, exists: 3, no_version: 1, manual_needed: 1}}});
    const store = new LedgerStore('week_month');
    await renderModal(store);
    const ok = findButtonStarting('确认生成（');
    expect(ok.disabled).toBe(true);
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  test('确认后按后端实际结果如实展示（不以预览数量冒充）', async () => {
    mockHttpGet.mockResolvedValue({data: PREVIEW_PAYLOAD});
    mockHttpPost.mockResolvedValue({data: GENERATE_RESULT});
    const store = new LedgerStore('week_month');
    await renderModal(store);
    const ok = findButtonStarting('确认生成（');
    await act(async () => {
      ok.click();
    });
    await act(flush);
    const text = document.body.textContent; // Modal 经传送门渲染在 body 下
    // 预览口径 create=1，实际新增以生成结果为准并明示跳过/未处理
    expect(text).toContain('实际新增 1 张，已存在跳过 1 张，未处理 2 项');
    expect(text).toContain('EL-WM-20261012-0001');
    expect(text).toContain('缺少可用版本：模板尚未发布任何版本');
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledgers/period-generate/', {
        ledger_type: 'week_month', maintenance_cycles: ['weekly'], template_ids: [7]});
  });

  test('作废占用的槽位提供"补建"（2026-10-16），补建后重拉预览刷新判定', async () => {
    mockHttpGet.mockResolvedValue({data: PREVIEW_PAYLOAD});
    const store = new LedgerStore('week_month');
    await renderModal(store);
    // 待配置条目不可补建；作废占用条目提供补建按钮
    const rebuild = document.body.querySelector('[data-testid="period-rebuild"]');
    expect(rebuild).toBeTruthy();
    mockHttpPost.mockResolvedValue({data: {id: 102, ledger_no: 'EL-WM-20261012-0010'}});
    // 补建成功后重拉预览（返回已无作废占用的口径）
    mockHttpGet.mockResolvedValue({data: {...PREVIEW_PAYLOAD, entries:
      PREVIEW_PAYLOAD.entries.filter(e => !e.rebuildable),
      summary: {create: 1, exists: 1, no_version: 1, manual_needed: 1}}});
    await act(async () => {
      rebuild.click();
    });
    await act(flush);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledgers/period-generate/rebuild/', {template_id: 12});
    // 预览重拉后补建按钮消失（该槽位已重建）
    expect(document.body.querySelector('[data-testid="period-rebuild"]')).toBeNull();
  });
});

describe('两个填写列表的生成入口', () => {
  const LedgerIndex = require('../LedgerIndex').default;

  async function renderIndex(ledgerType) {
    await act(async () => {
      ReactDOM.render(
        h(LedgerIndex, {ledgerType, location: {search: ''}}), container);
    });
    await act(flush);
  }

  function findRadioInput(label) {
    const labels = Array.from(container.querySelectorAll('label.ant-radio-button-wrapper'));
    return labels.find(el => el.textContent === label);
  }

  test('周月维护列表：入口打开弹窗并按 week_month 拉取预览', async () => {
    mockHttpGet.mockImplementation(url => {
      if (url.endsWith('/ledgers/period-generate/')) {
        return Promise.resolve({data: PREVIEW_PAYLOAD});
      }
      if (url.endsWith('/ledgers/period-groups/')) return Promise.resolve(EMPTY_GROUPS);
      if (url.endsWith('/ledgers/batch-create/')) return Promise.resolve({data: []});
      return Promise.resolve({});
    });
    await renderIndex('week_month');
    const button = Array.from(container.querySelectorAll('button'))
      .find(el => el.textContent.includes('生成本期应填台账'));
    expect(button).toBeTruthy();
    await act(async () => {
      button.click();
    });
    await act(flush);
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/period-generate/'));
    expect(call[1].params.ledger_type).toBe('week_month');
    expect(document.body.textContent).toContain('生成本期应填周月维护台账');
  });

  test('季维护列表：同一入口按 seasonal 拉取预览，互不串扰', async () => {
    mockHttpGet.mockImplementation(url => {
      if (url.endsWith('/ledgers/period-generate/')) {
        return Promise.resolve({data: {...PREVIEW_PAYLOAD, ledger_type: 'seasonal'}});
      }
      if (url.endsWith('/ledgers/period-groups/')) return Promise.resolve(EMPTY_GROUPS);
      if (url.endsWith('/ledgers/batch-create/')) return Promise.resolve({data: []});
      return Promise.resolve({});
    });
    await renderIndex('seasonal');
    const button = Array.from(container.querySelectorAll('button'))
      .find(el => el.textContent.includes('生成本期应填台账'));
    await act(async () => {
      button.click();
    });
    await act(flush);
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/period-generate/'));
    expect(call[1].params.ledger_type).toBe('seasonal');
    expect(document.body.textContent).toContain('生成本期应填季维护台账');
  });

  test('按模板查看视图同样提供生成本期应填台账入口', async () => {
    await renderIndex('week_month');
    await act(async () => {
      findRadioInput('按模板查看').querySelector('input').click();
    });
    await act(flush);
    const buttons = Array.from(container.querySelectorAll('button'))
      .filter(el => el.textContent.includes('生成本期应填台账'));
    expect(buttons.length).toBe(1);
  });

  test('周期视图操作区：生成为唯一主按钮，新增/导出次级入口全部在位', async () => {
    await renderIndex('week_month');
    const buttons = Array.from(container.querySelectorAll('button'));
    // 唯一突出主操作
    const primary = buttons.filter(el => el.getAttribute('data-btn-type') === 'primary');
    expect(primary).toHaveLength(1);
    expect(primary[0].textContent).toContain('生成本期应填台账');
    // 现有操作不隐藏：手动新增 + 批量导出 PDF 均为次级默认按钮
    // （原生模板新增入口已随原生路线整体下线删除，不得再出现；
    // 明细导出 CSV 已于 2026-10-21 替换为"批量导出 PDF"入口）
    const entryOf = text => buttons.find(el => el.textContent.includes(text));
    expect(entryOf('新增周月维护台账')).toBeTruthy();
    expect(entryOf('按原生模板新增')).toBeUndefined();
    expect(entryOf('批量导出 PDF')).toBeTruthy();
    expect(entryOf('导出明细 CSV')).toBeUndefined();
    ['新增周月维护台账', '批量导出 PDF'].forEach(text => {
      expect(entryOf(text).getAttribute('data-btn-type')).toBeNull();
    });
  });
});
