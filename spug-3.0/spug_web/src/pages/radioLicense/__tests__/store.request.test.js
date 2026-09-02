/**
 * 无线电执照 Store 请求行为测试（上线门禁）。
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，
 * 验证：
 * - fetchRecords 组装分页与筛选参数正确
 * - 成功后 records/total/pageNum/pageSize 更新，isFetching 复位
 * - HTTP 200 + error（promise reject）时记录不被覆盖、isFetching 复位
 * - 快速切换筛选条件时，旧请求响应不得覆盖新结果（六.6）
 * - 删除最后一页最后一条记录后分页回退行为（A7）
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  X_TOKEN: 'test-token',
}));

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../store').default;
}

// store.fetchRecords 不返回 promise，需用宏任务冲刷微任务链
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
});

describe('无线电执照 Store fetchRecords', () => {
  it('组装分页与筛选参数', () => {
    const store = freshStore();
    store.pageNum = 3;
    store.pageSize = 50;
    store.f_station_name = 'RG-台站';
    store.f_purpose = 'RG-用途';
    store.f_status = 'expiring';
    store.f_valid_to_range = ['2026-01-01', '2026-12-31'];
    mockHttpGet.mockReturnValue(deferred().promise);
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/radio-license/', {
      params: {
        page: 3,
        page_size: 50,
        station_name: 'RG-台站',
        purpose: 'RG-用途',
        status: 'expiring',
        valid_to_start: '2026-01-01',
        valid_to_end: '2026-12-31',
      },
    });
  });

  it('成功后更新列表数据并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({
      records: [{id: 1, station_name: 'RG-A'}],
      total: 1,
      page: 1,
      page_size: 20,
    });
    expect(store.isFetching).toBe(false);
    const pending = store.fetchRecords();
    expect(store.isFetching).toBe(true);
    await pending;
    await flush();
    expect(store.isFetching).toBe(false);
    expect(store.records).toHaveLength(1);
    expect(store.total).toBe(1);
    expect(store.pageNum).toBe(1);
  });

  it('HTTP 200 + error 业务失败：数据不更新且 isFetching 复位', async () => {
    const store = freshStore();
    store.records = [{id: 9, station_name: 'RG-旧数据'}];
    // libs/http.js 对业务错误返回 reject(errorMsg)
    mockHttpGet.mockRejectedValue('服务器内部错误，请联系管理员');
    await store.fetchRecords();
    await flush();
    expect(store.records).toEqual([{id: 9, station_name: 'RG-旧数据'}]);
    expect(store.isFetching).toBe(false);
  });

  it('旧请求响应不得覆盖新请求结果（快速切换筛选）', async () => {
    const store = freshStore();
    const first = deferred();
    const second = deferred();
    // 第一次请求（慢）：筛选 A
    mockHttpGet.mockReturnValueOnce(first.promise);
    store.f_station_name = 'RG-筛选A';
    const p1 = store.fetchRecords();
    // 用户立即切换筛选 B（快）：新请求
    mockHttpGet.mockReturnValueOnce(second.promise);
    store.f_station_name = 'RG-筛选B';
    const p2 = store.fetchRecords();
    // 新请求先返回
    second.resolve({records: [{id: 2, station_name: 'RG-新结果'}], total: 1, page: 1, page_size: 20});
    await p2;
    await flush();
    expect(store.records[0].station_name).toBe('RG-新结果');
    // 旧请求后返回：不得覆盖新结果
    first.resolve({records: [{id: 1, station_name: 'RG-旧结果'}], total: 1, page: 1, page_size: 20});
    await p1;
    await flush();
    expect(store.records[0].station_name).toBe('RG-新结果');
  });

  it('删除最后一页最后一条记录后分页应回退（当前页为空时）', async () => {
    const store = freshStore();
    store.pageNum = 2;
    store.pageSize = 10;
    store.total = 11;
    // 删除后只剩 10 条：第 2 页为空
    mockHttpGet.mockResolvedValue({records: [], total: 10, page: 2, page_size: 10});
    await store.fetchRecords();
    // 期望：页码应回退到有效页（1），当前页不再为空
    expect(store.pageNum).toBe(1);
    expect(store.records).not.toHaveLength(0);
  });
});

describe('无线电执照 Store 责任人列表', () => {
  it('按 token 缓存，token 变化后强制重拉', async () => {
    const store = freshStore();
    sessionStorage.setItem('token', 'token-A');
    mockHttpGet.mockResolvedValue([{id: 1, nickname: 'RG-用户A', username: 'a'}]);
    await store.fetchResponsibleUsers();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(store.responsibleUsersLoaded).toBe(true);

    // 同 token：直接用缓存，不再发请求
    await store.fetchResponsibleUsers();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);

    // 切换账号（token 变化）：强制重拉，避免残留上一账号租户数据
    sessionStorage.setItem('token', 'token-B');
    mockHttpGet.mockResolvedValue([{id: 2, nickname: 'RG-用户B', username: 'b'}]);
    await store.fetchResponsibleUsers();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
    expect(store.responsibleUsers[0].nickname).toBe('RG-用户B');
    sessionStorage.removeItem('token');
  });
});
