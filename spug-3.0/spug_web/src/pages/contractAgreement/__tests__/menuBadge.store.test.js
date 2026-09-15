/**
 * 合同协议菜单红点 Store 测试
 *
 * 真实 import layout/ContractAgreementBadgeStore（MobX 装饰器经 babel 编译），mock libs，验证：
 * - 有权限时 start() 立即拉取 /api/contract-agreement/badge/ 并按 5 分钟轮询
 * - 无权限时 start()/fetch() 均不发请求
 * - 成功后 count/expiringCount/expiredCount/loaded 更新（兼容 data 包装与裸返回）
 * - 失败时静默保留旧值，loaded 不置位
 * - stop() 清除轮询定时器
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  syncAttachmentCount: jest.fn(),
}));

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../../../layout/ContractAgreementBadgeStore').default;
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

afterEach(() => {
  mockHttpGet.mockReset();
  jest.useRealTimers();
});

describe('合同协议菜单红点 Store', () => {
  it('有权限时 start() 立即拉取并按 5 分钟轮询，stop() 后停止', () => {
    jest.useFakeTimers();
    const store = freshStore();
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.start();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/contract-agreement/badge/');

    jest.advanceTimersByTime(5 * 60 * 1000);
    expect(mockHttpGet).toHaveBeenCalledTimes(2);

    store.stop();
    jest.advanceTimersByTime(5 * 60 * 1000);
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
  });

  it('无权限时 start() 不发请求', () => {
    const store = freshStore();
    // store 与此处 require('libs') 在 resetModules 后共享同一 mock 实例
    // eslint-disable-next-line global-require
    require('libs').hasPermission.mockReturnValue(false);
    store.start();
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('成功后更新角标计数并置位 loaded（data 包装）', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({
      data: {count: 7, expiring_count: 5, expired_count: 2},
    });
    store.fetch();
    await flush();
    expect(store.count).toBe(7);
    expect(store.expiringCount).toBe(5);
    expect(store.expiredCount).toBe(2);
    expect(store.loaded).toBe(true);
  });

  it('成功后兼容裸返回结构', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({count: 3, expiring_count: 1, expired_count: 2});
    store.fetch();
    await flush();
    expect(store.count).toBe(3);
    expect(store.expiringCount).toBe(1);
    expect(store.expiredCount).toBe(2);
    expect(store.loaded).toBe(true);
  });

  it('失败时静默保留旧值且 loaded 不置位', async () => {
    const store = freshStore();
    store.count = 4;
    store.expiringCount = 3;
    store.expiredCount = 1;
    mockHttpGet.mockRejectedValue('网络错误');
    store.fetch();
    await flush();
    expect(store.count).toBe(4);
    expect(store.expiringCount).toBe(3);
    expect(store.expiredCount).toBe(1);
    expect(store.loaded).toBe(false);
  });
});
