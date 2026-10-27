/**
 * 干扰分类选项管理页行为测试（2026-10-25 分类选项化改造）。
 *
 * 真实渲染 CategoriesPage（ReactDOM + jsdom），mock libs.http，验证：
 * - 以 include_inactive=1 加载全量选项并渲染启用/停用状态
 * - 新增弹窗空提交被校验拦截、编码规则拦截，不发起请求
 * - 编辑弹窗回填后提交载荷携带不可变编码与更新后的名称
 * - 删除：确认弹窗、取消不发请求、成功后刷新列表、失败保留列表且不重复提示
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true, permissions: []},
}));

const CategoriesPage = require('../categories').default;

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

const RECORDS = {
  records: [
    {
      id: 1, group: 'interference_kind', group_text: '具体干扰类型',
      code: 'noise', name: '杂音', sort_id: 10, is_active: true,
    },
    {
      id: 2, group: 'source_type', group_text: '疑似干扰源',
      code: 'environment', name: '环境', sort_id: 50, is_active: false,
    },
  ],
  groups: [
    {value: 'interference_kind', label: '具体干扰类型'},
    {value: 'affected_system', label: '受影响系统'},
    {value: 'source_type', label: '疑似干扰源'},
  ],
};

let container = null;

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function renderPage() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<CategoriesPage/>, container);
  });
}

function unmountPage() {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
}

function q(selector) {
  return Array.from(document.querySelectorAll(selector));
}

function setNativeValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

function click(node) {
  act(() => {
    node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

function modalOk() {
  return q('.ant-modal-footer .ant-btn-primary')[0];
}

function modalErrors() {
  return q('.ant-modal .ant-form-item-explain').map(x => x.textContent.trim());
}

function rowContaining(text) {
  return q('.ant-table-row').find(row => row.textContent.includes(text));
}

function confirmModal() {
  return document.querySelector('.ant-modal-confirm');
}

// okType danger 时 OK 按钮不带 primary 类；antd 默认渲染顺序为 [取消, 确定]
function confirmButtons() {
  return q('.ant-modal-confirm-btns .ant-btn');
}

function confirmOk() {
  return confirmButtons().slice(-1)[0];
}

function confirmCancel() {
  return confirmButtons()[0];
}

let messageSuccessSpy;
let messageErrorSpy;

beforeEach(() => {
  jest.clearAllMocks();
  mockHttpGet.mockResolvedValue(RECORDS);
  messageSuccessSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  messageErrorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
});

afterEach(async () => {
  unmountPage();
  // antd 确认弹窗关闭动画的卸载定时器（约 300ms）若被提前摘除节点，
  // 会在下一个用例的时间窗内抛 jsdom NotFoundError；先等它完成再清理
  await new Promise(resolve => setTimeout(resolve, 400));
  document.querySelectorAll('.ant-modal-root, .ant-modal-confirm').forEach(n => n.remove());
  messageSuccessSpy.mockRestore();
  messageErrorSpy.mockRestore();
});

describe('分类选项管理页', () => {
  it('以全量口径加载选项并渲染启用/停用状态', async () => {
    renderPage();
    await act(async () => { await flush(); });
    expect(mockHttpGet).toHaveBeenCalledWith('/api/interference/categories/', {
      params: {include_inactive: 1, group: undefined},
    });
    const text = document.body.textContent;
    expect(text).toContain('noise');
    expect(text).toContain('杂音');
    expect(text).toContain('已停用');
  });

  it('新增弹窗空提交被必填与编码规则拦截，不发起请求', async () => {
    renderPage();
    await act(async () => { await flush(); });
    const addButton = q('.ant-btn').find(btn => btn.textContent.includes('新增选项'));
    click(addButton);
    await act(async () => { await flush(); });
    click(modalOk());
    await act(async () => { await flush(); });
    expect(mockHttpPost).not.toHaveBeenCalled();
    const errors = modalErrors();
    expect(errors).toContain('请选择分组');
    expect(errors).toContain('请输入编码');
  });

  it('新增弹窗非法编码被规则拦截', async () => {
    renderPage();
    await act(async () => { await flush(); });
    const addButton = q('.ant-btn').find(btn => btn.textContent.includes('新增选项'));
    click(addButton);
    await act(async () => { await flush(); });
    const codeInput = q('.ant-modal #code')[0];
    setNativeValue(codeInput, 'Bad-Code');
    click(modalOk());
    await act(async () => { await flush(); });
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(modalErrors().join('\n')).toContain('小写字母开头');
  });

  it('编辑弹窗回填存量值，提交载荷携带编码与更新后的名称', async () => {
    mockHttpPut.mockResolvedValue({});
    renderPage();
    await act(async () => { await flush(); });
    const row = rowContaining('noise');
    const editButton = Array.from(row.querySelectorAll('.ant-btn'))
      .find(btn => btn.textContent.includes('编辑'));
    click(editButton);
    await act(async () => { await flush(); });
    const nameInput = q('.ant-modal #name')[0];
    expect(nameInput.value).toBe('杂音');
    setNativeValue(nameInput, '电磁杂音');
    click(modalOk());
    await act(async () => { await flush(); });
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toBe('/api/interference/categories/1/');
    expect(payload.code).toBe('noise');
    expect(payload.group).toBe('interference_kind');
    expect(payload.name).toBe('电磁杂音');
  });
});

describe('删除分类选项', () => {
  // 注意：必须用顺序 await；act 返回的 thenable 链式 .then 会破坏
  // act 作用域，点击后的 Modal.confirm 不会挂载（本套件踩过的坑）
  async function openDeleteConfirm() {
    renderPage();
    await act(async () => { await flush(); });
    const row = rowContaining('noise');
    const removeButton = Array.from(row.querySelectorAll('.ant-btn'))
      .find(btn => btn.textContent.includes('删除'));
    click(removeButton);
    await act(async () => { await flush(); });
  }

  it('点击删除弹出确认弹窗，取消不发起请求', async () => {
    await openDeleteConfirm();
    expect(confirmModal()).toBeTruthy();
    expect(confirmModal().textContent).toContain('杂音');
    expect(confirmModal().textContent).toContain('未被任何干扰事件引用');
    click(confirmCancel());
    await act(async () => { await flush(); });
    expect(mockHttpDelete).not.toHaveBeenCalled();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
  });

  it('确认后发起删除，成功提示并刷新列表', async () => {
    mockHttpDelete.mockResolvedValue({});
    await openDeleteConfirm();
    click(confirmOk());
    await act(async () => { await flush(); });
    expect(mockHttpDelete).toHaveBeenCalledWith('/api/interference/categories/1/');
    expect(messageSuccessSpy).toHaveBeenCalledWith('删除成功');
    // 删除成功后重新拉取列表（get 调用次数从 1 变为 2）
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
  });

  it('删除失败时保留列表且不重复提示业务错误', async () => {
    // 延迟一拍再拒绝，避开 jsdom 在事件分发内卸载确认弹窗的已知竞态
    mockHttpDelete.mockImplementation(() => new Promise((resolve, reject) => {
      setTimeout(() => reject('该选项已被干扰事件引用，不能删除；如需不再供新事件选择，请使用停用功能'), 10);
    }));
    await openDeleteConfirm();
    await act(async () => {
      click(confirmOk());
      await flush();
      await flush();
    });
    expect(mockHttpDelete).toHaveBeenCalledTimes(1);
    // 业务错误由统一 HTTP 拦截器提示，页面代码不得再弹一次
    expect(messageErrorSpy).not.toHaveBeenCalled();
    expect(messageSuccessSpy).not.toHaveBeenCalled();
    // 列表不刷新
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
  });
});
