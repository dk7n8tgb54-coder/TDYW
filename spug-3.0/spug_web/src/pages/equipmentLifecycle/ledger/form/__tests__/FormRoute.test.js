/**
 * 数字表单路线接线测试（2026-10-21）：统一列表来源判定与生成预览行键。
 *
 * 真实渲染（ReactDOM + jsdom）+ mock libs/http，验证：
 * - sourceTypeOf：created_from=form_template → 'form'（source_type 优先）；
 * - LedgerDetailLayer：formStore.detail 存在时渲染 FormLedgerDetail（表单
 *   填写视图），与 Excel/手工详情互不串扰；
 * - entryKeyOf：生成预览行键 = 路线+模板主键（两条路线主键可能撞号）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: jest.fn(), put: jest.fn(), delete: jest.fn(),
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
  const AuthButton = (props) => React.createElement('button', {
    type: 'button', 'data-testid': props['data-testid'], onClick: props.onClick,
  }, props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell, AuthButton, AuthCard: Shell, AuthFragment: Shell,
    Breadcrumb, SearchForm: Shell,
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

const {sourceTypeOf} = require('../../LedgerColumns');
const LedgerDetailLayer = require('../../LedgerDetailLayer').default;
const {entryKeyOf} = require('../../LedgerPeriodGenerateModal');
const {FormLedgerStore} = require('../formLedgerStore');
const {ExcelLedgerStore} = require('../../excel/excelLedgerStore');
const storeModule = require('../../store');
const {getLedgerStore} = storeModule;

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const FORM_DETAIL = {
  id: 77, ledger_no: 'EL-SE-20261018-0003', ledger_type: 'seasonal',
  status: 'draft', system_name: 'DVOR 系统', maintenance_period: '2026-冬春',
  created_by_name: '李四', completed_at: null, void_reason: '',
  form: {
    record_id: 3, values: {}, editable: true, voided: false,
    version: {id: 6, version_no: 1, template_name: '季维护数字表单',
              form: {protocol_version: 1, groups: [
                {id: 'g1', name: '检查', kind: 'fields', fields: [
                  {id: 'f1', name: '项目', type: 'text', required: false,
                   description: '', unit: '', options: []}]},
              ]}},
  },
};

describe('来源判定与生成行键', () => {
  test('sourceTypeOf：form_template → form（source_type 优先，兼容旧数据）', () => {
    expect(sourceTypeOf({source_type: 'form'})).toBe('form');
    expect(sourceTypeOf({created_from: 'form_template'})).toBe('form');
    expect(sourceTypeOf({created_from: 'excel_template'})).toBe('excel');
    expect(sourceTypeOf({})).toBe('manual');
  });

  test('entryKeyOf：路线+主键组合，跨路线撞号不冲突', () => {
    expect(entryKeyOf({template_kind: 'form', template_id: 7})).toBe('form-7');
    expect(entryKeyOf({template_kind: 'excel', template_id: 7})).toBe('excel-7');
    expect(entryKeyOf({template_id: 7})).toBe('excel-7');
    expect(entryKeyOf({template_kind: 'form', template_id: 7}))
      .not.toBe(entryKeyOf({template_kind: 'excel', template_id: 7}));
  });
});

describe('LedgerDetailLayer 数字表单详情分流', () => {
  test('formStore 有详情时渲染数字表单填写视图（标题含台账编号与表单分组）', async () => {
    const store = getLedgerStore('seasonal');
    const excelStore = new ExcelLedgerStore();
    const formStore = new FormLedgerStore();
    mockHttpGet.mockResolvedValue({data: FORM_DETAIL});
    await formStore.fetchDetail(77);
    const container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(h(LedgerDetailLayer, {
        store, excelStore, formStore, ledgerType: 'seasonal',
        excelCreateVisible: false, formCreateVisible: false,
        onExcelCreateCancel: () => {}, onFormCreateCancel: () => {},
        onExcelDetailBack: () => {}, onFormDetailBack: () => {},
      }), container);
    });
    await act(flush);
    expect(document.body.textContent).toContain('数字表单台账：EL-SE-20261018-0003');
    expect(document.body.textContent).toContain('季维护数字表单');
    expect(document.body.textContent).toContain('检查');
    ReactDOM.unmountComponentAtNode(container);
    container.remove();
  });

  test('formStore 无详情且 store 无详情时只渲染创建弹窗层，不出表单视图', () => {
    const store = getLedgerStore('seasonal');
    const excelStore = new ExcelLedgerStore();
    const formStore = new FormLedgerStore();
    const container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(h(LedgerDetailLayer, {
        store, excelStore, formStore, ledgerType: 'seasonal',
        excelCreateVisible: false, formCreateVisible: false,
        onExcelCreateCancel: () => {}, onFormCreateCancel: () => {},
        onExcelDetailBack: () => {}, onFormDetailBack: () => {},
      }), container);
    });
    expect(document.body.textContent).not.toContain('数字表单台账：');
    ReactDOM.unmountComponentAtNode(container);
    container.remove();
  });
});
