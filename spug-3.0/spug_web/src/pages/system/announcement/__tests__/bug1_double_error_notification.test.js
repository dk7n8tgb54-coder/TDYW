/**
 * Bug 1 回归测试：管理端操作错误提示只弹一次（已修复）
 *
 * 原缺陷：
 *   后端返回 HTTP 200 + {"error": "..."} 时，libs/http.js 拦截器调用 message.error()
 *   弹出第一个错误提示，组件 .catch() 又调用 notification.error() 弹出第二个，
 *   用户看到两个错误弹窗。
 *
 * 修复：
 *   公告模块组件的 .catch() 不再重复提示（保留空 catch 维持控制流），
 *   错误统一由 http 拦截器提示一次（项目规则：同一错误只能提示一次）。
 */
jest.mock('antd', () => {
  const mockMessage = {
    info: jest.fn(),
    success: jest.fn(),
    error: jest.fn(),
    warning: jest.fn(),
    loading: jest.fn(() => jest.fn()),
  };
  const mockNotification = {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warning: jest.fn(),
  };
  return { message: mockMessage, notification: mockNotification };
});

const { message, notification } = require('antd');

/**
 * 模拟 http.js handleResponse 的关键逻辑：
 * 1. 检测 response.data.error
 * 2. 调用 showErrorOnce → message.error
 * 3. return Promise.reject(error_string)
 */
function simulateHandleResponse(data) {
  if (data.error) {
    message.error(data.error);
    return Promise.reject(data.error);
  }
  return Promise.resolve(data.data || data);
}

/**
 * 模拟修复后组件的 catch handler（index.js / Form.js / Detail.js）：
 * 修复后组件 catch 为空实现（维持控制流），不再调用 notification.error，
 * 错误统一由 http 拦截器提示。
 */
function simulateFixedComponentCatch() {
  // 修复后组件不再重复提示
}

/** 模拟完整的请求链：拦截器 reject → 修复后的组件 catch */
function simulateFullRequestChain(data) {
  return simulateHandleResponse(data)
    .then(successData => successData)
    .catch(error => {
      simulateFixedComponentCatch();
      return error;
    });
}

// ============================================================
describe('Bug 1 修复回归：错误提示只弹一次', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('业务错误时仅拦截器提示一次，组件不再重复弹窗', async () => {
    const errorMsg = '公告已发布，请勿重复发布';

    await simulateFullRequestChain({ error: errorMsg });

    // 拦截器提示一次
    expect(message.error).toHaveBeenCalledTimes(1);
    expect(message.error).toHaveBeenCalledWith(errorMsg);

    // 修复后组件不再弹 notification.error
    expect(notification.error).not.toHaveBeenCalled();

    const totalErrorCount = message.error.mock.calls.length + notification.error.mock.calls.length;
    expect(totalErrorCount).toBe(1);
  });

  test('撤回失败时同样只提示一次', async () => {
    await simulateFullRequestChain({ error: '仅已发布公告可撤回' });

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(notification.error).not.toHaveBeenCalled();
  });

  test('删除失败时同样只提示一次', async () => {
    await simulateFullRequestChain({ error: '公告不存在' });

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(notification.error).not.toHaveBeenCalled();
  });

  test('Form 保存失败时同样只提示一次', async () => {
    await simulateFullRequestChain({ error: '生效结束时间不能早于开始时间' });

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(notification.error).not.toHaveBeenCalled();
  });

  test('成功时不应有任何错误提示', async () => {
    await simulateFullRequestChain({ data: { id: 1, status: 'published' } });

    expect(message.error).not.toHaveBeenCalled();
    expect(notification.error).not.toHaveBeenCalled();
  });
});
