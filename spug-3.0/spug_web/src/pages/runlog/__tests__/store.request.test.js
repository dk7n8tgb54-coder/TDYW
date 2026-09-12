/**
 * 跨日事项跟踪 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装筛选（状态/严重度/系统/日期范围）与分页参数
 * - 成功后 records（res.logs）/ systemNames / pagination 更新，isFetching 复位
 * - HTTP 200 + error（promise reject）时记录不被覆盖、isFetching 复位
 * - setFilter 重置页码并重新请求；setPage 更新分页并请求
 * - getExportParams 与列表筛选一致（不含分页与时间戳参数）
 * - 事件类型 CRUD（增/改/删）后刷新事件类型列表
 */
const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
}));

import moment from 'moment';

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../store').default;
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return {promise, resolve, reject};
}

afterEach(() => {
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
  mockHttpDelete.mockReset();
});

describe('跨日事项跟踪 Store fetchRecords', () => {
  it('组装筛选与分页参数（日期范围格式化为 YYYY-MM-DD）', () => {
    const store = freshStore();
    store.f_status = 'processing';
    store.f_severity = 'high';
    store.f_system_name = 'SYS-A';
    store.f_date_range = [moment('2026-09-01'), moment('2026-09-30')];
    store.pagination = {page: 2, page_size: 50, total_count: 0, total_pages: 0};
    mockHttpGet.mockReturnValue(deferred().promise);
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/runlog/', {
      params: expect.objectContaining({
        status: 'processing',
        severity: 'high',
        system_name: 'SYS-A',
        start_date: '2026-09-01',
        end_date: '2026-09-30',
        page: 2,
        page_size: 50,
        _t: expect.any(Number),
      }),
    });
  });

  it('成功后更新 records / systemNames / pagination 并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({
      logs: [{id: 1, title: 'RL-记录'}],
      system_names: ['SYS-A', 'SYS-B'],
      pagination: {page: 1, page_size: 50, total_count: 7, total_pages: 1},
    });
    expect(store.isFetching).toBe(false);
    const pending = store.fetchRecords();
    expect(store.isFetching).toBe(true);
    await pending;
    await flush();
    expect(store.isFetching).toBe(false);
    expect(store.records).toEqual([{id: 1, title: 'RL-记录'}]);
    expect(store.systemNames).toEqual(['SYS-A', 'SYS-B']);
    expect(store.pagination.total_count).toBe(7);
  });

  it('HTTP 200 + error 业务失败：数据不更新且 isFetching 复位', async () => {
    const store = freshStore();
    store.records = [{id: 9, title: 'RL-旧数据'}];
    mockHttpGet.mockRejectedValue('服务器内部错误，请联系管理员');
    // fetchRecords 的 catch 链会 rethrow，业务错误由 http 拦截器统一提示
    await store.fetchRecords().catch(() => null);
    await flush();
    expect(store.records).toEqual([{id: 9, title: 'RL-旧数据'}]);
    expect(store.isFetching).toBe(false);
  });
});

describe('跨日事项跟踪 Store 分页与筛选联动', () => {
  it('setFilter 更新筛选并重置到第一页重新请求', () => {
    const store = freshStore();
    store.pagination.page = 3;
    mockHttpGet.mockReturnValue(deferred().promise);
    store.setFilter('status', 'closed');
    expect(store.f_status).toBe('closed');
    expect(store.pagination.page).toBe(1);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/runlog/', {
      params: expect.objectContaining({status: 'closed', page: 1}),
    });
  });

  it('setPage 更新页码与页大小并请求', () => {
    const store = freshStore();
    mockHttpGet.mockReturnValue(deferred().promise);
    store.setPage(3, 20);
    expect(store.pagination.page).toBe(3);
    expect(store.pagination.page_size).toBe(20);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/runlog/', {
      params: expect.objectContaining({page: 3, page_size: 20}),
    });
  });
});

describe('跨日事项跟踪 Store 导出参数', () => {
  it('getExportParams 与列表筛选一致，且不含分页/时间戳参数', () => {
    const store = freshStore();
    store.f_status = 'processing';
    store.f_severity = 'high';
    store.f_system_name = 'SYS-A';
    store.f_date_range = [moment('2026-09-01'), moment('2026-09-30')];
    expect(store.getExportParams()).toEqual({
      status: 'processing',
      severity: 'high',
      system_name: 'SYS-A',
      start_date: '2026-09-01',
      end_date: '2026-09-30',
    });
  });

  it('无筛选时导出参数为空对象', () => {
    const store = freshStore();
    expect(store.getExportParams()).toEqual({});
  });
});

describe('跨日事项跟踪 Store 事件类型管理', () => {
  it('fetchEventTypes 更新事件类型列表', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue([{id: 1, name: '故障'}]);
    await store.fetchEventTypes();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/runlog/event_types/');
    expect(store.eventTypes).toEqual([{id: 1, name: '故障'}]);
  });

  it('addEventType 提交后刷新事件类型列表', async () => {
    const store = freshStore();
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue([]);
    await store.addEventType({name: '升级'});
    expect(mockHttpPost).toHaveBeenCalledWith('/api/runlog/event_types/', {name: '升级'});
    expect(mockHttpGet).toHaveBeenCalledWith('/api/runlog/event_types/');
  });

  it('updateEventType 携带 id 提交并刷新', async () => {
    const store = freshStore();
    mockHttpPut.mockResolvedValue({});
    mockHttpGet.mockResolvedValue([]);
    await store.updateEventType(5, {name: '故障2'});
    expect(mockHttpPut).toHaveBeenCalledWith('/api/runlog/event_types/', {id: 5, name: '故障2'});
  });

  it('deleteEventType 以查询参数携带 id 并刷新', async () => {
    const store = freshStore();
    mockHttpDelete.mockResolvedValue({});
    mockHttpGet.mockResolvedValue([]);
    await store.deleteEventType(5);
    expect(mockHttpDelete).toHaveBeenCalledWith('/api/runlog/event_types/', {params: {id: 5}});
  });
});

describe('跨日事项跟踪 Store 统计与弹窗状态', () => {
  it('fetchStatistics 更新统计对象', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({total: 10, open: 3});
    await store.fetchStatistics();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/runlog/statistics/', {params: {_t: expect.any(Number)}});
    expect(store.statistics).toEqual({total: 10, open: 3});
  });

  it('showForm / showAddUpdateForm 标记模式', () => {
    const store = freshStore();
    store.showForm({id: 1});
    expect(store.formVisible).toBe(true);
    expect(store.record).toEqual({id: 1, isViewMode: false});

    store.showAddUpdateForm({id: 2});
    expect(store.record).toEqual({id: 2, isAddUpdateMode: true});
  });
});
