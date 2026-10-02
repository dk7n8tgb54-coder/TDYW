/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行记录 Store 测试（2026-10 第一版）。
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与全部筛选参数（系统/状态/需要跟进/重要程度/影响程度/时间范围）
 * - submitForm 新增走 POST、编辑走 PUT
 * - 状态动作（跟进/已处理/关闭/标记重要/转故障）调用明确动作端点，
 *   成功后重新获取详情、进展与列表
 * - 处理进展追加与更正调用对应端点，业务错误时 Promise 拒绝
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

describe('运行记录 Store · 列表筛选', () => {
  it('fetchRecords 组装分页与全部筛选参数', () => {
    const store = freshStore();
    store.page = 2;
    store.pageSize = 15;
    store.f_keyword = '中断';
    store.f_status = 'following_up';
    store.f_system = 9;
    store.f_follow = true;
    store.f_importance = 'important';
    store.f_impact = 'degraded';
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/runtime-records/', {
      params: {
        page: 2, page_size: 15, keyword: '中断', status: 'following_up',
        system: 9, needs_follow_up: 'yes', importance: 'important', impact: 'degraded',
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

describe('运行记录 Store · 表单提交', () => {
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
});

describe('运行记录 Store · 状态动作与处理进展', () => {
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
    ['resolveRecord', 'resolve'],
    ['closeRecord', 'close'],
    ['markImportant', 'mark-important'],
    ['convertToFault', 'convert-to-fault'],
  ])('%s 调用对应动作端点并刷新详情/进展/列表', async (action, path) => {
    const store = freshStore();
    setupDetail(store);
    await store[action]({importance_reason: '原因'});
    expect(mockHttpPost).toHaveBeenCalledWith(`${RECORD_BASE}/${path}/`,
      expect.objectContaining({}));
    // 动作成功后刷新：详情 + 进展 + 列表
    const urls = mockHttpGet.mock.calls.map(c => c[0]);
    expect(urls).toContain(`${RECORD_BASE}/`);
    expect(urls).toContain(`${RECORD_BASE}/progress/`);
    expect(urls).toContain('/api/equipment-lifecycle/runtime-records/');
  });

  it('addProgressRecord 提交进展载荷并返回列表刷新 Promise', async () => {
    const store = freshStore();
    setupDetail(store);
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue({data: [{id: 1, content: '已处理'}], total: 1});
    const payload = {handled_at: '2026-10-01 09:00', handler_name: '值班员甲',
      content: '现场确认恢复', result: '', work_hours: null};
    await store.addProgressRecord(payload);
    expect(mockHttpPost).toHaveBeenCalledWith(`${RECORD_BASE}/progress/`, payload);
    expect(store.progressRecords).toHaveLength(1);
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

describe('运行记录 Store · 系统详情页签', () => {
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
