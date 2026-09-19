/**
 * 设备全生命周期（步骤 3.3）工单 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与筛选参数（状态/类型/优先级/来源/系统 ID）
 * - buildFormPayload 一律提交系统 ID 与幂等 client_token（不提交名称）
 * - submitForm 新增走 POST、编辑走 PUT
 * - 状态动作调用独立动作端点，成功后重新获取详情、处理记录与列表
 * - 故障生成维修工单调用于来源故障端点，携带幂等令牌
 * - 系统详情工单页签按 role（target/affected）查询
 * - 后端业务错误（http reject）时 Promise 拒绝，不进入成功提示路径
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
  const store = require('../store').default;
  // eslint-disable-next-line global-require
  const {uuid} = require('../store');
  return {store, uuid};
}

afterEach(() => {
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

describe('工单 Store（步骤 3.3）', () => {
  it('fetchRecords 组装分页与筛选参数（系统以 ID 传递）', () => {
    const {store} = freshStore();
    store.page = 2;
    store.pageSize = 15;
    store.f_keyword = '维修';
    store.f_status = 'executing';
    store.f_work_type = 'repair';
    store.f_priority = 'high';
    store.f_source_type = 'fault';
    store.f_system = 42;
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/work-orders/', {
      params: {
        page: 2, page_size: 15, keyword: '维修',
        status: 'executing', work_type: 'repair',
        priority: 'high', source_type: 'fault', system: 42,
      },
    });
  });

  it('buildFormPayload 提交系统 ID 列表与幂等令牌，计划时间格式化', () => {
    const {store} = freshStore();
    store.formToken = 'tok-abc';
    const moment = require('moment');
    const payload = store.buildFormPayload({
      title: '季度维护',
      work_type: 'special_maintenance',
      priority: 'normal',
      target_system: 7,
      affected_system_ids: [9, 11],
      work_location: '机房A',
      planned_range: [moment('2026-09-20 08:00'), moment('2026-09-20 12:00')],
    });
    // 业务关联一律提交 ID
    expect(payload.target_system).toBe(7);
    expect(payload.affected_system_ids).toEqual([9, 11]);
    expect(payload.client_token).toBe('tok-abc');
    expect(payload.planned_start).toBe('2026-09-20 08:00');
    expect(payload.planned_end).toBe('2026-09-20 12:00');
    // 不存在把系统名称当关联键的字段
    expect(payload.target_system_name).toBeUndefined();
  });

  it('submitForm 新增走 POST、编辑走 PUT，成功后关闭弹窗并刷新列表', async () => {
    const {store} = freshStore();
    store.formToken = 'tok-1';
    mockHttpPost.mockResolvedValue({});
    mockHttpPut.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    const values = {
      title: '季度维护', work_type: 'special_maintenance', priority: 'normal',
      target_system: 7, affected_system_ids: [],
    };
    await store.submitForm(values);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/',
      expect.objectContaining({title: '季度维护', target_system: 7, client_token: 'tok-1'}));

    store.record = {id: 5};
    await store.submitForm(values);
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/',
      expect.objectContaining({target_system: 7}));
    expect(store.formVisible).toBe(false);
  });

  it('状态动作调用独立动作端点，成功后重新获取真实数据', async () => {
    const {store} = freshStore();
    store.detailId = 5;
    const detail = {id: 5, status: 'pending_accept'};
    mockHttpPost.mockResolvedValue(detail);
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.accept();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/accept/', {});
    await store.dispatch({owner_id: 3, participant_ids: [4]});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/dispatch/',
      {owner_id: 3, participant_ids: [4]});
    await store.start();
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/work-orders/5/start/', {});
    await store.submitReview({process_result: '结果'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/submit-review/', {process_result: '结果'});
    await store.reviewPass({review_result: '同意'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/review-pass/', {review_result: '同意'});
    await store.reviewReturn({return_reason: '返工'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/review-return/', {return_reason: '返工'});
    await store.close();
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/work-orders/5/close/', {});
    await store.cancel({cancel_reason: '计划变更'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/cancel/', {cancel_reason: '计划变更'});
    // 动作成功后 detail 更新为后端真实返回
    expect(store.detail).toEqual(detail);
  });

  it('处理记录添加与更正调用对应端点', async () => {
    const {store} = freshStore();
    store.detailId = 5;
    mockHttpPost.mockResolvedValue({});
    mockHttpPut.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.addHandlingRecord({handled_at: '2026-09-18 10:00', content: '更换板卡'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/handling-records/',
      {handled_at: '2026-09-18 10:00', content: '更换板卡'});
    await store.correctHandlingRecord(8, {content: '更正内容', correction_reason: '笔误'});
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/work-orders/5/handling-records/8/',
      {content: '更正内容', correction_reason: '笔误'});
  });

  it('故障生成维修工单：POST 来源故障端点并携带幂等令牌', async () => {
    const {store} = freshStore();
    store.convertSource = {id: 33};
    store.formToken = 'tok-conv';
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.submitConvertFromFault({
      title: '维修工单', work_type: 'repair', priority: 'normal',
      target_system: 7, affected_system_ids: [9],
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/faults/33/create-work-order/',
      expect.objectContaining({
        work_type: 'repair', target_system: 7,
        affected_system_ids: [9], client_token: 'tok-conv',
      }));
    expect(store.convertVisible).toBe(false);
  });

  it('系统详情工单页签按 role 查询', async () => {
    const {store} = freshStore();
    const rows = [{id: 1, order_role: 'target'}];
    mockHttpGet.mockResolvedValue({data: rows});
    await store.fetchSystemOrders(7, 'affected');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/work-orders/', {params: {role: 'affected'}});
    expect(store.systemOrders).toEqual(rows);
    expect(store.systemOrderRole).toBe('affected');
  });

  it('后端业务错误（http reject）时 Promise 拒绝，不关闭弹窗不刷新', async () => {
    const {store} = freshStore();
    store.formToken = 'tok-err';
    store.formVisible = true;
    mockHttpPost.mockRejectedValue(new Error('目标系统不存在'));
    await expect(store.submitForm({
      title: 'X', work_type: 'repair', target_system: 7,
    })).rejects.toThrow('目标系统不存在');
    expect(store.formVisible).toBe(true);
  });

  it('每次 showForm 生成新的幂等令牌', () => {
    const {store} = freshStore();
    mockHttpGet.mockResolvedValue({data: []});
    store.showForm();
    const first = store.formToken;
    store.showForm();
    expect(store.formToken).toBeTruthy();
    expect(store.formToken).not.toBe(first);
  });
});
