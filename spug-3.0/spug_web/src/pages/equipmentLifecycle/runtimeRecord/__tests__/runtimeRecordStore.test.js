/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行异常记录 Store 测试（2026-10 第一版；2026-10-05 第四版：研判不再是
 * 必经步骤）。真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与全部筛选参数（系统/状态/需要跟进/异常类别/时间范围；
 *   重要程度/影响程度筛选已随字段删除移除 2026-10-06）
 * - submitForm 新增走 POST、编辑走 PUT
 * - 状态动作（修改跟进计划/完成跟进/转故障）调用明确动作端点，
 *   成功后重新获取详情、进展与列表；研判（triage）/close/no-follow-up/
 *   标记重要（mark-important）已从 store 删除（研判弹窗整体下线，
 *   标记重要字段 2026-10-06 删除）
 * - 处理进展追加（即"跟进"动作，成功后全量刷新）与更正调用对应端点，
 *   业务错误时 Promise 拒绝
 * - 系统详情页签数据源独立（systems/<id>/runtime-records/）
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
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

describe('运行异常记录 Store · 列表筛选', () => {
  it('fetchRecords 组装分页与全部筛选参数', () => {
    const store = freshStore();
    store.page = 2;
    store.pageSize = 15;
    store.f_keyword = '中断';
    store.f_status = 'following_up';
    store.f_system = 9;
    store.f_follow = true;
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/runtime-records/', {
      params: {
        page: 2, page_size: 15, keyword: '中断', status: 'following_up',
        system: 9, needs_follow_up: 'yes',
      },
    });
  });

  it('needs_follow_up=false 时以 no 传递，未设置时不传', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.fetchRecords();
    expect(mockHttpGet.mock.calls[0][1].params.needs_follow_up).toBeUndefined();
    store.f_follow = false;
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.fetchRecords();
    expect(mockHttpGet.mock.calls[0][1].params.needs_follow_up).toBe('no');
  });
});

describe('运行异常记录 Store · 表单提交', () => {
  it('submitForm 新增走 POST、编辑走 PUT，成功后关闭弹窗并刷新列表', async () => {
    const store = freshStore();
    const payload = {system: 7, title: '标题', description: '描述',
      occurred_at: '2026-10-01 08:30', client_token: 'rt-x'};
    mockHttpPost.mockResolvedValue({});
    mockHttpPut.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.showForm();
    expect(store.formVisible).toBe(true);
    await store.submitForm(payload);
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/runtime-records/', payload);
    expect(store.formVisible).toBe(false);
    // 编辑
    store.showForm({id: 5});
    await store.submitForm({system: 7, title: '改', description: '改', occurred_at: '2026-10-01 09:00'});
    expect(mockHttpPut).toHaveBeenCalledWith('/api/equipment-lifecycle/runtime-records/5/',
      expect.objectContaining({title: '改'}));
  });

  it('submitForm 失败（业务错误）时 Promise 拒绝、弹窗保持打开', async () => {
    const store = freshStore();
    mockHttpPost.mockRejectedValue(new Error('所属系统不存在、已停用或无权限'));
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.showForm();
    store.formVisible = true;
    let caught = false;
    await store.submitForm({system: 1}).catch(() => {caught = true;});
    expect(caught).toBe(true);
    expect(store.formVisible).toBe(true);
    expect(store.isSubmitting).toBe(false);
  });

  it('新建提交成功后不自动打开详情、不调用 close 接口（只记录场景）', async () => {
    const store = freshStore();
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    store.showForm();
    await store.submitForm({
      system: 7, title: '短暂中断', description: '已自行恢复',
      occurred_at: '2026-10-04 08:30', client_token: 'rt-only-record',
    });
    // 只有一次创建请求，全程没有 close 调用
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/runtime-records/',
      expect.objectContaining({title: '短暂中断'}));
    // 表单关闭、列表刷新，且不自动打开详情窗口
    expect(store.formVisible).toBe(false);
    expect(store.detailVisible).toBe(false);
    expect(mockHttpGet.mock.calls.map(call => call[0]))
      .toContain('/api/equipment-lifecycle/runtime-records/');
  });
});

describe('运行异常记录 Store · 状态动作与处理进展', () => {
  const RECORD_BASE = '/api/equipment-lifecycle/runtime-records/11';

  function setupDetail(store) {
    // showDetail 会立即发起 详情/进展/附件 三个请求：先配置 mock 再打开详情
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 0});
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      return Promise.resolve({id: 11, status: 'recorded'});
    });
    mockHttpPost.mockResolvedValue({});
    mockHttpPut.mockResolvedValue({});
    store.showDetail({id: 11, record_no: 'YX20261001-0001', status: 'recorded'});
  }

  it.each([
    ['markFollowUp', 'follow-up'],
    ['completeFollowUp', 'resolve'],
    ['convertToFault', 'convert-to-fault'],
  ])('%s 调用对应动作端点并刷新详情/进展/列表', async (action, path) => {
    const store = freshStore();
    setupDetail(store);
    await store[action]({});
    expect(mockHttpPost).toHaveBeenCalledWith(`${RECORD_BASE}/${path}/`,
      expect.objectContaining({}));
    // 动作成功后刷新：详情 + 进展 + 列表
    const urls = mockHttpGet.mock.calls.map(c => c[0]);
    expect(urls).toContain(`${RECORD_BASE}/`);
    expect(urls).toContain(`${RECORD_BASE}/progress/`);
    expect(urls).toContain('/api/equipment-lifecycle/runtime-records/');
  });

  it('标记重要字段删除后 store 不再提供 triage/close/no-follow-up/markImportant 入口', () => {
    const store = freshStore();
    // 研判弹窗整体下线：旧研判入口与弹窗状态不再存在
    expect(store.submitTriage).toBeUndefined();
    expect(store.closeRecord).toBeUndefined();
    expect(store.markNoFollowUp).toBeUndefined();
    expect(store.triageVisible).toBeUndefined();
    // 标记重要已随字段删除移除（2026-10-06）
    expect(store.markImportant).toBeUndefined();
  });

  it('addProgressRecord（跟进动作）成功后全量刷新详情/进展/列表', async () => {
    const store = freshStore();
    setupDetail(store);
    mockHttpGet.mockClear();
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) {
        return Promise.resolve({data: [{id: 1, content: '已处理'}], total: 1});
      }
      return Promise.resolve({id: 11, status: 'following_up'});
    });
    const payload = {handled_at: '2026-10-01 09:00', handler_name: '值班员甲',
      content: '现场确认恢复', result: '', work_hours: null};
    await store.addProgressRecord(payload);
    expect(mockHttpPost).toHaveBeenCalledWith(`${RECORD_BASE}/progress/`, payload);
    // 已记录保存首条跟进记录后后端流转跟进中：全量刷新真实数据
    const urls = mockHttpGet.mock.calls.map(c => c[0]);
    expect(urls).toContain(`${RECORD_BASE}/`);
    expect(urls).toContain(`${RECORD_BASE}/progress/`);
    expect(urls).toContain('/api/equipment-lifecycle/runtime-records/');
    expect(store.progressRecords).toHaveLength(1);
  });

  it('重复问题功能下线后 store 不再提供相似/关联/标记重复入口', () => {
    // 2026-10-05 重复问题下线：旧接口后端保留，前端调用入口整体移除
    const store = freshStore();
    expect(store.fetchDuplicateLinks).toBeUndefined();
    expect(store.linkDuplicate).toBeUndefined();
    expect(store.unlinkDuplicate).toBeUndefined();
    expect(store.fetchSimilarRecords).toBeUndefined();
    expect(store.markRepeated).toBeUndefined();
    expect(store.duplicateLinks).toBeUndefined();
    expect(store.similarRecords).toBeUndefined();
  });

  it('correctProgressRecord 走 PUT 更正端点并携带更正原因', async () => {
    const store = freshStore();
    setupDetail(store);
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await store.correctProgressRecord(3, {
      handled_at: '2026-10-01 09:00', handler_name: '值班员甲',
      content: '更正后的内容', correction_reason: '笔误',
    });
    expect(mockHttpPut).toHaveBeenCalledWith(`${RECORD_BASE}/progress/3/`,
      expect.objectContaining({content: '更正后的内容', correction_reason: '笔误'}));
  });

  it('旧进展响应不覆盖新请求（requestSeq 防护）', async () => {
    const store = freshStore();
    // 进展请求按调用顺序分发：showDetail 内部请求（空）、旧请求（挂起）、新请求（新数据）
    let resolveOld;
    const progressResponses = [
      Promise.resolve({data: [], total: 0}),
      new Promise(resolve => {resolveOld = resolve;}),
      Promise.resolve({data: [{id: 2, content: '新数据'}], total: 1}),
    ];
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return progressResponses.shift();
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      return Promise.resolve({id: 11, status: 'recorded'});
    });
    store.showDetail({id: 11});
    const oldFetch = store.fetchProgressRecords();
    const newFetch = store.fetchProgressRecords();
    await newFetch;
    // 旧响应迟到：不得覆盖新数据
    resolveOld({data: [{id: 1, content: '旧数据'}], total: 1});
    await oldFetch;
    expect(store.progressRecords).toEqual([{id: 2, content: '新数据'}]);
  });
});

describe('运行异常记录 Store · 系统详情页签', () => {
  it('fetchSystemRecords 按系统查询且数据源独立', async () => {
    const store = freshStore();
    const rows = [{id: 1, record_no: 'YX20261001-0001'}];
    mockHttpGet.mockResolvedValue({data: rows, total: 1});
    await store.fetchSystemRecords(42);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/42/runtime-records/');
    expect(store.systemRecords).toEqual(rows);
  });
});
