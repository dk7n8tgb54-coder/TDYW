/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿恢复行为测试（jsdom + ReactDOM，2026-10-29 草稿恢复优先级规则）：
 * - 无草稿文件不渲染空白编辑器，按服务端 draft_recovery 提示渲染恢复入口。
 * - 有当前生效版本：显示「从当前生效版本恢复草稿」，空体 POST draft/create
 *   （恢复优先级由后端权威决定，前端不得静默调用最近原稿）。
 * - 无任何发布版本：才显示「从初始原稿创建草稿」。
 * - requires_confirm（当前版本不含该文件/已废止）：只能走高级恢复，
 *   明确确认后按指定原稿重建（confirm=true + 已验证密码）。
 * - 已有草稿：不出现恢复入口，也不自动发起任何 draft/create。
 * - 恢复失败：不显示成功提示（错误由拦截器提示一次）。
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
    draft: null,
    active_session: null,
  }, overrides);
}

function mockFetch(files, manual) {
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({editor_available: false});
    }
    if (url.includes('/originals/')) {
      return Promise.resolve([
        {id: 77, file_name: '原始上传.docx', ext: '.docx', file_size: 1024,
          uploaded_by_name: '张三', uploaded_at: '2026-10-01T10:00:00'}]);
    }
    if (url.includes('/files/')) return Promise.resolve(files);
    return Promise.resolve(manual || {
      id: 5, name: '测试手册', my_roles: ['edit'],
      has_versions: true, has_password: true});
  });
}

/** 恢复成功后 refreshFiles 返回带草稿的清单（模拟后端已就绪） */
function mockFilesAfterRecovery(fileId, draft) {
  http.get.mockImplementation(url => {
    if (url.includes('/files/')) {
      return Promise.resolve([makeFile(fileId, {draft})]);
    }
    return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit']});
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function renderPage() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(
      React.createElement(InstitutionDraftWorkspace, {match: {params: {id: '5'}}}),
      container);
  });
  return container;
}

async function enterWorkspace() {
  const container = renderPage();
  await flush();
  store.passwordVerified = true;
  await flush();
  return container;
}

function findButton(container, text) {
  return Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.includes(text));
}

function click(el) {
  el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
}

function draftOf(revision, baseVersionNo) {
  return {id: 900 + revision, revision, file_name: '文件1.docx',
    file_size: 1024, file_hash: 'h1',
    base_version_id: baseVersionNo != null ? 9 : null,
    base_version_no: baseVersionNo, source_original_id: null,
    last_saved_by_name: '张三', last_saved_at: '2026-10-01T10:00:00'};
}

let errorSpy, successSpy;

beforeEach(() => {
  jest.clearAllMocks();
  store.reset();
  sessionStorage.clear();
  errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
  successSpy.mockRestore();
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
});

describe('草稿工作台（从当前生效版本恢复）', () => {
  it('有当前生效版本：显示恢复入口并带版本号，不渲染空白编辑器', async () => {
    mockFetch([makeFile(1, {draft_recovery: {
      source: 'current_version', version_id: 9, version_no: 3}})]);
    const container = await enterWorkspace();
    expect(container.textContent).toContain('当前文件：文件1');
    expect(container.textContent).toContain('当前生效版本为 v3');
    expect(container.textContent).not.toContain('在线编辑服务未配置');
    expect(findButton(container, '从当前生效版本恢复草稿')).not.toBeUndefined();
  });

  it('恢复成功后空体请求 + 提示新修订号与来源版本', async () => {
    mockFetch([makeFile(1, {draft_recovery: {
      source: 'current_version', version_id: 9, version_no: 3}})]);
    const container = await enterWorkspace();
    http.post.mockResolvedValue(
      {revision: 2, base_version_id: 9, base_version_no: 3});
    mockFilesAfterRecovery(1, draftOf(2, 3));
    await act(async () => {
      click(findButton(container, '从当前生效版本恢复草稿'));
      await Promise.resolve();
    });
    await flush();
    // 空体请求：恢复来源由后端按优先级决定
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/create/', {});
    expect(successSpy).toHaveBeenCalledWith(expect.stringContaining('草稿已恢复'));
    expect(successSpy).toHaveBeenCalledWith(expect.stringContaining('r2'));
    expect(successSpy).toHaveBeenCalledWith(expect.stringContaining('v3'));
  });
});

describe('草稿工作台（从初始原稿创建与高级恢复）', () => {
  it('无任何发布版本：显示「从初始原稿创建草稿」并提示初始来源', async () => {
    mockFetch([makeFile(1, {draft_recovery: {source: 'original'}})],
      {id: 5, name: '测试手册', my_roles: ['edit'],
        has_versions: false, has_password: false});
    const container = await enterWorkspace();
    expect(container.textContent).toContain('从初始原稿创建草稿');
    expect(container.textContent).not.toContain('从当前生效版本恢复草稿');
    http.post.mockResolvedValue({revision: 1, base_version_id: null});
    mockFilesAfterRecovery(1, draftOf(1, null));
    await act(async () => {
      click(findButton(container, '从初始原稿创建草稿'));
      await Promise.resolve();
    });
    await flush();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/create/', {});
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('来源：初始原稿'));
  });

  it('requires_confirm：只能走高级恢复，确认后按指定原稿重建', async () => {
    mockFetch([makeFile(1, {draft_recovery: {
      source: 'original', requires_confirm: true,
      note: '当前生效版本（v3）不包含该文件的快照'}})]);
    const container = await enterWorkspace();
    store.verifiedPassword = 'pw1';
    // 不得出现"直接创建"入口（不能从原稿静默补齐）
    expect(container.textContent).not.toContain('从初始原稿创建草稿');
    expect(container.textContent).toContain('高级恢复');
    const btn = findButton(container, '从原始上传文件重建草稿');
    expect(btn).not.toBeUndefined();
    await act(async () => {
      click(btn);
      await Promise.resolve();
    });
    await flush();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).not.toBeNull();
    expect(confirm.textContent).toContain('不可撤销');
    http.post.mockResolvedValue({revision: 1});
    const okButton = confirm.querySelector('.ant-btn-primary');
    await act(async () => {
      okButton.click();
      await Promise.resolve();
      await Promise.resolve();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    // 高级恢复按原稿清单首个（最近原稿）重建，confirm + 已验证密码
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/originals/');
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/create/',
      {original_id: 77, confirm: true, password: 'pw1'});
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('已按原始上传文件重建'));
  });
});

describe('草稿工作台（已有草稿守护与失败提示）', () => {
  it('已有草稿：不出现恢复入口，加载过程不自动发起 draft/create', async () => {
    mockFetch([makeFile(1, {draft: draftOf(3, null)})]);
    const container = await enterWorkspace();
    expect(container.textContent).not.toContain('从当前生效版本恢复草稿');
    expect(container.textContent).not.toContain('从初始原稿创建草稿');
    expect(container.textContent).toContain('当前文件：文件1');
    const createCalls = http.post.mock.calls.filter(
      ([url]) => url.includes('draft/create/'));
    expect(createCalls).toHaveLength(0);
    expect(successSpy).not.toHaveBeenCalled();
  });

  it('恢复失败：不显示成功提示（拦截器统一提示一次）', async () => {
    mockFetch([makeFile(1, {draft_recovery: {
      source: 'current_version', version_id: 9, version_no: 3}})]);
    const container = await enterWorkspace();
    http.post.mockRejectedValue('当前版本文件不存在或已被清理，无法恢复草稿');
    await act(async () => {
      click(findButton(container, '从当前生效版本恢复草稿'));
      await Promise.resolve();
    });
    await flush();
    expect(successSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
