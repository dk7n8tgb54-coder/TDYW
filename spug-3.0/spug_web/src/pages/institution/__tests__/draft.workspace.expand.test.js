/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台「放大/还原」组件交互测试（jsdom + ReactDOM，2026-10-30）：
 * - 默认视图：常规布局（非浮层）、编辑器 72vh、放大按钮带图标与 Tooltip。
 * - 放大：fixed 浮层（zIndex 900）承载，文件清单/元数据/次级操作/说明
 *   收起，精简顶栏保留 返回/文件名/保存状态/保存并结束编辑；编辑器高度
 *   切到 100%。切换前后 OnlyOfficeEditor 实例不重建（挂载计数不变、
 *   DOM 节点同一），不重新请求 editor-config（不轮换 document key）。
 * - 还原：回到常规布局（72vh），实例仍不重建。
 * - Esc：放大态按 Esc 还原；还原后监听移除（再次 Esc 无副作用）；非 Esc
 *   按键不退出放大。
 * - 退出时机：切换文件/保存并结束编辑成功/返回详情 均退出放大；保存确认
 *   失败保留放大与编辑器并呈现 重试保存/不保存并退出（保护流程不中断）；
 *   「不保存并退出」确认后撤销会话并退出放大。
 * mock 约定与 draft.workspace.test.js 相同；OnlyOfficeEditor 用带挂载
 * 计数的替身（height prop 透传到 data-height 供断言）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import { message } from 'antd';

window.matchMedia = window.matchMedia || function () {
  return {matches: false, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}};
};

jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  history: {push: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: false, permissions: []},
}));

// var（而非 let）：jest.mock 工厂被提升到模块顶部，let 会进入 TDZ
var mockEditorMounts;
var mockEditorUnmounts;
var mockEditorHostNode;

jest.mock('../draft/OnlyOfficeEditor', () => {
  const React = require('react');
  return function OnlyOfficeEditor(props) {
    const hostRef = React.useRef(null);
    React.useEffect(() => {
      mockEditorMounts += 1;
      mockEditorHostNode = hostRef.current;
      return () => { mockEditorUnmounts += 1; };
    }, []);
    return React.createElement('div', {
      className: 'oo-editor-mock',
      ref: hostRef,
      'data-height': props.height || '72vh',
    }, 'oo-editor');
  };
});

jest.mock('../detail/PreviewModal', () => function PreviewModal() {
  return null;
});
jest.mock('../../../layout/useWorkTabUnsaved', () => () => {});

import InstitutionDraftWorkspace from '../draft';
import { http, history } from 'libs';
import store from '../draft/store';

function makeFile(id, overrides) {
  return Object.assign({
    id,
    manual_id: 5,
    name: `文件${id}`,
    sort_order: id,
    is_removed: false,
    created_at: '2026-10-01T10:00:00',
    originals_count: 1,
    draft: {
      id: 100 + id,
      revision: id,
      file_name: `文件${id}.docx`,
      file_size: 1024,
      file_hash: `hash-${id}`,
      base_version_id: null,
      source_original_id: null,
      last_saved_by_name: '张三',
      last_saved_at: '2026-10-01T10:00:00',
      created_at: '2026-10-01T10:00:00',
    },
    active_session: null,
  }, overrides);
}

function mockFetch(files) {
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({
        editor_available: true, editor_api_url: 'http://oo/api.js',
        document_key: 'k1', config: {}, token: 't',
      });
    }
    if (url.includes('/files/')) return Promise.resolve(files);
    return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit']});
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

let pageInstance = null;
let pageContainer = null;

function renderPage() {
  pageContainer = document.createElement('div');
  document.body.appendChild(pageContainer);
  act(() => {
    pageInstance = ReactDOM.render(
      React.createElement(InstitutionDraftWorkspace, {match: {params: {id: '5'}}}),
      pageContainer);
  });
  return pageContainer;
}

const norm = s => (s || '').replace(/\s+/g, '');

/** 按钮查找归一化空白（antd 两字中文按钮插空格："放大"→"放 大"） */
function findButton(container, text) {
  return Array.from(container.querySelectorAll('button'))
    .find(b => norm(b.textContent).includes(norm(text)));
}

/** 可见按钮查找：跳过处于 display:none 祖先下的按钮（如收起的文件头部） */
function findVisibleButton(container, text) {
  return Array.from(container.querySelectorAll('button'))
    .find(b => norm(b.textContent).includes(norm(text)) && !isHidden(b));
}

function isHidden(el) {
  let node = el;
  while (node && node !== document.body) {
    if (node.style && node.style.display === 'none') return true;
    node = node.parentElement;
  }
  return false;
}

/** 包含 text 的最小元素（孩子都不完整包含全文），用于定位实际渲染位置 */
function minimalTextEls(container, text) {
  const all = Array.from(container.querySelectorAll('*'))
    .filter(el => el.textContent.includes(text));
  return all.filter(el => Array.from(el.children)
    .every(ch => !ch.textContent.includes(text)));
}

/** 文本至少有一处落在可见（无 display:none 祖先）的最小元素内 */
function textVisible(container, text) {
  const els = minimalTextEls(container, text);
  if (!els.length) return false;
  return els.some(el => !isHidden(el));
}

function click(el) {
  el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
}

function pressKey(key) {
  act(() => {
    window.dispatchEvent(new KeyboardEvent('keydown', {key}));
  });
}

const configCalls = () => http.get.mock.calls.filter(
  ([url]) => url.includes('editor-config')).length;

/** 建立在线编辑（文件 1 持会话、配置可用）的工作区 */
async function setupOnlineEditing(fileIds, sessionFileId = 1) {
  sessionStorage.setItem(
    `institution_edit_session_5_${sessionFileId}`,
    JSON.stringify({sessionKey: 'sess-1', expiresAt: '2099-01-01T00:00:00'}));
  store.confirmSettleMs = 0;
  mockFetch(fileIds.map(id => makeFile(id)));
  const container = renderPage();
  await flush();
  await flush();
  return container;
}

function expandEditor(container) {
  const btn = findButton(container, '放大');
  expect(btn).not.toBeUndefined();
  act(() => { click(btn); });
}

let errorSpy, successSpy, warningSpy;

beforeEach(() => {
  jest.clearAllMocks();
  // 本套件在 afterEach 真实卸载组件：componentWillUnmount 会对持有会话的
  // 文件发起 quiet forcesave 兜底，给 http 默认 resolved 实现避免卸载报错
  http.get.mockResolvedValue({});
  http.post.mockResolvedValue({});
  http.delete.mockResolvedValue({});
  store.reset();
  pageInstance = null;
  pageContainer = null;
  mockEditorMounts = 0;
  mockEditorUnmounts = 0;
  mockEditorHostNode = null;
  sessionStorage.clear();
  errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  warningSpy = jest.spyOn(message, 'warning').mockImplementation(() => {});
});

afterEach(() => {
  if (pageContainer) {
    act(() => { ReactDOM.unmountComponentAtNode(pageContainer); });
    pageContainer = null;
  }
  errorSpy.mockRestore();
  successSpy.mockRestore();
  warningSpy.mockRestore();
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
});

describe('草稿工作台（放大/还原）', () => {
  it('默认视图：常规布局（非浮层）、编辑器 72vh、放大按钮带图标与 Tooltip', async () => {
    const container = await setupOnlineEditing([1]);
    const root = pageContainer.firstChild;
    expect(root.style.position).not.toBe('fixed');
    const editor = container.querySelector('.oo-editor-mock');
    expect(editor.getAttribute('data-height')).toBe('72vh');
    const btn = findButton(container, '放大');
    expect(btn).not.toBeUndefined();
    // 带图标（zoom-in）且包在 Tooltip 下（hover 出现提示文案）
    expect(btn.querySelector('.anticon-zoom-in')).not.toBeNull();
    act(() => {
      btn.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
    });
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 300));
    });
    const tip = document.querySelector('.ant-tooltip');
    expect(tip).not.toBeNull();
    expect(tip.textContent).toContain('放大编辑区');
    expect(mockEditorMounts).toBe(1);
  });

  it('放大：fixed 浮层 + 编辑器 100% + 清单/元数据/次级操作收起 + 精简顶栏；实例不重建、不重拉配置', async () => {
    const container = await setupOnlineEditing([1, 2]);
    const callsBefore = configCalls();
    expect(callsBefore).toBe(1);
    const hostBefore = container.querySelector('.oo-editor-mock');
    expandEditor(container);
    const root = pageContainer.firstChild;
    // 浮层：fixed + zIndex 900（低于 antd Modal 1000，确认弹窗不被遮挡）
    expect(root.style.position).toBe('fixed');
    expect(root.style.zIndex).toBe('900');
    // 编辑器容器切到 100%，DOM 节点同一（实例不重建）
    const editor = container.querySelector('.oo-editor-mock');
    expect(editor.getAttribute('data-height')).toBe('100%');
    expect(editor).toBe(hostBefore);
    expect(mockEditorMounts).toBe(1);
    expect(mockEditorUnmounts).toBe(0);
    expect(mockEditorHostNode).toBe(hostBefore);
    // 不重新获取 editor-config（不轮换 document key）
    expect(configCalls()).toBe(callsBefore);
    // 收起：文件清单 / 文件头部 / 元数据 / 次级操作行 / 编辑器下方说明
    expect(container.textContent).toContain('待发布文件（共 2 份）');
    expect(textVisible(container, '待发布文件（共 2 份）')).toBe(false);
    expect(textVisible(container, '当前文件：文件1')).toBe(false);
    expect(textVisible(container, '工作文件')).toBe(false);
    expect(textVisible(container, '文件管理：')).toBe(false);
    expect(textVisible(container, '以上方保存状态为准')).toBe(false);
    // 精简顶栏保留：返回 / 文件名 / 保存状态 / 保存并结束编辑 可见
    // （在线编辑无确认记录：独立保存状态显示"尚未确认落盘"警示）
    expect(textVisible(container, '文件1')).toBe(true);
    expect(textVisible(container, '编辑中：内容尚未经服务端确认落盘')).toBe(true);
    expect(findVisibleButton(container, '返回 测试手册')).not.toBeUndefined();
    expect(findVisibleButton(container, '保存并结束编辑')).not.toBeUndefined();
    expect(findVisibleButton(container, '还原')).not.toBeUndefined();
  });

  it('还原：常规布局恢复（72vh、清单可见），实例不重建', async () => {
    const container = await setupOnlineEditing([1, 2]);
    expandEditor(container);
    const restoreBtn = findVisibleButton(container, '还原');
    expect(restoreBtn.querySelector('.anticon-zoom-out')).not.toBeNull();
    act(() => { click(restoreBtn); });
    const root = pageContainer.firstChild;
    expect(root.style.position).not.toBe('fixed');
    expect(container.querySelector('.oo-editor-mock').getAttribute('data-height'))
      .toBe('72vh');
    expect(mockEditorMounts).toBe(1);
    expect(mockEditorUnmounts).toBe(0);
    expect(textVisible(container, '待发布文件（共 2 份）')).toBe(true);
    expect(textVisible(container, '当前文件：文件1')).toBe(true);
    expect(textVisible(container, '文件管理：')).toBe(true);
    expect(configCalls()).toBe(1);
  });

  it('Esc 还原；还原后监听移除，再次 Esc 无副作用', async () => {
    const container = await setupOnlineEditing([1]);
    expandEditor(container);
    expect(pageContainer.firstChild.style.position).toBe('fixed');
    pressKey('Escape');
    expect(pageContainer.firstChild.style.position).not.toBe('fixed');
    expect(container.querySelector('.oo-editor-mock').getAttribute('data-height'))
      .toBe('72vh');
    expect(mockEditorMounts).toBe(1);
    // 再次 Esc：监听已随退出摘除，无副作用
    pressKey('Escape');
    expect(pageContainer.firstChild.style.position).not.toBe('fixed');
  });

  it('非 Esc 按键不退出放大', async () => {
    const container = await setupOnlineEditing([1]);
    expandEditor(container);
    pressKey('a');
    expect(pageContainer.firstChild.style.position).toBe('fixed');
    pressKey('Escape');
    expect(pageContainer.firstChild.style.position).not.toBe('fixed');
  });

  it('编辑器不可用（会话退出）时放大自动失效，不残留全屏浮层', async () => {
    const container = await setupOnlineEditing([1]);
    expandEditor(container);
    expect(pageContainer.firstChild.style.position).toBe('fixed');
    // 模拟会话被清除（如保存失败清理）：编辑器分支离开在线态
    act(() => {
      store.clearSession(1);
    });
    await flush();
    expect(pageContainer.firstChild.style.position).not.toBe('fixed');
    expect(pageInstance.state.expanded).toBe(false);
  });
});

describe('草稿工作台（放大态的退出时机与保存保护）', () => {
  it('放大态「保存并结束编辑」成功：确认落盘后撤销会话并退出放大', async () => {
    const container = await setupOnlineEditing([1]);
    http.post.mockResolvedValue({forcesave: 'no_changes', revision: 1});
    http.delete.mockResolvedValue({});
    expandEditor(container);
    const btn = findVisibleButton(container, '保存并结束编辑');
    await act(async () => {
      click(btn);
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    await flush();
    expect(store.sessionKeyOf(1)).toBe('');
    expect(pageInstance.state.expanded).toBe(false);
    expect(pageContainer.firstChild.style.position).not.toBe('fixed');
    expect(successSpy).toHaveBeenCalledWith('已保存并结束编辑');
    // 会话已撤销：编辑器卸载，工作区回到未开会话提示
    expect(container.querySelector('.oo-editor-mock')).toBeNull();
  });

  it('放大态切换文件：确认落盘后切换并退出放大（会话按文件保留）', async () => {
    const container = await setupOnlineEditing([1, 2]);
    http.post.mockResolvedValue({forcesave: 'no_changes', revision: 1});
    expandEditor(container);
    const rows = Array.from(container.querySelectorAll('div'))
      .filter(el => el.style && el.style.cursor === 'pointer');
    expect(rows).toHaveLength(2);
    await act(async () => {
      click(rows[1]);
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    await flush();
    expect(store.selectedFileId).toBe(2);
    expect(pageInstance.state.expanded).toBe(false);
    expect(pageContainer.firstChild.style.position).not.toBe('fixed');
    // 切换保护：确认落盘但不撤销会话
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(http.delete).not.toHaveBeenCalled();
  });

  it('放大态返回详情：确认落盘后跳转并退出放大', async () => {
    const container = await setupOnlineEditing([1]);
    http.post.mockResolvedValue({forcesave: 'no_changes', revision: 1});
    expandEditor(container);
    const backBtn = findVisibleButton(container, '返回 测试手册');
    expect(backBtn).not.toBeUndefined();
    await act(async () => {
      click(backBtn);
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    await flush();
    expect(history.push).toHaveBeenCalledWith('/institution/manuals/5');
    expect(pageInstance.state.expanded).toBe(false);
    expect(store.sessionKeyOf(1)).toBe('sess-1');
  });
});

describe('草稿工作台（放大态的保存确认失败与危险出口）', () => {
  it('放大态保存确认失败：保留放大与编辑器，呈现重试保存/不保存并退出', async () => {
    const container = await setupOnlineEditing([1]);
    store.pollIntervalMs = 1;
    store.pollMaxAttempts = 2;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 1});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true, document_key: 'k1'});
      }
      if (url.endsWith('/draft/')) {
        return Promise.resolve({revision: 1}); // 修订号始终未推进（未落盘）
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    expandEditor(container);
    await act(async () => {
      click(findVisibleButton(container, '保存并结束编辑'));
      await new Promise(resolve => setTimeout(resolve, 30));
    });
    await flush();
    // 确认未完成：会话与编辑器保留，放大态保留（浮层仍在）
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(http.delete).not.toHaveBeenCalled();
    expect(pageInstance.state.expanded).toBe(true);
    expect(pageContainer.firstChild.style.position).toBe('fixed');
    expect(mockEditorUnmounts).toBe(0);
    // 精简顶栏呈现可重试状态（文件头部已收起，重试入口在顶栏）
    expect(textVisible(container, '保存未确认')).toBe(true);
    expect(findVisibleButton(container, '重试保存')).not.toBeUndefined();
    expect(findVisibleButton(container, '不保存并退出')).not.toBeUndefined();
  });

  it('放大态「不保存并退出」：确认后撤销会话并退出放大', async () => {
    const container = await setupOnlineEditing([1]);
    store.pollIntervalMs = 1;
    store.pollMaxAttempts = 2;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 1});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true, document_key: 'k1'});
      }
      if (url.endsWith('/draft/')) return Promise.resolve({revision: 1});
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    http.delete.mockResolvedValue({});
    expandEditor(container);
    await act(async () => {
      click(findVisibleButton(container, '保存并结束编辑'));
      await new Promise(resolve => setTimeout(resolve, 30));
    });
    await flush();
    expect(pageInstance.state.expanded).toBe(true);
    const discardBtn = findVisibleButton(container, '不保存并退出');
    await act(async () => {
      click(discardBtn);
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    // 危险出口确认弹窗（portal 到 body）
    const confirmBtn = Array.from(
      document.querySelectorAll('.ant-modal-confirm button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '不保存并退出');
    expect(confirmBtn).not.toBeUndefined();
    await act(async () => {
      confirmBtn.click();
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    await flush();
    expect(store.sessionKeyOf(1)).toBe('');
    expect(pageInstance.state.expanded).toBe(false);
    expect(pageContainer.firstChild.style.position).not.toBe('fixed');
    expect(successSpy).toHaveBeenCalledWith('已退出编辑会话');
  });
});
