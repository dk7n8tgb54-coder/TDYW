/**
 * 设备生命周期 - 设备档案（独立主数据）前端行为测试。
 *
 * 真实渲染页面组件 + 真实 store（仅 mock libs/http），验证：
 * 1. 权限边界：无 device.view 权限时页面整体不渲染、不发起任何请求；
 *    view-only 无维护按钮；device.manage 控制新增/编辑/删除入口。
 * 2. 正常路径：授权用户能看到设备列表并在详情弹窗看到从后端回取的最新数据。
 * 3. Store 请求行为：筛选参数组装、失败时数据保护与 loading 复位、
 *    重置回第一页、CRUD 请求与删除分页回退。
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染组件。
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
    removeEventListener() {},
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
    device_sn: 'EL-001',
    device_name: '测向仪',
    device_model: 'M1',
    current_status: '1',
    install_time: '2026-01-01',
    enable_time: '2026-02-01',
    remark: '',
  }],
  total: 1,
  page: 1,
  page_size: 20,
};

describe('设备档案 store 请求行为', () => {
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
    // 防止本组测试的请求调用记录泄漏到页面渲染组
    mockHttpGet.mockReset();
    mockHttpPost.mockReset();
    mockHttpPut.mockReset();
    mockHttpDelete.mockReset();
  });

  it('fetchRecords 组装分页与筛选参数并更新列表', async () => {
    store.page = 2;
    store.f_device_sn = '雷达';
    store.f_device_model = 'M1';
    store.f_current_status = ['1', '2'];
    mockHttpGet.mockResolvedValue({data: [{id: 9}], total: 42});

    await store.fetchRecords();

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/devices/', {
      params: {
        page: 2,
        page_size: 20,
        keyword: '雷达',
        device_model: 'M1',
        current_status: ['1', '2'],
      }
    });
    expect(store.records).toEqual([{id: 9}]);
    expect(store.total).toBe(42);
    expect(store.isFetching).toBe(false);
  });

  it('HTTP 200 + error（拦截器 reject）时列表数据不被覆盖且 loading 复位', async () => {
    mockHttpGet.mockResolvedValueOnce({data: [{id: 1}], total: 1});
    await store.fetchRecords();

    mockHttpGet.mockRejectedValueOnce('获取设备列表失败');
    await store.fetchRecords();

    expect(store.records).toEqual([{id: 1}]);
    expect(store.total).toBe(1);
    expect(store.isFetching).toBe(false);
  });

  it('resetFilter 清空筛选并回到第一页', async () => {
    store.page = 5;
    store.f_device_sn = '关键字';
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    store.resetFilter();
    await flush();

    expect(store.page).toBe(1);
    expect(store.f_device_sn).toBe(null);
    expect(store.f_current_status).toEqual([]);
    expect(mockHttpGet).toHaveBeenLastCalledWith('/api/equipment-lifecycle/devices/', {
      params: {page: 1, page_size: 20}
    });
  });

  it('handleAdd POST 后回到第一页并刷新', async () => {
    store.page = 3;
    mockHttpPost.mockResolvedValue({id: 2});
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await store.handleAdd({device_sn: 'EL-NEW-001', device_name: '新设备'});

    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/devices/', {
      device_sn: 'EL-NEW-001', device_name: '新设备'
    });
    expect(store.page).toBe(1);
    expect(store.formVisible).toBe(false);
  });

  it('handleUpdate PUT 携带 id 并刷新', async () => {
    mockHttpPut.mockResolvedValue({id: 1});
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await store.handleUpdate({id: 1, device_name: '改名'});

    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/devices/', {id: 1, device_name: '改名'});
  });

  it('handleDelete 走查询串并刷新，末页最后一条回退页码', async () => {
    store.page = 2;
    store.records = [{id: 1}];
    mockHttpDelete.mockResolvedValue('');
    mockHttpGet.mockResolvedValue({data: [], total: 10});

    await store.handleDelete(1);

    expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/devices/', {params: {id: 1}});
    expect(store.page).toBe(1);
  });

  it('showDetail 先展示列表数据并回取最新详情，回取失败保留列表数据', async () => {
    mockHttpGet.mockResolvedValueOnce({id: 7, device_sn: 'EL-7', remark: '最新备注'});
    store.showDetail({id: 7, device_sn: 'EL-7', remark: '旧'});
    expect(store.detailVisible).toBe(true);
    await flush();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/devices/', {params: {id: 7}});
    expect(store.record.remark).toBe('最新备注');

    mockHttpGet.mockRejectedValueOnce('设备不存在或无权限访问');
    store.showDetail({id: 8, device_sn: 'EL-8', remark: '保留'});
    await flush();
    expect(store.record.remark).toBe('保留');
    expect(store.detailVisible).toBe(true);
  });

  it('closeDetail 关闭详情并清空当前记录', async () => {
    mockHttpGet.mockResolvedValue({id: 1, device_sn: 'EL-1'});
    store.showDetail({id: 1});
    await flush();
    store.closeDetail();
    expect(store.detailVisible).toBe(false);
    expect(store.record).toEqual({});
  });
});

describe('设备档案 页面渲染', () => {
  let container = null;

  function renderPage() {
    // 文件加载时已捕获组件（见底部 require），保持单一 React 实例
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<EquipmentLifecycle/>, container);
    });
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

  it('无权限时页面不渲染任何内容且不发起请求', () => {
    mockHasPermission.mockReturnValue(false);
    renderPage();
    expect(container.textContent).toBe('');
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('view-only 可见设备列表但无维护按钮，仅详情入口', async () => {
    mockHasPermission.mockImplementation(code => code === VIEW_AUTH);
    mockHttpGet.mockResolvedValue(listPayload);
    renderPage();
    await flush();

    const text = container.textContent;
    expect(text).toContain('EL-001');
    expect(text).toContain('测向仪');
    expect(text).toContain('正常');
    expect(text).toContain('共 1 条');

    // 无 device.manage 权限：不渲染任何维护入口
    expect(text).not.toContain('新增设备');
    expect(text).not.toContain('编辑');
    expect(text).not.toContain('删除');

    // 详情入口存在
    const buttons = Array.from(container.querySelectorAll('button'));
    expect(buttons.some(btn => btn.textContent.includes('详情'))).toBe(true);
  });

  it('manage 权限出现新增/编辑/删除入口', async () => {
    mockHasPermission.mockImplementation(code => [VIEW_AUTH, MANAGE_AUTH].includes(code));
    mockHttpGet.mockResolvedValue(listPayload);
    renderPage();
    await flush();

    const text = container.textContent;
    expect(text).toContain('新增设备');
    expect(text).toContain('编辑');
    expect(text).toContain('删除');
  });

  it('无 relation.view 权限时详情弹窗不显示所属系统关系', async () => {
    mockHasPermission.mockImplementation(code => code === VIEW_AUTH);
    mockHttpGet.mockImplementation((url, config) => {
      if (config && config.params && config.params.id) {
        return Promise.resolve({...listPayload.data[0]});
      }
      return Promise.resolve(listPayload);
    });
    renderPage();
    await flush();

    const detailBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('详情'));
    act(() => {
      Simulate.click(detailBtn);
    });
    await flush();

    expect(document.body.textContent).toContain('设备详情');
    expect(document.body.textContent).not.toContain('所属系统关系');
    // 关系区块被权限门拦截，设备侧关系接口不会被调用
    const relationCalls = mockHttpGet.mock.calls.filter(
      call => call[1] && call[1].params && call[1].params.device_id);
    expect(relationCalls.length).toBe(0);
  });

  it('有 relation.view 权限时详情弹窗展示所属系统关系（关系请求晚于详情返回也能刷新）', async () => {
    mockHasPermission.mockImplementation(code => [VIEW_AUTH, 'equipment_lifecycle.relation.view'].includes(code));
    // 模拟真实时序：详情请求先返回，关系请求延迟返回——
    // 关系区块必须自己订阅 store（observer），否则会永远停留在加载态
    let resolveRelations;
    mockHttpGet.mockImplementation((url, config) => {
      if (config && config.params && config.params.id) {
        return Promise.resolve({...listPayload.data[0]});
      }
      if (config && config.params && config.params.device_id) {
        return new Promise(resolve => {
          resolveRelations = resolve;
        });
      }
      return Promise.resolve(listPayload);
    });
    renderPage();
    await flush();

    const detailBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('详情'));
    act(() => {
      Simulate.click(detailBtn);
    });
    await flush();
    // 此时详情已回填、关系请求仍在途
    expect(document.body.textContent).toContain('设备详情');

    await act(async () => {
      resolveRelations({
        data: [{id: 5, system_name: '所属系统A', role_text: '主用', is_primary: true,
                valid_from: '2026-01-01', valid_to: null, status: 'active', status_text: '生效中'}],
        total: 1,
      });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(document.body.textContent).toContain('所属系统关系');
    expect(document.body.textContent).toContain('所属系统A');
    expect(document.body.textContent).not.toContain('加载中');
  });

  it('点击详情从后端回取最新数据并在弹窗展示', async () => {
    mockHasPermission.mockImplementation(code => code === VIEW_AUTH);
    mockHttpGet.mockImplementation((url, config) => {
      if (config && config.params && config.params.id) {
        return Promise.resolve({...listPayload.data[0], remark: '详情接口回取的最新备注'});
      }
      return Promise.resolve(listPayload);
    });
    renderPage();
    await flush();

    const detailBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('详情'));
    act(() => {
      Simulate.click(detailBtn);
    });
    await flush();

    // antd Modal 渲染到 document.body
    expect(document.body.textContent).toContain('设备详情');
    expect(document.body.textContent).toContain('详情接口回取的最新备注');
  });

  it('仅 relation.view 权限时详情弹窗显示关系但无新增关系入口', async () => {
    mockHasPermission.mockImplementation(code =>
      [VIEW_AUTH, 'equipment_lifecycle.relation.view'].includes(code));
    mockHttpGet.mockImplementation((url, config) => {
      if (config && config.params && config.params.id) {
        return Promise.resolve({...listPayload.data[0]});
      }
      if (config && config.params && config.params.device_id) {
        return Promise.resolve({data: [], total: 0});
      }
      return Promise.resolve(listPayload);
    });
    renderPage();
    await flush();

    const detailBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('详情'));
    act(() => {
      Simulate.click(detailBtn);
    });
    await flush();

    expect(document.body.textContent).toContain('所属系统关系');
    expect(document.body.textContent).not.toContain('新增关系');
  });

  it('有 relation.manage 权限时可从设备详情新增关系且设备锁定', async () => {
    mockHasPermission.mockImplementation(code => [
      VIEW_AUTH, MANAGE_AUTH,
      'equipment_lifecycle.relation.view', 'equipment_lifecycle.relation.manage',
    ].includes(code));
    mockHttpGet.mockImplementation((url, config) => {
      if (config && config.params && config.params.id) {
        return Promise.resolve({...listPayload.data[0]});
      }
      if (config && config.params && config.params.device_id) {
        return Promise.resolve({data: [], total: 0});
      }
      if (config && config.params && config.params.system_options) {
        return Promise.resolve([{id: 3, name: '系统A', code: ''}]);
      }
      return Promise.resolve(listPayload);
    });
    renderPage();
    await flush();

    const detailBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('详情'));
    act(() => {
      Simulate.click(detailBtn);
    });
    await flush();

    const addBtn = Array.from(document.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('新增关系'));
    expect(addBtn).toBeTruthy();
    act(() => {
      Simulate.click(addBtn);
    });
    await flush();

    // 表单打开：系统可自选（拉取系统选项），设备锁定为当前设备
    expect(document.body.textContent).toContain('关系角色');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/system-relations/', {params: {system_options: 1}});
    const deviceSearchCalls = mockHttpGet.mock.calls.filter(
      call => call[1] && call[1].params && 'device_options' in call[1].params);
    expect(deviceSearchCalls.length).toBe(0);
    const lockedInput = Array.from(document.querySelectorAll('input[disabled]'))
      .find(input => input.value === 'EL-001（测向仪）');
    expect(lockedInput).toBeTruthy();
  });
});

// 渲染测试组件：在 mock 注册后于文件加载期捕获，保证单一 React 实例
const EquipmentLifecycle = require('../index').default;
