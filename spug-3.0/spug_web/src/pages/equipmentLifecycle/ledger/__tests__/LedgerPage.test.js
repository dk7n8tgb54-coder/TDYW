/**
 * 运维台账（步骤 3.2）页面渲染与交互测试。
 *
 * 真实渲染组件（ReactDOM + jsdom，全 createElement 风格与仓库测试惯例一致），
 * mock libs.http 与公共组件壳，验证：
 * - 三类台账页面名称正确（巡检/周月维护/季维护），周月维护单入口区分周与月
 * - 异常数量红色突出显示
 * - 录入表单：模板先行预览生成明细（只选模板，自动覆盖全部未停用系统）、
 *   payload 按系统+模板分组且每条明细携带 system_id、
 *   异常项必须填写说明、新增模式实际执行日期默认当日、
 *   后端业务错误不视为成功（弹窗不关闭）、成功后重新获取真实数据
 * - 页面不存在机房现场/离线/二维码/移动端入口
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

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const LEDGERS_PAYLOAD = {
  data: [
    {
      id: 1, ledger_no: 'EL-INS-20260910-0001', ledger_type: 'inspection',
      maintenance_cycle: '', executed_date: '2026-09-10', status: 'submitted',
      executor_names: '王五', items_count: 3,
      abnormal_count: 2, created_by_name: 'op1', created_at: '2026-09-11 09:00',
    },
  ],
  total: 1, page: 1, page_size: 20,
};

const entriesModule = require('../entries');
const ledgerFormModule = require('../LedgerForm');
const storeModule = require('../store');

describe('三类台账页面', () => {
  test.each([
    [entriesModule.InspectionLedgerIndex, 'inspection', '巡检台账'],
    [entriesModule.WeekMonthLedgerIndex, 'week_month', '周月维护台账'],
    [entriesModule.SeasonalLedgerIndex, 'seasonal', '季维护台账'],
  ])('%s 入口渲染正确的页面名称与请求类型', async (Component, type, label) => {
    mockHttpGet.mockResolvedValue(LEDGERS_PAYLOAD);
    await act(async () => {
      ReactDOM.render(h(Component), container);
    });
    await act(async () => {});
    expect(container.textContent).toContain(label);
    const call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/ledgers/'));
    expect(call[1].params.ledger_type).toBe(type);
  });

  test('异常数量突出显示（红色加粗）', async () => {
    mockHttpGet.mockResolvedValue(LEDGERS_PAYLOAD);
    await act(async () => {
      ReactDOM.render(h(entriesModule.InspectionLedgerIndex), container);
    });
    await act(async () => {});
    const abnormal = container.querySelector('span[style*="f5222d"], span[style*="rgb(245, 34, 45)"]');
    expect(abnormal).not.toBeNull();
    expect(abnormal.textContent).toBe('2');
  });

  test('页面不存在二维码、离线、移动端或机房现场录入入口', async () => {
    mockHttpGet.mockResolvedValue(LEDGERS_PAYLOAD);
    await act(async () => {
      ReactDOM.render(h(entriesModule.InspectionLedgerIndex), container);
    });
    await act(async () => {});
    ['二维码', '离线', '移动端', '现场录入', '扫码'].forEach(word => {
      expect(container.textContent).not.toContain(word);
    });
  });
});

describe('台账录入表单（LedgerForm）', () => {
  // 引入未包 observer 的原始类，测试可直接通过 ref 拿到类实例驱动交互
  const LedgerForm = ledgerFormModule.LedgerForm;
  const getLedgerStore = storeModule.getLedgerStore;

  function renderForm(store) {
    let instance = null;
    act(() => {
      ReactDOM.render(h(LedgerForm, {ref: r => {instance = r;}, store}), container);
    });
    return instance;
  }

  test('模板预览生成明细（数值项快照进入行状态）', async () => {
    const store = getLedgerStore('inspection');
    store.formVisible = true;
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) {
        return Promise.resolve({data: [{id: 11, system_code: 'S1', name: '系统一', install_location: '机房A'}], total: 1});
      }
      if (url.includes('/ledger-templates/available/')) {
        return Promise.resolve({data: [{id: 5, name: '巡检模板A', items_count: 1}]});
      }
      return Promise.resolve({data: []});
    });
    mockHttpPost.mockImplementation((url) => {
      if (url.endsWith('/ledgers/preview/')) {
        return Promise.resolve({
          data: [{
            system: {id: 11, system_code: 'S1', name: '系统一', install_location: '机房A'},
            template: {id: 5, name: '巡检模板A'},
            items: [{
              id: 201, name: '电源电压', input_type: 'number',
              unit: 'V', choices: [],
              is_required: false,
            }],
          }],
        });
      }
      return Promise.resolve({});
    });
    const instance = renderForm(store);
    await act(async () => {});
    await act(async () => {
      instance.setState({templateEntries: [{template_id: 5}]});
    });
    await act(async () => {
      instance.generatePreview();
    });
    await flush();
    const rows = instance.state.rows;
    expect(rows).toHaveLength(1);
    expect(rows[0].system_id).toBe(11);
    expect(rows[0].template_id).toBe(5);
    expect(rows[0].template_item_id).toBe(201);
    expect(rows[0].input_type).toBe('number');
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/preview/',
      expect.objectContaining({ledger_type: 'inspection', entries: [{system_id: 11, template_id: 5}]}));
  });

  test('只选模板自动展开全部可用系统（停用系统被剔除，不选电台）', async () => {
    const store = getLedgerStore('inspection');
    store.formVisible = true;
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) {
        return Promise.resolve({data: [
          {id: 11, system_code: 'S1', name: '系统一', install_location: '机房A'},
          {id: 99, system_code: 'S9', name: '停用系统', install_location: '机房X', is_active: false},
        ], total: 2});
      }
      if (url.includes('/ledger-templates/available/')) {
        return Promise.resolve({data: [{
          id: 5, name: '全科巡检模板', items_count: 1,
        }]});
      }
      return Promise.resolve({data: []});
    });
    mockHttpPost.mockImplementation((url) => {
      if (url.endsWith('/ledgers/preview/')) {
        return Promise.resolve({
          data: [{
            system: {id: 11, system_code: 'S1', name: '系统一', install_location: '机房A'},
            template: {id: 5, name: '全科巡检模板'},
            items: [{
              id: 201, name: '电源电压', input_type: 'text',
              unit: '', choices: [], is_required: false,
            }],
          }],
        });
      }
      return Promise.resolve({});
    });
    const instance = renderForm(store);
    await act(async () => {});
    // 只选模板：预览请求自动携带全部未停用系统（停用系统被剔除）
    await act(async () => {
      instance.setState({templateEntries: [{template_id: 5}]});
    });
    await act(async () => {
      instance.generatePreview();
    });
    await flush();
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/preview/',
      expect.objectContaining({ledger_type: 'inspection', entries: [{system_id: 11, template_id: 5}]}));
    const rows = instance.state.rows;
    expect(rows).toHaveLength(1);
    expect(rows[0].system_id).toBe(11);
    expect(rows[0].template_id).toBe(5);
  });

  test('挂载即加载当前类型全部模板（不带 system 参数），存入 templates 状态', async () => {
    const store = getLedgerStore('inspection');
    store.formVisible = true;
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/')) return Promise.resolve({data: [], total: 0});
      return Promise.resolve({data: [{
        id: 5, name: '巡检模板A', items_count: 1,
      }]});
    });
    const instance = renderForm(store);
    await act(async () => {});
    const availableCalls = mockHttpGet.mock.calls.filter(c => c[0].includes('/ledger-templates/available/'));
    expect(availableCalls).toHaveLength(1);
    // 模板不绑定系统：一次加载全部启用模板，无需按系统过滤
    expect(availableCalls[0][0]).not.toContain('system=');
    expect(instance.state.templates).toHaveLength(1);
    expect(instance.state.templates[0]).not.toHaveProperty('applicable_systems');
  });

  test('新增模式实际执行日期自动填入当日日期', async () => {
    const store = getLedgerStore('inspection');
    store.formVisible = true;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    const instance = renderForm(store);
    await act(async () => {});
    const d = new Date();
    const pad = n => (n < 10 ? `0${n}` : `${n}`);
    const today = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    expect(instance.state.header.executed_date).toBe(today);
  });

  test('一次提交多系统明细：按电台拆分提交，每条请求只含本电台明细', async () => {
    const store = getLedgerStore('inspection');
    store.formVisible = true;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    mockHttpPost.mockResolvedValue({});
    const instance = renderForm(store);
    act(() => {
      instance.setState({
        createdFrom: 'manual',
        header: {executed_date: '2026-09-10', executor_names: '', executed_start: null, executed_end: null},
        rows: [
          {client_key: 'a', system_id: 11, item_name: '项一', input_type: 'text', value_text: 'ok', is_temporary: true},
          {client_key: 'b', system_id: 22, item_name: '项二', input_type: 'text', value_text: 'ok', is_temporary: true},
          {client_key: 'c', system_id: 22, item_name: '项三', input_type: 'text', value_text: 'x', is_temporary: true},
        ],
      });
    });
    await act(async () => {
      instance.submit();
    });
    expect(mockHttpPost).toHaveBeenCalledTimes(2); // 两个电台各一条台账记录
    const payloads = mockHttpPost.mock.calls.map(c => c[1]);
    const group22 = payloads.map(p => p.entries.find(e => e.system_id === 22)).find(Boolean);
    expect(group22.items).toHaveLength(2);   // 同一系统两条
    payloads.forEach(p => {
      expect(p.entries).toHaveLength(1);     // 每次请求只含本电台明细
      expect(typeof p.entries[0].system_id).toBe('number');
      // 2026-09-22 起结果列移除：明细载荷不再携带 result
      p.entries[0].items.forEach(it => expect(it).not.toHaveProperty('result'));
    });
  });

  test('结果不再拦截提交：异常行无说明也一次提交成功', async () => {
    const store = getLedgerStore('inspection');
    store.formVisible = true;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    mockHttpPost.mockResolvedValue({});
    const instance = renderForm(store);
    act(() => {
      instance.setState({
        createdFrom: 'manual',
        header: {executed_date: '2026-09-10', executor_names: '', executed_start: null, executed_end: null},
        rows: [{client_key: 'a', system_id: 11, item_name: '项一', input_type: 'text', value_text: 'ok'}],
      });
    });
    await act(async () => {
      instance.submit();
    });
    await flush();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
  });

  test('周月维护缺少维护周期时提交被拦截', async () => {
    const store = getLedgerStore('week_month');
    store.formVisible = true;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    const instance = renderForm(store);
    act(() => {
      instance.setState({
        createdFrom: 'manual',
        header: {executed_date: '2026-09-10', executor_names: '', executed_start: null, executed_end: null},
        rows: [{client_key: 'a', system_id: 11, item_name: '项一', input_type: 'text', value_text: 'x'}],
      });
    });
    await act(async () => {
      instance.submit();
    });
    expect(mockHttpPost).not.toHaveBeenCalled();
  });

  test('后端业务错误不被当作成功：弹窗保持打开且不刷新列表', async () => {
    const store = getLedgerStore('inspection');
    store.formVisible = true;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    mockHttpPost.mockRejectedValue({error: '台账模板不存在'});
    const instance = renderForm(store);
    act(() => {
      instance.setState({
        createdFrom: 'manual',
        header: {executed_date: '2026-09-10', executor_names: '', executed_start: null, executed_end: null},
        rows: [{client_key: 'a', system_id: 11, item_name: '项一', input_type: 'text', value_text: 'x'}],
      });
    });
    await act(async () => {
      instance.submit();
    });
    await flush();
    expect(store.formVisible).toBe(true);
    // 失败后不重新获取台账列表（didMount 的系统列表请求除外）
    const listCalls = mockHttpGet.mock.calls.filter(c => c[0].endsWith('/ledgers/'));
    expect(listCalls).toHaveLength(0);
  });

  test('提交成功后关闭弹窗并重新获取后端真实数据', async () => {
    const store = getLedgerStore('inspection');
    store.formVisible = true;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    mockHttpPost.mockResolvedValue({});
    const instance = renderForm(store);
    act(() => {
      instance.setState({
        createdFrom: 'manual',
        header: {executed_date: '2026-09-10', executor_names: '', executed_start: null, executed_end: null},
        rows: [{client_key: 'a', system_id: 11, item_name: '项一', input_type: 'text', value_text: 'x'}],
      });
    });
    await act(async () => {
      instance.submit();
    });
    await flush();
    expect(store.formVisible).toBe(false);
    expect(mockHttpGet).toHaveBeenCalled(); // 重新获取真实列表数据
  });
});
