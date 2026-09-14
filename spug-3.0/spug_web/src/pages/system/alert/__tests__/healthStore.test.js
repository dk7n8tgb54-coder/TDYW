/**
 * 系统告警平台健康 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetch 并行拉取趋势与近 7 天汇总，更新 items / state / summary
 * - setHours 更新时间窗并重新请求（携带新的 hours 参数）
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../healthStore').default;
}

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('平台健康 Store', () => {
  it('fetch 并行拉取趋势与汇总并更新状态', async () => {
    const store = freshStore();
    mockHttpGet.mockImplementation((url) => Promise.resolve(
      String(url).includes('summary') ? {items: [{day: '2026-09-12'}]} : {items: [{t: 1}], state: 'healthy'}
    ));
    await store.fetch();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/alert/run-metrics/', {params: {hours: 48}});
    expect(mockHttpGet).toHaveBeenCalledWith('/api/alert/run-metrics/summary/', {params: {days: 7}});
    expect(store.items).toEqual([{t: 1}]);
    expect(store.state).toBe('healthy');
    expect(store.summary).toEqual([{day: '2026-09-12'}]);
    expect(store.loading).toBe(false);
  });

  it('接口缺省字段时兜底为空数组 / unknown', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({});
    await store.fetch();
    expect(store.items).toEqual([]);
    expect(store.summary).toEqual([]);
    expect(store.state).toBe('unknown');
  });

  it('setHours 更新时间窗并携带新参数重新请求', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({});
    await store.setHours(24);
    expect(store.hours).toBe(24);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/alert/run-metrics/', {params: {hours: 24}});
  });

  it('时间跨度快速切换时只应用最新请求的结果', async () => {
    const store = freshStore();
    const deferred = () => {
      let resolve;
      const promise = new Promise(r => { resolve = r; });
      return {promise, resolve};
    };
    const oldTrend = deferred();
    const oldSummary = deferred();
    const newTrend = deferred();
    const newSummary = deferred();
    mockHttpGet
      .mockReturnValueOnce(oldTrend.promise)
      .mockReturnValueOnce(oldSummary.promise)
      .mockReturnValueOnce(newTrend.promise)
      .mockReturnValueOnce(newSummary.promise);

    const oldRequest = store.setHours(24);
    const newRequest = store.setHours(168);
    newTrend.resolve({items: [{bucket: 'new'}], state: 'healthy'});
    newSummary.resolve({items: [{day: 'new'}]});
    await newRequest;
    oldTrend.resolve({items: [{bucket: 'old'}], state: 'degraded'});
    oldSummary.resolve({items: [{day: 'old'}]});
    await oldRequest;

    expect(store.hours).toBe(168);
    expect(store.items).toEqual([{bucket: 'new'}]);
    expect(store.state).toBe('healthy');
    expect(store.summary).toEqual([{day: 'new'}]);
    expect(store.loading).toBe(false);
  });
});
