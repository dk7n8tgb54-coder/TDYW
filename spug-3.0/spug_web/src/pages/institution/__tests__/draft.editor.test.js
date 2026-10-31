/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * OnlyOfficeEditor 组件交互测试（jsdom + ReactDOM）：
 * - api.js 加载失败呈现错误与重试入口（不静默白屏）。
 * - DocsAPI 已就绪时用 editorConfig 初始化编辑器（占位节点由宿主
 *   命令式创建、包含 document_key；config 含 JWT token）。
 * - 卸载时调用 destroyEditor 并清空宿主（防 React 17 卸载崩）。
 * 顺序约束：脚本失败用例必须最先跑（模块级 apiScriptPromise 单例，
 * 失败后复位；后续用例以 window.DocsAPI 就绪短路，不再拉脚本）。
 * 禁止 jest.resetModules（会二次 require 出两份 React，触发
 * Invalid hook call）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

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

import OnlyOfficeEditor from '../draft/OnlyOfficeEditor';

const EDITOR_CONFIG = {
  editor_available: true,
  editor_api_url: 'http://onlyoffice.test/web-apps/apps/api/documents/api.js',
  document_key: 'oo-5-r1-abcd1234',
  config: {documentType: 'word', document: {key: 'oo-5-r1-abcd1234'}},
  token: 'jwt-token-value',
};

function renderEditor() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  let instanceRef = null;
  act(() => {
    ReactDOM.render(
      React.createElement(OnlyOfficeEditor, {
        editorConfig: EDITOR_CONFIG,
        ref: ref => { instanceRef = ref; },
      }),
      container);
  });
  return container;
}

afterEach(() => {
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
  delete window.DocsAPI;
});

describe('OnlyOfficeEditor 组件', () => {
  it('api.js 加载失败呈现错误 Alert 与重试按钮，并上报 onUnavailable（不静默白屏）', async () => {
    const onUnavailable = jest.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(
        React.createElement(OnlyOfficeEditor, {
          editorConfig: EDITOR_CONFIG, onUnavailable,
        }),
        container);
    });
    // 组件创建了 script 标签，jsdom 不会真正加载：手动触发 onerror
    const script = document.body.querySelector(
      'script[src="http://onlyoffice.test/web-apps/apps/api/documents/api.js"]');
    expect(script).not.toBeNull();
    await act(async () => {
      script.dispatchEvent(new Event('error'));
    });
    expect(container.textContent).toContain('在线编辑器不可用');
    expect(container.textContent).toContain('本机编辑');
    // 工作台据此提供「切换到本机编辑」入口（即使上报不可靠，切换控件
    // 也独立渲染——此处钉死上报链路本身）
    expect(onUnavailable).toHaveBeenCalled();
  });

  it('onDocumentReady 上报 onReady（重试成功后清除失败标记）', async () => {
    let events = null;
    class FakeDocEditor {
      constructor(_placeholderId, config) { events = config.events; }
      destroyEditor() {}
    }
    window.DocsAPI = {DocEditor: FakeDocEditor};
    const onReady = jest.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(
        React.createElement(OnlyOfficeEditor, {
          editorConfig: EDITOR_CONFIG, onReady,
        }),
        container);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(events).not.toBeNull();
    act(() => { events.onDocumentReady(); });
    expect(onReady).toHaveBeenCalledTimes(1);
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
  });
});

describe('OnlyOfficeEditor 组件（初始化与卸载）', () => {
  it('DocsAPI 就绪时初始化编辑器，占位节点含 document_key 且 config 带 token', async () => {
    const created = [];
    class FakeDocEditor {
      constructor(placeholderId, config) {
        created.push({placeholderId, config});
        // 模拟 DS 文档加载完成回调
        if (config.events && config.events.onDocumentReady) {
          config.events.onDocumentReady();
        }
      }
      destroyEditor() {}
    }
    // 真实 DocsAPI 是命名空间对象，构造器挂在 DocsAPI.DocEditor
    window.DocsAPI = {DocEditor: FakeDocEditor};
    const container = renderEditor();
    // initEditor 经微任务调度（loadDocsApi 短路后 .then），需冲刷后再断言
    await act(async () => {
      await Promise.resolve();
    });
    // 占位节点由命令式创建（React 树之外）
    const placeholder = container.querySelector('#oo-editor-oo-5-r1-abcd1234');
    expect(placeholder).not.toBeNull();
    expect(created).toHaveLength(1);
    expect(created[0].placeholderId).toBe('oo-editor-oo-5-r1-abcd1234');
    expect(created[0].config.token).toBe('jwt-token-value');
    expect(created[0].config.documentType).toBe('word');
    // 就绪后不显示 Spin
    expect(container.textContent).not.toContain('正在加载');
  });

  it('卸载时调用 destroyEditor 并清空宿主节点', async () => {
    const destroyed = [];
    class FakeDocEditor {
      constructor() {}
      destroyEditor() { destroyed.push(true); }
    }
    window.DocsAPI = {DocEditor: FakeDocEditor};
    const container = renderEditor();
    await act(async () => {
      await Promise.resolve();
    });
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    expect(destroyed).toHaveLength(1);
  });

  it('onDocumentStateChange 上报编辑器修改状态（data 布尔化后透传）', async () => {
    let events = null;
    class FakeDocEditor {
      constructor(_placeholderId, config) { events = config.events; }
      destroyEditor() {}
    }
    window.DocsAPI = {DocEditor: FakeDocEditor};
    const onDirtyChange = jest.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(
        React.createElement(OnlyOfficeEditor, {
          editorConfig: EDITOR_CONFIG,
          onDirtyChange,
        }),
        container);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(events).not.toBeNull();
    expect(typeof events.onDocumentStateChange).toBe('function');
    // 有未保存修改：上报 true
    act(() => { events.onDocumentStateChange({data: true}); });
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
    // DS 自身"所有更改已保存"（data=false）：组件原样上报 false，
    // 是否清除由 store 侧闩锁决定（不得据此显示业务已保存）
    act(() => { events.onDocumentStateChange({data: false}); });
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
    // 无 data（异常事件）按未修改处理
    act(() => { events.onDocumentStateChange({}); });
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
  });
});
