/**
 * 设备全生命周期（步骤 3.4，单系统简化）统一系统履历——Store 与来源跳转测试
 *
 * 真实 import store/constants（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - fetchRecords 组装分页与筛选参数（事件类型/来源类型/时间范围，不再有角色筛选）
 * - fetchSystemEvents 按系统 ID 查询本系统事件（详情页签复用，无角色过滤）
 * - buildSourceHref：按来源类型生成跳转地址，无权限或无来源时不跳转
 * - 履历只读：Store 不含任何新增/修改/删除请求方法
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  X_TOKEN: '',
  exportFile: jest.fn(),
  syncAttachmentCount: jest.fn(),
  history: {push: jest.fn()},
}));

function freshModule() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  const store = require('../store').default;
  // eslint-disable-next-line global-require
  const constants = require('../constants');
  return {store, constants};
}

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('系统履历 Store（步骤 3.4）', () => {
  it('fetchRecords 组装分页与筛选参数（关键词/事件类型/来源类型/时间范围）', () => {
    const {store} = freshModule();
    store.page = 2;
    store.pageSize = 30;
    store.f_keyword = '维修';
    store.f_event_type = 'fault';
    store.f_source_type = 'work_order';
    store.f_range = ['2026-09-01 00:00', '2026-09-19 23:59'];
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.fetchRecords();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/system-events/', {
      params: {
        page: 2, page_size: 30,
        keyword: '维修', event_type: 'fault', source_type: 'work_order',
        occurred_from: '2026-09-01 00:00', occurred_to: '2026-09-19 23:59',
      },
    });
  });

  it('fetchSystemEvents 按系统 ID 查询本系统事件（无角色参数）', () => {
    const {store} = freshModule();
    mockHttpGet.mockResolvedValue({data: [{id: 1, title: '工单登记'}], total: 1});
    return store.fetchSystemEvents(66).then(() => {
      expect(mockHttpGet).toHaveBeenCalledWith(
        '/api/equipment-lifecycle/systems/66/system-events/', {params: {page: 1, page_size: 20}});
      expect(store.records).toHaveLength(1);
      expect(store.total).toBe(1);
    });
  });

  it('履历只读：Store 不提供新增/修改/删除入口', () => {
    const {store} = freshModule();
    ['post', 'put', 'remove', 'delete', 'create', 'update', 'destroy'].forEach(name => {
      expect(store[name]).toBeUndefined();
    });
    // 状态字段仅查询相关
    expect(store.fetchRecords).toBeInstanceOf(Function);
    expect(store.fetchSystemEvents).toBeInstanceOf(Function);
  });
});

describe('来源跳转 buildSourceHref（跳转后由来源页面重新鉴权）', () => {
  const baseEvent = {source_type: 'fault', source_id: '9', source_no: 'GZ20260919-0001', detail: {}};

  it('故障来源跳转故障详情深链', () => {
    const {constants} = freshModule();
    expect(constants.buildSourceHref(baseEvent)).toBe('/el/faults?detail=9');
  });

  it('工单来源已随工单功能删除，无跳转地址', () => {
    const {constants} = freshModule();
    const event = {...baseEvent, source_type: 'work_order'};
    expect(constants.buildSourceHref(event)).toBeNull();
  });

  it('台账异常来源按台账类型跳转台账详情深链', () => {
    const {constants} = freshModule();
    const event = {...baseEvent, source_type: 'ledger_item',
      detail: {ledger_type: 'week_month', ledger_id: 33}};
    expect(constants.buildSourceHref(event)).toBe('/el/week-month-ledgers?detail=33');
  });

  it('运行记录来源跳转运行记录详情深链（2026-10）', () => {
    const {constants} = freshModule();
    const event = {...baseEvent, source_type: 'runtime_record', source_id: '11'};
    expect(constants.buildSourceHref(event)).toBe('/el/runtime-records?detail=11');
  });

  it('健康状态事件无来源对象，不渲染跳转', () => {
    const {constants} = freshModule();
    const event = {...baseEvent, source_type: 'health', source_id: ''};
    expect(constants.buildSourceHref(event)).toBeNull();
  });

  it('无对应查看权限时不渲染跳转链接', () => {
    jest.resetModules();
    // eslint-disable-next-line global-require
    const libs = require('libs');
    libs.hasPermission.mockImplementation(code => code !== 'equipment_lifecycle.fault.view');
    // eslint-disable-next-line global-require
    const constants = require('../constants');
    expect(constants.buildSourceHref(baseEvent)).toBeNull();
  });
});
