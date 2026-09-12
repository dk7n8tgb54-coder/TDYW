/**
 * 操作日志 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与五类筛选参数（时间范围格式化 YYYY-MM-DD HH:mm:ss）
 * - 成功后 records / total 更新，isFetching 复位
 * - fetchOptions 拉取操作类型与对象类型选项
 * - changePage 更新分页并重新请求；resetFilters 清空筛选回到第一页
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

import moment from 'moment';

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../store').default;
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('操作日志 Store fetchRecords', () => {
  it('组装分页与筛选参数（时间范围格式化到秒）', () => {
    const store = freshStore();
    store.page = 2;
    store.pageSize = 50;
    store.f_username = 'admin';
    store.f_action = 'create';
    store.f_target_type = 'duty';
    store.f_keyword = '关键字';
    store.f_time_range = [moment('2026-09-01 00:00:00'), moment('2026-09-30 23:59:59')];
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/logs/audit/', {
      params: {
        page: 2,
        page_size: 50,
        username: 'admin',
        action: 'create',
        target_type: 'duty',
        keyword: '关键字',
        start_time: '2026-09-01 00:00:00',
        end_time: '2026-09-30 23:59:59',
      },
    });
  });

  it('成功后更新 records 与 total 并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({records: [{id: 1}], total: 1});
    store.fetchRecords();
    await flush();
    expect(store.records).toEqual([{id: 1}]);
    expect(store.total).toBe(1);
    expect(store.isFetching).toBe(false);
  });
});

describe('操作日志 Store 选项与分页', () => {
  it('fetchOptions 拉取操作类型与对象类型选项', async () => {
    const store = freshStore();
    mockHttpGet.mockImplementation((url) => Promise.resolve(
      String(url).endsWith('actions/') ? ['create', 'delete'] : ['duty', 'fault']
    ));
    await store.fetchOptions();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/logs/audit/actions/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/logs/audit/target_types/');
    expect(store.actionOptions).toEqual(['create', 'delete']);
    expect(store.targetTypeOptions).toEqual(['duty', 'fault']);
  });

  it('changePage 更新页码与页大小并重新请求', () => {
    const store = freshStore();
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.changePage(3, 50);
    expect(store.page).toBe(3);
    expect(store.pageSize).toBe(50);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/logs/audit/', {
      params: expect.objectContaining({page: 3, page_size: 50}),
    });
  });

  it('resetFilters 清空筛选回到第一页并重新请求', () => {
    const store = freshStore();
    store.f_username = 'admin';
    store.f_action = 'create';
    store.f_target_type = 'duty';
    store.f_keyword = '关键字';
    store.f_time_range = [moment('2026-09-01'), moment('2026-09-30')];
    store.page = 5;
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.resetFilters();
    expect(store.f_username).toBe('');
    expect(store.f_action).toBe('');
    expect(store.f_target_type).toBe('');
    expect(store.f_keyword).toBe('');
    expect(store.f_time_range).toBeNull();
    expect(store.page).toBe(1);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/logs/audit/', {
      params: {page: 1, page_size: 20},
    });
  });
});
