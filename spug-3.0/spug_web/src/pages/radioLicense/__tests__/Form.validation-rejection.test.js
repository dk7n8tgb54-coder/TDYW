/**
 * F-12 缺陷验证用例：Form.handleSubmit 的 form.validateFields() 无 .catch
 * （上线门禁复验）。
 *
 * 真实渲染执照 Form，**不包装 validateFields**（区别于 Form.behavior.test.js
 * 中为继续验证其他行为而做的吸收包装），注册 unhandledRejection 记录器，
 * 在空表单上触发提交并冲刷微任务。
 *
 * 规格：校验失败是可预期的交互路径，提交处理器必须消化该拒绝，
 * 不得产生未处理的 Promise 拒绝（生产表现为浏览器控制台
 * Uncaught (in promise)；Node 20 下足以使进程崩溃）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpPost = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: jest.fn().mockResolvedValue([]),
    post: mockHttpPost,
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  X_TOKEN: 'test-token',
}));

jest.mock('components', () => ({
  AttachmentManager: () => <div data-testid="attachment-manager">ATT</div>,
}));

const ComForm = require('../Form').default;
const S = require('../store').default;

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {},
    dispatchEvent: () => false,
  });
}

// 记录未处理的 Promise 拒绝（只移除自己的监听器，不动 jest 的）
const rejections = [];
const rejectionRecorder = (reason) => {
  rejections.push(reason && reason.errorFields
    ? `validateFields 拒绝: ${reason.errorFields.map(f => f.name.join('.')).join(', ')}`
    : String(reason));
};
process.on('unhandledRejection', rejectionRecorder);
afterAll(() => {
  process.off('unhandledRejection', rejectionRecorder);
});

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  rejections.length = 0;
  sessionStorage.setItem('token', 'rg-test-token');
  S.responsibleUsers = [];
  S.responsibleUsersLoaded = true;
  S._responsibleUsersToken = 'rg-test-token';
  S.formVisible = true;
  S.detailVisible = false;
  S.record = {};
});

afterEach(() => {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
  document.querySelectorAll('.ant-modal-root').forEach(n => n.remove());
  S.formVisible = false;
  S.record = {};
  sessionStorage.removeItem('token');
});

describe('F-12 验证：空表单提交的校验拒绝必须被处理', () => {
  it('点击确定触发校验失败后，不应产生未处理的 Promise 拒绝', async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<ComForm/>, container);
    });
    const okBtn = document.querySelector('.ant-modal-footer .ant-btn-primary');
    expect(okBtn).toBeTruthy();
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      // 冲刷微任务链，让 validateFields 的拒绝暴露
      await new Promise(r => setTimeout(r, 0));
    });
    // 校验错误正常显示（这是正确的行为部分）
    const errors = Array.from(document.querySelectorAll('.ant-form-item-explain'))
      .map(el => el.textContent.trim());
    expect(errors).toContain('请输入台站名称');
    // 规格：不得有未处理的 Promise 拒绝
    expect(rejections).toEqual([]);
  });
});
