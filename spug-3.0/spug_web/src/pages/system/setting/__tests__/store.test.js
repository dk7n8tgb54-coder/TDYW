/**
 * 系统设置 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs/http，验证：
 * - fetchSettings 成功后更新 settings 并复位 isFetching
 * - update 局部更新设置项
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

describe('系统设置 Store', () => {
  it('fetchSettings 成功后更新 settings 并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({bind_ip: false, default_repo: 'repo-x'});
    store.fetchSettings();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/setting/');
    await flush();
    expect(store.settings).toEqual({bind_ip: false, default_repo: 'repo-x'});
    expect(store.isFetching).toBe(false);
  });

  it('update 局部更新设置项', () => {
    const store = freshStore();
    store.settings = {bind_ip: false};
    store.update('bind_ip', true);
    expect(store.settings.bind_ip).toBe(true);
  });
});
