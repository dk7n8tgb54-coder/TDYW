/**
 * 未读版本更新提示（ReleaseNoteNotification）组件行为测试
 *
 * 真实渲染组件（react-dom + act + 真实 store + mock http），验证：
 * - 未读展示：登录挂载后拉取未读，有未读弹窗展示版本/标题/内容与剩余条数
 * - 我知道了：标记已读后弹窗关闭（弹窗为纯告知，无允许/取消更新语义），
 *   重新挂载不再弹出
 * - 右上角关闭：不调用已读接口、未读数不变，重新挂载仍会提示
 * - 未读数：组件以服务端 unread_count 驱动剩余未读提示
 * - HTTP 200 + error：不得视为成功，不弹窗不崩溃
 * - 重要更新：仅可确认，不允许关闭；确认走 ack 接口
 * - 弹窗内勾选框「每次更新后自动弹出更新日志」：默认勾选，取消立即保存偏好（PUT），
 *   本次弹窗继续可用；保存失败勾选框回弹
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: jest.fn(),
  },
  X_TOKEN: 'test-token',
}));

// 用 require 而非 import：import 会被提升到 mock 变量声明之前
const ReleaseNoteNotification = require('../ReleaseNoteNotification').default;
const store = require('../store').default;

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

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

function mountNotification() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<ReleaseNoteNotification/>, container);
  });
  return container;
}

function findButton(text) {
  // antd 4 对两个汉字按钮自动插入空格，匹配前归一化空白
  return [...document.body.querySelectorAll('button')].find(
    b => b.textContent.replace(/\s+/g, '') === text);
}

function clickButton(text) {
  const btn = findButton(text);
  expect(btn).toBeTruthy();
  act(() => {
    btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

function buildItem(id, overrides = {}) {
  return {
    id,
    version: 'v3.3.4',
    title: '本次更新说明',
    content: '更新内容正文第一行',
    is_published: true,
    is_required: false,
    publish_at: '2026-09-06 10:00:00',
    is_read: false,
    is_acknowledged: false,
    ...overrides,
  };
}

function unreadPayload(items, count, showAfterUpdate) {
  const payload = {
    unread_count: count === undefined ? items.length : count,
    has_required: items.some(x => x.is_required),
    current_version: 'v3.3.4',
    items,
  };
  if (showAfterUpdate !== undefined) payload.show_after_update = showAfterUpdate;
  return payload;
}

describe('ReleaseNoteNotification 组件行为', () => {
  let containers;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(console, 'error').mockImplementation(() => {});
    store.setUnread([], 0);
    store.checked = false;
    store.drawerVisible = false;
    store.versions = [];
    store.detailItems = [];
    store.showAfterUpdate = true;
    containers = [];
  });

  afterEach(() => {
    containers.forEach(c => {
      ReactDOM.unmountComponentAtNode(c);
      c.remove();
    });
    console.error.mockRestore();
  });

  test('未读展示：挂载即拉取未读并弹窗，展示版本/标题/内容与剩余条数', async () => {
    mockHttpGet.mockResolvedValueOnce(unreadPayload([
      buildItem(101),
      buildItem(102, {title: '第二条更新'}),
    ]));

    containers.push(mountNotification());
    await flush();

    expect(mockHttpGet).toHaveBeenCalledWith('/api/system/release-notes/unread/');
    // 以服务端 unread_count 驱动未读数
    expect(store.unreadCount).toBe(2);
    expect(document.body.textContent).toContain('版本更新');
    expect(document.body.textContent).toContain('v3.3.4');
    expect(document.body.textContent).toContain('本次更新说明');
    expect(document.body.textContent).toContain('更新内容正文第一行');
    expect(document.body.textContent).toContain('还有 1 条未读更新');
    // 纯告知弹窗：只有「我知道了」，不存在允许/取消更新语义
    expect(findButton('我知道了')).toBeTruthy();
    expect(findButton('取消更新')).toBeUndefined();
    expect(findButton('允许更新')).toBeUndefined();
  });

  test('我知道了：标记已读、弹窗关闭，重新挂载不再重复弹出', async () => {
    mockHttpGet.mockResolvedValueOnce(unreadPayload([buildItem(101)]))
      .mockResolvedValueOnce(unreadPayload([]))   // 标记已读后重新拉取
      .mockResolvedValueOnce(unreadPayload([]));  // 重新挂载后再拉取
    mockHttpPost.mockResolvedValueOnce({});

    const container = mountNotification();
    containers.push(container);
    await flush();
    expect(document.body.textContent).toContain('本次更新说明');

    clickButton('我知道了');
    await flush();

    expect(mockHttpPost).toHaveBeenCalledWith('/api/system/release-notes/101/read/', {});
    // 纯告知弹窗：确认后直接关闭，不自动打开更新日志抽屉
    expect(store.drawerVisible).toBe(false);
    // 已读后服务端未读清空，弹窗随之消失
    expect(store.unreadCount).toBe(0);
    expect(store.unreadItems).toHaveLength(0);
    expect(document.body.textContent).not.toContain('本次更新说明');

    // 重新挂载（如重新登录/刷新）不再重复弹出同一条
    ReactDOM.unmountComponentAtNode(container);
    await flush();
    const second = mountNotification();
    containers.push(second);
    await flush();
    expect(document.body.textContent).not.toContain('本次更新说明');
    expect(document.body.querySelector('.ant-modal')).toBeNull();
  });

  test('右上角关闭：不标记已读，重新挂载仍会提示', async () => {
    mockHttpGet.mockResolvedValueOnce(unreadPayload([buildItem(101)]))
      .mockResolvedValueOnce(unreadPayload([buildItem(101)])); // 重新挂载再拉取

    const container = mountNotification();
    containers.push(container);
    await flush();

    const closeBtn = document.body.querySelector('.ant-modal-close');
    expect(closeBtn).toBeTruthy();
    act(() => {
      closeBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();

    // 关闭不得调用已读接口，未读状态保持
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(store.unreadCount).toBe(1);
    expect(store.unreadItems).toHaveLength(1);
    expect(store.drawerVisible).toBe(false);

    // 重新挂载（下次登录）仍会提示该未读更新
    ReactDOM.unmountComponentAtNode(container);
    await flush();
    const second = mountNotification();
    containers.push(second);
    await flush();
    expect(document.body.textContent).toContain('本次更新说明');
  });

  test('HTTP 200 + error：不得视为成功，不弹窗不崩溃', async () => {
    mockHttpGet.mockResolvedValueOnce({error: '登录状态异常'});

    containers.push(mountNotification());
    await flush();

    expect(store.checked).toBe(true);
    expect(store.unreadCount).toBe(0);
    expect(document.body.querySelector('.ant-modal')).toBeNull();
    expect(document.body.textContent).not.toContain('本次更新说明');
  });

  test('弹窗开关关闭（show_after_update=false）：有未读也不自动弹窗，未读数照常记录', async () => {
    mockHttpGet.mockResolvedValueOnce(unreadPayload([buildItem(301)], 1, false));

    containers.push(mountNotification());
    await flush();

    // 拉取过未读、角标数量照常，但不弹窗
    expect(mockHttpGet).toHaveBeenCalledWith('/api/system/release-notes/unread/');
    expect(store.unreadCount).toBe(1);
    expect(store.showAfterUpdate).toBe(false);
    expect(document.body.querySelector('.ant-modal')).toBeNull();
    expect(document.body.textContent).not.toContain('本次更新说明');
  });

  test('弹窗开关开启：有未读照常自动弹窗', async () => {
    mockHttpGet.mockResolvedValueOnce(unreadPayload([buildItem(302)], 1, true));

    containers.push(mountNotification());
    await flush();

    expect(store.showAfterUpdate).toBe(true);
    expect(document.body.textContent).toContain('版本更新');
    expect(document.body.textContent).toContain('本次更新说明');
  });

  test('弹窗内勾选框：默认勾选，取消后立即保存偏好，本次弹窗继续可用', async () => {
    mockHttpGet.mockResolvedValueOnce(unreadPayload([buildItem(401)]))
      .mockResolvedValueOnce(unreadPayload([buildItem(401)], 1, false)); // 我知道了后重新拉取（携带已关闭的偏好）
    mockHttpPost.mockResolvedValueOnce({});
    mockHttpPut.mockResolvedValueOnce({show_after_update: false});

    containers.push(mountNotification());
    await flush();

    // 弹窗内默认勾选「每次更新后自动弹出更新日志」
    const checkbox = document.body.querySelector('.ant-modal .ant-checkbox-input');
    expect(checkbox).toBeTruthy();
    expect(checkbox.checked).toBe(true);

    // 取消勾选：立即保存偏好，不关闭弹窗
    act(() => {
      checkbox.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();

    expect(mockHttpPut).toHaveBeenCalledWith('/api/system/release-notes/settings/', {show_after_update: false});
    expect(store.showAfterUpdate).toBe(false);
    expect(document.body.querySelector('.ant-modal .ant-checkbox-input').checked).toBe(false);
    expect(document.body.textContent).toContain('本次更新说明');

    // 本次更新仍可正常确认：标记已读并直接关闭
    clickButton('我知道了');
    await flush();

    expect(mockHttpPost).toHaveBeenCalledWith('/api/system/release-notes/401/read/', {});
    expect(store.drawerVisible).toBe(false);
    expect(document.body.textContent).not.toContain('本次更新说明');
  });

  test('弹窗内勾选框保存失败：勾选框回弹为原状态，不误改偏好', async () => {
    mockHttpGet.mockResolvedValueOnce(unreadPayload([buildItem(402)]));
    mockHttpPut.mockRejectedValueOnce(new Error('network down'));

    containers.push(mountNotification());
    await flush();

    const checkbox = document.body.querySelector('.ant-modal .ant-checkbox-input');
    expect(checkbox.checked).toBe(true);

    act(() => {
      checkbox.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();

    expect(mockHttpPut).toHaveBeenCalled();
    // 保存失败后偏好保持开启，勾选框回弹
    expect(store.showAfterUpdate).toBe(true);
    expect(document.body.querySelector('.ant-modal .ant-checkbox-input').checked).toBe(true);
  });

  test('重要更新：仅可确认不允许关闭，确认调用 ack 接口', async () => {
    mockHttpGet.mockResolvedValueOnce(unreadPayload([
      buildItem(201, {is_required: true, title: '重要变更说明'}),
    ]))
      .mockResolvedValueOnce(unreadPayload([]));  // 确认后重新拉取
    mockHttpPost.mockResolvedValueOnce({});

    containers.push(mountNotification());
    await flush();

    expect(document.body.textContent).toContain('重要变更说明');
    expect(document.body.textContent).toContain('本次更新为重要变更');
    // 不提供取消与关闭出口
    expect(findButton('我知道了')).toBeUndefined();
    expect(document.body.querySelector('.ant-modal-close')).toBeNull();

    clickButton('我已确认，继续');
    await flush();

    expect(mockHttpPost).toHaveBeenCalledWith('/api/system/release-notes/201/ack/', {});
    expect(store.drawerVisible).toBe(false);
    expect(store.unreadCount).toBe(0);
    expect(document.body.textContent).not.toContain('重要变更说明');
  });
});
