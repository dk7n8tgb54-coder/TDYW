/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台离开保护与独立保存状态组件行为测试（jsdom + ReactDOM）：
 * - 切换文件/返回详情（工作台内可拦截的离开）先经服务端确认落盘
 *   （store.confirmFileSave：确认成功但不撤销会话），成功才真正切换/
 *   跳转；确认失败留在当前文件并呈现被取消语境与重试入口，绝不静默
 *   forcesave 后销毁编辑器。
 * - 确认进行中（finishingFileId）禁用冲突导航与重复提交。
 * - 独立"制度草稿保存状态"：服务端确认落盘后才显示"已保存到制度草稿：
 *   rN、时间"；在线编辑有未确认修改显示警示；编辑器自身的"所有更改
 *   已保存"不冒充业务保存成功。
 * mock 约定与 draft.workspace.test.js 相同（见该文件头注释）。
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

jest.mock('../draft/OnlyOfficeEditor', () => function OnlyOfficeEditor() {
  return null;
});
jest.mock('../detail/PreviewModal', () => function PreviewModal() {
  return null;
});
jest.mock('../../../layout/useWorkTabUnsaved', () => () => {});

import InstitutionDraftWorkspace from '../draft';
import {http} from 'libs';
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

function mockFetch(files, manual) {
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({editor_available: false});
    }
    if (url.includes('/files/')) return Promise.resolve(files);
    return Promise.resolve(manual || {id: 5, name: '测试手册', my_roles: ['edit']});
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

let pageInstance = null;

function renderPage() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    pageInstance = ReactDOM.render(
      React.createElement(InstitutionDraftWorkspace, {match: {params: {id: '5'}}}),
      container);
  });
  return container;
}

function findListRows(container) {
  return Array.from(container.querySelectorAll('div'))
    .filter(el => el.style && el.style.cursor === 'pointer');
}

function findButton(container, text) {
  return Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.includes(text));
}

function click(el) {
  el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
}

/** 在线编辑中（会话 + 在线配置）的页面状态；轮询参数调小加速 */
function setupOnlineEditing(fileIds) {
  mockFetch(fileIds.map(id => makeFile(id)));
  const container = renderPage();
  return flush().then(() => {
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: true, document_key: 'k1'};
    store.pollIntervalMs = 1;
    return flush().then(() => container);
  });
}

let errorSpy, successSpy, warningSpy;

beforeEach(() => {
  jest.clearAllMocks();
  store.reset();
  pageInstance = null;
  sessionStorage.clear();
  errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  warningSpy = jest.spyOn(message, 'warning').mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
  successSpy.mockRestore();
  warningSpy.mockRestore();
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
});

describe('草稿工作台（切换文件保护：确认落盘后才切换）', () => {
  it('切换文件先经服务端确认落盘：成功才切换，会话保留可切回', async () => {
    const container = await setupOnlineEditing([1, 2]);
    const fsCalls = () => http.post.mock.calls.filter(
      ([url]) => url.includes('forcesave'));
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        // 第一次受理；修订号推进后的复核轮 DS 报告无更多待存修改
        return fsCalls().length === 1
          ? Promise.resolve({forcesave: 'requested', revision: 1})
          : Promise.resolve({forcesave: 'no_changes', revision: 2});
      }
      return Promise.resolve({});
    });
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true});
      }
      if (url.endsWith('/draft/')) {
        return Promise.resolve({revision: 2,
          last_saved_at: '2026-10-30T10:00:00', last_saved_by_name: '张三'});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1), makeFile(2)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const rows = findListRows(container);
    await act(async () => {
      click(rows[1]);
      await new Promise(resolve => setTimeout(resolve, 20));
    });
    await flush();
    // 确认链路真实走完（forcesave 受理 + 复核），不是静默 fire-and-forget
    expect(fsCalls().length).toBeGreaterThanOrEqual(2);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/forcesave/',
      {session_key: 'sess-1'});
    // 服务端确认后才切换；会话按文件保留（不撤销），可随时切回
    expect(store.selectedFileId).toBe(2);
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(http.delete).not.toHaveBeenCalled();
    expect(successSpy).toHaveBeenCalledWith('当前文件「文件1」已保存到制度草稿');
  });

  it('降级路径切换文件不触发 forcesave（无在线编辑器）', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: false};
    await flush();
    const rows = findListRows(container);
    await act(async () => {
      click(rows[1]);
      await Promise.resolve();
    });
    await flush();
    expect(http.post).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(1)).toBe('sess-1');
  });
});

describe('草稿工作台（切换文件保护：失败与冲突导航）', () => {
  it('确认失败（超时）留在当前文件并呈现重试入口，不静默切换', async () => {
    const container = await setupOnlineEditing([1, 2]);
    store.pollMaxAttempts = 2;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 1});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true});
      }
      if (url.endsWith('/draft/')) {
        return Promise.resolve({revision: 1}); // 修订号始终未推进（未落盘）
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1), makeFile(2)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const rows = findListRows(container);
    await act(async () => {
      click(rows[1]);
      await new Promise(resolve => setTimeout(resolve, 30));
    });
    await flush();
    // 未确认落盘绝不切换，也不撤销会话
    expect(store.selectedFileId).toBe(1);
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(http.delete).not.toHaveBeenCalled();
    // 界面呈现被取消语境与重试入口
    expect(container.textContent).toContain('保存未确认');
    expect(container.textContent).toContain('已取消切换文件');
    expect(findButton(container, '重试保存')).not.toBeUndefined();
    expect(findButton(container, '不保存并退出')).not.toBeUndefined();
  });

  it('确认进行中禁用重复切换（冲突导航防护）', async () => {
    const container = await setupOnlineEditing([1, 2]);
    let releasePoll;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 1});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true});
      }
      if (url.endsWith('/draft/')) {
        return new Promise(resolve => { releasePoll = resolve; }); // 挂起的轮询
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1), makeFile(2)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const rows = findListRows(container);
    await act(async () => {
      click(rows[1]);
      await flush(); // 确认开始：finishingFileId 已置位
    });
    expect(store.finishingFileId).toBe(1);
    await act(async () => {
      click(rows[1]);
      await Promise.resolve();
    });
    expect(warningSpy).toHaveBeenCalledWith('正在保存当前文件，请稍候再切换');
    expect(store.selectedFileId).toBe(1);
    if (releasePoll) releasePoll({revision: 2});
  });
});

describe('草稿工作台（返回详情保护：确认落盘后才跳转）', () => {
  it('返回详情先经服务端确认落盘：成功才 history.push', async () => {
    const container = await setupOnlineEditing([1]);
    const {history} = require('libs');
    const fsCalls = () => http.post.mock.calls.filter(
      ([url]) => url.includes('forcesave'));
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        return fsCalls().length === 1
          ? Promise.resolve({forcesave: 'requested', revision: 1})
          : Promise.resolve({forcesave: 'no_changes', revision: 2});
      }
      return Promise.resolve({});
    });
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true});
      }
      if (url.endsWith('/draft/')) {
        return Promise.resolve({revision: 2,
          last_saved_at: '2026-10-30T10:00:00', last_saved_by_name: '张三'});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const backBtn = findButton(container, '返回 测试手册');
    expect(backBtn).not.toBeUndefined();
    await act(async () => {
      click(backBtn);
      await new Promise(resolve => setTimeout(resolve, 20));
    });
    await flush();
    // 确认链路完成后才跳转；会话保留（返回详情不撤销会话）
    expect(fsCalls().length).toBeGreaterThanOrEqual(2);
    expect(history.push).toHaveBeenCalledWith('/institution/manuals/5');
    expect(store.sessionKeyOf(1)).toBe('sess-1');
  });

  it('确认失败：不跳转并呈现被取消语境', async () => {
    const container = await setupOnlineEditing([1]);
    const {history} = require('libs');
    store.pollMaxAttempts = 2;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 1});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true});
      }
      if (url.endsWith('/draft/')) return Promise.resolve({revision: 1});
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const backBtn = findButton(container, '返回 测试手册');
    await act(async () => {
      click(backBtn);
      await new Promise(resolve => setTimeout(resolve, 30));
    });
    await flush();
    expect(history.push).not.toHaveBeenCalled();
    expect(container.textContent).toContain('已取消返回详情');
    expect(store.sessionKeyOf(1)).toBe('sess-1');
  });
});

describe('草稿工作台（独立保存状态显示）', () => {
  it('在线编辑且有未确认修改：显示警示，绝不显示"已保存到制度草稿"', async () => {
    const container = await setupOnlineEditing([1]);
    await act(async () => {
      store.setEditorDirty(1, true);
    });
    await flush();
    expect(container.textContent).toContain('有未确认落盘的修改');
    expect(container.textContent).not.toContain('已保存到制度草稿');
  });

  it('在线编辑确认成功后：显示"已保存到制度草稿：rN、时间"', async () => {
    const container = await setupOnlineEditing([1]);
    await act(async () => {
      store.setEditorDirty(1, true);
      store.markSaveConfirmed(1, {revision: 3,
        last_saved_at: '2026-10-30T10:00:00', last_saved_by_name: '张三'});
    });
    await flush();
    expect(container.textContent).toContain('已保存到制度草稿：r3');
    expect(container.textContent).toContain('2026-10-30 10:00:00');
  });

  it('在线编辑无确认记录：显示"内容尚未经服务端确认落盘"', async () => {
    const container = await setupOnlineEditing([1]);
    await flush();
    expect(container.textContent).toContain('内容尚未经服务端确认落盘');
    expect(container.textContent).not.toContain('已保存到制度草稿');
  });

  it('确认进行中：状态条显示正在请求服务端保存', async () => {
    const container = await setupOnlineEditing([1]);
    await act(async () => {
      store.finishingFileId = 1;
    });
    await flush();
    expect(container.textContent).toContain('正在请求服务端保存当前文件');
    store.finishingFileId = null;
  });
});
