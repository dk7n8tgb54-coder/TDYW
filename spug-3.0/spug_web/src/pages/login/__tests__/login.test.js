/**
 * 登录页测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例，无 @testing-library），mock libs.http /
 * libs.history / routes（避免拖入全部页面组件），验证：
 * - 提交登录：POST /api/account/login/ 携带账号密码与登录类型
 * - 登录成功：写入 sessionStorage 会话信息、updatePermissions 调用、跳转默认路由
 * - location.state.from 优先于默认路由
 * - 默认路由：无工作台权限时递归找第一个有权限的菜单；都没有则回个人中心
 * - required_mfa：出现验证码输入框与 30 秒倒计时；未填验证码提交被拦截
 * - has_real_ip 为否：弹安全警告，确认后完成登录
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染组件。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import Login from '../index';
import { http, updatePermissions } from 'libs';
import history from 'libs/history';

const mockHttpPost = jest.fn();
const mockHistoryPush = jest.fn();
const mockHasPermission = jest.fn(() => false);

jest.mock('libs', () => ({
  http: {post: (...args) => mockHttpPost(...args)},
  updatePermissions: jest.fn(),
  hasPermission: (...args) => mockHasPermission(...args),
}));

jest.mock('libs/history', () => ({
  __esModule: true,
  default: {
    push: (...args) => mockHistoryPush(...args),
    location: {state: null},
  },
}));

// 登录页 import routes 会拖入全部页面组件（含图表库），mock 掉只保留路由结构
jest.mock('../../../routes', () => ([
  {title: '工作台', path: '/home', auth: 'dashboard.dashboard.view'},
  {title: '业务', child: [
    {title: '值班日志', path: '/duty', auth: 'duty.duty.view'},
    {title: '资料库', path: '/document', auth: 'document.document.view'},
  ]},
  {title: '个人中心', child: [{title: '信息', path: '/welcome/info'}]},
]));

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

const LOGIN_OK = {
  id: 1,
  access_token: 'tok-123',
  nickname: '测试用户',
  is_supper: false,
  tenant_id: 't1',
  permissions: {dashboard: {}},
  has_real_ip: true,
};

let container = null;

function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function getInputs() {
  const inputs = document.querySelectorAll('input[placeholder]');
  return {
    username: Array.from(inputs).find(i => i.placeholder === '请输入账户'),
    password: Array.from(inputs).find(i => i.placeholder === '请输入密码'),
    captcha: Array.from(inputs).find(i => i.placeholder === '请输入验证码'),
  };
}

async function renderLogin() {
  await act(async () => {
    ReactDOM.render(<Login />, container);
  });
}

async function clickLogin() {
  // antd 对两字中文按钮自动插入空格，文本为"登 录"
  const btn = Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s/g, '') === '登录');
  expect(btn).toBeTruthy();
  await act(async () => {
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await act(async () => {});
}

function fillCredentials(username = 'admin', password = 'pass123') {
  const {username: u, password: p} = getInputs();
  act(() => {
    setInputValue(u, username);
    setInputValue(p, password);
  });
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  mockHttpPost.mockReset();
  mockHistoryPush.mockReset();
  mockHasPermission.mockReset();
  mockHasPermission.mockImplementation(() => false);
  history.location.state = null;
  sessionStorage.clear();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
  sessionStorage.clear();
});

describe('登录提交', () => {
  it('POST 携带账号密码与登录类型', async () => {
    await renderLogin();
    fillCredentials();
    mockHttpPost.mockReturnValue(new Promise(() => {}));
    await clickLogin();
    expect(mockHttpPost).toHaveBeenCalledWith('/api/account/login/', {
      username: 'admin',
      password: 'pass123',
      type: 'default',
    });
  });

  it('登录成功：写入会话信息并跳转默认路由', async () => {
    await renderLogin();
    fillCredentials();
    mockHttpPost.mockResolvedValue(LOGIN_OK);
    await clickLogin();
    expect(sessionStorage.getItem('token')).toBe('tok-123');
    expect(sessionStorage.getItem('nickname')).toBe('测试用户');
    expect(sessionStorage.getItem('tenant_id')).toBe('t1');
    expect(sessionStorage.getItem('is_supper')).toBe('false');
    expect(JSON.parse(sessionStorage.getItem('permissions'))).toEqual({dashboard: {}});
    expect(updatePermissions).toHaveBeenCalled();
    // 无任何权限：默认路由回退个人中心
    expect(mockHistoryPush).toHaveBeenCalledWith('/welcome/info');
  });

  it('location.state.from 优先于默认路由', async () => {
    history.location.state = {from: '/duty/detail'};
    await renderLogin();
    fillCredentials();
    mockHttpPost.mockResolvedValue(LOGIN_OK);
    await clickLogin();
    expect(mockHistoryPush).toHaveBeenCalledWith('/duty/detail');
  });

  it('无工作台权限时跳转第一个有权限的菜单', async () => {
    mockHasPermission.mockImplementation(perm => perm === 'duty.duty.view');
    await renderLogin();
    fillCredentials();
    mockHttpPost.mockResolvedValue(LOGIN_OK);
    await clickLogin();
    expect(mockHistoryPush).toHaveBeenCalledWith('/duty');
  });

  it('有工作台权限时优先跳转工作台', async () => {
    mockHasPermission.mockImplementation(perm => perm === 'dashboard.dashboard.view');
    await renderLogin();
    fillCredentials();
    mockHttpPost.mockResolvedValue(LOGIN_OK);
    await clickLogin();
    expect(mockHistoryPush).toHaveBeenCalledWith('/home');
  });
});

describe('MFA 验证码流程', () => {
  it('required_mfa 后出现验证码输入框与 30 秒倒计时', async () => {
    await renderLogin();
    fillCredentials();
    mockHttpPost.mockResolvedValue({required_mfa: true});
    await clickLogin();
    const {captcha} = getInputs();
    expect(captcha).toBeTruthy();
    // 倒计时按钮禁用并显示 30 秒
    const countdown = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.includes('秒后重新获取'));
    expect(countdown).toBeTruthy();
    expect(countdown.textContent).toContain('30');
    expect(countdown.disabled).toBe(true);
  });

  it('MFA 模式下未填验证码提交被拦截，不发请求', async () => {
    await renderLogin();
    fillCredentials();
    mockHttpPost.mockResolvedValueOnce({required_mfa: true});
    await clickLogin();
    expect(getInputs().captcha).toBeTruthy();
    // 第二次提交：验证码为空 → 拦截，不再发请求
    mockHttpPost.mockClear();
    await clickLogin();
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(document.querySelector('.ant-message')).toBeTruthy();
  });
});

describe('真实 IP 校验', () => {
  it('has_real_ip 为否时弹安全警告，确认后完成登录', async () => {
    await renderLogin();
    fillCredentials();
    mockHttpPost.mockResolvedValue({...LOGIN_OK, has_real_ip: false});
    await clickLogin();
    // 安全警告弹窗
    const confirmModal = document.querySelector('.ant-modal-confirm');
    expect(confirmModal).toBeTruthy();
    expect(confirmModal.textContent).toContain('安全警告');
    // 警告弹窗期间不应写入会话
    expect(sessionStorage.getItem('token')).toBeNull();
    // 点击确定 → 完成登录
    const okBtn = document.querySelector('.ant-modal-confirm .ant-btn-primary');
    expect(okBtn).toBeTruthy();
    await act(async () => {
      okBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await act(async () => {});
    expect(sessionStorage.getItem('token')).toBe('tok-123');
    expect(mockHistoryPush).toHaveBeenCalledWith('/welcome/info');
  });
});
