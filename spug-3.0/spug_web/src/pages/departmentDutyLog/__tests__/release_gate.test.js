/**
 * 部门值班日志 - 上线前发布门禁前端测试
 *
 * 分类：stable_contract
 *
 * 覆盖：
 * - FE-01 store.showDetail 过期响应保护（对照组：showForm/showSign 已有）
 * - FE-02 Form 版本冲突时错误提示是否重复（项目规则：同一错误只能提示一次）
 * - FE-03 提交成功后等待后端响应再关闭弹窗/刷新列表（不得乐观更新）
 * - FE-04 月份缓存失效逻辑
 * - FE-05 Form 编辑模式固定 _editId/_editVersion，防止异步覆盖后提交到错误记录
 *
 * 全部执行真实组件代码路径（实例化真实组件类 / 真实 store），不读取源码做字符串断言。
 */

// ---- mock antd message（统计提示次数） ----
jest.mock('antd', () => {
  const mockMessage = {
    info: jest.fn(),
    success: jest.fn(),
    error: jest.fn(),
    warning: jest.fn(),
    loading: jest.fn(() => jest.fn()),
  };
  return { message: mockMessage };
});

// ---- mock libs（http + 常用导出，避免拉起整个公共层） ----
jest.mock('libs', () => {
  const http = {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  };
  const hasPermission = jest.fn(() => true);
  const Permission = { isSuper: false };
  const exportFile = jest.fn();
  const AuthDiv = ({ children }) => children;
  const Breadcrumb = ({ children }) => children;
  Breadcrumb.Item = ({ children }) => children;
  const SearchForm = ({ children }) => children;
  SearchForm.Item = ({ children }) => children;
  return { http, hasPermission, Permission, exportFile, AuthDiv, Breadcrumb, SearchForm };
});

// ---- mock components（Form 只用到本模块组件，未直接依赖） ----
jest.mock('components', () => ({
  AuthDiv: ({ children }) => children,
  Breadcrumb: ({ children }) => children,
  SearchForm: ({ children }) => children,
  TableCard: () => null,
  Action: ({ children }) => children,
}));

const { message } = require('antd');
const { http } = require('libs');
const store = require('../departmentDutyLogStore').default;
const DepartmentDutyLogForm = require('../DepartmentDutyLogForm').default;

// ============================================================
// 工具：构造延迟 resolve 的 http.get mock
// ============================================================

function deferred() {
  let resolveFn, rejectFn;
  const promise = new Promise((res, rej) => { resolveFn = res; rejectFn = rej; });
  return { promise, resolve: resolveFn, reject: rejectFn };
}

/**
 * 冲刷微任务/宏任务队列。
 * handleSubmit 返回的是外层 validateFields().then(...)，
 * 内部 request.then(...).catch(...).finally(...) 链未被外层返回，
 * 必须显式冲刷才能观察到组件内部的最终行为。
 */
async function flushAsync() {
  for (let i = 0; i < 20; i++) {
    await Promise.resolve();
  }
  await new Promise(r => setTimeout(r, 0));
  for (let i = 0; i < 20; i++) {
    await Promise.resolve();
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  // 重置 store 状态（@observable 字段可直接赋值；@action.bound 方法不可重新赋值）
  store.records = [];
  store.formRecord = {};
  store.formVisible = false;
  store.formLoading = false;
  store.detailVisible = false;
  store.detailLoading = false;
  store.dutyDatesByMonth = {};
});

/** 统计列表刷新次数（fetchRecords 内部调用列表接口） */
function listRefreshCount() {
  return http.get.mock.calls.filter(([url]) => url === '/api/department-duty-log/records/').length;
}

// ============================================================
// FE-01 详情抽屉竞态（缺陷复现已移至 defect_reproduction.test.js / DEFECT-1）
// ============================================================

describe('FE-01 store.showDetail（正向行为）', () => {
  test('打开记录后详情异步返回时填充全文字段', async () => {
    const d = deferred();
    http.get.mockImplementationOnce(() => d.promise);

    store.showDetail({ id: 5, duty_date: '2026-01-05', duty_record_summary: '摘要' });
    expect(store.record.id).toBe(5);
    expect(store.detailLoading).toBe(true);

    d.resolve({ id: 5, duty_record: '详情全文', remark: '备注全文' });
    await flushAsync();

    expect(store.record.duty_record).toBe('详情全文');
    expect(store.record.remark).toBe('备注全文');
    expect(store.detailLoading).toBe(false);
  });
});

// ============================================================
// FE-02 版本冲突错误提示次数
// ============================================================

describe('FE-02 Form 业务错误提示（正向行为）', () => {
  function makeFormInstance(editId, editVersion) {
    const form = new DepartmentDutyLogForm({});
    form.formRef = {
      current: {
        validateFields: jest.fn(() => Promise.resolve({
          duty_date: { format: () => '2026-01-01' },
          weather: '晴',
          duty_record: '内容',
          remark: '',
        })),
        setFieldsValue: jest.fn(),
      },
    };
    form._mounted = true;
    form._editId = editId;
    form._editVersion = editVersion;
    return form;
  }

  /**
   * 复现 libs/http.js 拦截器真实行为（见 src/libs/http.js:56-94）：
   * 1) 检测 response.data.error -> showErrorOnce(result) -> message.error(result)
   * 2) return Promise.reject(result)
   * 组件 catch 收到的 err 即后端 error 字符串。
   */
  function simulateInterceptorBusinessError(errorText) {
    message.error(errorText);       // 拦截器 showErrorOnce
    return Promise.reject(errorText);
  }

  test('非版本类业务错误（如校验失败）只弹一次', async () => {
    const errorText = '值班记录 不能为空';
    http.post.mockImplementation(() => simulateInterceptorBusinessError(errorText));

    const form = makeFormInstance(null, null);
    await form.handleSubmit();
    await flushAsync();

    expect(message.error).toHaveBeenCalledTimes(1);
  });
});

// ============================================================
// FE-03 提交成功后再关闭弹窗并刷新列表（不得乐观更新）
// ============================================================

describe('FE-03 提交成功时序', () => {
  function makeFormInstance(editId, editVersion) {
    const form = new DepartmentDutyLogForm({});
    form.formRef = {
      current: {
        validateFields: jest.fn(() => Promise.resolve({
          duty_date: { format: () => '2026-01-01' },
          weather: '晴',
          duty_record: '内容',
          remark: '',
        })),
        setFieldsValue: jest.fn(),
      },
    };
    form._mounted = true;
    form._editId = editId;
    form._editVersion = editVersion;
    form.setState = jest.fn();
    return form;
  }

  test('新建：后端成功响应前不关闭弹窗、不刷新列表', async () => {
    const d = deferred();
    http.post.mockImplementation(() => d.promise);
    // 列表刷新（fetchRecords）会请求列表接口
    http.get.mockImplementation(() => Promise.resolve({ records: [], total: 0 }));

    store.formVisible = true;

    const form = makeFormInstance(null, null);
    const pending = form.handleSubmit();

    // 请求未 resolve：不得提前关闭弹窗或刷新
    expect(store.formVisible).toBe(true);
    expect(listRefreshCount()).toBe(0);
    expect(message.success).not.toHaveBeenCalled();

    d.resolve({});
    await pending;
    await flushAsync();

    // 成功后才关闭 + 刷新 + 提示
    expect(store.formVisible).toBe(false);
    expect(listRefreshCount()).toBe(1);
    expect(message.success).toHaveBeenCalledWith('新建成功');
  });

  test('新建失败：弹窗保持打开，不刷新列表', async () => {
    http.post.mockImplementation(() => Promise.reject('天气情况 不能为空'));
    http.get.mockImplementation(() => Promise.resolve({ records: [], total: 0 }));

    store.formVisible = true;

    const form = makeFormInstance(null, null);
    await form.handleSubmit();
    await flushAsync();

    expect(store.formVisible).toBe(true);
    expect(listRefreshCount()).toBe(0);
    expect(message.success).not.toHaveBeenCalled();
  });
});

// ============================================================
// FE-04 月份日期缓存失效
// ============================================================

describe('FE-04 dutyDatesByMonth 缓存失效', () => {
  test('保存成功后失效记录所属月份', () => {
    store.dutyDatesByMonth = { '2026-01': new Set(['2026-01-01']) };
    store.invalidateDutyDatesCache(['2026-01']);
    expect(store.dutyDatesByMonth).toEqual({});
  });

  test('日期变更时同时失效新旧两个月份', () => {
    store.dutyDatesByMonth = {
      '2026-01': new Set(['2026-01-01']),
      '2026-02': new Set(['2026-02-01']),
    };
    store.invalidateDutyDatesCache(['2026-02', '2026-01']);
    expect(store.dutyDatesByMonth).toEqual({});
  });

  test('其他月份缓存保留', () => {
    store.dutyDatesByMonth = {
      '2026-01': new Set(['2026-01-01']),
      '2026-03': new Set(['2026-03-01']),
    };
    store.invalidateDutyDatesCache(['2026-01']);
    expect(store.dutyDatesByMonth['2026-01']).toBeUndefined();
    expect(store.dutyDatesByMonth['2026-03']).toBeDefined();
  });

  test('hasDutyDate 命中与未命中', () => {
    store.dutyDatesByMonth = { '2026-01': new Set(['2026-01-15']) };
    expect(store.hasDutyDate('2026-01-15')).toBe(true);
    expect(store.hasDutyDate('2026-01-16')).toBe(false);
    expect(store.hasDutyDate('2026-02-15')).toBe(false); // 无缓存月份
  });

  test('fetchDutyDatesByMonth 命中缓存时不发请求', async () => {
    store.dutyDatesByMonth = { '2026-01': new Set(['2026-01-01']) };
    await store.fetchDutyDatesByMonth(2026, 1);
    expect(http.get).not.toHaveBeenCalled();
  });
});

// ============================================================
// FE-05 编辑模式固定 id/version
// ============================================================

describe('FE-05 编辑提交参数', () => {
  test('编辑提交携带后端下发的 version，且 URL 使用固定 _editId', async () => {
    let capturedUrl = null;
    let capturedPayload = null;
    http.put.mockImplementation((url, payload) => {
      capturedUrl = url;
      capturedPayload = payload;
      return Promise.resolve({});
    });

    const form = new DepartmentDutyLogForm({});
    form.formRef = {
      current: {
        validateFields: jest.fn(() => Promise.resolve({
          duty_date: { format: () => '2026-01-01' },
          weather: '晴',
          duty_record: '内容',
          remark: '',
        })),
        setFieldsValue: jest.fn(),
      },
    };
    form._mounted = true;
    form._editId = 42;
    form._editVersion = 7;
    form.setState = jest.fn();
    http.get.mockImplementation(() => Promise.resolve({ records: [], total: 0 }));

    await form.handleSubmit();
    await flushAsync();

    expect(capturedUrl).toBe('/api/department-duty-log/records/42/');
    expect(capturedPayload.version).toBe(7);
  });
});
