/**
 * 规章管理新建/编辑弹窗错误提示行为测试（defect_reproduction）
 *
 * 需求（AGENTS.md 第九条第 3 点）：
 *   同一个错误只能提示一次。HTTP 拦截器已提示的错误，业务代码不得重复提示。
 *
 * 期望（正确行为）：
 *   后端返回 HTTP 200 + {"error": "..."} 时，用户只看到 1 条错误提示，
 *   并且弹窗不关闭、不刷新列表、不弹成功提示。
 *
 * 现状（缺陷 REG-UI-001，P2）：
 *   libs/http.js 拦截器先 message.error(原始错误文案)，并以字符串 reject；
 *   Form/CategoryForm 的 .catch(e => message.error(e.message || '操作失败'))
 *   因 reject 值是字符串（e.message 为 undefined）而又弹出一条 '操作失败'，
 *   两条文案不同，2 秒去重窗口不生效 -> 用户看到 2 条提示。
 *
 * 实现方式：mock axios 捕获真实响应拦截器，mock libs 让 http.put/post
 * 走真实拦截器代码，再渲染真实 Form 组件，统计 antd message 调用次数。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import { message } from 'antd';

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    interceptors: {
      request: { use: () => {} },
      response: {
        use: (onOk, onErr) => {
          global.__promptHandlers = global.__promptHandlers || {};
          global.__promptHandlers.ok = onOk;
          global.__promptHandlers.err = onErr;
        },
      },
    },
    defaults: { headers: {} },
  },
}));

jest.mock('components', () => ({
  AttachmentManager: () => null,
}));

jest.mock('libs', () => {
  // 加载真实 libs/http.js，使其把响应拦截器注册到被 mock 的 axios 上
  // eslint-disable-next-line global-require
  require('libs/http');
  const runInterceptor = (url, method) => {
    const handler = (global.__promptHandlers || {}).ok;
    return handler({
      status: 200,
      statusText: 'OK',
      headers: { 'content-type': 'application/json' },
      config: { url, method, isInternal: true },
      data: { error: '规章编号不能为空', data: '' },
    });
  };
  return {
    hasPermission: () => true,
    http: {
      get: () => Promise.resolve({}),
      post: (url) => runInterceptor(url, 'post'),
      put: (url) => runInterceptor(url, 'put'),
      delete: (url) => runInterceptor(url, 'delete'),
    },
  };
});

// eslint-disable-next-line import/first
import ComForm from '../Form';
import S from '../store';

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const EDIT_RECORD = {
  id: 1,
  title: '测试规章',
  rule_no: 'R-001',
  category_id: 5,
  issuing_authority: '某单位',
  biz_type: '空管',
  publish_date: '2026-01-01',
  effective_date: '2026-02-01',
  status: 'active',
};

let container = null;
let errorSpy = null;
let successSpy = null;

function renderEditForm() {
  S.record = EDIT_RECORD;
  S.detailVisible = false;
  S.formVisible = true;
  act(() => {
    ReactDOM.render(<ComForm />, container);
  });
}

async function clickOk() {
  const okBtn = document.querySelector('.ant-modal-footer .ant-btn-primary');
  expect(okBtn).toBeTruthy();
  await act(async () => {
    okBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await act(async () => {});
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
  successSpy.mockRestore();
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
  S.record = {};
  S.detailVisible = false;
  S.formVisible = false;
});

describe('HTTP 200 + error 时弹窗行为', () => {
  test('只提示一次错误，不弹成功、不关闭弹窗、不刷新列表', async () => {
    renderEditForm();
    await clickOk();

    // 拒绝后 .then 分支不执行：不弹成功、不关闭弹窗、不刷新列表
    expect(successSpy).not.toHaveBeenCalled();
    expect(S.formVisible).toBe(true);
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });
});
