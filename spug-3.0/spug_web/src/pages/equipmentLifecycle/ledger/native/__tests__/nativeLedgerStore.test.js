/**
 * 原生路线维护台账 Store 行为测试（真实 store + http mock）。
 *
 * 覆盖：
 * - 详情应用与脏值跟踪（values vs savedValues）；
 * - 创建（client_token 幂等走后端，前端只发请求）；
 * - 保存：编辑器 collect 值合并 → PUT（values/header 形态），成功后通知
 *   编辑器复位；无未保存修改不发请求；
 * - 完成填写：先保存再 POST complete；必填本地预检 requiredMissing；
 * - 更正：进入/取消/提交（reason + values + header 形态）；
 * - 作废沿用既有 /ledgers 端点、删除走 /ledgers DELETE、导出 PDF POST。
 */
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: mockHttpDelete},
  exportFile: jest.fn(),
  history: {location: {search: ''}, replace: jest.fn(), push: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

const {NativeLedgerStore, API, LEDGER_API} = require('../nativeLedgerStore');

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const VERSION = {
  id: 5, version_no: 1, template_name: '原生测试模板', ledger_type: 'week_month',
  field_count: 2,
  snapshot: {sheets: {ledger: {cellData: {}}}},
  bindings: [
    {id: 'b1', key: 'conclusion', label: '维护结论', section: '结论', range: 'B2',
      type: 'text', placeholder: '', is_required: true},
    {id: 'b2', key: 'note', label: '备注', section: '结论', range: 'B3',
      type: 'textarea', placeholder: '', is_required: false},
  ],
  paper: {size: 'A4', orientation: 'landscape', fitToWidth: true,
    margins: {top: 12, right: 10, bottom: 12, left: 10}},
};

function makeDetail(overrides = {}) {
  const {status = 'draft', values = {}, editable = status === 'draft',
    corrections = [], ...rest} = overrides;
  return {
    id: 66,
    ledger_no: 'EL-WM-20261018-001',
    ledger_type: 'week_month',
    status,
    corrections,
    native: {record_id: 9, values, editable, voided: status === 'void', version: VERSION},
    ...rest,
  };
}

function setupStore() {
  const store = new NativeLedgerStore();
  jest.clearAllMocks();
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
  return store;
}

function restoreMessage() {
  message.success.mockRestore();
  message.warning.mockRestore();
  message.error.mockRestore();
}

describe('NativeLedgerStore 脏值跟踪与保存', () => {
  let store;

  beforeEach(() => {
    store = setupStore();
  });

  afterEach(restoreMessage);

  test('applyDetail 建立脏值基线；编辑推送后 valuesDirty 判定', () => {
    store.applyDetail(makeDetail({values: {conclusion: 'A', note: ''}}));
    expect(store.editable).toBe(true);
    expect(store.valuesDirty).toBe(false);
    store.applyEditorValues({values: {conclusion: 'A2', note: ''}});
    store.values = {...store.values, ...store.editorValues};
    expect(store.valuesDirty).toBe(true);
    store.values = {...store.values, conclusion: 'A'};
    expect(store.valuesDirty).toBe(false);
  });

  test('hasUnsaved：仅草稿/更正模式参与', () => {
    store.applyDetail(makeDetail({status: 'completed', editable: false}));
    store.values = {...store.values, conclusion: '改了'};
    expect(store.hasUnsaved).toBe(false);
  });

  test('saveValues：合并编辑器 collect 值后 PUT，成功通知编辑器', async () => {
    store.applyDetail(makeDetail({values: {conclusion: '', note: ''}}));
    mockHttpPut.mockResolvedValue({data: makeDetail({values: {conclusion: 'OK', note: ''}})});
    const notifySaved = jest.fn();
    const collect = jest.fn().mockResolvedValue({values: {conclusion: 'OK', note: ''}});
    await store.saveValues(collect, notifySaved);
    await flush();
    expect(mockHttpPut).toHaveBeenCalledWith(`${API}/66/`, {
      values: {conclusion: 'OK', note: ''},
      header: undefined,
    });
    expect(notifySaved).toHaveBeenCalled();
    expect(store.detail.status).toBe('draft');
    expect(message.success).toHaveBeenCalledWith('填写值已保存');
  });

  test('saveValues：collect 失败时用最近推送值继续保存', async () => {
    store.applyDetail(makeDetail({values: {conclusion: '', note: ''}}));
    store.applyEditorValues({values: {conclusion: '推送值', note: ''}});
    mockHttpPut.mockResolvedValue({data: makeDetail({})});
    const collect = jest.fn().mockRejectedValue(new Error('编辑器未就绪'));
    await store.saveValues(collect, null);
    await flush();
    expect(mockHttpPut).toHaveBeenCalledWith(`${API}/66/`, {
      values: {conclusion: '推送值', note: ''},
      header: undefined,
    });
  });

  test('saveValues：无未保存修改不发请求', async () => {
    store.applyDetail(makeDetail({values: {conclusion: 'A', note: 'B'}}));
    await store.saveValues(null, null);
    await flush();
    expect(mockHttpPut).not.toHaveBeenCalled();
  });

  test('saveValues：保存中重复调用忽略', async () => {
    store.applyDetail(makeDetail({values: {conclusion: '', note: ''}}));
    store.saving = true;
    await store.saveValues(null, null);
    await flush();
    expect(mockHttpPut).not.toHaveBeenCalled();
    store.saving = false;
  });
});

describe('NativeLedgerStore 完成/更正/状态流转', () => {
  let store;

  beforeEach(() => {
    store = setupStore();
  });

  afterEach(restoreMessage);

  test('complete：先保存未保存修改再 POST complete，成功后复位', async () => {
    store.applyDetail(makeDetail({values: {conclusion: '', note: ''}}));
    mockHttpPut.mockResolvedValue({data: makeDetail({values: {conclusion: '好', note: ''}})});
    mockHttpPost.mockResolvedValue({data: makeDetail({status: 'completed', editable: false})});
    const collect = jest.fn().mockResolvedValue({values: {conclusion: '好', note: ''}});
    const notifySaved = jest.fn();
    await store.complete(collect, notifySaved);
    await flush();
    expect(mockHttpPut).toHaveBeenCalled();
    expect(mockHttpPost).toHaveBeenCalledWith(`${API}/66/complete/`);
    expect(notifySaved).toHaveBeenCalled();
    expect(message.success).toHaveBeenCalledWith('已完成填写');
  });

  test('requiredMissing：必填未填返回字段名', () => {
    store.applyDetail(makeDetail({values: {conclusion: '', note: 'x'}}));
    expect(store.requiredMissing()).toEqual(['维护结论']);
    store.values = {...store.values, conclusion: '有值'};
    expect(store.requiredMissing()).toEqual([]);
  });

  test('submitCorrection：reason + values + header 整体提交', async () => {
    store.applyDetail(makeDetail({
      status: 'completed', editable: false,
      values: {conclusion: '原值', note: ''},
      corrections: [],
    }));
    store.startCorrection('复核修正');
    expect(store.correctingEditable).toBe(true);
    const collect = jest.fn().mockResolvedValue({values: {conclusion: '修正值', note: ''}});
    mockHttpPost.mockResolvedValue({data: makeDetail({})});
    await store.submitCorrection(collect);
    await flush();
    expect(mockHttpPost).toHaveBeenCalledWith(`${API}/66/correct/`, {
      reason: '复核修正',
      values: {conclusion: '修正值', note: ''},
    });
    expect(message.success).toHaveBeenCalledWith('更正已保存');
    // 更正模式随详情刷新退出
    expect(store.correcting).toBe(false);
  });

  test('cancelCorrection 恢复服务端值', () => {
    store.applyDetail(makeDetail({values: {conclusion: '原值', note: ''}}));
    store.startCorrection('r');
    store.values = {...store.values, conclusion: '改了'};
    store.cancelCorrection();
    expect(store.values.conclusion).toBe('原值');
    expect(store.correcting).toBe(false);
  });

  test('voidLedger 走既有 /ledgers 端点并重取详情', async () => {
    store.applyDetail(makeDetail({status: 'completed', editable: false}));
    mockHttpPost.mockResolvedValueOnce({data: {}})
      .mockResolvedValueOnce({data: makeDetail({status: 'void', editable: false})});
    await store.voidLedger('录入错误');
    await flush();
    expect(mockHttpPost).toHaveBeenCalledWith(`${LEDGER_API}/66/void/`, {reason: '录入错误'});
    expect(mockHttpGet).toHaveBeenCalledWith(`${API}/66/`);
    expect(message.success).toHaveBeenCalledWith('已作废');
  });

  test('deleteLedger 走既有 /ledgers DELETE', async () => {
    store.applyDetail(makeDetail());
    mockHttpDelete.mockResolvedValue({});
    await store.deleteLedger();
    await flush();
    expect(mockHttpDelete).toHaveBeenCalledWith(`${LEDGER_API}/66/`);
  });

  test('exportPdf POST 二进制下载（exportFile 承载）', () => {
    const {exportFile} = require('libs');
    store.applyDetail(makeDetail());
    store.exportPdf();
    expect(exportFile).toHaveBeenCalledWith(expect.objectContaining({
      url: `${API}/66/export/pdf/`,
      method: 'post',
    }));
  });
});
