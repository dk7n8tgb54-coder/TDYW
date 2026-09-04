/**
 * 设备生命周期第 2 步前端行为测试：系统主数据 + 系统—设备关系维护。
 *
 * 真实渲染组件 + 真实 store（仅 mock libs/http），验证：
 * 1. 权限边界：无权限不渲染不请求；view-only 无维护按钮；manage 控制维护入口。
 * 2. 系统列表/详情加载与只读展示、详情路由跳转。
 * 3. Store 请求行为：参数组装、删除分页回退、关系退出端点、设备搜索。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();
const mockHasPermission = jest.fn();
const mockHistoryPush = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: mockHttpDelete},
  hasPermission: mockHasPermission,
  Permission: {isSuper: false},
  history: {push: mockHistoryPush},
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

const PERM_SYSTEM_VIEW = 'equipment_lifecycle.system.view';
const PERM_SYSTEM_MANAGE = 'equipment_lifecycle.system.manage';
const PERM_RELATION_VIEW = 'equipment_lifecycle.relation.view';
const PERM_RELATION_MANAGE = 'equipment_lifecycle.relation.manage';

// 渲染测试用：文件加载时捕获组件与 store（保持单一 React 实例，
// 避免与 jest.resetModules 产生两份 React 导致 Invalid hook call）
const SystemIndex = require('../index').default;
const SystemDetail = require('../detail').default;
const EquipmentLifecycleRelations = require('../../relations').default;

// store 行为测试用：每个测试重置模块后取全新 store 实例
function freshStores() {
  jest.resetModules();
  const storeModule = require('../store');
  return {systemStore: storeModule.systemStore, relationStore: storeModule.relationStore};
}

// 详情页 AuthDiv 的 auth 为 a|b 组合串，权限 mock 需按 | 拆分判断
const grantPerms = (perms) => mockHasPermission.mockImplementation(code =>
  String(code).split('|').some(c => perms.includes(c)));

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

afterEach(() => {
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
  mockHttpDelete.mockReset();
  mockHasPermission.mockReset();
  mockHistoryPush.mockReset();
});

describe('系统主数据 store 请求行为', () => {
  it('fetchRecords 组装关键字与分页参数', async () => {
    const {systemStore} = freshStores();
    systemStore.page = 2;
    systemStore.f_keyword = '测控';
    mockHttpGet.mockResolvedValue({data: [{id: 1}], total: 7});

    await systemStore.fetchRecords();

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/', {
      params: {page: 2, page_size: 20, keyword: '测控'}
    });
    expect(systemStore.records).toEqual([{id: 1}]);
    expect(systemStore.total).toBe(7);
    expect(systemStore.isFetching).toBe(false);
  });

  it('handleAdd POST 后回到第一页并刷新', async () => {
    const {systemStore} = freshStores();
    systemStore.page = 3;
    mockHttpPost.mockResolvedValue({id: 9});
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await systemStore.handleAdd({name: '新系统'});

    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/', {name: '新系统'});
    expect(systemStore.page).toBe(1);
  });

  it('handleUpdate PUT 携带 id', async () => {
    const {systemStore} = freshStores();
    mockHttpPut.mockResolvedValue({id: 1});
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await systemStore.handleUpdate({id: 1, name: '改名'});

    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/', {id: 1, name: '改名'});
  });

  it('handleDelete 走查询串并刷新，末页最后一条回退页码', async () => {
    const {systemStore} = freshStores();
    systemStore.page = 2;
    systemStore.records = [{id: 1}];
    mockHttpDelete.mockResolvedValue('');
    mockHttpGet.mockResolvedValue({data: [], total: 10});

    await systemStore.handleDelete(1);

    expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/', {params: {id: 1}});
    expect(systemStore.page).toBe(1);
  });

  it('fetchRecord 走详情端点', async () => {
    const {systemStore} = freshStores();
    mockHttpGet.mockResolvedValue({id: 5, name: '测控系统'});

    await systemStore.fetchRecord(5);

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/detail/', {params: {id: 5}});
  });
});

describe('关系维护 store 请求行为', () => {
  it('fetchRecords 按 system_id 组装参数', async () => {
    const {relationStore} = freshStores();
    relationStore.setSystem(5);
    relationStore.f_status = 'active';
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await relationStore.fetchRecords();

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      params: {system_id: 5, page: 1, page_size: 20, status: 'active'}
    });
  });

  it('fetchRecords 支持全局查询与系统/状态/关键字筛选', async () => {
    const {relationStore} = freshStores();
    relationStore.f_system_id = 7;
    relationStore.f_status = 'ended';
    relationStore.f_keyword = 'EL';
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await relationStore.fetchRecords();

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      params: {page: 1, page_size: 20, system_id: 7, status: 'ended', keyword: 'EL'}
    });
  });

  it('无固定系统范围时不携带 system_id（全局列表）', async () => {
    const {relationStore} = freshStores();
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await relationStore.fetchRecords();

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      params: {page: 1, page_size: 20}
    });
  });

  it('fetchDeviceRelations 按设备查询关系（多对多设备侧视图）', async () => {
    const {relationStore} = freshStores();
    mockHttpGet.mockResolvedValue({data: [{id: 1, system_name: '系统A'}], total: 1});

    await relationStore.fetchDeviceRelations(9);

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      params: {device_id: 9, page_size: 50}
    });
    expect(relationStore.deviceRelations).toEqual([{id: 1, system_name: '系统A'}]);
    expect(relationStore.deviceRelationsLoading).toBe(false);
  });

  it('handleAdd 在设备上下文中同时刷新设备视角关系列表', async () => {
    const {relationStore} = freshStores();
    relationStore.deviceId = 9;
    mockHttpPost.mockResolvedValue({id: 1});
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await relationStore.handleAdd({system_id: 1, device_id: 9, role: 'member'});

    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      system_id: 1, device_id: 9, role: 'member'
    });
    // 设备详情弹窗内新增关系后，该设备视角的关系列表被联动刷新
    const deviceCalls = mockHttpGet.mock.calls.filter(
      call => call[1] && call[1].params && call[1].params.device_id === 9);
    expect(deviceCalls.length).toBe(1);
  });

  it('handleExit 调用退出端点并刷新列表', async () => {
    const {relationStore} = freshStores();
    relationStore.setSystem(5);
    mockHttpPost.mockResolvedValue({id: 1, status: 'ended'});
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    await relationStore.handleExit(1);

    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/exit/', {id: 1});
  });

  it('handleAdd 提交完整关系 payload', async () => {
    const {relationStore} = freshStores();
    relationStore.setSystem(5);
    mockHttpPost.mockResolvedValue({id: 2});
    mockHttpGet.mockResolvedValue({data: [], total: 0});

    const payload = {
      system_id: 5, device_id: 8, role: 'primary', is_primary: true,
      valid_from: '2026-01-01', valid_to: '', remark: '',
    };
    await relationStore.handleAdd(payload);

    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', payload);
  });

  it('searchDevices 按关键字查询设备选项', async () => {
    const {relationStore} = freshStores();
    mockHttpGet.mockResolvedValue([{id: 8, device_sn: 'EL-1', device_name: '雷达'}]);

    await relationStore.searchDevices('EL');

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      params: {device_options: 1, keyword: 'EL'}
    });
    expect(relationStore.deviceOptions).toEqual([{id: 8, device_sn: 'EL-1', device_name: '雷达'}]);
  });

  it('searchDevices 空关键字返回设备列表（弹窗打开即加载）', async () => {
    const {relationStore} = freshStores();
    mockHttpGet.mockResolvedValue([{id: 8, device_sn: 'EL-1', device_name: '雷达'}]);

    await relationStore.searchDevices('');

    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      params: {device_options: 1, keyword: ''}
    });
  });
});

describe('系统列表页渲染', () => {
  let container = null;

  function renderPage() {
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<SystemIndex/>, container);
    });
  }

  afterEach(() => {
    if (container) {
      act(() => {
        ReactDOM.unmountComponentAtNode(container);
      });
      container.remove();
      container = null;
    }
  });

  const listPayload = {
    data: [{id: 5, name: '测控系统', code: 'CK-01', description: '描述',
            active_device_count: 3, created_at: '2026-09-04 10:00:00'}],
    total: 1, page: 1, page_size: 20,
  };

  it('无权限时页面不渲染任何内容且不发起请求', () => {
    grantPerms([]);
    renderPage();
    expect(container.textContent).toBe('');
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('view-only 可见列表但无维护按钮，详情点击跳转详情路由', async () => {
    grantPerms([PERM_SYSTEM_VIEW]);
    mockHttpGet.mockResolvedValue(listPayload);
    renderPage();
    await flush();

    const text = container.textContent;
    expect(text).toContain('测控系统');
    expect(text).toContain('CK-01');
    expect(text).not.toContain('新增系统');
    expect(text).not.toContain('编辑');
    expect(text).not.toContain('删除');

    const detailBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.trim() === '详情');
    act(() => {
      Simulate.click(detailBtn);
    });
    expect(mockHistoryPush).toHaveBeenCalledWith('/equipment-lifecycle/systems/detail/5');
  });

  it('manage 权限出现新增/编辑/删除入口', async () => {
    grantPerms([PERM_SYSTEM_VIEW, PERM_SYSTEM_MANAGE]);
    mockHttpGet.mockResolvedValue(listPayload);
    renderPage();
    await flush();

    const text = container.textContent;
    expect(text).toContain('新增系统');
    expect(text).toContain('编辑');
    expect(text).toContain('删除');
  });
});

describe('系统详情页（关系维护）渲染', () => {
  let container = null;

  function renderDetail(id = 5) {
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<SystemDetail match={{params: {id}}}/>, container);
    });
  }

  afterEach(() => {
    if (container) {
      act(() => {
        ReactDOM.unmountComponentAtNode(container);
      });
      container.remove();
      container = null;
    }
  });

  const systemDetail = {
    id: 5, name: '测控系统', code: 'CK-01', description: '系统描述',
    active_device_count: 2, created_at: '2026-09-04 10:00:00',
  };
  const relationsPayload = {
    data: [
      {id: 1, device_sn: 'EL-DEV-001', device_name: '雷达', role: 'primary', role_text: '主用',
       is_primary: true, valid_from: '2026-01-01', valid_to: null,
       status: 'active', status_text: '生效中', remark: ''},
      {id: 2, device_sn: 'EL-DEV-002', device_name: '电台', role: 'backup', role_text: '备用',
       is_primary: false, valid_from: '2025-01-01', valid_to: '2025-06-01',
       status: 'ended', status_text: '已退出', remark: ''},
    ],
    total: 2, page: 1, page_size: 20,
  };

  function mockDetailApi() {
    mockHttpGet.mockImplementation((url) => {
      if (url === '/api/equipment-lifecycle/systems/detail/') {
        return Promise.resolve(systemDetail);
      }
      if (url === '/api/equipment-lifecycle/system-relations/') {
        return Promise.resolve(relationsPayload);
      }
      return Promise.resolve({});
    });
  }

  it('加载系统详情与关系列表并渲染', async () => {
    grantPerms([PERM_SYSTEM_VIEW, PERM_RELATION_VIEW, PERM_RELATION_MANAGE]);
    mockDetailApi();
    renderDetail();
    await flush();

    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/detail/', {params: {id: 5}});
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      params: {system_id: 5, page: 1, page_size: 20}
    });

    const text = container.textContent;
    expect(text).toContain('测控系统');
    expect(text).toContain('EL-DEV-001');
    expect(text).toContain('主用');
    expect(text).toContain('长期');
    // 已退出行展示历史标记，生效行有退出入口
    expect(text).toContain('历史记录');
    expect(text).toContain('退出');
    expect(text).toContain('新增关系');
  });

  it('无 relation.view 权限时关系维护区不渲染', async () => {
    grantPerms([PERM_SYSTEM_VIEW]);
    mockDetailApi();
    renderDetail();
    await flush();

    const text = container.textContent;
    expect(text).toContain('测控系统');
    expect(text).not.toContain('设备编号');
    expect(text).not.toContain('新增关系');
  });
});

describe('设备关系独立页面渲染', () => {
  let container = null;

  function renderRelationsPage() {
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<EquipmentLifecycleRelations/>, container);
    });
  }

  afterEach(() => {
    if (container) {
      act(() => {
        ReactDOM.unmountComponentAtNode(container);
      });
      container.remove();
      container = null;
    }
  });

  const relationsPayload = {
    data: [
      {id: 1, system_name: '全局系统A', device_sn: 'EL-DEV-001', device_name: '雷达',
       role: 'primary', role_text: '主用', is_primary: true, valid_from: '2026-01-01',
       valid_to: null, status: 'active', status_text: '生效中', remark: ''},
      {id: 2, system_name: '全局系统B', device_sn: 'EL-DEV-002', device_name: '电台',
       role: 'member', role_text: '组成单元', is_primary: false, valid_from: '2025-01-01',
       valid_to: '2025-06-01', status: 'ended', status_text: '已退出', remark: ''},
    ],
    total: 2, page: 1, page_size: 20,
  };

  function mockRelationsApi() {
    mockHttpGet.mockImplementation((url, config) => {
      if (config && config.params && config.params.system_options) {
        return Promise.resolve([
          {id: 1, name: '全局系统A', code: 'A'},
          {id: 2, name: '全局系统B', code: ''},
        ]);
      }
      if (config && config.params && config.params.device_options) {
        return Promise.resolve([
          {id: 8, device_sn: 'EL-DEV-001', device_name: '雷达'},
          {id: 9, device_sn: 'EL-DEV-002', device_name: '电台'},
        ]);
      }
      return Promise.resolve(relationsPayload);
    });
  }

  it('无权限时页面不渲染任何内容且不发起请求', () => {
    grantPerms([]);
    renderRelationsPage();
    expect(container.textContent).toBe('');
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('view-only 跨系统查看关系列表（含系统名与历史标记），无维护按钮', async () => {
    grantPerms([PERM_RELATION_VIEW]);
    mockRelationsApi();
    renderRelationsPage();
    await flush();

    const text = container.textContent;
    expect(text).toContain('全局系统A');
    expect(text).toContain('全局系统B');
    expect(text).toContain('EL-DEV-001');
    expect(text).toContain('主用');
    expect(text).toContain('历史记录');
    expect(text).not.toContain('新增关系');
    // 退出是操作按钮（状态列的"已退出"文本不算）——按按钮元素断言
    const btnTexts = Array.from(container.querySelectorAll('button')).map(b => b.textContent);
    expect(btnTexts.some(t => t.includes('退出'))).toBe(false);

    // 全局列表：不按系统过滤
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-relations/', {
      params: {page: 1, page_size: 20}
    });
  });

  it('manage 权限出现新增/编辑/退出入口', async () => {
    grantPerms([PERM_RELATION_VIEW, PERM_RELATION_MANAGE]);
    mockRelationsApi();
    renderRelationsPage();
    await flush();

    const text = container.textContent;
    expect(text).toContain('新增关系');
    expect(text).toContain('编辑');
    expect(text).toContain('退出');
  });

  it('点击新增关系打开弹窗（系统可选模式）并加载系统选项', async () => {
    grantPerms([PERM_RELATION_VIEW, PERM_RELATION_MANAGE]);
    mockRelationsApi();
    renderRelationsPage();
    await flush();

    const addBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('新增关系'));
    act(() => {
      Simulate.click(addBtn);
    });
    await flush();

    // 系统可选模式：弹窗打开时加载系统下拉选项；设备选项同步预加载
    const optionCalls = mockHttpGet.mock.calls.filter(
      call => call[1] && call[1].params && call[1].params.system_options);
    expect(optionCalls.length).toBeGreaterThan(0);
    const deviceOptionCalls = mockHttpGet.mock.calls.filter(
      call => call[1] && call[1].params && call[1].params.device_options === 1);
    expect(deviceOptionCalls.length).toBeGreaterThan(0);
    // 弹窗渲染到 document.body，包含系统/设备/角色/时间段字段
    expect(document.body.textContent).toContain('所属系统');
    expect(document.body.textContent).toContain('设备');
    expect(document.body.textContent).toContain('关系角色');
    expect(document.body.textContent).toContain('生效日期');
  });
});
