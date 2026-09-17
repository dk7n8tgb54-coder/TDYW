/**
 * 合同协议 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与七类筛选参数（含 has_fee 布尔与日期范围）
 * - 成功后 records / total / pageNum / pageSize 更新，isFetching 复位
 * - HTTP 200 + error（promise reject）时记录不被覆盖、isFetching 复位（catch 兜底）
 * - fetchDetail：拉取详情并进入详情态；无 id 直接返回 null 不发请求
 * - 责任人列表按登录 token 缓存，token 变化后强制重拉（跨账号残留防护）
 * - showForm / showDetail 互斥切换
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
  return require('../store').default;
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

afterEach(() => {
  mockHttpGet.mockReset();
  sessionStorage.removeItem('token');
});

describe('合同协议 Store fetchRecords', () => {
  it('组装分页与筛选参数', () => {
    const store = freshStore();
    store.pageNum = 2;
    store.pageSize = 50;
    store.f_contract_name = 'CA-合同名';
    store.f_contract_no = 'HT-001';
    store.f_contract_type = 'device_purchase';
    store.f_status = 'expiring';
    store.f_signing_party = 'CA-签约方';
    store.f_has_fee = false;
    store.f_valid_end_range = ['2026-01-01', '2026-12-31'];
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/contract-agreement/', {
      params: {
        page: 2,
        page_size: 50,
        contract_name: 'CA-合同名',
        contract_no: 'HT-001',
        contract_type: 'device_purchase',
        status: 'expiring',
        signing_party: 'CA-签约方',
        has_fee: false,
        valid_end_from: '2026-01-01',
        valid_end_to: '2026-12-31',
      },
    });
  });

  it('无筛选时只携带分页参数', () => {
    const store = freshStore();
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    const {params} = mockHttpGet.mock.calls[0][1];
    expect(params).toEqual({page: 1, page_size: 20});
  });

  it('状态筛选可提交 long_term 且状态选项包含长期有效', () => {
    const store = freshStore();
    store.f_status = 'long_term';
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    const {params} = mockHttpGet.mock.calls[0][1];
    expect(params.status).toBe('long_term');
    // 筛选下拉的选项来自 store.statusOptions，必须含「长期有效」
    expect(store.statusOptions).toContainEqual({value: 'long_term', label: '长期有效'});
  });

  it('成功后更新列表数据并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({
      records: [{id: 1, contract_name: 'CA-A'}],
      total: 1,
      page: 1,
      page_size: 20,
    });
    store.fetchRecords();
    await flush();
    expect(store.isFetching).toBe(false);
    expect(store.records).toHaveLength(1);
    expect(store.total).toBe(1);
  });

  it('HTTP 200 + error 业务失败：数据不更新且 isFetching 复位', async () => {
    const store = freshStore();
    store.records = [{id: 9, contract_name: 'CA-旧数据'}];
    mockHttpGet.mockRejectedValue('服务器内部错误，请联系管理员');
    store.fetchRecords();
    await flush();
    expect(store.records).toEqual([{id: 9, contract_name: 'CA-旧数据'}]);
    expect(store.isFetching).toBe(false);
  });
});

describe('合同协议 Store fetchDetail', () => {
  it('拉取详情并进入详情态', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({id: 5, contract_name: 'CA-详情'});
    const data = await store.fetchDetail(5);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/contract-agreement/5/');
    expect(data).toEqual({id: 5, contract_name: 'CA-详情'});
    expect(store.detailVisible).toBe(true);
    expect(store.record.contract_name).toBe('CA-详情');
  });

  it('无 id 时直接返回 null 不发请求', async () => {
    const store = freshStore();
    const data = await store.fetchDetail(null);
    expect(data).toBeNull();
    expect(mockHttpGet).not.toHaveBeenCalled();
  });
});

describe('合同协议 Store 责任人列表', () => {
  it('按 token 缓存，token 变化后强制重拉', async () => {
    const store = freshStore();
    sessionStorage.setItem('token', 'token-A');
    mockHttpGet.mockResolvedValue([{id: 1, nickname: 'CA-用户A', username: 'a'}]);
    await store.fetchResponsibleUsers();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(store.responsibleUsersLoaded).toBe(true);

    // 同 token：直接用缓存，不再发请求
    await store.fetchResponsibleUsers();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);

    // 切换账号（token 变化）：强制重拉，避免残留上一账号租户数据
    sessionStorage.setItem('token', 'token-B');
    mockHttpGet.mockResolvedValue([{id: 2, nickname: 'CA-用户B', username: 'b'}]);
    await store.fetchResponsibleUsers();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
    expect(store.responsibleUsers[0].nickname).toBe('CA-用户B');
  });
});

describe('合同协议 Store 弹窗状态', () => {
  it('showForm / showDetail 互斥切换', () => {
    const store = freshStore();
    store.showDetail({id: 5});
    expect(store.detailVisible).toBe(true);
    expect(store.formVisible).toBe(false);

    store.showForm({id: 5});
    expect(store.formVisible).toBe(true);
    expect(store.detailVisible).toBe(false);
    expect(store.record).toEqual({id: 5});
  });
});
