/**
 * 合同协议菜单红点 Store 测试（2026-09 第二轮改为事件驱动刷新）
 *
 * 真实 import layout/ContractAgreementBadgeStore（MobX 装饰器经 babel 编译），mock libs，验证：
 * - 有权限时 start() 立即拉取 /api/contract-agreement/badge/，无固定轮询
 * - 无权限时 start()/fetch() 均不发请求
 * - 成功后 count/expiringCount/expiredCount/loaded 更新（兼容 data 包装与裸返回）
 * - 失败时静默保留旧值，loaded 不置位
 * - 同一自然日 focus / visible 不重复请求；stop() 后事件不再触发
 *
 * 三个 Store 的完整生命周期场景见 src/layout/__tests__/expiryBadgeStoreBase.test.js。
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
  it('有权限时 start() 立即拉取一次且无固定轮询，stop() 后事件不再触发', async () => {
    jest.useFakeTimers();
    const store = freshStore();
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.start();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/contract-agreement/badge/');

    // 事件驱动刷新：推进计时器（含 5 分钟）不产生任何新请求
    jest.advanceTimersByTime(24 * 60 * 60 * 1000);
    expect(mockHttpGet).toHaveBeenCalledTimes(1);

    store.stop();
    jest.useRealTimers();
    // stop() 后 focus / visible 事件不再触发请求
    window.dispatchEvent(new Event('focus'));
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible', configurable: true,
    });
    document.dispatchEvent(new Event('visibilitychange'));
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
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
