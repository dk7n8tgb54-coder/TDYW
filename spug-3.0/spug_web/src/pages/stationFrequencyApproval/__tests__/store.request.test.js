/**
 * 台站频率批复 Store 请求行为测试（上线门禁）。
 *
 * 真实 import store，mock libs.http，验证：
 * - fetchRecords 参数组装与数据更新
 * - 业务失败时数据不被污染
 * - 深链 loadDetail 加载详情
 * - 旧请求不得覆盖新结果
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
  const promise = new Promise(res => {
    resolve = res;
  });
  return {promise, resolve};
}

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('批复 Store fetchRecords', () => {
  it('组装分页与筛选参数', () => {
    const store = freshStore();
    store.pageNum = 2;
    store.pageSize = 50;
    store.f_name = 'RG-批复';
    store.f_doc_no = 'RG-DOC';
    store.f_status = 'expired';
    store.f_valid_to_range = ['2026-01-01', '2026-12-31'];
    mockHttpGet.mockReturnValue(deferred().promise);
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/radio-license/approvals/', {
      params: {
        page: 2,
        page_size: 50,
        name: 'RG-批复',
        doc_no: 'RG-DOC',
        status: 'expired',
        valid_to_start: '2026-01-01',
        valid_to_end: '2026-12-31',
      },
    });
  });

  it('成功后更新列表数据', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({
      records: [{id: 1, doc_no: 'RG-DOC-1'}],
      total: 1,
      page: 1,
      page_size: 20,
    });
    await store.fetchRecords();
    await flush();
    expect(store.records).toHaveLength(1);
    expect(store.total).toBe(1);
    expect(store.isFetching).toBe(false);
  });

  it('HTTP 200 + error 业务失败：数据不更新', async () => {
    const store = freshStore();
    store.records = [{id: 9, doc_no: 'RG-旧数据'}];
    mockHttpGet.mockRejectedValue('权限拒绝');
    await store.fetchRecords();
    await flush();
    expect(store.records).toEqual([{id: 9, doc_no: 'RG-旧数据'}]);
    expect(store.isFetching).toBe(false);
  });

  it('旧请求响应不得覆盖新结果', async () => {
    const store = freshStore();
    const first = deferred();
    const second = deferred();
    mockHttpGet.mockReturnValueOnce(first.promise);
    const p1 = store.fetchRecords();
    mockHttpGet.mockReturnValueOnce(second.promise);
    const p2 = store.fetchRecords();
    second.resolve({records: [{id: 2, doc_no: 'RG-新'}], total: 1, page: 1, page_size: 20});
    await p2;
    await flush();
    expect(store.records[0].doc_no).toBe('RG-新');
    first.resolve({records: [{id: 1, doc_no: 'RG-旧'}], total: 1, page: 1, page_size: 20});
    await p1;
    await flush();
    expect(store.records[0].doc_no).toBe('RG-新');
  });
});

describe('批复 Store loadDetail 深链', () => {
  it('按 id 加载详情并写入 record', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({id: 7, name: 'RG-深链批复', doc_no: 'RG-DL-7'});
    const record = await store.loadDetail(7);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/radio-license/approvals/7/');
    expect(record.name).toBe('RG-深链批复');
    expect(store.record.name).toBe('RG-深链批复');
  });
});
