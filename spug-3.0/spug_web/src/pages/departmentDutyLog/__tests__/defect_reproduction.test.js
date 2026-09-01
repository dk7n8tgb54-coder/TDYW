/**
 * 部门值班日志 - 已修复缺陷回归测试（stable_contract）
 *
 * 两个缺陷已经修复；这些用例用于防止回归。
 *
 * REGRESSION-1（P2）：详情请求乱序时，旧响应不得覆盖当前记录。
 *
 * REGRESSION-2（P3）：版本冲突时只显示一次错误提示并保留表单。
 */

jest.mock('antd', () => {
  const mockMessage = {
    info: jest.fn(), success: jest.fn(), error: jest.fn(),
    warning: jest.fn(), loading: jest.fn(() => jest.fn()),
  };
  return { message: mockMessage };
});

jest.mock('libs', () => {
  const http = { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() };
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

function deferred() {
  let resolveFn, rejectFn;
  const promise = new Promise((res, rej) => { resolveFn = res; rejectFn = rej; });
  return { promise, resolve: resolveFn, reject: rejectFn };
}

async function flushAsync() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
  await new Promise(r => setTimeout(r, 0));
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

beforeEach(() => {
  jest.clearAllMocks();
  store.record = {};
  store.formRecord = {};
  store.formVisible = false;
  store.formLoading = false;
});

// ============================================================
// DEFECT-1：showDetail 过期响应覆盖
// ============================================================

describe('REGRESSION-1 [P2] store.showDetail 过期异步响应保护', () => {
  test('快速打开 A、B 后，慢返回的 A 不覆盖 B 的详情', async () => {
    const a = deferred();
    const b = deferred();
    http.get.mockImplementationOnce(() => a.promise)
      .mockImplementationOnce(() => b.promise);

    store.showDetail({ id: 1, duty_date: '2026-01-01', duty_record_summary: 'A 摘要' });
    store.showDetail({ id: 2, duty_date: '2026-01-02', duty_record_summary: 'B 摘要' });
    expect(store.record.id).toBe(2);

    // B 的详情先返回，A 的详情后返回（乱序）
    b.resolve({ id: 2, duty_record: 'B 全文' });
    await Promise.resolve();
    a.resolve({ id: 1, duty_record: 'A 全文' });
    await Promise.resolve();

    // 旧响应不得覆盖当前记录 B
    expect(store.record.id).toBe(2);
    expect(store.record.duty_record).toBe('B 全文');
  });
});

// ============================================================
// DEFECT-2：版本冲突错误提示重复
// ============================================================

describe('REGRESSION-2 [P3] Form 版本冲突错误提示去重', () => {
  test('版本冲突时 message.error 仅调用一次', async () => {
    const errorText = '记录不存在、无权操作或版本冲突，请刷新后重试';

    // 复现 libs/http.js 拦截器真实行为：先提示一次，再 reject
    http.put.mockImplementation(() => {
      message.error(errorText);
      return Promise.reject(errorText);
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
    form._editId = 101;
    form._editVersion = 1;

    await form.handleSubmit();
    await flushAsync();

    // 项目规则：HTTP 拦截器已提示的错误，业务代码不得重复提示
    // 业务代码不得重复弹出同一错误
    expect(message.error).toHaveBeenCalledTimes(1);
  });
});
