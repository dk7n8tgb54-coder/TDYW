/**
 * Excel 台账并发防护测试（2026-10-26 审计修复 P6/P7/P8/P9）。
 *
 * 真实 store 行为 + mock libs/http（与 ExcelSaveSubmit.test.js 同风格）：
 * - P7 翻阅竞态：fetchDetail 序列守卫——乱序返回的旧响应整体丢弃，
 *   落地的始终是最新一次请求的台账（否则后续保存 PUT 会发往错误 id）；
 * - P6 保存不回滚在途输入：PUT 在途期间新输入的单元格值在响应到达后
 *   保留且如实显示未保存；已保存部分更新基线不再算脏；
 * - P8 提交更正防重：保存中/提交中/更正提交中重复 submitCorrection
 *   直接忽略（不发请求）；
 * - P9 乐观锁令牌：详情顶层 version 记为基线，保存/更正请求体携带
 *   expected_version，成功后从响应更新；version 缺省时不带该键。
 */
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: jest.fn()},
  exportFile: jest.fn(),
  history: {location: {search: ''}, replace: jest.fn(), push: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const {ExcelLedgerStore} = require('../excelLedgerStore');

const FIELD_PS = 'aaaaaaaa-1111-4aaa-8aaa-000000000001';
const FIELD_REMARK = 'aaaaaaaa-1111-4aaa-8aaa-000000000002';

const SHEET = {
  name: '信道维护记录', max_row: 4, max_column: 8, merged_ranges: [],
  row_heights: {}, column_widths: {},
  cells: {A1: {v: '信道维护记录表'}, C3: {v: ''}, H3: {v: ''}},
};

const BINDINGS = [
  {field_id: FIELD_PS, sheet_name: '信道维护记录', cell_coordinate: 'C3',
   field_name: 'PS模块', input_type: 'status', is_required: true,
   unit: '', options: ['正常', '异常']},
  {field_id: FIELD_REMARK, sheet_name: '信道维护记录', cell_coordinate: 'H3',
   field_name: '备注', input_type: 'text', is_required: false,
   unit: '', options: []},
];

/** 详情夹具（version 为顶层乐观锁令牌；excel.version 为模板版本快照）。 */
function makeDetail(overrides = {}) {
  const {
    id = 66, status = 'draft', values = {}, editable = status === 'draft',
    version = undefined, ...rest
  } = overrides;
  return {
    id, ledger_no: `EL-WM-20261015-0${id}`, ledger_type: 'week_month',
    status, created_from: 'excel_template',
    ...(version !== undefined ? {version} : {}),
    excel: {
      record_id: 9, values, editable,
      version: {
        id: 5, version_no: 1, template_name: '信道Excel维护台账',
        ledger_type: 'week_month', source_filename: 'channel.xlsx',
        source_hash: 'a'.repeat(64), field_count: 2,
        published_at: '2026-10-15 09:00:00',
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [SHEET]},
        bindings: BINDINGS,
      },
    },
    ...rest,
  };
}

const flush = async () => {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
};

beforeEach(() => {
  [mockHttpGet, mockHttpPost, mockHttpPut].forEach(fn => fn.mockReset());
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ===== P7：fetchDetail 翻阅竞态守卫 =====

describe('ExcelLedgerStore fetchDetail 翻阅竞态守卫', () => {
  test('乱序响应丢弃：后到的旧响应不落地，最终 detail 为最新请求的台账', async () => {
    const store = new ExcelLedgerStore();
    let resolveA;
    let resolveB;
    mockHttpGet.mockImplementation(url => url.includes('/77/')
      ? new Promise(resolve => { resolveA = resolve; })
      : new Promise(resolve => { resolveB = resolve; }));
    const first = store.fetchDetail(77);
    await flush();
    const second = store.fetchDetail(88);
    await flush();
    // A 响应后到：被序列守卫丢弃，不得把详情覆盖成 77 号台账
    resolveA({data: makeDetail({id: 77})});
    await act(async () => { await first; });
    expect(store.detail).toBe(null);
    // B 响应落地：detail 为最新请求的 88 号台账，loading 复位
    resolveB({data: makeDetail({id: 88})});
    await act(async () => { await second; });
    expect(store.detail.id).toBe(88);
    expect(store.loading).toBe(false);
  });

  test('单次详情请求不受守卫影响（正常落地并返回详情）', async () => {
    mockHttpGet.mockResolvedValue({data: makeDetail({id: 66})});
    const store = new ExcelLedgerStore();
    const detail = await store.fetchDetail(66);
    expect(detail.id).toBe(66);
    expect(store.detail.id).toBe(66);
    expect(store.loading).toBe(false);
  });
});

// ===== P6：保存不回滚在途输入 =====

describe('ExcelLedgerStore 保存不回滚在途输入', () => {
  test('PUT 在途期间的新输入在响应到达后保留；已保存部分更新基线不再算脏', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({version: 5})});
    store.setValue(FIELD_PS, '正常');
    let resolvePut;
    mockHttpPut.mockImplementation(() => new Promise(resolve => {
      resolvePut = resolve;
    }));
    const saving = store.saveValues();
    await flush();
    // 保存请求在途时用户继续输入另一单元格
    store.setValue(FIELD_REMARK, '在途输入');
    resolvePut({data: makeDetail({version: 6, values: {[FIELD_PS]: '正常'}})});
    await act(async () => { await saving; });
    // 在途新输入不被保存响应重置；已保存部分保留
    expect(store.values[FIELD_PS]).toBe('正常');
    expect(store.values[FIELD_REMARK]).toBe('在途输入');
    // 新输入仍未保存（dirty 为真）；保存基线 = 服务端响应值
    expect(store.valuesDirty).toBe(true);
    expect(store.savedValues).toEqual({[FIELD_PS]: '正常'});
    // 在途输入回退（清空）后：已保存部分不再算脏
    store.setValue(FIELD_REMARK, '');
    expect(store.valuesDirty).toBe(false);
  });
});

// ===== P8：提交更正防重 =====

describe('ExcelLedgerStore 提交更正防重', () => {
  test('保存中/提交中时 submitCorrection 直接忽略（不发请求）', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({
      status: 'completed', editable: false, values: {[FIELD_PS]: '正常'}})});
    store.startCorrection('登记时选错模块');
    store.setValue(FIELD_PS, '异常');
    store.saving = true;
    await store.submitCorrection();
    store.saving = false;
    store.submitting = true;
    await store.submitCorrection();
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  test('更正提交中重复调用忽略（correcting 保持且只发一次）', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({
      status: 'completed', editable: false, values: {[FIELD_PS]: '正常'}})});
    store.startCorrection('登记时选错模块');
    store.setValue(FIELD_PS, '异常');
    let resolvePost;
    mockHttpPost.mockImplementation(() => new Promise(resolve => {
      resolvePost = resolve;
    }));
    const first = store.submitCorrection();
    await flush();
    await store.submitCorrection();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    resolvePost({data: makeDetail({
      status: 'completed', editable: false, values: {[FIELD_PS]: '异常'}})});
    await act(async () => { await first; });
    expect(store.correcting).toBe(false);
  });
});

// ===== P9：乐观锁令牌 expected_version =====

describe('ExcelLedgerStore 乐观锁令牌 expected_version', () => {
  test('保存 PUT 携带详情 version；成功后基线更新为响应 version', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({version: 5})});
    store.setValue(FIELD_PS, '正常');
    mockHttpPut.mockResolvedValue({data: makeDetail({
      version: 6, values: {[FIELD_PS]: '正常'}})});
    await act(async () => { await store.saveValues(); });
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/66/', {
      values: {[FIELD_PS]: '正常'},
      expected_version: 5,
    });
    expect(store.savedVersion).toBe(6);
  });

  test('详情无 version（旧后端/mock）时保存请求体不带 expected_version 键', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail()});
    store.setValue(FIELD_PS, '正常');
    mockHttpPut.mockResolvedValue({data: makeDetail({values: {[FIELD_PS]: '正常'}})});
    await act(async () => { await store.saveValues(); });
    const body = mockHttpPut.mock.calls[0][1];
    expect('expected_version' in body).toBe(false);
  });

  test('提交更正携带 expected_version；成功后基线更新为响应 version', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({
      status: 'completed', editable: false,
      version: 4, values: {[FIELD_PS]: '正常'}})});
    store.startCorrection('登记时选错模块');
    store.setValue(FIELD_PS, '异常');
    mockHttpPost.mockResolvedValue({data: makeDetail({
      status: 'completed', editable: false, version: 5,
      values: {[FIELD_PS]: '异常'}})});
    await act(async () => { await store.submitCorrection(); });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/66/correct/', {
        reason: '登记时选错模块',
        values: {[FIELD_PS]: '异常'},
        expected_version: 4,
      });
    expect(store.savedVersion).toBe(5);
  });
});

// ===== 二轮复核（2026-10-26）：返回列表失效在途详情 + 完成在途编辑锁定 =====

describe('ExcelLedgerStore 返回列表使在途详情请求失效', () => {
  test('applyDetail(null) 后旧详情响应落地不重新打开详情', async () => {
    const store = new ExcelLedgerStore();
    let resolveA;
    mockHttpGet.mockImplementationOnce(
      () => new Promise(resolve => { resolveA = resolve; }));
    const first = store.fetchDetail(77);
    await flush();
    // 用户在响应到达前返回列表（详情关闭）
    store.applyDetail(null);
    expect(store.detail).toBe(null);
    // 在途响应此时才落地：必须被丢弃，不得把已退出的台账重新打开
    resolveA({data: makeDetail({id: 77})});
    await act(async () => { await first; });
    expect(store.detail).toBe(null);
    expect(store.loading).toBe(false);
  });

  test('关闭详情后再打开新台账不受失效标记影响（序列号单调递增）', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail(null);
    mockHttpGet.mockResolvedValueOnce({data: makeDetail({id: 88})});
    const detail = await store.fetchDetail(88);
    expect(detail.id).toBe(88);
    expect(store.loading).toBe(false);
  });
});

describe('ExcelLedgerStore 完成在途填写区锁定（fillEditable）', () => {
  test('完成/更正提交在途锁定填写区；普通保存期间仍可编辑', () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({version: 5})});
    expect(store.fillEditable).toBe(true);
    // 普通保存不重置编辑副本，保存期间仍可继续输入（P6 语义保持）
    store.saving = true;
    expect(store.fillEditable).toBe(true);
    store.saving = false;
    // 完成在途：响应落地会以服务端详情整体重置 values，必须先锁定
    store.submitting = true;
    expect(store.fillEditable).toBe(false);
    store.submitting = false;
    // 更正提交在途（correcting && saving）同样锁定
    store.startCorrection('笔误更正');
    store.saving = true;
    expect(store.fillEditable).toBe(false);
    store.saving = false;
    store.cancelCorrection();
    expect(store.fillEditable).toBe(true);
  });
});

// ===== 三轮复核（2026-10-26）：保存在途返回列表——写响应按 id 守卫丢弃 =====

describe('ExcelLedgerStore 保存在途返回列表（响应丢弃）', () => {
  test('保存 PUT 在途时返回列表：响应落地不重新打开详情，基线/令牌不回写', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({version: 5})});
    store.setValue(FIELD_PS, '异常');
    let resolvePut;
    mockHttpPut.mockImplementationOnce(
      () => new Promise(resolve => { resolvePut = resolve; }));
    const saving = store.saveValues();
    await flush();
    store.applyDetail(null);
    resolvePut({data: makeDetail({id: 66, version: 6, values: {[FIELD_PS]: '异常'}})});
    await act(async () => { await saving; });
    expect(store.detail).toBe(null);
    expect(store.savedVersion).toBe(undefined);
    expect(store.saving).toBe(false);
  });

  test('保存 PUT 在途时切换到另一张台账：旧响应不覆盖新详情', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({id: 66, version: 5})});
    store.setValue(FIELD_PS, '异常');
    let resolvePut;
    mockHttpPut.mockImplementationOnce(
      () => new Promise(resolve => { resolvePut = resolve; }));
    const saving = store.saveValues();
    await flush();
    // 返回列表后打开 88 号台账（fetchDetail 正常落地）
    mockHttpGet.mockResolvedValueOnce({data: makeDetail({id: 88})});
    await store.fetchDetail(88);
    resolvePut({data: makeDetail({id: 66, version: 6})});
    await act(async () => { await saving; });
    expect(store.detail.id).toBe(88);
  });

  test('完成内层保存在途返回列表：完成请求不再发出', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({version: 5})});
    store.setValue(FIELD_PS, '异常');
    let resolvePut;
    mockHttpPut.mockImplementationOnce(
      () => new Promise(resolve => { resolvePut = resolve; }));
    const completing = store.complete();
    await flush();
    store.applyDetail(null);
    resolvePut({data: makeDetail({version: 6, values: {[FIELD_PS]: '异常'}})});
    await act(async () => { await completing; });
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(store.detail).toBe(null);
    expect(store.submitting).toBe(false);
  });

  test('完成请求在途返回列表：完成响应不重新打开详情', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({version: 5})});
    let resolvePost;
    mockHttpPost.mockImplementationOnce(
      () => new Promise(resolve => { resolvePost = resolve; }));
    const completing = store.complete();
    await flush();
    store.applyDetail(null);
    resolvePost({data: makeDetail({status: 'completed', editable: false, version: 6})});
    await act(async () => { await completing; });
    expect(store.detail).toBe(null);
    expect(store.submitting).toBe(false);
  });
});
