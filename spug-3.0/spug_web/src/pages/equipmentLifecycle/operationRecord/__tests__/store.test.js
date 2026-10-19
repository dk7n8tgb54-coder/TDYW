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
 * 2026-10-15 体验三轮：系统页签筛选收进 store（查询/重置/翻页/重试同一组
 * 条件），换系统重置条件；详情动作/删除后页签在位时联动刷新不显示过期行。
 * 2026-10-15 体验四轮：关键词输入草稿与已执行条件分离（列表/导出/联动刷新
 * 只用已执行条件，导出范围文案按已执行条件逐项列出）；详情加载失败置
 * detailError、重试保持当前记录与目标定位区块（2026-10-18 页签改分区后由
 * 详情组件在加载完成后消费）；快速切换记录时旧详情/旧附件的迟到
 * 响应与迟到失败不覆盖新记录。
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

// 等待在途微任务/宏任务（showDetail 派发的并发请求等）
function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
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

  it('删除成功后系统页签在位时联动刷新（不显示过期行）', async () => {
    const store = loadStore();
    store.detailId = 9;
    store.systemRecordsSystemId = 7;
    await store.deleteRecord();
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/', expect.anything());
  });
});

describe('运行处置记录 Store——系统页签筛选与联动刷新（2026-10-15）', () => {
  it('请求 systems/<id>/records/ 携带筛选/分页，失败置标记成功清除', async () => {
    const store = loadStore();
    // 首次进入系统 7（换系统重置）：只携带分页参数
    await store.fetchSystemRecords(7, 2);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      {params: {page: 2, page_size: 10}});
    // 同一系统内设置筛选后刷新（无参调用）：全量筛选参数生效
    store.sf_keyword = 'UPS';
    store.sf_status = 'handling';
    store.sf_record_type = 'fault';
    store.sf_category = 'signal';
    store.sf_occurred_range = [
      moment('2026-10-01 00:00'), moment('2026-10-14 10:30')];
    await store.fetchSystemRecords();
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      {params: {
        page: 2, page_size: 10, keyword: 'UPS', status: 'handling',
        record_type: 'fault', category: 'signal',
        occurred_from: '2026-10-01 00:00', occurred_to: '2026-10-14 10:30',
      }});
    mockHttpGet.mockRejectedValueOnce('boom');
    await store.fetchSystemRecords();
    expect(store.systemRecordsError).toBe(true);
    await store.fetchSystemRecords();
    expect(store.systemRecordsError).toBe(false);
  });

  it('换系统进入重置筛选与页码；重试/联动刷新沿用同一组条件', async () => {
    const store = loadStore();
    store.sf_keyword = 'UPS';
    store.systemRecordsPage = 3;
    // 首次进入系统 7（从无到有）：重置筛选与页码
    await store.fetchSystemRecords(7);
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      {params: {page: 1, page_size: 10}});
    // 同一系统内设置条件后翻页，重试（无参调用）沿用同组条件与页码
    store.sf_status = 'handling';
    await store.fetchSystemRecords(undefined, 2);
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      {params: {page: 2, page_size: 10, status: 'handling'}});
    await store.fetchSystemRecords();
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      {params: {page: 2, page_size: 10, status: 'handling'}});
    // 换到系统 8：筛选与页码全部重置
    await store.fetchSystemRecords(8);
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/8/records/',
      {params: {page: 1, page_size: 10}});
  });

  it('refreshSystemRecordsIfActive：页签在位时以当前条件刷新，未在位不请求', async () => {
    const store = loadStore();
    await store.refreshSystemRecordsIfActive();
    expect(mockHttpGet).not.toHaveBeenCalled();
    // 进入系统 7 后设置条件，联动刷新沿用同组条件与页码
    await store.fetchSystemRecords(7, 1);
    store.sf_keyword = 'UPS';
    mockHttpGet.mockClear();
    await store.refreshSystemRecordsIfActive();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      {params: {page: 1, page_size: 10, keyword: 'UPS'}});
    store.clearSystemRecords();
    expect(store.systemRecordsSystemId).toBe(null);
    expect(store.systemRecords).toEqual([]);
    mockHttpGet.mockClear();
    await store.refreshSystemRecordsIfActive();
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('详情状态动作成功后系统页签在位时联动刷新', async () => {
    const store = loadStore();
    store.detailId = 9;
    store.systemRecordsSystemId = 7;
    await store.completeFollowUp({});
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/9/complete/', {});
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/', expect.anything());
  });

  it('systemHasActiveFilter 区分系统无记录与筛选后无匹配', async () => {
    const store = loadStore();
    expect(store.systemHasActiveFilter).toBe(false);
    store.sf_keyword = 'UPS';
    expect(store.systemHasActiveFilter).toBe(true);
    store.resetSystemFilter();
    expect(store.systemHasActiveFilter).toBe(false);
    expect(store.systemRecordsPage).toBe(1);
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

describe('运行处置记录 Store——关键词草稿与已执行条件分离（2026-10-15）', () => {
  it('输入未查询不进列表/导出；查询提交后转正并回第 1 页；翻页不改导出条件', async () => {
    const store = loadStore();
    // 输入未查询：草稿与已执行条件分离，列表与导出均不使用
    store.setKeywordInput('UPS');
    expect(store.input_keyword).toBe('UPS');
    expect(store.f_keyword).toBeUndefined();
    await store.fetchRecords();
    expect(mockHttpGet.mock.calls[0][1].params).not.toHaveProperty('keyword');
    expect(store.getExportParams()).toEqual({});
    expect(store.exportScopeText).toBe('导出范围：全部未撤销记录');
    // 查询提交（查询按钮/回车共用）：草稿转正，列表与导出同一关键词
    store.page = 3;
    await store.commitKeyword();
    expect(store.f_keyword).toBe('UPS');
    expect(store.page).toBe(1);
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/records/',
      {params: {page: 1, page_size: 20, keyword: 'UPS'}});
    expect(store.getExportParams()).toMatchObject({keyword: 'UPS'});
    // 翻页不改变导出条件（分页不参与导出参数）
    store.page = 2;
    expect(store.getExportParams()).toMatchObject({keyword: 'UPS'});
    expect(store.getExportParams()).not.toHaveProperty('page');
    // 清空输入后提交：已执行关键词随之清除
    store.setKeywordInput('');
    await store.commitKeyword();
    expect(store.f_keyword).toBeUndefined();
    expect(store.getExportParams()).toEqual({});
  });

  it('重置同时清除关键词草稿与已执行条件', () => {
    const store = loadStore();
    store.setKeywordInput('UPS');
    store.f_keyword = 'UPS';
    store.page = 2;
    store.resetFilter();
    expect(store.input_keyword).toBe('');
    expect(store.f_keyword).toBeUndefined();
    expect(store.page).toBe(1);
  });

  it('导出范围文案逐项列出已执行条件，不含输入中的草稿', () => {
    const store = loadStore();
    expect(store.exportScopeText).toBe('导出范围：全部未撤销记录');
    store.f_system = 7;
    store.systems = [{id: 7, name: 'DVOR系统'}];
    store.f_keyword = 'UPS';
    store.f_status = 'handling';
    store.f_record_type = 'fault';
    store.f_category = 'signal';
    store.f_occurred_range = [
      moment('2026-10-01 00:00'), moment('2026-10-14 10:30')];
    const text = store.exportScopeText;
    expect(text).toContain('当前查询条件');
    expect(text).toContain('关键词「UPS」');
    expect(text).toContain('系统「DVOR系统」');
    expect(text).toContain('状态「处置中」');
    expect(text).toContain('类型「设备故障」');
    expect(text).toContain('异常类别「信号异常」');
    expect(text).toContain('2026-10-01 00:00');
    expect(text).toContain('2026-10-14 10:30');
    expect(text).toContain('分页不影响');
    // 输入中的草稿不出现在文案里
    store.setKeywordInput('未查询草稿');
    expect(store.exportScopeText).not.toContain('未查询草稿');
  });

  it('系统页签关键词草稿与已执行条件分离；换系统连草稿一并重置', async () => {
    const store = loadStore();
    // 页签挂载先建立系统上下文（componentDidMount 路径）
    await store.fetchSystemRecords(7);
    store.setSystemKeywordInput('UPS');
    expect(store.sf_input_keyword).toBe('UPS');
    expect(store.sf_keyword).toBeUndefined();
    // 查询提交：草稿转正并回第 1 页
    await store.querySystemRecords(7);
    expect(store.sf_keyword).toBe('UPS');
    expect(store.systemRecordsPage).toBe(1);
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      {params: {page: 1, page_size: 10, keyword: 'UPS'}});
    // 输入未查询：联动刷新（无参取数）只用已执行条件
    store.setSystemKeywordInput('未查询');
    mockHttpGet.mockClear();
    await store.fetchSystemRecords();
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      {params: {page: 1, page_size: 10, keyword: 'UPS'}});
    // 换系统：条件与草稿一并重置
    await store.fetchSystemRecords(8);
    expect(store.sf_input_keyword).toBe('');
    expect(store.sf_keyword).toBeUndefined();
  });
});

describe('运行处置记录 Store——详情加载失败/重试/竞态（2026-10-15）', () => {
  it('详情加载失败置 detailError、重试成功清除并写入详情本体', async () => {
    const store = loadStore();
    mockHttpGet.mockRejectedValueOnce('boom');
    await store.showDetail(11);
    await flush();
    expect(store.detailError).toBe(true);
    expect(store.isDetailFetching).toBe(false);
    expect(store.detailId).toBe(11);
    // 重试成功：清除失败标记并写入详情本体
    mockHttpGet.mockResolvedValueOnce({id: 11, record_no: 'JL-11'});
    await store.retryDetailLoad();
    expect(store.detailError).toBe(false);
    expect(store.detail).toMatchObject({id: 11, record_no: 'JL-11'});
  });

  it('重试保持当前记录与目标定位区块，重发详情/进展请求', async () => {
    const store = loadStore();
    await store.showDetail(11);
    await flush();
    // 定位目标由详情组件在内容加载完成后消费，Store 层重试不改动它
    store.pendingSection = 'progress';
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue({id: 11, record_no: 'JL-11'});
    await store.retryDetailLoad();
    expect(store.detailId).toBe(11);
    expect(store.pendingSection).toBe('progress');
    // 附件列表不在 Store 层重试：由详情内附件表格挂载/重试入口自行请求
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/11/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/11/progress/');
    expect(mockHttpGet).not.toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/11/attachments/');
  });

  it('showDetail 第二参设置定位目标区块，缺省从顶部展示', async () => {
    const store = loadStore();
    await store.showDetail(21, 'progress');
    expect(store.pendingSection).toBe('progress');
    await store.showDetail(22);
    expect(store.pendingSection).toBe('basic');
  });

  it('切换记录重开详情时重置失败标记', async () => {
    const store = loadStore();
    mockHttpGet.mockRejectedValueOnce('boom');
    await store.showDetail(11);
    await flush();
    expect(store.detailError).toBe(true);
    await store.showDetail(12);
    await flush();
    expect(store.detailError).toBe(false);
    expect(store.detailId).toBe(12);
  });

  it('快速切换记录：旧详情迟到成功响应不覆盖新详情', async () => {
    const store = loadStore();
    let resolveA;
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/') || url.endsWith('/attachments/')) {
        return Promise.resolve({data: [], total: 0});
      }
      if (url.endsWith('/records/11/')) {
        return new Promise((resolve) => { resolveA = resolve; });
      }
      return Promise.resolve({id: 12, record_no: 'JL-12'});
    });
    await store.showDetail(11);
    await store.showDetail(12);
    await flush();
    expect(store.detail.record_no).toBe('JL-12');
    resolveA({id: 11, record_no: 'JL-11'});
    await flush();
    expect(store.detail.record_no).toBe('JL-12');
    expect(store.detailError).toBe(false);
  });

  it('快速切换记录：旧详情迟到失败不置失败标记、不覆盖新详情', async () => {
    const store = loadStore();
    let rejectA;
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/') || url.endsWith('/attachments/')) {
        return Promise.resolve({data: [], total: 0});
      }
      if (url.endsWith('/records/11/')) {
        return new Promise((_, reject) => { rejectA = reject; });
      }
      return Promise.resolve({id: 12, record_no: 'JL-12'});
    });
    await store.showDetail(11);
    await store.showDetail(12);
    await flush();
    rejectA(new Error('late boom'));
    await flush();
    expect(store.detailError).toBe(false);
    expect(store.detail.record_no).toBe('JL-12');
  });
});

describe('运行处置记录 Store——附件列表请求与数量同步（2026-10-18）', () => {
  it('fetchAttachmentList 解析裸数组并写入数量/加载/失败状态', async () => {
    const store = loadStore();
    store.detailId = 11;
    mockHttpGet.mockResolvedValueOnce(
      [{id: 1, file_name: 'a.png'}, {id: 2, file_name: 'b.pdf'}]);
    const rows = await store.fetchAttachmentList();
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/11/attachments/');
    expect(rows).toHaveLength(2);
    expect(store.attachmentsTotal).toBe(2);
    expect(store.attachmentsError).toBe(false);
    expect(store.isAttachmentsFetching).toBe(false);
    // 失败：置失败标记且数量不变（不显示为 0）
    mockHttpGet.mockRejectedValueOnce(new Error('boom'));
    await store.fetchAttachmentList().catch(() => {});
    expect(store.attachmentsError).toBe(true);
    expect(store.attachmentsTotal).toBe(2);
    mockHttpGet.mockResolvedValueOnce({});
    await expect(store.fetchAttachmentList()).rejects.toThrow('Invalid attachment');
    expect(store.attachmentsError).toBe(true);
    expect(store.attachmentsTotal).toBe(2);
  });

  it('附件数量变化只刷新当前记录对应列表，旧回调不更新', async () => {
    const store = loadStore();
    store.detailId = 11;
    store.attachmentsTotal = 2;
    store.systemRecordsSystemId = 7;
    store.syncAttachmentCount(2, 11);
    expect(mockHttpGet).not.toHaveBeenCalled();
    store.syncAttachmentCount(3, 12);
    expect(store.attachmentsTotal).toBe(2);
    store.syncAttachmentCount(3, 11);
    await flush();
    expect(store.attachmentsTotal).toBe(3);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/', expect.any(Object));
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/', expect.any(Object));
  });

  it('快速切换记录：旧记录附件迟到响应不覆盖新记录附件', async () => {
    const store = loadStore();
    let resolveOld;
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/records/11/attachments/')) {
        return new Promise((resolve) => { resolveOld = resolve; });
      }
      if (url.endsWith('/records/12/attachments/')) {
        return Promise.resolve([{id: 2, file_name: '新附件'}]);
      }
      return Promise.resolve([]);
    });
    await store.showDetail(11);
    const staleRequest = store.fetchAttachmentList();
    // 切换记录：showDetail 使在途请求失效并重置附件状态
    await store.showDetail(12);
    expect(store.attachments).toEqual([]);
    expect(store.attachmentsTotal).toBe(0);
    const freshRows = await store.fetchAttachmentList();
    expect(freshRows).toEqual([{id: 2, file_name: '新附件'}]);
    expect(store.attachments).toEqual([{id: 2, file_name: '新附件'}]);
    expect(store.attachmentsTotal).toBe(1);
    // 旧记录迟到响应：仅拒绝，不写状态也不产出旧数据
    resolveOld([{id: 1, file_name: '旧附件'}]);
    await expect(staleRequest).rejects.toThrow('stale');
    expect(store.attachments).toEqual([{id: 2, file_name: '新附件'}]);
    expect(store.attachmentsTotal).toBe(1);
    expect(store.attachmentsError).toBe(false);
  });
});
