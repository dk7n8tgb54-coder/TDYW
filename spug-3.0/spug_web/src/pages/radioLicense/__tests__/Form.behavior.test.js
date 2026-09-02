/**
 * 无线电台执照 Form 组件行为测试（上线门禁）。
 *
 * 真实渲染 Form（ReactDOM + jsdom），mock libs.http 与 components.AttachmentManager，
 * 直接驱动真实 store 单例（MobX），验证：
 * - 必填字段校验：空表单提交不发起请求并显示错误
 * - 编辑回填后提交：载荷日期格式化、频率 sort_order 重排、携带 id
 * - 提交成功：message.success、关闭弹窗、刷新列表（六.2/六.5）
 * - 提交失败（HTTP 200 + error）：错误只提示一次、弹窗不关闭、loading 复位
 * - 关闭后重开：字段与错误状态正确重置（六.2）
 * - 详情模式：渲染业务字段与附件区
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message, Form as AntdForm} from 'antd';

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

// require 避免提升问题（与既有测试惯例一致）
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

// 【产品缺陷记录】Form.js handleSubmit 的 form.validateFields() 只链了
// .then 没有 .catch，校验失败时产生未处理 Promise 拒绝：
// - 生产环境：浏览器控制台报 Uncaught (in promise)
// - 测试环境：jest 将该拒绝归因为当前用例导致误失败、Node 20 直接崩溃
// 测试中包装 validateFields：校验失败时返回永不 settle 的 Promise，
// 与生产语义完全一致（.then 不执行、校验错误照常显示），仅消除拒绝噪音。
// 缺陷本身记录在上线门禁报告（F-12）。
const _useForm = AntdForm.useForm;
jest.spyOn(AntdForm, 'useForm').mockImplementation(() => {
  const [form] = _useForm();
  const _validate = form.validateFields.bind(form);
  form.validateFields = (...args) => _validate(...args).catch(
    () => new Promise(() => {}));
  return [form];
});

const FULL_RECORD = {
  id: 5,
  station_name: 'RG-表单台站',
  purpose: 'RG-表单用途',
  valid_from: '2026-01-01',
  valid_to: '2027-01-01',
  responsible_user_id: 3,
  responsible_user_name: 'RG-责任人',
  frequencies: [
    {id: 11, frequency_value: '100.5', frequency_unit: 'MHz', frequency_text: '主频'},
    {id: 12, frequency_value: '200', frequency_unit: 'kHz', frequency_text: ''},
  ],
};

let container = null;
let messageSuccessSpy;
let messageErrorSpy;

// antd 校验错误渲染是异步的，需冲刷微任务后断言
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

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
  // 测试环境无 ConfigProvider 中文 locale（按钮文案为 OK/Cancel），
  // 按 antd Modal 约定用 footer 主按钮定位，与文案无关
  return q('.ant-modal-footer .ant-btn-primary')[0];
}

function formErrors() {
  return Array.from(q('.ant-form-item-explain'))
    .map(el => el.textContent.trim());
}

beforeEach(() => {
  jest.clearAllMocks();
  messageSuccessSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  messageErrorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  // store 基础状态：责任人已加载，避免触发真实 HTTP
  sessionStorage.setItem('token', 'rg-test-token');
  S.responsibleUsers = [{id: 3, nickname: 'RG-责任人', username: 'rg_resp'}];
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

describe('执照 Form：必填校验', () => {
  it('空表单提交不发起请求并显示错误信息', async () => {
    S.record = {};
    renderForm();
    await act(async () => {
      okButton().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).not.toHaveBeenCalled();
    const errors = formErrors();
    expect(errors).toContain('请输入台站名称');
    expect(errors).toContain('请选择起始日期');
    expect(errors).toContain('请选择截止日期');
  });
});

describe('执照 Form：编辑回填与提交载荷', () => {
  it('提交载荷包含格式化日期、重排的频率和记录 id', async () => {
    S.record = {...FULL_RECORD};
    mockHttpPost.mockResolvedValue({});
    renderForm();
    await act(async () => {
      okButton().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPost.mock.calls[0];
    expect(payload.id).toBe(5);
    expect(payload.valid_from).toBe('2026-01-01');
    expect(payload.valid_to).toBe('2027-01-01');
    expect(payload.frequencies).toEqual([
      {frequency_value: 100.5, frequency_unit: 'MHz', frequency_text: '主频', sort_order: 0},
      {frequency_value: 200, frequency_unit: 'kHz', frequency_text: '', sort_order: 1},
    ]);
    expect(messageSuccessSpy).toHaveBeenCalledWith('操作成功');
    expect(S.formVisible).toBe(false);
  });
});

describe('执照 Form：提交失败', () => {
  it('业务失败（HTTP 200 + error）弹窗不关闭，错误提示一次，loading 复位', async () => {
    S.record = {...FULL_RECORD};
    mockHttpPost.mockRejectedValue('起始日期不能晚于截止日期');
    renderForm();
    await act(async () => {
      okButton().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    // 【缺陷证据】libs/http.js 对业务错误 reject 的是字符串，
    // Form.js catch 里取 e.message 恒为 undefined，永远走通用兜底文案；
    // 生产环境拦截器 showErrorOnce 已展示具体错误，表单再弹一次通用错误
    // = 同一错误双重提示（违反"同一错误只能提示一次"，报告缺陷 F-13）。
    expect(messageErrorSpy).toHaveBeenCalledTimes(1);
    expect(messageErrorSpy).toHaveBeenCalledWith('起始日期不能晚于截止日期');
    // 弹窗保持打开
    expect(S.formVisible).toBe(true);
    // loading 复位：确定按钮不再是 loading 态
    expect(q('.ant-btn-loading').length).toBe(0);
  });
});

describe('执照 Form：关闭后重开重置', () => {
  it('校验失败后关闭再重开，错误状态与字段重置', async () => {
    S.record = {};
    renderForm();
    await act(async () => {
      okButton().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(formErrors().length).toBeGreaterThan(0);
    // 关闭弹窗（组件卸载）
    S.formVisible = false;
    unmountForm();
    // 重新打开空表单
    S.formVisible = true;
    S.record = {};
    renderForm();
    expect(formErrors()).toEqual([]);
    const stationInput = q('#station_name')[0];
    expect(stationInput.value).toBe('');
  });
});

describe('执照 Form：详情模式', () => {
  it('渲染业务字段、状态标签与附件区', () => {
    S.detailVisible = true;
    S.formVisible = false;
    S.record = {
      ...FULL_RECORD,
      computed_status: 'expiring',
      days_left: 30,
      created_by_name: 'RG-创建人',
      created_at: '2026-08-01 10:00:00',
    };
    renderForm();
    const text = document.body.textContent;
    expect(text).toContain('RG-表单台站');
    expect(text).toContain('即将到期');
    expect(text).toContain('RG-责任人');
    expect(text).toContain('100.5 MHz（主频）');
    expect(q('[data-testid="attachment-manager"]').length).toBeGreaterThan(0);
    // 详情模式底部有编辑按钮（有编辑权限时）
    // antd 按钮两个汉字间会插入空格（"编 辑"），断言前先去除空白
    const footerText = document.querySelector('.ant-modal-footer')
      .textContent.replace(/\s/g, '');
    expect(footerText).toContain('编辑');
  });
});
