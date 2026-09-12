/**
 * 租户管理 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs/http，验证：
 * - fetchRecords 成功后更新记录并复位 isFetching
 * - showForm 弹窗状态
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

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('租户管理 Store', () => {
  it('fetchRecords 成功后更新记录并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue([{id: 1, name: '租户A'}]);
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/account/tenant/');
    await flush();
    expect(store.records).toEqual([{id: 1, name: '租户A'}]);
    expect(store.isFetching).toBe(false);
  });

  it('showForm 打开弹窗并记录当前行', () => {
    const store = freshStore();
    store.showForm({id: 2, name: '租户B'});
    expect(store.formVisible).toBe(true);
    expect(store.record.id).toBe(2);
  });
});
