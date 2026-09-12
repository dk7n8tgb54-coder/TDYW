/**
 * 登录日志 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，
 * includes 使用真实 functools 实现（大小写不敏感包含匹配），验证：
 * - dataSource：IP / 用户名包含匹配、登录成败过滤
 * - fetchRecords 成功后更新记录
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => {
  const {includes} = jest.requireActual('libs/functools');
  return {
    http: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
    includes,
    hasPermission: jest.fn(() => true),
  };
});

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../store').default;
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const RECORDS = [
  {id: 1, ip: '10.0.0.1', username: 'admin', is_success: true},
  {id: 2, ip: '172.20.0.1', username: 'operator', is_success: false},
  {id: 3, ip: '10.0.0.2', username: 'admin', is_success: true},
];

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('登录日志 Store', () => {
  it('dataSource：IP 与用户名包含匹配（大小写不敏感）', () => {
    const store = freshStore();
    store.records = RECORDS;
    store.f_ip = '10.0.0';
    expect(store.dataSource.map(x => x.id)).toEqual([1, 3]);
    store.f_ip = undefined;

    store.f_name = 'ADMIN';
    expect(store.dataSource.map(x => x.id)).toEqual([1, 3]);
    store.f_name = undefined;
  });

  it('dataSource：按登录成败过滤', () => {
    const store = freshStore();
    store.records = RECORDS;
    store.f_status = 'false';
    expect(store.dataSource.map(x => x.id)).toEqual([2]);
    store.f_status = 'true';
    expect(store.dataSource.map(x => x.id)).toEqual([1, 3]);
  });

  it('fetchRecords 成功后更新记录并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue(RECORDS);
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/account/login/history/');
    await flush();
    expect(store.records).toHaveLength(3);
    expect(store.isFetching).toBe(false);
  });
});
