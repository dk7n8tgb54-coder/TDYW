/**
 * 设备生命周期 - 设备位置（当前位置 + 位置变更历史）前端行为测试。
 *
 * 真实渲染页面组件 + 真实 store（仅 mock libs/http），验证：
 * 1. 列表展示"当前位置"列；
 * 2. 详情弹窗展示当前位置（含空位置显示 -）；
 * 3. 位置历史弹窗正常渲染历史数据；
 * 4. 变更位置入口权限门控：无 device.manage 时不渲染；
 * 5. Store 请求行为：变更请求参数正确、成功后重新拉取详情/列表、
 *    失败时不更新页面、历史请求携带 device_id。
 *
 * 环境说明：沿用本仓库惯例使用 ReactDOM + react-dom/test-utils + jsdom 真实渲染。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();
const mockHasPermission = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: mockHttpDelete},
  hasPermission: mockHasPermission,
  Permission: {isSuper: false},
  history: {push: jest.fn()},
  X_TOKEN: 'test-token',
}));

// jsdom 环境垫片：antd Table 分页链需要 matchMedia，rc-table 测量需要 ResizeObserver
/* eslint-disable no-empty-function */
if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    dispatchEvent: () => false,
  });
}
if (!global.ResizeObserver) {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
/* eslint-enable no-empty-function */

const VIEW_AUTH = 'equipment_lifecycle.device.view';
const MANAGE_AUTH = 'equipment_lifecycle.device.manage';

const HISTORY_URL = '/api/equipment-lifecycle/devices/location-history/';
const CHANGE_URL = '/api/equipment-lifecycle/devices/location-change/';

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

// store 行为测试用：每个测试重置模块后取全新 store 实例
function freshStore() {
  jest.resetModules();
  return require('../store').default;
}

const listPayload = {
  data: [{
    id: 1,
    device_sn: 'EL-LOC-001',
    device_name: '测向仪',
    device_model: 'M1',
    current_status: '1',
    current_location: '一号机房-A区-机柜03-机位12',
    remark: '',
  }],
  total: 1,
  page: 1,
  page_size: 20,
};

const historyPayload = {
  data: [
    {id: 11, device_id: 1, old_location: '一号机房-A区-机柜03-机位12', new_location: '二号机房-B区-机柜01',
     effective_at: '2026-09-01 08:30:00', ended_at: null, change_type: 'relocation',
     change_type_text: '位置搬迁', reason: '机房重新布置', created_by_name: '管理员'},
    {id: 10, device_id: 1, old_location: '', new_location: '一号机房-A区-机柜03-机位12',
     effective_at: '2026-08-01 10:00:00', ended_at: '2026-09-01 08:30:00', change_type: 'initial',
     change_type_text: '初始登记', reason: '', created_by_name: '管理员'},
  ],
  total: 2,
};

describe('设备位置 store 请求行为', () => {
  let store;

  beforeEach(() => {
    jest.resetModules();
    mockHttpGet.mockReset();
    mockHttpPost.mockReset();
    mockHttpPut.mockReset();
    mockHttpDelete.mockReset();
    store = freshStore();
  });

  afterEach(() => {
    mockHttpGet.mockReset();
    mockHttpPost.mockReset();
    mockHttpPut.mockReset();
    mockHttpDelete.mockReset();
  });

  it('changeLocation 请求参数正确（device_id 服务端来源合并）', async () => {
    store.record = {id: 5, device_sn: 'EL-5', current_location: '旧位置'};
    mockHttpPost.mockResolvedValue({id: 5});
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await store.changeLocation({
      new_location: '新位置', effective_at: '2026-09-04 10:30:00',
      change_type: 'relocation', reason: '搬迁',
    });

    expect(mockHttpPost).toHaveBeenCalledWith(CHANGE_URL, {
      new_location: '新位置',
      effective_at: '2026-09-04 10:30:00',
      change_type: 'relocation',
      reason: '搬迁',
      device_id: 5,
    });
  });

  it('changeLocation 成功后关闭弹窗并重新拉取设备详情与列表（不乐观更新）', async () => {
    store.record = {id: 5, device_sn: 'EL-5', current_location: '旧位置'};
    store.locationChangeVisible = true;
    mockHttpPost.mockResolvedValue({id: 5});
    mockHttpGet.mockResolvedValue({id: 5, device_sn: 'EL-5', current_location: '新位置'});

    await store.changeLocation({new_location: '新位置', change_type: 'relocation', reason: '搬迁'});

    expect(store.locationChangeVisible).toBe(false);
    // 详情重新请求（GET devices/?id=5）且 record 更新为后端返回的最新数据
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/devices/', {params: {id: 5}});
    expect(store.record.current_location).toBe('新位置');
  });

  it('changeLocation 失败时弹窗保持打开、详情不刷新、位置不变', async () => {
    store.record = {id: 5, device_sn: 'EL-5', current_location: '旧位置'};
    store.locationChangeVisible = true;
    mockHttpPost.mockRejectedValue('请填写变更原因');

    await store.changeLocation({new_location: '新位置', change_type: 'relocation', reason: ''})
      .catch(() => {});

    expect(store.locationChangeVisible).toBe(true);
    expect(store.record.current_location).toBe('旧位置');
    // 失败路径不触发任何刷新请求
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('fetchLocationHistory 携带 device_id 并写入列表，失败时复位 loading', async () => {
    store.record = {id: 7, device_sn: 'EL-7'};
    mockHttpGet.mockResolvedValueOnce(historyPayload);

    await store.fetchLocationHistory();

    expect(mockHttpGet).toHaveBeenCalledWith(HISTORY_URL, {params: {device_id: 7}});
    expect(store.locationHistory).toEqual(historyPayload.data);
    expect(store.locationHistoryLoading).toBe(false);

    mockHttpGet.mockRejectedValueOnce('设备不存在或无权限访问');
    await store.fetchLocationHistory();
    expect(store.locationHistoryLoading).toBe(false);
  });

  it('showLocationHistory 打开弹窗并拉取，closeLocationHistory 清空数据', async () => {
    store.record = {id: 7, device_sn: 'EL-7'};
    mockHttpGet.mockResolvedValue(historyPayload);

    store.showLocationHistory();
    expect(store.locationHistoryVisible).toBe(true);
    await flush();
    expect(store.locationHistory.length).toBe(2);

    store.closeLocationHistory();
    expect(store.locationHistoryVisible).toBe(false);
    expect(store.locationHistory).toEqual([]);
  });
});

describe('设备位置 页面渲染', () => {
  let container = null;

  function renderPage() {
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<EquipmentLifecycle/>, container);
    });
  }

  function openDetail() {
    const detailBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('详情'));
    act(() => {
      Simulate.click(detailBtn);
    });
    return flush();
  }

  beforeEach(() => {
    jest.resetModules();
  });

  afterEach(() => {
    if (container) {
      act(() => {
        ReactDOM.unmountComponentAtNode(container);
      });
      container.remove();
      container = null;
    }
    mockHttpGet.mockReset();
    mockHttpPost.mockReset();
    mockHttpPut.mockReset();
    mockHttpDelete.mockReset();
    mockHasPermission.mockReset();
  });

  it('设备列表展示当前位置列', async () => {
    mockHasPermission.mockImplementation(code => code === VIEW_AUTH);
    mockHttpGet.mockResolvedValue(listPayload);
    renderPage();
    await flush();

    const text = container.textContent;
    expect(text).toContain('当前位置');
    expect(text).toContain('一号机房-A区-机柜03-机位12');
  });

  it('详情弹窗展示当前所在位置；无 manage 权限时不渲染变更位置入口', async () => {
    mockHasPermission.mockImplementation(code => code === VIEW_AUTH);
    mockHttpGet.mockImplementation((url, config) => {
      if (config && config.params && config.params.id) {
        return Promise.resolve({...listPayload.data[0]});
      }
      return Promise.resolve(listPayload);
    });
    renderPage();
    await openDetail();

    const body = document.body.textContent;
    expect(body).toContain('当前所在位置');
    expect(body).toContain('一号机房-A区-机柜03-机位12');
    expect(body).toContain('位置历史');
    expect(body).not.toContain('变更位置');
  });

  it('详情弹窗空位置显示 -，manage 权限时出现变更位置入口', async () => {
    mockHasPermission.mockImplementation(code => [VIEW_AUTH, MANAGE_AUTH].includes(code));
    const noLocation = {...listPayload.data[0], current_location: ''};
    mockHttpGet.mockImplementation((url, config) => {
      if (config && config.params && config.params.id) {
        return Promise.resolve({...noLocation});
      }
      return Promise.resolve({...listPayload, data: [noLocation]});
    });
    renderPage();
    await openDetail();

    const body = document.body.textContent;
    // 空位置展示 "-"（详情项中不出现任何位置文本）
    expect(body).toContain('当前所在位置');
    expect(body).not.toContain('一号机房-A区-机柜03-机位12');
    expect(body).toContain('变更位置');
  });

  it('位置历史弹窗正常渲染历史数据', async () => {
    mockHasPermission.mockImplementation(code => code === VIEW_AUTH);
    mockHttpGet.mockImplementation((url, config) => {
      if (url === HISTORY_URL) {
        return Promise.resolve(historyPayload);
      }
      if (config && config.params && config.params.id) {
        return Promise.resolve({...listPayload.data[0]});
      }
      return Promise.resolve(listPayload);
    });
    renderPage();
    await openDetail();

    const historyBtn = Array.from(document.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('位置历史'));
    act(() => {
      Simulate.click(historyBtn);
    });
    await flush();

    const body = document.body.textContent;
    expect(body).toContain('位置历史 - 测向仪（EL-LOC-001）');
    expect(body).toContain('二号机房-B区-机柜01');
    expect(body).toContain('位置搬迁');
    expect(body).toContain('初始登记');
    expect(body).toContain('机房重新布置');
    // 请求必须携带 device_id
    expect(mockHttpGet).toHaveBeenCalledWith(HISTORY_URL, {params: {device_id: 1}});
  });
});

// 渲染测试组件：在 mock 注册后于文件加载期捕获，保证单一 React 实例
const EquipmentLifecycle = require('../index').default;
