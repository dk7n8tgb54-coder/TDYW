/**
 * 运行与故障记录——统一 Store 契约测试（2026-10-11 合并改造）。
 * 真实加载 Store（MobX legacy decorators），mock libs.http，验证：
 * - 列表/详情/进展/附件请求指向统一 /records/ 路由并携带筛选参数；
 * - 状态动作端点：完成跟进 complete / 认定正式故障 identify-fault /
 *   确认恢复并结案 recover / 撤销登记 cancel / 原因分析 reason-analysis；
 * - 统一进展追加与更正端点；仅日常运行删除端点；
 * - 系统详情页签请求 systems/<id>/records/；待办与统计端点。
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

describe('运行与故障记录 Store', () => {
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

  it('统一进展追加与更正端点', async () => {
    const store = loadStore();
    store.detailId = 9;
    await store.addProgressRecord({content: '现场检查'});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/progress/', {content: '现场检查'});
    await store.correctProgressRecord(3, {content: '更正', correction_reason: '笔误'});
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/progress/3/',
      {content: '更正', correction_reason: '笔误'});
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

  it('待办与统计端点', async () => {
    const store = loadStore();
    await store.fetchTodoRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/todo/');
    store.f_stats_record_type = 'fault';
    await store.fetchStatistics();
    const [url, config] = mockHttpGet.mock.calls[mockHttpGet.mock.calls.length - 1];
    expect(url).toBe('/api/equipment-lifecycle/records/statistics/');
    expect(config.params.record_type).toBe('fault');
  });
});
