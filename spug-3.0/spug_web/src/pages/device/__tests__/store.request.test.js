/**
 * 设备台账/履历 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与筛选参数（keyword 同时匹配编号/名称、状态数组）
 * - 成功后 records（res.data）/ total 更新，isFetching 复位；业务失败数据保留
 * - fetchFilterOptions 拉取使用单位与设备型号选项
 * - fetchEvents 组装设备/分页/事件类型筛选参数
 * - setEventTypeFilter：all 归零、重置页码并刷新
 * - 设备 CRUD：新增/更新成功后关闭弹窗并刷新；删除以查询参数携带 id
 * - 事件提交防重复（isSubmittingEvent 期间直接拒绝）
 * - showDetail 重置事件分页与筛选；resetFilter / getExportParams
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
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
  mockHttpDelete.mockReset();
});

describe('设备档案 Store fetchRecords', () => {
  it('组装分页与筛选参数', () => {
    const store = freshStore();
    store.page = 2;
    store.pageSize = 50;
    store.f_device_sn = 'DEV-关键字';
    store.f_device_model = '型号X';
    store.f_current_status = ['1', '2'];
    store.f_use_unit = '使用单位A';
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/device/device-resume/', {
      params: {
        page: 2,
        page_size: 50,
        keyword: 'DEV-关键字',
        device_model: '型号X',
        current_status: ['1', '2'],
        use_unit: '使用单位A',
      },
    });
  });

  it('成功后更新 records 与 total 并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({data: [{id: 1, device_sn: 'DEV-1'}], total: 1});
    store.fetchRecords();
    await flush();
    expect(store.isFetching).toBe(false);
    expect(store.records).toEqual([{id: 1, device_sn: 'DEV-1'}]);
    expect(store.total).toBe(1);
  });

  it('业务失败：记录保留且 isFetching 复位（catch 兜底提示）', async () => {
    const store = freshStore();
    store.records = [{id: 9, device_sn: 'DEV-旧'}];
    mockHttpGet.mockRejectedValue(new Error('获取设备列表失败'));
    store.fetchRecords();
    await flush();
    expect(store.records).toEqual([{id: 9, device_sn: 'DEV-旧'}]);
    expect(store.isFetching).toBe(false);
  });
});

describe('设备档案 Store 筛选选项与事件列表', () => {
  it('fetchFilterOptions 拉取使用单位与设备型号', async () => {
    const store = freshStore();
    mockHttpGet.mockImplementation((url) => Promise.resolve(
      String(url).includes('use_units') ? ['单位A', '单位B'] : ['型号X', '型号Y']
    ));
    await store.fetchFilterOptions();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/device/device-resume/?use_units=1');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/device/device-resume/?device_models=1');
    expect(store.useUnits).toEqual(['单位A', '单位B']);
    expect(store.deviceModels).toEqual(['型号X', '型号Y']);
  });

  it('fetchEvents 组装设备/分页/类型筛选参数', async () => {
    const store = freshStore();
    store.eventPage = 2;
    store.eventPageSize = 50;
    store.eventTypeFilter = '3';
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.fetchEvents(7);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/device/device-event/', {
      params: {device_resume_id: 7, page: 2, page_size: 50, event_type: '3'},
    });
  });

  it('setEventTypeFilter：all 归零、具体类型保留、重置页码并刷新', () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.eventPage = 3;
    store.setEventTypeFilter('all', 7);
    expect(store.eventTypeFilter).toBeNull();
    expect(store.eventPage).toBe(1);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/device/device-event/', {
      params: expect.objectContaining({device_resume_id: 7, page: 1}),
    });

    store.setEventTypeFilter('2', 7);
    expect(store.eventTypeFilter).toBe('2');
  });
});

describe('设备档案 CRUD', () => {
  it('handleAdd 成功后关闭弹窗并刷新列表', async () => {
    const store = freshStore();
    store.formVisible = true;
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.handleAdd({device_sn: 'DEV-2'});
    expect(mockHttpPost).toHaveBeenCalledWith('/api/device/device-resume/', {device_sn: 'DEV-2'});
    expect(store.formVisible).toBe(false);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/device/device-resume/', {
      params: expect.objectContaining({page: 1}),
    });
  });

  it('handleUpdate 以 PUT 提交并刷新', async () => {
    const store = freshStore();
    mockHttpPut.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.handleUpdate({id: 5, device_sn: 'DEV-2B'});
    expect(mockHttpPut).toHaveBeenCalledWith('/api/device/device-resume/', {id: 5, device_sn: 'DEV-2B'});
    expect(store.formVisible).toBe(false);
  });

  it('handleDelete 以查询参数携带 id 并刷新', async () => {
    const store = freshStore();
    mockHttpDelete.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.handleDelete(5);
    expect(mockHttpDelete).toHaveBeenCalledWith('/api/device/device-resume/', {params: {id: 5}});
  });
});

describe('事件提交防重复', () => {
  it('isSubmittingEvent 期间的第二次提交直接拒绝', async () => {
    const store = freshStore();
    const first = deferred();
    mockHttpPost.mockReturnValue(first.promise);
    const p1 = store.handleAddEvent({device_resume_id: 7, event_type: '1'});
    expect(store.isSubmittingEvent).toBe(true);
    // 提交中再次提交：立即拒绝且不再发起请求
    await expect(store.handleAddEvent({device_resume_id: 7, event_type: '2'}))
      .rejects.toThrow('正在提交中，请勿重复操作');
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    // 第一次提交完成：复位提交状态并刷新事件列表
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    first.resolve({});
    await p1;
    await flush();
    expect(store.isSubmittingEvent).toBe(false);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/device/device-event/', {
      params: expect.objectContaining({device_resume_id: 7}),
    });
  });
});

describe('设备详情与筛选重置', () => {
  it('showDetail 重置事件分页与筛选并拉取事件', () => {
    const store = freshStore();
    store.eventPage = 3;
    store.eventTypeFilter = '2';
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.showDetail({id: 7, device_sn: 'DEV-7'});
    expect(store.detailVisible).toBe(true);
    expect(store.record.id).toBe(7);
    expect(store.eventPage).toBe(1);
    expect(store.eventTypeFilter).toBeNull();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/device/device-event/', {
      params: expect.objectContaining({device_resume_id: 7, page: 1}),
    });
  });

  it('resetFilter 清空筛选并回到第一页重新请求', () => {
    const store = freshStore();
    store.f_device_sn = 'DEV-关键字';
    store.f_device_model = '型号X';
    store.f_current_status = ['1'];
    store.f_use_unit = '单位A';
    store.page = 4;
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.resetFilter();
    expect(store.f_device_sn).toBeNull();
    expect(store.f_device_model).toBeNull();
    expect(store.f_current_status).toEqual([]);
    expect(store.f_use_unit).toBeNull();
    expect(store.page).toBe(1);
  });

  it('getExportParams 与列表筛选一致且不含分页参数', () => {
    const store = freshStore();
    store.f_device_sn = 'DEV-关键字';
    store.f_current_status = ['1', '2'];
    expect(store.getExportParams()).toEqual({keyword: 'DEV-关键字', current_status: ['1', '2']});
  });
});
