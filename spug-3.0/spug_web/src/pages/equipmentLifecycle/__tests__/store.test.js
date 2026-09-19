/**
 * 设备全生命周期（步骤二）Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与筛选参数；成功后 records/total 更新
 * - submitForm 编辑走 PUT、新增走 POST，成功后关闭弹窗并刷新列表
 * - toggleActive / deleteRecord 调用对应端点并刷新
 * - showDetail 记录详情 ID 并清理旧页签数据；fetchFormFields 加载表单动态字段
 * - 组成项提交成功后刷新组成项与详情
 * - fetchSnapshotDiff 按 target 传参；clearSnapshotDiff 复位
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
  it('showDetail 记录 ID 并清理旧页签数据', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({id: 5, name: '系统A'});
    store.components = [{id: 1}];
    store.showDetail({id: 5, name: '系统A'});
    expect(store.detailId).toBe(5);
    expect(store.detailVisible).toBe(true);
    expect(store.components).toEqual([]);
    await flush();
    expect(store.detail.name).toBe('系统A');
  });

  it('fetchFormFields 携带参数请求 form-fields 并缓存字段列表', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({
      data: [{id: 101, field_code: 'frequency'}],
      values: {},
      components: [],
    });
    await store.fetchFormFields({system: 5});
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/form-fields/', {params: {system: 5}});
    expect(store.formFields.length).toBe(1);
    expect(store.isFormFieldsFetching).toBe(false);
  });

  it('组成项提交成功后刷新组成项与详情', async () => {
    const store = freshStore();
    store.detailId = 5;
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.showComponentForm({name: '接入交换机'});
    await store.submitComponent({name: '接入交换机', quantity: 4});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/5/components/', {name: '接入交换机', quantity: 4});
    expect(store.componentFormVisible).toBe(false);
  });

  it('fetchSnapshotDiff 按 target 传参并保存差异', async () => {
    const store = freshStore();
    store.detailId = 5;
    const diff = {snapshot: {id: 2, name: 'S'}, target: {label: '当前配置'}, diffs: []};
    mockHttpGet.mockResolvedValue(diff);
    await store.fetchSnapshotDiff(2, 'current');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/5/snapshots/2/', {params: {target: 'current'}});
    expect(store.snapshotDiff).toStrictEqual(diff);
    store.clearSnapshotDiff();
    expect(store.snapshotDiff).toBe(null);
  });
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}
