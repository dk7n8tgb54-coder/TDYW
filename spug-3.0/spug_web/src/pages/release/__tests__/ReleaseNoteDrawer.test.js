/**
 * 更新日志抽屉「每次更新后自动弹出更新日志」开关行为测试
 *
 * 真实渲染组件（react-dom + act + 真实 store + mock http），验证：
 * - 开关回显 store.showAfterUpdate 当前偏好
 * - 切换开关调用设置接口（PUT），成功后才更新本地偏好
 * - 保存失败（网络/HTTP 200 + error）开关保持原状态
 * - 关闭自动弹窗后用户仍可正常打开抽屉查看更新日志（重新开启的入口）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(),
    put: mockHttpPut,
    delete: jest.fn(),
  },
  X_TOKEN: 'test-token',
}));

// 用 require 而非 import：import 会被提升到 mock 变量声明之前
const ReleaseNoteDrawer = require('../ReleaseNoteDrawer').default;
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
    dispatchEvent() {
      return false;
    },
  });
}

const SETTINGS_API = '/api/system/release-notes/settings/';

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

function mountDrawer() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  store.drawerVisible = true;
  act(() => {
    ReactDOM.render(<ReleaseNoteDrawer/>, container);
  });
  return container;
}

function findSwitch() {
  return document.body.querySelector('.ant-switch');
}

function toggleSwitch() {
  const sw = findSwitch();
  expect(sw).toBeTruthy();
  act(() => {
    sw.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

describe('ReleaseNoteDrawer 弹窗偏好开关', () => {
  let containers;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(console, 'error').mockImplementation(() => {});
    store.drawerVisible = false;
    store.showAfterUpdate = true;
    store.versions = [];
    store.detailItems = [];
    store.selectedVersion = '';
    containers = [];
  });

  afterEach(() => {
    containers.forEach(c => {
      ReactDOM.unmountComponentAtNode(c);
      c.remove();
    });
    store.drawerVisible = false;
    console.error.mockRestore();
  });

  test('开关回显当前偏好，抽屉正常展示版本内容', async () => {
    store.versions = [{version: 'v3.3.4', count: 2, publish_at: '2026-09-06 10:00:00'}];
    containers.push(mountDrawer());
    await flush();

    expect(findSwitch().className).toContain('ant-switch-checked');
    expect(document.body.textContent).toContain('每次更新后自动弹出更新日志');
    expect(document.body.textContent).toContain('v3.3.4');
  });

  test('关闭开关：调用设置接口保存，成功后取消选中态', async () => {
    mockHttpPut.mockResolvedValueOnce({show_after_update: false});
    containers.push(mountDrawer());
    await flush();

    toggleSwitch();
    await flush();

    expect(mockHttpPut).toHaveBeenCalledWith(SETTINGS_API, {show_after_update: false});
    expect(store.showAfterUpdate).toBe(false);
    expect(findSwitch().className).not.toContain('ant-switch-checked');
  });

  test('保存失败：开关保持原状态（可重新勾选），偏好不误改', async () => {
    store.showAfterUpdate = false;
    mockHttpPut.mockRejectedValueOnce(new Error('network down'));
    containers.push(mountDrawer());
    await flush();

    expect(findSwitch().className).not.toContain('ant-switch-checked');

    toggleSwitch();
    await flush();

    expect(mockHttpPut).toHaveBeenCalledWith(SETTINGS_API, {show_after_update: true});
    // 失败后偏好保持关闭、开关不选中，用户可再次尝试开启
    expect(store.showAfterUpdate).toBe(false);
    expect(findSwitch().className).not.toContain('ant-switch-checked');
  });
});
