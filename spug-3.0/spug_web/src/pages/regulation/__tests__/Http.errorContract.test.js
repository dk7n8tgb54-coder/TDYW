/**
 * 规章管理前后端错误契约测试（stable_contract）
 *
 * 验证项目约定（AGENTS.md 第九条）：
 * 1. HTTP 200 + {"error": "..."} 必须被公共 HTTP 层判为失败（Promise reject），
 *    业务代码不得当作成功。
 * 2. HTTP 200 + {"data": ...} 才判为成功，并解包 data。
 * 3. 同一个错误只能提示一次：拦截器已提示的业务错误，
 *    业务代码 catch 中不得再弹一条不同的提示。
 *
 * 实现方式：mock axios 以捕获真实 libs/http.js 注册的响应拦截器，
 * 然后驱动真实拦截器代码，不做源码字符串匹配。
 */
import { message } from 'antd';

// jest.mock 与 import 都会被提升，工厂执行时机早于模块体，
// 因此容器必须在工厂内惰性初始化。
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    interceptors: {
      request: { use: () => {} },
      response: {
        use: (onOk, onErr) => {
          global.__mockResponseHandlers = global.__mockResponseHandlers || [];
          global.__mockErrorHandlers = global.__mockErrorHandlers || [];
          global.__mockResponseHandlers.push(onOk);
          if (onErr) global.__mockErrorHandlers.push(onErr);
        },
      },
    },
    defaults: { headers: {} },
  },
}));

jest.mock('libs/history', () => ({
  __esModule: true,
  default: { location: { pathname: '/regulation' }, push: jest.fn() },
}));

jest.mock('libs/functools', () => ({
  __esModule: true,
  X_TOKEN: 'unit-test-token-placeholder',
}));

jest.mock('libs/systemFolderContext', () => ({
  __esModule: true,
  getSystemFolder: () => null,
  shouldUseSystemFolder: () => false,
}));

// eslint-disable-next-line import/first
import { http } from 'libs';

function onFulfilled() {
  const handlers = global.__mockResponseHandlers || [];
  return handlers[handlers.length - 1];
}

function jsonResponse(payload, extra = {}) {
  return {
    status: 200,
    statusText: 'OK',
    headers: { 'content-type': 'application/json' },
    config: { url: '/api/regulation/create/', method: 'post', isInternal: true, ...extra },
    data: payload,
  };
}

let errorSpy;
let successSpy;

beforeEach(() => {
  jest.clearAllMocks();
  errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
  successSpy.mockRestore();
});

describe('HTTP 200 + error 不得被当作成功', () => {
  test('业务错误响应必须 reject，而不是 resolve', async () => {
    const result = onFulfilled()(jsonResponse({ error: '规章编号不能为空', data: '' }));
    await expect(result).rejects.toBe('规章编号不能为空');
  });

  test('业务错误响应只弹一次错误提示', async () => {
    // 每个用例使用不同文案，规避拦截器 2 秒去重窗口的相互影响
    try {
      await onFulfilled()(jsonResponse({ error: '单次提示错误A', data: '' }));
    } catch (ignored) {
      /* 预期 reject */
    }
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith('单次提示错误A');
    expect(successSpy).not.toHaveBeenCalled();
  });

  test('正常响应解包 data 且不弹任何提示', async () => {
    const data = await onFulfilled()(jsonResponse({ error: '', data: { id: 1 } }));
    expect(data).toEqual({ id: 1 });
    expect(errorSpy).not.toHaveBeenCalled();
  });

  test('data 为空字符串时解包为空对象', async () => {
    const data = await onFulfilled()(jsonResponse({ error: '', data: '' }));
    expect(data).toEqual({});
  });

  test('skipErrorNotification 可抑制拦截器提示（用于业务代码自行提示的场景）', async () => {
    try {
      await onFulfilled()(jsonResponse({ error: '静默错误', data: '' },
        { skipErrorNotification: true }));
    } catch (ignored) {
      /* 预期 reject */
    }
    expect(errorSpy).not.toHaveBeenCalled();
  });

  test('二进制响应中的 JSON 错误体也能被识别为失败', async () => {
    const resp = {
      status: 200,
      statusText: 'OK',
      headers: { 'content-type': 'application/json' },
      config: { url: '/api/regulation/1/attachments/1/download/', responseType: 'blob',
        isInternal: true },
      data: JSON.stringify({ error: '附件不存在' }),
    };
    await expect(onFulfilled()(resp)).rejects.toBe('附件不存在');
  });

  test('二进制正常响应直接透传，不被当作错误', async () => {
    const payload = { headers: { 'content-type': 'application/pdf' }, data: 'blob' };
    const resp = {
      status: 200,
      statusText: 'OK',
      headers: payload.headers,
      config: { url: '/api/regulation/1/attachments/1/download/', responseType: 'blob',
        isInternal: true },
      data: payload.data,
    };
    await expect(onFulfilled()(resp)).resolves.toBe(resp);
    expect(errorSpy).not.toHaveBeenCalled();
  });
});

describe('错误去重与双提示风险', () => {
  test('拦截器 2 秒内重复相同消息只提示一次', async () => {
    const handler = onFulfilled();
    for (let i = 0; i < 3; i++) {
      try {
        await handler(jsonResponse({ error: '重复错误', data: '' }));
      } catch (ignored) {
        /* 预期 reject */
      }
    }
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });

  test('reject 值是字符串而非 Error：业务代码 e.message 为 undefined（双提示根因）', async () => {
    let rejected;
    try {
      await onFulfilled()(jsonResponse({ error: '规章编号不能为空', data: '' }));
    } catch (e) {
      rejected = e;
    }
    expect(typeof rejected).toBe('string');
    expect(rejected.message).toBeUndefined();
    // 业务代码 `.catch(e => message.error(e.message || '操作失败'))` 会退化为 '操作失败'
    const businessFallback = rejected.message || '操作失败';
    expect(businessFallback).toBe('操作失败');
    expect(businessFallback).not.toBe('规章编号不能为空');
  });
});

describe('http 模块导出', () => {
  test('libs 导出 http 且响应拦截器已注册', () => {
    expect(http).toBeDefined();
    expect((global.__mockResponseHandlers || []).length).toBeGreaterThan(0);
    expect((global.__mockErrorHandlers || []).length).toBeGreaterThan(0);
  });
});
