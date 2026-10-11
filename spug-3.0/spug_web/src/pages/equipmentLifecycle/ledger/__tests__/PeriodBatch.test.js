/**
 * 周期批量新增与周期分组（2026-10-11）行为测试。
 *
 * - Store：fetchGroups/batchCreate/fetchSystemOptions 的请求参数与响应映射；
 * - LedgerGroupTable：分组行（周期/台账数/待填写/已提交复核）与组内系统台账渲染；
 * - LedgerBatchCreateModal：范围提示来自后端系统数、航季选择（夏秋/冬春）、
 *   受控 form 提交后按后端返回展示实际新增/已存在（真实渲染）。
 * mock libs.http 返回真实响应格式，错误提示由拦截器负责（本处不重复断言）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {Form} from 'antd';
import moment from 'moment';

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
  const AuthButton = (props) => React.createElement('span', null, props.children);
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

import {LedgerStore} from '../store';
import {LEDGER_TYPE} from '../constants';
import LedgerGroupTable from '../LedgerGroupTable';
import LedgerBatchCreateModal from '../LedgerBatchCreateModal';

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const GROUPS_PAYLOAD = [
  {
    maintenance_period: '2026-10', period_text: '2026年10月',
    total: 2, pending: 1, filled: 1,
    ledgers: [
      {id: 11, ledger_no: 'EL-WM-20261011-0001', ledger_type: 'week_month',
       system: 3, system_name: 'DVOR系统', executed_date: '2026-10-11',
       status: 'submitted', created_by_name: 'op1', created_at: '2026-10-11 09:00'},
      {id: 12, ledger_no: 'EL-WM-20261011-0002', ledger_type: 'week_month',
       system: 4, system_name: 'ILS系统', executed_date: '2026-10-11',
       status: 'draft', created_by_name: 'op1', created_at: '2026-10-11 09:00'},
    ],
  },
  {
    maintenance_period: '2026-09', period_text: '2026年9月',
    total: 1, pending: 0, filled: 1,
    ledgers: [
      {id: 5, ledger_no: 'EL-WM-20260910-0001', ledger_type: 'week_month',
       system: '', system_name: '', executed_date: '2026-09-10',
       status: 'reviewed', created_by_name: 'op1', created_at: '2026-09-11 09:00'},
    ],
  },
];

const BATCH_RESULT = {
  ledger_type: 'week_month', maintenance_period: '2026-10', period_text: '2026年10月',
  created: 3, existed: 1,
  created_ledgers: [{id: 21, ledger_no: 'EL-WM-20261011-0001', system_name: 'DVOR系统'}],
  existed_systems: ['DME系统'],
};

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  // 清理 Modal 传送门残留，避免污染后续用例的 textContent 断言
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask').forEach(node => node.remove());
});

describe('LedgerStore 周期分组与批量新增', () => {
  test('fetchGroups 携带类型与筛选参数并映射分组数据', async () => {
    mockHttpGet.mockResolvedValue({data: GROUPS_PAYLOAD});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.f_status = 'draft';
    store.f_system = 3;
    store.f_keyword = 'EL-WM';
    await store.fetchGroups();
    const [url, config] = mockHttpGet.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/ledgers/period-groups/');
    expect(config.params).toEqual({
      ledger_type: 'week_month', status: 'draft', system: 3, keyword: 'EL-WM',
    });
    expect(store.groups).toEqual(GROUPS_PAYLOAD);
    expect(store.groupsVersion).toBe(1);
    expect(store.isGroupsFetching).toBe(false);
  });

  test('batchCreate 提交类型+周期、成功后刷新分组并透传后端结果', async () => {
    mockHttpPost.mockResolvedValue(BATCH_RESULT);
    mockHttpGet.mockResolvedValue({data: []});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    const result = await store.batchCreate({ledger_type: 'week_month', period: '2026-10'});
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/batch-create/', {
      ledger_type: 'week_month', period: '2026-10',
    });
    expect(result).toEqual(BATCH_RESULT);
    expect(result.created).toBe(3);
    expect(result.existed).toBe(1);
    await flush();
    // 成功后刷新周期分组（不依赖手工触发）
    expect(mockHttpGet.mock.calls.some(c => c[0].endsWith('/ledgers/period-groups/'))).toBe(true);
  });

  test('fetchSystemOptions 拉取系统范围供筛选与批量新增展示', async () => {
    mockHttpGet.mockResolvedValue({data: [{id: 3, name: 'DVOR系统', system_code: 'SYS-3', is_active: true}]});
    const store = new LedgerStore(LEDGER_TYPE.SEASONAL);
    await store.fetchSystemOptions();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/batch-create/');
    expect(store.systemOptions).toHaveLength(1);
    expect(store.systemOptions[0].is_active).toBe(true);
  });
});

describe('LedgerGroupTable 分组渲染', () => {
  const columns = [
    {title: '台账编号', dataIndex: 'ledger_no'},
    {title: '系统', dataIndex: 'system_name', render: v => v || '—'},
    {title: '状态', dataIndex: 'status'},
  ];

  test('按周期渲染分组与组内各系统台账及填写状态', () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.groups = GROUPS_PAYLOAD;
    store.groupsVersion = 1;
    act(() => {
      ReactDOM.render(h(LedgerGroupTable, {store, columns}), container);
    });
    const text = container.textContent;
    // 分组行：周期文本 + 台账数/待填写/已提交复核
    expect(text).toContain('2026年10月');
    expect(text).toContain('2026年9月');
    // 组内行：各系统台账与状态（默认展开由 groupsVersion remount 保证）
    expect(text).toContain('EL-WM-20261011-0001');
    expect(text).toContain('DVOR系统');
    expect(text).toContain('EL-WM-20261011-0002');
    expect(text).toContain('ILS系统');
    expect(text).toContain('EL-WM-20260910-0001');
  });
});

describe('LedgerBatchCreateModal 一键新增弹窗', () => {
  // antd 受控 form 注入：真实走 validateFields → handleOk → store.batchCreate 链路
  const formRef = {current: null};

  function ModalHarness(props) {
    const [form] = Form.useForm();
    formRef.current = form;
    return h(LedgerBatchCreateModal, {...props, form});
  }

  async function renderModal(ledgerType, store) {
    await act(async () => {
      ReactDOM.render(h(ModalHarness, {
        visible: true, ledgerType, store, onCancel: () => {},
      }), container);
    });
    await act(async () => {
      await flush();
    });
  }

  test('范围提示按后端在用系统数展示并提供周期选择与提交按钮', async () => {
    // 范围来自后端 GET /ledgers/batch-create/（停用系统不计入），不编造台账
    mockHttpGet.mockResolvedValue({data: [
      {id: 3, name: 'DVOR系统', system_code: 'SYS-3', is_active: true},
      {id: 4, name: 'ILS系统', system_code: 'SYS-4', is_active: true},
      {id: 5, name: '退役系统', system_code: 'SYS-5', is_active: false},
    ]});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await renderModal(LEDGER_TYPE.WEEK_MONTH, store);
    const text = document.body.textContent;
    // 范围依据在用系统（停用系统不计入），不编造台账
    expect(text).toContain('2 个在用系统');
    expect(text).toContain('维护周期');
    // 弹窗存在确认按钮（antd4 双字按钮自动插空格："新 增"）
    const okButton = [...document.querySelectorAll('.ant-modal-footer button')]
      .find(b => b.textContent.replace(/\s/g, '') === '新增');
    expect(okButton).toBeTruthy();
  });

  test('季维护弹窗按航季选择：年份不限 + 夏秋季/冬春季二选一', async () => {
    mockHttpGet.mockResolvedValue({data: [{id: 3, name: 'DVOR系统', system_code: 'SYS-3', is_active: true}]});
    const store = new LedgerStore(LEDGER_TYPE.SEASONAL);
    await renderModal(LEDGER_TYPE.SEASONAL, store);
    const text = document.body.textContent;
    // 航季口径：夏秋季/冬春季（非 Q1-Q4），年份选择不设固定范围
    expect(text).toContain('航季年份');
    expect(text).toContain('夏秋季');
    expect(text).toContain('冬春季');
    expect(text).not.toContain('季度');
  });

  test('选择周期提交后按后端返回如实展示实际新增与已存在数量', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.systemOptions = [{id: 3, name: 'DVOR系统', system_code: 'SYS-3', is_active: true}];
    mockHttpPost.mockResolvedValue(BATCH_RESULT);
    mockHttpGet.mockResolvedValue({data: []});
    await renderModal(LEDGER_TYPE.WEEK_MONTH, store);
    // 通过受控 form 真实设值（周月维护 = 月份选择器值），点击"新增"走 validateFields
    await act(async () => {
      formRef.current.setFieldsValue({period: moment('2026-10', 'YYYY-MM')});
    });
    const okButton = [...document.querySelectorAll('.ant-modal-footer button')]
      .find(b => b.textContent.replace(/\s/g, '') === '新增');
    expect(okButton).toBeTruthy();
    await act(async () => {
      okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    // 提交的是所选周期；成功提示与结果展示均来自后端确认后的返回
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/batch-create/', {
      ledger_type: 'week_month', period: '2026-10',
    });
    expect(document.body.textContent).toContain('实际新增 3 张，已存在 1 张');
    expect(document.body.textContent).toContain('已存在的系统：DME系统');
  });
});
