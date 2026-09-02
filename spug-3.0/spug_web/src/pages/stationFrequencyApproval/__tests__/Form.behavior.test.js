/**
 * 台站频率批复 Form 组件行为测试（上线门监）。
 *
 * 真实渲染 Form，mock libs.http 与 components.AttachmentManager，验证：
 * - 前端日期顺序校验：valid_from > valid_to 时不发请求并提示（B2）
 * - 提交成功：message.success、关闭弹窗、刷新列表
 * - 提交失败：弹窗保持打开
 * - 详情模式：渲染业务字段与附件区
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

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
  AttachmentManager: () => <div data-testid="attachment-manager">ATTACHMENTS</div>,
}));

const ComForm = require('../Form').default;
const S = require('../store').default;

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  });
}

const FULL_RECORD = {
  id: 8,
  name: 'RG-批复表单',
  doc_no: 'RG-FORM-DOC',
  frequency_text: '88-108 MHz',
  valid_from: '2026-01-01',
  valid_to: '2027-01-01',
  responsible_user_id: 4,
  responsible_user_name: 'RG-责任人',
};

let container = null;
let messageSuccessSpy;
let messageErrorSpy;

function renderForm() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<ComForm/>, container);
  });
}

function unmountForm() {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
}

// antd Modal 渲染到 document.body 的 portal，必须从 body 查询
function q(selector) {
  return document.querySelectorAll(selector);
}

function okButton() {
  return Array.from(q('.ant-modal-footer .ant-btn'))
    .find(btn => btn.textContent.replace(/\s/g, '') === '确定');
}

beforeEach(() => {
  jest.clearAllMocks();
  messageSuccessSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  messageErrorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  sessionStorage.setItem('token', 'rg-test-token');
  S.responsibleUsers = [{id: 4, nickname: 'RG-责任人', username: 'rg_resp'}];
  S.responsibleUsersLoaded = true;
  S._responsibleUsersToken = 'rg-test-token';
  S.formVisible = true;
  S.detailVisible = false;
  S.record = {};
});

afterEach(() => {
  unmountForm();
  document.querySelectorAll('.ant-modal-root').forEach(n => n.remove());
  S.formVisible = false;
  S.detailVisible = false;
  S.record = {};
  sessionStorage.removeItem('token');
});

describe('批复 Form：前端日期顺序校验', () => {
  it('valid_from 晚于 valid_to 时不发请求并提示', async () => {
    S.record = {...FULL_RECORD, valid_from: '2027-06-01', valid_to: '2026-01-01'};
    renderForm();
    await act(async () => {
      okButton().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await Promise.resolve();
    });
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(messageErrorSpy).toHaveBeenCalledWith('起始日期不能晚于截止日期');
    expect(S.formVisible).toBe(true);
  });
});

describe('批复 Form：提交成功与失败', () => {
  it('成功后关闭弹窗并刷新列表', async () => {
    S.record = {...FULL_RECORD};
    mockHttpPost.mockResolvedValue({});
    renderForm();
    await act(async () => {
      okButton().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await Promise.resolve();
    });
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPost.mock.calls[0];
    expect(payload.id).toBe(8);
    expect(payload.valid_from).toBe('2026-01-01');
    expect(payload.valid_to).toBe('2027-01-01');
    expect(messageSuccessSpy).toHaveBeenCalledWith('操作成功');
    expect(S.formVisible).toBe(false);
  });

  it('业务失败（HTTP 200 + error）弹窗不关闭', async () => {
    S.record = {...FULL_RECORD};
    mockHttpPost.mockRejectedValue('权限拒绝：缺少编辑批复权限');
    renderForm();
    await act(async () => {
      okButton().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(S.formVisible).toBe(true);
    expect(q('.ant-btn-loading').length).toBe(0);
  });
});

describe('批复 Form：详情模式', () => {
  it('渲染业务字段与附件区', () => {
    S.detailVisible = true;
    S.formVisible = false;
    S.record = {
      ...FULL_RECORD,
      computed_status: 'expired',
      days_left: -3,
      attachment_count: 2,
      created_by_name: 'RG-创建人',
      created_at: '2026-08-01 10:00:00',
    };
    renderForm();
    const text = document.body.textContent;
    expect(text).toContain('RG-批复表单');
    expect(text).toContain('RG-FORM-DOC');
    expect(text).toContain('已过期');
    expect(q('[data-testid="attachment-manager"]').length).toBeGreaterThan(0);
  });
});
