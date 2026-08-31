/**
 * 交付详情（InboxDetail）组件行为测试
 *
 * 真实渲染组件（react-dom + act），验证：
 * - 挂载即发起详情请求，成功后渲染交付明细
 * - 提交按钮请求完成前防重复触发（issue：双击重复提交）
 * - 提交成功：刷新详情、通知父级、刷新角标；提交失败：不刷新不通知且按钮恢复
 * - 组件卸载后未完成请求的回调不再回写状态、不触发父级刷新（issue：卸载后 setState）
 * - assignmentId 切换后旧请求响应不得覆盖新数据（issue：旧请求覆盖新状态）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {notification} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHasPermission = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: mockHasPermission,
  X_TOKEN: 'test-token',
}));

jest.mock('components/AttachmentManager', () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock('@/layout/CoopTaskBadgeStore', () => ({
  __esModule: true,
  default: {fetch: jest.fn()},
}));

// 用 require 而非 import：import 会被提升到 mock 变量声明之前，
// 触发 "Cannot access before initialization"（与既有 coopTaskUtils.test.js 一致）
const InboxDetail = require('../InboxDetail').default;
const coopTaskBadge = require('@/layout/CoopTaskBadgeStore').default;

// jsdom 无 matchMedia，antd 响应式组件需要
if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false;
    },
  });
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return {promise, resolve, reject};
}

function buildTask(assignmentId, title) {
  return {
    id: 7,
    title,
    description: '',
    deadline: '2026-09-30 18:00',
    is_overdue: false,
    status: 'in_progress',
    created_by_name: '张三',
    created_at: '2026-08-30 10:00',
    urge_count: 0,
    assignment_id: assignmentId,
    target_tenant_name: '二科',
    aggregate_status: 'pending',
    aggregate_status_text: '待交付',
    items: [
      {
        id: 100,
        item_name: '材料A',
        item_remark: '',
        status: 'pending',
        attachment_count: 1, // 有附件才允许提交
        reject_reason: '',
        templates: [],
      },
    ],
  };
}

function renderModal(element) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(element, container);
  });
  return container;
}

async function flush() {
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

function findSubmitButton() {
  // antd 4 对两个汉字按钮自动插入空格（"提 交"），匹配前归一化空白
  return [...document.body.querySelectorAll('button')].find(
    b => b.textContent.replace(/\s+/g, '') === '提交');
}

function click(el) {
  act(() => {
    el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

const unmountedWarnings = () =>
  console.error.mock.calls.filter(call =>
    /unmounted component/i.test(String(call[0])));

describe('InboxDetail 组件行为', () => {
  let containers;
  let onChanged;
  let onClose;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(console, 'error').mockImplementation(() => {});
    jest.spyOn(notification, 'success').mockImplementation(() => {});
    jest.spyOn(notification, 'error').mockImplementation(() => {});
    mockHasPermission.mockReturnValue(true);
    containers = [];
    onChanged = jest.fn();
    onClose = jest.fn();
  });

  afterEach(() => {
    containers.forEach(c => {
      ReactDOM.unmountComponentAtNode(c);
      c.remove();
    });
    console.error.mockRestore();
    notification.success.mockRestore();
    notification.error.mockRestore();
  });

  const mount = assignmentId => {
    const c = renderModal(
      <InboxDetail assignmentId={assignmentId}
                   onClose={onClose} onChanged={onChanged} />);
    containers.push(c);
    return c;
  };

  test('挂载即请求交付详情并渲染材料', async () => {
    mockHttpGet.mockResolvedValueOnce(buildTask(10, '交付任务甲'));
    mount(10);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/coop-task/inbox/10/');
    await flush();
    expect(document.body.textContent).toContain('交付任务甲');
    expect(document.body.textContent).toContain('材料A');
    expect(findSubmitButton()).toBeTruthy();
  });

  test('提交按钮请求完成前不可重复触发', async () => {
    mockHttpGet.mockResolvedValue(buildTask(10, '交付任务甲')); // 初次与刷新均有响应
    const sd = deferred();
    mockHttpPost.mockImplementation(() => sd.promise);
    mount(10);
    await flush();

    const btn = findSubmitButton();
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);

    click(btn);
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/coop-task/deliveries/100/submit/');

    click(btn); // 请求未完成前再次点击
    expect(mockHttpPost).toHaveBeenCalledTimes(1); // 不得发出第二个提交请求
    expect(findSubmitButton().disabled).toBe(true); // 按钮进入提交中禁用态

    sd.resolve(undefined);
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2); // 成功后刷新详情
    expect(onChanged).toHaveBeenCalled();
    expect(coopTaskBadge.fetch).toHaveBeenCalled();
    expect(findSubmitButton().disabled).toBe(false); // 提交中状态已恢复
  });

  test('提交失败不刷新详情不通知父级，按钮恢复可用', async () => {
    mockHttpGet.mockResolvedValueOnce(buildTask(10, '交付任务甲'));
    mockHttpPost.mockRejectedValueOnce(new Error('network down'));
    mount(10);
    await flush();

    click(findSubmitButton());
    await flush();
    expect(onChanged).not.toHaveBeenCalled();
    expect(coopTaskBadge.fetch).not.toHaveBeenCalled();
    expect(mockHttpGet).toHaveBeenCalledTimes(1); // 失败不触发刷新
    expect(findSubmitButton().disabled).toBe(false); // 加载态已恢复
    expect(notification.success).not.toHaveBeenCalled();
  });

  test('卸载后未完成的提交请求不再回写状态、不触发父级刷新', async () => {
    mockHttpGet.mockResolvedValueOnce(buildTask(10, '交付任务甲'));
    const sd = deferred();
    mockHttpPost.mockImplementation(() => sd.promise);
    const container = renderModal(
      <InboxDetail assignmentId={10} onClose={onClose} onChanged={onChanged} />);
    containers.push(container);
    await flush();

    const btn = findSubmitButton();
    expect(btn).toBeTruthy();
    click(btn);
    expect(mockHttpPost).toHaveBeenCalledTimes(1);

    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    containers = containers.filter(c => c !== container);

    sd.resolve(undefined);
    await flush();
    expect(unmountedWarnings()).toHaveLength(0);
    expect(onChanged).not.toHaveBeenCalled();
    expect(coopTaskBadge.fetch).not.toHaveBeenCalled();
    expect(mockHttpGet).toHaveBeenCalledTimes(1); // 卸载后不追加刷新请求
  });

  test('assignmentId 切换后旧请求响应不覆盖新详情', async () => {
    const d10 = deferred();
    const d20 = deferred();
    mockHttpGet.mockImplementationOnce(() => d10.promise)
      .mockImplementationOnce(() => d20.promise);
    mount(10);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/coop-task/inbox/10/');

    act(() => {
      ReactDOM.render(
        <InboxDetail assignmentId={20} onClose={onClose} onChanged={onChanged}/>,
        containers[0]);
    });
    expect(mockHttpGet).toHaveBeenCalledWith('/api/coop-task/inbox/20/');

    d20.resolve(buildTask(20, '交付任务乙'));
    await flush();
    expect(document.body.textContent).toContain('交付任务乙');

    d10.resolve(buildTask(10, '交付任务甲')); // 旧请求迟到
    await flush();
    expect(document.body.textContent).toContain('交付任务乙');
    expect(document.body.textContent).not.toContain('交付任务甲');
  });
});
