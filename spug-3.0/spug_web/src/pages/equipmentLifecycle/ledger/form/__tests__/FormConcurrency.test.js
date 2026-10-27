/**
 * 数字表单台账并发防护测试（2026-10-26 审计修复 P5/P9）。
 *
 * 真实 store 行为 + 真实渲染（ReactDOM + jsdom）+ mock libs/http
 * （与 FormLedgerDetail.test.js 同风格）：
 * - P5 保存/完成并发守卫：saving/submitting 进行中重复调用
 *   saveValues/complete 直接忽略（无 HTTP 发出）；
 * - P5 按钮互斥：保存按钮在 submitting 时 disabled、完成按钮在
 *   saving 时 disabled（disabled/loading 双保险，与 Excel 路线一致）；
 * - P9 乐观锁令牌：详情顶层 version 记为基线，保存 PUT 请求体携带
 *   expected_version，成功后从响应更新；version 缺省时不带该键。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: jest.fn(),
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
  return {
    AuthDiv: Shell, AuthButton: (props) => React.createElement('button', {
      type: 'button', 'data-testid': props['data-testid'],
      disabled: props.disabled, onClick: props.onClick,
    }, props.children),
    AuthCard: Shell, AuthFragment: Shell, Breadcrumb: Shell, SearchForm: Shell,
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

const FormLedgerDetail = require('../FormLedgerDetail').default;
const {FormLedgerStore} = require('../formLedgerStore');

const FORM = {
  protocol_version: 1,
  groups: [
    {id: 'g_base', name: '基本信息', kind: 'fields', fields: [
      {id: 'f_date', name: '维护日期', type: 'date', required: true,
       description: '', unit: '', options: []},
      {id: 'f_abn', name: '外观', type: 'normal_abnormal', required: true,
       description: '', unit: '', options: []},
    ]},
  ],
};

/** 详情夹具（version 为顶层乐观锁令牌，缺省不带；id 供乱序竞态用例区分）。 */
function makeDetail(status = 'draft', values = {}, version = undefined, id = 55) {
  return {
    id, ledger_no: 'EL-WM-20261019-0001', ledger_type: 'week_month',
    status, system_name: 'ILS 系统', maintenance_period: '2026-10-19',
    created_by_name: '张三',
    completed_at: status === 'completed' ? '2026-10-21T08:00:00' : null,
    void_reason: '',
    ...(version !== undefined ? {version} : {}),
    form: {
      record_id: 9, values, editable: status === 'draft', voided: status === 'void',
      version: {id: 3, version_no: 2, template_name: '周维护数字表单', form: FORM},
    },
  };
}

function createDraftStore(version = undefined) {
  const store = new FormLedgerStore();
  store.applyDetail({data: makeDetail('draft', {}, version)});
  return store;
}

function renderDetail(store) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  ReactDOM.render(h(FormLedgerDetail, {store, onBack: jest.fn()}), container);
  return {container, cleanup: () => {
    ReactDOM.unmountComponentAtNode(container);
    document.querySelectorAll('.ant-modal-confirm, .ant-modal-root')
      .forEach(node => node.remove());
    container.remove();
  }};
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

beforeEach(() => {
  [mockHttpGet, mockHttpPost, mockHttpPut].forEach(fn => fn.mockReset());
});

// ===== P5：保存/完成并发守卫（store 层） =====

describe('FormLedgerStore 保存/完成并发守卫', () => {
  test('saving 进行中：saveValues/complete 直接忽略（无 HTTP 发出）', async () => {
    const store = createDraftStore();
    store.edit('field', 'f_date', '2026-10-26');
    expect(store.valuesDirty).toBe(true);
    store.saving = true;
    await store.saveValues();
    await store.complete();
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  test('submitting 进行中：saveValues/complete 直接忽略（无 HTTP 发出）', async () => {
    const store = createDraftStore();
    store.edit('field', 'f_date', '2026-10-26');
    store.submitting = true;
    await store.saveValues();
    await store.complete();
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  test('完成中重复调用忽略（complete 只发一次完成请求）', async () => {
    const store = createDraftStore();
    let resolvePost;
    mockHttpPost.mockImplementation(() => new Promise(resolve => {
      resolvePost = resolve;
    }));
    const first = store.complete();
    await act(async () => { await flush(); });
    await store.complete();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    resolvePost({data: makeDetail('completed')});
    await act(async () => { await first; });
    expect(store.detail.status).toBe('completed');
  });
});

// ===== P5：保存/完成按钮互斥（组件层） =====

describe('FormLedgerDetail 保存/完成按钮互斥', () => {
  test('submitting 时保存按钮 disabled；saving 时完成按钮 disabled', async () => {
    const store = createDraftStore();
    const view = renderDetail(store);
    const saveBtn = document.querySelector('[data-testid="form-save-draft"]');
    const completeBtn = document.querySelector('[data-testid="form-complete"]');
    expect(saveBtn.disabled).toBe(false);
    expect(completeBtn.disabled).toBe(false);
    // 完成进行中：保存按钮被互斥禁用
    await act(async () => { store.submitting = true; });
    expect(document.querySelector('[data-testid="form-save-draft"]').disabled).toBe(true);
    // 保存进行中：完成按钮被互斥禁用
    await act(async () => { store.submitting = false; store.saving = true; });
    expect(document.querySelector('[data-testid="form-complete"]').disabled).toBe(true);
    // 恢复后两按钮均可用
    await act(async () => { store.saving = false; });
    expect(document.querySelector('[data-testid="form-save-draft"]').disabled).toBe(false);
    expect(document.querySelector('[data-testid="form-complete"]').disabled).toBe(false);
    view.cleanup();
  });
});

// ===== P9：乐观锁令牌 expected_version =====

describe('FormLedgerStore 乐观锁令牌 expected_version', () => {
  test('详情 version 记基线：保存 PUT 携带 expected_version，成功后更新为响应 version', async () => {
    const store = createDraftStore(5);
    store.edit('field', 'f_date', '2026-10-26');
    mockHttpPut.mockResolvedValue({data: makeDetail(
      'draft', {f_date: '2026-10-26'}, 6)});
    await act(async () => { await store.saveValues(); });
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/form-ledgers/55/', {
      values: expect.objectContaining({f_date: '2026-10-26'}),
      expected_version: 5,
    });
    expect(store.savedVersion).toBe(6);
  });

  test('详情无 version（旧后端/mock）时保存请求体不带 expected_version 键', async () => {
    const store = createDraftStore();
    store.edit('field', 'f_date', '2026-10-26');
    mockHttpPut.mockResolvedValue({data: makeDetail('draft', {f_date: '2026-10-26'})});
    await act(async () => { await store.saveValues(); });
    const body = mockHttpPut.mock.calls[0][1];
    expect('expected_version' in body).toBe(false);
  });
});

// ===== 二轮复核（2026-10-26）：详情导航竞态守卫 + 完成在途填写区锁定 =====

describe('FormLedgerStore 详情请求竞态守卫', () => {
  test('乱序响应丢弃：后到的旧详情不覆盖新详情（保存不会发往错误 id）', async () => {
    const store = new FormLedgerStore();
    let resolveA;
    let resolveB;
    mockHttpGet
      .mockImplementationOnce(() => new Promise(resolve => { resolveA = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveB = resolve; }));
    const first = store.fetchDetail(1);
    await act(async () => { await flush(); });
    const second = store.fetchDetail(2);
    await act(async () => { await flush(); });
    // B 先落地：detail 为最新请求的 2 号台账
    resolveB({data: makeDetail('draft', {}, 3, 2)});
    await act(async () => { await second; });
    expect(store.detail.id).toBe(2);
    // A 响应后到：被序列守卫整体丢弃
    resolveA({data: makeDetail('draft', {}, 1, 1)});
    await act(async () => { await first; });
    expect(store.detail.id).toBe(2);
    expect(store.loading).toBe(false);
  });

  test('返回列表（applyDetail(null)）后旧详情响应落地不重新打开详情', async () => {
    const store = new FormLedgerStore();
    let resolveA;
    mockHttpGet.mockImplementationOnce(
      () => new Promise(resolve => { resolveA = resolve; }));
    const first = store.fetchDetail(55);
    await act(async () => { await flush(); });
    store.applyDetail(null);
    expect(store.detail).toBe(null);
    // 在途响应此时才落地：必须被丢弃，不得把已退出的台账重新打开
    resolveA({data: makeDetail('draft')});
    await act(async () => { await first; });
    expect(store.detail).toBe(null);
    expect(store.loading).toBe(false);
  });
});

describe('FormLedgerStore 完成在途填写区锁定（fillEditable）', () => {
  test('submitting 时 fillEditable=false；普通保存期间仍可编辑', () => {
    const store = createDraftStore(3);
    expect(store.fillEditable).toBe(true);
    // 普通保存不重置编辑副本，保存期间仍可继续输入
    store.saving = true;
    expect(store.fillEditable).toBe(true);
    store.saving = false;
    // 完成在途：响应落地会以服务端详情整体重置 values，必须先锁定
    store.submitting = true;
    expect(store.fillEditable).toBe(false);
    store.submitting = false;
    expect(store.fillEditable).toBe(true);
  });

  test('完成在途：填写控件渲染为禁用（在途输入不会被完成响应丢弃）', async () => {
    const store = createDraftStore(3);
    const view = renderDetail(store);
    // normal_abnormal 字段渲染 Radio.Button 组（disabled 透传到内部 input）
    const radioInput = document.querySelector('.ant-radio-button-wrapper input');
    expect(radioInput).not.toBe(null);
    expect(radioInput.disabled).toBe(false);
    await act(async () => { store.submitting = true; });
    expect(document.querySelector('.ant-radio-button-wrapper input').disabled)
      .toBe(true);
    view.cleanup();
  });
});

// ===== 三轮复核（2026-10-26）：保存在途返回列表——写响应按 id 守卫丢弃 =====

describe('FormLedgerStore 保存在途返回列表（响应丢弃）', () => {
  test('保存 PUT 在途时返回列表：响应落地不重新打开详情，基线/令牌不回写', async () => {
    const store = createDraftStore(5);
    store.edit('field', 'f_date', '2026-10-26');
    let resolvePut;
    mockHttpPut.mockImplementationOnce(
      () => new Promise(resolve => { resolvePut = resolve; }));
    const saving = store.saveValues();
    await act(async () => { await flush(); });
    store.applyDetail(null);
    resolvePut({data: makeDetail('draft', {'f_date': '2026-10-26'}, 6)});
    await act(async () => { await saving; });
    expect(store.detail).toBe(null);
    expect(store.savedVersion).toBe(undefined);
    expect(store.saving).toBe(false);
  });

  test('完成内层保存在途返回列表：完成请求不再发出', async () => {
    const store = createDraftStore(5);
    store.edit('field', 'f_date', '2026-10-26');
    let resolvePut;
    mockHttpPut.mockImplementationOnce(
      () => new Promise(resolve => { resolvePut = resolve; }));
    const completing = store.complete();
    await act(async () => { await flush(); });
    store.applyDetail(null);
    resolvePut({data: makeDetail('draft', {'f_date': '2026-10-26'}, 6)});
    await act(async () => { await completing; });
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(store.detail).toBe(null);
    expect(store.submitting).toBe(false);
  });

  test('完成请求在途返回列表：完成响应不重新打开详情', async () => {
    const store = createDraftStore(5);
    let resolvePost;
    mockHttpPost.mockImplementationOnce(
      () => new Promise(resolve => { resolvePost = resolve; }));
    const completing = store.complete();
    await act(async () => { await flush(); });
    store.applyDetail(null);
    resolvePost({data: makeDetail('completed', {}, 6)});
    await act(async () => { await completing; });
    expect(store.detail).toBe(null);
    expect(store.submitting).toBe(false);
  });
});
