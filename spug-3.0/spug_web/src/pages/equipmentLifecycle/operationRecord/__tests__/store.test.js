/**
 * 运行处置记录——统一 Store 契约测试（2026-10-11 合并改造）。
 * 真实加载 Store（MobX legacy decorators），mock libs.http，验证：
 * - 列表/详情/进展/附件请求指向统一 /records/ 路由并携带筛选参数；
 * - 状态动作端点：完成跟进 complete / 认定设备故障 identify-fault /
 *   确认恢复并结案 recover / 撤销登记 cancel / 原因分析 reason-analysis；
 * - 统一进展追加与更正端点（成功后全量刷新详情/进展/列表）；仅一般记录删除端点；
 * - 系统详情页签请求 systems/<id>/records/；待办与统计端点。
 * 2026-10-14 体验二轮：列表/待办/统计失败置失败标记（页面据此提示重试，
 * 不把旧结果冒充新查询结果）；待办带分页与分组筛选参数；导出参数与
 * 列表筛选完全一致。
 */
const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

const moment = require('moment');

beforeEach(() => {
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  mockHttpGet.mockResolvedValue({data: [], total: 0});
  mockHttpPost.mockResolvedValue({});
  mockHttpPut.mockResolvedValue({});
  mockHttpDelete.mockResolvedValue({});
});

function loadStore() {
  let store;
  jest.isolateModules(() => {
    store = require('../store').default;
  });
  return store;
}

describe('运行处置记录 Store——列表/表单/动作端点', () => {
  it('fetchRecords 请求统一列表路由并携带筛选参数', async () => {
    const store = loadStore();
    store.page = 2;
    store.f_keyword = 'UPS';
    store.f_record_type = 'fault';
    store.f_status = 'handling';
    store.f_system = 7;
    store.f_category = 'signal';
    await store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    const [url, config] = mockHttpGet.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/records/');
    expect(config.params).toMatchObject({
      page: 2, keyword: 'UPS', record_type: 'fault',
      status: 'handling', system: 7, category: 'signal',
    });
  });

  it('submitForm 编辑走 PUT / 新建走 POST', async () => {
    const store = loadStore();
    store.record = {id: 5};
    await store.submitForm({title: 'x'});
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/records/5/', {title: 'x'});
    store.record = {};
    await store.submitForm({title: 'y'});
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/records/', {title: 'y'});
  });

  it('状态动作端点完整：complete / identify-fault / recover / cancel / reason-analysis', async () => {
    const store = loadStore();
    store.detailId = 9;
    await store.completeFollowUp({});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/complete/', {});
    await store.identifyFault({affects_system_operation: true, impact_status: 'fault'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/identify-fault/',
      {affects_system_operation: true, impact_status: 'fault'});
    await store.confirmRecoverAndClose({recovery_close_note: '结案'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/recover/', {recovery_close_note: '结案'});
    await store.cancelRecord({cancel_reason: '误报'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/cancel/', {cancel_reason: '误报'});
    await store.saveReasonAnalysis({reason_analysis: '天馈进水'});
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/reason-analysis/', {reason_analysis: '天馈进水'});
  });

  it('统一进展追加与更正端点，成功后全量刷新详情/进展/列表', async () => {
    const store = loadStore();
    store.detailId = 9;
    await store.addProgressRecord({content: '现场检查'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/progress/', {content: '现场检查'});
    // 追加进展改变最新进展时间/持续时间：详情、进展与主列表全量刷新
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/9/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/9/progress/');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/',
      expect.objectContaining({params: expect.objectContaining({page: 1})}));
    mockHttpGet.mockClear();
    await store.correctProgressRecord(3, {content: '更正', correction_reason: '笔误'});
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/progress/3/',
      {content: '更正', correction_reason: '笔误'});
    // 更正可修改处理时间：两列真实数据同样随详情与列表刷新（此前仅刷进展）
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/9/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/9/progress/');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/', expect.anything());
  });

  it('删除仅走 DELETE /records/<id>/', async () => {
    const store = loadStore();
    store.detailId = 9;
    await store.deleteRecord();
    expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/records/9/');
  });

  it('系统详情页签请求 systems/<id>/records/ 并透传筛选', async () => {
    const store = loadStore();
    await store.fetchSystemRecords(7, {record_type: 'abnormal'});
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/', {params: {record_type: 'abnormal'}});
  });
});

describe('运行处置记录 Store——待办分页/失败标记/导出参数（2026-10-14）', () => {
  it('待办与统计端点：待办带分页/类型筛选参数', async () => {
    const store = loadStore();
    await store.fetchTodoRecords();
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/todo/',
      {params: {page: 1, page_size: 20}});
    store.f_todo_record_type = 'fault';
    store.todoPage = 2;
    await store.fetchTodoRecords();
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/records/todo/',
      {params: {page: 2, page_size: 20, record_type: 'fault'}});
    store.f_stats_record_type = 'fault';
    await store.fetchStatistics();
    const [url, config] = mockHttpGet.mock.calls[mockHttpGet.mock.calls.length - 1];
    expect(url).toBe('/api/equipment-lifecycle/records/statistics/');
    expect(config.params.record_type).toBe('fault');
  });

  it('待办分组筛选重置页码；失败置 todoError，成功清除', async () => {
    const store = loadStore();
    store.todoPage = 3;
    await store.setTodoRecordType('abnormal');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/todo/',
      {params: {page: 1, page_size: 20, record_type: 'abnormal'}});
    expect(store.todoPage).toBe(1);
    mockHttpGet.mockRejectedValueOnce('boom');
    await store.fetchTodoRecords();
    expect(store.todoError).toBe(true);
    mockHttpGet.mockResolvedValue({data: [], total: 0, counts: {total: 0}});
    await store.fetchTodoRecords();
    expect(store.todoError).toBe(false);
  });

  it('列表失败置 fetchError、成功清除；导出参数与列表筛选完全一致', async () => {
    const store = loadStore();
    mockHttpGet.mockRejectedValueOnce('boom');
    await store.fetchRecords();
    expect(store.fetchError).toBe(true);
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.fetchRecords();
    expect(store.fetchError).toBe(false);
    store.f_keyword = 'UPS';
    store.f_record_type = 'fault';
    store.f_occurred_range = [
      moment('2026-10-01 00:00'), moment('2026-10-14 10:30')];
    expect(store.hasActiveFilter).toBe(true);
    expect(store.getExportParams()).toMatchObject({
      keyword: 'UPS', record_type: 'fault',
      occurred_from: '2026-10-01 00:00', occurred_to: '2026-10-14 10:30',
    });
    store.resetFilter();
    expect(store.hasActiveFilter).toBe(false);
    expect(store.getExportParams()).toEqual({});
  });
});
