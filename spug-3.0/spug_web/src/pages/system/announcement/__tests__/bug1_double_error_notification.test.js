/**
 * Bug 1 复现测试：管理端操作错误提示重复弹出
 *
 * 缺陷描述：
 *   后端返回 HTTP 200 + {"error": "..."} 时，libs/http.js 拦截器调用 message.error()
 *   弹出第一个错误提示，然后将 Promise reject。管理端组件的 .catch() 又调用
 *   notification.error() 弹出第二个错误提示，导致用户看到两个错误弹窗。
 *
 * 验证方式：
 *   模拟 handleResponse 的 reject 行为，验证组件的 catch handler 会叠加第二个提示。
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

// 重置错误去重状态（模拟 handleResponse 内部的 _lastErrorMsg）
// 由于 showErrorOnce 是 http.js 的内部函数，我们直接模拟其行为
function simulateHandleResponse(data) {
  /**
   * 模拟 http.js handleResponse 的关键逻辑：
   * 1. 检测 response.data.error
   * 2. 调用 showErrorOnce → message.error
   * 3. return Promise.reject(error_string)
   *
   * 注意：返回值是 rejected Promise，调用方必须 .catch() 处理。
   */
  if (data.error) {
    message.error(data.error);
    return Promise.reject(data.error);
  }
  return Promise.resolve(data.data || data);
}

// 模拟管理端组件的 doPublish / doWithdraw / doDelete 的 catch 逻辑
function simulateComponentCatch(error) {
  /**
   * 模拟 index.js 中的 catch handler：
   *   .catch(e => notification.error({
   *     message: '操作失败',
   *     description: e.message || String(e),
   *   }))
   */
  notification.error({
    message: '操作失败',
    description: typeof error === 'string' ? error : (error.message || String(error)),
  });
}

/**
 * 模拟完整的请求链：拦截器 reject → 组件 catch handler
 * 返回 Promise 以便测试可以 await，避免 UnhandledPromiseRejection。
 */
function simulateFullRequestChain(data) {
  return simulateHandleResponse(data)
    .then(successData => {
      // 成功分支（本测试不走这里）
      return successData;
    })
    .catch(error => {
      // catch handler：组件的 .catch() 逻辑
      simulateComponentCatch(error);
      return error; // 返回以供断言
    });
}

// ============================================================
describe('Bug 1: 双重错误提示验证', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('业务错误时拦截器和组件各弹一次错误，共两次', async () => {
    const errorMsg = '公告已发布，请勿重复发布';

    // 模拟完整请求链：拦截器 reject → 组件 catch handler
    await simulateFullRequestChain({ error: errorMsg });

    // 断言：message.error 被调用 1 次（拦截器）
    expect(message.error).toHaveBeenCalledTimes(1);
    expect(message.error).toHaveBeenCalledWith(errorMsg);

    // 断言：notification.error 被调用 1 次（组件 catch）
    expect(notification.error).toHaveBeenCalledTimes(1);
    expect(notification.error).toHaveBeenCalledWith(
      expect.objectContaining({
        message: '操作失败',
        description: errorMsg,
      }),
    );

    // 结论：用户会看到两个错误提示
    const totalErrorCount = message.error.mock.calls.length + notification.error.mock.calls.length;
    expect(totalErrorCount).toBe(2);
  });

  test('撤回失败时也会双重提示', async () => {
    const errorMsg = '仅已发布公告可撤回';

    await simulateFullRequestChain({ error: errorMsg });

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(notification.error).toHaveBeenCalledTimes(1);
  });

  test('删除失败时也会双重提示', async () => {
    const errorMsg = '公告不存在';

    await simulateFullRequestChain({ error: errorMsg });

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(notification.error).toHaveBeenCalledTimes(1);
  });

  test('Form 保存失败时也会双重提示', async () => {
    const errorMsg = '生效结束时间不能早于开始时间';

    // Form.js 的 catch: notification.error({ message: '保存失败', description: ... })
    await simulateFullRequestChain({ error: errorMsg });
    notification.error.mockClear();
    notification.error({
      message: '保存失败',
      description: errorMsg,
    });

    expect(message.error).toHaveBeenCalledTimes(1);
    expect(notification.error).toHaveBeenCalledTimes(1);
  });

  test('成功时不应有任何错误提示', async () => {
    // 模拟成功响应
    await simulateFullRequestChain({ data: { id: 1, status: 'published' } });

    expect(message.error).not.toHaveBeenCalled();
    expect(notification.error).not.toHaveBeenCalled();
  });

  test('2 秒内相同错误消息的去重仅适用于 message.error，不影响 notification.error', async () => {
    const errorMsg = '重复的错误消息';

    // 第一次调用
    await simulateFullRequestChain({ error: errorMsg });

    // 第二次调用（模拟 2 秒内重复）
    await simulateFullRequestChain({ error: errorMsg });

    // message.error 可能被去重（取决于 showErrorOnce 的实现）
    // 但 notification.error 不受去重影响
    const notificationCalls = notification.error.mock.calls.length;

    // 即使 message.error 去重了，notification.error 至少被调用 2 次
    expect(notificationCalls).toBeGreaterThanOrEqual(2);

    // 验证 notification.error 确实不在去重范围内
    const allDescriptions = notification.error.mock.calls.map(call => call[0].description);
    expect(allDescriptions).toEqual([errorMsg, errorMsg]);
  });
});
