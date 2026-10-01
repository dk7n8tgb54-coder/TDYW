/**
 * 设备全生命周期——系统履历事项分组 Store 测试
 *
 * 真实 import groupStore（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchGroups 组装分页与筛选参数（关键词/事项类型/来源类型/时间范围）
 * - 响应版本号：旧请求晚到不覆盖新状态；失败置 fetchFailed
 * - loadItemNodes：按需加载、同事项在途去重、已加载缓存、失败后可重试
 * - 展开处理：系统/事项展开键维护，收起展开行
 * - 健康状态变化抽屉：按系统查询 event_type=health，加载与失败状态
 * - 履历只读：Store 不含任何新增/修改/删除请求方法
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  const module = require('../groupStore');
  return module.default;
}

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('分组列表请求', () => {
  it('fetchGroups 组装分页与筛选参数', () => {
    const store = freshStore();
    store.page = 2;
    store.pageSize = 10;
    store.f_keyword = '故障';
    store.f_event_type = 'fault';
    store.f_source_type = 'ledger_item';
    store.f_range = ['2026-09-01 00:00', '2026-09-25 23:59'];
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchGroups();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-event-groups/', {
      params: {
        page: 2, page_size: 10,
        keyword: '故障', event_type: 'fault', source_type: 'ledger_item',
        occurred_from: '2026-09-01 00:00', occurred_to: '2026-09-25 23:59',
      },
    });
  });

  it('请求成功写入分组数据，失败置 fetchFailed（错误提示由拦截器统一处理）', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValueOnce({data: [{system: {id: 1}, items: []}], total: 1});
    await store.fetchGroups();
    expect(store.groups).toHaveLength(1);
    expect(store.fetchFailed).toBe(false);
    expect(store.isFetching).toBe(false);

    mockHttpGet.mockRejectedValueOnce(new Error('network'));
    await store.fetchGroups();
    expect(store.fetchFailed).toBe(true);
    expect(store.isFetching).toBe(false);
  });

  it('快速翻页/筛选时旧响应不覆盖新状态（版本号守卫）', async () => {
    const store = freshStore();
    let resolveFirst;
    mockHttpGet.mockImplementationOnce(() => new Promise(resolve => {
      resolveFirst = resolve;
    }));
    const first = store.fetchGroups();
    store.page = 2;
    mockHttpGet.mockResolvedValueOnce({data: [], total: 0});
    await store.fetchGroups();
    expect(store.page).toBe(2);
    // 旧请求（page=1）晚到：不覆盖当前数据与 loading 状态
    resolveFirst({data: [{system: {id: 99}, items: []}], total: 99});
    await first;
    expect(store.groups).toEqual([]);
    expect(store.isFetching).toBe(false);
  });
});

describe('事项节点按需加载', () => {
  it('展开事项时按需请求节点接口（系统+来源键）', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValueOnce({data: [{id: 1, action: 'create'}]});
    await store.loadItemNodes(5, 'fault', '9');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/system-event-groups/nodes/',
      {params: {system: 5, source_type: 'fault', source_id: '9'}});
    expect(store.itemNodes['5:fault:9'].status).toBe('done');
    expect(store.itemNodes['5:fault:9'].nodes).toHaveLength(1);
  });

  it('同事项并发展开只发一次请求；已加载事项不再重复请求', async () => {
    const store = freshStore();
    let resolveFirst;
    mockHttpGet.mockImplementationOnce(() => new Promise(resolve => {
      resolveFirst = resolve;
    }));
    const first = store.loadItemNodes(5, 'fault', '9');
    const second = store.loadItemNodes(5, 'fault', '9');
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    resolveFirst({data: []});
    await Promise.all([first, second]);

    mockHttpGet.mockClear();
    await store.loadItemNodes(5, 'fault', '9');
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('节点加载失败标记 failed，可重试', async () => {
    const store = freshStore();
    mockHttpGet.mockRejectedValueOnce(new Error('network'));
    await store.loadItemNodes(5, 'fault', '9');
    expect(store.itemNodes['5:fault:9'].status).toBe('failed');
    mockHttpGet.mockResolvedValueOnce({data: [{id: 2}]});
    await store.loadItemNodes(5, 'fault', '9');
    expect(store.itemNodes['5:fault:9'].status).toBe('done');
    expect(store.itemNodes['5:fault:9'].nodes).toHaveLength(1);
  });
});

describe('事项展开按需加载', () => {
  it('onItemExpand 展开时触发节点加载，收起与重复展开不再请求', () => {
    const store = freshStore();
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    const record = {source_type: 'fault', source_id: '9'};
    store.onItemExpand(true, record, 5);
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    // 收起：不触发请求
    store.onItemExpand(false, record, 5);
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    // 重复展开：命中缓存不请求（由 loadItemNodes 去重，这里仍在途）
    store.onItemExpand(true, record, 5);
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
  });

  it('无来源对象的事项展开不发起请求', () => {
    const store = freshStore();
    store.onItemExpand(true, {source_type: 'ledger_item', source_id: ''}, 5);
    expect(mockHttpGet).not.toHaveBeenCalled();
  });
});

describe('健康状态变化抽屉', () => {
  it('打开抽屉按系统查询健康状态事件（event_type=health）', async () => {
    const store = freshStore();
    const group = {system: {id: 7, name: '烟台通信系统'}};
    mockHttpGet.mockResolvedValueOnce({data: [{id: 1, title: '状态变化'}]});
    store.openHealthDrawer(group);
    expect(store.healthDrawer.visible).toBe(true);
    expect(store.healthDrawer.systemName).toBe('烟台通信系统');
    expect(store.healthDrawer.loading).toBe(true);
    await Promise.resolve();
    await Promise.resolve();
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/system-events/',
      {params: {page: 1, page_size: 200, event_type: 'health'}});
    expect(store.healthDrawer.records).toHaveLength(1);
    expect(store.healthDrawer.loading).toBe(false);
  });

  it('健康状态查询失败置 failed，不影响抽屉关闭', async () => {
    const store = freshStore();
    mockHttpGet.mockRejectedValueOnce(new Error('network'));
    store.openHealthDrawer({system: {id: 7, name: 'X'}});
    await Promise.resolve();
    await Promise.resolve();
    expect(store.healthDrawer.failed).toBe(true);
    store.closeHealthDrawer();
    expect(store.healthDrawer.visible).toBe(false);
  });
});

describe('只读约束', () => {
  it('分组 Store 不含新增/修改/删除请求方法', () => {
    const store = freshStore();
    expect(store.fetchGroups).toBeInstanceOf(Function);
    expect(store.loadItemNodes).toBeInstanceOf(Function);
    expect(store.post).toBeUndefined();
    expect(store.put).toBeUndefined();
    expect(store.delete).toBeUndefined();
    expect(Object.getOwnPropertyNames(Object.getPrototypeOf(store)))
      .not.toContain('create');
  });
});
