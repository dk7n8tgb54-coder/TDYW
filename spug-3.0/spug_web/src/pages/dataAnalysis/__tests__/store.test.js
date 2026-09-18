/**
 * 数据分析 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - TABS 配置：五个分析 Tab 的 key/权限码/端点与后端路由一致
 * - 默认日期范围为最近一年；快捷区间预设天数正确
 * - fetchTab：未知 Tab 不发请求；日期参数格式化 YYYY-MM-DD
 * - 每个 Tab 独立的 data/fetching/error 状态，互不污染
 * - 业务失败（reject）时记录错误信息并复位 fetching
 *
 * 注：图表组件依赖 bizcharts 在 jsdom 下不可渲染（并行测试已知问题），
 * 本文件只覆盖 store 层行为，不渲染页面组件。
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
}));

import moment from 'moment';

// 注意：不能在顶部 import '../store'（ES import 提升会先于 mock 变量初始化执行），
// 统一经 freshStore 的 require 加载
function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  const mod = require('../store');
  return {store: mod.default, TABS: mod.TABS, DEFAULT_RANGE_DAYS: mod.DEFAULT_RANGE_DAYS, MAX_RANGE_DAYS: mod.MAX_RANGE_DAYS, getDatePresets: mod.getDatePresets};
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('数据分析 TABS 配置', () => {
  it('四个 Tab 的 key/权限码/端点与后端路由一致', () => {
    const {TABS} = freshStore();
    expect(TABS).toEqual([
      {key: 'overview', label: '总览分析', perm: 'data_analysis.overview.view', endpoint: '/api/data-analysis/overview/'},
      {key: 'interference', label: '干扰分析', perm: 'data_analysis.interference.view', endpoint: '/api/data-analysis/interference/'},
      {key: 'device', label: '设备分析', perm: 'data_analysis.device.view', endpoint: '/api/data-analysis/device/'},
      {key: 'upgrade', label: '升级分析', perm: 'data_analysis.upgrade.view', endpoint: '/api/data-analysis/upgrade/'},
    ]);
  });
});

describe('数据分析日期范围', () => {
  it('默认日期范围为最近一年（365 天含起止）', () => {
    const {store, DEFAULT_RANGE_DAYS} = freshStore();
    expect(store.dateRange).toHaveLength(2);
    const [start, end] = store.dateRange;
    expect(end.isSame(moment(), 'day')).toBe(true);
    expect(start.diff(end, 'days')).toBe(-(DEFAULT_RANGE_DAYS - 1));
  });

  it('快捷区间预设天数正确', () => {
    const {getDatePresets, DEFAULT_RANGE_DAYS, MAX_RANGE_DAYS} = freshStore();
    const presets = getDatePresets();
    const expected = {
      '近半年': 182,
      '近一年': DEFAULT_RANGE_DAYS - 1,
      '近两年': 730,
      '近三年': 1095,
      '近五年': MAX_RANGE_DAYS - 1,
    };
    Object.keys(expected).forEach(label => {
      const [start, end] = presets[label];
      expect(start.diff(end, 'days')).toBe(-expected[label]);
      expect(end.isSame(moment(), 'day')).toBe(true);
    });
  });
});

describe('数据分析 fetchTab', () => {
  it('未知 Tab 不发请求', () => {
    const {store} = freshStore();
    expect(store.fetchTab('nonexistent')).toBeUndefined();
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('组装日期参数并更新对应 Tab 数据', async () => {
    const {store} = freshStore();
    store.dateRange = [moment('2026-01-01'), moment('2026-12-31')];
    mockHttpGet.mockResolvedValue({total: 42});
    const pending = store.fetchTab('overview');
    expect(store.isFetching('overview')).toBe(true);
    await pending;
    await flush();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/data-analysis/overview/', {
      params: {start_date: '2026-01-01', end_date: '2026-12-31'},
    });
    expect(store.getData('overview')).toEqual({total: 42});
    expect(store.isFetching('overview')).toBe(false);
    expect(store.getError('overview')).toBeNull();
  });

  it('各 Tab 状态独立互不污染', async () => {
    const {store} = freshStore();
    mockHttpGet.mockResolvedValueOnce({tab: 'interference'});
    await store.fetchTab('interference');
    await flush();
    expect(store.getData('interference')).toEqual({tab: 'interference'});
    // 其他 Tab 不受影响
    expect(store.getData('device')).toBeUndefined();
    expect(store.isFetching('device')).toBe(false);
  });

  it('业务失败（Error 对象）记录错误信息并复位 fetching', async () => {
    const {store} = freshStore();
    mockHttpGet.mockRejectedValue(new Error('查询超时'));
    await store.fetchTab('device');
    await flush();
    expect(store.getError('device')).toBe('查询超时');
    expect(store.getData('device')).toBeUndefined();
    expect(store.isFetching('device')).toBe(false);
  });

  it('业务失败（字符串拒绝）使用兜底错误文案', async () => {
    const {store} = freshStore();
    mockHttpGet.mockRejectedValue('服务器内部错误');
    await store.fetchTab('upgrade');
    await flush();
    expect(store.getError('upgrade')).toBe('数据加载失败');
    expect(store.isFetching('upgrade')).toBe(false);
  });
});

describe('数据分析 Tab 与日期切换', () => {
  it('setActiveTab / setDateRange 更新状态', () => {
    const {store} = freshStore();
    store.setActiveTab('interference');
    expect(store.activeTab).toBe('interference');
    const range = [moment('2026-01-01'), moment('2026-06-30')];
    store.setDateRange(range);
    expect(store.dateRange).toEqual(range);
  });
});
