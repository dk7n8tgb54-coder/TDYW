/**
 * Excel 台账"完成填写"改版测试（2026-10-16 流程简化）。
 *
 * 覆盖（真实 store 行为 + jsdom 组件交互 + http mock）：
 * - 脏值跟踪：填写值快照比对、执行日期草稿（undefined=未动/''=显式清空）；
 * - 完成填写（流程终点）：先 PUT 保存未保存修改再 POST 完成
 *   （草稿 → 已完成），成功提示只出现一次；任一步失败不显示完成成功、
 *   不丢弃页面内容；完成中重复调用忽略；
 * - 更正模式：已完成台账进入更正（须填原因）后可修改，提交更正走
 *   /correct/ 并以服务端详情为准；取消更正恢复服务端值；
 * - 组件：草稿提供"保存草稿 + 完成填写"，旧流程历史状态只读（含删除），
 *   已完成提供"更正"；返回列表未保存确认（继续填写保留内容 /
 *   放弃修改并返回）；执行日期草稿保存请求形态。
 */
import React from 'react';
import ReactDOM from 'react-dom';
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
const ExcelLedgerDetail = require('../ExcelLedgerDetail').default;

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

function makeDetail(overrides = {}) {
  const {
    status = 'draft', values = {}, editable = status === 'draft',
    executed_date = null, ...rest
  } = overrides;
  return {
    id: 66,
    ledger_no: 'EL-WM-20261015-001',
    ledger_type: 'week_month',
    executed_date,
    status,
    created_from: 'excel_template',
    excel: {
      record_id: 9,
      values,
      editable,
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

function removeModals() {
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask')
    .forEach(node => node.remove());
}

function buttonByText(text, root) {
  const scope = root || document.body;
  return Array.from(scope.querySelectorAll('button'))
    .find(node => node.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
}

beforeEach(() => {
  [mockHttpGet, mockHttpPost, mockHttpPut].forEach(fn => fn.mockReset());
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
});

afterEach(() => {
  removeModals();
  jest.restoreAllMocks();
});

// ===== Store：脏值跟踪 =====

describe('ExcelLedgerStore 未保存状态跟踪', () => {
  test('详情初载无未保存；修改填写值后 valuesDirty，改回后复原', () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({values: {[FIELD_PS]: '正常'}})});
    expect(store.hasUnsaved).toBe(false);
    store.setValue(FIELD_REMARK, '备注内容');
    expect(store.valuesDirty).toBe(true);
    expect(store.hasUnsaved).toBe(true);
    store.setValue(FIELD_REMARK, '');
    expect(store.valuesDirty).toBe(false);
    expect(store.hasUnsaved).toBe(false);
  });

  test('清空已填值算未保存；键序不同不影响比对', () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({values: {[FIELD_PS]: '正常', [FIELD_REMARK]: 'ok'}})});
    store.setValue(FIELD_PS, '');
    expect(store.valuesDirty).toBe(true);
    store.setValue(FIELD_PS, '正常');
    expect(store.valuesDirty).toBe(false);
  });

  test('执行日期草稿：未动不脏；改期/清空已录日期为脏；清空空日期不脏', () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({executed_date: '2026-10-16'})});
    store.setDateDraft('2026-10-17');
    expect(store.dateDirty).toBe(true);
    store.setDateDraft('2026-10-16');
    expect(store.dateDirty).toBe(false);
    store.setDateDraft('');
    expect(store.dateDirty).toBe(true);
    store.setDateDraft(undefined);
    expect(store.dateDirty).toBe(false);
    // 已录日期为空的台账：显式清空（''）等同未动
    store.applyDetail({data: makeDetail({executed_date: null})});
    store.setDateDraft('');
    expect(store.dateDirty).toBe(false);
    store.setDateDraft('2026-10-18');
    expect(store.dateDirty).toBe(true);
  });

  test('不可编辑状态（已完成等）恒无未保存', () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({status: 'completed', editable: false})});
    store.setValue(FIELD_PS, '正常');
    store.setDateDraft('2026-10-18');
    expect(store.hasUnsaved).toBe(false);
  });
});

// ===== Store：完成填写（流程终点） =====

describe('ExcelLedgerStore 完成填写', () => {
  test('有未保存修改：先 PUT 保存（含日期）再 POST 完成，成功提示只出现一次', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail()});
    store.setValue(FIELD_PS, '正常');
    store.setDateDraft('2026-10-16');
    mockHttpPut.mockResolvedValue({data: makeDetail({
      values: {[FIELD_PS]: '正常'}, executed_date: '2026-10-16'})});
    mockHttpPost.mockResolvedValue({data: makeDetail({
      status: 'completed', values: {[FIELD_PS]: '正常'},
      executed_date: '2026-10-16', editable: false})});
    await act(async () => {
      await store.complete();
    });
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/66/', {
      values: {[FIELD_PS]: '正常'},
      header: {executed_date: '2026-10-16'},
    });
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/66/complete/');
    // 只出现一次完成成功提示，不出现保存成功提示
    expect(message.success).toHaveBeenCalledTimes(1);
    expect(message.success).toHaveBeenCalledWith('已完成填写');
    expect(store.detail.status).toBe('completed');
    expect(store.hasUnsaved).toBe(false);
  });

  test('保存失败：不发起完成、不显示完成成功、页面内容不丢弃', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail()});
    store.setValue(FIELD_PS, '正常');
    store.setDateDraft('2026-10-16');
    mockHttpPut.mockRejectedValue(new Error('network down'));
    await act(async () => {
      await store.complete().catch(() => {});
    });
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(message.success).not.toHaveBeenCalled();
    // 填写值与日期草稿原样保留，可继续编辑重试
    expect(store.values[FIELD_PS]).toBe('正常');
    expect(store.dateDraft).toBe('2026-10-16');
    expect(store.hasUnsaved).toBe(true);
  });

  test('完成失败：不显示完成成功，已保存内容保留（保存步骤不回滚）', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail()});
    store.setValue(FIELD_PS, '正常');
    mockHttpPut.mockResolvedValue({data: makeDetail({values: {[FIELD_PS]: '正常'}})});
    mockHttpPost.mockRejectedValue(new Error('backend rejected'));
    await act(async () => {
      await store.complete().catch(() => {});
    });
    expect(message.success).not.toHaveBeenCalled();
    expect(store.detail.status).toBe('draft');
    // 填写值已保存成功（保存与完成是两步，保存结果不因完成失败丢弃）
    expect(store.values[FIELD_PS]).toBe('正常');
    expect(store.hasUnsaved).toBe(false);
  });

  test('完成中重复调用忽略（防重复点击/并发处理）', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({values: {[FIELD_PS]: '正常'}})});
    let resolvePost;
    mockHttpPost.mockImplementation(() => new Promise(resolve => {
      resolvePost = resolve;
    }));
    const first = store.complete();
    await flush();
    store.complete();
    await flush();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    resolvePost({data: makeDetail({status: 'completed', editable: false})});
    await act(async () => {
      await first;
    });
    expect(message.success).toHaveBeenCalledTimes(1);
  });

  test('无未保存修改时保存草稿不发请求；完成直接 POST', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({values: {[FIELD_PS]: '正常'}})});
    await act(async () => {
      await store.saveValues();
    });
    expect(mockHttpPut).not.toHaveBeenCalled();
    mockHttpPost.mockResolvedValue({data: makeDetail({status: 'completed', editable: false})});
    await act(async () => {
      await store.complete();
    });
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/66/complete/');
  });
});

// ===== Store：已完成台账更正模式 =====

describe('ExcelLedgerStore 已完成台账更正', () => {
  test('已完成详情非更正模式无未保存；进入更正后修改为脏，取消更正恢复服务端值', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({
      status: 'completed', editable: false, values: {[FIELD_PS]: '正常'}})});
    expect(store.hasUnsaved).toBe(false);
    store.setValue(FIELD_PS, '异常');
    expect(store.hasUnsaved).toBe(false); // 非更正模式下只读，不计脏
    await act(async () => {
      store.startCorrection('登记时选错模块');
    });
    expect(store.correcting).toBe(true);
    expect(store.correctingEditable).toBe(true);
    await act(async () => {
      store.setValue(FIELD_PS, '异常');
    });
    expect(store.hasUnsaved).toBe(true); // 更正模式下计脏，返回前会提示
    await act(async () => {
      store.cancelCorrection();
    });
    expect(store.correcting).toBe(false);
    expect(store.values[FIELD_PS]).toBe('正常'); // 恢复服务端已保存值
    expect(store.hasUnsaved).toBe(false);
  });

  test('提交更正：POST /correct/（原因+整体值+日期），以服务端详情为准并退出更正模式', async () => {
    const store = new ExcelLedgerStore();
    store.applyDetail({data: makeDetail({
      status: 'completed', editable: false,
      values: {[FIELD_PS]: '正常'}, executed_date: '2026-10-16'})});
    await act(async () => {
      store.startCorrection('登记时选错模块');
      store.setValue(FIELD_PS, '异常');
      store.setDateDraft('2026-10-17');
    });
    mockHttpPost.mockResolvedValue({data: makeDetail({
      status: 'completed', editable: false, values: {[FIELD_PS]: '异常'},
      executed_date: '2026-10-17',
      corrections: [{id: 3, reason: '登记时选错模块', changes: []}]})});
    await act(async () => {
      await store.submitCorrection();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/66/correct/',
      {reason: '登记时选错模块',
       values: {[FIELD_PS]: '异常'},
       header: {executed_date: '2026-10-17'}});
    expect(message.success).toHaveBeenCalledWith('更正已保存');
    expect(store.correcting).toBe(false);
    expect(store.detail.status).toBe('completed');
    expect(store.values[FIELD_PS]).toBe('异常');
  });
});

// ===== 组件：按钮显隐与提交（共用夹具见 setupDetailSuite） =====

function setupDetailSuite() {
  let container = null;
  let store = null;
  let onBack = null;

  async function renderDetail(detailOverrides) {
    await act(async () => {
      store.applyDetail({data: makeDetail(detailOverrides)});
    });
    await act(async () => {
      ReactDOM.render(
        <ExcelLedgerDetail store={store} onBack={onBack}/>, container);
    });
    await flush();
  }

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    store = new ExcelLedgerStore();
    onBack = jest.fn();
  });

  afterEach(() => {
    ReactDOM.unmountComponentAtNode(container);
    document.body.removeChild(container);
    removeModals();
    container = null;
    store = null;
    onBack = null;
  });

  return {renderDetail, getStore: () => store, getOnBack: () => onBack,
          getContainer: () => container};
}

describe('ExcelLedgerDetail 完成填写按钮', () => {
  const suite = setupDetailSuite();

  test('草稿提供"保存草稿 + 完成填写"；已作废只读（无编辑/删除/更正按钮）', async () => {
    await suite.renderDetail({status: 'draft'});
    expect(buttonByText('保存草稿', suite.getContainer())).toBeTruthy();
    expect(buttonByText('完成填写', suite.getContainer())).toBeTruthy();
    ReactDOM.unmountComponentAtNode(suite.getContainer());
    await suite.renderDetail({status: 'void', editable: false});
    expect(buttonByText('保存草稿', suite.getContainer())).toBeUndefined();
    expect(buttonByText('完成填写', suite.getContainer())).toBeUndefined();
    expect(buttonByText('删除', suite.getContainer())).toBeUndefined();
    expect(buttonByText('更正', suite.getContainer())).toBeUndefined();
  });

  test('已完成台账提供"更正"按钮，无保存/完成/删除', async () => {
    await suite.renderDetail({status: 'completed', editable: false});
    expect(buttonByText('更正', suite.getContainer())).toBeTruthy();
    expect(buttonByText('保存草稿', suite.getContainer())).toBeUndefined();
    expect(buttonByText('完成填写', suite.getContainer())).toBeUndefined();
    expect(buttonByText('删除', suite.getContainer())).toBeUndefined();
  });

  test('完成填写：先本地必填预检（未填拦截不发请求），齐全后走完成端点', async () => {
    await suite.renderDetail({});
    // 必填未填 → warning，无请求（主操作按钮为"完成填写"）
    await act(async () => {
      buttonByText('完成填写', suite.getContainer()).click();
    });
    await flush();
    expect(message.warning).toHaveBeenCalledWith(expect.stringContaining('必填字段未填写'));
    expect(mockHttpPost).not.toHaveBeenCalled();
    // 填写齐全后点击：先 PUT 保存再 POST complete/
    await act(async () => {
      suite.getStore().setValue(FIELD_PS, '正常');
    });
    mockHttpPut.mockResolvedValue({data: makeDetail({values: {[FIELD_PS]: '正常'}})});
    mockHttpPost.mockResolvedValue({data: makeDetail({
      status: 'completed', values: {[FIELD_PS]: '正常'}, editable: false})});
    await act(async () => {
      buttonByText('完成填写', suite.getContainer()).click();
    });
    await flush();
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/66/complete/');
    expect(message.success).toHaveBeenCalledWith('已完成填写');
  });
});

describe('ExcelLedgerDetail 更正模式', () => {
  const suite = setupDetailSuite();

  test('已完成台账经"更正"进入更正模式（须填原因），提交更正走 /correct/', async () => {
    await suite.renderDetail({status: 'completed', editable: false,
                             values: {[FIELD_PS]: '正常'}, executed_date: '2026-10-16'});
    await act(async () => {
      buttonByText('更正', suite.getContainer()).click();
    });
    // 更正原因弹窗为异步挂载，先 flush 再查询
    await flush();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    // 原因为空被拦截
    const okBtn = Array.from(document.querySelectorAll('.ant-modal-confirm button'))
      .find(node => node.textContent.replace(/\s/g, '') === '进入更正');
    await act(async () => {
      okBtn.click();
    });
    await flush();
    expect(suite.getStore().correcting).toBe(false);
    // 填写原因后进入更正模式
    const reasonInput = document.querySelector('.ant-modal-confirm textarea');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      nativeSetter.call(reasonInput, '登记时选错模块');
      reasonInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(async () => {
      okBtn.click();
    });
    await flush();
    removeModals();
    expect(suite.getStore().correcting).toBe(true);
    expect(document.querySelector('[data-testid="correct-mode-banner"]')).toBeTruthy();
    // 提交更正：POST /correct/（原因 + 整体值 + 日期）
    mockHttpPost.mockResolvedValue({data: makeDetail({
      status: 'completed', editable: false, values: {[FIELD_PS]: '异常'},
      corrections: [{id: 3, reason: '登记时选错模块', changes: []}]})});
    await act(async () => {
      suite.getStore().setValue(FIELD_PS, '异常');
    });
    await act(async () => {
      buttonByText('提交更正', suite.getContainer()).click();
    });
    await flush();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-ledgers/66/correct/',
      expect.objectContaining({reason: '登记时选错模块'}));
    expect(message.success).toHaveBeenCalledWith('更正已保存');
    expect(suite.getStore().correcting).toBe(false);
  });
});

describe('ExcelLedgerDetail 返回确认与执行日期草稿', () => {
  const suite = setupDetailSuite();

  test('返回列表：无未保存修改直接返回，不弹确认', async () => {
    await suite.renderDetail({});
    await act(async () => {
      buttonByText('返回列表', suite.getContainer()).click();
    });
    expect(suite.getOnBack()).toHaveBeenCalledTimes(1);
    expect(document.querySelector('.ant-modal-confirm')).toBeNull();
  });

  test('返回列表：有未保存修改先确认，继续填写保留内容且不返回', async () => {
    await suite.renderDetail({values: {[FIELD_PS]: '正常'}});
    // act 内变更，确保点击前重渲染完成（避免点击到已脱管的旧节点）
    await act(async () => {
      suite.getStore().setValue(FIELD_PS, '异常');
    });
    await act(async () => {
      buttonByText('返回列表', suite.getContainer()).click();
    });
    // antd confirm 为异步挂载，先 flush 再查询（与导出预检确认框测试同口径）
    await flush();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).toBeTruthy();
    expect(confirm.textContent).toContain('有未保存的修改');
    expect(suite.getOnBack()).not.toHaveBeenCalled();
    const cancel = Array.from(document.querySelectorAll('.ant-modal-confirm button'))
      .find(node => node.textContent.replace(/\s/g, '') === '继续填写');
    await act(async () => {
      cancel.click();
    });
    await flush();
    expect(suite.getOnBack()).not.toHaveBeenCalled();
    // 内容保留：仍是详情页且填写值未丢
    expect(suite.getStore().detail).toBeTruthy();
    expect(suite.getStore().values[FIELD_PS]).toBe('异常');
    expect(buttonByText('完成填写', suite.getContainer())).toBeTruthy();
  });

  test('返回列表：确认放弃后返回列表', async () => {
    await suite.renderDetail({});
    await act(async () => {
      suite.getStore().setValue(FIELD_PS, '异常');
    });
    await act(async () => {
      buttonByText('返回列表', suite.getContainer()).click();
    });
    // antd confirm 为异步挂载，先 flush 再取按钮
    await flush();
    const ok = Array.from(document.querySelectorAll('.ant-modal-confirm button'))
      .find(node => node.textContent.replace(/\s/g, '') === '放弃修改并返回');
    await act(async () => {
      ok.click();
    });
    await flush();
    expect(suite.getOnBack()).toHaveBeenCalledTimes(1);
  });

  test('执行日期草稿：未动时保存保持当前日期（不误清空），改期后保存新日期', async () => {
    await suite.renderDetail({executed_date: '2026-10-16'});
    // 未改动日期直接点保存：保持已录日期而非清空
    mockHttpPut.mockResolvedValue({data: makeDetail({executed_date: '2026-10-16'})});
    await act(async () => {
      document.body.querySelector('[data-testid="excel-save-executed-date"]').click();
    });
    await flush();
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/66/',
      {header: {executed_date: '2026-10-16'}});
    // 改期后保存：提交草稿日期
    mockHttpPut.mockClear();
    mockHttpPut.mockResolvedValue({data: makeDetail({executed_date: '2026-10-17'})});
    await act(async () => {
      suite.getStore().setDateDraft('2026-10-17');
    });
    await act(async () => {
      document.body.querySelector('[data-testid="excel-save-executed-date"]').click();
    });
    await flush();
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/excel-ledgers/66/',
      {header: {executed_date: '2026-10-17'}});
    expect(suite.getStore().dateDirty).toBe(false);
  });
});
