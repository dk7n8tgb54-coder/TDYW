/**
 * 设备全生命周期（步骤 3.1）故障 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与筛选参数（状态/系统 ID/发生时间；级别筛选已随字段退役删除）
 * - fetchSystems 拉取候选系统（供选择器展示名称、提交 ID）
 * - submitForm 新增走 POST、编辑走 PUT，payload 原样透传系统 ID
 * - 状态动作（确认恢复并结案/作废）调用明确动作端点，
 *   成功后重新获取详情、处置记录与列表（重新获取真实数据）；
 *   2026-10 流程合并：无"开始处置"与单独关闭动作（新建即处置中，
 *   确认恢复与结案一次提交）
 * - 处置记录添加与更正调用对应端点
 * - 后端业务错误（http reject）时不显示成功提示路径（Promise 拒绝，不关闭弹窗）
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
  return require('../faultStore').default;
}

afterEach(() => {
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

describe('故障 Store · 列表与候选系统', () => {
  it('fetchRecords 组装分页与筛选参数（系统以 ID 传递）', () => {
    const store = freshStore();
    store.page = 3;
    store.pageSize = 10;
    store.f_keyword = '丢包';
    store.f_status = 'handling';
    store.f_system = 42;
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/', {
      params: {
        page: 3, page_size: 10, keyword: '丢包',
        status: 'handling', system: 42,
      },
    });
  });

  it('fetchSystems 拉取候选系统列表', async () => {
    const store = freshStore();
    const systems = [{id: 1, system_code: 'S1', name: '系统A', install_location: '机房A'}];
    mockHttpGet.mockResolvedValue({data: systems});
    await store.fetchSystems();
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/faults/candidate-systems/');
    expect(store.systems).toEqual(systems);
  });

});

describe('故障 Store · 表单提交', () => {
  it('submitForm 新增走 POST、编辑走 PUT，成功后关闭弹窗并刷新列表', async () => {
    const store = freshStore();
    const payload = {
      system: 7,
      impact_status: 'degraded',
      occurred_at: '2026-09-18 08:30',
      phenomenon: '丢包',
    };
    mockHttpPost.mockResolvedValue({});
    mockHttpPut.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.showForm();
    await store.submitForm(payload);
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/', payload);
    expect(store.formVisible).toBe(false);
    // 编辑
    store.showForm({id: 5});
    await store.submitForm(payload);
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/5/', payload);
  });

  it('submitForm 失败（后端业务错误）时弹窗保持打开、不刷新', async () => {
    const store = freshStore();
    mockHttpPost.mockRejectedValue(new Error('故障系统不存在'));
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.showForm();
    store.formVisible = true;
    let caught = false;
    await store.submitForm({system: 1}).catch(() => {
      caught = true;
    });
    expect(caught).toBe(true);
    expect(store.formVisible).toBe(true);
  });

});

describe('故障 Store · 状态动作与处置记录', () => {
  it('确认恢复并结案调用 recover 端点，成功后刷新详情/处置记录/列表', async () => {
    const store = freshStore();
    store.detailId = 8;
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    // 2026-10 流程合并：确认恢复与关闭故障一次提交（统一结案说明一次事务）
    await store.confirmRecoverAndClose({
      recovered_at: '2026-09-18 10:00',
      recovered_by_name: '确认人甲',
      recovery_close_note: '更换板卡，已恢复'});
    expect(mockHttpPost).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/faults/8/recover/',
      {recovered_at: '2026-09-18 10:00', recovered_by_name: '确认人甲',
        recovery_close_note: '更换板卡，已恢复'});
    await store.cancelFault({cancel_reason: '误报'});
    expect(mockHttpPost).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/faults/8/cancel/', {cancel_reason: '误报'});
    // 动作成功后重新获取了详情与列表（真实数据刷新）
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/8/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/8/handling-records/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/', {params: {page: 1, page_size: 20}});
  });

  it('不再提供开始处置与单独关闭动作（合并后无 start/close 调用路径）', async () => {
    const store = freshStore();
    store.detailId = 8;
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    expect(store.startHandling).toBeUndefined();
    expect(store.closeFault).toBeUndefined();
    await store.confirmRecoverAndClose({
      recovered_at: '2026-09-18 10:00', recovered_by_name: '确认人甲',
      recovery_close_note: '已恢复'});
    await store.cancelFault({cancel_reason: '误报'});
    const posted = mockHttpPost.mock.calls.map(call => call[0]);
    expect(posted).not.toContain('/api/equipment-lifecycle/faults/8/start/');
    expect(posted).not.toContain('/api/equipment-lifecycle/faults/8/close/');
  });

  it('处置记录添加与更正调用对应端点并刷新时间线', async () => {
    const store = freshStore();
    store.detailId = 8;
    mockHttpPost.mockResolvedValue({});
    mockHttpPut.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.addHandlingRecord({handled_at: '2026-09-18 09:00', content: '现场检查'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/faults/8/handling-records/',
      {handled_at: '2026-09-18 09:00', content: '现场检查'});
    await store.correctHandlingRecord(3, {
      handled_at: '2026-09-18 09:00', content: '改后内容',
      correction_reason: '笔误'});
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/faults/8/handling-records/3/',
      {handled_at: '2026-09-18 09:00', content: '改后内容', correction_reason: '笔误'});
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/faults/8/handling-records/');
  });

});

describe('故障 Store · 详情查询', () => {
  it('fetchSystemFaults 查询本系统故障（单系统简化，无角色参数）', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({data: [{id: 1, system: 7}]});
    await store.fetchSystemFaults(7);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/faults/');
    expect(store.systemFaults.length).toBe(1);
  });

  it('fetchDetail 把后端详情（http 解包后即详情本体）赋给 store.detail', async () => {
    // 后端 FaultDetailView 返回 json_response(详情)，http 拦截器解包后
    // resolve 的就是详情 dict 本身（无 data 包裹层）
    const store = freshStore();
    const detail = {
      id: 8, fault_no: 'GZ20260919-0001', status: 'handling',
      system_name: '系统A',
    };
    mockHttpGet.mockResolvedValue(detail);
    store.detailId = 8;
    await store.fetchDetail();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/8/');
    expect(store.detail).toEqual(detail);
  });

  it('fetchDetailById 返回详情本体（供编辑表单回填）', async () => {
    const store = freshStore();
    const detail = {id: 5, fault_no: 'GZ20260919-0002', system: 7,
      impact_status: 'fault'};
    mockHttpGet.mockResolvedValue(detail);
    await expect(store.fetchDetailById(5)).resolves.toEqual(detail);
  });
});

describe('故障 Store · 请求竞态守卫（2026-09 新增处置记录后刷新状态异常缺陷）', () => {
  function deferred() {
    let resolve;
    return {promise: new Promise(r => {resolve = r;}), resolve};
  }
  const flushAsync = () => new Promise(resolve => setTimeout(resolve, 0));

  it('并发 fetchDetail 旧响应不覆盖新详情，loading 由最后一次请求关闭', async () => {
    const store = freshStore();
    store.detailId = 8;
    const older = deferred();
    const newer = deferred();
    mockHttpGet.mockImplementationOnce(() => older.promise);
    mockHttpGet.mockImplementationOnce(() => newer.promise);
    const p1 = store.fetchDetail();
    const p2 = store.fetchDetail();
    expect(store.isDetailFetching).toBe(true);
    // 旧请求先返回：不覆盖数据，也不关闭 loading（最新请求仍在途）
    older.resolve({id: 8, fault_no: 'OLD'});
    await p1;
    expect(store.detail).toEqual({});
    expect(store.isDetailFetching).toBe(true);
    // 最新请求返回：应用数据并关闭 loading
    newer.resolve({id: 8, fault_no: 'NEW'});
    await p2;
    expect(store.detail.fault_no).toBe('NEW');
    expect(store.isDetailFetching).toBe(false);
  });

  it('并发 fetchHandlingRecords 旧响应不覆盖新时间线', async () => {
    const store = freshStore();
    store.detailId = 8;
    const older = deferred();
    const newer = deferred();
    mockHttpGet.mockImplementationOnce(() => older.promise);
    mockHttpGet.mockImplementationOnce(() => newer.promise);
    const p1 = store.fetchHandlingRecords();
    const p2 = store.fetchHandlingRecords();
    older.resolve({data: [{id: 1, content: '旧记录'}], total: 1});
    await p1;
    expect(store.handlingRecords).toEqual([]);
    expect(store.isHandlingFetching).toBe(true);
    newer.resolve({data: [{id: 2, content: '新记录'}], total: 1});
    await p2;
    expect(store.handlingRecords.map(r => r.content)).toEqual(['新记录']);
    expect(store.isHandlingFetching).toBe(false);
  });

  it('新增处置记录成功后等待列表刷新完成，动作 loading 不提前结束', async () => {
    const store = freshStore();
    store.detailId = 8;
    const listFetch = deferred();
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockImplementation(() => listFetch.promise);
    let done = false;
    const p = store.addHandlingRecord({content: '现场检查'})
      .then(() => {done = true;});
    await flushAsync();
    // POST 已成功但列表 GET 在途：弹窗关闭信号（外层 Promise）与 loading 均未结束
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/faults/8/handling-records/');
    expect(done).toBe(false);
    expect(store.isActionSubmitting).toBe(true);
    listFetch.resolve({data: [{id: 2, content: '现场检查'}], total: 1});
    await p;
    expect(done).toBe(true);
    expect(store.isActionSubmitting).toBe(false);
    expect(store.handlingRecords.map(r => r.content)).toEqual(['现场检查']);
  });
});
