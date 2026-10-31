/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 */
/**
 * 系统配置共享 Store / 系统详情配置页签 竞态行为测试（2026-10-31 上线前审查）。
 * 真实执行 Store 方法与组件挂载/卸载（ReactDOM + jsdom，仓库惯例），mock
 * libs.http 用可控 deferred 响应构造时序，验证：
 * - A → B 快速切换后，迟到的 A 系统响应（当前配置/配置变更）不得覆盖 B 的状态；
 * - 逆序响应（B 先回、A 后回）最终只保留最后一次请求的数据；
 * - 卸载（clearView）后到达的响应不得回写已清空的视图数据，loading 不残留。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {MemoryRouter} from 'react-router-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();
const mockHasPermission = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: mockHasPermission,
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
let store = null;

beforeEach(() => {
  mockHasPermission.mockImplementation(() => true);
  container = document.createElement('div');
  document.body.appendChild(container);
  store = require('../store').default;
  act(() => {
    store.clearView();
  });
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-dropdown, .ant-select-dropdown, .ant-message, .ant-modal-confirm, .ant-drawer-mask').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

/** 可控响应：手动决定何时 resolve，用于构造逆序/迟到时序。 */
function deferred() {
  let resolve;
  const promise = new Promise(res => {
    resolve = res;
  });
  return {promise, resolve};
}

const CONFIG_A = {
  system: {id: 7, name: 'DVOR系统', system_code: 'SYS-001'},
  baseline: {source: 'A来源', established_by_name: 'A员', established_at: '2026-10-01 08:00:00'},
  items: [{
    param: 11, param_code: 'a_param', param_name: 'A系统参数',
    category: 'runtime_param', category_text: '运行参数', data_type: 'number',
    data_type_text: '数字', unit: '', is_required: false, options: [],
    value_text: '', value_number: '1', value_bool: null, value_date: null,
    value_choice: '', display_value: '1', effective_at: null,
    last_change_id: null, last_change_no: '', last_changed_by_name: '', source_text: '',
  }],
};

const CONFIG_B = {
  system: {id: 8, name: 'DME系统', system_code: 'SYS-002'},
  baseline: {source: 'B来源', established_by_name: 'B员', established_at: '2026-10-02 08:00:00'},
  items: [{
    param: 12, param_code: 'b_param', param_name: 'B系统参数',
    category: 'runtime_param', category_text: '运行参数', data_type: 'number',
    data_type_text: '数字', unit: '', is_required: false, options: [],
    value_text: '', value_number: '2', value_bool: null, value_date: null,
    value_choice: '', display_value: '2', effective_at: null,
    last_change_id: null, last_change_no: '', last_changed_by_name: '', source_text: '',
  }],
};

const CHANGES_A = {
  total: 1, page: 1, page_size: 10,
  items: [{
    id: 31, change_no: 'PZ-A-0001', system: 7, system_name: 'DVOR系统',
    reason: 'A变更', status: 'applied', status_text: '已生效',
    applied_at: '2026-10-02 08:30:00', verify_status: '', verify_status_text: '未验证',
    verified_at: null, verified_by_name: '',
    created_by_name: 'admin', created_at: '2026-10-02 08:00:00',
  }],
};

const CHANGES_B = {
  total: 1, page: 1, page_size: 10,
  items: [{
    id: 41, change_no: 'PZ-B-0001', system: 8, system_name: 'DME系统',
    reason: 'B变更', status: 'applied', status_text: '已生效',
    applied_at: '2026-10-03 08:30:00', verify_status: '', verify_status_text: '未验证',
    verified_at: null, verified_by_name: '',
    created_by_name: 'admin', created_at: '2026-10-03 08:00:00',
  }],
};

describe('systemConfig store · 当前配置请求竞态', () => {
  it('A → B 逆序响应：迟到的 A 系统响应不得覆盖 B 系统状态', async () => {
    const da = deferred();
    const db = deferred();
    mockHttpGet.mockImplementation(url => {
      const u = String(url);
      if (u.endsWith('/systems/7/config/')) return da.promise;
      if (u.endsWith('/systems/8/config/')) return db.promise;
      return Promise.resolve({});
    });
    act(() => {
      store.fetchConfig(7);
      store.fetchConfig(8);
    });
    // B 的响应先到：展示 B
    await act(async () => {
      db.resolve(CONFIG_B);
      await flush();
      await flush();
    });
    expect(store.configSystem.id).toBe(8);
    expect(store.configItems[0].param_code).toBe('b_param');
    expect(store.configBaseline.source).toBe('B来源');
    expect(store.isConfigFetching).toBe(false);
    // A 的响应迟到：不得回写
    await act(async () => {
      da.resolve(CONFIG_A);
      await flush();
      await flush();
    });
    expect(store.configSystem.id).toBe(8);
    expect(store.configItems[0].param_code).toBe('b_param');
    expect(store.configBaseline.source).toBe('B来源');
    expect(store.isConfigFetching).toBe(false);
  });

  it('同系统重复请求逆序：后发起的请求胜出，先发起的迟到响应被丢弃', async () => {
    const d1 = deferred();
    const d2 = deferred();
    mockHttpGet.mockImplementation(() => d1.promise);
    act(() => {
      store.fetchConfig(7);
    });
    mockHttpGet.mockImplementation(() => d2.promise);
    act(() => {
      store.fetchConfig(7);
    });
    await act(async () => {
      d2.resolve(CONFIG_B);
      await flush();
      await flush();
    });
    expect(store.configSystem.id).toBe(8);
    await act(async () => {
      d1.resolve(CONFIG_A);
      await flush();
      await flush();
    });
    expect(store.configSystem.id).toBe(8);
    expect(store.configItems[0].param_code).toBe('b_param');
  });
});

describe('systemConfig store · 配置变更请求竞态', () => {
  it('A → B 逆序响应：迟到的 A 变更历史不得覆盖 B 的变更列表', async () => {
    const da = deferred();
    const db = deferred();
    mockHttpGet.mockImplementation(url => {
      const u = String(url);
      if (u.includes('/systems/7/config/changes/')) return da.promise;
      if (u.includes('/systems/8/config/changes/')) return db.promise;
      return Promise.resolve({});
    });
    act(() => {
      store.fetchChanges(7);
      store.fetchChanges(8);
    });
    await act(async () => {
      db.resolve(CHANGES_B);
      await flush();
      await flush();
    });
    expect(store.changes[0].change_no).toBe('PZ-B-0001');
    expect(store.isChangesFetching).toBe(false);
    await act(async () => {
      da.resolve(CHANGES_A);
      await flush();
      await flush();
    });
    expect(store.changes[0].change_no).toBe('PZ-B-0001');
    expect(store.total).toBe(1);
    expect(store.isChangesFetching).toBe(false);
  });
});

describe('systemConfig store · 卸载后响应', () => {
  it('clearView（页签卸载）后到达的配置/变更响应不得回写已清空的数据', async () => {
    const dc = deferred();
    const dg = deferred();
    mockHttpGet.mockImplementation(url => {
      const u = String(url);
      if (u.endsWith('/systems/7/config/')) return dc.promise;
      if (u.includes('/config/changes/')) return dg.promise;
      return Promise.resolve({});
    });
    act(() => {
      store.refreshAll(7);
    });
    // 模拟页签/维护页卸载（componentWillUnmount → clearView）
    act(() => {
      store.clearView();
    });
    await act(async () => {
      dc.resolve(CONFIG_A);
      dg.resolve(CHANGES_A);
      await flush();
      await flush();
    });
    expect(store.configItems).toEqual([]);
    expect(store.configSystem).toEqual({});
    expect(store.configBaseline).toBeNull();
    expect(store.changes).toEqual([]);
    expect(store.total).toBe(0);
    expect(store.isConfigFetching).toBe(false);
    expect(store.isChangesFetching).toBe(false);
  });
});

describe('SystemConfigTab 组件 · 卸载后响应', () => {
  it('页签卸载后迟到的当前配置响应不回写 Store（A → B 切换场景）', async () => {
    const dc = deferred();
    mockHttpGet.mockImplementation(url => {
      const u = String(url);
      if (u.endsWith('/systems/7/config/')) return dc.promise;
      if (u.includes('/config/changes/')) return Promise.resolve(CHANGES_A);
      return Promise.resolve({});
    });
    const SystemConfigTab = require('../SystemConfigTab').default;
    act(() => {
      ReactDOM.render(
        <MemoryRouter><SystemConfigTab systemId={7}/></MemoryRouter>, container);
    });
    // 切换系统详情即卸载页签，随后迟到的 A 响应到达
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    await act(async () => {
      dc.resolve(CONFIG_A);
      await flush();
      await flush();
    });
    expect(store.configItems).toEqual([]);
    expect(store.configSystem).toEqual({});
    expect(store.configBaseline).toBeNull();
    expect(store.isConfigFetching).toBe(false);
  }, 15000);  // 组件挂载渲染较慢，全量并行下默认 5s 超时不够
});
