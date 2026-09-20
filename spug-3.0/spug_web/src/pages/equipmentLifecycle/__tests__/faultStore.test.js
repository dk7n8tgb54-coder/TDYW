/**
 * 设备全生命周期（步骤 3.1）故障 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与筛选参数（状态/级别/系统 ID/发生时间）
 * - fetchSystems 拉取候选系统（供选择器展示名称、提交 ID）
 * - submitForm 新增走 POST、编辑走 PUT，payload 原样透传系统 ID
 * - 状态动作（开始处置/恢复/关闭/作废）调用明确动作端点，
 *   成功后重新获取详情、处置记录与列表（重新获取真实数据）
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

describe('故障 Store', () => {
  it('fetchRecords 组装分页与筛选参数（系统以 ID 传递）', () => {
    const store = freshStore();
    store.page = 3;
    store.pageSize = 10;
    store.f_keyword = '丢包';
    store.f_status = 'handling';
    store.f_level = 'major';
    store.f_system = 42;
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/', {
      params: {
        page: 3, page_size: 10, keyword: '丢包',
        status: 'handling', level: 'major', system: 42,
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

  it('submitForm 新增走 POST、编辑走 PUT，成功后关闭弹窗并刷新列表', async () => {
    const store = freshStore();
    const payload = {
      system: 7,
      impact_status: 'degraded',
      occurred_at: '2026-09-18 08:30',
      discovery: 'patrol',
      level: 'major',
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

  it('状态动作调用明确动作端点，成功后刷新详情/处置记录/列表', async () => {
    const store = freshStore();
    store.detailId = 8;
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.startHandling();
    expect(mockHttpPost).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/faults/8/start/', {});
    await store.confirmRecover({
      recovered_at: '2026-09-18 10:00', recover_confirm: '已恢复'});
    expect(mockHttpPost).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/faults/8/recover/',
      {recovered_at: '2026-09-18 10:00', recover_confirm: '已恢复'});
    await store.closeFault({final_result: '更换板卡'});
    expect(mockHttpPost).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/faults/8/close/', {final_result: '更换板卡'});
    await store.cancelFault({cancel_reason: '误报'});
    expect(mockHttpPost).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/faults/8/cancel/', {cancel_reason: '误报'});
    // 动作成功后重新获取了详情与列表（真实数据刷新）
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/8/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/8/handling-records/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/faults/', {params: {page: 1, page_size: 20}});
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
