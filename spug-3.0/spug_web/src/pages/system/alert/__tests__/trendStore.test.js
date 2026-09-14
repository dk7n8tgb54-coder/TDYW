const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn()},
}));

const deferred = () => {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return {promise, resolve};
};

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../store').default;
}

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('磁盘趋势 Store', () => {
  it('时间跨度快速切换时只应用最新请求的结果', async () => {
    const store = freshStore();
    const oldRequest = deferred();
    const newRequest = deferred();
    mockHttpGet
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const oldPromise = store.setTrendHours(6);
    const newPromise = store.setTrendHours(168);
    newRequest.resolve({series: [{name: 'new'}]});
    await newPromise;
    oldRequest.resolve({series: [{name: 'old'}]});
    await oldPromise;

    expect(mockHttpGet).toHaveBeenNthCalledWith(1, '/api/alert/trend/', {params: {hours: 6}});
    expect(mockHttpGet).toHaveBeenNthCalledWith(2, '/api/alert/trend/', {params: {hours: 168}});
    expect(store.trendHours).toBe(168);
    expect(store.trendData).toEqual([{name: 'new'}]);
    expect(store.trendLoading).toBe(false);
  });
});
