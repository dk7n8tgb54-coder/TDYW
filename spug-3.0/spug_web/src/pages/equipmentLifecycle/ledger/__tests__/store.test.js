/**
 * 运维台账（步骤 3.2）Store 行为测试。
 * 真实执行 Store 方法与请求参数组装，mock libs.http 返回真实响应格式。
 */
import {LedgerStore, getLedgerStore} from '../store';
import {LEDGER_TYPE, STATUS_FILTER_ALL, STATUS_FILTER_OPTIONS} from '../constants';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();
const mockExportFile = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  exportFile: (...args) => mockExportFile(...args),
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
}));

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

describe('LedgerStore', () => {
  beforeEach(() => {
    [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete, mockExportFile].forEach(fn => fn.mockReset());
  });

  test('fetchRecords 携带台账类型与筛选参数（按类型区分请求）', async () => {
    mockHttpGet.mockResolvedValue({data: [{id: 1}], total: 1, page: 1, page_size: 20});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.f_status = 'draft';
    store.page = 2;
    await store.fetchRecords();
    const [url, config] = mockHttpGet.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/ledgers/');
    expect(config.params.ledger_type).toBe('week_month');
    expect(config.params.status).toBe('draft');
    expect(config.params.page).toBe(2);
    expect(store.records).toEqual([{id: 1}]);
    expect(store.total).toBe(1);
  });

  test('deleteLedger 调用物理删除接口并在成功后重新获取列表', async () => {
    mockHttpDelete.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    const store = new LedgerStore(LEDGER_TYPE.SEASONAL);
    await store.deleteLedger(9);
    expect(mockHttpDelete).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/9/');
    await flush();
    expect(mockHttpGet).toHaveBeenCalled();
  });

  test('voidLedger 受控作废携带原因且不调用物理删除', async () => {
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    const store = new LedgerStore(LEDGER_TYPE.INSPECTION);
    await store.voidLedger(3, '录入错误');
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/3/void/', {reason: '录入错误'});
    expect(mockHttpDelete).not.toHaveBeenCalled();
  });

  test('getLedgerStore 按类型缓存且互不串扰', () => {
    const a = getLedgerStore('inspection');
    const b = getLedgerStore('inspection');
    const c = getLedgerStore('week_month');
    expect(a).toBe(b);
    expect(a).not.toBe(c);
    expect(c.ledgerType).toBe('week_month');
  });
});

describe('TemplateStore（旧可视化模板）', () => {
  test('旧可视化模板 TemplateStore 已随路线删除（2026-10）', () => {
    const storeModule = require('../store');
    expect(storeModule.TemplateStore).toBeUndefined();
    expect(storeModule.templateStore).toBeUndefined();
  });
});

describe('LedgerStore 模板分组视图（2026-10-11）', () => {
  const GROUPS_URL = '/api/equipment-lifecycle/ledgers/template-groups/';

  function flush() {
    return new Promise(resolve => setTimeout(resolve, 0));
  }

  beforeEach(() => {
    [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete, mockExportFile].forEach(fn => fn.mockReset());
    mockHttpGet.mockResolvedValue({data: [], total: 0, page: 1, page_size: 10});
  });

  test('setViewMode 切换到模板视图拉取模板组统计，切回周期视图拉取周期分组', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.setViewMode('template');
    expect(store.viewMode).toBe('template');
    let call = mockHttpGet.mock.calls.find(c => c[0] === GROUPS_URL);
    expect(call[1].params).toEqual({ledger_type: 'week_month', page: 1, page_size: 10});
    await store.setViewMode('period');
    call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/ledgers/period-groups/'));
    expect(call).toBeTruthy();
    expect(call[1].params.ledger_type).toBe('week_month');
  });

  test('fetchTemplateGroups 携带同口径筛选（关键词/状态，模板视图独立字段）', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.t_keyword = 'EL-WM';
    store.t_status = 'completed';
    store.templateGroupsPage = 2;
    await store.fetchTemplateGroups();
    const call = mockHttpGet.mock.calls.find(c => c[0] === GROUPS_URL);
    expect(call[1].params).toEqual({
      ledger_type: 'week_month', page: 2, page_size: 10,
      keyword: 'EL-WM', status: 'completed',
    });
  });

  test('模板视图筛选与周期视图筛选互不混淆（f_* 变更不影响 templateFilterParams）', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.f_keyword = '周期关键词';
    store.f_status = 'draft';
    store.t_status = 'void';
    await store.fetchTemplateGroups();
    const call = mockHttpGet.mock.calls.find(c => c[0] === GROUPS_URL);
    expect(call[1].params.status).toBe('void');
    expect(call[1].params.keyword).toBeUndefined();
  });

  test('fetchTemplateGroups 映射分页统计（组内数量不受分页影响由后端保证）', async () => {
    mockHttpGet.mockResolvedValue({
      data: [{group_key: '7', template_name: 'T', total: 3, draft: 1}],
      total: 2, page: 1, page_size: 10,
    });
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchTemplateGroups();
    expect(store.templateGroups).toHaveLength(1);
    expect(store.templateGroupsTotal).toBe(2);
  });

  test('openTemplateGroup 进入组内台账列表，fetchGroupLedgers 携带组键与筛选', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.t_status = 'draft';
    await store.openTemplateGroup({group_key: '7', template_name: '信道台账'});
    expect(store.activeGroup).toEqual({group_key: '7', group_name: '信道台账'});
    const call = mockHttpGet.mock.calls.find(c =>
      c[0] === GROUPS_URL + '7/ledgers/');
    expect(call[1].params.ledger_type).toBe('week_month');
    expect(call[1].params.status).toBe('draft');
  });

  test('backToGroups 返回组列表并保留组列表页码', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.templateGroupsPage = 3;
    await store.backToGroups();
    expect(store.activeGroup).toBeNull();
    const call = mockHttpGet.mock.calls.find(c => c[0] === GROUPS_URL);
    expect(call[1].params.page).toBe(3);
  });

  test('refresh 按视图与层级分发：周期（分组+概览）/组列表/组内', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.refresh();
    expect(mockHttpGet.mock.calls[0][0].endsWith('/ledgers/period-groups/')).toBe(true);
    // 周期视图刷新同时拉取本期工作概览（数量与列表保持一致）
    expect(mockHttpGet.mock.calls[1][0].endsWith('/ledgers/period-overview/')).toBe(true);
    store.viewMode = 'template';
    await store.refresh();
    expect(mockHttpGet.mock.calls[2][0]).toBe(GROUPS_URL);
    store.activeGroup = {group_key: '7', group_name: 'T'};
    await store.refresh();
    expect(mockHttpGet.mock.calls[3][0]).toBe(GROUPS_URL + '7/ledgers/');
  });

  test('组内视图删除台账后刷新组内列表而非周期分组', async () => {
    mockHttpDelete.mockResolvedValue({});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.viewMode = 'template';
    store.activeGroup = {group_key: '7', group_name: 'T'};
    await store.deleteLedger(5);
    expect(mockHttpDelete.mock.calls[0][0]).toBe(
      '/api/equipment-lifecycle/ledgers/5/');
    expect(mockHttpGet.mock.calls[0][0]).toBe(GROUPS_URL + '7/ledgers/');
  });

  test('无 activeGroup 时 fetchGroupLedgers 不发请求', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchGroupLedgers();
    expect(mockHttpGet).not.toHaveBeenCalled();
  });
});

describe('LedgerStore 组内批量 PDF 导出（2026-10-11）', () => {
  const EXPORT_PREVIEW = {
    group_key: '7', template_id: 7, template_name: '信道台账',
    ledger_type: 'week_month', total: 3,
    status_scope: ['completed'],
    versions: [{version_no: 1, count: 1}, {version_no: 2, count: 2}],
    max_records: 50,
  };

  beforeEach(() => {
    [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete, mockExportFile].forEach(fn => fn.mockReset());
    mockHttpGet.mockResolvedValue({data: [], total: 0});
  });

  test('openBatchExport 取确认数据（与组内列表同口径筛选）并剥层读取', async () => {
    mockHttpGet.mockResolvedValue({data: EXPORT_PREVIEW});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.t_status = 'completed';
    store.activeGroup = {group_key: '7', group_name: '信道台账'};
    await store.openBatchExport();
    const [url, config] = mockHttpGet.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/ledgers/template-groups/7/export-pdf/');
    expect(config.params).toEqual({ledger_type: 'week_month', status: 'completed'});
    expect(store.batchExportPreview).toEqual(EXPORT_PREVIEW);
    expect(store.isBatchExportFetching).toBe(false);
  });

  test('exportBatchPdf 以相同筛选 POST 交给 exportFile 二进制下载', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.activeGroup = {group_key: '7', group_name: '信道台账'};
    await store.exportBatchPdf();
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const options = mockExportFile.mock.calls[0][0];
    expect(options.url).toBe('/api/equipment-lifecycle/ledgers/template-groups/7/export-pdf/');
    expect(options.method).toBe('post');
    expect(options.params).toEqual({ledger_type: 'week_month'});
    expect(options.timeout).toBe(300000);
  });

  test('closeBatchExport 清空确认数据；无 activeGroup 两个动作均不发请求', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.batchExportPreview = EXPORT_PREVIEW;
    store.closeBatchExport();
    expect(store.batchExportPreview).toBeNull();
    await store.openBatchExport();
    await store.exportBatchPdf();
    expect(mockHttpGet).not.toHaveBeenCalled();
    expect(mockExportFile).not.toHaveBeenCalled();
  });

  test('openBatchExport 请求失败时确认数据保持为空（拦截器已提示）', async () => {
    mockHttpGet.mockRejectedValue(new Error('业务错误'));
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.activeGroup = {group_key: '7', group_name: '信道台账'};
    await store.openBatchExport();
    expect(store.batchExportPreview).toBeNull();
    expect(store.isBatchExportFetching).toBe(false);
  });
});

describe('LedgerStore 本期工作概览与周期分组增强（2026-10-14）', () => {
  const GROUPS_URL = '/api/equipment-lifecycle/ledgers/period-groups/';
  const OVERVIEW_URL = '/api/equipment-lifecycle/ledgers/period-overview/';
  const GENERATE_URL = '/api/equipment-lifecycle/ledgers/period-generate/';

  const groupsPayload = (groups) => ({data: {data: groups, total: groups.length}});

  beforeEach(() => {
    [mockHttpGet, mockHttpPost].forEach(fn => fn.mockReset());
    window.localStorage.clear();
  });

  test('fetchGroups 携带分页与筛选参数并映射分页响应（兼容旧版裸列表）', async () => {
    mockHttpGet.mockResolvedValue(groupsPayload([
      {maintenance_period: '2026-10-12', is_current: true},
      {maintenance_period: '2026-09', is_current: false},
    ]));
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.groupsPage = 2;
    store.f_keyword = 'EL-WM-20261012';
    store.f_status = 'draft';
    store.f_system = 3;
    await store.fetchGroups();
    const call = mockHttpGet.mock.calls.find(c => c[0] === GROUPS_URL);
    expect(call[1].params).toEqual({
      ledger_type: 'week_month', page: 2, page_size: 6,
      keyword: 'EL-WM-20261012', status: 'draft', system: 3,
    });
    expect(store.groups).toHaveLength(2);
    expect(store.groupsTotal).toBe(2);
    // 旧版裸列表形态不丢数据
    mockHttpGet.mockResolvedValue({data: [{maintenance_period: '2026-08'}]});
    await store.fetchGroups();
    expect(store.groups).toEqual([{maintenance_period: '2026-08'}]);
    expect(store.groupsTotal).toBe(1);
  });
});

describe('LedgerStore 展开状态持久化与跨周期恢复（2026-10-20 修复）', () => {
  const GROUPS_URL = '/api/equipment-lifecycle/ledgers/period-groups/';
  const OVERVIEW_URL = '/api/equipment-lifecycle/ledgers/period-overview/';
  const GENERATE_URL = '/api/equipment-lifecycle/ledgers/period-generate/';
  const groupsPayload = (groups) => ({data: {data: groups, total: groups.length}});

  test('首次加载默认只展开本期组，历史期次折叠', async () => {
    mockHttpGet.mockResolvedValue(groupsPayload([
      {maintenance_period: '2026-10-12', is_current: true},
      {maintenance_period: '2026-10', is_current: true},
      {maintenance_period: '2026-09', is_current: false},
    ]));
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchGroups();
    expect(store.expandedPeriodKeys.sort()).toEqual(['2026-10', '2026-10-12']);
  });

  test('展开状态持久化：手动折叠本期后刷新保留，且按台账类型隔离', async () => {
    mockHttpGet.mockResolvedValue(groupsPayload([
      {maintenance_period: '2026-10-12', is_current: true},
      {maintenance_period: '2026-09', is_current: false},
    ]));
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchGroups();
    store.togglePeriodExpanded(['2026-09']); // 用户改为只看 9 月历史组
    // 新 store（模拟刷新/重进页面）从 localStorage 恢复，不重置回默认
    const reloaded = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await reloaded.fetchGroups();
    expect(reloaded.expandedPeriodKeys).toEqual(['2026-09']);
    // 另一列表（季维护）互不串扰
    const seasonal = new LedgerStore(LEDGER_TYPE.SEASONAL);
    await seasonal.fetchGroups();
    expect(seasonal.expandedPeriodKeys).toEqual(['2026-10-12']); // 无存储状态 → 默认本期
    expect(seasonal.expandedPeriodKeys).not.toEqual(reloaded.expandedPeriodKeys);
  });

  test('跨周期恢复：滚出本期的自动展开键不再恢复，手动历史组保留（2026-10-20 缺陷回归）', async () => {
    // 上周访问时 '2026-10-12' 是本期，自动展开并随快照持久化；本周再进入，
    // 该组已不是本期，不得自动展开（否则"不属于本期的组自动展开"）
    window.localStorage.setItem(
      'el_ledger_expanded_periods_week_month',
      JSON.stringify({keys: ['2026-10-12', '2026-10', '2026-09'],
                      current: ['2026-10-12', '2026-10']}));
    mockHttpGet.mockResolvedValue(groupsPayload([
      {maintenance_period: '2026-10-19', is_current: true},  // 新的一周
      {maintenance_period: '2026-10-12', is_current: false}, // 已滚出本期
      {maintenance_period: '2026-10', is_current: true},
      {maintenance_period: '2026-09', is_current: false},
    ]));
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchGroups();
    // 当下本期（2026-10-19）自动展开；上周的自动展开被丢弃；
    // 用户上周手动展开的 9 月历史组保留
    expect(store.expandedPeriodKeys).toContain('2026-10-19');
    expect(store.expandedPeriodKeys).toContain('2026-10');
    expect(store.expandedPeriodKeys).toContain('2026-09');
    expect(store.expandedPeriodKeys).not.toContain('2026-10-12');
    // 恢复后的快照回写为当下口径（旧键被清洗）
    const snapshot = JSON.parse(
      window.localStorage.getItem('el_ledger_expanded_periods_week_month'));
    expect(snapshot.current.slice().sort()).toEqual(['2026-10', '2026-10-19']);
    expect(snapshot.keys).toEqual(store.expandedPeriodKeys.slice());
  });

  test('旧版裸数组持久化（含自动展开污染）读取时弃用，按当下本期默认展开', async () => {
    window.localStorage.setItem(
      'el_ledger_expanded_periods_week_month',
      JSON.stringify(['2026-10-12', '2026-09']));
    mockHttpGet.mockResolvedValue(groupsPayload([
      {maintenance_period: '2026-10-12', is_current: true},
      {maintenance_period: '2026-09', is_current: false},
    ]));
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchGroups();
    // 旧数组无法区分自动/手动，整体弃用：只展开当下本期
    expect(store.expandedPeriodKeys).toEqual(['2026-10-12']);
    expect(store.expandedPeriodKeys).not.toContain('2026-09');
  });
});

describe('LedgerStore 生成后展开联动与周期视图刷新', () => {
  const OVERVIEW_URL = '/api/equipment-lifecycle/ledgers/period-overview/';
  const GENERATE_URL = '/api/equipment-lifecycle/ledgers/period-generate/';
  const groupsPayload = (groups) => ({data: {data: groups, total: groups.length}});

  test('generatePeriodLedgers 成功后刷新并强制展开本期组', async () => {
    mockHttpGet.mockResolvedValue(groupsPayload([
      {maintenance_period: '2026-10-12', is_current: true},
      {maintenance_period: '2026-09', is_current: false},
    ]));
    mockHttpPost.mockResolvedValue({data: {
      created: [{id: 1, ledger_no: 'EL-WM-20261012-0001'}], skipped: [], failed: []}});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchGroups();
    store.togglePeriodExpanded(['2026-09']); // 用户先折叠了本期
    await store.generatePeriodLedgers(LEDGER_TYPE.WEEK_MONTH);
    expect(mockHttpPost).toHaveBeenCalledWith(GENERATE_URL, {ledger_type: 'week_month'});
    expect(store.expandedPeriodKeys).toEqual(expect.arrayContaining(['2026-10-12']));
    // 刷新链路：概览与分组都重新拉取
    const urls = mockHttpGet.mock.calls.map(c => c[0]);
    expect(urls).toContain(OVERVIEW_URL);
  });

  test('refresh 在周期视图同时刷新概览与分组；fetchOverview 映射概览数据', async () => {
    mockHttpGet.mockImplementation(url => {
      if (url === OVERVIEW_URL) {
        return Promise.resolve({data: {
          ledger_type: 'week_month', base_date: '2026-10-14',
          blocks: [{key: 'week', title: '本周', expected: 1, to_generate: 1}],
          unconfigured_templates: 2,
        }});
      }
      return Promise.resolve(groupsPayload([]));
    });
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.refresh();
    const overviewCall = mockHttpGet.mock.calls.find(c => c[0] === OVERVIEW_URL);
    expect(overviewCall[1].params).toEqual({ledger_type: 'week_month'});
    expect(store.overview.blocks).toHaveLength(1);
    expect(store.overview.blocks[0].title).toBe('本周');
    expect(store.overview.unconfigured_templates).toBe(2);
    expect(store.isOverviewFetching).toBe(false);
  });

  test('generatePeriodLedgers 无新增时不强制展开（保留用户当前展开状态）', async () => {
    mockHttpGet.mockResolvedValue(groupsPayload([
      {maintenance_period: '2026-10-12', is_current: true},
    ]));
    mockHttpPost.mockResolvedValue({data: {created: [], skipped: [], failed: []}});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchGroups();
    store.togglePeriodExpanded([]);
    await store.generatePeriodLedgers(LEDGER_TYPE.WEEK_MONTH);
    expect(store.expandedPeriodKeys).toEqual([]);
  });
});

describe('LedgerStore 已作废默认隐藏与"全部"筛选（2026-10-17）', () => {
  const GROUPS_URL = '/api/equipment-lifecycle/ledgers/period-groups/';
  const TEMPLATE_GROUPS_URL = '/api/equipment-lifecycle/ledgers/template-groups/';
  const OVERVIEW_URL = '/api/equipment-lifecycle/ledgers/period-overview/';
  const groupsPayload = (groups) => ({data: {data: groups, total: groups.length}});

  beforeEach(() => {
    [mockHttpGet, mockHttpPost].forEach(fn => fn.mockReset());
    window.localStorage.clear();
    mockHttpGet.mockResolvedValue(groupsPayload([]));
  });

  test('状态筛选选项含"全部"，全部/已作废/草稿/已完成齐备且与后端口径一致', () => {
    expect(STATUS_FILTER_ALL).toBe('all');
    expect(STATUS_FILTER_OPTIONS.map(o => o.value)).toEqual(
      ['all', 'draft', 'completed', 'void']);
    const labels = Object.fromEntries(STATUS_FILTER_OPTIONS.map(o => [o.value, o.label]));
    expect(labels.all).toBe('全部');
    expect(labels.draft).toBe('草稿');
    expect(labels.completed).toBe('已完成');
    expect(labels.void).toBe('已作废');
  });

  test('默认视图（未选状态）请求不携带 status 参数（后端默认不含已作废）', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.fetchGroups();
    const call = mockHttpGet.mock.calls.find(c => c[0] === GROUPS_URL);
    expect(call[1].params.status).toBeUndefined();
  });

  test('选择"全部"后周期分组与明细 CSV 导出请求携带 status=all', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.f_status = STATUS_FILTER_ALL;
    await store.fetchGroups();
    const call = mockHttpGet.mock.calls.find(c => c[0] === GROUPS_URL);
    expect(call[1].params.status).toBe('all');
    expect(store.periodExportParams()).toEqual(
      {ledger_type: 'week_month', status: 'all'});
  });

  test('模板视图选"全部"：组列表与组内列表同口径携带 status=all', async () => {
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.t_status = STATUS_FILTER_ALL;
    await store.fetchTemplateGroups();
    let call = mockHttpGet.mock.calls.find(c => c[0] === TEMPLATE_GROUPS_URL);
    expect(call[1].params.status).toBe('all');
    store.activeGroup = {group_key: '7', group_name: '信道模板'};
    await store.fetchGroupLedgers();
    call = mockHttpGet.mock.calls.find(c => c[0].endsWith('/template-groups/7/ledgers/'));
    expect(call[1].params.status).toBe('all');
  });

  test('作废成功后刷新当前视图：默认口径重拉，已作废记录从默认视图消失', async () => {
    mockHttpPost.mockResolvedValue({});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    await store.voidLedger(5, '整单填错');
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/ledgers/5/void/', {reason: '整单填错'});
    const urls = mockHttpGet.mock.calls.map(c => c[0]);
    expect(urls).toContain(GROUPS_URL);
    expect(urls).toContain(OVERVIEW_URL);
    // 刷新请求仍为默认口径（无 status → 后端默认视图不含已作废）；
    // 切换"已作废"筛选后（f_status='void'）重新拉取即可找回
    const refreshCall = mockHttpGet.mock.calls.find(c => c[0] === GROUPS_URL);
    expect(refreshCall[1].params.status).toBeUndefined();
    store.f_status = 'void';
    await store.fetchGroups();
    const voidCall = mockHttpGet.mock.calls.filter(c => c[0] === GROUPS_URL).pop();
    expect(voidCall[1].params.status).toBe('void');
  });
});
