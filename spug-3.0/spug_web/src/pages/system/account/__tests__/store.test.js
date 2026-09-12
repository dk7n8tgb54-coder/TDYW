/**
 * 账户管理 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs/http，验证：
 * - dataSource：用户名大小写不敏感过滤、启用状态过滤
 * - isSupper / currentTenantId 动态读取 sessionStorage（SPA 内切换账号不缓存过期）
 * - fetchRecords：show_deleted 开关以查询参数传递
 * - showForm / showSignature 弹窗状态
 */
const mockHttpGet = jest.fn();

jest.mock('libs/http', () => ({
  __esModule: true,
  default: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
}));

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../store').default;
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const USERS = [
  {id: 1, username: 'Admin', is_active: true},
  {id: 2, username: 'operator', is_active: false},
  {id: 3, username: 'Auditor', is_active: true},
];

afterEach(() => {
  mockHttpGet.mockReset();
  sessionStorage.clear();
});

describe('账户管理 Store', () => {
  it('dataSource 用户名过滤大小写不敏感', () => {
    const store = freshStore();
    store.records = USERS;
    store.f_name = 'ADMIN';
    expect(store.dataSource.map(x => x.id)).toEqual([1]);
    store.f_name = undefined;
    store.f_name = 'aud';
    expect(store.dataSource.map(x => x.id)).toEqual([3]);
  });

  it('dataSource 按启用状态过滤（字符串比较 is_active）', () => {
    const store = freshStore();
    store.records = USERS;
    store.f_status = 'true';
    expect(store.dataSource.map(x => x.id)).toEqual([1, 3]);
    store.f_status = 'false';
    expect(store.dataSource.map(x => x.id)).toEqual([2]);
  });

  it('isSupper / currentTenantId 动态读取 sessionStorage', () => {
    const store = freshStore();
    expect(store.isSupper).toBe(false);
    sessionStorage.setItem('is_supper', 'true');
    // getter 每次读取，不缓存旧值
    expect(store.isSupper).toBe(true);
    expect(store.currentTenantId).toBe('');
    sessionStorage.setItem('tenant_id', 't1');
    expect(store.currentTenantId).toBe('t1');
  });

  it('fetchRecords：show_deleted 以查询参数传递，成功后更新记录', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue(USERS);
    store.f_show_deleted = true;
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/account/user/', {params: {show_deleted: 'true'}});
    await flush();
    expect(store.records).toEqual(USERS);
    expect(store.isFetching).toBe(false);
  });

  it('fetchRecords：默认不带 show_deleted 参数', () => {
    const store = freshStore();
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/account/user/', {params: {}});
  });

  it('showForm / showSignature 弹窗状态', () => {
    const store = freshStore();
    store.showForm({id: 1});
    expect(store.formVisible).toBe(true);
    expect(store.record.id).toBe(1);
    store.showSignature({id: 2});
    expect(store.signatureVisible).toBe(true);
    expect(store.signatureRecord.id).toBe(2);
  });
});
