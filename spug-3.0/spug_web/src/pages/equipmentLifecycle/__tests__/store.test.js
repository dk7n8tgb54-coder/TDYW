/**
 * 设备全生命周期（步骤二）Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与筛选参数；成功后 records/total 更新
 * - submitForm 编辑走 PUT、新增走 POST，成功后关闭弹窗并刷新列表
 * - toggleActive / deleteRecord 调用对应端点并刷新
 * - showDetail 记录详情 ID 并清理旧数据
 * （自定义字段机制已下线，fetchFormFields 与配置相关方法/用例一并移除）
 */
const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
}));

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../store').default;
}

afterEach(() => {
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
  mockHttpDelete.mockReset();
});

describe('系统列表 Store', () => {
  it('fetchRecords 组装分页与筛选参数', () => {
    const store = freshStore();
    store.page = 2;
    store.pageSize = 50;
    store.f_keyword = '通信';
    store.f_health_status = 'fault';
    store.f_is_active = false;
    store.f_use_unit = '运行一科';
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/', {
      params: {
        page: 2,
        page_size: 50,
        keyword: '通信',
        health_status: 'fault',
        is_active: false,
        use_unit: '运行一科',
      },
    });
  });

  it('成功后更新 records 与 total 并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({
      data: [{id: 1, system_code: 'SYS-1'}],
      total: 1,
    });
    store.isFetching = true;
    await store.fetchRecords();
    expect(store.records.length).toBe(1);
    expect(store.total).toBe(1);
    expect(store.isFetching).toBe(false);
  });

  it('submitForm 新增走 POST、编辑走 PUT，成功后关闭弹窗刷新', async () => {
    const store = freshStore();
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.showForm({name: '新系统'});
    await store.submitForm({name: '新系统'});
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/', {name: '新系统'});
    expect(store.formVisible).toBe(false);

    mockHttpPut.mockResolvedValue({});
    store.showForm({id: 7, name: '老系统'});
    await store.submitForm({name: '老系统改'});
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/7/', {name: '老系统改'});
    expect(store.formVisible).toBe(false);
  });

  it('toggleActive 提交 is_active 并刷新列表', async () => {
    const store = freshStore();
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.toggleActive({id: 9}, false);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/9/active/', {is_active: false});
    expect(mockHttpGet).toHaveBeenCalled();
  });

  it('deleteRecord 调用删除端点并刷新', async () => {
    const store = freshStore();
    mockHttpDelete.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.deleteRecord({id: 11});
    expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/11/');
  });
});

describe('系统详情 Store', () => {
  it('showDetail 记录 ID 并加载详情', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({id: 5, name: '系统A'});
    store.showDetail({id: 5, name: '系统A'});
    expect(store.detailId).toBe(5);
    expect(store.detailVisible).toBe(true);
    await flush();
    expect(store.detail.name).toBe('系统A');
  });

});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}
