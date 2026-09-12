/**
 * 故障管理 Store 测试（record 故障记录 + part 故障备件）
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http / libs.http，
 * includes 使用真实 functools 实现（大小写不敏感包含匹配），验证：
 * - record：dataSource 四类筛选、fetchRecords、导出参数（日期范围格式化）、视图模式标记
 * - part：dataSource 三类筛选（名称子串 / 系统精确 / 状态精确）、固定状态选项、
 *   提交成功关闭弹窗并刷新、删除以查询参数携带 id
 */
const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpDelete = jest.fn();
const mockPartGet = jest.fn();
const mockPartPost = jest.fn();
const mockPartDelete = jest.fn();

jest.mock('libs', () => {
  const {includes} = jest.requireActual('libs/functools');
  return {
    http: {get: mockHttpGet, post: mockHttpPost, delete: mockHttpDelete},
    includes,
    hasPermission: jest.fn(() => true),
  };
});

// part/store.js 使用 `import http from 'libs/http'`（default 导入）
jest.mock('libs/http', () => ({
  __esModule: true,
  default: {get: mockPartGet, post: mockPartPost, delete: mockPartDelete},
}));

function freshRecordStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../record/store').default;
}

function freshPartStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../part/store').default;
}

import moment from 'moment';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

afterEach(() => {
  [mockHttpGet, mockHttpPost, mockHttpDelete, mockPartGet, mockPartPost, mockPartDelete]
    .forEach(m => m.mockReset());
});

const RECORDS = [
  {id: 1, fault_date: '2026-09-01', system_name: 'SYS-Alpha', handler: '张三', fault_level: '一级'},
  {id: 2, fault_date: '2026-09-02', system_name: 'SYS-Beta', handler: '李四', fault_level: '二级'},
  {id: 3, fault_date: '2026-09-03', system_name: 'SYS-Alpha', handler: '王五', fault_level: '一级'},
];

describe('故障记录 Store', () => {
  it('dataSource 四类筛选（includes 大小写不敏感）', () => {
    const store = freshRecordStore();
    store.records = RECORDS;
    // 系统名小写关键字也能匹配大写数据
    store.f_system_name = 'sys-alpha';
    expect(store.dataSource.map(x => x.id)).toEqual([1, 3]);
    store.f_system_name = undefined;

    store.f_handler = '李';
    expect(store.dataSource.map(x => x.id)).toEqual([2]);
    store.f_handler = undefined;

    store.f_fault_level = '一级';
    expect(store.dataSource.map(x => x.id)).toEqual([1, 3]);
    store.f_fault_level = undefined;

    store.f_fault_date = '2026-09-02';
    expect(store.dataSource.map(x => x.id)).toEqual([2]);
  });

  it('fetchRecords 成功后更新 records 与 systemNames', async () => {
    const store = freshRecordStore();
    mockHttpGet.mockResolvedValue({
      records: RECORDS,
      system_names: ['SYS-Alpha', 'SYS-Beta'],
    });
    store.fetchRecords();
    await flush();
    expect(store.records).toHaveLength(3);
    expect(store.systemNames).toEqual(['SYS-Alpha', 'SYS-Beta']);
    expect(store.isFetching).toBe(false);
  });

  it('getExportParams 携带筛选与格式化日期范围', () => {
    const store = freshRecordStore();
    store.f_system_name = 'SYS-Alpha';
    store.f_export_date_range = [moment('2026-09-01'), moment('2026-09-30')];
    expect(store.getExportParams()).toEqual({
      system_name: 'SYS-Alpha',
      start_date: '2026-09-01',
      end_date: '2026-09-30',
    });
  });

  it('showForm 支持视图模式标记', () => {
    const store = freshRecordStore();
    store.showForm({id: 1}, true);
    expect(store.formVisible).toBe(true);
    expect(store.record).toEqual({id: 1, isViewMode: true});
  });
});

const PARTS = [
  {id: 1, name: '电源模块A', system_name: 'SYS-Alpha', status: '故障'},
  {id: 2, name: '风扇模块B', system_name: 'SYS-Beta', status: '送修'},
  {id: 3, name: '电源模块C', system_name: 'SYS-Beta', status: '正常归档'},
];

describe('故障备件 Store', () => {
  it('dataSource：名称子串 / 系统精确 / 状态精确', () => {
    const store = freshPartStore();
    store.records = PARTS;

    store.f_name = '电源';
    expect(store.dataSource.map(x => x.id)).toEqual([1, 3]);
    store.f_name = undefined;

    store.f_system = 'SYS-Beta';
    expect(store.dataSource.map(x => x.id)).toEqual([2, 3]);
    store.f_system = undefined;

    store.f_status = '送修';
    expect(store.dataSource.map(x => x.id)).toEqual([2]);
  });

  it('statusOptions 固定四态', () => {
    const store = freshPartStore();
    expect(store.statusOptions).toEqual(['故障', '送修', '运回测试', '正常归档']);
  });

  it('fetchRecords 成功后更新 records 与 system_names', async () => {
    const store = freshPartStore();
    mockPartGet.mockResolvedValue({records: PARTS, system_names: ['SYS-Alpha']});
    await store.fetchRecords();
    expect(store.records).toHaveLength(3);
    expect(store.system_names).toEqual(['SYS-Alpha']);
    expect(store.isFetching).toBe(false);
  });

  it('handleSubmit 成功后关闭弹窗并刷新列表', async () => {
    const store = freshPartStore();
    store.formVisible = true;
    mockPartPost.mockResolvedValue({});
    mockPartGet.mockResolvedValue({records: [], system_names: []});
    await store.handleSubmit({name: '新备件'});
    expect(mockPartPost).toHaveBeenCalledWith('/api/fault/faultpart/', {name: '新备件'});
    expect(store.formVisible).toBe(false);
    expect(mockPartGet).toHaveBeenCalledWith('/api/fault/faultpart/');
  });

  it('handleDelete 以查询参数携带 id 并刷新', async () => {
    const store = freshPartStore();
    mockPartDelete.mockResolvedValue({});
    mockPartGet.mockResolvedValue({records: [], system_names: []});
    await store.handleDelete({id: 5});
    expect(mockPartDelete).toHaveBeenCalledWith('/api/fault/faultpart/', {params: {id: 5}});
    expect(mockPartGet).toHaveBeenCalledWith('/api/fault/faultpart/');
  });
});
