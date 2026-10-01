/**
 * 运维台账（步骤 3.2）Store 行为测试。
 * 真实执行 Store 方法与请求参数组装，mock libs.http 返回真实响应格式。
 */
import {LedgerStore, getLedgerStore} from '../store';
import {LEDGER_TYPE} from '../constants';

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
  history: {},
  X_TOKEN: '',
}));

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

describe('LedgerStore', () => {
  beforeEach(() => {
    [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  });

  test('fetchRecords 携带台账类型与筛选参数（按类型区分请求）', async () => {
    mockHttpGet.mockResolvedValue({data: [{id: 1}], total: 1, page: 1, page_size: 20});
    const store = new LedgerStore(LEDGER_TYPE.WEEK_MONTH);
    store.f_status = 'submitted';
    store.page = 2;
    await store.fetchRecords();
    const [url, config] = mockHttpGet.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/ledgers/');
    expect(config.params.ledger_type).toBe('week_month');
    expect(config.params.status).toBe('submitted');
    expect(config.params.page).toBe(2);
    expect(store.records).toEqual([{id: 1}]);
    expect(store.total).toBe(1);
  });

  test('submitLedger 调用提交动作接口并在成功后重新获取列表', async () => {
    mockHttpPost.mockResolvedValue({});
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    const store = new LedgerStore(LEDGER_TYPE.SEASONAL);
    await store.submitLedger(9);
    expect(mockHttpPost).toHaveBeenCalledWith('/api/equipment-lifecycle/ledgers/9/submit/', {});
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
