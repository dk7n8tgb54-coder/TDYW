/**
 * 值班日志 Store 测试
 *
 * 真实 import store（MobX 装饰器经 babel 编译），mock libs.http，验证：
 * - dataSource 按值班人员 / 科室 / 日期范围过滤（前端本地过滤）
 * - fetchRecords 成功后 records / dutyPersons / departments 更新，isFetching 复位
 *
 * 注：duty store 的 fetchRecords 链上没有 .catch，业务错误由 http 拦截器
 * 统一提示后 reject（仓库约定"同一个错误只提示一次"），store 层会留下一个
 * 未处理的 promise 拒绝，无法在本测试环境中干净地断言该路径，故不覆盖。
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
}));

function freshStore() {
  jest.resetModules();
  // eslint-disable-next-line global-require
  return require('../store').default;
}

// store.fetchRecords 不返回 promise，需用宏任务冲刷微任务链
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const RECORDS = [
  {id: 1, duty_person: '张三', department: '运维部', duty_date: '2026-09-01', duty_situation: '正常'},
  {id: 2, duty_person: '李四', department: '安全部', duty_date: '2026-09-02', duty_situation: '正常'},
  {id: 3, duty_person: '张三', department: '安全部', duty_date: '2026-09-03', duty_situation: '有干扰'},
];

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('值班日志 Store dataSource 前端过滤', () => {
  it('无筛选条件时返回全部记录', () => {
    const store = freshStore();
    store.records = RECORDS;
    expect(store.dataSource).toHaveLength(3);
  });

  it('按值班人员过滤', () => {
    const store = freshStore();
    store.records = RECORDS;
    store.f_duty_person = '张三';
    expect(store.dataSource).toHaveLength(2);
    expect(store.dataSource.every(x => x.duty_person === '张三')).toBe(true);
  });

  it('按科室过滤', () => {
    const store = freshStore();
    store.records = RECORDS;
    store.f_department = '安全部';
    expect(store.dataSource).toHaveLength(2);
    expect(store.dataSource.every(x => x.department === '安全部')).toBe(true);
  });

  it('按开始日期过滤（含边界）', () => {
    const store = freshStore();
    store.records = RECORDS;
    store.f_start_date = '2026-09-02';
    expect(store.dataSource.map(x => x.id)).toEqual([2, 3]);
  });

  it('按结束日期过滤（含边界）', () => {
    const store = freshStore();
    store.records = RECORDS;
    store.f_end_date = '2026-09-02';
    expect(store.dataSource.map(x => x.id)).toEqual([1, 2]);
  });

  it('日期范围与人员组合过滤', () => {
    const store = freshStore();
    store.records = RECORDS;
    store.f_duty_person = '张三';
    store.f_start_date = '2026-09-02';
    store.f_end_date = '2026-09-03';
    expect(store.dataSource.map(x => x.id)).toEqual([3]);
  });

  it('无匹配结果时返回空数组', () => {
    const store = freshStore();
    store.records = RECORDS;
    store.f_department = '不存在的科室';
    expect(store.dataSource).toEqual([]);
  });
});

describe('值班日志 Store fetchRecords', () => {
  it('成功后更新 records / dutyPersons / departments 并复位 isFetching', async () => {
    const store = freshStore();
    mockHttpGet.mockResolvedValue({
      records: RECORDS,
      duty_persons: ['张三', '李四'],
      departments: ['运维部', '安全部'],
    });
    expect(store.isFetching).toBe(false);
    const pending = store.fetchRecords();
    expect(store.isFetching).toBe(true);
    await pending;
    await flush();
    expect(store.isFetching).toBe(false);
    expect(store.records).toHaveLength(3);
    expect(store.dutyPersons).toEqual(['张三', '李四']);
    expect(store.departments).toEqual(['运维部', '安全部']);
  });
});

describe('值班日志 Store 弹窗状态', () => {
  it('showForm 携带记录与查看模式标记', () => {
    const store = freshStore();
    store.showForm({id: 1, duty_person: '张三'});
    expect(store.formVisible).toBe(true);
    expect(store.record).toEqual({id: 1, duty_person: '张三', isViewMode: false});

    store.showForm({id: 2}, true);
    expect(store.record.isViewMode).toBe(true);
  });

  it('showDetail 打开详情并记录', () => {
    const store = freshStore();
    store.showDetail({id: 3, duty_person: '王五'});
    expect(store.detailVisible).toBe(true);
    expect(store.record.id).toBe(3);
  });
});
