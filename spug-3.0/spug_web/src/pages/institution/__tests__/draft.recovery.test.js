/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿恢复行为测试（jsdom + ReactDOM；2026-11-02 两态简化版）：
 * - 无草稿文件不渲染空白编辑器，恢复途径由服务端 draft_recovery 权威决定。
 * - source='current_version'：提示当前生效版本 vN 可恢复，按钮
 *   「从当前生效版本恢复草稿」，空体 POST draft/create；成功提示带新修订号
 *   与来源版本（「草稿已恢复（修订号 rN，来源版本 vN）」）。
 * - source='none'（或字段缺失）：仅警示「该文件没有可恢复的发布快照。
 *   请重新上传制度文件建立草稿（已有历史版本时，可先在「版本与发布」中
 *   回退重建草稿）」，**不显示任何恢复/重建按钮**，也不发任何 draft/create。
 * - 已有草稿：不出现恢复入口，也不自动发起任何 draft/create（不覆盖草稿）。
 * - 恢复失败：不显示成功提示（错误由拦截器提示一次）。
 * - 历史来源/高级恢复/更换来源能力已整体删除：界面不出现任何相关入口。
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
    draft: null,
    active_session: null,
  }, overrides);
}

function mockFetch(files, manual) {
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({editor_available: false});
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
    base_version_no: baseVersionNo,
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
    // 界面不再出现任何历史来源/高级恢复类入口
    expect(container.textContent).not.toContain('高级恢复');
    expect(container.textContent).not.toContain('原稿');
    expect(container.textContent).not.toContain('更换来源');
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
    // 空体请求：能否恢复、从哪个版本恢复由后端权威决定
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/create/', {});
    expect(http.post.mock.calls.filter(
      ([url]) => url.includes('draft/create/'))).toHaveLength(1);
    expect(successSpy).toHaveBeenCalledWith(
      '草稿已恢复（修订号 r2，来源版本 v3）');
  });
});

describe('草稿工作台（无可恢复发布快照：仅提示重新上传）', () => {
  it('source=none：明确提示重新上传/先回退，且不显示任何恢复/重建按钮', async () => {
    mockFetch([makeFile(1, {draft_recovery: {
      source: 'none', requires_reupload: true,
      note: '该文件没有可恢复的发布快照，请重新上传制度文件建立草稿'}})]);
    const container = await enterWorkspace();
    expect(container.textContent)
      .toContain('该文件没有可恢复的发布快照。请重新上传制度文件建立草稿');
    expect(container.textContent).toContain('「版本与发布」中回退重建草稿');
    // 恢复面板内不得渲染任何按钮（无恢复/重建入口）
    expect(container.querySelectorAll('.ant-alert button')).toHaveLength(0);
    expect(findButton(container, '从当前生效版本恢复草稿')).toBeUndefined();
    expect(findButton(container, '重建草稿')).toBeUndefined();
    expect(container.textContent).not.toContain('高级恢复');
    expect(container.textContent).not.toContain('从初始原稿');
    // 不会发任何恢复请求
    expect(http.post).not.toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
  });

  it('draft_recovery 字段缺失同样按无可恢复快照处理（只提示，无按钮）', async () => {
    mockFetch([makeFile(1)]);
    const container = await enterWorkspace();
    expect(container.textContent).toContain('该文件没有可恢复的发布快照');
    expect(container.querySelectorAll('.ant-alert button')).toHaveLength(0);
    expect(http.post).not.toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
  });
});

describe('草稿工作台（已有草稿守护与失败提示）', () => {
  it('已有草稿：不出现恢复入口，加载过程不自动发起 draft/create（不覆盖草稿）', async () => {
    mockFetch([makeFile(1, {draft: draftOf(3, null),
      draft_recovery: {source: 'none'}})]);
    const container = await enterWorkspace();
    expect(container.textContent).not.toContain('从当前生效版本恢复草稿');
    expect(container.textContent).not.toContain('该文件没有可恢复的发布快照');
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
